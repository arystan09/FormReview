# Held-out synthetic split

18 supported documents in six complete families, with separate layouts and supplier
identities from dev. In stage 5 these sources/labels/hashes are validated only.
No test extraction outputs have been run or used for tuning. This is public synthetic
data, not an author-blind study. Human label review remains pending.

Use `uv run python manage.py evaluate --dataset datasets/test/manifest.json --validate-only`.
The stage-5 runner rejects test extraction. See ../../docs/evaluation.md.
