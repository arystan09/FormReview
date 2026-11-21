# FormReview implementation boundaries

This is the new FormReview project. Never edit ScopeCheck or ImportLedger.
There are exactly **10 mandatory stages**. Work on one authorized stage only.
Stage 1 establishes the foundation. A keyless replay walkthrough is due after
stage 3; the full MVP is due after stage 4. Stages 2–10 are not implemented here.
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

Do not scaffold later capabilities. Stage 1 permits only built-in Django tables.
Use focused typed modules. Verification: `make install`, `make check`,
`uv run pytest --collect-only`, `uv run python manage.py help`,
`make container-check`. Missing Docker or remote CI is a pending gate, never a pass.
Stop after reporting acceptance evidence and suggesting the intended commit:
`set up FormReview app and verification workflow`.
