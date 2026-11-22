from typing import BinaryIO, cast

from django.core.files.uploadedfile import UploadedFile
from django.db import connection
from django.db.utils import DatabaseError
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from accounts.access import active_membership
from documents.models import Document, TextVersion
from documents.services import upload_document
from documents.storage import UploadRejected
from extraction.models import LiveAttempt
from reviews.models import ApprovedRecord, ReviewDraft


def owned_document(request: HttpRequest, document_id: object) -> Document:
    membership = active_membership(request)
    return get_object_or_404(Document, pk=document_id, workspace_id=membership.workspace_id)


@require_http_methods(["GET", "POST"])
def documents_api(request: HttpRequest) -> HttpResponse:
    membership = active_membership(request, reviewer=request.method == "POST")
    if request.method == "GET":
        documents = (
            Document.objects.filter(workspace_id=membership.workspace_id)
            .select_related("parse_job")
            .order_by("-created_at")[:100]
        )
        return JsonResponse(
            {
                "documents": [
                    {"id": str(doc.id), "filename": doc.filename, "status": doc.parse_job.status}
                    for doc in documents
                ]
            }
        )
    if request.META.get("FORMREVIEW_UPLOAD_LIMIT_EXCEEDED", False):
        return JsonResponse({"error": "file_too_large"}, status=413)
    if set(request.FILES) != {"file"} or len(request.FILES.getlist("file")) != 1:
        return JsonResponse({"error": "one_file_required"}, status=400)
    upload = request.FILES["file"]
    if not isinstance(upload, UploadedFile) or not upload.name:
        return JsonResponse({"error": "one_file_required"}, status=400)
    try:
        document = upload_document(membership, upload.name, cast(BinaryIO, upload.file))
    except UploadRejected as error:
        return JsonResponse(
            {"error": str(error)}, status=413 if str(error) == "file_too_large" else 400
        )
    if request.POST.get("return_to_source") == "yes":
        response = HttpResponse(status=303)
        response["Location"] = f"/documents/{document.id}"
        return response
    return JsonResponse(
        {"id": str(document.id), "status": "queued", "source_url": f"/documents/{document.id}"},
        status=202,
    )


@require_GET
def inbox(request: HttpRequest) -> HttpResponse:
    membership = active_membership(request)
    documents = (
        Document.objects.filter(workspace_id=membership.workspace_id)
        .select_related("parse_job")
        .order_by("-created_at")[:100]
    )
    return render(
        request, "documents/inbox.html", {"membership": membership, "documents": documents}
    )


@require_GET
def source(request: HttpRequest, document_id: object) -> HttpResponse:
    document = owned_document(request, document_id)
    text = TextVersion.objects.filter(document=document).first()
    return render(
        request,
        "documents/source.html",
        {
            "document": document,
            "text": text,
            "job": document.parse_job,
            "can_extract": active_membership(request).role == "reviewer",
            "review_draft": ReviewDraft.objects.filter(document=document).first(),
            "approved_record": ApprovedRecord.objects.filter(document=document).first(),
            "live_attempts": LiveAttempt.objects.filter(text_version__document=document).order_by(
                "-created_at"
            ),
        },
    )


@require_GET
def source_text(request: HttpRequest, document_id: object) -> HttpResponse:
    document = owned_document(request, document_id)
    text = get_object_or_404(TextVersion, document=document)
    return JsonResponse(
        {
            "document_id": str(document.id),
            "pages": text.pages,
            "raw_sha256": document.raw_sha256,
            "canonical_sha256": text.canonical_sha256,
            "parser_version": text.parser_version,
            "normalization_version": text.normalization_version,
        }
    )


@require_GET
def readiness(request: HttpRequest) -> HttpResponse:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_encoding")
            if cursor.fetchone() != ("UTF8",):
                return JsonResponse({"status": "not_ready"}, status=503)
            cursor.execute("SELECT 1 FROM documents_job LIMIT 1")
    except DatabaseError:
        return JsonResponse({"status": "not_ready"}, status=503)
    return JsonResponse({"status": "ready"})
