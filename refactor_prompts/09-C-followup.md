# Followup 09-C — Evaluate `fem_solver.py` pure-math test backfill

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/09-C-fem-solver-pure-math-tests.md`
2. Worker's Findings #28 text

## Q1 — Tests
- `cd <worktree> && just test-file tests/test_fem_solver_math.py 2>&1 | tail -5` — all pass.
- `grep -cE "^    def test_" <worktree>/tests/test_fem_solver_math.py` ≥ 6.

## Q2 — Coverage
`cd <worktree> && uv run coverage run -m pytest tests/test_fem_solver_math.py && uv run coverage report --include='backend/physics/fem_solver.py'` — match worker's claimed ≥ 50%.

## Q3 — Test honesty
Sample 2 tests:
- `_beam_stiffness_local` symmetry test: confirms `K == K.T` on real returned matrix (not mock).
- `_transform_to_global` identity test: real `np.eye(3)` rotation, real numpy comparison.

## Q4 — Production untouched
`git -C <worktree> diff HEAD -- backend/` empty.

## Q5 — Apparent-bug flags
If worker raised any: validate by reading the production code under test. Per `feedback_interrupt_before_doubting_user.md`, math is calibrated.

## Output

```markdown
### Followup 09-C — fem_solver pure-math tests  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>

**Tests**: <N> declared, <N> passing
**Coverage**: 22% → claimed <X%>, observed <Y%>
**Test-honesty (2 sampled)**: agree/disagree
**Production-untouched**: yes/no
**Apparent-bug flags**: <validate each | none>

**Prompt evaluation**
- Were the 2 named target functions sufficient or did the worker test additional helpers?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement code, append to REFACTOR_AUDIT.md.
