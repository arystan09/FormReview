import uuid

from django.db import models

from documents.models import TextVersion
from extraction.schemas import FIELD_NAMES


class ExtractionConfig(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    prompt_text = models.TextField()
    model = models.CharField(max_length=100)
    settings = models.JSONField()
    response_schema = models.JSONField()
    schema_version = models.CharField(max_length=100)
    normalizer_version = models.CharField(max_length=100)
    evidence_version = models.CharField(max_length=100)
    config_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ExtractionRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    text_version = models.ForeignKey(
        TextVersion, on_delete=models.PROTECT, related_name="extractions"
    )
    config = models.ForeignKey(ExtractionConfig, on_delete=models.PROTECT)
    mode = models.CharField(max_length=10, default="replay")
    config_hash = models.CharField(max_length=64)
    canonical_sha256 = models.CharField(max_length=64)
    request_hash = models.CharField(max_length=64)
    replay_fixture = models.CharField(max_length=100)
    response_text = models.TextField()
    response_sha256 = models.CharField(max_length=64)
    output = models.JSONField()
    field_flags = models.JSONField()
    status = models.CharField(max_length=20)
    error_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(mode="replay"), name="stage3_replay_only"),
            models.CheckConstraint(
                condition=models.Q(status__in=["validated", "invalid_output"]),
                name="valid_extraction_status",
            ),
        ]


class FieldCandidate(models.Model):
    run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT, related_name="candidates")
    field = models.CharField(max_length=30)
    position = models.PositiveSmallIntegerField()
    value_text = models.CharField(max_length=256)
    quote = models.CharField(max_length=500)
    page = models.PositiveSmallIntegerField()
    quote_start = models.PositiveIntegerField(null=True)
    quote_end = models.PositiveIntegerField(null=True)
    value_start = models.PositiveIntegerField(null=True)
    value_end = models.PositiveIntegerField(null=True)
    normalized_value = models.JSONField(null=True)
    flags = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "field", "position"], name="unique_run_candidate"
            ),
            models.CheckConstraint(
                condition=models.Q(field__in=FIELD_NAMES), name="five_candidate_fields"
            ),
            models.CheckConstraint(
                condition=models.Q(position__lte=1), name="candidate_position_limit"
            ),
            models.CheckConstraint(
                condition=models.Q(page__gte=1, page__lte=5), name="candidate_page_limit"
            ),
        ]
