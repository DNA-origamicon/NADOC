# Refactor 11-B — `atomistic_to_nadoc.py` test backfill

**Worker prompt. (test) coverage backfill — same template as 06-A, 07-A, 09-C, 10-D, 10-E.**

## Pre-read

1. `CLAUDE.md` (Three-Layer Law)
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #21 calibrated coverage targets)
3. `REFACTOR_AUDIT.md` Findings #16 (backend coverage audit; `atomistic_to_nadoc.py` flagged 18.7% — Tier-2 testable), #20 (PDB orchestrator tests precedent), #28 (fem_solver pure-math; archived now), #33 (fem_solver integration tests; archived now)
4. `REFACTOR_AUDIT.md` audit-log row "2026-05-10 | policy" — atomistic family **UNLOCKED**
5. `memory/REFERENCE_ATOMISTIC.md` if available (PDB import/export specifics)
6. `backend/core/atomistic_to_nadoc.py` (428 LOC) — read FULLY
7. `tests/test_pdb_to_design.py` (Pass 7-A precedent) — same shape, different module

## Step 0 — CWD safety

```bash
pwd
git rev-parse --show-toplevel
```

## Goal

Calibrated coverage backfill on `backend/core/atomistic_to_nadoc.py` (currently **18.7%**). Per precondition #21, FIRST compute the natural ceiling:

```bash
just test-file --cov=backend.core.atomistic_to_nadoc --cov-report=term-missing 2>&1 | tail -20
```

Then identify what's currently uncovered. Set the target as the lower of:
- 70% (default per #21)
- (covered_stmts + named_helper_stmts) / total_stmts (the natural ceiling)

If the natural ceiling is <70%, declare REFACTORED-with-natural-ceiling per #21.

## In scope

- Build a synthetic atomistic input (likely a small PDB string + chain-map dict, or a tiny `Design` instance) as a test fixture.
- Test the orchestrator entry point + each helper function exposed at module level.
- Aim for tests that verify ACTUAL OUTPUT VALUES, not "no exception raised" (precondition #21 prohibition on test honesty).
- Use real `numpy.allclose` / column-anchored string assertions / reference-data comparisons.
- If the module reads B-DNA template data (per `REFERENCE_ATOMISTIC.md`), build the fixture from public template values, not by mocking.

## Out of scope

- Modifying `atomistic_to_nadoc.py` production code
- Adding new dependencies to `pyproject.toml`
- Atomistic calibration workstream (`_SUGAR` template drift Finding #18) — apparent-bug only; do NOT fix
- `atomistic.py` (separate Pass 11-A scope)

## Verification

3× baseline + lint per precondition #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/11B_test_pre$i.txt 2>&1; done
just lint > /tmp/11B_lint_pre.txt 2>&1
```

Post:
- `tests/test_atomistic_to_nadoc.py` exists
- N tests pass (target ≥ 8 tests)
- Coverage on `atomistic_to_nadoc.py` ≥ calibrated target (or natural ceiling reached + audit-noted)
- Lint Δ = 0
- Failure set ⊆ stable_baseline ∪ KNOWN_FLAKES

## Stop conditions

- Step 0 fails → STOP
- Any test requires real subprocess invocation (mrdna, GROMACS, NAMD) — those need different fixtures + are tier-3
- Any test requires real binary template data (e.g. PDB files >10 KB on disk) — fixture too heavy; reduce or skip-mark
- Production code modification needed → STOP (this is a coverage backfill, not a refactor)
- Test failure not in baseline → revert, STOP

## Output (Findings #39)

Required:
- Test count + per-class breakdown
- Pre-coverage % vs post-coverage % on atomistic_to_nadoc.py
- Calibrated target + whether natural ceiling reached
- Honesty samples (3 representative test bodies showing real assertions, not "no exception")
- Lint Δ
- Apparent-bug flags (if any; do NOT fix)
- Linked: #16 (parent audit), #20 (PDB precedent), policy row 2026-05-10 (atomistic unlock)

## USER TODO template

Coverage backfills don't need in-app smoke tests typically. If the fixture covers code paths users hit (e.g. atomistic export via UI), include:

1. `just dev` + `just frontend`; load saved `.nadoc` with atomistic data
2. Export atomistic via UI; verify file is identical to pre-test-backfill
3. Mark Finding #39 USER VERIFIED if clean

## Do NOT

- Modify `atomistic_to_nadoc.py`
- Add `pyproject.toml` deps
- Mock orchestrators (`@patch` on the SUT itself violates precondition #21)
- Touch `_SUGAR` template (calibration workstream)
- Commit / append to REFACTOR_AUDIT.md
