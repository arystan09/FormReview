from collections.abc import Callable

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadhandler import FileUploadHandler, StopUpload
from django.http import HttpRequest, HttpResponse, JsonResponse

from accounts.access import active_membership
from documents.storage import MAX_BYTES


class BoundedUploadHandler(FileUploadHandler):
    chunk_size = 65536

    def __init__(self, request: HttpRequest) -> None:
        super().__init__(request)
        self.received = 0
        self.upload_request = request

    def receive_data_chunk(self, raw_data: bytes, start: int) -> bytes:
        self.received += len(raw_data)
        if self.received > MAX_BYTES:
            self.upload_request.META["FORMREVIEW_UPLOAD_LIMIT_EXCEEDED"] = True
            raise StopUpload(connection_reset=True)
        return raw_data

    def file_complete(self, file_size: int) -> None:
        return None


class UploadAdmissionMiddleware:
    """Reject unauthorized/oversized upload bodies before CSRF parses multipart data."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if (
            settings.PUBLIC_DEMO
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and request.path not in {"/accounts/login", "/accounts/logout", "/accounts/workspaces"}
        ):
            return JsonResponse({"error": "public_demo_read_only"}, status=403)
        if request.path == "/api/v1/documents" and request.method == "POST":
            try:
                active_membership(request, reviewer=True)
            except PermissionDenied:
                return JsonResponse({"error": "reviewer_membership_required"}, status=403)
            try:
                length = int(request.META.get("CONTENT_LENGTH", ""))
            except ValueError:
                return JsonResponse({"error": "content_length_required"}, status=411)
            if not 0 < length <= MAX_BYTES + 65536:
                return JsonResponse({"error": "request_too_large"}, status=413)
            if request.content_type != "multipart/form-data":
                return JsonResponse({"error": "multipart_required"}, status=415)
            request.upload_handlers = [BoundedUploadHandler(request), *request.upload_handlers]
        elif request.method in {"POST", "PUT", "PATCH"}:
            try:
                length = int(request.META.get("CONTENT_LENGTH") or "0")
            except ValueError:
                return JsonResponse({"error": "invalid_content_length"}, status=400)
            if length < 0 or length > 65536:
                return JsonResponse({"error": "request_too_large"}, status=413)
        response = self.get_response(request)
        if request.META.get("FORMREVIEW_UPLOAD_LIMIT_EXCEEDED", False):
            return JsonResponse({"error": "file_too_large"}, status=413)
        if request.user.is_authenticated:
            response["Cache-Control"] = "no-store"
        return response
