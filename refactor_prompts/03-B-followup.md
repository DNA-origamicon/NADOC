# Followup 03-B — Evaluate animation-endpoint extraction from `client.js`

You are a **followup session**. Audit, do not implement.

## Pre-read

1. `refactor_prompts/03-B-client-js-animation-extract.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" + the worker's new Findings entry
3. `git diff frontend/src/api/client.js` and `git diff frontend/src/api/animation_endpoints.js` (or new-file content)
4. The followup template requirement: `**Diff vs claimed-touched files**`

## Your job

### Q1 — Did the worker hit the metrics?

- Re-run `just lint`. Compare pre/post error counts to claimed delta.
- Re-run `just test`. Compare pass/fail/error to claimed; failure set ⊆ stable_baseline ∪ flakes?
- Re-measure `wc -l frontend/src/api/client.js` and `wc -l frontend/src/api/animation_endpoints.js`. Confirm `client.js` shrank by ≥ 200 LOC and the new file accounts for it.
- Re-count exports: `rg -nE "^export (async )?function" frontend/src/api/client.js | wc -l`. Compare to pre/post claimed.
- **Transparency check (load-bearing)**: re-run the caller grep:
  ```bash
  rg -nE "createAnimation|updateAnimation|deleteAnimation|createKeyframe|updateKeyframe|deleteKeyframe|reorderKeyframes|createAssemblyAnimation|updateAssemblyAnimation|deleteAssemblyAnimation|createAssemblyKeyframe|updateAssemblyKeyframe|deleteAssemblyKeyframe|reorderAssemblyKeyframes|createAssemblyConfiguration|restoreAssemblyConfiguration|updateAssemblyConfiguration|deleteAssemblyConfiguration" frontend/src --glob '!**/client.js' --glob '!**/animation_endpoints.js'
  ```
  This must be byte-identical to `/tmp/03B_callers_pre.txt`. If any caller picked up a different import (e.g. `from '../api/animation_endpoints.js'`), that's an out-of-scope edit; flag.
- If the worker said `NOT VERIFIED IN APP`, do not penalize, but note whether the app could have been reached.

### Q2 — Verbatim-move check

For 5 randomly-sampled moved functions, diff the original-line range in `client.js` (use `git show HEAD:frontend/src/api/client.js | sed -n 'A,Bp'`) against the new file's body. They must be identical except for surrounding whitespace. Any change to a function body — even a comment edit — is scope creep; flag.

### Q3 — Did the worker stay in scope?

- `git diff frontend/src --stat` must show ONLY `client.js` (deletions) and `animation_endpoints.js` (additions). Any other file in the diff is a violation.
- Specifically: `frontend/src/ui/animation_panel.js` must show no diff. Confirm.
- `package.json` / `frontend/package.json` must be unchanged.
- Check `### Pre-existing dirty state declaration` against `git status` at the followup's start. Identify any file that's in the diff but NOT in the worker's declaration — that's silent absorption.

### Q4 — API surface honesty

The Findings entry's `**API surface added**` field should list:
- Every function newly exported from `animation_endpoints.js` (these were already exported from `client.js`, so net public surface unchanged)
- Any *new* re-export from `client.js` of `_request` / sync helpers that was needed to make the move work (these ARE new public surface)

If the worker said "API surface added: none" but the new file imports `{ _request, _syncFromDesignResponse, _syncFromAssemblyResponse }` from `./client.js`, then `client.js` had to *export* those three (they were previously private). That IS new public surface and the entry should say so. Cross-check.

### Q5 — Prompt evaluation

- **Function-list accuracy**: did the prompt's list of 18 function names match the actual code at L1739-L2065? Did the worker hit a "function not found" stop? If so, did the prompt's "use actual names and document discrepancy" guidance work?
- **Implementation rhythm (5 steps)**: was the survey-before-moving step useful? Did the worker discover a hidden module-level dependency that forced a different shape?
- **Caller-diff stop condition**: did this fire? Was it the most useful stop in the prompt?
- **Frontend smoke (precondition #8)**: did the worker exercise the Animation panel? If yes, did anything break?

### Q6 — Framework improvements

- Should the Findings template add an explicit `**Transparency check**: <pass|fail with details>` field for refactors that promise zero caller change? (god-file extractions, re-exports, renames-with-shim).
- Should "verbatim move" be a first-class refactor sub-type with its own checklist, separate from `Change` field?
- Was the `Out-of-scope diff in same files` field actionable, or did it conflict with `### Pre-existing dirty state declaration` (both report "stuff the worker didn't introduce")? Should they be merged?
- Did the prompt's `Open questions` queue (suggested as a place to log future endpoint-group extractions) actually surface any that the manager should pick up next pass?

## Output format

Append your evaluation to `REFACTOR_AUDIT.md` under `## Followup evaluations`, AND output to chat:

```markdown
### Followup 03-B — client.js animation-endpoint extract  (eval date)

**Worker outcome confirmation**: <REFACTORED|UNSUCCESSFUL — confirmed/disputed>

**Diff vs claimed-touched files**: <2 files claimed | M files observed | extras: ...>

**Metric audit**
- lint: claimed Δ=<X>, observed Δ=<Y>
- test: claimed <X> pass / <Y> fail / <Z> err; observed <X'>/<Y'>/<Z'>; baseline match: <yes/no>
- client.js LOC: pre=2080, post claimed=<K>, observed=<K'>
- animation_endpoints.js LOC: claimed=<K2>, observed=<K2'>
- exports moved: claimed=<N>, observed=<N'>
- caller-diff transparency check: <PASS — empty | FAIL — list>

**Verbatim-move audit**
- 5 sampled functions: <K out of 5 byte-identical>; non-identical findings: <list with line refs>

**Scope audit**
- files touched: <2 | other: list>
- animation_panel.js diff: <empty|non-empty>
- package.json: <unchanged|delta>
- pre-existing dirty state declaration: <complete|incomplete: missing files>

**API surface honesty**
- moved exports: <count match>
- new re-exports from client.js (private→public): <list | none>
- Findings entry's `API surface added` field accurate: <yes/no>

**Prompt evaluation**
- Function-list accuracy: ...
- Implementation rhythm: ...
- Caller-diff stop fired: <yes/no, useful>
- Frontend smoke: ...

**Proposed framework edits**
1. ...
2. ...
```

## Time budget

200 lines max.

## Do NOT

- Implement code.
- Pick new candidates.
- Re-do the move yourself if it failed — file an UNSUCCESSFUL evaluation and let the manager rewrite the prompt.
