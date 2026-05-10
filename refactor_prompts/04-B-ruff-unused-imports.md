# Refactor 04-B — Auto-remove F401 / F811 unused imports across backend + tests

You are a **worker session** running in a git worktree. This is a mechanical (b) dead-code refactor with high blast radius (52 files) but extremely low risk (each fix is a single import-line removal).

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #1, #2 lint-delta-stable, #6 dead-file 3-step check)
3. `REFACTOR_AUDIT.md` § "Categories" — this is **(b) dead-code**
4. This prompt

## Goal

The codebase has 142 `F401` (unused imports) and 7 `F811` (redefinition) ruff errors. Auto-fix all of them via `ruff check --fix --select F401,F811 backend tests`. Confirm tests still pass and nothing semantically broke.

## In scope

- `backend/` — every Python file
- `tests/` — every test file
- ONE command: `uv run ruff check --select F401,F811 backend tests --fix`
- Spot-checks for false positives (see Verification plan)

## Out of scope

- All other ruff rule codes. We are NOT auto-fixing the full 449-error baseline; only F401 + F811. Ruff has 164 fixable suggestions across many rules — most should NOT be touched mechanically (e.g. import-order changes can break circular import workarounds; type-annotation changes can break runtime).
- `frontend/`. Different language, different tooling.
- The `--unsafe-fixes` flag. Stay on safe fixes only.
- Restructuring imports beyond removing unused ones (no `isort`-style re-ordering).

## Verification plan

### Pre-state capture
```bash
git status > /tmp/04B_dirty_pre.txt
just lint > /tmp/04B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/04B_lint_pre.txt
grep -cE "F401|F811" /tmp/04B_lint_pre.txt > /tmp/04B_f401_811_pre.txt
just test > /tmp/04B_test_pre1.txt 2>&1
just test > /tmp/04B_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/04B_test_pre1.txt | sort > /tmp/04B_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/04B_test_pre2.txt | sort > /tmp/04B_baseline2.txt
comm -12 /tmp/04B_baseline1.txt /tmp/04B_baseline2.txt > /tmp/04B_stable_failures.txt

# Save the list of files about to be edited:
uv run ruff check --select F401,F811 backend tests --diff 2>&1 | grep -E "^---" | awk '{print $2}' | sort -u > /tmp/04B_files_pre.txt
wc -l /tmp/04B_files_pre.txt
```

### Caveat for F401: `validate_design`

Pre-flight observed `backend.core.validator.validate_design imported but unused` in 16 test files. Before applying the fix:

1. Open one such test file (e.g. `tests/test_overhang_geometry.py`).
2. Confirm the import is genuinely unused (grep for `validate_design(` in the file body).
3. If unused: ruff fix is correct.
4. If the import IS referenced (e.g. via `pytest.fixture` autouse or a type annotation that ruff missed): **stop, document as a false positive, exclude that file from the fix via `--exclude`**.

Same caveat applies to any F401 in code with `__all__`-driven re-export tricks — confirm by reading the file before mass-fix. If you find ≥ 1 false positive, run the fix with explicit per-file exclusions; do NOT skip the entire prompt.

### Implementation
```bash
uv run ruff check --select F401,F811 backend tests --fix
git diff --stat | head -60   # confirm only Python files in backend/ + tests/
```

### Post-state capture
```bash
just lint > /tmp/04B_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/04B_lint_post.txt
grep -cE "F401|F811" /tmp/04B_lint_post.txt > /tmp/04B_f401_811_post.txt   # expect 0 (or near-zero if false positives excluded)
just test > /tmp/04B_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/04B_test_post.txt | sort > /tmp/04B_post_failures.txt
diff /tmp/04B_stable_failures.txt /tmp/04B_post_failures.txt   # ⊆ baseline ∪ flake

# Confirm net lint error count dropped by ~149:
echo "Pre lint errors:" ; head -1 /tmp/04B_lint_pre.txt | grep -oE "Found [0-9]+ errors"
echo "Post lint errors:" ; head -1 /tmp/04B_lint_post.txt | grep -oE "Found [0-9]+ errors"
```

## Stop conditions

- Worktree's pre-state shows uncommitted edits in any file ruff would touch: stop, report.
- `just test` post-failures contain a NEW failure (not in `stable_baseline ∪ flakes`): **revert all changes** via `git checkout HEAD -- backend tests` and stop. The most likely cause is a false-positive F401 (e.g. import had a side effect like registering a route or model).
- Lint error count went UP: revert, stop, report.
- Ruff modifies a file outside `backend/` or `tests/`: revert, stop. (`--select F401,F811` should never do this, but verify.)
- Ruff fix touches a `__init__.py` and removes an import that was a deliberate re-export: revert that file's changes, document as false positive.

## Output (worker's final message)

```markdown
## 04-B ruff F401/F811 cleanup — <REFACTORED|UNSUCCESSFUL>

### Pre-existing dirty state declaration
<git status output at session start; expect "nothing to commit" since worktree is fresh>

### False-positive exclusions (if any)
<list of files where the F401/F811 fix was reverted because the import had a runtime side effect or __all__ re-export>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 14. Ruff F401 / F811 unused-import cleanup — `low` ✓ REFACTORED
- **Category**: (b) dead-code
- **Move type**: additive — pure deletion, no symbol re-binding
- **Where**: `backend/`, `tests/` (52 files initially, after exclusions <K> files)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: <K>; other-files: none
- **Transparency check**: PASS — no public symbol semantics changed (only import declarations removed); imports of these symbols *from other modules* unaffected
- **API surface added**: none
- **Visibility changes**: none
- **Callsites touched**: 0 (these are dead imports — no callers ever read them)
- **Symptom**: 142 F401 + 7 F811 = 149 ruff errors across 52 files
- **Why it matters**: dead imports add noise to module-load time, mislead readers into thinking a symbol is used (the `validate_design` cluster across 16 test files is the worst case), and bloat the module graph. Mechanical cleanup with high signal-to-risk ratio.
- **Change**: `uv run ruff check --select F401,F811 backend tests --fix`
- **Implementation deferred**: <none — fully implemented> OR <details if any false positives left for manual review>
- **Effort**: S (mechanical, ~5 min worker time)
- **Three-Layer**: not applicable — pure import cleanup
- **Pre-metric → Post-metric**:
  - F401 count: 142 → <N>
  - F811 count: 7 → <M>
  - total ruff errors: 449 → <P>; expected Δ ≈ −149
  - tests: <pre-pass>/<pre-fail>/<pre-error> → <post-same set>
- **Raw evidence**: `/tmp/04B_*.txt`
- **Linked Findings**: —
- **Queued follow-ups**: <if false positives surfaced any latent bugs (e.g. `validate_design` was meant to be called), file as separate prompts>
```

## Success criteria

- [ ] `just lint` post-error-count ≤ pre-error-count (delta should be ~−149)
- [ ] `just test` post-failures ⊆ stable_baseline ∪ flakes
- [ ] No file outside `backend/` or `tests/` modified
- [ ] False-positive exclusions documented per file (or "none" if all fixes were correct)
- [ ] `### Pre-existing dirty state declaration` populated honestly

## Do NOT

- Use `--unsafe-fixes`.
- Apply other ruff rule codes (no `--select F401,F811,*`).
- Reorder imports (no isort).
- Edit `frontend/`.
- Commit.
- Append to `REFACTOR_AUDIT.md` from the worktree.
