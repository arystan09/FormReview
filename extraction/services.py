import hashlib
import json
import uuid
from typing import Any

from django.db import transaction
from pydantic import ValidationError

from accounts.models import Membership
from documents.models import Document, TextVersion
from extraction.config import replay_config
from extraction.evidence import anchor
from extraction.models import ExtractionConfig, ExtractionRun, FieldCandidate
from extraction.normalization import normalize
from extraction.providers import build_request, request_hash
from extraction.replay import ReplayProvider
from extraction.schemas import ExtractionOutput
from reviews.models import ApprovedRecord, ReviewDraft, ReviewEvent


class ReplayConflict(ValueError):
    pass


def reviewer_for_document(membership: Membership, document: Document) -> None:
    current = (
        Membership.objects.select_for_update()
        .filter(
            pk=membership.pk,
            workspace_id=document.workspace_id,
            user_id=membership.user_id,
            role="reviewer",
            user__is_active=True,
        )
        .first()
    )
    if current is None:
        raise ReplayConflict("reviewer_membership_required")


def parse_response(response: str) -> ExtractionOutput:
    # JSON decoding must also reject repeated keys, which JSON/Pydantic otherwise collapse.
    def unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    if len(response.encode("utf-8")) > 65536:
        raise ValueError("output_too_large")
    return ExtractionOutput.model_validate(json.loads(response, object_pairs_hook=unique_keys))


@transaction.atomic
def run_replay(
    membership: Membership, document_id: uuid.UUID | str, config: ExtractionConfig | None = None
) -> ExtractionRun:
    document = Document.objects.select_for_update().get(
        pk=document_id, workspace_id=membership.workspace_id
    )
    reviewer_for_document(membership, document)
    text = TextVersion.objects.filter(document=document).first()
    if text is None:
        raise ReplayConflict("canonical_source_required")
    config = config or replay_config()
    try:
        request = build_request(config, text)
        fixture_id, response = ReplayProvider().extract(request)
    except ValueError as error:
        raise ReplayConflict(str(error)) from None
    return persist_result(text, config, "replay", request_hash(request), response, fixture_id)


@transaction.atomic
def persist_result(
    text: TextVersion,
    config: ExtractionConfig,
    mode: str,
    payload_hash: str,
    response: str,
    fixture_id: str = "",
    provider_error: str = "",
) -> ExtractionRun:
    output: dict[str, Any] = {}
    field_flags: dict[str, list[str]] = {}
    candidates = []
    error_code = provider_error
    try:
        if provider_error:
            raise ValueError("provider_failure")
        validated = parse_response(response)
        output = validated.model_dump()
        for name, field in validated.field_results():
            flags: list[str] = [] if field.status == "present" else [field.status]
            for position, candidate in enumerate(field.candidates):
                evidence = anchor(text.pages, candidate.page, candidate.quote, candidate.value_text)
                normalized, normalization_flags = normalize(name, candidate.value_text)
                candidate_flags = list(evidence.flags + normalization_flags)
                flags.extend(candidate_flags)
                candidates.append(
                    FieldCandidate(
                        field=name,
                        position=position,
                        value_text=candidate.value_text,
                        quote=candidate.quote,
                        page=candidate.page,
                        quote_start=evidence.quote_start,
                        quote_end=evidence.quote_end,
                        value_start=evidence.value_start,
                        value_end=evidence.value_end,
                        normalized_value=normalized,
                        flags=candidate_flags,
                    )
                )
            field_flags[name] = sorted(set(flags))
    except (ValidationError, ValueError, TypeError, RecursionError):
        error_code = provider_error or "invalid_provider_output"
    response_bytes = response.encode("utf-8", errors="surrogatepass")
    safe_response = (
        response
        if "\x00" not in response
        and not any(0xD800 <= ord(c) <= 0xDFFF for c in response)
        and len(response_bytes) <= 65536
        else ""
    )
    run = ExtractionRun.objects.create(
        text_version=text,
        config=config,
        mode=mode,
        config_hash=config.config_hash,
        canonical_sha256=text.canonical_sha256,
        request_hash=payload_hash,
        replay_fixture=fixture_id,
        response_text=safe_response,
        response_sha256=hashlib.sha256(response_bytes).hexdigest(),
        output=output,
        field_flags=field_flags,
        status="failed" if provider_error else "invalid_output" if error_code else "validated",
        error_code=error_code,
    )
    if not error_code:
        for stored_candidate in candidates:
            stored_candidate.run = run
        FieldCandidate.objects.bulk_create(candidates)
    return run


@transaction.atomic
def create_draft(
    membership: Membership,
    document_id: uuid.UUID | str,
    run_id: uuid.UUID | str,
    expected_revision: int,
    expected_draft_id: str | None = None,
) -> ReviewDraft:
    document = Document.objects.select_for_update().get(
        pk=document_id, workspace_id=membership.workspace_id
    )
    reviewer_for_document(membership, document)
    if ApprovedRecord.objects.filter(document=document).exists():
        raise ReplayConflict("document_already_approved")
    existing = (
        ReviewDraft.objects.select_for_update().filter(document=document, status="active").first()
    )
    if existing is not None:
        if existing.revision != expected_revision:
            raise ReplayConflict("revision_conflict")
        if str(existing.run_id) == str(run_id):
            return existing
        if expected_draft_id != str(existing.id):
            raise ReplayConflict("explicit_current_draft_selection_required")
    elif expected_revision != 0 or expected_draft_id is not None:
        raise ReplayConflict("revision_conflict")
    run = ExtractionRun.objects.filter(
        pk=run_id, text_version__document=document, status="validated"
    ).first()
    if run is None:
        raise ReplayConflict("valid_owned_run_required")
    if existing is not None:
        existing.status = "superseded"
        existing.revision += 1
        existing.save(update_fields=["status", "revision"])
        ReviewEvent.objects.create(
            draft=existing,
            actor_id=membership.user_id,
            action="superseded",
            revision=existing.revision,
            decisions=existing.decisions,
        )
    draft = ReviewDraft.objects.create(
        document=document, run=run, text_version=run.text_version, mode=run.mode
    )
    if existing is not None:
        ReviewEvent.objects.create(
            draft=draft,
            actor_id=membership.user_id,
            action="selected",
            revision=draft.revision,
            decisions={},
        )
    return draft
