from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

FIELD_NAMES = ("supplier_name", "registration_id", "contact_email", "country", "payment_terms_days")
FieldName = Literal[
    "supplier_name", "registration_id", "contact_email", "country", "payment_terms_days"
]
SCHEMA_VERSION = "five-fields-v1"


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SourceCandidate(StrictContract):
    value_text: Annotated[str, Field(min_length=1, max_length=256)]
    quote: Annotated[str, Field(min_length=1, max_length=500)]
    page: Annotated[int, Field(ge=1, le=5)]

    @model_validator(mode="after")
    def nonblank(self) -> Self:
        if not self.value_text.strip() or not self.quote.strip():
            raise ValueError("Candidate text must not be blank")
        for text in (self.value_text, self.quote):
            text.encode("utf-8")
            if "\x00" in text:
                raise ValueError("NUL is not source text")
        return self


class FieldResult(StrictContract):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        json_schema_extra={
            "allOf": [
                {
                    "if": {"properties": {"status": {"const": status}}},
                    "then": {"properties": {"candidates": {"minItems": count, "maxItems": count}}},
                }
                for status, count in (("present", 1), ("missing", 0), ("ambiguous", 2))
            ],
        },
    )
    status: Literal["present", "missing", "ambiguous"]
    candidates: Annotated[list[SourceCandidate], Field(max_length=2)]

    @model_validator(mode="after")
    def cardinality(self) -> Self:
        if len(self.candidates) != {"present": 1, "missing": 0, "ambiguous": 2}[self.status]:
            raise ValueError("Status and candidate count disagree")
        sources = {
            (candidate.page, candidate.quote, candidate.value_text) for candidate in self.candidates
        }
        if len(sources) != len(self.candidates):
            raise ValueError("Source candidates must be distinct")
        return self


class ExtractionOutput(StrictContract):
    supplier_name: FieldResult
    registration_id: FieldResult
    contact_email: FieldResult
    country: FieldResult
    payment_terms_days: FieldResult

    def field_results(self) -> list[tuple[str, FieldResult]]:
        return [(name, getattr(self, name)) for name in FIELD_NAMES]
