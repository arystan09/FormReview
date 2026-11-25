from dataclasses import replace

import pytest

from evaluation.scoring import Outcome, field_correct, score, validation
from extraction.providers.baseline import PATTERNS, extract
from extraction.schemas import ExtractionOutput, FieldResult

pytestmark = pytest.mark.unit
SETTINGS = {"patterns": PATTERNS, "flags": "IGNORECASE", "max_candidates": 2}


def one_case(dataset, case_id):
    manifest = dataset.manifest.model_copy(deep=True)
    manifest.documents = [d for d in manifest.documents if d.id == case_id]
    return replace(dataset, manifest=manifest)


def test_wrong_entity_quote_valid_but_incorrect(dev_dataset):
    dataset = one_case(dev_dataset, "f07_v2")
    output = ExtractionOutput.model_validate(extract(dataset.pages["f07_v2"], SETTINGS))
    country = output.country.candidates[0]
    assert country.value_text == "Germany"
    result = score(dataset, {"f07_v2": Outcome("complete", output)})
    assert result["metrics"]["evidence_validity"]["rate"] == 1
    assert result["cases"][0]["field_correct"]["country"] is False
    assert result["metrics"]["all_five_correctness"]["correct"] == 0


def test_malformed_present_literals_not_missing(dev_dataset):
    dataset = one_case(dev_dataset, "f05_v2")
    output = ExtractionOutput.model_validate(extract(dataset.pages["f05_v2"], SETTINGS))
    assert output.contact_email.status == output.payment_terms_days.status == "present"
    result = score(dataset, {"f05_v2": Outcome("complete", output)})
    assert result["metrics"]["unnormalizable_handling"] == {"correct": 2, "total": 2, "rate": 1}
    assert result["metrics"]["present_field_accuracy"]["total"] == 3
    assert validation("contact_email", "not-email") == (None, ("invalid_email",))
    assert validation("payment_terms_days", "Net366") == (None, ("unresolved_terms",))


def test_missing_and_ambiguous_are_separate(dev_dataset):
    for case_id, metric in [("f03_v1", "missing_handling"), ("f04_v1", "ambiguity_detection")]:
        dataset = one_case(dev_dataset, case_id)
        output = ExtractionOutput.model_validate(extract(dataset.pages[case_id], SETTINGS))
        result = score(dataset, {case_id: Outcome("complete", output)})
        assert result["metrics"][metric]["rate"] == 1
    expected = dev_dataset.gold.cases["f04_v1"].fields["contact_email"]
    reversed_prediction = output.contact_email.model_copy(deep=True)
    reversed_prediction.candidates.reverse()
    assert field_correct(
        "contact_email", reversed_prediction, expected, dev_dataset.pages["f04_v1"]
    )
    wrong = reversed_prediction.model_copy(deep=True)
    wrong.candidates[0].quote = "Unsupported quote"
    assert not field_correct("contact_email", wrong, expected, dev_dataset.pages["f04_v1"])


@pytest.mark.parametrize("state", ["error", "refused", "unattempted"])
def test_failed_scheduled_cases_stay_in_denominators(dev_dataset, state):
    dataset = one_case(dev_dataset, "f01_v1")
    result = score(dataset, {"f01_v1": Outcome(state)})
    assert result["counts"][state] == 1 and result["counts"]["scheduled"] == 1
    assert result["metrics"]["present_field_accuracy"] == {"correct": 0, "total": 5, "rate": 0}
    assert result["metrics"]["all_five_correctness"]["rate"] == 0
    assert result["metrics"]["missing_handling"]["total"] == 0
    assert result["metrics"]["missing_handling"]["rate"] is None


def test_absent_outcomes_and_manual_corrections_never_become_model_success(dev_dataset):
    dataset = one_case(dev_dataset, "f01_v1")
    assert score(dataset, {})["counts"]["unattempted"] == 1
    output = ExtractionOutput.model_validate(extract(dataset.pages["f01_v1"], SETTINGS))
    result = score(dataset, {"f01_v1": Outcome("complete", output, mode="manual")})
    assert result["counts"]["error"] == 1
    assert result["metrics"]["all_five_correctness"]["correct"] == 0


def test_all_missing_guess_cannot_inflate_present_accuracy(dev_dataset):
    dataset = one_case(dev_dataset, "f01_v1")
    output = ExtractionOutput.model_validate(
        {
            name: {"status": "missing", "candidates": []}
            for name in dataset.gold.cases["f01_v1"].fields
        }
    )
    result = score(dataset, {"f01_v1": Outcome("complete", output)})
    assert result["metrics"]["present_field_accuracy"]["rate"] == 0
    assert result["metrics"]["evidence_validity"]["rate"] == 0
    assert not field_correct(
        "country",
        FieldResult(status="missing", candidates=[]),
        dataset.gold.cases["f01_v1"].fields["country"],
        dataset.pages["f01_v1"],
    )
