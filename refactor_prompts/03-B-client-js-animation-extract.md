# Refactor 03-B — Extract animation-endpoint group from `client.js` into a sub-module

You are a **worker session**. Execute exactly this one refactor.

## Pre-read (mandatory, in this order)

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #1, #2, #8, #9)
3. `REFACTOR_AUDIT.md` § "Categories" — this is **(c) god-file decomposition**
4. `REFACTOR_AUDIT.md` § "Findings" #1–#7 — context
5. The followup evaluations for 02-A and 02-B
6. `frontend/src/api/client.js:1758-2065` — the animation/configuration endpoint groups (read the full range, not just function signatures)
7. `frontend/src/ui/animation_panel.js` lines that import from `api/client.js` — confirm callers use `import * as api from '...client.js'` or `import { ... } from '...client.js'`. The extraction must be transparent to them.

## Goal

`frontend/src/api/client.js` is 2080 LOC. The animation + assembly-animation + assembly-configuration endpoint groups occupy a coherent ~330 LOC slab (L1739-L2065). Extract them into a new file `frontend/src/api/animation_endpoints.js`. Have `client.js` re-export them so every existing caller keeps working with **zero source changes outside the two API files**.

## In scope

- Create `frontend/src/api/animation_endpoints.js`.
- Move these functions from `client.js` to the new file (verbatim — copy, then delete from `client.js`):
  - The `// ── Animations ──` block: `createAnimation`, `updateAnimation`, `deleteAnimation`, `createKeyframe`, `updateKeyframe`, `deleteKeyframe`, `reorderKeyframes` (around L1758-L1797)
  - The `// ── Assembly animations ──` block: `createAssemblyAnimation`, `updateAssemblyAnimation`, `deleteAssemblyAnimation`, `createAssemblyKeyframe`, `updateAssemblyKeyframe`, `deleteAssemblyKeyframe`, `reorderAssemblyKeyframes` (around L2029-L2065)
  - The 4 assembly-configuration helpers at L1739-L1754: `createAssemblyConfiguration`, `restoreAssemblyConfiguration`, `updateAssemblyConfiguration`, `deleteAssemblyConfiguration` (read the surrounding code to confirm names; if the actual names differ, use the actual names and document the discrepancy)
- The new file must `import { _request, _syncFromDesignResponse, _syncFromAssemblyResponse } from './client.js'` — it depends on the private internals already exported (or, if those internals are not currently exported, export the *narrowest* surface needed; document each new export under "API surface added").
- `client.js` must `export * from './animation_endpoints.js'` (or named re-exports) so existing imports `import { createAnimation } from '../api/client.js'` continue working.

## Out of scope (do not touch)

- Any function outside the listed ranges.
- The `_request` / `_syncFromDesignResponse` / `_syncFromAssemblyResponse` internals — do not rename, do not change signatures.
- ANY caller of these endpoints. Specifically `frontend/src/ui/animation_panel.js` (≥13 callsites) — if you find yourself editing it, you've broken transparency; revert.
- Backend (`backend/`).
- Tests (`tests/`, `frontend/**/*.test.js`).
- Other endpoint groups in `client.js` (overhang, scaffold, deformation, cluster, …) — those are separate prompts, queue them in your Open questions.

## Verification plan

### Pre-state capture
```bash
git status > /tmp/03B_dirty_pre.txt   # precondition #9: clean tree (declare any inherited dirt)
just lint > /tmp/03B_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/03B_lint_pre.txt
just test > /tmp/03B_test_pre1.txt 2>&1
just test > /tmp/03B_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/03B_test_pre1.txt | sort > /tmp/03B_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/03B_test_pre2.txt | sort > /tmp/03B_baseline2.txt
comm -12 /tmp/03B_baseline1.txt /tmp/03B_baseline2.txt > /tmp/03B_stable_failures.txt

wc -l frontend/src/api/client.js > /tmp/03B_client_loc_pre.txt   # currently 2080
rg -nE "^export (async )?function" frontend/src/api/client.js | wc -l > /tmp/03B_client_exports_pre.txt
rg -nE "createAnimation|updateAnimation|deleteAnimation|createKeyframe|updateKeyframe|deleteKeyframe|reorderKeyframes|createAssemblyAnimation|updateAssemblyAnimation|deleteAssemblyAnimation|createAssemblyKeyframe|updateAssemblyKeyframe|deleteAssemblyKeyframe|reorderAssemblyKeyframes|createAssemblyConfiguration|restoreAssemblyConfiguration|updateAssemblyConfiguration|deleteAssemblyConfiguration" frontend/src --glob '!**/client.js' --glob '!**/animation_endpoints.js' > /tmp/03B_callers_pre.txt
```

### Implementation rhythm
1. **Survey before moving.** Read L1739-L2065 of `client.js` end-to-end. Note any function that depends on a module-level `let`/`const` defined elsewhere in `client.js` (besides `_request` / sync helpers). If any such dependency exists, document it under Open questions before proceeding — it may force a different extraction shape.
2. **Create `animation_endpoints.js`.** Write the file with imports at the top, then the moved functions verbatim. Do not edit any function body.
3. **Re-export from `client.js`.** Replace the moved blocks with a single `export * from './animation_endpoints.js'` line (or named re-exports if `export *` collides with anything — document the collision).
4. **Run `just test` after step 3.** Any non-baseline failure → revert.
5. **Confirm callers untouched.** `git diff frontend/src --stat` should show only `client.js` (deletions) and `animation_endpoints.js` (additions). Any other file in the diff is a bug — revert.

### Post-state capture
```bash
just lint > /tmp/03B_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/03B_lint_post.txt
just test > /tmp/03B_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/03B_test_post.txt | sort > /tmp/03B_post_failures.txt
diff /tmp/03B_stable_failures.txt /tmp/03B_post_failures.txt   # expect ⊆ baseline ∪ flake

wc -l frontend/src/api/client.js > /tmp/03B_client_loc_post.txt
wc -l frontend/src/api/animation_endpoints.js > /tmp/03B_endpoints_loc.txt
rg -nE "^export (async )?function" frontend/src/api/client.js > /tmp/03B_client_exports_post.txt
# Caller list must be IDENTICAL before and after — transparency check:
rg -nE "createAnimation|updateAnimation|deleteAnimation|createKeyframe|updateKeyframe|deleteKeyframe|reorderKeyframes|createAssemblyAnimation|updateAssemblyAnimation|deleteAssemblyAnimation|createAssemblyKeyframe|updateAssemblyKeyframe|deleteAssemblyKeyframe|reorderAssemblyKeyframes|createAssemblyConfiguration|restoreAssemblyConfiguration|updateAssemblyConfiguration|deleteAssemblyConfiguration" frontend/src --glob '!**/client.js' --glob '!**/animation_endpoints.js' > /tmp/03B_callers_post.txt
diff /tmp/03B_callers_pre.txt /tmp/03B_callers_post.txt   # MUST be empty
```

### Frontend smoke (precondition #8)
- Start `just frontend` if it isn't running. Load the app once. Open the Animation panel; create one animation; add one keyframe; delete the keyframe; delete the animation. If anything throws in the JS console, the extraction broke a caller — revert.
- If you cannot run the app, your final message MUST start with `NOT VERIFIED IN APP` and explain why.

## Stop conditions

- **Dirty tree at pre-state**: declare every `M`/`??` file in `### Pre-existing dirty state declaration`. If any of `frontend/src/api/client.js`, `frontend/src/api/animation_endpoints.js`, or `frontend/src/ui/animation_panel.js` is already modified, **stop and report**; you cannot safely separate your diff from the inherited dirt without a worktree (precondition #7).
- Lint-error-count delta > 0 → revert and stop.
- Any test post-failure not in `stable_baseline ∪ flakes` → revert and stop.
- Caller diff non-empty after the move → you broke transparency; revert and stop.
- Any of the listed function names doesn't exist in `client.js` (e.g. names differ from what the prompt lists): document and adjust; do not invent functions.
- Any function in the target range has internal references to `client.js` private symbols beyond `_request` / `_syncFrom*Response` / `_syncFromAssemblyResponse`: stop, document the dependency, ask the manager whether to widen the new file's import surface.

## Lint-delta rule (precondition #2)

Pre lint will likely show ~449 errors. Success = post-error-count ≤ pre-error-count AND no new error categories. The most likely *new* lint warning would be unused imports in either file after the move; clean those before declaring done.

## Output format for final message

```markdown
## 03-B client.js animation-endpoint extract — <REFACTORED|UNSUCCESSFUL>

[NOT VERIFIED IN APP — <reason>]   ← only if applicable

### Pre-existing dirty state declaration
<list every file from `git status` at session start that this refactor did NOT touch>

### Metrics
- pre lint: <PASS/FAIL, N errors>; post lint: <PASS/FAIL, M errors; Δ = M-N>
- pre test: <X> pass / <Y> fail / <Z> error  |  post: <X'> / <Y'> / <Z'>
- stable baseline failure set: <count> ; flake set: <count>
- client.js LOC: <2080> → <K>; expected delta ≈ −330
- new file LOC: animation_endpoints.js = <K'>
- exported function count in client.js: <pre> → <post>; functions moved: <N>
- caller diff: <empty | non-empty contents>

### Functions moved
| Function | Original line in client.js | New line in animation_endpoints.js |
|---|---|---|
| createAnimation | 1764 | … |
| ... |

### What was deliberately NOT changed
- `frontend/src/ui/animation_panel.js` (≥13 callsites — verified untouched)
- Other endpoint groups in `client.js` (deformation, overhang, scaffold, …)
- Function bodies (verbatim move only)
- Private `_request` / sync helper signatures

### API surface added
<list new public symbols in animation_endpoints.js — should equal the N functions moved + any private internals re-exported from client.js to make the move work; or `none` if internals were not re-exported>

### Tracker updates
- `frontend/src/api/client.js` row → `PARTIAL` with notes (still ~1750 LOC after extraction)
- new inventory row added: `frontend/src/api/animation_endpoints.js`
- Findings entry #<N> appended

### Open questions / surprises
<anything the prompt didn't anticipate; queue future endpoint-group extractions here>
```

## Success criteria

- [ ] `### Pre-existing dirty state declaration` present
- [ ] `frontend/src/api/animation_endpoints.js` exists, contains moved functions verbatim
- [ ] `frontend/src/api/client.js` LOC reduced by ≥ 200 (target ≈ 330)
- [ ] `git diff frontend/src --stat` shows only the two API files
- [ ] Caller-list diff is empty (transparency confirmed)
- [ ] Lint delta ≤ 0
- [ ] Test post ⊆ stable_baseline ∪ flakes
- [ ] Frontend smoke run, OR `NOT VERIFIED IN APP` caveat
- [ ] Findings entry uses post-Pass-2 template (Out-of-scope diff + API surface added fields populated)

## Do NOT

- Edit any caller. Even one. The whole point of this refactor is transparency.
- Rename any moved function.
- Combine functions that are similar (e.g. don't merge `createAnimation` + `createAssemblyAnimation` into a parameterized helper; that's a separate semantic refactor).
- Add new endpoint helpers that the original code didn't have.
- Move other endpoint groups "while you're at it" — they're queued.
- Commit or push.
