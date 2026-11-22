import json
import os
import subprocess
import sys

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from playwright.sync_api import expect, sync_playwright

from accounts.models import Membership, Workspace
from tests.support import ROOT

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


@pytest.fixture
def browser_seed(settings, tmp_path, transactional_db):
    settings.PRIVATE_ROOT = tmp_path / "private"
    settings.PUBLIC_DEMO = False
    user = get_user_model().objects.create_user(
        username="browser-reviewer", password="synthetic-test-password"
    )
    Membership.objects.create(
        user=user,
        workspace=Workspace.objects.create(name="Browser synthetic workspace"),
        role="reviewer",
    )
    database = connection.settings_dict
    env = {
        **os.environ,
        "POSTGRES_DB": database["NAME"],
        "POSTGRES_HOST": database["HOST"],
        "POSTGRES_PORT": str(database["PORT"]),
        "POSTGRES_USER": database["USER"],
        "POSTGRES_PASSWORD": database["PASSWORD"],
        "FORMREVIEW_PRIVATE_ROOT": str(settings.PRIVATE_ROOT),
    }
    env.pop("FORMREVIEW_OPENAI_API_KEY", None)
    return env


@pytest.fixture
def review_page(browser_seed, live_server):
    # Keep Playwright's event loop inside this fixture, after DB setup and before teardown.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        yield context.new_page()
        context.close()
        browser.close()


def fill_replay_decisions(page):
    for name in ["supplier_name", "country", "payment_terms_days"]:
        page.get_by_label(f"Decision for {name}", exact=True).select_option("accept")
        page.get_by_label(f"Candidate for {name}", exact=True).select_option(index=1)
    page.get_by_label("Decision for registration_id", exact=True).select_option("missing")
    page.get_by_label("Reason for registration_id", exact=True).fill(
        "Optional identifier left unresolved for this synthetic record"
    )
    page.get_by_label("Decision for contact_email", exact=True).select_option("edit")
    page.get_by_label("Manual value for contact_email", exact=True).fill("alder@example.test")
    page.get_by_label("Reason for contact_email", exact=True).fill(
        "Corrected unsupported replay quote"
    )
    page.get_by_label("Provenance for contact_email", exact=True).fill("Page 1 Email line")


def upload_source(page, live_server, browser_seed):
    page.goto(live_server.url + "/accounts/login")
    page.get_by_label("Username:", exact=True).fill("browser-reviewer")
    page.get_by_label("Password:", exact=True).fill("synthetic-test-password")
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("button", name="Open workspace").click()
    page.get_by_label("Document", exact=True).set_input_files(
        str(ROOT / "datasets/dev/01_complete.txt")
    )
    page.get_by_role("button", name="Upload for parsing").click()
    expect(page.get_by_text("Parse status:", exact=False)).to_contain_text("queued")
    result = subprocess.run(
        [sys.executable, "manage.py", "process_jobs", "--once"],
        cwd=ROOT,
        env=browser_seed,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0
    page.reload()
    expect(page.get_by_text("Parse status:", exact=False)).to_contain_text("succeeded")


def test_replay_human_edit_approve_export(browser_seed, live_server, review_page) -> None:
    page = review_page
    upload_source(page, live_server, browser_seed)
    page.get_by_role("button", name="Run synthetic replay").click()
    expect(page.get_by_text("Manual review flags: quote_missing", exact=True)).to_be_visible()
    page.get_by_role("button", name="Create initial draft from this run").click()
    expect(page.get_by_role("heading", name="Review all five fields")).to_be_visible()
    stale = page.context.new_page()
    stale.goto(page.url)
    fill_replay_decisions(page)
    page.get_by_role("button", name="Save decisions and review confirmation").click()
    expect(page.get_by_role("heading", name="Confirm human approval")).to_be_visible()
    fill_replay_decisions(stale)
    stale.get_by_role("button", name="Save decisions and review confirmation").click()
    expect(stale.get_by_role("alert")).to_contain_text("stale_or_closed_draft")
    stale.close()
    page.get_by_label("I have reviewed all five decisions and approve this record.").check()
    page.get_by_role("button", name="Approve reviewed record").click()
    expect(page.get_by_role("heading", name="Human-approved record")).to_be_visible()
    expect(page.get_by_text("The extraction was synthetic replay", exact=False)).to_be_visible()
    with page.expect_download() as download:
        page.get_by_role("link", name="Export approved JSON").click()
    record = json.loads(open(download.value.path(), encoding="utf-8").read())
    assert record["fields"]["contact_email"] == "alder@example.test"
    assert record["fields"]["payment_terms_days"] == 30
    assert record["snapshot"]["mode"] == "replay"
    assert record["snapshot"]["provenance"]["contact_email"]["kind"] == "manual_edit"
    page.screenshot(path=str(ROOT / "work/stage4-approved-record.png"), full_page=True)
    page.get_by_role("link", name="View canonical source").click()
    page.get_by_role("link", name="Open approved record and export").click()
    expect(page.get_by_role("heading", name="Human-approved record")).to_be_visible()


def test_manual_only_fallback(browser_seed, live_server, review_page) -> None:
    page = review_page
    upload_source(page, live_server, browser_seed)
    page.get_by_role("button", name="Create manual-only draft").click()
    expect(page.get_by_text("Manual-only fallback", exact=False)).to_be_visible()
    values = {
        "supplier_name": "Alder Parts",
        "contact_email": "alder@example.test",
        "registration_id": "001-AB",
        "country": "Italy",
        "payment_terms_days": "30",
    }
    for name, value in values.items():
        page.get_by_label(f"Decision for {name}", exact=True).select_option("edit")
        page.get_by_label(f"Manual value for {name}", exact=True).fill(value)
        page.get_by_label(f"Reason for {name}", exact=True).fill("Manual-only synthetic review")
        page.get_by_label(f"Provenance for {name}", exact=True).fill(
            "Page 1, reviewer transcribed source"
        )
    page.get_by_role("button", name="Save decisions and review confirmation").click()
    expect(page.get_by_role("heading", name="Confirm human approval")).to_be_visible()
    page.get_by_label("I have reviewed all five decisions and approve this record.").check()
    page.get_by_role("button", name="Approve reviewed record").click()
    expect(page.get_by_text("Manual-only fallback; no AI result.", exact=False)).to_be_visible()
