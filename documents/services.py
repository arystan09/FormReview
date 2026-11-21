import uuid
from datetime import timedelta
from typing import BinaryIO

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from accounts.models import Membership
from documents.models import Document, Job, TextVersion
from documents.parser import NORMALIZATION_VERSION, ParseRejected, parse_original
from documents.storage import UploadRejected, artifact_path, safe_filename, store_original


def upload_document(membership: Membership, filename: str, source: BinaryIO) -> Document:
    if membership.role != Membership.Role.REVIEWER:
        raise UploadRejected("reviewer_required")
    kind = filename.rsplit(".", 1)[-1].lower()
    if kind not in {"txt", "pdf"}:
        raise UploadRejected("unsupported_type")
    document_id = uuid.uuid4()
    raw_hash, size = store_original(source, membership.workspace_id, document_id)
    try:
        with transaction.atomic():
            # Recheck authority under a lock, including revocations since request admission.
            current = Membership.objects.select_for_update().filter(pk=membership.pk).first()
            if (
                current is None
                or current.role != Membership.Role.REVIEWER
                or current.workspace_id != membership.workspace_id
            ):
                raise UploadRejected("reviewer_required")
            document = Document.objects.create(
                id=document_id,
                workspace_id=current.workspace_id,
                filename=safe_filename(filename),
                kind=kind,
                raw_sha256=raw_hash,
                byte_size=size,
            )
            Job.objects.create(document=document)
        return document
    except BaseException:
        artifact_path(membership.workspace_id, document_id).unlink(missing_ok=True)
        raise


def process_one_job() -> bool:
    now = timezone.now()
    with transaction.atomic():
        job = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(Q(status=Job.Status.QUEUED) | Q(status=Job.Status.RUNNING, lease_until__lt=now))
            .order_by("created_at")
            .first()
        )
        if job is None:
            return False
        if job.attempts >= 3:
            job.status = Job.Status.FAILED
            job.error_code = "worker_interrupted"
            job.lease_token = None
            job.lease_until = None
            job.save()
            return True
        token = uuid.uuid4()
        job.status = Job.Status.RUNNING
        job.lease_token = token
        job.lease_until = now + timedelta(seconds=30)
        job.attempts += 1
        job.save()
    document = job.document
    parsed = None
    error_code = ""
    try:
        parsed = parse_original(
            artifact_path(document.workspace_id, document.id), document.kind, document.raw_sha256
        )
    except ParseRejected as error:
        error_code = str(error)
    except OSError:
        error_code = "artifact_unavailable"
    with transaction.atomic():
        locked_job = Job.objects.select_for_update().get(pk=job.pk)
        if locked_job.lease_token != token or locked_job.status != Job.Status.RUNNING:
            return True
        if parsed is not None:
            TextVersion.objects.create(
                document=document,
                pages=parsed.pages,
                canonical_sha256=parsed.canonical_sha256,
                parser_version=parsed.parser_version,
                normalization_version=NORMALIZATION_VERSION,
            )
            locked_job.status = Job.Status.SUCCEEDED
        else:
            locked_job.status = Job.Status.FAILED
            locked_job.error_code = error_code
        locked_job.lease_until = None
        locked_job.lease_token = None
        locked_job.save()
    return True
