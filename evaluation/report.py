import json
from pathlib import Path
from typing import Any

from documents.models import TextVersion
from documents.parser import NORMALIZATION_VERSION
from evaluation.dataset import Dataset, load_json, sha256
from evaluation.scoring import SCORER_VERSION, VALIDATOR_VERSION, Outcome, score
from extraction.config import digest
from extraction.models import ExtractionConfig
from extraction.providers import build_request
from extraction.providers.baseline import extract
from extraction.replay import FIXTURES, ReplayProvider
from extraction.schemas import ExtractionOutput

ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / "datasets/configs.v1.json"


def frozen_config(provider: str) -> dict[str, Any]:
    frozen = load_json(FREEZE)
    config: dict[str, Any] = frozen["configs"][provider]
    if digest(config["executable"]) != config["config_hash"]:
        raise ValueError("frozen_config_hash_mismatch")
    for relative, expected in config["implementation_hashes"].items():
        if sha256(ROOT / relative) != expected:
            raise ValueError("frozen_implementation_changed")
    return config


def run(dataset: Dataset, provider: str) -> dict[str, Any]:
    if dataset.manifest.split != "dev":
        raise ValueError("stage5_holdout_validation_only")
    if provider not in {"baseline", "replay"}:
        raise ValueError("offline_provider_required")
    config = frozen_config(provider)
    executable = config["executable"]
    outcomes = {}
    for doc in dataset.manifest.documents:
        pages = dataset.pages[doc.id]
        try:
            if provider == "baseline":
                result = extract(pages, executable["settings"])
            else:
                stored = ExtractionConfig(**executable, config_hash=config["config_hash"])
                text = TextVersion(
                    pages=pages,
                    canonical_sha256=doc.canonical_sha256,
                    parser_version="dataset-canonical-v1",
                    normalization_version=NORMALIZATION_VERSION,
                )
                _, response = ReplayProvider().extract(build_request(stored, text))
                result = json.loads(response)
            outcomes[doc.id] = Outcome(
                "complete", ExtractionOutput.model_validate(result), mode=provider
            )
        except ValueError as error:
            absent = str(error) == "no_synthetic_replay_fixture"
            outcomes[doc.id] = Outcome(
                "unattempted" if absent else "error",
                mode=provider,
                error="no_scripted_fixture" if absent else "invalid_output",
            )
        except Exception:
            # Exceptions may contain source text: reports/logs expose only a fixed code.
            outcomes[doc.id] = Outcome("error", error="provider_error", mode=provider)
    sources = {
        str(p.relative_to(ROOT)): sha256(p)
        for directory in ("evaluation", "extraction", "documents")
        for p in sorted((ROOT / directory).rglob("*.py"))
    }
    sources.update(
        {
            name: sha256(ROOT / name)
            for name in (
                "uv.lock",
                "pyproject.toml",
                "scripts/build_dataset.py",
                "scripts/generate_fixtures.py",
                "datasets/scenarios.json",
            )
        }
    )
    return {
        "schema_version": "formreview-evaluation-report-v1",
        "provider": provider,
        "notice": (
            "Public synthetic benchmark; human label review pending. "
            "No live accuracy or generalization claim."
        ),
        "human_review": dataset.gold.human_review,
        "split": dataset.manifest.split,
        "dataset_hash": dataset.dataset_hash,
        "config_hash": config["config_hash"],
        "freeze_hash": sha256(FREEZE),
        "scorer_version": SCORER_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "scorer_hash": sha256(Path(__file__).with_name("scoring.py")),
        "build_hash": digest(sources),
        "source_hashes": sources,
        "replay_fixture_hash": sha256(FIXTURES) if provider == "replay" else None,
        **score(dataset, outcomes),
    }
