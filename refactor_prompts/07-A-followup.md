# Followup 07-A — Evaluate PDB orchestrator test backfill

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/07-A-pdb-orchestrator-tests.md`
2. Worker's Findings #20 text

## Q1 — Tests
- `cd <worktree> && just test-file tests/test_pdb_to_design.py 2>&1 | tail -5` — all pass.
- Count tests: `grep -cE "^def test_" <worktree>/tests/test_pdb_to_design.py` ≥ 5 expected.

## Q2 — Coverage
- `cd <worktree> && uv run pytest --cov=backend.core.pdb_to_design --cov-report=term tests/test_pdb_to_design.py 2>&1 | grep "pdb_to_design"` — match worker's claimed % (≥ 40 expected).

## Q3 — Test honesty
Sample 2 tests:
- `test_import_pdb_single_duplex_returns_valid_design`: confirm the synthetic PDB has real ATOM coordinates (not placeholder floats); the assertion checks real `Design` fields.
- `test_merge_pdb_into_design_appends_to_existing`: confirm `make_minimal_design()` is real (not mocked); assertion validates the merged Design is a `Design` instance with expected helix counts.

## Q4 — Production untouched
`git -C <worktree> diff HEAD -- backend/`: empty.

## Q5 — Apparent-bug flags
For each, validate:
- The flagged behavior actually occurs (re-run the test with debug print or open the implementation).
- The worker's `feedback_interrupt_before_doubting_user.md` discipline held: the flag is documented, not "fixed".

## Q6 — Scope
- `git -C <worktree> diff HEAD --stat`: only `tests/test_pdb_to_design.py` (and possibly `tests/fixtures/pdb/<file>` if added).
- No `backend/` edits, no `pyproject.toml`.

## Output

```markdown
### Followup 07-A — PDB orchestrator tests  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>
**Diff vs claimed-touched files**: <K claimed | M observed>

**Test-count audit**: <N>; passing: <N>
**Coverage audit**: claimed <X%>, observed <Y%>
**Test-honesty (2 sampled)**: <agree/disagree per sample>
**Production-untouched**: yes/no
**Apparent-bug flags**: <validate each>
**Scope**: <files match prompt; yes/no>

**Prompt evaluation**
- Was the synthetic-PDB approach sufficient or did the worker need a fixture file?
- Did the orchestrator tests reveal anything Pass 6's pure-math tests missed?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Modify code, write tests, fix flagged bugs, append to REFACTOR_AUDIT.md.
