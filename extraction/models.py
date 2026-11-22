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
            models.CheckConstraint(
                condition=models.Q(mode__in=["replay", "live"]), name="extraction_mode"
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["validated", "invalid_output", "failed"]),
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


class LiveAllowance(models.Model):
    """One installation-wide budget and admission lock, managed by the local owner."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField(default=False)
    config = models.ForeignKey(ExtractionConfig, null=True, on_delete=models.PROTECT)
    key_fingerprint = models.CharField(max_length=64, blank=True)
    request_limit = models.PositiveIntegerField(default=0)
    consumed = models.PositiveIntegerField(default=0)
    version = models.PositiveIntegerField(default=1)
    active_attempt = models.UUIDField(null=True)
    next_admission_at = models.DateTimeField(null=True)
    input_price = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    output_price = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    price_checked_on = models.DateField(null=True)
    price_source = models.URLField(blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(id=1), name="singleton_live_allowance"),
            models.CheckConstraint(
                condition=models.Q(consumed__lte=models.F("request_limit")),
                name="finite_live_allowance",
            ),
        ]


class LiveAttempt(models.Model):
    """Durable one-shot dispatch; submitted attempts are never reclaimed or retried."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    text_version = models.ForeignKey(TextVersion, on_delete=models.PROTECT)
    config = models.ForeignKey(ExtractionConfig, on_delete=models.PROTECT)
    requested_by = models.ForeignKey("auth.User", on_delete=models.PROTECT)
    request_hash = models.CharField(max_length=64)
    allowance_version = models.PositiveIntegerField()
    estimate_usd = models.DecimalField(max_digits=12, decimal_places=6)
    price_snapshot = models.JSONField()
    status = models.CharField(max_length=16, default="queued")
    error_code = models.CharField(max_length=40, blank=True)
    run = models.OneToOneField(ExtractionRun, null=True, on_delete=models.PROTECT)
    provider_request_id = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True)
    finished_at = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    status__in=["queued", "submitted", "done", "unknown", "cancelled"]
                ),
                name="valid_live_attempt_status",
            )
        ]
