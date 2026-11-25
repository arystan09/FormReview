from pathlib import Path
from unittest.mock import patch

import pytest

from evaluation.report import frozen_config, run
from extraction.providers.baseline import PATTERNS, extract
from extraction.replay import ReplayProvider

pytestmark = pytest.mark.unit


def test_baseline_text_only_without_file_or_label_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("baseline must not read files")

    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr("builtins.open", forbidden)
    output = extract(
        ["Supplier: Unseen Synthetic\nEmail: unseen@example.test\nPayment terms: Net9"],
        {"patterns": PATTERNS, "flags": "IGNORECASE", "max_candidates": 2},
    )
    assert output["supplier_name"]["candidates"][0]["value_text"] == "Unseen Synthetic"
    assert output["registration_id"]["status"] == "missing"


def test_replay_reports_uncovered_cases_and_payload_excludes_truth(dev_dataset):
    captured = []
    original = ReplayProvider.extract

    def capture(self, request):
        captured.append(request)
        return original(self, request)

    with patch.object(ReplayProvider, "extract", capture):
        report = run(dev_dataset, "replay")
    assert report["counts"] == {
        "scheduled": 30,
        "complete": 12,
        "error": 0,
        "refused": 0,
        "unattempted": 18,
    }
    assert report["metrics"]["all_five_correctness"]["total"] == 30
    assert report["metrics"]["all_five_correctness"]["correct"] == 10
    assert report["metrics"]["present_field_accuracy"]["correct"] == 45
    assert all(set(request) == {"config", "config_hash", "source"} for request in captured)
    assert all(
        set(request["source"])
        == {"pages", "canonical_sha256", "parser_version", "normalization_version"}
        for request in captured
    )
    config = frozen_config("replay")
    assert all(request["config"] == config["executable"] for request in captured)
    assert report["human_review"] == "pending" and report["provider"] == "replay"


def test_holdout_outputs_are_not_executed(test_dataset):
    with pytest.raises(ValueError, match="holdout_validation_only"):
        run(test_dataset, "baseline")


def test_baseline_report_known_error(dev_dataset):
    report = run(dev_dataset, "baseline")
    assert report["counts"]["complete"] == 30
    wrong = next(c for c in report["cases"] if c["id"] == "f07_v2")
    assert wrong["field_correct"]["country"] is False
    assert report["metrics"]["all_five_correctness"]["correct"] == 29
    assert report["metrics"]["present_field_accuracy"]["correct"] == 112


def test_provider_errors_are_counted_and_sanitized(dev_dataset):
    with patch("evaluation.report.extract", side_effect=RuntimeError("PRIVATE_SOURCE_SENTINEL")):
        report = run(dev_dataset, "baseline")
    assert report["counts"]["error"] == report["counts"]["scheduled"] == 30
    assert report["metrics"]["present_field_accuracy"]["correct"] == 0
    assert "PRIVATE_SOURCE_SENTINEL" not in str(report)


def test_modified_frozen_implementation_rejected(monkeypatch):
    monkeypatch.setattr("evaluation.report.sha256", lambda path: "0" * 64)
    with pytest.raises(ValueError, match="frozen_implementation_changed"):
        frozen_config("baseline")
