from pathlib import Path

from django.http import HttpRequest, HttpResponse
from django.views.decorators.http import require_GET

ROOT = Path(__file__).parent / "static" / "reviews"


@require_GET
def javascript(request: HttpRequest) -> HttpResponse:
    return HttpResponse((ROOT / "review.js").read_bytes(), content_type="text/javascript")


@require_GET
def stylesheet(request: HttpRequest) -> HttpResponse:
    return HttpResponse((ROOT / "review.css").read_bytes(), content_type="text/css")
