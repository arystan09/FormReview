import hashlib
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from documents.parser import ParseRejected, canonical_hash, parse_original
from documents.storage import MAX_BYTES, UploadRejected, safe_filename, store_original
from scripts.generate_fixtures import write_pdf

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[2]


def parse(path: Path, kind: str = "txt"):
    return parse_original(path, kind, hashlib.sha256(path.read_bytes()).hexdigest())


def test_bom_unicode_and_canonical_hash(tmp_path: Path) -> None:
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    first.write_bytes(b"\xef\xbb\xbfCafe\xcc\x81\r\nLine\rEnd")
    second.write_text("Caf\u00e9\nLine\nEnd")
    original = first.read_bytes()
    assert parse(first).pages == ["Caf\u00e9\nLine\nEnd"]
    assert parse(first).canonical_sha256 == parse(second).canonical_sha256
    assert first.read_bytes() == original
    assert canonical_hash(["ab", "c"]) != canonical_hash(["a", "bc"])


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("malformed.pdf", "malformed_pdf"),
        ("encrypted.pdf", "encrypted_pdf"),
        ("scan_like.pdf", "no_text_page"),
        ("empty.pdf", "no_text_page"),
        ("six_pages.pdf", "too_many_pages"),
        ("invalid_utf8.txt", "invalid_utf8"),
        ("empty.txt", "invalid_size"),
    ],
)
def test_parser_negative_fixtures(fixture: str, code: str) -> None:
    with pytest.raises(ParseRejected, match=code):
        parse(ROOT / "fixtures/parser_negative" / fixture, fixture.rsplit(".", 1)[1])


@pytest.mark.parametrize("count", [20000, 20001])
def test_character_boundary(tmp_path: Path, count: int) -> None:
    path = tmp_path / "size.txt"
    path.write_text("x" * count)
    if count == 20000:
        assert len(parse(path).pages[0]) == count
    else:
        with pytest.raises(ParseRejected, match="too_many_characters"):
            parse(path)


def test_five_page_pdf(tmp_path: Path) -> None:
    path = tmp_path / "five.pdf"
    write_pdf(path, ["Synthetic page"] * 5)
    assert len(parse(path, "pdf").pages) == 5


def test_hash_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("Synthetic source")
    with pytest.raises(ParseRejected, match="original_hash_mismatch"):
        parse_original(path, "txt", "0" * 64)


def test_timeout_uses_hard_ten_second_subprocess_limit(tmp_path: Path) -> None:
    with patch(
        "documents.parser.subprocess.run", side_effect=subprocess.TimeoutExpired("parser", 10)
    ) as run:
        with pytest.raises(ParseRejected, match="parser_timeout"):
            parse_original(tmp_path / "file.pdf", "pdf", "0" * 64)
        assert run.call_args.kwargs["timeout"] == 10
        assert run.call_args.kwargs["env"] == {}


def test_real_timeout_terminates_child(tmp_path: Path) -> None:
    # Replace only the entrypoint with a sleeping fixture; use the real subprocess runner.
    child = tmp_path / "parser_process.py"
    child.write_text("import time\ntime.sleep(60)\n")
    with patch("documents.parser.__file__", str(tmp_path / "parser.py")):
        with pytest.raises(ParseRejected, match="parser_timeout"):
            parse_original(tmp_path / "file.pdf", "pdf", "0" * 64)


def test_safe_filename() -> None:
    assert safe_filename("../../secret.txt") == "secret.txt"
    assert safe_filename("C:\\private\\evil<script>.txt") == "evil_script_.txt"
    assert "/" not in safe_filename("/a/b.txt")


def test_stream_limit_and_no_overwrite(tmp_path: Path, settings) -> None:
    import io
    import uuid

    settings.PRIVATE_ROOT = tmp_path
    workspace_id, document_id = uuid.uuid4(), uuid.uuid4()
    data = b"x" * MAX_BYTES
    digest, size = store_original(io.BytesIO(data), workspace_id, document_id)
    assert size == MAX_BYTES and digest == hashlib.sha256(data).hexdigest()
    with pytest.raises(FileExistsError):
        store_original(io.BytesIO(b"replacement"), workspace_id, document_id)
    path = tmp_path / str(workspace_id) / str(document_id)
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o777 == 0o400
    with pytest.raises(UploadRejected, match="file_too_large"):
        store_original(io.BytesIO(data + b"x"), workspace_id, uuid.uuid4())
    assert len(list(path.parent.iterdir())) == 1


@pytest.mark.parametrize(
    "path",
    sorted((ROOT / "datasets/dev").glob("*.txt")) + sorted((ROOT / "datasets/dev").glob("*.pdf")),
    ids=lambda path: path.name,
)
def test_all_twelve_development_sources_parse(path: Path) -> None:
    result = parse(path, path.suffix[1:])
    assert result.pages and result.canonical_sha256


def test_canonical_not_raw_character_count(tmp_path: Path) -> None:
    path = tmp_path / "combining.txt"
    path.write_text("e\u0301" * 20000)
    assert len(parse(path).pages[0]) == 20000
