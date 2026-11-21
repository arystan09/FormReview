from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest

from accounts.models import Membership


def active_membership(request: HttpRequest, *, reviewer: bool = False) -> Membership:
    if not request.user.is_authenticated:
        raise PermissionDenied("Sign in required.")
    workspace_id = request.session.get("workspace_id")
    if not isinstance(workspace_id, str):
        raise PermissionDenied("Select a workspace you belong to.")
    try:
        membership = Membership.objects.get(user=request.user, workspace_id=workspace_id)
    except (Membership.DoesNotExist, ValidationError, ValueError) as error:
        raise PermissionDenied("Select a workspace you belong to.") from error
    if reviewer and membership.role != Membership.Role.REVIEWER:
        raise PermissionDenied("Reviewer membership required.")
    return membership
