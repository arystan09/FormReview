import uuid

from django.db import models

from documents.models import Document, TextVersion
from extraction.models import ExtractionRun


class ReviewDraft(models.Model):
    """An explicit initial source/run binding; editing and approval belong to stage 4."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name="review_draft")
    run = models.ForeignKey(ExtractionRun, on_delete=models.PROTECT)
    text_version = models.ForeignKey(TextVersion, on_delete=models.PROTECT)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(revision__gte=1), name="positive_draft_revision"
            )
        ]
