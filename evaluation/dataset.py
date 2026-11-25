import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from documents.parser import canonical_hash, parse_original
from evaluation.schemas import GoldCase, GoldFile, Manifest
from extraction.evidence import anchor


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path) -> Any:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)


def local_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or Path(relative).is_absolute():
        raise ValueError("dataset_path_outside_root")
    return path


@dataclass(frozen=True)
class Dataset:
    manifest: Manifest
    gold: GoldFile
    pages: dict[str, list[str]]
    dataset_hash: str
    template_fingerprints: frozenset[str]
    identities: frozenset[str]


def validate_gold(gold: GoldCase, pages: list[str]) -> None:
    for field in gold.fields.values():
        for candidate in field.candidates:
            seen: set[str] = set()
            for expected in candidate.anchors:
                if not 1 <= expected.page <= len(pages):
                    raise ValueError("gold_wrong_page")
                text = pages[expected.page - 1]
                raw = text[expected.value_start : expected.value_end]
                found = anchor(pages, expected.page, expected.quote, raw)
                if (
                    raw not in candidate.accepted_raw_values
                    or found.flags
                    or (found.quote_start, found.quote_end) != (expected.start, expected.end)
                    or (found.value_start, found.value_end)
                    != (expected.value_start, expected.value_end)
                ):
                    raise ValueError("invalid_gold_anchor")
                seen.add(raw)
            if seen != set(candidate.accepted_raw_values):
                raise ValueError("unanchored_gold_alias")


def load_dataset(path: Path) -> Dataset:
    manifest = Manifest.model_validate(load_json(path))
    gold_path = local_path(path.parent, manifest.gold_path)
    if sha256(gold_path) != manifest.gold_sha256:
        raise ValueError("gold_hash_mismatch")
    gold = GoldFile.model_validate(load_json(gold_path))
    expected_count, expected_groups = (30, 10) if manifest.split == "dev" else (18, 6)
    docs = manifest.documents
    if len(docs) != expected_count or len({d.id for d in docs}) != len(docs):
        raise ValueError("dataset_count_or_duplicate_id")
    if set(gold.cases) != {d.id for d in docs}:
        raise ValueError("gold_case_set_mismatch")
    families = Counter(d.family for d in docs)
    if len(families) != expected_groups or set(families.values()) != {3}:
        raise ValueError("family_count")
    for family in families:
        members = [d for d in docs if d.family == family]
        if {d.variant for d in members} != {1, 2, 3}:
            raise ValueError("family_variants")
        if (
            len({d.template_id for d in members}) != 1
            or len({d.identity_group for d in members}) != 1
        ):
            raise ValueError("family_metadata_mismatch")
    pages: dict[str, list[str]] = {}
    fingerprints: set[str] = set()
    identities: set[str] = set()
    for doc in docs:
        source = local_path(path.parent, doc.path)
        if source.suffix not in {".txt", ".pdf"} or sha256(source) != doc.raw_sha256:
            raise ValueError("source_type_or_hash_mismatch")
        parsed = parse_original(source, source.suffix[1:], doc.raw_sha256)
        if parsed.canonical_sha256 != doc.canonical_sha256:
            raise ValueError("canonical_hash_mismatch")
        pages[doc.id] = parsed.pages
        labels = gold.cases[doc.id]
        validate_gold(labels, parsed.pages)
        masked = "\n".join(parsed.pages)
        literals = []
        for name, field in labels.fields.items():
            for candidate in field.candidates:
                literals.extend(candidate.accepted_raw_values)
                if name in {"supplier_name", "contact_email", "registration_id"}:
                    identities.update(v.casefold() for v in candidate.accepted_raw_values)
        for literal in sorted(literals, key=len, reverse=True):
            masked = masked.replace(literal, "<value>")
        masked = re.sub(r"^Synthetic (?:development family|holdout scenario)[^\n]*\n?", "", masked)
        masked = re.sub(r"\s+", " ", masked).strip().casefold()
        fingerprints.add(canonical_hash([masked]))
    return Dataset(
        manifest,
        gold,
        pages,
        canonical_hash([sha256(path), sha256(gold_path)]),
        frozenset(fingerprints),
        frozenset(identities),
    )


def validate_split(dev: Dataset, test: Dataset) -> None:
    if (dev.manifest.split, test.manifest.split) != ("dev", "test"):
        raise ValueError("split_names")
    for attribute in (
        "id",
        "path",
        "family",
        "template_id",
        "identity_group",
        "raw_sha256",
        "canonical_sha256",
    ):
        left = {getattr(d, attribute) for d in dev.manifest.documents}
        right = {getattr(d, attribute) for d in test.manifest.documents}
        if left & right:
            raise ValueError("cross_split_" + attribute)
    if dev.identities & test.identities:
        raise ValueError("cross_split_identity_value")
    if dev.template_fingerprints & test.template_fingerprints:
        raise ValueError("cross_split_masked_template")
