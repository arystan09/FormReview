import hashlib
import io
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client
from django.utils import timezone

from accounts.models import Membership, Workspace
from documents.models import Document, Job, TextVersion
from documents.services import process_one_job, upload_document
from documents.storage import MAX_BYTES, artifact_path

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def context(tmp_path, settings):
    assert connection.vendor == "postgresql", "Integration tests require real PostgreSQL"
    settings.PRIVATE_ROOT = tmp_path / "private"
    workspace = Workspace.objects.create(name="Synthetic workspace")
    user = get_user_model().objects.create_user(username="reviewer", password="synthetic-password")
    membership = Membership.objects.create(workspace=workspace, user=user, role="reviewer")
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    session = client.session
    session["workspace_id"] = str(workspace.id)
    session.save()
    client.get("/documents")
    return client, membership


def post_file(client, path, **extra):
    with path.open("rb") as source:
        return client.post(
            "/api/v1/documents",
            {"file": source, "csrfmiddlewaretoken": client.cookies["csrftoken"].value, **extra},
        )


def test_upload_worker_and_owned_canonical_source(context, settings) -> None:
    client, membership = context
    source = ROOT / "datasets/dev/02_bom_unicode.txt"
    response = post_file(client, source)
    assert response.status_code == 202
    document = Document.objects.get(pk=response.json()["id"])
    assert document.workspace_id == membership.workspace_id
    assert document.parse_job.status == "queued"
    assert not TextVersion.objects.exists()
    assert artifact_path(document.workspace_id, document.id).read_bytes() == source.read_bytes()
    # Separate process, same real PostgreSQL database; never an inline HTTP parser.
    database = connection.settings_dict
    environment = {
        **os.environ,
        "POSTGRES_DB": database["NAME"],
        "POSTGRES_HOST": database["HOST"],
        "POSTGRES_PORT": str(database["PORT"]),
        "POSTGRES_USER": database["USER"],
        "POSTGRES_PASSWORD": database["PASSWORD"],
        "FORMREVIEW_PRIVATE_ROOT": str(settings.PRIVATE_ROOT),
    }
    result = subprocess.run(
        [sys.executable, "manage.py", "process_jobs", "--once"],
        env=environment,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    text = client.get(f"/documents/{document.id}/text").json()
    assert text["pages"][0].startswith("Supplier: Caf\u00e9 Parts\n")
    assert text["raw_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert client.get(f"/documents/{document.id}").status_code == 200
    assert artifact_path(document.workspace_id, document.id).read_bytes() == source.read_bytes()


def test_pdf_and_rejected_scan(context) -> None:
    client, _ = context
    good = post_file(client, ROOT / "datasets/dev/08_two_pages.pdf")
    bad = post_file(client, ROOT / "fixtures/parser_negative/scan_like.pdf")
    call_command("process_jobs", once=True)
    assert len(client.get(f"/documents/{good.json()['id']}/text").json()["pages"]) == 2
    rejected = Document.objects.get(pk=bad.json()["id"])
    assert rejected.parse_job.status == "failed"
    assert rejected.parse_job.error_code == "no_text_page"
    assert client.get(f"/documents/{rejected.id}/text").status_code == 404
    assert b"no_text_page" in client.get(f"/documents/{rejected.id}").content


def test_tenant_and_role_access(context) -> None:
    client, membership = context
    document = upload_document(membership, "source.txt", io.BytesIO(b"Synthetic source"))
    process_one_job()
    outsider = get_user_model().objects.create_user(username="outsider")
    other_workspace = Workspace.objects.create(name="Other")
    Membership.objects.create(user=outsider, workspace=other_workspace, role="reviewer")
    client.force_login(outsider)
    session = client.session
    session["workspace_id"] = str(other_workspace.id)
    session.save()
    assert client.get("/api/v1/documents").json() == {"documents": []}
    for suffix in ["", "/text"]:
        assert client.get(f"/documents/{document.id}{suffix}").status_code == 404
    session["workspace_id"] = str(membership.workspace_id)
    session.save()
    assert client.get("/api/v1/documents").status_code == 403
    client.force_login(membership.user)
    session = client.session
    session["workspace_id"] = str(membership.workspace_id)
    session.save()
    Membership.objects.filter(pk=membership.pk).update(role="viewer")
    assert client.get(f"/documents/{document.id}/text").status_code == 200
    assert post_file(client, ROOT / "datasets/dev/01_complete.txt").status_code == 403
    Membership.objects.filter(pk=membership.pk).delete()
    assert client.get(f"/documents/{document.id}").status_code == 403
    client.logout()
    assert client.get(f"/documents/{document.id}/text").status_code == 403
    assert client.post("/api/v1/documents", {}).status_code == 403


def test_csrf_login_logout_and_upload(context) -> None:
    client, _ = context
    with (ROOT / "datasets/dev/01_complete.txt").open("rb") as source:
        assert client.post("/api/v1/documents", {"file": source}).status_code == 403
    assert not Document.objects.exists()
    assert client.post("/accounts/logout").status_code == 403
    assert client.get("/accounts/logout").status_code == 405
    assert client.post("/accounts/workspaces", {}).status_code == 403
    anonymous = Client(enforce_csrf_checks=True)
    assert (
        anonymous.post(
            "/accounts/login", {"username": "reviewer", "password": "synthetic-password"}
        ).status_code
        == 403
    )
    anonymous.get("/accounts/login")
    response = anonymous.post(
        "/accounts/login",
        {
            "username": "reviewer",
            "password": "synthetic-password",
            "csrfmiddlewaretoken": anonymous.cookies["csrftoken"].value,
        },
    )
    assert response.status_code == 302
    assert anonymous.get("/accounts/workspaces").status_code == 200


def test_body_and_file_size_limits(context, tmp_path) -> None:
    client, _ = context
    for size in [MAX_BYTES, MAX_BYTES + 1, MAX_BYTES + 65537]:
        path = tmp_path / "limit.txt"
        path.write_bytes(b"x" * size)
        response = post_file(client, path)
        assert response.status_code == (202 if size == MAX_BYTES else 413)
    assert Document.objects.count() == 1
    assert (
        client.post(
            "/api/v1/documents", data=b"", content_type="multipart/form-data", CONTENT_LENGTH=""
        ).status_code
        == 411
    )
    assert (
        client.post("/api/v1/documents", data="remote url", content_type="text/plain").status_code
        == 415
    )


def test_database_immutability(context) -> None:
    _, membership = context
    document = upload_document(membership, "source.txt", io.BytesIO(b"Synthetic source"))
    process_one_job()
    with pytest.raises(DatabaseError), transaction.atomic():
        Document.objects.filter(pk=document.pk).update(raw_sha256="0" * 64)
    with pytest.raises(DatabaseError), transaction.atomic():
        TextVersion.objects.filter(document=document).update(pages=["changed"])


def test_parallel_workers_and_stale_lease(context) -> None:
    _, membership = context
    for index in range(4):
        upload_document(membership, f"{index}.txt", io.BytesIO(b"Synthetic source"))

    def drain():
        close_old_connections()
        try:
            while process_one_job():
                pass
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: drain(), range(2)))
    assert TextVersion.objects.count() == 4
    assert set(Job.objects.values_list("attempts", flat=True)) == {1}
    document = upload_document(membership, "crashed.txt", io.BytesIO(b"Recovered source"))
    Job.objects.filter(document=document).update(
        status="running", lease_until=timezone.now() - timedelta(seconds=1), attempts=1
    )
    assert process_one_job()
    assert TextVersion.objects.filter(document=document).exists()


def test_readiness(context) -> None:
    assert Client().get("/health/ready").json() == {"status": "ready"}


def test_workspace_selection_and_untrusted_body(context) -> None:
    client, membership = context
    token = client.cookies["csrftoken"].value
    assert (
        client.post(
            "/accounts/workspaces", {"membership": "invalid", "csrfmiddlewaretoken": token}
        ).status_code
        == 404
    )
    workspace = Workspace.objects.create(name="Unowned")
    other_user = get_user_model().objects.create_user(username="other-selection")
    other = Membership.objects.create(workspace=workspace, user=other_user, role="reviewer")
    assert (
        client.post(
            "/accounts/workspaces", {"membership": other.pk, "csrfmiddlewaretoken": token}
        ).status_code
        == 404
    )
    response = post_file(
        client, ROOT / "datasets/dev/01_complete.txt", workspace_id=str(workspace.id), role="owner"
    )
    assert Document.objects.get(pk=response.json()["id"]).workspace_id == membership.workspace_id


def test_source_html_is_escaped_and_no_raw_file_route(context) -> None:
    client, membership = context
    document = upload_document(
        membership, "source.txt", io.BytesIO(b"<script>alert('untrusted')</script>")
    )
    process_one_job()
    response = client.get(f"/documents/{document.id}")
    assert b"<script>" not in response.content
    assert b"&lt;script&gt;" in response.content
    assert response["Cache-Control"] == "no-store"
    assert client.get(f"/private/{membership.workspace_id}/{document.id}").status_code == 404


def test_unsupported_extension_does_not_enqueue(context, tmp_path) -> None:
    client, _ = context
    path = tmp_path / "unsupported.docx"
    path.write_bytes(b"synthetic unsupported")
    assert post_file(client, path).status_code == 400
    assert not Document.objects.exists()


def test_exhausted_lease_fails_safely(context) -> None:
    _, membership = context
    document = upload_document(membership, "crashed.txt", io.BytesIO(b"Synthetic source"))
    Job.objects.filter(document=document).update(
        status="running", attempts=3, lease_until=timezone.now() - timedelta(seconds=1)
    )
    assert process_one_job()
    job = Job.objects.get(document=document)
    assert job.status == "failed" and job.error_code == "worker_interrupted"
    assert not TextVersion.objects.filter(document=document).exists()


def test_bootstrap_command_prompts_and_does_not_echo_password(context, monkeypatch) -> None:
    import getpass

    password = "synthetic-bootstrap-password"
    monkeypatch.setattr(getpass, "getpass", lambda _: password)
    output = io.StringIO()
    call_command(
        "bootstrap_workspace", username="bootstrap-user", workspace="Bootstrapped", stdout=output
    )
    user = get_user_model().objects.get(username="bootstrap-user")
    assert user.check_password(password)
    assert Membership.objects.get(user=user).role == "reviewer"
    assert password not in output.getvalue()


def test_login_multipart_body_is_also_bounded() -> None:
    client = Client(enforce_csrf_checks=True)
    assert (
        client.post(
            "/accounts/login", data=b"x" * 65537, content_type="application/octet-stream"
        ).status_code
        == 413
    )
