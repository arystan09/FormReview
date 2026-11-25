"""Exact, source-aligned scoring. Valid quotes alone never establish correct entities."""

from dataclasses import dataclass
from itertools import permutations
from typing import Any, Literal

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from evaluation.dataset import Dataset
from evaluation.schemas import GoldCandidate, GoldField
from extraction.evidence import anchor
from extraction.normalization import normalize
from extraction.schemas import FIELD_NAMES, ExtractionOutput, FieldResult, SourceCandidate

SCORER_VERSION = "exact-source-aligned-v1"
VALIDATOR_VERSION = "email-and-explicit-terms-v1"
METRICS = (
    "present_field_accuracy",
    "present_literal_evidence",
    "unnormalizable_handling",
    "missing_handling",
    "ambiguity_detection",
    "ambiguous_candidates",
    "evidence_validity",
    "all_five_correctness",
)


@dataclass(frozen=True)
class Outcome:
    state: Literal["complete", "error", "refused", "unattempted"]
    output: ExtractionOutput | None = None
    error: str = ""
    mode: str = "baseline"


def validation(field: str, raw: str) -> tuple[str | int | None, tuple[str, ...]]:
    value, flags = normalize(field, raw)
    if field == "contact_email":
        try:
            validate_email(raw)
        except ValidationError:
            return None, ("invalid_email",)
    return value, flags


def matches(
    name: str,
    predicted: SourceCandidate,
    gold: GoldCandidate,
    pages: list[str],
    *,
    literal_only: bool = False,
) -> bool:
    evidence = anchor(pages, predicted.page, predicted.quote, predicted.value_text)
    aligned = any(
        predicted.page == a.page
        and evidence.value_start == a.value_start
        and evidence.value_end == a.value_end
        for a in gold.anchors
    )
    if evidence.flags or not aligned or predicted.value_text not in gold.accepted_raw_values:
        return False
    if literal_only:
        return True
    value, flags = validation(name, predicted.value_text)
    normalized = any(type(value) is type(v) and value == v for v in gold.accepted_normalized_values)
    return (normalized if gold.normalizable else value is None) and set(flags) == set(
        gold.expected_validation_flags
    )


def field_correct(
    name: str,
    predicted: FieldResult | None,
    gold: GoldField,
    pages: list[str],
    *,
    literal_only: bool = False,
) -> bool:
    if predicted is None or predicted.status != gold.status:
        return False
    return any(
        all(
            matches(name, p, g, pages, literal_only=literal_only)
            for p, g in zip(predicted.candidates, ordering, strict=True)
        )
        for ordering in permutations(gold.candidates)
    )


def score(dataset: Dataset, outcomes: dict[str, Outcome]) -> dict[str, Any]:
    if set(outcomes) - set(dataset.gold.cases):
        raise ValueError("unscheduled_result")
    counters = {name: [0, 0] for name in METRICS}
    states = {name: 0 for name in ("scheduled", "complete", "error", "refused", "unattempted")}
    cases = []

    def add(metric: str, correct: bool | int, total: int = 1) -> None:
        counters[metric][0] += int(correct)
        counters[metric][1] += total

    for doc in dataset.manifest.documents:
        outcome = outcomes.get(doc.id, Outcome("unattempted", error="not_attempted"))
        if outcome.mode not in {"baseline", "replay", "live"}:
            outcome = Outcome("error", error="manual_or_unknown_mode_excluded")
        if outcome.state == "complete" and outcome.output is None:
            outcome = Outcome("error", error="missing_structured_output")
        states["scheduled"] += 1
        states[outcome.state] += 1
        success = outcome.state == "complete" and outcome.output is not None
        correctness = {}
        for name in FIELD_NAMES:
            expected = dataset.gold.cases[doc.id].fields[name]
            predicted = getattr(outcome.output, name) if success else None
            correct = field_correct(name, predicted, expected, dataset.pages[doc.id])
            correctness[name] = correct
            if expected.status == "present":
                add(
                    "present_literal_evidence",
                    field_correct(
                        name, predicted, expected, dataset.pages[doc.id], literal_only=True
                    ),
                )
                add(
                    "present_field_accuracy"
                    if expected.candidates[0].normalizable
                    else "unnormalizable_handling",
                    correct,
                )
            elif expected.status == "missing":
                add("missing_handling", correct)
            else:
                add(
                    "ambiguity_detection", predicted is not None and predicted.status == "ambiguous"
                )
                add("ambiguous_candidates", correct)
            candidates = predicted.candidates if predicted else []
            valid = sum(
                not anchor(dataset.pages[doc.id], c.page, c.quote, c.value_text).flags
                for c in candidates
            )
            add("evidence_validity", valid, max(len(expected.candidates), len(candidates)))
        add("all_five_correctness", all(correctness.values()))
        cases.append(
            {
                "id": doc.id,
                "family": doc.family,
                "state": outcome.state,
                "error": outcome.error,
                "field_correct": correctness,
            }
        )
    return {
        "counts": states,
        "metrics": {
            name: {"correct": n, "total": d, "rate": n / d if d else None}
            for name, (n, d) in counters.items()
        },
        "cases": cases,
    }
