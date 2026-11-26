import uuid

from django.db import models

from documents.models import Document, TextVersion
from extraction.models import ExtractionRun


class ReviewDraft(models.Model):
    """Explicit source/run binding and revisioned human decisions."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="review_drafts")
    run = models.ForeignKey(ExtractionRun, null=True, on_delete=models.PROTECT)
    text_version = models.ForeignKey(TextVersion, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    decisions = models.JSONField(default=dict)
    status = models.CharField(max_length=10, default="active")
    mode = models.CharField(max_length=10, default="replay")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["document"],
                condition=models.Q(status="active"),
                name="one_active_review_draft",
            ),
            models.CheckConstraint(
                condition=models.Q(revision__gte=1), name="positive_draft_revision"
            ),
        ]


class ReviewEvent(models.Model):
    draft = models.ForeignKey(ReviewDraft, on_delete=models.PROTECT)
    actor = models.ForeignKey("auth.User", on_delete=models.PROTECT)
    action = models.CharField(max_length=12)
    revision = models.PositiveIntegerField()
    decisions = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)


class ApprovedRecord(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(Document, on_delete=models.PROTECT)
    draft = models.OneToOneField(ReviewDraft, on_delete=models.PROTECT)
    approved_by = models.ForeignKey("auth.User", on_delete=models.PROTECT)
    fields = models.JSONField()
    snapshot = models.JSONField()
    snapshot_hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)


class ApprovalReceipt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey("accounts.Workspace", on_delete=models.PROTECT)
    idempotency_key = models.UUIDField()
    request_hash = models.CharField(max_length=64)
    record = models.OneToOneField(ApprovedRecord, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "idempotency_key"], name="unique_approval_key"
            )
        ]
