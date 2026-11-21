from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "marker", ["", "@pytest.mark.unknown", "@pytest.mark.unit\n@pytest.mark.e2e"]
)
def test_invalid_test_categories_fail_collection(pytester: pytest.Pytester, marker: str) -> None:
    pytester.makeconftest(Path(__file__).parents[1].joinpath("conftest.py").read_text())
    pytester.makeini(
        "[pytest]\naddopts = --strict-markers\nmarkers =\n"
        "    unit: unit tests\n    integration: integration tests\n    e2e: e2e tests\n"
    )
    pytester.makepyfile(f"import pytest\n{marker}\ndef test_example():\n    pass\n")
    result = pytester.runpytest_subprocess("--collect-only")
    assert result.ret != 0
