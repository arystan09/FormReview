"""Exercise forward migration on populated stage-5 tables in a separate disposable DB."""

import os
import subprocess
import sys
import uuid

import pytest
from django.db import connection
from psycopg import sql

from tests.support import ROOT

pytestmark = [pytest.mark.integration, pytest.mark.django_db(transaction=True)]


def test_populated_stage5_upgrade_preserves_attribution(tmp_path):
    name = "test_formreview_upgrade_" + uuid.uuid4().hex[:12]
    database = connection.settings_dict
    env = {
        **os.environ,
        "POSTGRES_DB": name,
        "POSTGRES_HOST": database["HOST"],
        "POSTGRES_PORT": str(database["PORT"]),
        "POSTGRES_USER": database["USER"],
        "POSTGRES_PASSWORD": database["PASSWORD"],
        "FORMREVIEW_PRIVATE_ROOT": str(tmp_path / "private"),
    }
    env.pop("FORMREVIEW_OPENAI_API_KEY", None)
    before = tmp_path / "before.py"
    after = tmp_path / "after.py"
    state = tmp_path / "expected.json"
    before.write_text(
        """import json, uuid
from pathlib import Path
from django.conf import settings
from django.contrib.auth import get_user_model
from accounts.models import Workspace, Membership
from documents.services import upload_document, process_one_job
from extraction.services import run_replay, create_draft
from extraction.config import digest
from reviews.services import save_decisions
from reviews.approval import approve
from tests.support import decisions_for
user = get_user_model().objects.create_user(username="upgrade-synthetic")
member = Membership.objects.create(
    user=user, workspace=Workspace.objects.create(name="Upgrade"), role="reviewer")
items = []
for index in range(2):
    with open("datasets/dev/01_complete.txt", "rb") as source:
        document = upload_document(member, "synthetic.txt", source)
    assert process_one_job()
    run = run_replay(member, document.id)
    draft = create_draft(member, document.id, run.id, 0)
    draft = save_decisions(member, draft.id, 1, decisions_for(draft))
    items.append(draft)
receipt = approve(member, items[1].id, items[1].revision,
                  digest(items[1].decisions), uuid.uuid4(), True)
expected = {"active_id": str(items[0].id), "decisions": items[0].decisions,
            "revision": items[0].revision, "run_id": str(items[0].run_id),
            "receipt_id": str(receipt.id), "record_id": str(receipt.record_id),
            "snapshot": receipt.record.snapshot, "hash": receipt.record.snapshot_hash}
Path(STATE_PATH).write_text(json.dumps(expected))
""".replace("STATE_PATH", repr(str(state))),
        encoding="utf-8",
    )
    after.write_text(
        """import json
from pathlib import Path
from accounts.models import Membership
from reviews.models import ReviewDraft, ApprovalReceipt
from extraction.services import run_replay, create_draft
expected = json.loads(Path(STATE_PATH).read_text())
draft = ReviewDraft.objects.get(pk=expected["active_id"])
assert draft.decisions == expected["decisions"] and draft.revision == expected["revision"]
assert str(draft.run_id) == expected["run_id"] and draft.status == "active"
receipt = ApprovalReceipt.objects.get(pk=expected["receipt_id"])
assert str(receipt.record_id) == expected["record_id"]
assert receipt.record.snapshot == expected["snapshot"]
assert receipt.record.snapshot_hash == expected["hash"]
member = Membership.objects.get(role="reviewer")
run = run_replay(member, draft.document_id)
new = create_draft(member, draft.document_id, run.id, draft.revision, str(draft.id))
draft.refresh_from_db()
assert draft.status == "superseded" and draft.decisions == expected["decisions"]
assert new.status == "active" and new.decisions == {}
""".replace("STATE_PATH", repr(str(state))),
        encoding="utf-8",
    )

    def run(*arguments):
        result = subprocess.run(
            [sys.executable, "manage.py", *arguments],
            cwd=ROOT,
            env=env,
            capture_output=True,
            timeout=60,
        )
        assert result.returncode == 0, "Synthetic upgrade subprocess failed (content suppressed)"

    with connection.cursor() as cursor:
        cursor.execute(
            sql.SQL("CREATE DATABASE {} TEMPLATE template0 ENCODING 'UTF8'").format(
                sql.Identifier(name)
            )
        )
    try:
        run("migrate", "auth", "--noinput")
        run("migrate", "reviews", "0004", "--noinput")
        run("shell", "-c", f"exec(open({str(before)!r}).read())")
        run("migrate", "--noinput")
        run("shell", "-c", f"exec(open({str(after)!r}).read())")
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
