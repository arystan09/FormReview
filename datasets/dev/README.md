# Development split

30 supported synthetic documents in ten complete scenario/identity families.
The original 12 walkthrough files are retained byte-for-byte; replay still covers
only those 12. The other 18 are scheduled as unattempted by replay evaluation.

manifest.json pins sources/canonical/gold hashes; gold.json contains versioned,
authored expectations and spans with human review pending. labels.provisional.json
is retained historical stage-2 material, not the scorer input. See
../../docs/evaluation.md for grouping, matching rules, limitations and review checklist.
No labels or manual decisions enter provider requests. No live model results.
