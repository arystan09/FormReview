# Stage 6 review workflow

Stage 6 of exactly 10 refines human review. No new provider or approval authority,
paid experiment, frontend framework or external CRM is introduced.

## Review and source evidence

Open an existing draft from the document source or extraction preview. Canonical
pages remain bound to that draft's immutable text version. On wide screens they
sit beside the five field decisions; on narrow screens they appear above them.
Present/missing/ambiguous status and plain-language flag explanations accompany
each candidate. “Show evidence” highlights the server-derived exact quote and
moves keyboard focus to its source page. Unicode offsets are code points, including
in JavaScript via Array.from. Text is rendered through escaped templates/text nodes,
never HTML insertion. No confidence percentage is shown.

Choose each decision explicitly: accept an eligible source candidate, enter a
manual correction, or mark an optional field missing with a reason. Controls appear
for that choice. Invalid-evidence candidates are disabled in the selector and also
rejected by the server. A valid quote is not semantic truth; a reviewer must resolve
wrong entities, contradictory terms and other contextual ambiguity.

Manual edits always require reason and provenance before approval. Optionally
select text from a canonical page and use “Use selected source”, or type its page,
exact quote and literal using the keyboard. At approval, the server must uniquely
anchor that span and verify that its explicit normalized literal equals the final
value. This is a human source correction, never a model success. Without a span,
a manual value remains a reviewer-supplied override, not verified source evidence.
The record page, confirmation and JSON export distinguish these provenance kinds.

## Partial saves and conflicts

“Save partial draft” sends partial=true, expected_revision and the current field
decisions to PATCH /api/v1/drafts/{id}. The API also supports a subset of fields,
merging only those supplied. Missing keys are retained, never implicitly erased.
An unresolved decision or unfinished manual value/reason can be saved as work in
progress. Structural limits and unsafe-text checks still apply. Accepting a source
candidate still requires valid evidence; partial saves cannot mark invalid evidence
accepted. Each save increments revision and records a ReviewEvent snapshot.

Partial saves do not approve. “Save decisions and review confirmation” applies the
full five-decision rules. Confirmation and approval independently validate again:
name/email required, optional nulls require reasons, supported terms in 0–365,
manual provenance/reason, correct source/run binding and active revision. The
confirmation shows the actual source mode/config and an explicit human checkbox.
The existing atomic receipt/idempotency behavior is unchanged.

A stale save returns HTTP 409. The page retains local input and reveals a comparison
panel. “Compare current saved decisions” uses an owned GET of the same draft API,
including revision/status, values and provenance. It does not modify local input.
After comparing and reconciling every field, the reviewer must check the explicit
acknowledgment before using the fetched revision. A subsequent save is still
conditional; another intervening change produces another 409. There is no automatic
merge, revision advancement, retry or last-write-wins fallback. Closed drafts cannot
be reconciled for saving. “Reload and discard” requires explicit confirmation.

Unsaved edits remain in this tab on save/network errors and the browser warns on
navigation away. No private draft content is placed in localStorage. Closing the
browser, crashing it or deliberately discarding edits can still lose unsaved text.
Changes typed during an in-flight save remain marked unsaved and do not trigger
navigation to confirmation. A stale approval shows a 409 page directing the reviewer
back to the saved decisions; it does not approve or overwrite anything.

## Explicit selection of another run

Re-extraction adds a run and never touches an open review. To use a different
validated owned run, open its extraction preview and select “Select this run and
start a new draft”. The form sends the currently active draft ID and its revision.
Under a Document lock, the service locks that draft, checks role/revision, marks it
superseded without changing its decisions or source/run binding, and creates an
empty active draft for the selected run. Selection/supersession events are recorded
in the same transaction. There is no automatic transfer of old decisions.

An old tab keeps its text but can no longer save or approve that superseded draft.
Old draft URLs remain attributable and read-only, with a link to the active draft.
Approved documents cannot start another review; the unique approved-document and
immutable record contracts remain in force. A save/approval/selection race is
serialized under the Document→Draft lock order.

Migrations 0005 and 0006 replace the document/draft one-to-one constraint with a
foreign key plus a conditional unique active draft, and extend transition guards.
Existing IDs, decisions, revisions, source references, records and receipts are not
rewritten. A dedicated PostgreSQL upgrade test populates stage-5 tables, migrates
forward and verifies preserved decisions, IDs, receipt/snapshot hashes and subsequent
explicit run selection. Back up the database before migrating. Guard migrations remain
irreversible, as in earlier stages; restoring an old app requires a deliberate
schema/data rollback plan, not blind reverse migration.

## Demonstration and verification

Prerequisites and local startup remain in README.md: Python 3.12, uv and PostgreSQL
18/UTF-8, migrate, bootstrap a reviewer, run web and process_jobs. No key is needed
for replay/manual review. Existing paid confirmation additionally names mode live,
actual model/config and the current estimate; no paid request was made for stage 6.

Upload datasets/dev/01_complete.txt, parse, run synthetic replay and create a draft.
Inspect the supported supplier quote and invalid email quote. Save a partial email
correction; open a second tab, save in the first, then save in the second to see the
conflict. Compare and reconcile manually, provide all five decisions and confirm.
For ambiguity, datasets/dev/04_ambiguous_email.txt supplies two contact candidates.

The real-browser test test_contradictory_terms_missing_id_and_hostile_source uses
an explicitly mocked synthetic replay with Net30/Net60, absent registration ID and
hostile HTML text. It chooses Net60, records a missing-ID reason, saves/approves
through actual local HTTP and verifies that hostile text does not execute. It is
not a live model result and is not part of the frozen evaluation dataset.

Run:

```sh
make check
make integration
uv run pytest tests/integration/test_review_conflicts.py
uv run playwright install chromium
uv run pytest -m e2e
uv run python scripts/demo_smoke.py
make container-check
```

PostgreSQL tests use dedicated disposable databases and independent connections for
selection/approval races. Browser tests cover stale save and stale approval, local
text preservation/reconciliation, explicit run selection, source highlighting,
manual span provenance, keyboard focus, malformed-source escaping, replay and
manual-only paths. These automated reviewer interactions are not an independent
human review claim. Docker/Linux resource proof and remote CI remain separate gates;
actual paid verification from stage 4 remains pending owner authorization/key.
