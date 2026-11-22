import uuid

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from accounts.access import active_membership
from documents.models import Document
from extraction.live import confirmation
from extraction.models import LiveAttempt
from extraction.services import ReplayConflict


@require_GET
def live_confirmation(request: HttpRequest, document_id: uuid.UUID) -> HttpResponse:
    membership = active_membership(request, reviewer=True)
    document = get_object_or_404(Document, pk=document_id, workspace_id=membership.workspace_id)
    try:
        context = confirmation(document)
    except ReplayConflict as error:
        return JsonResponse({"error": str(error)}, status=409)
    return render(request, "extraction/live_confirm.html", {**context, "document": document})


@require_GET
def attempt_view(request: HttpRequest, attempt_id: uuid.UUID) -> HttpResponse:
    membership = active_membership(request)
    attempt = get_object_or_404(
        LiveAttempt, pk=attempt_id, text_version__document__workspace_id=membership.workspace_id
    )
    return render(request, "extraction/live_attempt.html", {"attempt": attempt})
