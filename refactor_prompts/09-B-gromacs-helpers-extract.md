# Refactor 09-B — Extract `gromacs_package.py` pure helpers + tests

You are a **worker session** in a git worktree. Pure-helper extraction from `gromacs_package.py` (Pass 8-B's #4 candidate). The 3 target helpers operate on PDB text strings — no `subprocess` / FF-dir / GROMACS install needed for tests.

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)**, **#15 (CWD-safety)**, **#16 (≤5 LOC hand-apply)**
3. `REFACTOR_AUDIT.md` § "Findings" #16 (coverage audit naming `gromacs_package.py` as `hard-to-test`), #18 (PDB pure-math extraction precedent), #24 (08-B audit naming this as #4 candidate)
4. `backend/core/gromacs_package.py:1-260` — read the 3 target helpers and surrounding context (no need to read the 2332-LOC GROMACS-spawning core)
5. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
```

## Goal

Extract 3 pure-text helpers from `backend/core/gromacs_package.py` to a new `backend/core/gromacs_helpers.py` sibling module. Add tests in `tests/test_gromacs_helpers.py`. **Pure helpers**: operate on PDB text strings, no I/O, no subprocess. Testable without GROMACS installed.

## In scope — exact functions

Move these 3 functions verbatim:

- `_rename_atom_in_line(line: str, old: str, new: str) -> str` (L193, ~12 LOC)
- `adapt_pdb_for_ff(pdb_text: str, ff: str) -> str` (L206, ~50 LOC)
- `strip_5prime_phosphate(pdb_text: str) -> str` (L257, ~50 LOC)

Plus any module-private constants they reference (read the bodies; if e.g. a FF-name table is referenced, move it too).

The new file at `backend/core/gromacs_helpers.py`:
```python
"""Pure-text helpers extracted from gromacs_package.py (Refactor 09-B).

These operate on PDB text strings only — no subprocess, no FF-directory
lookup, no GROMACS install required. Testable in isolation.
"""

# (move the 3 functions verbatim with any required imports)
```

Update `gromacs_package.py` to re-import them at the top:
```python
from backend.core.gromacs_helpers import (
    _rename_atom_in_line,
    adapt_pdb_for_ff,
    strip_5prime_phosphate,
)
```

Delete the 3 function definitions from `gromacs_package.py` after moving.

## Tests in `tests/test_gromacs_helpers.py`

- `TestRenameAtomInLine`:
  - rename C5'→C5* in a sample PDB ATOM line; assert the new line has C5* in the right column
  - input line with no match → returned unchanged
  - input line with `old` substring outside the atom-name field → unchanged (column-anchored, not free substring replace)

- `TestAdaptPdbForFf`:
  - amber99sb-ildn happy path: feed a 4-line synthetic PDB with DA/DT/DG/DC residues; assert the output has expected atom-name remappings (whatever `adapt_pdb_for_ff` actually does — read its body to know what to assert)
  - unknown FF name → raises ValueError or passes through unchanged (read body)

- `TestStrip5primePhosphate`:
  - input PDB with explicit `P`, `OP1`, `OP2`, `O5'` 5'-phosphate atoms → output strips them
  - input PDB without those atoms → unchanged
  - residue-1 vs residue-N: only residue-1's phosphate stripped (or all 5'-ends, depending on what the function actually does)

For each test, build synthetic PDB strings inline (no fixture file; reuse the inline-writer pattern from `tests/test_pdb_import_geometry.py::TestAnalyzeDuplex`).

## Out of scope

- The 2332-LOC GROMACS-spawning core (anything that calls `subprocess.run(['gmx', ...])`).
- Other coverage-low modules.
- Adding `pytest-cov` to dev-deps.
- Modifying `gromacs_package.py` beyond the import-and-delete.

## Verification plan

### Pre-state (3× baseline)
```bash
git status > /tmp/09B_dirty_pre.txt
just lint > /tmp/09B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/09B_lint_pre.txt
for i in 1 2 3; do just test > /tmp/09B_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/09B_test_pre$i.txt | sort > /tmp/09B_baseline$i.txt; done
comm -12 /tmp/09B_baseline1.txt /tmp/09B_baseline2.txt | comm -12 - /tmp/09B_baseline3.txt > /tmp/09B_stable_failures.txt
```

### Implementation
1. Read the 3 functions in full at `gromacs_package.py:193-310` (rough range).
2. Identify any module-private constants/imports they need.
3. Create `backend/core/gromacs_helpers.py` with the 3 functions verbatim + needed deps.
4. Add the import line at the top of `gromacs_package.py` (after existing imports).
5. Delete the 3 originals.
6. Write `tests/test_gromacs_helpers.py` with ≥ 8 tests across 3 classes.
7. Run `just test-file tests/test_gromacs_helpers.py` — all should pass.
8. Run full `just test` — failure set baseline-preserved.

### Post-state
```bash
just lint > /tmp/09B_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/09B_lint_post.txt
just test > /tmp/09B_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/09B_test_post.txt | sort > /tmp/09B_post_failures.txt
diff /tmp/09B_stable_failures.txt /tmp/09B_post_failures.txt   # ⊆ stable_baseline ∪ flakes

uv run coverage run -m pytest tests/test_gromacs_helpers.py
uv run coverage report --include='backend/core/gromacs_helpers.py' > /tmp/09B_cov_post.txt
```

## Stop conditions

- Step 0 fails: STOP.
- A target function's body uses `subprocess`, `os.system`, `Path(...).read_text()`, or any FF-directory lookup: STOP — it's not pure; document and reduce scope.
- Test post-failure not in stable_baseline ∪ flakes: revert, stop.
- The 3 functions reference module-private state (e.g. a singleton config) beyond constants: STOP — extracting it requires bigger surgery.

## Output

```markdown
## 09-B gromacs_helpers extract + tests — <REFACTORED|UNSUCCESSFUL>

### CWD-safety check
- Match: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends)

### 27. `gromacs_package.py` pure-helper extraction + tests — `low` ✓ REFACTORED
- **Category**: (c) god-file decomposition + (test) coverage backfill
- **Move type**: verbatim (3 functions) + new test file
- **Where**: `backend/core/gromacs_package.py:193-307` (3 function defs deleted + 1 import line added); `backend/core/gromacs_helpers.py` (new, ~120 LOC); `tests/test_gromacs_helpers.py` (new, ~150 LOC, ≥8 tests)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 3 (gromacs_package.py, gromacs_helpers.py new, test file new)
- **Transparency check**: PASS — `gromacs_package.py`'s public API unchanged (the 3 helpers were already exported by name; now re-imported and re-exported transparently OR they're internal-only — read the file to confirm)
- **API surface added**: 3 imports in gromacs_helpers.py (matched by 3 deleted from gromacs_package.py); net public surface unchanged
- **Visibility changes**: `_rename_atom_in_line` was module-private in gromacs_package.py; now module-private in gromacs_helpers.py but importable by gromacs_package.py via the public name. Effectively unchanged.
- **Callsites touched**: 0 external (gromacs_package.py's internal callers updated automatically by the import); + 1 import line added
- **Pre-metric → Post-metric**:
  - gromacs_package.py LOC: <pre> → <post> (Δ ≈ −110)
  - gromacs_helpers.py LOC: 0 → <K>
  - gromacs_helpers.py coverage: 0% (didn't exist) → ≥80% (target)
  - Tests: <pre> → <pre + N>
  - Lint Δ: 0
- **Raw evidence**: `/tmp/09B_*.txt`, `/tmp/09B_cov_post.txt`
- **Linked Findings**: #16 (Tier-2 hard-to-test), #18 (pure-math precedent), #24 (audit named this candidate)
- **Queued follow-ups**: GROMACS-spawning core remains 0% covered + hard-to-test (need GROMACS install or mocks); future pass.
```

## Success criteria

- [ ] Step 0 passed
- [ ] `backend/core/gromacs_helpers.py` exists with 3 pure helpers
- [ ] `tests/test_gromacs_helpers.py` has ≥ 8 tests across 3 classes
- [ ] gromacs_package.py reduced by ≥ 100 LOC
- [ ] gromacs_helpers.py coverage ≥ 80%
- [ ] Test post-failure set ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0

## Do NOT
- Touch GROMACS-spawning code.
- Add new helpers; only move the 3 named.
- Modify `pyproject.toml`.
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
