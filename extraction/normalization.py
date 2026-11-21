import re

NORMALIZER_VERSION = "explicit-fields-v1"


def normalize(field: str, value_text: str) -> tuple[str | int | None, tuple[str, ...]]:
    if field != "payment_terms_days":
        return value_text, ()
    match = re.fullmatch(
        r"(?:net\s*([0-9]{1,3})|([0-9]{1,3})\s*days)", value_text.strip(), re.IGNORECASE
    )
    if match:
        value = int(match.group(1) or match.group(2))
        if 0 <= value <= 365:
            return value, ()
    return None, ("unresolved_terms",)
