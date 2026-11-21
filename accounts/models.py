import uuid

from django.conf import settings
from django.db import models


class Workspace(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)


class Membership(models.Model):
    class Role(models.TextChoices):
        VIEWER = "viewer"
        REVIEWER = "reviewer"

    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=8, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="unique_workspace_member"),
            models.CheckConstraint(
                condition=models.Q(role__in=["viewer", "reviewer"]), name="valid_membership_role"
            ),
        ]
