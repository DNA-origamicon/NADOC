# Followup 06-A — Evaluate PDB import pure-math test backfill

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list   # find the agent-* worktree path
```

## Pre-read
1. `refactor_prompts/06-A-pdb-import-pure-math-tests.md`
2. Worker's Findings #18 text (passed by manager)

## Q1 — Tests written + passing?

- `cat <worktree>/tests/test_pdb_import_geometry.py | grep -cE "^def test_"` — count test functions. ≥ 6 expected.
- Run `just test-file tests/test_pdb_import_geometry.py` in the worktree. All declared tests should pass.
- Re-run full `just test` in worktree. Confirm baseline preserved (failure-set diff empty).

## Q2 — Coverage delta honest?

- `uv run pytest --cov=backend.core.pdb_import --cov-report=term <worktree>/tests/test_pdb_import_geometry.py` — match worker's claimed post-coverage %.
- Pre-coverage was 0% per Finding #16. If post is ≥30%, claim is honest. If post is below 30%, flag — maybe tests didn't actually exercise the helpers (e.g. mocked too aggressively).

## Q3 — Test fixture honesty

For 2-3 sampled tests, open the test body and judge:
- Are assertions on real numbers (with tolerance) or on placeholder values?
- Are the synthetic `Residue`-like objects real enough to exercise the helper, or do they short-circuit it?
- If a fixture PDB was added, does it actually contain the expected duplex geometry?

A test like `assert abs(result - expected) < 1e-3` with `result = func(real_input)` and `expected = known_value` is honest.
A test like `assert func(mock).value == mock.expected_value` is mock-circular and uninformative.

## Q4 — Production code untouched

- `git -C <worktree> diff HEAD --stat backend/`: must be empty.
- Confirm `pdb_import.py` was not modified to make tests pass.

## Q5 — Apparent-bug flags

If the worker's Findings entry lists "Apparent-bug flags", spot-check the math. The user is a biophysicist and may want to fix the helper rather than work around it. Flag for manager attention.

## Q6 — Skipped functions

For each function the worker marked as "skipped":
- Confirm the skip reason is real (e.g. helper truly is unreachable from synthetic stubs and would require a fixture PDB the worker didn't have time to construct).
- Don't mark as a regression — skips are allowed if documented.

## Output (return as agent result text)

```markdown
### Followup 06-A — PDB import pure-math test backfill  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>
**Diff vs claimed-touched files**: <K claimed | M observed>

**Test-count audit**
- declared tests: <N>
- passing: <N>
- skipped: <K> (with reasons: ...)

**Coverage audit**
- post `pdb_import.py` coverage: claimed <X%>, observed <Y%>; honest: yes/no

**Test-fixture honesty audit (2-3 sampled)**
- <test_name>: real-input + real-expected | mock-circular | other
- ...

**Production-code untouched**: yes / no
**Apparent-bug flags raised by worker**: <list, validate each>

**Prompt evaluation**
- Was the synthetic-stub vs fixture-PDB choice clearly enough laid out?
- Did any function's body need a different test approach than the prompt anticipated?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Fix any apparent bug in production code.
- Add tests yourself.
- Append to REFACTOR_AUDIT.md.
