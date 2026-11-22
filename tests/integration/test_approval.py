import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest
from django.db import DatabaseError, close_old_connections, transaction
from django.test import Client

from accounts.models import Membership, Workspace
from extraction.config import digest
from reviews.approval import approve
from reviews.models import ApprovalReceipt, ApprovedRecord, ReviewEvent
from reviews.services import ReviewConflict, save_decisions
from tests.support import decisions_for, draft_case

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def case(settings, tmp_path):
    return draft_case(settings, tmp_path)


def save(case):
    _, member, _, draft = case
    return save_decisions(member, draft.id, draft.revision, decisions_for(draft))


def test_human_approval_is_immutable_and_idempotent(case) -> None:
    client, member, document, _ = case
    draft = save(case)
    assert not ApprovedRecord.objects.exists()
    key = uuid.uuid4()
    receipt = approve(member, draft.id, draft.revision, digest(draft.decisions), key, True)
    assert (
        approve(member, draft.id, draft.revision, digest(draft.decisions), key, True).id
        == receipt.id
    )
    assert ApprovedRecord.objects.count() == 1 and ApprovalReceipt.objects.count() == 1
    assert receipt.record.fields["contact_email"] == "alder@example.test"
    assert receipt.record.snapshot["provenance"]["contact_email"]["kind"] == "manual_edit"
    assert receipt.record.snapshot["mode"] == "replay"
    assert ReviewEvent.objects.filter(action="approved").count() == 1
    for key2, revision in [(key, draft.revision + 1), (uuid.uuid4(), draft.revision)]:
        with pytest.raises(ReviewConflict):
            approve(member, draft.id, revision, digest(draft.decisions), key2, True)
    with pytest.raises(ReviewConflict):
        save_decisions(member, draft.id, draft.revision, draft.decisions)
    with pytest.raises(DatabaseError), transaction.atomic():
        ApprovedRecord.objects.filter(pk=receipt.record_id).update(fields={})
    response = client.get(f"/records/{receipt.record_id}/export")
    assert response.status_code == 200
    assert response.json()["snapshot"]["canonical_sha256"] == document.text_version.canonical_sha256


@pytest.mark.parametrize(
    "problem",
    [
        "missing_field",
        "required_missing",
        "no_reason",
        "no_provenance",
        "bad_email",
        "bad_terms",
        "unsupported_accept",
        "extra_decision",
    ],
)
def test_five_decisions_and_final_schema(case, problem) -> None:
    _, member, _, draft = case
    decisions = decisions_for(draft)
    if problem == "missing_field":
        del decisions["country"]
    elif problem == "required_missing":
        decisions["supplier_name"] = decisions["registration_id"]
    elif problem == "no_reason":
        decisions["contact_email"]["reason"] = ""
    elif problem == "no_provenance":
        decisions["contact_email"]["provenance"] = ""
    elif problem == "bad_email":
        decisions["contact_email"]["value"] = "not-email"
    elif problem == "bad_terms":
        decisions["payment_terms_days"] = {**decisions["contact_email"], "value": 366}
    elif problem == "unsupported_accept":
        decisions["contact_email"] = {
            "action": "accept",
            "candidate_id": draft.run.candidates.get(field="contact_email").pk,
            "value": None,
            "reason": "",
            "provenance": "",
        }
    else:
        decisions["country"]["approved"] = True
    with pytest.raises(ReviewConflict):
        save_decisions(member, draft.id, 1, decisions)
    assert not ReviewEvent.objects.exists() and not ApprovedRecord.objects.exists()


def test_approval_rollback(case) -> None:
    _, member, _, _ = case
    draft = save(case)
    with patch(
        "reviews.approval.ReviewEvent.objects.create",
        side_effect=DatabaseError("synthetic failure"),
    ):
        with pytest.raises(DatabaseError):
            approve(member, draft.id, draft.revision, digest(draft.decisions), uuid.uuid4(), True)
    draft.refresh_from_db()
    assert draft.status == "active"
    assert not ApprovedRecord.objects.exists() and not ApprovalReceipt.objects.exists()


def test_concurrent_save_and_approve(case) -> None:
    _, member, _, _ = case
    draft = save(case)

    def attempt(action):
        close_old_connections()
        try:
            if action == "save":
                save_decisions(member, draft.id, draft.revision, draft.decisions)
            else:
                approve(
                    member, draft.id, draft.revision, digest(draft.decisions), uuid.uuid4(), True
                )
            return "success"
        except ReviewConflict:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ["save", "approve"])) == ["conflict", "success"]
    assert ApprovedRecord.objects.count() <= 1


def test_concurrent_duplicate_approval(case) -> None:
    _, member, _, _ = case
    draft = save(case)
    key = uuid.uuid4()

    def attempt(_):
        close_old_connections()
        try:
            return approve(member, draft.id, draft.revision, digest(draft.decisions), key, True).id
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(attempt, range(2)))
    assert receipts[0] == receipts[1] and ApprovedRecord.objects.count() == 1


def test_endpoint_roles_csrf_stale_and_ownership(case) -> None:
    client, member, _, draft = case
    url = f"/api/v1/drafts/{draft.id}"
    body = {"expected_revision": 1, "decisions": decisions_for(draft)}
    assert client.patch(url, json.dumps(body), content_type="application/json").status_code == 403
    response = client.patch(
        url,
        json.dumps(body),
        content_type="application/json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert response.status_code == 200
    assert (
        client.patch(
            url,
            json.dumps(body),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        ).status_code
        == 409
    )
    assert client.post(f"/drafts/{draft.id}/approve", {}).status_code == 403
    Membership.objects.filter(pk=member.pk).update(role="viewer")
    assert (
        client.patch(
            url,
            json.dumps(body),
            content_type="application/json",
            HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
        ).status_code
        == 403
    )
    assert client.get(f"/drafts/{draft.id}").status_code == 200
    other = Workspace.objects.create(name="Other")
    Membership.objects.create(workspace=other, user=member.user, role="reviewer")
    session = client.session
    session["workspace_id"] = str(other.id)
    session.save()
    assert client.get(f"/drafts/{draft.id}").status_code == 404
    assert Client().get(f"/drafts/{draft.id}").status_code == 403
