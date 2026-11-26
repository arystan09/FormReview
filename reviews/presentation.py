from typing import Any

from extraction.evidence import anchor
from extraction.normalization import normalize
from extraction.schemas import FIELD_NAMES
from reviews.models import ReviewDraft
from reviews.services import ReviewConflict, resolve_decisions

FLAG_HELP = {
    "missing": "No source candidate. Correct it or explain an optional missing value.",
    "ambiguous": "Two candidates disagree. Compare the source, then choose or correct one.",
    "quote_missing": "This quote does not occur in the canonical source. Correct it manually.",
    "wrong_page": "The quote is not on its claimed page. Correct it before acceptance.",
    "duplicate_quote": "The quote appears more than once. Its source location is not unique.",
    "value_not_in_quote": "The proposed value is absent from the quoted text.",
    "duplicate_value_in_quote": "The value repeats in this quote; its position is unresolved.",
    "unresolved_terms": "Only NetN/Ndays in 0–365 normalize. Explain any manual correction.",
}


def validation_errors(draft: ReviewDraft) -> list[str]:
    try:
        resolve_decisions(draft, draft.decisions)
    except ReviewConflict as error:
        return [str(error)]
    return []


def review_rows(draft: ReviewDraft) -> list[dict[str, Any]]:
    rows = []
    for name in FIELD_NAMES:
        candidates = []
        flags = draft.run.field_flags.get(name, []) if draft.run else []
        for candidate in (
            draft.run.candidates.filter(field=name).order_by("position") if draft.run else []
        ):
            evidence = anchor(
                draft.text_version.pages, candidate.page, candidate.quote, candidate.value_text
            )
            _, normalization_flags = normalize(name, candidate.value_text)
            supported = not (candidate.flags or evidence.flags or normalization_flags)
            candidates.append(
                {
                    "candidate": candidate,
                    "supported": supported,
                    "start": evidence.quote_start,
                    "end": evidence.quote_end,
                }
            )
        rows.append(
            {
                "name": name,
                "decision": draft.decisions.get(name, {}),
                "status": draft.run.output.get(name, {}).get("status", "unavailable")
                if draft.run
                else "manual-only",
                "flags": [
                    {"code": flag, "help": FLAG_HELP.get(flag, "Review this source flag manually.")}
                    for flag in flags
                ],
                "candidates": candidates,
            }
        )
    return rows
