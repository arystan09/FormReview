import json
from pathlib import Path
from typing import Any

from documents.parser import canonical_hash
from extraction.config import digest

FIXTURES = Path(__file__).with_name("fixtures") / "synthetic_v1.json"


class ReplayProvider:
    """Return authored synthetic responses. No model inference, baseline or network call."""

    def extract(self, request: dict[str, Any]) -> tuple[str, str]:
        if digest(request["config"]) != request["config_hash"]:
            raise ValueError("config_hash_mismatch")
        if canonical_hash(request["source"]["pages"]) != request["source"]["canonical_sha256"]:
            raise ValueError("canonical_hash_mismatch")
        fixtures = json.loads(FIXTURES.read_text(encoding="utf-8"))
        fixture = fixtures["by_canonical_hash"].get(request["source"]["canonical_sha256"])
        if fixture is None:
            raise ValueError("no_synthetic_replay_fixture")
        return fixture["id"], json.dumps(fixture["output"], ensure_ascii=False)
