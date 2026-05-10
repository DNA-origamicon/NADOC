# Followup 08-B — Evaluate backend non-atomistic audit

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/08-B-backend-non-atomistic-audit.md`
2. `memory/feedback_phase_constants_locked.md` — verify worker did not recommend touching locked constants
3. Worker's Findings #24 text

## Q1 — Atomistic exclusion respected
- The 3 atomistic files (`atomistic.py`, `atomistic_to_nadoc.py`, `cg_to_atomistic.py`) MUST be marked DEFERRED, not audited.
- Worker should not have recommended any change to atomistic files.

## Q2 — `_PHASE_*` / `make_bundle_continuation` discipline
- Verify worker did not flag `_PHASE_*` constants for change.
- Verify worker did not recommend splitting `make_bundle_continuation`.
- If either appears as a "high" candidate, flag the worker's discipline failure.

## Q3 — Tag-honesty audit (3 sampled)
Same as 08-A but for backend files. For `high` candidates:
- LOC > 1500, OR function ≥ 300 LOC, OR coverage < 30%, OR Three-Layer-Law violation, OR radon CC ≥ D in any function.

## Q4 — Three-Layer-Law canary
If worker reported any layer violations, validate each carefully — these are highest-priority for the project.

## Q5 — Coverage gaps surfaced match Finding #16's earlier audit
Worker should not contradict Finding #16's coverage measurements. If they report different numbers, flag.

## Q6 — No code modified
`git -C <worktree> diff HEAD --stat` empty.

## Q7 — Pre-tracked correctness
Files cited as `pre-tracked` should genuinely have an existing Finding (#14, #16, #17, #18, #19, #20, #21).

## Output

```markdown
### Followup 08-B — backend non-atomistic audit  (eval date)

**Worker outcome confirmation**: <INVESTIGATED — confirmed/disputed>
**Worktree audit context**: <path>

**Atomistic exclusion respected**: yes/no — `<files> marked DEFERRED`
**Locked-area discipline (_PHASE_*, make_bundle_continuation)**: <upheld | flagged with details>
**Tag-honesty (3 sampled)**: <pass/fail per sample>
**Three-Layer-Law flags validated**: <none | validated each>
**Coverage gaps consistent with Finding #16**: yes/no
**No code modified**: yes/no
**Pre-tracked references valid**: yes/no

**Prompt evaluation**
- Did the explicit DEFERRED list cover the right scope?
- Were any sensitive areas not anticipated by the prompt's exclusion list?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Modify code, append to REFACTOR_AUDIT.md.
