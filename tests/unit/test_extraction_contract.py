import copy
import json

import pytest
from pydantic import ValidationError

from extraction.config import digest
from extraction.schemas import FIELD_NAMES, ExtractionOutput
from extraction.services import parse_response

pytestmark = pytest.mark.unit


def missing_output():
    return {field: {"status": "missing", "candidates": []} for field in FIELD_NAMES}


def candidate():
    return {"page": 1, "quote": "Supplier: Synthetic", "value_text": "Synthetic"}


def test_exact_five_fields_and_full_schema() -> None:
    output = missing_output()
    assert set(ExtractionOutput.model_validate(output).model_dump()) == set(FIELD_NAMES)
    schema = ExtractionOutput.model_json_schema()
    assert set(schema["required"]) == set(FIELD_NAMES)
    assert schema["additionalProperties"] is False
    assert len(schema["$defs"]["FieldResult"]["allOf"]) == 3
    for name in FIELD_NAMES:
        missing = copy.deepcopy(output)
        del missing[name]
        with pytest.raises(ValidationError):
            ExtractionOutput.model_validate(missing)
    output["confidence"] = 0.99
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(output)


@pytest.mark.parametrize(
    ("status", "count", "valid"),
    [
        ("present", 0, False),
        ("present", 1, True),
        ("present", 2, False),
        ("missing", 0, True),
        ("missing", 1, False),
        ("ambiguous", 1, False),
        ("ambiguous", 2, True),
        ("ambiguous", 3, False),
    ],
)
def test_status_cardinality(status, count, valid) -> None:
    output = missing_output()
    output["supplier_name"] = {
        "status": status,
        "candidates": [{**candidate(), "page": i + 1} for i in range(count)],
    }
    if valid:
        ExtractionOutput.model_validate(output)
    else:
        with pytest.raises(ValidationError):
            ExtractionOutput.model_validate(output)


def test_distinct_source_candidates() -> None:
    output = missing_output()
    output["supplier_name"] = {"status": "ambiguous", "candidates": [candidate(), candidate()]}
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(output)


@pytest.mark.parametrize(
    "change",
    [
        {"offset": 12},
        {"confidence": 0.8},
        {"page": "1"},
        {"page": True},
        {"page": 0},
        {"page": 6},
        {"quote": "x" * 501},
        {"value_text": "x" * 257},
        {"value_text": " "},
        {"quote": ""},
        {"value_text": "\x00"},
        {"value_text": "\ud800"},
    ],
)
def test_strict_candidate_values(change) -> None:
    output = missing_output()
    output["supplier_name"] = {"status": "present", "candidates": [{**candidate(), **change}]}
    with pytest.raises(ValidationError):
        ExtractionOutput.model_validate(output)


@pytest.mark.parametrize(
    "response", ["not json", "[]", "null", '{"supplier_name":{},"supplier_name":{}}', "x" * 65537]
)
def test_malformed_outputs(response) -> None:
    with pytest.raises((ValueError, ValidationError)):
        parse_response(response)


def test_prompt_participates_in_hash() -> None:
    assert digest({"prompt_text": "one"}) != digest({"prompt_text": "two"})
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    assert parse_response(json.dumps(missing_output())).supplier_name.status == "missing"
