import os

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from playwright.sync_api import sync_playwright

from accounts.models import Membership, Workspace


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


@pytest.fixture
def contradictory_source(browser_seed, tmp_path, monkeypatch):
    import json

    from extraction.replay import ReplayProvider

    hostile_name = '<img src=x onerror="window.formreviewXss=1">'
    values = {
        "supplier_name": [(hostile_name, "Supplier: " + hostile_name)],
        "registration_id": [],
        "contact_email": [("review@example.test", "Email: review@example.test")],
        "country": [("Italy", "Country: Italy")],
        "payment_terms_days": [
            ("Net30", "Payment terms: Net30"),
            ("Net60", "Payment terms: Net60"),
        ],
    }
    source = tmp_path / "contradictory.txt"
    source.write_text(
        "\n".join(quote for entries in values.values() for _, quote in entries), encoding="utf-8"
    )
    output = {
        name: {
            "status": ("missing", "present", "ambiguous")[len(entries)],
            "candidates": [
                {"value_text": value, "quote": quote, "page": 1} for value, quote in entries
            ],
        }
        for name, entries in values.items()
    }
    monkeypatch.setattr(
        ReplayProvider,
        "extract",
        lambda self, request: ("synthetic-stage6-browser", json.dumps(output)),
    )
    return source
