import io
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, transaction
from django.utils import timezone

from extraction.config import DEFAULT_PROMPT, live_config
from extraction.live import KEY_ENV, admit, confirmation, key_fingerprint, process_live_once
from extraction.models import LiveAllowance, LiveAttempt
from extraction.providers.openai import ProviderResult
from extraction.schemas import FIELD_NAMES
from extraction.services import ReplayConflict
from tests.support import source_case

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def live_case(settings, tmp_path, monkeypatch):
    client, membership, document = source_case(settings, tmp_path)
    monkeypatch.setenv(KEY_ENV, "synthetic-key")
    config = live_config(DEFAULT_PROMPT + "\nSynthetic live adapter test.")
    policy = LiveAllowance.objects.create(
        pk=1,
        enabled=True,
        config=config,
        key_fingerprint=key_fingerprint("synthetic-key"),
        request_limit=2,
        input_price=Decimal("0.75"),
        output_price=Decimal("4.5"),
        price_checked_on=timezone.localdate(),
        price_source="https://developers.openai.com/api/docs/models/gpt-5.4-mini",
    )
    # A fail-closed fixture: every worker test must replace this before dispatch.
    monkeypatch.setattr(
        "extraction.live.request_once",
        AsyncMock(side_effect=AssertionError("Unexpected provider invocation")),
    )
    return client, membership, document, policy


def test_concurrent_admission_and_idempotency(live_case) -> None:
    _, member, document, policy = live_case
    token = confirmation(document)["token"]

    def attempt(_):
        close_old_connections()
        try:
            return admit(member, document.id, token, True).id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(attempt, range(2)))
    assert ids[0] == ids[1]
    policy.refresh_from_db()
    assert policy.consumed == 1 and LiveAttempt.objects.count() == 1
    with pytest.raises(ReplayConflict, match="in_flight"):
        admit(member, document.id, confirmation(document)["token"], True)


@pytest.mark.parametrize(
    "result",
    [
        ProviderResult(text="{}"),
        ProviderResult(text="[" * 1200 + "]" * 1200),
        ProviderResult(error="refusal"),
        ProviderResult(error="truncated"),
        ProviderResult(error="rate_limited"),
        ProviderResult(error="unknown_outcome", unknown=True),
    ],
)
def test_no_retry_and_durable_consumption(live_case, monkeypatch, result) -> None:
    _, member, document, policy = live_case
    attempt = admit(member, document.id, confirmation(document)["token"], True)
    mock = AsyncMock(return_value=result)
    monkeypatch.setattr("extraction.live.request_once", mock)
    assert process_live_once()
    assert not process_live_once()
    assert mock.call_count == 1
    policy.refresh_from_db()
    attempt.refresh_from_db()
    assert policy.consumed == 1
    assert attempt.run.mode == "live"
    assert attempt.run.status in {"invalid_output", "failed"}
    assert (policy.active_attempt is not None) == result.unknown
    with pytest.raises(DatabaseError), transaction.atomic():
        LiveAttempt.objects.filter(pk=attempt.pk).update(status="queued")
    with pytest.raises(DatabaseError), transaction.atomic():
        LiveAllowance.objects.filter(pk=1).update(consumed=0)


def test_success_payload_and_finite_limit(live_case, monkeypatch) -> None:
    import json

    client, member, document, policy = live_case
    policy.request_limit = 1
    policy.save()
    token = confirmation(document)["token"]
    attempt = admit(member, document.id, token, True)
    mock = AsyncMock(
        return_value=ProviderResult(
            text=json.dumps(
                {name: {"status": "missing", "candidates": []} for name in FIELD_NAMES}
            ),
            request_id="req_synthetic",
        )
    )
    monkeypatch.setattr("extraction.live.request_once", mock)
    process_live_once()
    attempt.refresh_from_db()
    assert attempt.run.status == "validated" and attempt.provider_request_id == "req_synthetic"
    source_html = client.get(f"/documents/{document.id}").content.decode()
    assert f"Live extraction {attempt.run_id}" in source_html
    assert f"Synthetic replay {attempt.run_id}" not in source_html
    sent_body, sent_settings, _key = mock.call_args.args
    assert sent_body["instructions"] == attempt.config.prompt_text
    assert sent_settings == attempt.config.settings
    assert "labels" not in sent_body and "review" not in sent_body
    assert admit(member, document.id, token, True).id == attempt.id
    with pytest.raises(ReplayConflict, match="exhausted"):
        admit(member, document.id, confirmation(document)["token"], True)


def test_explicit_confirmation_rate_and_policy_guards(live_case, monkeypatch, settings) -> None:
    _, member, document, policy = live_case
    token = confirmation(document)["token"]
    with pytest.raises(ReplayConflict, match="explicit"):
        admit(member, document.id, token, False)
    policy.next_admission_at = timezone.now() + timedelta(seconds=60)
    policy.save()
    with pytest.raises(ReplayConflict, match="rate_limit"):
        admit(member, document.id, token, True)
    policy.next_admission_at = None
    policy.version += 1
    policy.save()
    with pytest.raises(ReplayConflict, match="expired"):
        admit(member, document.id, token, True)
    settings.PUBLIC_DEMO = True
    with pytest.raises(ReplayConflict, match="disabled"):
        confirmation(document)
    settings.PUBLIC_DEMO = False
    attempt = admit(member, document.id, confirmation(document)["token"], True)
    monkeypatch.delenv(KEY_ENV)
    assert process_live_once()
    attempt.refresh_from_db()
    assert attempt.status == "cancelled" and attempt.run_id is None


def test_configure_command_never_replenishes(live_case, tmp_path) -> None:
    _, member, document, policy = live_case
    admit(member, document.id, confirmation(document)["token"], True)
    output = io.StringIO()
    call_command("configure_live", disable=True, stdout=output)
    policy.refresh_from_db()
    assert not policy.enabled and policy.consumed == 1
    assert "synthetic-key" not in output.getvalue()


def test_two_workers_submit_once_and_uncertain_owner_reconciliation(live_case, monkeypatch) -> None:
    import threading

    _, member, document, policy = live_case
    attempt = admit(member, document.id, confirmation(document)["token"], True)
    entered, release = threading.Event(), threading.Event()

    async def provider(*args):
        entered.set()
        assert release.wait(5)
        return ProviderResult(error="unknown_outcome", unknown=True)

    mock = AsyncMock(side_effect=provider)
    monkeypatch.setattr("extraction.live.request_once", mock)

    def worker():
        close_old_connections()
        try:
            return process_live_once()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(worker)
        try:
            assert entered.wait(5)
            assert pool.submit(worker).result(timeout=5) is False
        finally:
            release.set()
        assert first.result(timeout=5)
    assert mock.call_count == 1
    with pytest.raises(ReplayConflict, match="in_flight"):
        admit(member, document.id, confirmation(document)["token"], True)
    call_command(
        "configure_live",
        reconcile_unknown=attempt.id,
        confirm_provider_finished=True,
        stdout=io.StringIO(),
    )
    policy.refresh_from_db()
    assert policy.active_attempt is None and policy.consumed == 1
    assert not process_live_once()


def test_owner_enable_persists_full_prompt_and_public_demo_rejects_writes(
    live_case, tmp_path, settings
) -> None:
    client, _, document, policy = live_case
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Custom owner prompt for synthetic tests only.", encoding="utf-8")
    output = io.StringIO()
    call_command(
        "configure_live",
        enable=True,
        prompt_file=prompt,
        limit=1,
        input_price="0.75",
        output_price="4.50",
        price_checked_on=str(timezone.localdate()),
        price_source="https://developers.openai.com/api/docs/models/gpt-5.4-mini",
        stdout=output,
    )
    policy.refresh_from_db()
    assert policy.config.prompt_text == prompt.read_text()
    assert policy.request_limit == 1 and policy.consumed == 0
    assert "synthetic-key" not in output.getvalue()
    settings.PUBLIC_DEMO = True
    response = client.post(f"/documents/{document.id}/extractions", {"mode": "replay"})
    assert response.status_code == 403
    assert response.json()["error"] == "public_demo_read_only"


def test_paid_endpoint_requires_csrf_and_explicit_confirmation(live_case) -> None:
    client, _, document, policy = live_case
    url = f"/documents/{document.id}/extractions"
    confirmation_page = client.get(f"/documents/{document.id}/live-confirm")
    assert confirmation_page.status_code == 200
    assert b"synthetic-key" not in confirmation_page.content
    data = {"mode": "live", "confirmation_token": confirmation_page.context["token"]}
    assert client.post(url, data).status_code == 403
    csrf = client.cookies["csrftoken"].value
    assert client.post(url, data, HTTP_X_CSRFTOKEN=csrf).status_code == 409
    data["paid_confirmed"] = "yes"
    response = client.post(url, data, HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 202
    assert (
        client.post(url, data, HTTP_X_CSRFTOKEN=csrf).json()["attempt_id"]
        == response.json()["attempt_id"]
    )
    policy.refresh_from_db()
    assert policy.consumed == 1
