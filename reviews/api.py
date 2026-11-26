import json
import uuid

from django.db import IntegrityError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from accounts.access import active_membership
from extraction.config import digest
from extraction.services import ReplayConflict
from reviews.approval import approve
from reviews.models import ApprovedRecord, ReviewDraft
from reviews.presentation import review_rows, validation_errors
from reviews.services import ReviewConflict, resolve_decisions, save_decisions


def owned_draft(request: HttpRequest, draft_id: uuid.UUID) -> ReviewDraft:
    membership = active_membership(request)
    return get_object_or_404(
        ReviewDraft.objects.select_related("document", "text_version", "run"),
        pk=draft_id,
        document__workspace_id=membership.workspace_id,
    )


@require_http_methods(["GET", "PATCH"])
def patch_draft(request: HttpRequest, draft_id: uuid.UUID) -> HttpResponse:
    if request.method == "GET":
        draft = owned_draft(request, draft_id)
        return JsonResponse(
            {
                "id": str(draft.id),
                "revision": draft.revision,
                "status": draft.status,
                "decisions": draft.decisions,
                "candidate_values": {
                    name: candidate.value_text
                    for name, decision in draft.decisions.items()
                    if decision.get("action") == "accept"
                    for candidate in (
                        draft.run.candidates.filter(pk=decision.get("candidate_id"), field=name)
                        if draft.run
                        else []
                    )
                },
            }
        )
    membership = active_membership(request, reviewer=True)
    owned_draft(request, draft_id)
    try:
        data = json.loads(request.body)
        if (
            not isinstance(data, dict)
            or set(data)
            not in (
                {"expected_revision", "decisions"},
                {"expected_revision", "decisions", "partial"},
            )
            or type(data.get("partial", False)) is not bool
            or type(data["expected_revision"]) is not int
        ):
            raise ValueError
    except (ValueError, TypeError, RecursionError):
        return JsonResponse({"error": "expected_revision_and_five_decisions_required"}, status=400)
    try:
        draft = save_decisions(
            membership,
            draft_id,
            data["expected_revision"],
            data["decisions"],
            partial=data.get("partial", False),
        )
    except (ReviewConflict, ReplayConflict) as error:
        return JsonResponse({"error": str(error)}, status=409)
    return JsonResponse(
        {
            "id": str(draft.id),
            "revision": draft.revision,
            "decisions_hash": digest(draft.decisions),
            "confirmation_url": f"/drafts/{draft.id}/confirm",
            "validation_errors": validation_errors(draft),
        }
    )


@require_GET
def edit(request: HttpRequest, draft_id: uuid.UUID) -> HttpResponse:
    draft = owned_draft(request, draft_id)
    return render(
        request,
        "reviews/edit.html",
        {
            "draft": draft,
            "rows": review_rows(draft),
            "source_pages": draft.text_version.pages,
            "active_draft": ReviewDraft.objects.filter(
                document=draft.document, status="active"
            ).first(),
            "can_write": active_membership(request).role == "reviewer" and draft.status == "active",
        },
    )


@require_GET
def confirm(request: HttpRequest, draft_id: uuid.UUID) -> HttpResponse:
    active_membership(request, reviewer=True)
    draft = owned_draft(request, draft_id)
    try:
        fields, provenance = resolve_decisions(draft, draft.decisions)
    except ReviewConflict as error:
        return JsonResponse({"error": str(error)}, status=409)
    if draft.status != "active":
        return JsonResponse({"error": "draft_closed"}, status=409)
    return render(
        request,
        "reviews/confirm.html",
        {
            "draft": draft,
            "fields": fields,
            "provenance": provenance,
            "decisions_hash": digest(draft.decisions),
            "idempotency_key": uuid.uuid4(),
        },
    )


@require_POST
def approve_endpoint(request: HttpRequest, draft_id: uuid.UUID) -> HttpResponse:
    membership = active_membership(request, reviewer=True)
    owned_draft(request, draft_id)
    try:
        expected = int(request.POST.get("expected_revision", ""))
        key = uuid.UUID(request.POST.get("idempotency_key", ""))
    except ValueError:
        return JsonResponse({"error": "revision_and_idempotency_key_required"}, status=400)
    try:
        receipt = approve(
            membership,
            draft_id,
            expected,
            request.POST.get("decisions_hash", ""),
            key,
            request.POST.get("confirmed") == "yes",
        )
    except (ReviewConflict, ReplayConflict) as error:
        if request.POST.get("preview") == "yes":
            return render(
                request,
                "reviews/conflict.html",
                {"draft_id": draft_id, "error": str(error)},
                status=409,
            )
        return JsonResponse({"error": str(error)}, status=409)
    except IntegrityError:
        return JsonResponse({"error": "approval_or_idempotency_conflict"}, status=409)
    if request.POST.get("preview") == "yes":
        response = HttpResponse(status=303)
        response["Location"] = f"/records/{receipt.record_id}"
        return response
    return JsonResponse(
        {
            "receipt_id": str(receipt.id),
            "record_id": str(receipt.record_id),
            "record_url": f"/records/{receipt.record_id}",
        }
    )


def owned_record(request: HttpRequest, record_id: uuid.UUID) -> ApprovedRecord:
    membership = active_membership(request)
    return get_object_or_404(
        ApprovedRecord, pk=record_id, document__workspace_id=membership.workspace_id
    )


@require_GET
def record(request: HttpRequest, record_id: uuid.UUID) -> HttpResponse:
    approved = owned_record(request, record_id)
    rows = [
        {
            "name": name,
            "value": value,
            "provenance": approved.snapshot.get("provenance", {}).get(name, {}),
        }
        for name, value in approved.fields.items()
    ]
    return render(request, "reviews/record.html", {"record": approved, "rows": rows})


@require_GET
def export(request: HttpRequest, record_id: uuid.UUID) -> HttpResponse:
    record = owned_record(request, record_id)
    response = JsonResponse(
        {
            "id": str(record.id),
            "fields": record.fields,
            "snapshot": record.snapshot,
            "snapshot_hash": record.snapshot_hash,
            "approved_at": record.created_at.isoformat(),
        }
    )
    response["Content-Disposition"] = f'attachment; filename="formreview-{record.id}.json"'
    return response
