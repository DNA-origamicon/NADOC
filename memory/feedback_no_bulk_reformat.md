---
name: feedback_no_bulk_reformat
description: "Don't make repo-wide one-shot reformat commits — they collide with the other computer's divergent history"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 34a9d22c-4b20-45cb-8d9c-cd3ee5afa8ad
---

Do **not** create a single repo-wide "ruff format everything" commit (e.g. the old `style: ruff format repo-wide`). The user has opted out of bulk reformatting. A pre-commit hook already auto-formats each commit incrementally, so the repo stays consistent without a bulk pass.

**Why:** This is a solo two-computer setup (`master`, GitHub remote `DNA-origamicon/NADOC`). A bulk reformat touches nearly every line of every file. When computer A commits it but the histories diverge before computer B syncs, the reformat collides with everything B did → hundreds of conflicts. That exact mess happened on 2026-06-20 during an integration: the fix was to *drop* the bulk-format commit before rebasing, shrinking conflicts from ~80 files to the 3 real ones. Formatting's value for solo work (clean diffs) is real but modest and not worth the sync risk.

**How to apply:**
- Never run an ad-hoc `just fmt` across the whole repo and commit it as one change, especially mid-divergence.
- Rely on the existing pre-commit hook to keep new/edited code formatted per-commit.
- If a one-time formatted baseline is ever genuinely wanted: (1) both computers fully synced + clean, (2) bulk-format once from that converged point, (3) push and sync both immediately, (4) let the hook maintain it. Get explicit user approval first.
- Note: `.git-blame-ignore-revs` may reference stale format-commit hashes — cosmetic, ignore.

Related: the two-computer pull-before-start / push-before-stop discipline in CLAUDE.md is the actual safeguard here.
