import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


def load_settings(overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "POSTGRES_", "FORMREVIEW_"))
    }
    return subprocess.run(
        [sys.executable, "-c", "import config.settings"],
        env={**environment, **overrides},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({}, "DJANGO_SECRET_KEY"),
        ({"DJANGO_SECRET_KEY": "x" * 60}, "DJANGO_ALLOWED_HOSTS"),
        (
            {"DJANGO_SECRET_KEY": "x" * 60, "DJANGO_ALLOWED_HOSTS": "*"},
            "DJANGO_ALLOWED_HOSTS",
        ),
        (
            {"DJANGO_SECRET_KEY": "x" * 60, "DJANGO_ALLOWED_HOSTS": "example.test"},
            "POSTGRES_PASSWORD",
        ),
    ],
)
def test_production_rejects_unsafe_defaults(overrides: dict[str, str], message: str) -> None:
    result = load_settings({"FORMREVIEW_ENV": "production", **overrides})
    assert result.returncode != 0
    assert message in result.stderr


def test_valid_production_settings() -> None:
    result = load_settings(
        {
            "FORMREVIEW_ENV": "production",
            "DJANGO_SECRET_KEY": "synthetic-secret-" * 5,
            "DJANGO_ALLOWED_HOSTS": "example.test,127.0.0.1",
            "POSTGRES_PASSWORD": "synthetic-database-password",
        }
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == result.stderr == ""


def test_credentials_are_not_echoed_on_failure() -> None:
    secrets = {"DJANGO_SECRET_KEY": "synthetic-short-secret", "POSTGRES_PASSWORD": "synthetic-pass"}
    result = load_settings({"FORMREVIEW_ENV": "production", **secrets})
    assert result.returncode != 0
    for secret in secrets.values():
        assert secret not in result.stdout + result.stderr


def test_environment_typo_fails_closed() -> None:
    assert load_settings({"FORMREVIEW_ENV": "prod"}).returncode != 0
