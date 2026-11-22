import uuid
from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_POST

from accounts.access import active_membership
from documents.models import Document
from extraction.models import ExtractionRun
from extraction.schemas import FIELD_NAMES
from extraction.services import ReplayConflict, create_draft, run_replay
from reviews.models import ReviewDraft


def owned_run(request: HttpRequest, run_id: uuid.UUID) -> ExtractionRun:
    membership = active_membership(request)
    return get_object_or_404(
        ExtractionRun.objects.select_related("text_version__document", "config"),
        pk=run_id,
        text_version__document__workspace_id=membership.workspace_id,
    )


@require_POST
def extract(request: HttpRequest, document_id: uuid.UUID) -> HttpResponse:
    membership = active_membership(request, reviewer=True)
    get_object_or_404(Document, pk=document_id, workspace_id=membership.workspace_id)
    if request.POST.get("mode") == "live":
        from extraction.live import admit

        try:
            attempt = admit(
                membership,
                document_id,
                request.POST.get("confirmation_token", ""),
                request.POST.get("paid_confirmed") == "yes",
            )
        except ReplayConflict as error:
            return JsonResponse({"error": str(error)}, status=409)
        if request.POST.get("preview") == "yes":
            response = HttpResponse(status=303)
            response["Location"] = f"/live-attempts/{attempt.id}"
            return response
        return JsonResponse({"attempt_id": str(attempt.id), "status": attempt.status}, status=202)
    if request.POST.get("mode") != "replay":
        return JsonResponse({"error": "explicit_replay_mode_required"}, status=400)
    try:
        run = run_replay(membership, document_id)
    except ReplayConflict as error:
        return JsonResponse({"error": str(error)}, status=409)
    if request.POST.get("preview") == "yes":
        response = HttpResponse(status=303)
        response["Location"] = f"/extractions/{run.id}"
        return response
    return JsonResponse(
        {
            "id": str(run.id),
            "mode": run.mode,
            "status": run.status,
            "preview_url": f"/extractions/{run.id}",
        },
        status=201,
    )


@require_GET
def extraction_json(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    run = owned_run(request, run_id)
    candidates = list(
        run.candidates.order_by("field", "position").values(
            "id",
            "field",
            "position",
            "value_text",
            "quote",
            "page",
            "quote_start",
            "quote_end",
            "value_start",
            "value_end",
            "normalized_value",
            "flags",
        )
    )
    return JsonResponse(
        {
            "id": str(run.id),
            "mode": run.mode,
            "notice": ("Source mode is explicit. Quote membership is not semantic truth."),
            "status": run.status,
            "error_code": run.error_code,
            "text_version_id": run.text_version_id,
            "canonical_sha256": run.canonical_sha256,
            "config_id": str(run.config_id),
            "config_hash": run.config_hash,
            "request_hash": run.request_hash,
            "schema_version": run.config.schema_version,
            "normalizer_version": run.config.normalizer_version,
            "evidence_version": run.config.evidence_version,
            "fields": run.output,
            "field_flags": run.field_flags,
            "candidates": candidates,
        }
    )


def preview_context(run: ExtractionRun) -> dict[str, Any]:
    fields = []
    for name in FIELD_NAMES:
        candidates = []
        for candidate in run.candidates.filter(field=name).order_by("position"):
            highlight = None
            if candidate.quote_start is not None and candidate.quote_end is not None:
                page_text = run.text_version.pages[candidate.page - 1]
                # All segments remain template-escaped. Offsets are Python Unicode code points.
                highlight = {
                    "before": page_text[: candidate.quote_start],
                    "quote": page_text[candidate.quote_start : candidate.quote_end],
                    "after": page_text[candidate.quote_end :],
                }
            candidates.append({"candidate": candidate, "highlight": highlight})
        fields.append(
            {
                "name": name,
                "status": run.output.get(name, {}).get("status", "unavailable"),
                "flags": run.field_flags.get(name, []),
                "candidates": candidates,
            }
        )
    return {
        "run": run,
        "fields": fields,
        "document": run.text_version.document,
        "existing_draft": ReviewDraft.objects.filter(document=run.text_version.document).first(),
    }


@require_GET
def preview(request: HttpRequest, run_id: uuid.UUID) -> HttpResponse:
    run = owned_run(request, run_id)
    context = preview_context(run)
    context["can_write"] = active_membership(request).role == "reviewer"
    return render(request, "extraction/preview.html", context)


@require_POST
def draft_create(request: HttpRequest, document_id: uuid.UUID) -> HttpResponse:
    membership = active_membership(request, reviewer=True)
    get_object_or_404(Document, pk=document_id, workspace_id=membership.workspace_id)
    if request.POST.get("mode") == "manual":
        from reviews.services import ReviewConflict, manual_draft

        try:
            draft = manual_draft(
                membership, document_id, int(request.POST.get("expected_revision", ""))
            )
        except (ValueError, ReviewConflict) as error:
            return JsonResponse({"error": str(error)}, status=409)
        response = HttpResponse(status=303)
        response["Location"] = f"/drafts/{draft.id}"
        return response
    try:
        run_id = uuid.UUID(request.POST.get("run_id", ""))
        expected_revision = int(request.POST.get("expected_revision", ""))
    except ValueError:
        return JsonResponse({"error": "run_id_and_expected_revision_required"}, status=400)
    try:
        draft = create_draft(membership, document_id, run_id, expected_revision)
    except ReplayConflict as error:
        return JsonResponse({"error": str(error)}, status=409)
    if request.POST.get("preview") == "yes":
        response = HttpResponse(status=303)
        response["Location"] = f"/drafts/{draft.id}"
        return response
    return JsonResponse(
        {
            "id": str(draft.id),
            "run_id": str(draft.run_id),
            "text_version_id": draft.text_version_id,
            "revision": draft.revision,
            "preview_url": f"/drafts/{draft.id}",
        },
        status=201,
    )
