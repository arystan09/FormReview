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
from reviews.models import ReviewDraft


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
    output: dict[str, Any] = {}
    field_flags: dict[str, list[str]] = {}
    candidates = []
    error_code = ""
    try:
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
    except (ValidationError, ValueError, TypeError):
        error_code = "invalid_provider_output"
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
        mode="replay",
        config_hash=config.config_hash,
        canonical_sha256=text.canonical_sha256,
        request_hash=request_hash(request),
        replay_fixture=fixture_id,
        response_text=safe_response,
        response_sha256=hashlib.sha256(response_bytes).hexdigest(),
        output=output,
        field_flags=field_flags,
        status="invalid_output" if error_code else "validated",
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
) -> ReviewDraft:
    document = Document.objects.select_for_update().get(
        pk=document_id, workspace_id=membership.workspace_id
    )
    reviewer_for_document(membership, document)
    existing = ReviewDraft.objects.select_for_update().filter(document=document).first()
    if existing is not None:
        if existing.revision != expected_revision:
            raise ReplayConflict("revision_conflict")
        if str(existing.run_id) != str(run_id):
            raise ReplayConflict("draft_already_bound_to_another_run")
        return existing
    if expected_revision != 0:
        raise ReplayConflict("revision_conflict")
    run = ExtractionRun.objects.filter(
        pk=run_id, text_version__document=document, status="validated"
    ).first()
    if run is None:
        raise ReplayConflict("valid_owned_run_required")
    return ReviewDraft.objects.create(document=document, run=run, text_version=run.text_version)
