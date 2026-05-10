# Followup 05-C — Evaluate vulture dead-function scan

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/05-C-vulture-dead-functions.md`
2. Worker's Findings #17 text (passed by manager)

## Q1 — Did vulture actually run?

```bash
ls -la /tmp/05C_vulture_high.txt /tmp/05C_vulture_borderline.txt /tmp/05C_candidates.txt
wc -l /tmp/05C_vulture_high.txt /tmp/05C_candidates.txt
```

Spot-check the worker's claimed candidate count: re-run `uvx vulture backend --min-confidence 80 | wc -l`. Match within ±2 lines.

## Q2 — Removals: were they truly safe?

For each `removed` row in the worker's triage table:

1. `git -C <worktree> show HEAD:<file> | grep -n "<symbol>"` — confirm the symbol was at the claimed line in HEAD.
2. `git -C <worktree> diff HEAD -- <file>` — confirm only the symbol's definition was deleted (no unrelated edits).
3. **3-step dead-file check** (precondition #6) for the symbol:
   - `rg "\b<symbol>\b" <worktree>/backend <worktree>/tests <worktree>/frontend/src` — must show only the definition line (or zero in worktree if the worker already deleted it).
   - `rg "\b<symbol>\b" --type-not py --type-not js` — check docs/comments (catches the Pass 1 #4 false-alarm pattern).
   - Worker should have done this; you re-do the highest-risk one (the symbol with the most ambiguous name).
4. Decorator check: `git show HEAD:<file>` and check for `@router|@app|@pytest|@validator|@field_validator|@model_validator|@property` decorating the symbol.

If any removed symbol fails any of these, the worker over-removed. Flag as a regression risk; manager should revert that single symbol.

## Q3 — `possibly-dead` honesty

For 2 of the worker's `possibly-dead` triage rows, validate the cited reason:
- "decorator-protected": confirm the decorator is actually present
- "string-referenced": grep the cited doc/path for the symbol literal
- "tests use it": find the test reference

If the reason is bogus, the symbol may actually be removable; flag for re-triage.

## Q4 — Scope

- `git -C <worktree> diff HEAD --stat`: only Python files in `backend/`. No `tests/`, no `frontend/`, no `pyproject.toml`, no `__init__.py` `__all__` edits.
- Test baseline preserved.
- Lint Δ: any new errors from imports of now-removed symbols (F401/F841)? Re-run lint to confirm.

## Q5 — Vulture limitations

vulture has known false positives:
- Pydantic v2 `@field_validator` / `@model_validator` (decorator-form classmethods)
- FastAPI route handlers in `crud.py` / `assembly.py` / `ws.py`
- `pytest.fixture(autouse=True)` fixtures in `conftest.py`
- Dunder methods (`__init__`, `__call__`, etc.)
- `__all__` exports

Did the worker's framework-decorator filter catch all of these patterns? Sample a few removed candidates and confirm none fall into a missed-pattern bucket.

## Output (return as agent result text)

```markdown
### Followup 05-C — vulture dead-function scan  (eval date)

**Worker outcome confirmation**: <INVESTIGATED <+ N safe removals> | UNSUCCESSFUL>
**Worktree audit context**: <path>
**Diff vs claimed-touched files**: <K claimed | M observed | extras>

**Vulture run audit**
- /tmp/05C_vulture_high.txt: claimed <X> candidates, observed <Y>
- /tmp/05C_candidates.txt (post framework-filter): <Z>

**Removals safety audit** (per removed symbol)
- <symbol>: 4-condition check <PASS | FAIL — reason>
- <symbol>: …
- summary: <K of K removals safe>

**`possibly-dead` honesty audit** (2 sampled)
- <symbol>: reason claim <agree/disagree, evidence>
- <symbol>: reason claim <agree/disagree, evidence>

**Scope audit**
- files-changed: <count, all in backend/>: <yes | flag>
- tests/frontend/pyproject.toml untouched: <yes/no>
- baseline preserved: <yes/no>

**Vulture-limitation audit**
- Pydantic v2 @field_validator handled: <yes | missed in <path>>
- FastAPI @router handled: <yes | missed>
- pytest fixtures handled: <yes | missed>
- dunder methods handled: <yes | missed>

**Prompt evaluation**
- Was the 4-condition removal threshold restrictive enough? Too restrictive?
- Did the framework-decorator filter list miss anything?
- 30-candidate cap was reached / not reached?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement code, remove additional symbols, append to REFACTOR_AUDIT.md.
