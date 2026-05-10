# Followup 08-C — Evaluate `make_minimal_design` REVERSE-staple fix

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/08-C-fix-make-minimal-design-reverse-staple.md`
2. Worker's Findings #25 text

## Q1 — Convention fix correct?
- `git -C <worktree> diff HEAD -- tests/conftest.py` — the REVERSE staple should now have `start_bp > end_bp`.
- Read `backend/core/sequences.py:84-95` to confirm convention. Worker's fix should match.

## Q2 — `domain_bp_range` no longer empty
Run a quick check in the worktree:
```python
from tests.conftest import make_minimal_design
from backend.core.sequences import domain_bp_range
d = make_minimal_design()
staple = next(s for s in d.strands if s.strand_type.name == 'STAPLE')
print(list(domain_bp_range(staple.domains[0])))
```
Should produce a non-empty list of bp indices.

## Q3 — Silent-reliance migrations honest
For each test the worker updated as "silent-reliance":
- Read the test body before and after.
- Confirm the worker's classification was correct (test was using `make_minimal_design()` and accidentally relying on the empty REVERSE-staple iterator).
- Confirm the migration is minimal — it doesn't change test intent.

## Q4 — No production code modified
`git -C <worktree> diff HEAD -- backend/` empty.

## Q5 — Test post-failure set ⊆ stable_baseline ∪ flakes
Run `cd <worktree> && just test 2>&1 | tail -5`. Compare to `/tmp/08C_stable_failures.txt`.

## Q6 — Apparent-bug flags
If worker raised any "real bug exposed by fix" flags, validate each:
- Read the test that newly fails.
- Read the production code under test.
- Decide: real production bug OR worker misclassification.

## Output

```markdown
### Followup 08-C — make_minimal_design REVERSE-staple fix  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>

**Convention fix correct**: yes/no
**`domain_bp_range` no longer empty**: yes/no (with bp range observed)
**Silent-reliance migrations**: <K> tests updated; <K> validated as honest
**No production code modified**: yes/no
**Test post ⊆ stable_baseline ∪ flakes**: yes/no
**Apparent-bug flags validated**: <none | list with severity>

**Prompt evaluation**
- Was 6-test silent-reliance ceiling realistic? Was it hit?
- Did any silent-reliance test reveal a fixture-design issue beyond the REVERSE-staple convention?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Modify code, append to REFACTOR_AUDIT.md.
