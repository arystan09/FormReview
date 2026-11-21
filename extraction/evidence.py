from dataclasses import dataclass

EVIDENCE_VERSION = "unique-page-quotes-v1"


@dataclass(frozen=True)
class AnchoredEvidence:
    quote_start: int | None
    quote_end: int | None
    value_start: int | None
    value_end: int | None
    flags: tuple[str, ...]


def occurrences(text: str, needle: str) -> list[int]:
    positions = []
    start = 0
    while needle and (found := text.find(needle, start)) >= 0:
        positions.append(found)
        start = found + 1
    return positions


def anchor(pages: list[str], page: int, quote: str, value_text: str) -> AnchoredEvidence:
    flags: list[str] = []
    matches = [
        (number, offset)
        for number, text in enumerate(pages, 1)
        for offset in occurrences(text, quote)
    ]
    if not 1 <= page <= len(pages):
        flags.append("wrong_page")
    elif not any(number == page for number, _ in matches):
        flags.append("wrong_page" if matches else "quote_missing")
    if not matches and "quote_missing" not in flags:
        flags.append("quote_missing")
    if len(matches) > 1:
        flags.append("duplicate_quote")
    value_positions = occurrences(quote, value_text)
    if not value_positions:
        flags.append("value_not_in_quote")
    elif len(value_positions) > 1:
        flags.append("duplicate_value_in_quote")
    quote_start = quote_end = value_start = value_end = None
    if len(matches) == 1 and matches[0][0] == page:
        quote_start = matches[0][1]
        quote_end = quote_start + len(quote)
        if len(value_positions) == 1:
            value_start = quote_start + value_positions[0]
            value_end = value_start + len(value_text)
    return AnchoredEvidence(quote_start, quote_end, value_start, value_end, tuple(flags))
