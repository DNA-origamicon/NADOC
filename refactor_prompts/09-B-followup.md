# Followup 09-B — Evaluate `gromacs_helpers.py` extraction + tests

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/09-B-gromacs-helpers-extract.md`
2. Worker's Findings #27 text

## Q1 — Helper extraction correct
- `grep -nE "^def (_rename_atom_in_line|adapt_pdb_for_ff|strip_5prime_phosphate)" <worktree>/backend/core/gromacs_helpers.py` — all 3 present.
- `grep -nE "^def (_rename_atom_in_line|adapt_pdb_for_ff|strip_5prime_phosphate)" <worktree>/backend/core/gromacs_package.py` — none (deleted).
- Diff each function body against HEAD's gromacs_package.py — byte-identical.

## Q2 — Pure-helper claim load-bearing
Confirm the new `gromacs_helpers.py` does NOT import:
- `subprocess`
- `os.system`
- `pathlib.Path` (for filesystem ops; plain Path manipulation is fine if no I/O)
- Any module that itself does I/O

`grep -nE "import (subprocess|os|pathlib)" <worktree>/backend/core/gromacs_helpers.py` — flag any matches.

## Q3 — Tests
- `cd <worktree> && just test-file tests/test_gromacs_helpers.py 2>&1 | tail -5` — all pass.
- `grep -cE "^    def test_" <worktree>/tests/test_gromacs_helpers.py` ≥ 8.
- Spot-check 2 tests: confirm they use real synthetic PDB strings and real assertions (not mocks of `_rename_atom_in_line` itself).

## Q4 — Coverage
`cd <worktree> && uv run coverage run -m pytest tests/test_gromacs_helpers.py && uv run coverage report --include='backend/core/gromacs_helpers.py'` — match worker's claimed ≥ 80%.

## Q5 — Transparency
- `gromacs_package.py` callers of these 3 functions still work (the import line at the top of `gromacs_package.py` covers them).
- `git -C <worktree> diff HEAD --stat` shows only the 3 files (gromacs_package.py + new gromacs_helpers.py + new test file).

## Output

```markdown
### Followup 09-B — gromacs_helpers extract + tests  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>

**Helper extraction**: 3/3 byte-identical | <list any deviations>
**Pure-helper claim**: PASS — no subprocess/os/pathlib imports | FAIL — <list>
**Tests**: <N> declared, <N> passing
**Coverage**: claimed <X%>, observed <Y%>
**Transparency**: gromacs_package.py callers preserved: yes/no
**Scope**: <3 files | extras>

**Prompt evaluation**
- Did the extraction reveal any hidden dependency (FF-table, module constant)?
- Were the 3 chosen functions truly pure or did one need scope widening?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement code, write tests, fix flagged issues, append to REFACTOR_AUDIT.md.
