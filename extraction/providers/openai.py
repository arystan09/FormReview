"""One non-streaming structured response. No tools, SDK retries or configurable endpoint."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, RateLimitError

from documents.models import TextVersion
from extraction.config import LIVE_MODEL
from extraction.models import ExtractionConfig
from extraction.providers import build_request


@dataclass(frozen=True)
class ProviderResult:
    text: str = ""
    error: str = ""
    request_id: str = ""
    unknown: bool = False


def payload(config: ExtractionConfig, text: TextVersion) -> dict[str, Any]:
    request = build_request(config, text)
    if config.model != LIVE_MODEL:
        raise ValueError("live_config_required")
    stored = request["config"]
    return {
        "model": stored["model"],
        "instructions": stored["prompt_text"],
        "input": json.dumps({"pages": request["source"]["pages"]}, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "supplier_fields",
                "strict": True,
                "schema": stored["response_schema"],
            }
        },
        "max_output_tokens": stored["settings"]["max_output_tokens"],
        "reasoning": {"effort": stored["settings"]["reasoning_effort"]},
        "store": stored["settings"]["store"],
    }


async def request_once(body: dict[str, Any], settings: dict[str, Any], key: str) -> ProviderResult:
    # SDK/transport debug logging must not expose headers, canonical text or prompt contents.
    prefixes = ("openai", "httpx", "httpcore")
    names = set(logging.Logger.manager.loggerDict) | set(prefixes)
    for name in names:
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            logger = logging.getLogger(name)
            logger.disabled = True
            logger.setLevel(logging.CRITICAL + 1)
    try:
        async with httpx.AsyncClient(
            timeout=settings["timeout_seconds"], trust_env=False, follow_redirects=False
        ) as http_client:
            async with AsyncOpenAI(
                api_key=key,
                base_url="https://api.openai.com/v1",
                max_retries=settings["max_retries"],
                timeout=settings["timeout_seconds"],
                http_client=http_client,
            ) as client:
                async with asyncio.timeout(settings["timeout_seconds"]):
                    response = await client.responses.create(**body)
        request_id = response._request_id or ""
        if response.status == "incomplete":
            return ProviderResult(error="truncated", request_id=request_id)
        if response.status != "completed":
            return ProviderResult(error="unknown_outcome", request_id=request_id, unknown=True)
        for item in response.output:
            if item.type == "message":
                if any(content.type == "refusal" for content in item.content):
                    return ProviderResult(error="refusal", request_id=request_id)
        return ProviderResult(text=response.output_text, request_id=request_id)
    except RateLimitError:
        return ProviderResult(error="rate_limited")
    except (TimeoutError, APITimeoutError, APIConnectionError):
        return ProviderResult(error="unknown_outcome", unknown=True)
    except APIStatusError as error:
        return ProviderResult(
            error="unknown_outcome" if error.status_code >= 500 else "provider_rejected",
            unknown=error.status_code >= 500,
        )
    except Exception:
        # Do not expose exception messages, which may contain request/response contents.
        return ProviderResult(error="unknown_outcome", unknown=True)
