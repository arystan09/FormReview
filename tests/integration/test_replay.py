import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client

from accounts.models import Membership, Workspace
from documents.services import process_one_job, upload_document
from extraction.api import preview_context
from extraction.config import DEFAULT_PROMPT, digest, executable_config, replay_config
from extraction.models import ExtractionConfig, ExtractionRun, FieldCandidate
from extraction.providers import build_request, request_hash
from extraction.replay import ReplayProvider
from extraction.services import ReplayConflict, create_draft, run_replay
from reviews.models import ReviewDraft

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def context(tmp_path, settings):
    assert connection.vendor == "postgresql"
    settings.PRIVATE_ROOT = tmp_path / "private"
    workspace = Workspace.objects.create(name="Replay workspace")
    user = get_user_model().objects.create_user(username="replay-user")
    membership = Membership.objects.create(user=user, workspace=workspace, role="reviewer")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    session = client.session
    session["workspace_id"] = str(workspace.pk)
    session.save()
    client.get("/documents")
    return client, membership


def source(membership, filename="01_complete.txt"):
    path = ROOT / "datasets/dev" / filename
    with path.open("rb") as stream:
        document = upload_document(membership, filename, stream)
    assert process_one_job()
    return document


def post(client, url, **data):
    return client.post(url, {"csrfmiddlewaretoken": client.cookies["csrftoken"].value, **data})


def test_replay_preview_and_explicit_draft(context) -> None:
    client, membership = context
    document = source(membership)
    response = post(client, f"/documents/{document.id}/extractions", mode="replay")
    assert response.status_code == 201
    run = ExtractionRun.objects.get(pk=response.json()["id"])
    assert not ReviewDraft.objects.exists()
    assert run.field_flags["registration_id"] == ["missing"]
    assert run.field_flags["contact_email"] == ["quote_missing"]
    supplier = run.candidates.get(field="supplier_name")
    page = run.text_version.pages[0]
    assert page[supplier.quote_start : supplier.quote_end] == supplier.quote
    assert supplier.flags == []
    email = run.candidates.get(field="contact_email")
    assert email.quote_start is None
    context = preview_context(run)
    assert context["fields"][0]["candidates"][0]["highlight"]["quote"] == "Supplier: Alder Parts"
    response = client.get(f"/extractions/{run.id}")
    assert response.status_code == 200
    assert b"<mark>Supplier: Alder Parts</mark>" in response.content
    assert b"Synthetic replay" in response.content and b"quote_missing" in response.content
    assert b"approval is available only after explicit human review" in response.content
    assert client.get(f"/api/v1/extractions/{run.id}").json()["mode"] == "replay"
    created = post(client, f"/documents/{document.id}/drafts", run_id=run.id, expected_revision=0)
    assert created.status_code == 201
    draft = ReviewDraft.objects.get(pk=created.json()["id"])
    assert draft.run_id == run.id and draft.text_version_id == run.text_version_id
    assert client.get(f"/drafts/{draft.id}").status_code == 200
    later = run_replay(membership, document.id)
    draft.refresh_from_db()
    assert draft.run_id == run.id and draft.revision == 1
    assert (
        post(
            client, f"/documents/{document.id}/drafts", run_id=later.id, expected_revision=1
        ).status_code
        == 409
    )
    assert (
        post(
            client, f"/documents/{document.id}/drafts", run_id=run.id, expected_revision=0
        ).status_code
        == 409
    )
    assert (
        post(
            client, f"/documents/{document.id}/drafts", run_id=run.id, expected_revision=1
        ).status_code
        == 201
    )


def test_config_payload_is_actual_stored_content_without_labels(context) -> None:
    _, membership = context
    document = source(membership)
    first_config = replay_config()
    changed = replay_config(DEFAULT_PROMPT + "\nSynthetic config propagation test.")
    provider = ReplayProvider.extract
    captured = []

    def recording(self, request):
        captured.append(request)
        return provider(self, request)

    with patch.object(ReplayProvider, "extract", recording):
        first = run_replay(membership, document.id, first_config)
        second = run_replay(membership, document.id, changed)
    assert captured[1]["config"] == executable_config(changed)
    assert captured[1]["config"]["prompt_text"] == changed.prompt_text
    assert captured[1]["config"]["response_schema"] == changed.response_schema
    assert first.config_hash != second.config_hash and first.request_hash != second.request_hash
    assert digest(executable_config(changed)) == changed.config_hash
    assert request_hash(captured[1]) == second.request_hash
    assert set(captured[1]) == {"config", "config_hash", "source"}
    assert set(captured[1]["source"]) == {
        "pages",
        "canonical_sha256",
        "parser_version",
        "normalization_version",
    }
    create_draft(membership, document.id, first.id, 0)
    assert build_request(changed, second.text_version) == captured[1]
    # Neither labels nor review tables are provider-request inputs.
    assert "labels" not in captured[1] and "decisions" not in captured[1]


def test_immutable_config_outputs_and_reference_integrity(context) -> None:
    _, membership = context
    document = source(membership)
    run = run_replay(membership, document.id)
    candidate = run.candidates.first()
    for model, pk, update in [
        (ExtractionConfig, run.config_id, {"prompt_text": "changed"}),
        (ExtractionRun, run.id, {"mode": "live"}),
        (FieldCandidate, candidate.pk, {"quote": "changed"}),
    ]:
        with pytest.raises(DatabaseError), transaction.atomic():
            model.objects.filter(pk=pk).update(**update)
    other = source(membership, "03_missing_optional.txt")
    with pytest.raises(DatabaseError), transaction.atomic():
        ReviewDraft.objects.create(document=other, run=run, text_version=run.text_version)


@pytest.mark.parametrize(
    "filename",
    sorted(path.name for path in (ROOT / "datasets/dev").glob("*.txt"))
    + sorted(path.name for path in (ROOT / "datasets/dev").glob("*.pdf")),
)
def test_all_development_replays(context, filename) -> None:
    client, membership = context
    document = source(membership, filename)
    run = run_replay(membership, document.id)
    assert run.status == "validated"
    assert client.get(f"/extractions/{run.id}").status_code == 200
    if filename == "08_two_pages.pdf":
        assert run.field_flags["country"] == ["wrong_page"]
    if filename == "04_ambiguous_email.txt":
        assert run.field_flags["contact_email"] == ["ambiguous"]
    if filename == "10_out_of_range.pdf":
        assert run.candidates.get(field="payment_terms_days").normalized_value is None


@pytest.mark.parametrize("response", ["not json", "{}", "\x00", json.dumps({"confidence": 99})])
def test_invalid_outputs_never_create_candidates_or_drafts(context, response) -> None:
    _, membership = context
    document = source(membership)
    with patch.object(ReplayProvider, "extract", return_value=("synthetic-malformed", response)):
        run = run_replay(membership, document.id)
    assert run.status == "invalid_output"
    assert not run.candidates.exists()
    with pytest.raises(ReplayConflict, match="valid_owned_run_required"):
        create_draft(membership, document.id, run.id, 0)


def test_csrf_roles_ownership_and_no_live(context) -> None:
    client, membership = context
    document = source(membership)
    url = f"/documents/{document.id}/extractions"
    assert client.post(url, {"mode": "replay"}).status_code == 403
    assert post(client, url, mode="live").status_code == 409
    run = run_replay(membership, document.id)
    draft = create_draft(membership, document.id, run.id, 0)
    assert (
        client.post(
            f"/documents/{document.id}/drafts", {"run_id": run.id, "expected_revision": 1}
        ).status_code
        == 403
    )
    Membership.objects.filter(pk=membership.pk).update(role="viewer")
    assert post(client, url, mode="replay").status_code == 403
    assert client.get(f"/extractions/{run.id}").status_code == 200
    assert b"Create initial draft" not in client.get(f"/extractions/{run.id}").content
    outsider = Workspace.objects.create(name="Other workspace")
    other = Membership.objects.create(workspace=outsider, user=membership.user, role="reviewer")
    other_document = source(other)
    assert (
        post(
            client, f"/documents/{document.id}/drafts", run_id=run.id, expected_revision=1
        ).status_code
        == 403
    )
    session = client.session
    session["workspace_id"] = str(outsider.id)
    session.save()
    for path in [f"/extractions/{run.id}", f"/api/v1/extractions/{run.id}", f"/drafts/{draft.id}"]:
        assert client.get(path).status_code == 404
    assert post(client, url, mode="replay").status_code == 404
    assert (
        post(
            client, f"/documents/{other_document.id}/drafts", run_id=run.id, expected_revision=0
        ).status_code
        == 409
    )
    client.logout()
    assert client.get(f"/api/v1/extractions/{run.id}").status_code == 403


def test_unknown_source_does_not_fabricate_replay(context) -> None:
    _, membership = context
    document = upload_document(membership, "unknown.txt", io.BytesIO(b"Unknown synthetic source"))
    process_one_job()
    with pytest.raises(ReplayConflict, match="no_synthetic_replay_fixture"):
        run_replay(membership, document.id)
    assert not ExtractionRun.objects.exists()


def test_concurrent_draft_creation_has_one_winner(context) -> None:
    _, membership = context
    document = source(membership)
    run = run_replay(membership, document.id)

    def attempt(_):
        close_old_connections()
        try:
            create_draft(membership, document.id, run.id, 0)
            return "created"
        except ReplayConflict:
            return "conflict"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(attempt, range(2))) == ["conflict", "created"]
    assert ReviewDraft.objects.count() == 1


def test_hash_tampering_and_unsupported_config_fail_closed(context) -> None:
    _, membership = context
    document = source(membership)
    config = replay_config()
    config.prompt_text = "Modified without a new content hash"
    with pytest.raises(ValueError, match="config_hash_mismatch"):
        build_request(config, document.text_version)
    config.config_hash = digest(executable_config(config))
    config.settings = {"max_output_tokens": 999999}
    config.config_hash = digest(executable_config(config))
    with pytest.raises(ValueError, match="unsupported_settings"):
        build_request(config, document.text_version)
    assert not ExtractionRun.objects.exists()


def test_untrusted_candidate_highlight_is_template_escaped(context) -> None:
    client, membership = context
    text = "<script>alert('synthetic')</script>"
    document = upload_document(membership, "untrusted.txt", io.BytesIO(text.encode()))
    process_one_job()
    from extraction.schemas import FIELD_NAMES

    output = {name: {"status": "missing", "candidates": []} for name in FIELD_NAMES}
    output["supplier_name"] = {
        "status": "present",
        "candidates": [{"page": 1, "value_text": text, "quote": text}],
    }
    with patch.object(
        ReplayProvider, "extract", return_value=("synthetic-html", json.dumps(output))
    ):
        run = run_replay(membership, document.id)
    rendered = client.get(f"/extractions/{run.id}").content
    assert b"<script>" not in rendered
    assert b"<mark>&lt;script&gt;" in rendered
