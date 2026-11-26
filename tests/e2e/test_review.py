import json

import pytest
from playwright.sync_api import expect

from tests.e2e.test_review_flow import fill_replay_decisions, upload_source
from tests.support import ROOT

pytestmark = [pytest.mark.e2e, pytest.mark.django_db(transaction=True)]


def open_replay(page, live_server, browser_seed):
    upload_source(page, live_server, browser_seed)
    page.get_by_role("button", name="Run synthetic replay").click()
    page.get_by_role("button", name="Create initial draft from this run").click()


def test_partial_two_tab_reconcile_and_stale_approval(browser_seed, live_server, review_page):
    page = review_page
    open_replay(page, live_server, browser_seed)
    draft_url = page.url
    other = page.context.new_page()
    other.goto(draft_url)
    page.get_by_label("Decision for contact_email", exact=True).select_option("edit")
    page.get_by_label("Manual value for contact_email", exact=True).fill("unfinished text")
    page.get_by_role("button", name="Save partial draft", exact=True).click()
    expect(page.get_by_role("status").filter(has_text="Saved revision")).to_contain_text(
        "More decisions"
    )
    fill_replay_decisions(other)
    other.get_by_label("Reason for contact_email", exact=True).fill("My unsaved correction")
    other.get_by_role("button", name="Save partial draft", exact=True).click()
    expect(other.get_by_role("alert")).to_contain_text("stale_or_closed_draft")
    expect(other.get_by_label("Reason for contact_email", exact=True)).to_have_value(
        "My unsaved correction"
    )
    other.get_by_role("button", name="Compare current saved decisions").click()
    expect(other.locator("#saved-comparison")).to_contain_text("unfinished text")
    other.get_by_label("I compared every saved decision and reconciled my edits.").check()
    other.get_by_role("button", name="Use current revision; keep my edits").click()
    other.get_by_role("button", name="Save decisions and review confirmation").click()
    expect(other.get_by_role("heading", name="Confirm human approval")).to_be_visible()
    # First tab explicitly reloads its stale state, then saves a newer decision set.
    page.reload()
    fill_replay_decisions(page)
    page.get_by_label("Reason for registration_id", exact=True).fill(
        "Newer reviewed missing reason"
    )
    page.get_by_role("button", name="Save decisions and review confirmation").click()
    other.get_by_label("I have reviewed all five decisions and approve this record.").check()
    other.get_by_role("button", name="Approve reviewed record").click()
    expect(other.get_by_role("heading", name="Approval needs a fresh review")).to_be_visible()
    page.get_by_label("I have reviewed all five decisions and approve this record.").check()
    page.get_by_role("button", name="Approve reviewed record").click()
    expect(page.get_by_role("heading", name="Human-approved record")).to_be_visible()


def test_evidence_keyboard_manual_span_and_explicit_run_selection(
    browser_seed, live_server, review_page
):
    page = review_page
    open_replay(page, live_server, browser_seed)
    old_url = page.url
    evidence = page.get_by_role(
        "button", name="Show evidence for supplier_name candidate 1", exact=True
    )
    evidence.focus()
    page.keyboard.press("Enter")
    expect(page.locator("#source-page-1 mark")).to_have_text("Supplier: Alder Parts")
    expect(page.locator("#source-page-1")).to_be_focused()
    fill_replay_decisions(page)
    expect(page.get_by_label("Manual value for supplier_name", exact=True)).not_to_be_visible()
    page.get_by_role("button", name="Save partial draft", exact=True).click()
    expect(page.locator("#save-status")).to_contain_text("Saved revision")
    page.get_by_role("link", name="Inspect immutable source").click()
    page.get_by_role("button", name="Run synthetic replay").click()
    expect(page.get_by_role("link", name="Open existing draft")).to_be_visible()
    page.get_by_role("button", name="Select this run and start a new draft").click()
    assert page.url != old_url
    expect(page.get_by_label("Decision for supplier_name", exact=True)).to_have_value("unresolved")
    old = page.context.new_page()
    old.goto(old_url)
    expect(old.get_by_text("This draft is read-only.", exact=False)).to_be_visible()
    fill_replay_decisions(page)
    page.get_by_text("Optional exact source span for a manual correction", exact=True).nth(
        2
    ).click()
    page.evaluate("""() => {
        const source = document.getElementById('source-page-1');
        const start = source.textContent.indexOf('alder@example.test');
        const range = document.createRange();
        range.setStart(source.firstChild, start);
        range.setEnd(source.firstChild, start + 'alder@example.test'.length);
        const selection = window.getSelection();
        selection.removeAllRanges(); selection.addRange(range);
    }""")
    page.get_by_role("button", name="Use selected source for contact_email", exact=True).click()
    expect(page.get_by_label("Exact quote for contact_email", exact=True)).to_have_value(
        "alder@example.test"
    )
    expect(page.get_by_label("Reason for contact_email", exact=True)).to_be_focused()
    page.get_by_label("Source page for contact_email", exact=True).fill("1")
    page.get_by_label("Exact quote for contact_email", exact=True).fill("Email: alder@example.test")
    page.get_by_label("Source literal for contact_email", exact=True).fill("alder@example.test")
    page.get_by_role("button", name="Save decisions and review confirmation").click()
    expect(page.get_by_text("manual_source_correction", exact=False)).to_be_visible()
    page.get_by_label("I have reviewed all five decisions and approve this record.").check()
    page.get_by_role("button", name="Approve reviewed record").click()
    with page.expect_download() as download:
        page.get_by_role("link", name="Export approved JSON").click()
    with open(download.value.path(), encoding="utf-8") as handle:
        record = json.load(handle)
    assert record["snapshot"]["provenance"]["contact_email"]["kind"] == "manual_source_correction"


def test_contradictory_terms_missing_id_and_hostile_source(
    contradictory_source, browser_seed, live_server, review_page
):
    page = review_page
    upload_source(page, live_server, browser_seed, contradictory_source)
    page.get_by_role("button", name="Run synthetic replay").click()
    page.get_by_role("button", name="Create initial draft from this run").click()
    stale = page.context.new_page()
    stale.goto(page.url)
    expect(page.locator("#field-payment_terms_days")).to_contain_text("Two candidates disagree")
    expect(page.locator("#field-registration_id")).to_contain_text("No source candidate")
    assert page.locator("img").count() == 0
    assert page.evaluate("window.formreviewXss") is None
    page.get_by_label("Decision for registration_id", exact=True).select_option("missing")
    page.get_by_label("Reason for registration_id", exact=True).fill(
        "Identifier absent from this synthetic source"
    )
    page.get_by_role("button", name="Save partial draft", exact=True).click()
    expect(page.locator("#save-status")).to_contain_text("Saved revision")
    stale.get_by_label("Decision for registration_id", exact=True).select_option("missing")
    stale.get_by_label("Reason for registration_id", exact=True).fill("My second-tab explanation")
    stale.get_by_role("button", name="Save partial draft", exact=True).click()
    expect(stale.get_by_role("alert")).to_contain_text("stale_or_closed_draft")
    expect(stale.get_by_label("Reason for registration_id", exact=True)).to_have_value(
        "My second-tab explanation"
    )
    stale.close()
    for name in ("supplier_name", "contact_email", "country", "payment_terms_days"):
        page.get_by_label(f"Decision for {name}", exact=True).select_option("accept")
        page.get_by_label(f"Candidate for {name}", exact=True).select_option(
            index=2 if name == "payment_terms_days" else 1
        )
    page.get_by_role(
        "button", name="Show evidence for payment_terms_days candidate 2", exact=True
    ).click()
    expect(page.locator("#source-page-1 mark")).to_have_text("Payment terms: Net60")
    page.set_viewport_size({"width": 1440, "height": 1000})
    page.locator("#field-payment_terms_days").scroll_into_view_if_needed()
    page.screenshot(path=str(ROOT / "work/stage6-review.png"))
    page.get_by_role("button", name="Save decisions and review confirmation").click()
    expect(page.get_by_role("heading", name="Confirm human approval")).to_be_visible()
    expect(page.get_by_role("cell", name="60", exact=True)).to_be_visible()
    assert page.locator("img").count() == 0
    page.get_by_label("I have reviewed all five decisions and approve this record.").check()
    page.get_by_role("button", name="Approve reviewed record").click()
    expect(page.get_by_role("heading", name="Human-approved record")).to_be_visible()
    assert page.evaluate("window.formreviewXss") is None
