import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

NORMALIZATION_VERSION = "nfc-newline-v1;pages-json-utf8-v1"


class ParseRejected(ValueError):
    pass


@dataclass(frozen=True)
class ParsedSource:
    pages: list[str]
    canonical_sha256: str
    parser_version: str


def canonical_hash(pages: list[str]) -> str:
    serialized = json.dumps(pages, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def parse_original(path: Path, kind: str, expected_hash: str) -> ParsedSource:
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-I",
                str(Path(__file__).with_name("parser_process.py")),
                str(path),
                kind,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            env={},
        )
    except subprocess.TimeoutExpired as error:
        raise ParseRejected("parser_timeout") from error
    if result.returncode != 0:
        raise ParseRejected("parser_resource_limit")
    try:
        payload = json.loads(result.stdout)
        if "error" in payload:
            raise ParseRejected(payload["error"])
        if payload["raw_sha256"] != expected_hash:
            raise ParseRejected("original_hash_mismatch")
        pages = payload["pages"]
        if not isinstance(pages, list) or not 1 <= len(pages) <= 5:
            raise ValueError
        if not all(isinstance(page, str) for page in pages) or sum(map(len, pages)) > 20000:
            raise ValueError
        return ParsedSource(pages, canonical_hash(pages), payload["parser_version"])
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ParseRejected):
            raise
        raise ParseRejected("invalid_parser_response") from error
