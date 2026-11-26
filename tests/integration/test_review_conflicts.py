import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from django.db import DatabaseError, close_old_connections, transaction

from extraction.config import digest
from extraction.services import ReplayConflict, create_draft, run_replay
from reviews.approval import approve
from reviews.models import ApprovedRecord, ReviewDraft, ReviewEvent
from reviews.services import ReviewConflict, resolve_decisions, save_decisions
from tests.support import decisions_for, draft_case

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def case(settings, tmp_path):
    return draft_case(settings, tmp_path)


def test_partial_work_is_saved_but_never_approved(case):
    client, member, _, draft = case
    decision = {
        "action": "edit",
        "candidate_id": None,
        "value": "unfinished",
        "reason": "",
        "provenance": "",
    }
    saved = save_decisions(member, draft.id, 1, {"contact_email": decision}, partial=True)
    assert saved.revision == 2 and len(saved.decisions) == 1
    assert ReviewEvent.objects.get(action="saved").decisions == saved.decisions
    with pytest.raises(ReviewConflict):
        approve(member, draft.id, 2, digest(saved.decisions), uuid.uuid4(), True)
    assert not ApprovedRecord.objects.exists()
    response = client.get(f"/api/v1/drafts/{draft.id}")
    assert response.json()["decisions"]["contact_email"]["value"] == "unfinished"
    assert response["Cache-Control"] == "no-store"
    with pytest.raises(ReviewConflict, match="stale"):
        save_decisions(member, draft.id, 1, {"contact_email": decision}, partial=True)


def test_explicit_selection_preserves_previous_binding_and_decisions(case):
    _, member, document, old = case
    old = save_decisions(member, old.id, 1, decisions_for(old))
    second = run_replay(member, document.id)
    old.refresh_from_db()
    assert old.status == "active" and old.run_id != second.id
    with pytest.raises(ReplayConflict, match="explicit"):
        create_draft(member, document.id, second.id, old.revision)
    selected = create_draft(member, document.id, second.id, old.revision, str(old.id))
    old.refresh_from_db()
    assert old.status == "superseded" and old.decisions
    assert selected.run_id == second.id and selected.decisions == {}
    assert ReviewDraft.objects.filter(document=document, status="active").count() == 1
    assert set(ReviewEvent.objects.values_list("action", flat=True)) == {
        "saved",
        "superseded",
        "selected",
    }
    with pytest.raises(ReviewConflict):
        save_decisions(member, old.id, old.revision, old.decisions)
    with pytest.raises(ReviewConflict):
        approve(member, old.id, old.revision, digest(old.decisions), uuid.uuid4(), True)
    with pytest.raises(DatabaseError), transaction.atomic():
        ReviewDraft.objects.filter(pk=old.pk).update(status="active", revision=old.revision + 1)


def test_manual_source_correction_has_separate_provenance(case):
    _, member, _, draft = case
    decisions = decisions_for(draft)
    decisions["contact_email"]["source_span"] = {
        "page": 1,
        "quote": "Email: alder@example.test",
        "value_text": "alder@example.test",
    }
    saved = save_decisions(member, draft.id, 1, decisions)
    receipt = approve(member, draft.id, saved.revision, digest(saved.decisions), uuid.uuid4(), True)
    provenance = receipt.record.snapshot["provenance"]["contact_email"]
    assert provenance["kind"] == "manual_source_correction"
    assert provenance["value_start"] >= 0 and provenance["reason"]


@pytest.mark.parametrize(
    "problem", ["wrong_page", "wrong_value", "bad_candidate", "required_missing", "optional_reason"]
)
def test_invalid_source_or_incomplete_decisions_cannot_approve(case, problem):
    _, member, _, draft = case
    decisions = decisions_for(draft)
    if problem in {"wrong_page", "wrong_value"}:
        decisions["contact_email"]["source_span"] = {
            "page": 2 if problem == "wrong_page" else 1,
            "quote": "Supplier: Alder Parts",
            "value_text": "Alder Parts",
        }
    elif problem == "bad_candidate":
        decisions["contact_email"] = {
            "action": "accept",
            "candidate_id": draft.run.candidates.get(field="contact_email").pk,
            "value": None,
            "reason": "",
            "provenance": "",
        }
    elif problem == "required_missing":
        decisions["supplier_name"] = decisions["registration_id"]
    else:
        decisions["registration_id"]["reason"] = ""
    with pytest.raises(ReviewConflict):
        resolve_decisions(draft, decisions)
    assert not ApprovedRecord.objects.exists()


def test_selection_and_approval_race_share_document_lock(case):
    _, member, document, draft = case
    draft = save_decisions(member, draft.id, 1, decisions_for(draft))
    run = run_replay(member, document.id)

    def attempt(action):
        close_old_connections()
        try:
            if action == "select":
                create_draft(member, document.id, run.id, draft.revision, str(draft.id))
            else:
                approve(
                    member, draft.id, draft.revision, digest(draft.decisions), uuid.uuid4(), True
                )
            return "success"
        except (ReplayConflict, ReviewConflict):
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, ["select", "approve"])) == ["conflict", "success"]


def test_partial_endpoint_csrf_and_unknown_keys(case):
    client, _, _, draft = case
    body = json.dumps({"expected_revision": 1, "partial": True, "decisions": {}})
    url = f"/api/v1/drafts/{draft.id}"
    assert client.patch(url, body, content_type="application/json").status_code == 403
    response = client.patch(
        url,
        body,
        content_type="application/json",
        HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value,
    )
    assert response.status_code == 200 and response.json()["validation_errors"]
