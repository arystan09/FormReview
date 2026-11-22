from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import Client

from accounts.models import Membership, Workspace
from documents.services import process_one_job, upload_document
from extraction.services import create_draft, run_replay

ROOT = Path(__file__).resolve().parents[1]


def source_case(settings, tmp_path, *, username="stage4-reviewer"):
    settings.PRIVATE_ROOT = tmp_path / "private"
    user = get_user_model().objects.create_user(
        username=username, password="synthetic-test-password"
    )
    membership = Membership.objects.create(
        user=user, workspace=Workspace.objects.create(name="Synthetic review"), role="reviewer"
    )
    with (ROOT / "datasets/dev/01_complete.txt").open("rb") as stream:
        document = upload_document(membership, "01_complete.txt", stream)
    process_one_job()
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    session = client.session
    session["workspace_id"] = str(membership.workspace_id)
    session.save()
    client.get("/documents")
    return client, membership, document


def draft_case(settings, tmp_path):
    client, membership, document = source_case(settings, tmp_path)
    run = run_replay(membership, document.id)
    draft = create_draft(membership, document.id, run.id, 0)
    return client, membership, document, draft


def decisions_for(draft):
    accepted = {candidate.field: candidate for candidate in draft.run.candidates.all()}
    result = {}
    for name in ("supplier_name", "country", "payment_terms_days"):
        result[name] = {
            "action": "accept",
            "candidate_id": accepted[name].pk,
            "value": None,
            "reason": "",
            "provenance": "",
        }
    result["registration_id"] = {
        "action": "missing",
        "candidate_id": None,
        "value": None,
        "reason": "Reviewer intentionally leaves optional identifier unresolved",
        "provenance": "",
    }
    result["contact_email"] = {
        "action": "edit",
        "candidate_id": None,
        "value": "alder@example.test",
        "reason": "Replay quote was unsupported; corrected against source",
        "provenance": "Page 1, Email line",
    }
    return result
