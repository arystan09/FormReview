# Synthetic replay v1

These are hand-authored responses, including intentional errors, keyed by real
canonical hashes of the 12 development sources. They are not model predictions,
regex extraction, accuracy evidence or truth labels. No labels are loaded by the
fixture generator or runtime. Replay accepts the full stored executable config and
canonical source request; changing the prompt changes config/request hashes, not
the authored response. No provider SDK, keys or network are involved.

01_complete.txt demonstrates anchored supplier_name, deliberately missing
registration_id and unsupported contact_email quote. 04 has ambiguous email;
08 deliberately claims the wrong page for country; 11 has two country candidates.
Other fixtures exercise literal values and unresolved payment conventions.

Rebuild with `uv run python -m scripts.generate_replay_fixtures`. Changes to canonical
source/parser versions may require explicit fixture regeneration; unknown source
hashes fail with no_synthetic_replay_fixture, never a guessed result.
