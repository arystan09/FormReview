import asyncio
import hashlib
import os
import uuid
from datetime import timedelta
from decimal import ROUND_UP, Decimal

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from accounts.models import Membership
from documents.models import Document, TextVersion
from extraction.config import digest
from extraction.models import LiveAllowance, LiveAttempt
from extraction.providers.openai import payload, request_once
from extraction.services import ReplayConflict, persist_result, reviewer_for_document

KEY_ENV = "FORMREVIEW_OPENAI_API_KEY"
CONFIRMATION_SALT = "formreview-paid-confirmation-v1"


def key_fingerprint(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def current_policy(policy: LiveAllowance) -> None:
    if settings.PUBLIC_DEMO or not policy.enabled or policy.config_id is None:
        raise ReplayConflict("paid_mode_disabled")
    if (
        policy.price_checked_on is None
        or not 0 <= (timezone.localdate() - policy.price_checked_on).days <= 7
    ):
        raise ReplayConflict("price_estimate_expired")


def estimate(policy: LiveAllowance, text: TextVersion) -> Decimal:
    assert policy.config is not None
    body = payload(policy.config, text)
    # Conservative UTF-8-byte token approximation plus framing; not an invoice or hard cost cap.
    input_bound = len(str(body).encode("utf-8")) + 1024
    return (
        (Decimal(input_bound) * policy.input_price + Decimal(3000) * policy.output_price)
        / Decimal(1000000)
    ).quantize(Decimal("0.000001"), rounding=ROUND_UP)


def confirmation(document: Document) -> dict[str, object]:
    policy = LiveAllowance.objects.filter(pk=1).first()
    if policy is None:
        raise ReplayConflict("paid_mode_disabled")
    current_policy(policy)
    assert policy.config is not None
    text = TextVersion.objects.filter(document=document).first()
    if text is None:
        raise ReplayConflict("canonical_source_required")
    nonce = str(uuid.uuid4())
    token = signing.dumps(
        {
            "document": str(document.id),
            "text": text.pk,
            "policy_version": policy.version,
            "config_hash": policy.config.config_hash,
            "nonce": nonce,
        },
        salt=CONFIRMATION_SALT,
    )
    return {"policy": policy, "estimate": estimate(policy, text), "token": token}


@transaction.atomic
def admit(
    membership: Membership, document_id: uuid.UUID, token: str, confirmed: bool
) -> LiveAttempt:
    if not confirmed:
        raise ReplayConflict("explicit_paid_confirmation_required")
    try:
        signed = signing.loads(token, salt=CONFIRMATION_SALT, max_age=900)
        attempt_id = uuid.UUID(signed["nonce"])
    except (signing.BadSignature, KeyError, ValueError, TypeError):
        raise ReplayConflict("invalid_paid_confirmation") from None
    policy = LiveAllowance.objects.select_for_update().filter(pk=1).first()
    if policy is None:
        raise ReplayConflict("paid_mode_disabled")
    document = Document.objects.select_for_update().get(
        pk=document_id, workspace_id=membership.workspace_id
    )
    reviewer_for_document(membership, document)
    if signed["document"] != str(document.id):
        raise ReplayConflict("confirmation_document_mismatch")
    existing = LiveAttempt.objects.filter(pk=attempt_id).first()
    if existing:
        if (
            existing.requested_by_id != membership.user_id
            or existing.text_version.document_id != document.id
        ):
            raise ReplayConflict("idempotency_conflict")
        return existing
    current_policy(policy)
    assert policy.config is not None
    if (
        signed["policy_version"] != policy.version
        or signed["config_hash"] != policy.config.config_hash
    ):
        raise ReplayConflict("confirmation_expired")
    if policy.active_attempt is not None:
        raise ReplayConflict("live_request_in_flight_or_uncertain")
    if policy.consumed >= policy.request_limit:
        raise ReplayConflict("live_allowance_exhausted")
    if policy.next_admission_at and policy.next_admission_at > timezone.now():
        raise ReplayConflict("live_rate_limit")
    text = TextVersion.objects.get(pk=signed["text"], document=document)
    body = payload(policy.config, text)
    attempt = LiveAttempt.objects.create(
        id=attempt_id,
        text_version=text,
        config=policy.config,
        requested_by_id=membership.user_id,
        request_hash=digest(body),
        allowance_version=policy.version,
        estimate_usd=estimate(policy, text),
        price_snapshot={
            "input_per_million": str(policy.input_price),
            "output_per_million": str(policy.output_price),
            "checked_on": str(policy.price_checked_on),
            "source": policy.price_source,
        },
    )
    policy.consumed += 1
    policy.active_attempt = attempt.id
    policy.next_admission_at = timezone.now() + timedelta(seconds=60)
    policy.save()
    return attempt


def process_live_once() -> bool:
    # Commit the submitted marker before any network operation. There is no lease/retry path.
    with transaction.atomic():
        policy = LiveAllowance.objects.select_for_update().filter(pk=1).first()
        if policy is None or policy.active_attempt is None:
            return False
        attempt = LiveAttempt.objects.select_for_update().get(pk=policy.active_attempt)
        if attempt.status != "queued":
            return False
        key = os.environ.get(KEY_ENV, "")
        if (
            settings.PUBLIC_DEMO
            or not policy.enabled
            or not key
            or key_fingerprint(key) != policy.key_fingerprint
            or attempt.config_id != policy.config_id
        ):
            attempt.status = "cancelled"
            attempt.error_code = "worker_key_or_policy_unavailable"
            attempt.finished_at = timezone.now()
            attempt.save()
            policy.active_attempt = None
            policy.save()
            return True
        body = payload(attempt.config, attempt.text_version)
        if digest(body) != attempt.request_hash:
            raise ReplayConflict("live_payload_hash_mismatch")
        attempt.status = "submitted"
        attempt.submitted_at = timezone.now()
        attempt.save()
    result = asyncio.run(request_once(body, attempt.config.settings, key))
    with transaction.atomic():
        policy = LiveAllowance.objects.select_for_update().get(pk=1)
        locked = LiveAttempt.objects.select_for_update().get(pk=attempt.pk)
        if locked.status != "submitted":
            return True
        locked.run = persist_result(
            locked.text_version,
            locked.config,
            "live",
            locked.request_hash,
            result.text,
            provider_error=result.error,
        )
        locked.status = "unknown" if result.unknown else "done"
        locked.error_code = result.error
        locked.provider_request_id = result.request_id[:200]
        locked.finished_at = timezone.now()
        locked.save()
        if not result.unknown:
            policy.active_attempt = None
            policy.save()
    return True
