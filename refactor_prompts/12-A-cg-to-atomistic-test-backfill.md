# Refactor 12-A — `cg_to_atomistic.py` test backfill

**Worker prompt. (test) coverage backfill — same template as 11-B (atomistic_to_nadoc), 06-A (PDB), 10-D (ws), 10-E (fem_solver pre-archive).**

## Pre-read

1. `CLAUDE.md` (Three-Layer Law)
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #15 hardened-fail, #21 calibrated coverage targets + Pass 11-B refinement for env-bound fallback I/O modules)
3. `REFACTOR_AUDIT.md` Findings #16 (parent backend coverage audit; `cg_to_atomistic.py` flagged 0%), #39 (Pass 11-B atomistic_to_nadoc precedent), policy row 2026-05-10 (atomistic family unlock)
4. `memory/REFERENCE_ATOMISTIC.md` if available
5. `backend/core/cg_to_atomistic.py` (241 LOC) — read FULLY before writing tests

## Step 0 — CWD safety (precondition #15 — HARDENED)

```bash
pwd
git rev-parse --show-toplevel
if [ "$(pwd)" != "$EXPECTED_WORKTREE" ]; then
    echo "FATAL: not in worktree $EXPECTED_WORKTREE (got $(pwd))"
    exit 1
fi
```

## Goal

Calibrated coverage backfill on `backend/core/cg_to_atomistic.py` (currently **0%** per Finding #16; verify pre-run since 11-B revealed Finding #16's metrics may be stale).

Per precondition #21 (Pass 11-B refinement): if module has env-bound fallbacks (subprocess/binary/optional-dep), set target to natural ceiling not 70% cap.

```bash
just test-file --cov=backend.core.cg_to_atomistic --cov-report=term-missing 2>&1 | tail -10
```

Then identify what's currently uncovered. Set target = natural ceiling.

## In scope

- Build a synthetic CG → atomistic input fixture (likely a small CG bead model + parameter dict)
- Test the orchestrator entry point + each helper function exposed at module level
- Tests must verify ACTUAL OUTPUT VALUES per precondition #21 prohibition (no "no exception raised")
- Use real `numpy.allclose` / column-anchored string assertions / reference-data comparisons
- If the module reads B-DNA template data, build the fixture from public template values, not by mocking

## Out of scope

- Modifying `cg_to_atomistic.py` production code
- Adding new dependencies to `pyproject.toml`
- Calibration workstream (`_SUGAR` template drift, Finding #18) — apparent-bug only; do NOT fix
- `atomistic.py` + `atomistic_helpers.py` (separate scopes)
- AB-11B-1 cleanup (separate Pass 12-C scope)

## Verification

3× baseline + lint per precondition #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/12A_test_pre$i.txt 2>&1; done
just lint > /tmp/12A_lint_pre.txt 2>&1
```

Post:
- `tests/test_cg_to_atomistic.py` exists
- N tests pass (target ≥ 8)
- Coverage on cg_to_atomistic.py ≥ calibrated target (or natural ceiling reached + audit-noted)
- Lint Δ = 0
- Failure set ⊆ stable_baseline ∪ KNOWN_FLAKES

## Stop conditions

- Step 0 fails → STOP (literal `exit 1` per precondition #15)
- Real subprocess invocation needed (mrdna, GROMACS, NAMD) → those need different fixtures + tier-3
- Production code modification needed → STOP (this is coverage backfill)
- Test failure not in baseline → revert, STOP

## Output (Findings #41)

Required:
- Test count + per-class breakdown
- Pre-coverage % vs post-coverage % on cg_to_atomistic.py
- Calibrated target + whether natural ceiling reached
- Honesty samples (3 representative test bodies showing real assertions)
- Lint Δ
- Apparent-bug flags (if any; do NOT fix)
- Linked: #16, #39 (Pass 11-B precedent), policy row 2026-05-10

## Do NOT

- Modify `cg_to_atomistic.py`
- Add `pyproject.toml` deps
- Mock orchestrators (`@patch` on the SUT itself violates precondition #21)
- Touch `_SUGAR` template
- Commit / append to REFACTOR_AUDIT.md
