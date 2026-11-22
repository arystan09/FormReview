import uuid
from typing import Any, Literal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email
from django.db import transaction
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from accounts.models import Membership
from documents.models import Document, TextVersion
from extraction.evidence import anchor
from extraction.models import FieldCandidate
from extraction.normalization import normalize
from extraction.schemas import FIELD_NAMES
from extraction.services import reviewer_for_document
from reviews.models import ReviewDraft, ReviewEvent


class ReviewConflict(ValueError):
    pass


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["accept", "edit", "missing"]
    candidate_id: StrictInt | None
    value: StrictStr | StrictInt | None
    reason: str = Field(max_length=1000)
    provenance: str = Field(max_length=500)


def resolve_decisions(
    draft: ReviewDraft, decisions: object
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(decisions, dict) or set(decisions) != set(FIELD_NAMES):
        raise ReviewConflict("exactly_five_decisions_required")
    values: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for name in FIELD_NAMES:
        try:
            decision = Decision.model_validate(decisions[name])
        except ValidationError:
            raise ReviewConflict(f"{name}:invalid_decision") from None
        for item in (decision.value, decision.reason, decision.provenance):
            if isinstance(item, str) and (
                "\x00" in item or any(0xD800 <= ord(c) <= 0xDFFF for c in item)
            ):
                raise ReviewConflict(f"{name}:invalid_text")
        if decision.action == "accept":
            if draft.run_id is None or decision.candidate_id is None or decision.value is not None:
                raise ReviewConflict(f"{name}:candidate_required")
            candidate = FieldCandidate.objects.filter(
                pk=decision.candidate_id, run_id=draft.run_id, field=name
            ).first()
            if candidate is None:
                raise ReviewConflict(f"{name}:candidate_not_in_bound_run")
            evidence = anchor(
                draft.text_version.pages, candidate.page, candidate.quote, candidate.value_text
            )
            value, flags = normalize(name, candidate.value_text)
            if candidate.flags or evidence.flags or flags or value is None:
                raise ReviewConflict(f"{name}:unsupported_candidate_requires_manual_edit")
            provenance[name] = {
                "kind": "source_candidate",
                "candidate_id": candidate.pk,
                "page": candidate.page,
                "quote": candidate.quote,
                "quote_start": evidence.quote_start,
                "quote_end": evidence.quote_end,
            }
        elif decision.action == "edit":
            if (
                decision.candidate_id is not None
                or decision.value is None
                or not decision.reason.strip()
                or not decision.provenance.strip()
            ):
                raise ReviewConflict(f"{name}:manual_value_reason_and_provenance_required")
            value = decision.value
            provenance[name] = {
                "kind": "manual_edit",
                "reason": decision.reason,
                "provenance": decision.provenance,
            }
        else:
            if (
                decision.value is not None
                or decision.candidate_id is not None
                or not decision.reason.strip()
            ):
                raise ReviewConflict(f"{name}:missing_reason_required")
            value = None
            provenance[name] = {"kind": "reviewer_missing", "reason": decision.reason}
        if value is None:
            if name in {"supplier_name", "contact_email"}:
                raise ReviewConflict(f"{name}:required_for_approval")
        elif name == "payment_terms_days":
            if type(value) is not int or not 0 <= value <= 365:
                raise ReviewConflict(f"{name}:integer_0_to_365_required")
        elif not isinstance(value, str) or not value.strip() or len(value) > 256:
            raise ReviewConflict(f"{name}:nonblank_text_required")
        if name == "contact_email":
            if not isinstance(value, str):
                raise ReviewConflict("contact_email:required_for_approval")
            try:
                validate_email(value)
            except DjangoValidationError:
                raise ReviewConflict("contact_email:invalid_email") from None
        values[name] = value
    return values, provenance


def lock_draft(membership: Membership, draft_id: uuid.UUID | str) -> ReviewDraft:
    reference = ReviewDraft.objects.get(pk=draft_id, document__workspace_id=membership.workspace_id)
    document = Document.objects.select_for_update().get(pk=reference.document_id)
    draft = ReviewDraft.objects.select_for_update().get(pk=draft_id, document=document)
    reviewer_for_document(membership, document)
    if draft.text_version.document_id != document.id or (
        draft.run is not None and draft.run.text_version_id != draft.text_version_id
    ):
        raise ReviewConflict("draft_binding_mismatch")
    return draft


@transaction.atomic
def save_decisions(
    membership: Membership, draft_id: uuid.UUID | str, expected_revision: int, decisions: object
) -> ReviewDraft:
    draft = lock_draft(membership, draft_id)
    if draft.status != "active" or draft.revision != expected_revision:
        raise ReviewConflict("stale_or_closed_draft")
    resolve_decisions(draft, decisions)
    draft.decisions = decisions
    draft.revision += 1
    draft.save(update_fields=["decisions", "revision"])
    ReviewEvent.objects.create(
        draft=draft,
        actor_id=membership.user_id,
        action="saved",
        revision=draft.revision,
        decisions=draft.decisions,
    )
    return draft


@transaction.atomic
def manual_draft(
    membership: Membership, document_id: uuid.UUID, expected_revision: int
) -> ReviewDraft:
    document = Document.objects.select_for_update().get(
        pk=document_id, workspace_id=membership.workspace_id
    )
    reviewer_for_document(membership, document)
    if expected_revision != 0 or ReviewDraft.objects.filter(document=document).exists():
        raise ReviewConflict("draft_already_exists_or_revision_conflict")
    text = TextVersion.objects.filter(document=document).first()
    if text is None:
        raise ReviewConflict("canonical_source_required")
    return ReviewDraft.objects.create(document=document, text_version=text, mode="manual", run=None)
