# Followup 07-C — Evaluate `_apply_add_helix` removal

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/07-C-remove-apply-add-helix.md`
2. Worker's Findings #22 text (or REFACTORED-held-line report)

## Q1 — Removal happened OR worker correctly held the line

If worker REFACTORED:
- `git -C <worktree> diff HEAD --stat backend/api/crud.py` should show a single deletion-only hunk.
- Open the diff: confirm only `_apply_add_helix` and its docstring/comment were removed; NO other lines changed.
- `cd <worktree> && rg "_apply_add_helix" backend tests frontend/src` — must return 0 matches globally.

If worker held the line (UNSUCCESSFUL — held line):
- Confirm at least one of the 4 removal-threshold conditions was actually violated.
- The "held line" outcome is correct behavior; not a worker failure.

## Q2 — Sibling-route preserved
- `git -C <worktree> show HEAD:backend/api/crud.py | sed -n '2860,2890p'` — read the sibling `add_helix` route at L2870. Confirm it uses an inline `_apply` closure (NOT calling `_apply_add_helix`).
- After removal, the sibling should still pass tests via the existing test suite — no new test needed for it; the existing `tests/test_lattice.py` and `tests/test_crud.py` exercise the route.

## Q3 — Tests + lint preserved
- `cd <worktree> && just test 2>&1 | tail -5` — failure set ⊆ stable_baseline ∪ flakes.
- `cd <worktree> && just lint 2>&1 | tail -5` — error count ≤ 301 (post-Pass-4 baseline).
- A test surfaces NEW failure: the dead-code claim was wrong. Flag.

## Q4 — Scope
- Only `backend/api/crud.py` should be modified. No `tests/` edits, no `frontend/`, no `pyproject.toml`.

## Output

```markdown
### Followup 07-C — `_apply_add_helix` removal  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL — held line>
**Worktree audit context**: <path>

**Removal-threshold re-verify (independent)**
- Condition 1 (backend/ refs): <count>
- Condition 2 (tests/ refs): <count>
- Condition 3 (frontend/src/ refs): <count>
- Condition 4 (*.md refs): <count>

**Diff scope**: <single deletion hunk only | other changes flagged>
**Sibling `add_helix` route preserved**: yes/no
**Test post-failure set ⊆ stable_baseline ∪ flakes**: yes/no
**Lint Δ ≤ 0**: yes/no
**Global ripgrep post-removal**: <0 | non-zero — flag>

**Prompt evaluation**
- Was the 4-condition re-verify discipline appropriate? Could it be relaxed for vulture@60-confirmed-by-followup symbols, or kept strict?
- If the worker held the line, was the trigger condition documented clearly enough?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Modify code, fix flagged issues, append to REFACTOR_AUDIT.md.
- Remove additional dead-code candidates yourself.
