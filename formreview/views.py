from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET


@require_GET
def liveness(request: HttpRequest) -> JsonResponse:
    """Report process liveness without database access or configuration disclosure."""
    return JsonResponse({"status": "ok"})
