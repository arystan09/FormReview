from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from accounts.models import Membership


@login_required
@require_http_methods(["GET", "POST"])
def select_workspace(request: HttpRequest) -> HttpResponse:
    assert request.user.pk is not None
    memberships = Membership.objects.filter(user_id=request.user.pk).select_related("workspace")
    if request.method == "POST":
        try:
            membership_id = int(request.POST.get("membership", ""))
        except ValueError:
            raise Http404("Membership not found") from None
        membership = get_object_or_404(memberships, pk=membership_id)
        request.session["workspace_id"] = str(membership.workspace_id)
        return redirect("inbox")
    return render(request, "registration/workspaces.html", {"memberships": memberships})
