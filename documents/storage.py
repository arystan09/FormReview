import hashlib
import os
import re
import uuid
from pathlib import Path
from typing import BinaryIO

from django.conf import settings

MAX_BYTES = 5 * 1024 * 1024


class UploadRejected(ValueError):
    pass


def safe_filename(filename: str) -> str:
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"[^A-Za-z0-9._ -]", "_", name)[:120].strip(". ") or "document"


def artifact_path(workspace_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    return Path(settings.PRIVATE_ROOT) / str(workspace_id) / str(document_id)


def store_original(
    source: BinaryIO, workspace_id: uuid.UUID, document_id: uuid.UUID
) -> tuple[str, int]:
    root = Path(settings.PRIVATE_ROOT)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    folder = root / str(workspace_id)
    folder.mkdir(mode=0o700, exist_ok=True)
    target = artifact_path(workspace_id, document_id)
    digest = hashlib.sha256()
    size = 0
    # Exclusive creation prevents replacing an existing immutable original.
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            while chunk := source.read(min(65536, MAX_BYTES + 1 - size)):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UploadRejected("file_too_large")
                digest.update(chunk)
                destination.write(chunk)
            if size == 0:
                raise UploadRejected("empty_file")
            destination.flush()
            os.fsync(destination.fileno())
        target.chmod(0o400)
        return digest.hexdigest(), size
    except BaseException:
        target.unlink(missing_ok=True)
        raise
