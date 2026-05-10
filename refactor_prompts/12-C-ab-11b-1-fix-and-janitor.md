# Refactor 12-C — AB-11B-1 fix (`build_p_gro_order` length-guard) + small janitor

**Worker prompt. (b) bug-fix + small janitor — single-issue scope.**

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (esp. #15 hardened-fail, #16 manager-hand-apply threshold ≤ 5 LOC)
3. `REFACTOR_AUDIT.md` Finding #39 (Pass 11-B atomistic_to_nadoc tests + AB-11B-1 documented), Followup 11-B (validation of AB-11B-1)
4. `backend/core/atomistic_to_nadoc.py:140-160` — read the `build_p_gro_order` function fully

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

Fix AB-11B-1: `build_p_gro_order` line 142 calls `int(line[22:26])` inside the FIRST loop without a length guard, while the SECOND loop at L152 has the guard `if len(line) < 26: continue`. For short ATOM-prefixed lines, the first loop crashes before the second's guard fires — making line 153 effectively unreachable.

## In scope

**Option A (recommended)**: add `if len(line) < 26: continue` guard to the first loop matching the second loop's guard. Single-line addition.

**Option B**: fold the two loops into one if logic permits without changing semantics.

Pick whichever yields a cleaner diff. After the fix:
- Verify the previously-unreachable line 153 is now reachable by adding 1-2 tests in `tests/test_atomistic_to_nadoc.py` that pass short ATOM-prefixed lines through `build_p_gro_order`. Tests should:
  - Assert the function does NOT raise on short-line input
  - Assert the function correctly skips those lines (no spurious entries in the output)

## Out of scope

- Other apparent-bugs (none currently flagged for atomistic_to_nadoc.py)
- Refactoring beyond the length-guard fix
- Modifying the test count target beyond +1-2 tests for the guard
- Touching `_SUGAR` template (calibration workstream)
- Other atomistic files (separate Pass 12-A/B scope)

## Verification

3× baseline + lint per precondition #1, #2:

```bash
for i in 1 2 3; do just test > /tmp/12C_test_pre$i.txt 2>&1; done
just lint > /tmp/12C_lint_pre.txt 2>&1
```

Post:
- `atomistic_to_nadoc.py` modified (1-2 LOC change)
- 1-2 new tests added to `tests/test_atomistic_to_nadoc.py`
- All 33 existing tests still pass
- Coverage on atomistic_to_nadoc.py ≥ 96% (from Pass 11-B baseline) — line 153 should now be reachable + covered
- Lint Δ = 0
- Failure set ⊆ stable_baseline ∪ KNOWN_FLAKES

## Stop conditions

- Step 0 fails → STOP (literal `exit 1`)
- Fix changes function semantics for valid PDB input → revert, STOP
- Post-fix tests fail → revert, STOP
- Lint Δ > 0 → revert, STOP

## Output (Findings #43)

Required:
- Fix applied: Option A or B (with 1-2 LOC diff shown)
- New tests added (count + brief description)
- Coverage on atomistic_to_nadoc.py: pre 96% → post (should be 96% or higher; line 153 now reachable)
- Lint Δ
- Linked: #39 (apparent-bug surface), Followup 11-B (validation)

## USER TODO

None needed. The fix is a defensive guard against malformed input — no user-visible behavior change for well-formed PDB files (which is the normal case).

## Do NOT

- Refactor beyond the length-guard fix
- Modify well-formed-PDB code paths
- Touch `_SUGAR` template
- Commit / append to REFACTOR_AUDIT.md (manager aggregates)
