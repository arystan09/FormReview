from pathlib import Path

import pytest

from evaluation.dataset import load_dataset

ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def dev_dataset():
    return load_dataset(ROOT / "datasets/dev/manifest.json")


@pytest.fixture(scope="session")
def test_dataset():
    # Validation only: never generate or inspect held-out extraction outputs.
    return load_dataset(ROOT / "datasets/test/manifest.json")
