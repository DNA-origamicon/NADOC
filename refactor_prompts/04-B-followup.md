# Followup 04-B — Evaluate ruff F401/F811 unused-imports cleanup

You are a **followup session**. Audit, do not implement.

## Pre-read

1. `refactor_prompts/04-B-ruff-unused-imports.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #2 lint-delta-stable, #6 dead-code 3-step check)
3. Worker's final-message Findings text (passed by manager)

## Step 0 — locate worktree

```bash
git worktree list
# Audit in the 04B-* worktree, NOT the main checkout.
```

## Your job

### Q1 — Metrics

- Re-run `just lint` in the worktree. Count F401 and F811: `grep -cE "F401" output ; grep -cE "F811" output`. Match worker's claim.
- Re-run `just test`. Confirm pass/fail/error counts AND failure set are baseline-equivalent.
- Total error-count delta: pre 449 → post N. Confirm N is honest.

### Q2 — Scope

- `git diff HEAD --stat` in worktree. Confirm only `backend/` + `tests/` files changed. Anything else = scope creep; flag.
- Sample 5 random changed files; for each:
  - Confirm the diff shows ONLY removed import lines (no body changes, no rebinding).
  - Confirm at least one removed import was unambiguously unused (grep for the imported symbol in the file body — should return zero).

### Q3 — False-positive audit (load-bearing)

The 16-file `validate_design imported but unused` cluster is the most likely false-positive zone. For 3 of those 16 files in the worktree:
- Open the file
- Confirm `validate_design` truly isn't called anywhere in the body
- Confirm there's no `__all__` re-export referencing it
- Confirm the test still passes after import removal

If `validate_design` was meant to be called and the cleanup masks a latent bug: flag it as `Queued follow-up: latent bug in <file> — should be calling validate_design()`.

Sample 2 other files outside the `validate_design` cluster too. Same checks.

### Q4 — Side-effect imports (the canonical F401 false-positive risk)

Imports with side effects (registering a hook, populating a registry, side-effecting a module-init) should NOT be removed. Sample any imports of:
- `backend.api.library_events` (likely registers event handlers)
- `backend.api.routes` (FastAPI router registration)
- Anything ending in `_register` / `_hooks` / `_init`

If ruff removed any of these, revert that file's change and flag.

### Q5 — Did `just test` actually run with the cleaned imports?

Possible failure mode: a removed import was needed at module-import time (e.g., a class registration that side-effects on import). Tests would fail at collection time. Verify post-test output had no `ImportError` / `ModuleNotFoundError` / `AttributeError` at collection.

## Output (return as agent result text)

```markdown
### Followup 04-B — ruff F401/F811 unused-imports cleanup  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>

**Worktree audit context**: <path>

**Diff vs claimed-touched files**: <K claimed | M observed | extras>

**Metric audit**
- F401 count: claimed pre=142, observed pre=<X>; claimed post=<Y>, observed post=<Y'>
- F811 count: claimed pre=7, observed pre=<X>; post observed=<Y'>
- total ruff errors: 449 → <N> (Δ=<−149?>)
- tests: <pre-counts> → <post-counts>; failure set match: yes/no

**Scope audit**
- files-changed: <K within backend+tests | extras>
- sampled 5 diffs: all are pure-deletion ✓ | <list any with body changes>

**False-positive audit**
- `validate_design` cluster (3 sampled): <each: legit-removal | latent-bug>
- non-cluster sample (2): <each: legit | latent>

**Side-effect imports**
- `library_events` / route registries / `_register` / `_hooks` / `_init` patterns scanned: <none touched | list affected>

**Test-collection sanity**: <PASS — no ImportError/ModuleNotFoundError | FAIL — list>

**Prompt evaluation**
- Was the `--select F401,F811` scope right (no scope creep into other auto-fixable rules)?
- Did the false-positive caveat in the prompt actually catch anything?
- Was the per-file exclusion mechanism clear, or did the worker hit a workflow gap?

**Proposed framework edits**
1. ...
```

Time budget: 100 lines max.

## Do NOT

- Implement code.
- Pick new candidates.
- Append to `REFACTOR_AUDIT.md`.
