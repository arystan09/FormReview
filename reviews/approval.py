import uuid

from django.db import transaction

from accounts.models import Membership
from extraction.config import digest, executable_config
from reviews.models import ApprovalReceipt, ApprovedRecord, ReviewEvent
from reviews.services import ReviewConflict, lock_draft, resolve_decisions


@transaction.atomic
def approve(
    membership: Membership,
    draft_id: uuid.UUID | str,
    expected_revision: int,
    decisions_hash: str,
    idempotency_key: uuid.UUID,
    confirmed: bool,
) -> ApprovalReceipt:
    if not confirmed:
        raise ReviewConflict("human_confirmation_required")
    draft = lock_draft(membership, draft_id)
    request_hash = digest(
        {
            "draft_id": str(draft.id),
            "expected_revision": expected_revision,
            "decisions_hash": decisions_hash,
            "actor_id": membership.user_id,
        }
    )
    receipt = ApprovalReceipt.objects.filter(
        workspace_id=membership.workspace_id, idempotency_key=idempotency_key
    ).first()
    if receipt:
        if receipt.request_hash != request_hash:
            raise ReviewConflict("idempotency_mismatch")
        return receipt
    if (
        draft.status != "active"
        or draft.revision != expected_revision
        or decisions_hash != digest(draft.decisions)
    ):
        raise ReviewConflict("stale_or_closed_draft")
    if ApprovedRecord.objects.filter(document_id=draft.document_id).exists():
        raise ReviewConflict("document_already_approved")
    fields, provenance = resolve_decisions(draft, draft.decisions)
    run = draft.run
    snapshot = {
        "mode": draft.mode,
        "draft_id": str(draft.id),
        "revision": draft.revision,
        "actor_id": membership.user_id,
        "decisions": draft.decisions,
        "provenance": provenance,
        "document_id": str(draft.document_id),
        "raw_sha256": draft.document.raw_sha256,
        "text_version_id": draft.text_version_id,
        "canonical_sha256": draft.text_version.canonical_sha256,
        "parser_version": draft.text_version.parser_version,
        "source_normalization_version": draft.text_version.normalization_version,
        "run_id": str(run.id) if run else None,
        "config_hash": run.config_hash if run else None,
        "config": executable_config(run.config) if run else None,
        "response_sha256": run.response_sha256 if run else None,
        "request_hash": run.request_hash if run else None,
        "notice": (
            "Human-approved values. Source membership is not verification of supplier claims."
        ),
    }
    record = ApprovedRecord.objects.create(
        document=draft.document,
        draft=draft,
        approved_by_id=membership.user_id,
        fields=fields,
        snapshot=snapshot,
        snapshot_hash=digest({"fields": fields, "snapshot": snapshot}),
    )
    receipt = ApprovalReceipt.objects.create(
        workspace_id=membership.workspace_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        record=record,
    )
    draft.status = "approved"
    draft.save(update_fields=["status"])
    ReviewEvent.objects.create(
        draft=draft,
        actor_id=membership.user_id,
        action="approved",
        revision=draft.revision,
        decisions=draft.decisions,
    )
    return receipt
