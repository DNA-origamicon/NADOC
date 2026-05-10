# Refactor 05-C — Vulture dead-function scan (backend)

You are a **worker session** in a git worktree. **INVESTIGATED**-only — produce a Findings entry classifying dead-function candidates. Code changes only for unambiguous cases (see "Removal threshold" below).

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#6 dead-file 3-step check, #1 baseline-twice, #2 lint-delta-stable)
3. `REFACTOR_AUDIT.md` § "Findings" #4 (the prior dead-file false-alarm — `debug_snippet.js` was deliberately orphan), #14 (F401 unused-import cleanup; complement)
4. This prompt

## Goal

Run `vulture` against `backend/` to surface unused functions, classes, and methods (separate signal from F401-style unused imports). Classify each candidate; remove only the truly unambiguous ones.

## In scope

- `vulture` via `uvx vulture backend --min-confidence 80`
- Optional second pass at `--min-confidence 60` for borderline candidates (manual triage required)
- Spot-check each high-confidence candidate against:
  - Pre-condition #6 dead-file 3-step (no imports, no comment refs, no rule-file refs)
  - Whether the symbol is used in `tests/` (vulture by default scans only the dir given)
  - Whether the symbol is referenced by string (e.g. dynamic `getattr`, `globals()`, jinja templates)
- Removal threshold: only remove a function/class if it satisfies ALL of:
  1. vulture confidence ≥ 80
  2. zero matches in `rg <name>` across `backend/`, `tests/`, `frontend/src/`, and `*.md` documentation
  3. zero matches in `git log --all --oneline -- '*.py' | xargs git log -p` for the symbol over the last 50 commits (i.e. the symbol wasn't recently used and removed)
  4. not decorated with `@router.<method>`, `@pytest.fixture`, `@app.X`, `@validator`, `@property`, `@field_validator`, `@model_validator` (these decorations create framework-level usage vulture can't see)

If any condition fails, **do not remove** — document as a `possibly-dead` candidate for manual review.

## Out of scope

- `frontend/`. Different language; covered separately by the JS dead-export scan in a future pass.
- Removing decorated functions (FastAPI routes, pytest fixtures, Pydantic validators) — vulture doesn't grok the framework.
- Adding `vulture` to `pyproject.toml` as a dev-dep.
- Changing `__all__` lists.

## Verification plan

### Pre-state capture
```bash
git status > /tmp/05C_dirty_pre.txt
just lint > /tmp/05C_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/05C_lint_pre.txt
just test > /tmp/05C_test_pre1.txt 2>&1
just test > /tmp/05C_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05C_test_pre1.txt | sort > /tmp/05C_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/05C_test_pre2.txt | sort > /tmp/05C_baseline2.txt
comm -12 /tmp/05C_baseline1.txt /tmp/05C_baseline2.txt > /tmp/05C_stable_failures.txt
```

### Investigation
```bash
# High-confidence pass
uvx vulture backend --min-confidence 80 > /tmp/05C_vulture_high.txt 2>&1
wc -l /tmp/05C_vulture_high.txt

# Borderline pass (do NOT auto-act on these)
uvx vulture backend --min-confidence 60 > /tmp/05C_vulture_borderline.txt 2>&1
wc -l /tmp/05C_vulture_borderline.txt

# Filter framework-decorated symbols (FastAPI, pytest, Pydantic)
grep -vE "@(router|app|pytest\.fixture|validator|field_validator|model_validator|property)" /tmp/05C_vulture_high.txt > /tmp/05C_candidates.txt
wc -l /tmp/05C_candidates.txt
```

### Per-candidate triage

For each line in `/tmp/05C_candidates.txt`:

1. Extract symbol name and file:line.
2. `rg <name> backend/ tests/ frontend/src/` — count non-definition matches.
3. `rg <name>` across `*.md` docs.
4. Check decoration: `grep -B 3 "<name>" <file>` to see decorators.
5. If all 4 removal-threshold conditions pass: stage for removal.
6. If any fail: classify as `possibly-dead` and document.

### Removal step (if any unambiguous candidates)

```bash
# For each unambiguous symbol, edit the file to delete the function/class definition.
# Run tests after EACH removal:
just test 2>&1 | tail -3
# If a removal causes a new failure: revert that one symbol's change and re-classify as possibly-dead.
```

### Post-state capture
```bash
just lint > /tmp/05C_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/05C_lint_post.txt
just test > /tmp/05C_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05C_test_post.txt | sort > /tmp/05C_post_failures.txt
diff /tmp/05C_stable_failures.txt /tmp/05C_post_failures.txt   # ⊆ baseline ∪ flake
git diff --stat | tail -10
```

## Stop conditions

- `uvx vulture` fails to install: try `uv pip install vulture` then `uv run vulture ...`. If neither works: report and stop without an investigation result.
- More than 30 candidates after framework-decorator filtering: stop the per-candidate triage at 30 and document the remainder as "uninvestigated; manager queue."
- Any removal causes a new test failure: revert that single symbol's removal; do NOT roll back other clean removals.

## Output

```markdown
## 05-C Backend dead-function scan — INVESTIGATED <+ N removals if any unambiguous>

### Pre-existing dirty state declaration
<git status output at session start>

### Tooling note
- vulture installed via: <uvx | uv pip install | other>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 17. Backend dead-function audit — `pass` ✓ INVESTIGATED <+ partial REFACTORED if removals>
- **Category**: (b) dead-code
- **Move type**: investigation-only <or "investigation + N removals" if any>
- **Where**: `backend/` (whole tree)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: <list, or "none">; other-files: none
- **Transparency check**: <PASS — only deletions, no rebinding | not applicable>
- **API surface added**: none
- **Visibility changes**: none — only removals
- **Callsites touched**: 0
- **Symptom**: vulture@80% surfaced <X> candidates; <Y> after framework-decorator filtering.
- **Triage outcomes**:
  | Symbol | File:line | Decision | Reason |
  |---|---|---|---|
  | <name> | <path:line> | removed | confirmed dead per all 4 conditions |
  | <name> | <path:line> | possibly-dead | decorator-protected (FastAPI route) |
  | <name> | <path:line> | possibly-dead | string-referenced in <docs/path.md:line> |
  | … | … | … | … |
- **Why it matters**: dead functions are riskier than dead imports — they may shadow live names, create maintenance friction when readers wonder if they're called, and accumulate framework-decorator false-positives that need to be re-distinguished each pass.
- **Change**: <description of removals, or "documented; not implemented">
- **Implementation deferred**: <list of possibly-dead candidates left for manual review with their flagging reason>
- **Effort**: S
- **Three-Layer**: not applicable (cleanup; no layer crossings)
- **Pre-metric → Post-metric**:
  - vulture@80 candidates: pre <X>, post <X-N> (where N = number removed)
  - tests: pre <X/Y/Z>, post <X'/Y'/Z'>; baseline match: yes/no
  - lint Δ: <0 expected; flag if not>
- **Raw evidence**: `/tmp/05C_vulture_high.txt`, `/tmp/05C_vulture_borderline.txt`, `/tmp/05C_candidates.txt`
- **Linked Findings**: #4 (deliberate-orphan precedent), #14 (F401 import cleanup; this is the function-level analog)
- **Queued follow-ups**: <list of possibly-dead symbols where a manual review is needed; group by file>
```

## Success criteria

- [ ] `vulture --min-confidence 80` ran successfully against `backend/`
- [ ] Each candidate (after framework-decorator filtering) has a triage decision
- [ ] Removal-threshold check applied to every removed symbol; never removed without all 4 conditions met
- [ ] If removals happened: tests + lint baseline-equivalent; revert any individual removal that broke tests
- [ ] Findings entry classifies all surfaced candidates

## Do NOT

- Remove decorated symbols even if vulture says they're unused (FastAPI / pytest / Pydantic decorators are framework-level usage).
- Remove symbols referenced in tests, docs, or `__all__`.
- Touch `frontend/`, `tests/` or `pyproject.toml` (the `tests/` exclusion is because vulture doesn't see test usage by default; cross-checking against `tests/` is in scope but editing isn't).
- Commit. Append to REFACTOR_AUDIT.md from worktree.
