# Context economy — head/archive split of the ledgers + topic files

**Why.** Sessions had become slow on even trivial edits. Cause was not the test suite and not repo
size (search is fine; `workspace/` is gitignored). It was that the instructions in `CLAUDE.md` +
`MEMORY.md` mandated reads of files that had grown 10× past the size those instructions assumed.
A representative small edit (touch `main.js` in the assembly area while debugging) cost **~70k tokens
of mandatory reading before looking at a single line of source**. The model prefills every one of those
tokens before emitting its first output character, so this is wall-clock latency, not just cost.

## The pattern (apply to any file that grows past ~200 lines)

Split into a **head** and an **`*_archive.md`**:

- **Head** keeps the filename (inbound references keep working — `manual_validation_debt.md` alone had
  24 referrers, so nothing was renamed or `git mv`'d). It carries: purpose, protocol/conventions,
  invariants + gotchas, open/pending items, the handoff block.
- **Archive** holds the completed/superseded history, verbatim.
- Where a must-keep section is too big (90 pending `MV-` rows, 109 oracles, 61 lessons), the head carries
  a generated **one-line index with a hook**, and the archive holds the full text. Scan hooks, open one entry.

**Invariant, enforced mechanically:** every non-blank line of the original appears verbatim in head or
archive. Verified for all 11 splits (0 lines lost). Splitter + verifier were throwaway scripts; the rule is
what matters, not the tooling.

## Results (2026-07-09)

| File | before | after (head) |
|---|---|---|
| `memory/MEMORY.md` (always loaded) | 5,123 tok | 1,875 |
| `.claude/rules/main-init.md` (auto-loads on every `main.js` read) | 4,653 | 1,980 |
| `memory/LESSONS.md` | 23,041 | 2,892 (61-entry index) |
| `manual_validation_debt.md` | 48,703 | 4,860 |
| `memory/project_oxdna_relaxation.md` | 49,879 | 7,834 |
| `design_automation_backlog.md` | 41,559 | 6,527 |
| `sim_coverage_log.md` | 38,896 | 9,140 |
| `design_automation_log.md` | 35,550 | 5,290 |
| `memory/project_path_to_thousands.md` | 33,822 | 4,621 |
| `memory/project_cando_fem.md` | 26,374 | 7,187 |
| `memory/project_alpine_cluster_submission.md` | 22,042 | 2,222 |
| `issues_ledger.md` | 21,285 | 11,255 |

Representative small edit: **~70,076 → ~15,259 tokens (‑79%)**.

## Rules that now enforce it

- `CLAUDE.md` "Memory layout": **`*_archive.md` is never read in a routine loop.**
- `CLAUDE.md` Done checklist: topic-file read is gated on *behavior-altering* changes, not any change;
  reading an archive requires naming the specific past decision you're mining.
- `MEMORY.md` is pointer-only and **edited rarely** — it sits in the always-loaded prompt prefix, so every
  edit invalidates the prompt cache for all sessions. It had 18 commits in 60 days; that was the hidden cost.
- Feature updates go in the topic file **head**, not `MEMORY.md`, not the archive.

## Floors (not misses)

`issues_ledger.md` (11.3k) and `sim_coverage_log.md` (9.1k) can't shrink further without dropping
must-keep verbatim content — sim-coverage's oracle catalog alone is 27 KB. They're no longer the problem.

## Gotchas banked

- `.claude/rules/*.md` auto-load via a `paths:` frontmatter key. A rule's detail file must live **outside**
  `.claude/rules/` (this one went to `memory/main_init_detail.md`) — don't rely on "no `paths:` means no load".
- `.claude/` was gitignored, so rule/skill edits never reached the other computer. Un-ignoring needs
  **`.claude/*`, not `.claude/`** — git cannot re-include a file whose parent *directory* is excluded, so
  `.claude/` + `!.claude/rules/` silently does nothing. `settings.local.json` + `worktrees/` stay ignored.
- `physics-fem` was listed in the rules index but had been retired to `archive/physics_xpbd_fem/`. Stale
  pointers in an always-loaded index cost tokens and mislead; check the directory, don't trust the list.
- `~/.claude/projects/-home-joshua-NADOC/memory/` is a **symlink** to the repo's `memory/`. One file to maintain.
- Behavioral, not file-shaped: `/clear` between unrelated tasks; work in bursts (prompt cache TTL ~5 min);
  a 200k-context model beats a 1M one for small edits because it forces a compact instead of letting
  context sprawl.

Related: [[feedback_concurrent_sessions]] — a second session `git stash`ed mid-split; snapshot before bulk rewrites.
