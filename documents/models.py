import uuid

from django.db import models

from accounts.models import Workspace


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workspace = models.ForeignKey(Workspace, on_delete=models.PROTECT)
    filename = models.CharField(max_length=120)
    kind = models.CharField(max_length=3, choices=[("txt", "TXT"), ("pdf", "PDF")])
    raw_sha256 = models.CharField(max_length=64)
    byte_size = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(byte_size__gt=0, byte_size__lte=5 * 1024 * 1024),
                name="document_byte_limit",
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["txt", "pdf"]), name="document_kind"
            ),
        ]


class TextVersion(models.Model):
    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name="text_version")
    pages = models.JSONField()
    canonical_sha256 = models.CharField(max_length=64)
    parser_version = models.CharField(max_length=100)
    normalization_version = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name="parse_job")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    error_code = models.CharField(max_length=40, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    lease_token = models.UUIDField(null=True)
    lease_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status", "lease_until"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["queued", "running", "succeeded", "failed"]),
                name="valid_parse_status",
            )
        ]
