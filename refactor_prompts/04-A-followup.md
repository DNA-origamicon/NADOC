# Followup 04-A — Evaluate `client.js` recent-files leaf extraction

You are a **followup session**. Audit, do not implement.

## Pre-read

1. `refactor_prompts/04-A-client-js-recent-files-extract.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #12: `git worktree list` first)
3. The worker's final-message Findings entry (returned via agent result text; manager will pass to you)

## Step 0 — locate the worker's worktree

```bash
git worktree list
# Expect: a `04A-*` worktree path. Audit there, NOT in the main checkout.
```

## Your job

### Q1 — Metrics

- Re-run `just lint` and `just test` in the worktree. Match worker's claimed pre/post.
- `wc -l <worktree>/frontend/src/api/client.js` and `<worktree>/frontend/src/api/recent_files.js`.
- Caller-diff: re-run the worker's caller grep, sort, diff. Must be empty.

### Q2 — Verbatim-move check

Pick all 3 functions (`getRecentFiles`, `addRecentFile`, `clearRecentFiles`); diff each against HEAD's `client.js` original line range. Byte-identical or fail.

### Q3 — Leaf-pattern correctness

The whole point of this prompt: confirm `recent_files.js` has **zero** imports from `./client.js`. If `import { _request, ... } from './client.js'` appears anywhere in the new file, the worker picked the wrong candidate or the prompt's "no `_request` dependency" claim was wrong. Verify:

```bash
grep -nE "from\s+['\"]\\./client" <worktree>/frontend/src/api/recent_files.js
```

Expect zero results. Any match = leaf premise broken.

### Q4 — Scope

`git diff HEAD --stat` in the worktree; only `client.js` + new `recent_files.js`. Anything else = scope creep.

### Q5 — Contrast with Finding #12

03-B had 3 visibility changes (`_request` etc. private→public). This prompt promised zero. Confirm `Visibility changes: none` is honest in the worker's Findings entry. Run:

```bash
git -C <worktree> diff HEAD -- frontend/src/api/client.js | grep -E "^\+(export )?(async )?function _" 
```

Expect zero new exported underscore-prefixed identifiers. If any: visibility widening happened and the worker's Findings is wrong.

## Output (return as agent result text; manager will append to REFACTOR_AUDIT.md)

```markdown
### Followup 04-A — client.js recent-files leaf extraction  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL>

**Diff vs claimed-touched files**: <2 claimed | M observed | extras>

**Worktree audit context**: <path of worktree where audit ran>

**Metric audit**
- lint Δ: claimed <X>, observed <Y>
- test: claimed <X>/<Y>/<Z>, observed <X'>/<Y'>/<Z'>; baseline match
- client.js LOC: pre <P>, post <Q>; recent_files.js LOC <R>
- caller-diff: PASS|FAIL

**Verbatim-move audit**: 3/3 byte-identical | <list any deviations>

**Leaf-pattern correctness**: PASS — recent_files.js has 0 imports from ./client.js | FAIL — <details>

**Visibility changes audit**: 0 new exported underscore-prefixed identifiers | <list>

**Prompt evaluation**
- Did the leaf-pattern premise hold?
- Was the "≤ 30 LOC reduction" target meaningful?
- Did anything force a visibility change?

**Proposed framework edits**
1. ...
```

Time budget: 100 lines max (this is a small refactor; audit should be short).

## Do NOT

- Implement code.
- Pick new candidates.
- Append to REFACTOR_AUDIT.md (manager does it).
