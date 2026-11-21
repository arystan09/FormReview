"""Isolated parser entry point. No Django, credentials, callbacks or network clients."""

import hashlib
import io
import json
import logging
import resource
import sys
import unicodedata
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
MAX_CHARACTERS = 20000


def deny_external_operations(event: str, args: tuple[object, ...]) -> None:
    if event.startswith(("socket.", "subprocess.", "os.system", "os.exec", "os.spawn")):
        raise PermissionError("External operations are disabled in the parser")


def parse(path: str, kind: str) -> dict[str, object]:
    with Path(path).open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        return {"error": "invalid_size"}
    if kind == "txt":
        try:
            pages = [data.decode("utf-8-sig")]
        except UnicodeDecodeError:
            return {"error": "invalid_utf8"}
        parser_version = "utf8-v1"
    elif kind == "pdf":
        from pypdf import PdfReader, __version__

        if not data.startswith(b"%PDF-"):
            return {"error": "malformed_pdf"}
        reader = PdfReader(io.BytesIO(data), strict=True)
        if reader.is_encrypted:
            return {"error": "encrypted_pdf"}
        if len(reader.pages) > 5:
            return {"error": "too_many_pages"}
        if not reader.pages:
            return {"error": "empty_document"}
        # pypdf reads text only. Actions, scripts, attachments and links are never executed.
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if not text.strip():
                return {"error": "no_text_page"}
            text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
            pages.append(text)
            if sum(len(item) for item in pages) > MAX_CHARACTERS:
                return {"error": "too_many_characters"}
        parser_version = f"pypdf-{__version__}-text-v1"
    else:
        return {"error": "unsupported_type"}
    pages = [
        unicodedata.normalize("NFC", page.replace("\r\n", "\n").replace("\r", "\n"))
        for page in pages
    ]
    if any(
        any(unicodedata.category(c) in {"Cc", "Cs"} and c not in "\n\t" for c in page)
        for page in pages
    ):
        return {"error": "unsupported_control_characters"}
    if not any(page.strip() for page in pages):
        return {"error": "empty_document"}
    if sum(map(len, pages)) > MAX_CHARACTERS:
        return {"error": "too_many_characters"}
    return {
        "pages": pages,
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "parser_version": parser_version,
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    # RLIMIT_AS is reliable on Linux; Compose also caps the entire worker at 512 MiB.
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (9, 9))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    sys.addaudithook(deny_external_operations)
    try:
        result = parse(sys.argv[1], sys.argv[2])
    except MemoryError:
        result = {"error": "parser_resource_limit"}
    except Exception:
        result = {"error": "malformed_pdf" if sys.argv[2] == "pdf" else "parse_failed"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
