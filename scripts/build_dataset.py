"""Compile authored scenarios into deterministic sources, gold anchors and manifests.

Does not import an extractor/scorer/normalizer. Expected values are explicit in
scenarios.json; parsing only locates their evidence in canonical source pages.
Uses existing pypdf Base-14 Helvetica helper, with no embedded/distributed font.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter

from documents.parser import parse_original
from evaluation.schemas import GoldFile, Manifest
from scripts.generate_fixtures import write_pdf

ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    schema_dir = ROOT / "datasets/schemas"
    schema_dir.mkdir(exist_ok=True)
    write_json(schema_dir / "manifest-v1.schema.json", Manifest.model_json_schema())
    write_json(schema_dir / "gold-v1.schema.json", GoldFile.model_json_schema())
    negative = ROOT / "fixtures/parser_negative"
    mixed = PdfWriter()
    for source in (ROOT / "datasets/dev/07_complete.pdf", negative / "scan_like.pdf"):
        mixed.add_page(PdfReader(source).pages[0])
    with (negative / "mixed_text_scan.pdf").open("wb") as handle:
        mixed.write(handle)
    (negative / "unsupported.docx").write_bytes(
        b"Synthetic unsupported extension fixture, not a DOCX document."
    )
    spec = json.loads((ROOT / "datasets/scenarios.json").read_text(encoding="utf-8"))
    for split in ("dev", "test"):
        directory = ROOT / "datasets" / split
        documents = []
        cases = {}
        for case in spec["cases"]:
            if case["split"] != split:
                continue
            path = directory / case["path"]
            if not case["existing"]:
                if path.suffix == ".pdf":
                    write_pdf(path, case["pages"])
                else:
                    path.write_text(case["pages"][0], encoding="utf-8", newline="")
            raw_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            parsed = parse_original(path, path.suffix[1:], raw_hash)
            fields: dict[str, Any] = {}
            for name, expectations in case["fields"].items():
                candidates = []
                for expected in expectations:
                    text = parsed.pages[expected["page"] - 1]
                    quote, raw = expected["quote"], expected["raw"]
                    if text.count(quote) != 1 or quote.count(raw) != 1:
                        raise ValueError("Authored anchor must be unique")
                    start = text.index(quote)
                    value_start = start + quote.index(raw)
                    candidates.append(
                        {
                            "accepted_raw_values": [raw],
                            "accepted_normalized_values": []
                            if expected["normalized"] is None
                            else [expected["normalized"]],
                            "normalizable": expected["normalized"] is not None,
                            "expected_validation_flags": expected["flags"],
                            "anchors": [
                                {
                                    "page": expected["page"],
                                    "quote": quote,
                                    "start": start,
                                    "end": start + len(quote),
                                    "value_start": value_start,
                                    "value_end": value_start + len(raw),
                                }
                            ],
                        }
                    )
                fields[name] = {
                    "status": ("missing", "present", "ambiguous")[len(candidates)],
                    "candidates": candidates,
                }
            cases[case["id"]] = {"fields": fields}
            documents.append(
                {
                    "id": case["id"],
                    "family": case["family"],
                    "variant": case["variant"],
                    "template_id": case["family"],
                    "identity_group": case["family"],
                    "path": case["path"],
                    "raw_sha256": raw_hash,
                    "canonical_sha256": parsed.canonical_sha256,
                }
            )
        gold_path = directory / "gold.json"
        write_json(
            gold_path,
            {
                "schema_version": "formreview-gold-v1",
                "human_review": "pending",
                "provenance": spec["provenance"],
                "cases": cases,
            },
        )
        write_json(
            directory / "manifest.json",
            {
                "schema_version": "formreview-dataset-v1",
                "split": split,
                "gold_path": "gold.json",
                "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
                "documents": documents,
            },
        )


if __name__ == "__main__":
    main()
