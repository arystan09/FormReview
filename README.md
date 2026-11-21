# FormReview

Stage 3 of exactly **10 mandatory stages**: owned documents now support a keyless
synthetic extraction-to-review preview. Source evidence is anchored by the server,
with explicit manual-review flags and an immutable executable config. The keyless
walkthrough milestone is implemented; the full MVP remains due after stage 4.
There is no approval, live provider, paid mode or regex baseline in this stage.

## Keyless replay walkthrough

Use the local setup below, sign in as a reviewer and select your workspace. Upload
`datasets/dev/01_complete.txt`, let `process_jobs` parse it, then open its source
page and click **Run synthetic replay**. The preview shows:

- supplier_name: an exact server-highlighted source quote;
- registration_id: deliberately missing in the synthetic output;
- contact_email: deliberately unsupported quote, flagged `quote_missing`, no offset.

Click **Create initial draft from this run** to bind a revision-1 preview to that
explicit run and immutable text version. A later extraction does not replace this
draft. `04_ambiguous_email.txt` demonstrates two source candidates, while
`08_two_pages.pdf` deliberately claims the wrong page. No key is needed. Only the
12 bundled development sources have replay outputs; arbitrary source hashes return
`no_synthetic_replay_fixture` without inventing results.

Replay responses are authored examples with intentional errors, not model results,
a regex baseline or gold labels. The provider receives the stored full prompt,
model, settings, schema, versions and canonical pages; an allowlist excludes labels,
review decisions, user/workspace authority and filenames. A prompt change changes
config/request hashes but does not change an authored replay response. The initial
prompt constant is used only when creating a config; requests use the persisted
config contents and verify its hash/schema/version compatibility.

POST `/documents/{id}/extractions` requires a reviewer session, CSRF and form field
`mode=replay`. GET `/api/v1/extractions/{id}` exposes owned candidates/flags;
GET `/extractions/{id}` shows the source/field preview. POST
`/documents/{id}/drafts` requires `run_id` and `expected_revision=0` for initial
creation. Existing drafts require their exact revision and same run for an
idempotent response; stale revisions and replacement runs receive 409. GET
`/drafts/{id}` shows the owned draft. No editing or approval endpoint exists yet.

The strict contract requires all five fields, 1/0/2 distinct candidates for
present/missing/ambiguous, and no extras or confidence/offset fields. Quotes are
1–500 characters, values 1–256, claimed pages 1–5. Offsets are half-open Python
Unicode code-point indices into immutable canonical pages, never model output.
Repeated quotes anywhere in the source, missing/wrong-page quotes, absent or
repeated value substrings, missing/ambiguous fields and unresolved terms are
flagged. Exact quote membership does not prove semantic truth. Candidate values
are preserved; only full lexical NetN/Ndays patterns normalize to integers 0–365.
Config, run and candidate records are immutable under PostgreSQL triggers, and
DB constraints validate run hashes and draft source/run references.

Run the requested stage-specific checks against a disposable PostgreSQL server:

```sh
uv run pytest tests/unit/test_evidence.py tests/unit/test_extraction_contract.py tests/integration/test_replay.py
```

These tests replay all 12 real canonical development sources and inspect their
pages. See extraction/fixtures/README.md for the synthetic-output provenance.

## Run locally

Prerequisites: Python 3.12, uv 0.13.9 and PostgreSQL 18 with UTF-8 encoding. Docker
Engine/Compose v2 provides PostgreSQL and the deployment verification environment.
Dependencies are frozen in uv.lock. macOS can run development parsing, but only
Linux enforces the parser address-space limit used by the deployment.

```sh
uv sync --frozen --all-groups
cp .env.example .env
docker compose up -d db
uv run python manage.py migrate
uv run python manage.py bootstrap_workspace --username reviewer --workspace "Local demo"
# Enter a new password at the prompt; it is not echoed or accepted as a CLI flag.
uv run python manage.py runserver 127.0.0.1:8000
```

In another terminal run `uv run python manage.py process_jobs`. Open
http://127.0.0.1:8000/accounts/login, sign in, select the workspace, and upload
`datasets/dev/01_complete.txt` or `datasets/dev/08_two_pages.pdf`. Refresh the source
page to see canonical pages and hashes. Upload `fixtures/parser_negative/scan_like.pdf`
to see an explicit `no_text_page` failure. `process_jobs --once` drains available
jobs and exits. `bootstrap_workspace --role viewer` creates a separate read-only
workspace account; bootstrap never overwrites existing users or grants memberships
in existing workspaces. Membership administration is currently local Django ORM work.

Compose loads .env; local Python uses exported environment variables and development
fallbacks. There is no implicit dotenv loader. Export POSTGRES_HOST/PORT/DB/USER/
PASSWORD overrides if using another local instance. PostgreSQL tests create/drop
`test_<POSTGRES_DB>` on the configured server, with UTF-8/template0; use a dedicated,
disposable server with CREATEDB rights, never a production database.

## Container deployment checks

```sh
docker compose config --quiet
docker build -t formreview:local .
uv run python scripts/check_container.py
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py bootstrap_workspace --username reviewer --workspace "Local demo"
docker compose up -d web worker
```

Web and worker use the same non-root application image (UID 10001), PostgreSQL 18
and a private named volume. The worker has a 512 MiB memory/swap ceiling. Parsing
has a hard 10-second subprocess timeout and Linux 512 MiB address-space/9-second
CPU limits. No OCR, rendering, executable PDF actions, external links or network
processing occurs; the child has no inherited credentials and rejects Python
socket/process operations. This is a constrained text parser, not a general
untrusted-code sandbox. Only deploy the worker on Linux with the resource limits.
The web container has a real HTTP liveness check. Worker health does not reuse
web liveness; supervise worker process failures/restarts separately.

Production requires FORMREVIEW_ENV=production, a unique DJANGO_SECRET_KEY of at
least 50 characters, explicit DJANGO_ALLOWED_HOSTS including 127.0.0.1 for liveness,
non-default POSTGRES_PASSWORD and HTTPS. Configure HTTPS termination deliberately;
proxy headers are not implicitly trusted. Development defaults are local only.
Stop services with `docker compose down`; volumes retain originals and database
state. Do not remove volumes unless intentionally destroying local data.

## Source and access contracts

- GET /health/live is process-only. GET /health/ready checks UTF-8 database access
  and the parse-job table; it does not certify worker progress.
- Session login/logout and workspace selection use CSRF-protected writes.
  Every source lookup filters by the currently selected, server-validated membership.
- POST /api/v1/documents accepts one multipart `file`, reviewer membership and CSRF.
  Returns 202 and a document ID; no parsing runs in the request. The HTML form
  returns 303 to its source page. GET lists at most the latest 100 owned sources.
- GET /documents/{id} shows status/source. GET /documents/{id}/text returns canonical
  JSON after successful parsing. Other workspaces receive 404; no raw-file route exists.
- Maximum 5 MiB file bytes, 5 PDF pages and 20,000 canonical Unicode code points.
  TXT is one page. A PDF with any textless page is rejected, including mixed
  text/image-only documents; image-only text is not OCR. Blank/encrypted/malformed,
  invalid UTF-8, unsupported control characters and unsupported extensions fail.
- Upload admission checks membership, Content-Length and a 5 MiB + 64 KiB request
  envelope before multipart parsing. A streaming upload handler independently caps
  file bytes; fields are limited to 64 KiB/eight entries and one file is allowed.
  Deploy behind a server that enforces request timeouts; Gunicorn uses 30 seconds.
- Originals use exclusive UUID-based private paths, raw SHA-256 and mode 0400.
  Display names are sanitized and never used as paths. Parsing verifies original
  hash. Application file permissions are defense in depth, not protection from a
  privileged host administrator. Crashes before a DB commit can leave unreferenced
  private files; no destructive garbage collector is implemented in this stage.
- Canonical pages strip a leading TXT UTF-8 BOM, normalize CRLF/CR to LF and apply
  NFC. Hash is SHA-256 of UTF-8 compact JSON page arrays (ensure_ascii=False), which
  preserves page boundaries. Parser and normalization versions are stored.
  PostgreSQL triggers reject changes/deletion of documents and text versions.
- Parse jobs claim short DB locks with skip_locked, parse outside transactions,
  and finalize only under their current lease token. A 30-second lease allows
  crash recovery; after three interrupted attempts the job fails explicitly.
  Rejected files are terminal failures. No worker can approve a supplier.

## Verify

```sh
uv sync --frozen --all-groups
make check
uv run pytest --collect-only
docker compose up -d db
make integration
make container-check
```

`make check` runs Django checks, Ruff, formatting, mypy over all application packages,
and unit tests. `make integration` runs migrations, migration-drift check, real
PostgreSQL tests (including independent workers) and worker help. Test collection
requires exactly one unit/integration/e2e category. CI runs these with PostgreSQL 18
and container smoke checks. Real HTTP behavior can be verified locally; no JS is required. Stage 3 was also manually exercised in a real in-app browser;
that walkthrough is not a committed browser-regression suite.

The 12 synthetic development sources and separately authored provisional labels
are described in datasets/dev/README.md. Labels are not independently human-reviewed
gold, parser output or model input. Parser-negative fixtures are separate. There
are no live model results or accuracy claims. Synthetic replay is implemented;
regex baseline and live AI remain distinct future capabilities. Approved design/roadmap files were not supplied;
no replacement roadmap or history was invented. See AGENTS.md for permanent contracts.
