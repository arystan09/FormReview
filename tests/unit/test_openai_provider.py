import asyncio
import json
import logging

import httpx
import pytest

from documents.models import TextVersion
from documents.parser import NORMALIZATION_VERSION, canonical_hash
from extraction.config import LIVE_MODEL, LIVE_SCHEMA_VERSION, LIVE_SETTINGS, digest, live_schema
from extraction.evidence import EVIDENCE_VERSION
from extraction.models import ExtractionConfig
from extraction.normalization import NORMALIZER_VERSION
from extraction.providers.openai import payload, request_once
from extraction.schemas import FIELD_NAMES

pytestmark = pytest.mark.unit


def configured_payload():
    values = {
        "prompt_text": "SYNTHETIC_PRIVATE_PROMPT",
        "model": LIVE_MODEL,
        "settings": LIVE_SETTINGS,
        "response_schema": live_schema(),
        "schema_version": LIVE_SCHEMA_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "evidence_version": EVIDENCE_VERSION,
    }
    config = ExtractionConfig(config_hash=digest(values), **values)
    pages = ["Synthetic source only"]
    text = TextVersion(
        pages=pages,
        canonical_sha256=canonical_hash(pages),
        parser_version="utf8-v1",
        normalization_version=NORMALIZATION_VERSION,
    )
    return payload(config, text), config


def install_transport(monkeypatch, handler):
    original = httpx.AsyncClient

    class TestClient(original):
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False
            super().__init__(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr("extraction.providers.openai.httpx.AsyncClient", TestClient)


@pytest.mark.parametrize(
    "outcome", ["success", "refusal", "truncated", "timeout", "429", "500", "400", "malformed"]
)
def test_one_sdk_request_and_safe_failures(monkeypatch, caplog, outcome) -> None:
    caplog.set_level(logging.DEBUG)
    for name in ("openai", "openai._base_client", "httpx", "httpcore"):
        monkeypatch.setattr(logging.getLogger(name), "disabled", False)
        monkeypatch.setattr(logging.getLogger(name), "level", logging.DEBUG)
    body, config = configured_payload()
    calls = []
    output = json.dumps({name: {"status": "missing", "candidates": []} for name in FIELD_NAMES})

    def handler(request):
        calls.append(request)
        assert request.url == "https://api.openai.com/v1/responses"
        sent = json.loads(request.content)
        assert sent["instructions"] == config.prompt_text
        assert sent["text"]["format"]["schema"] == config.response_schema
        assert sent["max_output_tokens"] == 3000
        assert sent["store"] is False
        assert "tools" not in sent and "labels" not in sent
        assert "SYNTHETIC_SECRET_KEY" not in request.content.decode()
        if outcome == "timeout":
            raise httpx.ReadTimeout("SYNTHETIC_SECRET_KEY private response", request=request)
        if outcome in {"429", "500", "400"}:
            return httpx.Response(
                int(outcome),
                json={
                    "error": {
                        "message": "SYNTHETIC_SECRET_KEY private output",
                        "type": "test_error",
                    }
                },
            )
        content = {
            "type": "output_text",
            "text": "not json" if outcome == "malformed" else output,
            "annotations": [],
        }
        if outcome == "refusal":
            content = {"type": "refusal", "refusal": "private refusal"}
        return httpx.Response(
            200,
            headers={"x-request-id": "req_synthetic"},
            json={
                "id": "resp_synthetic",
                "object": "response",
                "created_at": 0,
                "status": "incomplete" if outcome == "truncated" else "completed",
                "model": LIVE_MODEL,
                "output": [
                    {
                        "id": "msg_synthetic",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [content],
                    }
                ],
            },
        )

    install_transport(monkeypatch, handler)
    result = asyncio.run(request_once(body, config.settings, "SYNTHETIC_SECRET_KEY"))
    assert len(calls) == 1
    if outcome == "success":
        assert result.text == output and result.request_id == "req_synthetic"
    elif outcome == "malformed":
        assert (
            result.text == "not json"
        )  # Common persistence validator rejects it, no repair request.
    else:
        assert result.error
        assert result.unknown == (outcome in {"timeout", "500"})
    assert "SYNTHETIC_SECRET_KEY" not in caplog.text
    assert "SYNTHETIC_PRIVATE_PROMPT" not in caplog.text


def test_wall_timeout_cancels_without_retry(monkeypatch) -> None:
    body, config = configured_payload()
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json={})

    install_transport(monkeypatch, handler)
    result = asyncio.run(
        request_once(body, {**config.settings, "timeout_seconds": 0.01}, "synthetic-key")
    )
    assert result.unknown and len(calls) == 1
