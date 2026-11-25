"""Text-only labelled-line baseline. No paths, fixture identifiers, labels or network."""

import re
from typing import Any

from extraction.schemas import FIELD_NAMES

BASELINE_VERSION = "labelled-lines-v1"
PATTERNS = dict(
    zip(
        FIELD_NAMES,
        (
            r"Supplier",
            r"Registration ID",
            r"Email",
            r"Country",
            r"Payment terms",
        ),
        strict=True,
    )
)


def extract(pages: list[str], settings: dict[str, Any]) -> dict[str, Any]:
    if settings != {"patterns": PATTERNS, "flags": "IGNORECASE", "max_candidates": 2}:
        raise ValueError("unsupported_baseline_settings")
    output = {}
    for field, label in settings["patterns"].items():
        candidates = []
        pattern = re.compile(r"^" + label + r":\s*(\S.*?)\s*$", re.IGNORECASE)
        for page, text in enumerate(pages, 1):
            for line in text.splitlines():
                match = pattern.fullmatch(line)
                if match:
                    candidate = {"value_text": match[1], "quote": line, "page": page}
                    if candidate not in candidates:
                        candidates.append(candidate)
        if len(candidates) > 2:
            raise ValueError("baseline_too_many_candidates")
        output[field] = {
            "status": ("missing", "present", "ambiguous")[len(candidates)],
            "candidates": candidates,
        }
    return output
