from typing import Literal, Self

from pydantic import Field, model_validator

from extraction.schemas import FIELD_NAMES, StrictContract


class GoldAnchor(StrictContract):
    page: int = Field(ge=1, le=5)
    quote: str = Field(min_length=1, max_length=500)
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    value_start: int = Field(ge=0)
    value_end: int = Field(ge=1)


class GoldCandidate(StrictContract):
    accepted_raw_values: list[str] = Field(min_length=1)
    accepted_normalized_values: list[str | int]
    normalizable: bool
    expected_validation_flags: list[Literal["invalid_email", "unresolved_terms"]]
    anchors: list[GoldAnchor] = Field(min_length=1)

    @model_validator(mode="after")
    def consistency(self) -> Self:
        if self.normalizable != bool(self.accepted_normalized_values):
            raise ValueError("normalizable_values_disagree")
        if self.normalizable == bool(self.expected_validation_flags):
            raise ValueError("normalizable_flags_disagree")
        return self


class GoldField(StrictContract):
    status: Literal["present", "missing", "ambiguous"]
    candidates: list[GoldCandidate] = Field(max_length=2)

    @model_validator(mode="after")
    def cardinality(self) -> Self:
        if len(self.candidates) != {"present": 1, "missing": 0, "ambiguous": 2}[self.status]:
            raise ValueError("gold_cardinality")
        if len({tuple(c.accepted_raw_values) for c in self.candidates}) != len(self.candidates):
            raise ValueError("duplicate_gold_candidates")
        return self


class GoldCase(StrictContract):
    fields: dict[str, GoldField]

    @model_validator(mode="after")
    def five_fields(self) -> Self:
        if set(self.fields) != set(FIELD_NAMES):
            raise ValueError("gold_requires_five_fields")
        return self


class GoldFile(StrictContract):
    schema_version: Literal["formreview-gold-v1"]
    human_review: Literal["pending"]
    provenance: str
    cases: dict[str, GoldCase]


class DocumentEntry(StrictContract):
    id: str
    family: str
    variant: int = Field(ge=1, le=3)
    template_id: str
    identity_group: str
    path: str
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Manifest(StrictContract):
    schema_version: Literal["formreview-dataset-v1"]
    split: Literal["dev", "test"]
    gold_path: str
    gold_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    documents: list[DocumentEntry]
