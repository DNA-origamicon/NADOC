# Followup 05-A — Evaluate `client.js` overhang-endpoints extraction

You are a **followup session**. Audit, do not implement.

## Step 0 — locate worktree

```bash
git worktree list   # find the agent-* worktree path
```

## Pre-read

1. `refactor_prompts/05-A-client-js-overhang-extract.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#12 worktree-list-first)
3. Worker's final-message Findings text (passed by manager)

## Q1 — Metrics
- Re-run `just lint` and `just test` IN THE WORKTREE. Match worker's claimed pre/post.
- `wc -l <worktree>/frontend/src/api/{client.js,overhang_endpoints.js}`. Confirm Δ ≈ −85 in client.js.
- Caller-diff: re-run sorted caller grep, diff. Must be empty.

## Q2 — Verbatim move
Sample 5 of the 10 moved functions. `git -C <worktree> show HEAD:frontend/src/api/client.js | sed -n A,Bp` against the new file body. Byte-identical or fail.

## Q3 — `clearAllLoopSkips` discipline
Verify `clearAllLoopSkips` is STILL in `<worktree>/frontend/src/api/client.js` and NOT in `overhang_endpoints.js`:
```bash
grep -n "clearAllLoopSkips" <worktree>/frontend/src/api/client.js
grep -n "clearAllLoopSkips" <worktree>/frontend/src/api/overhang_endpoints.js
```
First should return 1 line (the function definition); second should be empty.

## Q4 — Visibility-changes audit
`_request` and `_syncFromDesignResponse` were already public after Finding #12. This refactor must not widen further:
```bash
git -C <worktree> diff HEAD -- frontend/src/api/client.js | grep -E "^\+(export )?(async )?function _"
```
Must be empty. If new private helpers were exported: flag.

## Q5 — Scope
- `git -C <worktree> diff HEAD --stat`: only client.js + overhang_endpoints.js.
- Run `git -C <worktree> status --short` and confirm only `M client.js` + `?? overhang_endpoints.js` (per Followup 04-A's note about untracked files).
- Specifically: `frontend/src/scene/overhang_*.js` and `frontend/src/ui/overhangs_manager_popup.js` must show no diff.

## Output (return as agent result text)

```markdown
### Followup 05-A — client.js overhang extract  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>
**Worktree audit context**: <path>
**Diff vs claimed-touched files**: <2 claimed | M observed>

**Metric audit**
- lint Δ: claimed <X>, observed <Y>
- test: <pre> → <post>; baseline match: <yes/no>
- client.js LOC: pre <P>, post <Q>; overhang_endpoints.js: <K>
- caller-diff: PASS|FAIL

**Verbatim-move audit**: <K/5 byte-identical>

**`clearAllLoopSkips` discipline**: <STAYED in client.js | LEAKED to overhang_endpoints.js>

**Visibility-changes audit**: <0 new exports | list>

**Scope audit**
- files-changed: <2 | extras>
- overhang panel callers untouched: <yes/no>

**Prompt evaluation**
- Did the section-banner-vs-actual-cohesion warning prevent the 1 stray function?
- Did any function expose a hidden private dependency?

**Proposed framework edits**
1. ...
```

100 lines max.

## Do NOT
- Implement code. Pick new candidates. Append to REFACTOR_AUDIT.md.
