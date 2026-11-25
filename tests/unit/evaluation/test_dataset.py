from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from evaluation.dataset import local_path, validate_gold, validate_split
from evaluation.schemas import GoldFile

pytestmark = pytest.mark.unit


def test_48_sources_16_groups_and_grouped_split(dev_dataset, test_dataset):
    validate_split(dev_dataset, test_dataset)
    assert len(dev_dataset.manifest.documents) == 30
    assert len(test_dataset.manifest.documents) == 18
    assert (
        len({d.family for ds in [dev_dataset, test_dataset] for d in ds.manifest.documents}) == 16
    )
    assert dev_dataset.gold.human_review == test_dataset.gold.human_review == "pending"
    assert {Path(d.path).suffix for d in dev_dataset.manifest.documents} == {".txt", ".pdf"}


@pytest.mark.parametrize(
    "attribute", ["family", "template_id", "identity_group", "raw_sha256", "canonical_sha256"]
)
def test_cross_split_metadata_leaks_rejected(dev_dataset, test_dataset, attribute):
    manifest = test_dataset.manifest.model_copy(deep=True)
    setattr(manifest.documents[0], attribute, getattr(dev_dataset.manifest.documents[0], attribute))
    with pytest.raises(ValueError, match="cross_split"):
        validate_split(dev_dataset, replace(test_dataset, manifest=manifest))


def test_near_duplicate_template_and_identity_leaks(dev_dataset, test_dataset):
    for change in (
        {"identities": dev_dataset.identities},
        {"template_fingerprints": dev_dataset.template_fingerprints},
    ):
        with pytest.raises(ValueError, match="cross_split"):
            validate_split(dev_dataset, replace(test_dataset, **change))


def test_gold_spans_and_schema_are_strict(dev_dataset):
    case = dev_dataset.gold.cases["f01_v1"].model_copy(deep=True)
    case.fields["supplier_name"].candidates[0].anchors[0].value_start += 1
    with pytest.raises(ValueError, match="invalid_gold_anchor"):
        validate_gold(case, dev_dataset.pages["f01_v1"])
    payload = dev_dataset.gold.model_dump()
    payload["human_review"] = "confirmed"
    with pytest.raises(ValidationError):
        GoldFile.model_validate(payload)
    payload["human_review"] = "pending"
    payload["cases"]["f01_v1"]["fields"]["confidence"] = {}
    with pytest.raises(ValidationError):
        GoldFile.model_validate(payload)


def test_dataset_paths_cannot_escape(tmp_path):
    with pytest.raises(ValueError):
        local_path(tmp_path, "../secret")


def test_original_hash_tamper_is_rejected(tmp_path, dev_dataset):
    import json
    import shutil

    from evaluation.dataset import load_dataset

    root = Path(__file__).resolve().parents[3]
    destination = tmp_path / "dev"
    shutil.copytree(root / "datasets/dev", destination)
    manifest = json.loads((destination / "manifest.json").read_text())
    first = destination / manifest["documents"][0]["path"]
    first.write_bytes(first.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="source_type_or_hash_mismatch"):
        load_dataset(destination / "manifest.json")


def test_negative_fixtures_stay_outside_benchmark(dev_dataset, test_dataset):
    import hashlib

    from documents.parser import ParseRejected, parse_original

    root = Path(__file__).resolve().parents[3]
    source = root / "fixtures/parser_negative/mixed_text_scan.pdf"
    with pytest.raises(ParseRejected, match="no_text_page"):
        parse_original(source, "pdf", hashlib.sha256(source.read_bytes()).hexdigest())
    assert all(
        "parser_negative" not in d.path
        for ds in [dev_dataset, test_dataset]
        for d in ds.manifest.documents
    )
