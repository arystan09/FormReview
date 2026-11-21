from typing import Any

from documents.models import TextVersion
from documents.parser import canonical_hash
from extraction.config import digest, executable_config, validate_config
from extraction.models import ExtractionConfig


def build_request(config: ExtractionConfig, text: TextVersion) -> dict[str, Any]:
    validate_config(config)
    if canonical_hash(text.pages) != text.canonical_sha256:
        raise ValueError("canonical_hash_mismatch")
    # Explicit allowlist: no document metadata, memberships, labels or review decisions.
    return {
        "config": executable_config(config),
        "config_hash": config.config_hash,
        "source": {
            "pages": text.pages,
            "canonical_sha256": text.canonical_sha256,
            "parser_version": text.parser_version,
            "normalization_version": text.normalization_version,
        },
    }


def request_hash(request: dict[str, Any]) -> str:
    return digest(request)
