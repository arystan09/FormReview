# FormReview

Stage 1 of exactly 10 mandatory stages: a minimal Django foundation for supplier
onboarding extraction with evidence and human confirmation. `GET /health/live`
returns `{"status":"ok"}` without a database query. This is process liveness,
not database readiness. Django management command help is available.

No extraction, uploads, reviewer UI, worker, domain tables or model calls exist
at this stage. Replay, regex baseline and live are future distinct modes; no mock
or live AI result is demonstrated here. The keyless replay walkthrough is due
after stage 3 and full MVP after stage 4. Approved design and roadmap files were
not supplied; no substitute implementation history or roadmap is claimed.

## Quickstart

Prerequisites: Python 3.12, uv 0.13.9, Docker Engine with Compose v2 (for PostgreSQL
and container verification). `uv` can download Python 3.12 if it is absent.
Dependencies are frozen in `uv.lock`.

```sh
uv sync --frozen --all-groups
cp .env.example .env
docker compose up -d db
uv run python manage.py migrate
uv run python manage.py check
uv run python manage.py help
uv run python manage.py runserver 127.0.0.1:8000
# In another terminal:
curl --fail http://127.0.0.1:8000/health/live
```

Compose loads `.env`; local Python uses environment variables and safe development
fallbacks, not an automatic dotenv loader. Export overrides for local Python when
changing the example values. Only Django built-in migrations are present.
Liveness and unit checks do not need PostgreSQL.

```sh
make check
uv run pytest --collect-only
docker compose config --quiet
docker build -t formreview:local .
uv run python scripts/check_container.py
docker compose up -d web
```

The smoke script launches the built image with a random loopback port, checks its
default UID 10001, waits for Docker's real HTTP health check, checks HTTP from the
host, and removes its temporary container. CI runs the same checks. Test collection
requires exactly one of `unit`, `integration`, `e2e`; unknown markers are errors.
No integration/e2e workflows are claimed yet. `docker compose down` stops local
services while retaining database data; do not remove volumes unless intended.

Production requires `FORMREVIEW_ENV=production`, a unique `DJANGO_SECRET_KEY` of
at least 50 characters, explicit `DJANGO_ALLOWED_HOSTS` (include 127.0.0.1 for
health checks), and non-default `POSTGRES_PASSWORD`. HTTPS is required for all
routes except liveness; secure cookies and HSTS are enabled. Configure HTTPS
termination deliberately before deployment; no proxy headers are implicitly trusted.
Development defaults and loopback port mappings are for local use only. The image
runs non-root, with read-only application ownership and no uploaded files. Private
files, work artifacts, environment files and keys are excluded from Git/image
contexts. Paid/provider configuration does not exist in this stage.

See AGENTS.md for the permanent contracts and stage boundaries. Docker availability
and actual remote CI execution must be reported separately from source inspection.
