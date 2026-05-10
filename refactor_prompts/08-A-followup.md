# Followup 08-A — Evaluate frontend comprehensive audit

You are a **followup session**. Audit, do not implement.

## Step 0
```bash
git worktree list
```

## Pre-read
1. `refactor_prompts/08-A-frontend-comprehensive-audit.md`
2. Worker's Findings #23 text

## Q1 — Coverage of NOT SEARCHED set
- Verify the worker tagged every NOT SEARCHED file in `frontend/src/scene/` (42), `frontend/src/ui/` (32), `frontend/src/cadnano-editor/` (7) per master's inventory.
- `awk '/^## Inventory/,/^## Audit log/' /home/joshua/NADOC/REFACTOR_AUDIT.md | grep -E "^\| frontend/src/(scene|ui|cadnano-editor)" | grep -c "NOT SEARCHED"` should equal worker's `pass+low+high` count (i.e., 81 minus pre-tracked).

## Q2 — Tag-honesty audit (3 sampled)
Pick 3 files: 1 tagged `pass`, 1 tagged `low`, 1 tagged `high`. For each, verify the tag matches the heuristic signals:
- `pass` should have low LOC, no long functions, ≤ 1 ungated console.log, no cross-area boundary leaks
- `low` should have 1-2 cleanup signals (TODOs, magic numbers, ungated logs)
- `high` should match: LOC > 1500, OR a function ≥ 150 LOC, OR ≥ 5 ungated console.logs, OR cross-layer leak

## Q3 — Top-5 high-priority candidates honesty
For each top-5 candidate the worker named:
- Read the file briefly. Confirm the worker's "suggested refactor shape" is realistic.
- Cross-check that none of these candidates touch active-work files (locked/recent).

## Q4 — Three-Layer-Law canary
If worker reported any layer violations, validate each by reading the cited file:line. False positives are common.

## Q5 — No code modified
`git -C <worktree> diff HEAD --stat` empty.

## Q6 — Cross-area boundary leak count
Worker should report a count vs Finding #11's baseline of 5. If higher, name new leaks; if lower, the count probably drifted.

## Output

```markdown
### Followup 08-A — frontend comprehensive audit  (eval date)

**Worker outcome confirmation**: <INVESTIGATED — confirmed/disputed>
**Worktree audit context**: <path>

**Coverage of NOT SEARCHED set**: claimed <N>, observed <N> tagged
**Tag-honesty (3 sampled)**: <pass/fail per sample with reasoning>
**Top-5 candidate honesty**: <K of 5 honest>; out-of-scope or unrealistic: <list>
**Three-Layer-Law flags**: <validated | none claimed>
**No code modified**: yes/no
**Boundary leak count vs Finding #11**: <count> (was 5)

**Prompt evaluation**
- Was the heuristic-signal list comprehensive enough or did the worker have to invent additional signals?
- Did 81 files in one prompt fit comfortably in worker context, or was it strained?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Modify code, write tests, append to REFACTOR_AUDIT.md.
