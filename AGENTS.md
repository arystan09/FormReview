# FormReview implementation boundaries

This is the new FormReview project. Never edit ScopeCheck or ImportLedger.
There are exactly **10 mandatory stages**. Work on one authorized stage only.
Stage 1 establishes the foundation. A keyless replay walkthrough is due after
stage 3; the full MVP is due after stage 4. Stage 2 adds owned uploads and immutable canonical parsing. Stage 3 adds synthetic replay, immutable extraction config/evidence and an initial
review preview. Stages 4–10 are not implemented here.
No approved design/roadmap files were supplied at initialization. Do not invent
implementation history or fill in a replacement roadmap. Obtain the approved
stage scope before implementing a later stage.

Read this file, supplied design/roadmap, Git status, code and verification commands
first. Preserve unrelated changes; verify previous-stage assumptions and report
material conflicts. Do not automatically initialize Git, commit, push, deploy,
make paid calls or provision billable resources.

## Permanent compatibility contracts

- Python 3.12, Django 5.2/DRF, PostgreSQL 18/psycopg; templates/local JS.
  Eventually one application image serves web and a durable job worker. No
  mandatory Redis, Celery, S3, vector database, LangChain or agents.
- English UTF-8 TXT/digital text PDF only; private local files; at most 5 MiB,
  5 pages and 20,000 canonical characters. No OCR/scans/DOCX/URLs/CRM/payments.
- Exactly supplier_name, registration_id, contact_email, country,
  payment_terms_days. Name/email required for approval; other nulls require
  reviewer reasons. Preserve registration punctuation/leading zeros; no government
  verification. Country is source text. Normalize only explicit lexical NetN/Ndays
  to 0–365; otherwise unresolved.
- present/missing/ambiguous have 1/0/2 distinct candidates. value_text must occur in
  exact bounded page quotes. Server locates unique quotes in immutable NFC/newline
  normalized canonical pages, derives offsets and flags duplicate/missing/wrong-page
  evidence. Membership is not semantic truth. No model confidence percentages.
- Immutable hashed config includes executable prompt_text/model/settings/schema/
  normalizer versions; actual live payload uses it. Labels/reviewer/gold decisions
  never enter provider requests. Distinguish replay, regex baseline and live.
  Model receives canonical text and returns one structured response; no tools.
- Session membership supplies workspace/role; CSRF on writes. Documents/models
  cannot grant authority/approval. Drafts use expected_revision; extraction never
  silently overwrites review.
- Human approval validates five decisions and active draft under Document→Draft
  locks in one transaction, unique approved document and idempotent receipt.
  Manual overrides require provenance/reason. No automatic or worker approval.
- Paid mode defaults disabled: owner-configured finite durable allowance,
  allowlisted config/key and explicit per-request confirmation; at most one live
  request/run, 3,000 output tokens, 30 seconds; no hidden SDK/uncertain retries.
  Public demo read-only/keyless. Paid calls/publication/resources need authorization.
- Never log keys, sessions, emails, raw text, quotes or full prompts. Use synthetic
  data and mock provider calls in CI. Real PostgreSQL independent connections or
  processes prove concurrency; real browsers prove JS behavior. No invented passes.

Do not scaffold later capabilities. Stage 3 additionally permits ExtractionConfig,
ExtractionRun, FieldCandidate and initial ReviewDraft. No approval or live capability.
Use focused typed modules. Verification: `make install`, `make check`,
`uv run pytest --collect-only`, `uv run python manage.py help`,
`make container-check`. Missing Docker or remote CI is a pending gate, never a pass.
Stop after reporting acceptance evidence and suggesting the intended commit:
`validate extraction evidence and add replay review`.

Stage 2 checks additionally require PostgreSQL 18 with UTF-8 encoding:
`make integration`. Tests create/drop a dedicated test database; never point them
at a production server. PDF parsing has a 10-second subprocess wall timeout, Linux
512 MiB address-space limit and a 512 MiB Compose worker ceiling. macOS development
does not prove the Linux memory ceiling. No OCR or live model calls. Keep provisional labels
separate from parser output; never call them independently human-reviewed truth.

Stage 3 checks: `uv run pytest tests/unit/test_evidence.py
tests/unit/test_extraction_contract.py tests/integration/test_replay.py` (one command).
Replay is visibly synthetic, restricted to bundled source hashes, and must consume
the actual stored config payload. Never derive model offsets or claim quote
membership is truth. Initial draft creation binds an explicit run/text version;
new extraction must not replace it. Editing/approval remain stage 4.
