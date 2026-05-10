# Followup 07-B — Evaluate `sequences.py` test backfill

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/07-B-sequences-test-backfill.md`
2. Worker's Findings #21 text

## Q1 — Tests
- `cd <worktree> && just test-file tests/test_sequences.py 2>&1 | tail -5` — all pass.
- `grep -cE "^def test_" <worktree>/tests/test_sequences.py` ≥ 15 expected.

## Q2 — Coverage
`cd <worktree> && uv run pytest --cov=backend.core.sequences --cov-report=term tests/test_sequences.py 2>&1 | grep "sequences"` — should be ≥ 60% (target) or ≥ 40% (partial credit).

## Q3 — Test honesty (sample 3)
- `TestComplementBase::*`: a real lookup-table check (e.g. `assert complement_base('A') == 'T'`), not mock-circular.
- `TestAssignScaffoldSequence::*`: actual call to `assign_scaffold_sequence(design, 'M13mp18')`; assert resulting `Design` has scaffold strand with non-None sequence of expected length.
- `TestAssignStapleSequences::*`: scaffold sequence assigned first; staples then have Watson-Crick complements.

## Q4 — Production untouched
`git -C <worktree> diff HEAD -- backend/`: empty.

## Q5 — Skipped-with-reason validation
Worker may have skipped M13mp18-loading-dependent tests if scaffold files aren't in worktree. For each skip:
- Confirm the file actually isn't accessible (`ls m13mp18_scaffold.txt` from worktree root — should be at project root).
- If file IS accessible and worker still skipped, flag as missed test.

## Q6 — Scope
- `git -C <worktree> diff HEAD --stat`: only `tests/test_sequences.py`.

## Output

```markdown
### Followup 07-B — sequences.py test backfill  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>

**Test-count audit**: <N>; passing: <N>
**Coverage audit**: 20.8% → claimed <X%>, observed <Y%>
**Test-honesty (3 sampled)**: <agree/disagree>
**Production-untouched**: yes/no
**Skipped-tests validation**: <legit | unjustified>
**Scope**: <files match>

**Prompt evaluation**
- Did the M13mp18 file accessibility match the prompt's caveat?
- Were the orchestrator tests achievable with `make_minimal_design()` or did they need bespoke fixtures?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Modify code, write tests, fix flagged bugs, append to REFACTOR_AUDIT.md.
