import pytest
from django.test import Client

pytestmark = pytest.mark.unit


def test_liveness_without_database(client: Client) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_liveness_rejects_post(client: Client) -> None:
    assert client.post("/health/live").status_code == 405


def test_csrf_applies_to_writes() -> None:
    client = Client(enforce_csrf_checks=True)
    assert client.post("/health/live").status_code == 403
