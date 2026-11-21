"""Rebuild visibly synthetic, hand-authored replay outputs tied to source hashes.

No labels are read; output values/quotes below are authored examples, not parser
extraction. Only canonical source hashes are obtained through the real parser.
"""

import hashlib
import json
from pathlib import Path

from documents.parser import parse_original
from extraction.schemas import FIELD_NAMES

ROOT = Path(__file__).resolve().parents[1]

# Entries are (source value, exact or deliberately invalid quote, claimed page).
SCENARIOS = {
    "01_complete.txt": {
        "supplier_name": [("Alder Parts", "Supplier: Alder Parts", 1)],
        # Deliberate synthetic omissions/unsupported evidence for the walkthrough.
        "contact_email": [("alder@example.test", "Verified email: alder@example.test", 1)],
        "country": [("Italy", "Country: Italy", 1)],
        "payment_terms_days": [("Net30", "Payment terms: Net30", 1)],
    },
    "02_bom_unicode.txt": {
        "supplier_name": [("Café Parts", "Supplier: Café Parts", 1)],
        "registration_id": [("0007/X", "Registration ID: 0007/X", 1)],
        "contact_email": [("cafe@example.test", "Email: cafe@example.test", 1)],
        "country": [("France", "Country: France", 1)],
        "payment_terms_days": [("14 days", "Payment terms: 14 days", 1)],
    },
    "03_missing_optional.txt": {
        "supplier_name": [("Beacon Tools", "Supplier: Beacon Tools", 1)],
        "contact_email": [("beacon@example.test", "Email: beacon@example.test", 1)],
    },
    "04_ambiguous_email.txt": {
        "supplier_name": [("Cedar Supply", "Supplier: Cedar Supply", 1)],
        "contact_email": [
            ("sales@cedar.example.test", "Email: sales@cedar.example.test", 1),
            ("billing@cedar.example.test", "Email: billing@cedar.example.test", 1),
        ],
        "country": [("Canada", "Country: Canada", 1)],
        "payment_terms_days": [("Net45", "Payment terms: Net45", 1)],
    },
    "05_unresolved_terms.txt": {
        "supplier_name": [("Drift Materials", "Supplier: Drift Materials", 1)],
        "registration_id": [("00.04-A", "Registration ID: 00.04-A", 1)],
        "contact_email": [("drift@example.test", "Email: drift@example.test", 1)],
        "country": [("United Kingdom", "Country: United Kingdom", 1)],
        "payment_terms_days": [("on receipt", "Payment terms: on receipt", 1)],
    },
    "06_source_instructions.txt": {
        "supplier_name": [("Elm Goods", "Supplier: Elm Goods", 1)],
        "contact_email": [("elm@example.test", "Email: elm@example.test", 1)],
        "country": [("England", "Country: England", 1)],
        "payment_terms_days": [("Net0", "Payment terms: Net0", 1)],
    },
    "07_complete.pdf": {
        "supplier_name": [("Flint Goods", "Supplier: Flint Goods", 1)],
        "registration_id": [("009-Z", "Registration ID: 009-Z", 1)],
        "contact_email": [("flint@example.test", "Email: flint@example.test", 1)],
        "country": [("Germany", "Country: Germany", 1)],
        "payment_terms_days": [("Net60", "Payment terms: Net60", 1)],
    },
    "08_two_pages.pdf": {
        "supplier_name": [("Grove Components", "Supplier: Grove Components", 1)],
        "registration_id": [("000/19", "Registration ID: 000/19", 2)],
        "contact_email": [("grove@example.test", "Email: grove@example.test", 1)],
        "country": [("Spain", "Country: Spain", 1)],  # Deliberately wrong page.
        "payment_terms_days": [("90 days", "Payment terms: 90 days", 2)],
    },
    "09_missing_name.pdf": {
        "registration_id": [("000-Q", "Registration ID: 000-Q", 1)],
        "contact_email": [("unknown@example.test", "Email: unknown@example.test", 1)],
        "country": [("Ireland", "Country: Ireland", 1)],
        "payment_terms_days": [("Net15", "Payment terms: Net15", 1)],
    },
    "10_out_of_range.pdf": {
        "supplier_name": [("Harbor Tools", "Supplier: Harbor Tools", 1)],
        "contact_email": [("harbor@example.test", "Email: harbor@example.test", 1)],
        "country": [("USA", "Country: USA", 1)],
        "payment_terms_days": [("Net366", "Payment terms: Net366", 1)],
    },
    "11_ambiguous_country.pdf": {
        "supplier_name": [("Iris Supply", "Supplier: Iris Supply", 1)],
        "contact_email": [("iris@example.test", "Email: iris@example.test", 1)],
        "country": [("France", "Country: France", 1), ("Belgium", "Country: Belgium", 1)],
        "payment_terms_days": [("Net30", "Payment terms: Net30", 1)],
    },
    "12_upper_boundary.pdf": {
        "supplier_name": [("Juniper Parts", "Supplier: Juniper Parts", 1)],
        "registration_id": [("000-12", "Registration ID: 000-12", 1)],
        "contact_email": [("juniper@example.test", "Email: juniper@example.test", 1)],
        "country": [("Australia", "Country: Australia", 1)],
        "payment_terms_days": [("365 days", "Payment terms: 365 days", 1)],
    },
}


def main() -> None:
    fixtures = {}
    for filename, fields in SCENARIOS.items():
        path = ROOT / "datasets/dev" / filename
        source = parse_original(
            path, path.suffix[1:], hashlib.sha256(path.read_bytes()).hexdigest()
        )
        output = {}
        for name in FIELD_NAMES:
            candidates = [
                {"value_text": value, "quote": quote, "page": page}
                for value, quote, page in fields.get(name, [])
            ]
            output[name] = {
                "status": {0: "missing", 1: "present", 2: "ambiguous"}[len(candidates)],
                "candidates": candidates,
            }
        fixtures[source.canonical_sha256] = {"id": f"synthetic-v1/{filename}", "output": output}
    destination = ROOT / "extraction/fixtures/synthetic_v1.json"
    destination.write_text(
        json.dumps(
            {
                "notice": (
                    "SYNTHETIC REPLAY — authored examples, including intentional errors; "
                    "not model results or truth labels."
                ),
                "by_canonical_hash": fixtures,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
