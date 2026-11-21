import pytest

from extraction.evidence import anchor
from extraction.normalization import normalize

pytestmark = pytest.mark.unit


def test_exact_unicode_offsets() -> None:
    page = "📄 Café\nSupplier: Alder Parts\nEnd"
    result = anchor([page], 1, "Supplier: Alder Parts", "Alder Parts")
    assert result.flags == ()
    assert result.quote_start == 7
    assert page[result.quote_start : result.quote_end] == "Supplier: Alder Parts"
    assert page[result.value_start : result.value_end] == "Alder Parts"


@pytest.mark.parametrize(
    ("pages", "page", "quote", "value", "flag"),
    [
        (["same same"], 1, "same", "same", "duplicate_quote"),
        (["same", "same"], 1, "same", "same", "duplicate_quote"),
        (["aaaa"], 1, "aa", "aa", "duplicate_quote"),
        (["first", "target"], 1, "target", "target", "wrong_page"),
        (["target"], 2, "target", "target", "wrong_page"),
        (["source"], 1, "fabricated", "fabricated", "quote_missing"),
    ],
)
def test_no_fabricated_offset(pages, page, quote, value, flag) -> None:
    result = anchor(pages, page, quote, value)
    assert flag in result.flags
    assert result.quote_start is None and result.quote_end is None
    assert result.value_start is None and result.value_end is None


def test_value_membership_is_exact_not_semantic() -> None:
    result = anchor(
        ["Email: first@example.test"], 1, "Email: first@example.test", "second@example.test"
    )
    assert result.flags == ("value_not_in_quote",)
    assert result.quote_start == 0
    assert result.value_start is None
    result = anchor(["Net30 and Net30"], 1, "Net30 and Net30", "Net30")
    assert result.flags == ("duplicate_value_in_quote",)
    assert result.value_start is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Net0", 0),
        ("Net30", 30),
        ("NET 30", 30),
        ("14 days", 14),
        ("365days", 365),
        ("Net365", 365),
        ("Net030", 30),
    ],
)
def test_explicit_terms(value, expected) -> None:
    assert normalize("payment_terms_days", value) == (expected, ())


@pytest.mark.parametrize(
    "value",
    [
        "Net366",
        "366 days",
        "on receipt",
        "30",
        "about 30 days",
        "Net-1",
        "Net30.5",
        "thirty days",
        "Net30 or Net60",
        "30 business days",
    ],
)
def test_unresolved_terms(value) -> None:
    assert normalize("payment_terms_days", value) == (None, ("unresolved_terms",))


def test_other_values_are_not_inferred_or_rewritten() -> None:
    assert normalize("registration_id", "000/AB-01") == ("000/AB-01", ())
    assert normalize("country", "England") == ("England", ())
    assert normalize("contact_email", "Mixed@Example.TEST") == ("Mixed@Example.TEST", ())
