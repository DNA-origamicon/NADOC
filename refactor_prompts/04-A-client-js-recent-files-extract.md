# Refactor 04-A — Extract `Recent files` localStorage helpers from `client.js`

You are a **worker session** running in a git worktree. Execute exactly this one refactor; do not pick further candidates.

## Pre-read (in order)

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (especially #1, #2, #9, #13, #14)
3. `REFACTOR_AUDIT.md` § "Subagent automation" — your dispatch context
4. `REFACTOR_AUDIT.md` Findings #12 — the 03-B animation-endpoint extraction is your reference implementation
5. `frontend/src/api/client.js:87-130` — read the full block
6. This prompt to the end

## Goal

`frontend/src/api/client.js` has a `// ── Recent files ───` block at L87-L130 containing 3 localStorage helpers (`getRecentFiles`, `addRecentFile`, `clearRecentFiles`). Unlike the animation endpoints in 03-B, these helpers depend on **no** `_request` / sync internals — they're pure localStorage. Extract them into a new file `frontend/src/api/recent_files.js` and re-export from `client.js`.

This is the **leaf extraction pattern**: a target so independent of `client.js`'s internals that no visibility widening is needed. The whole point is to prove the pattern works without precondition #14's worker-MUST-export-private-helpers complication.

## In scope

- Create `frontend/src/api/recent_files.js`.
- Move these functions verbatim:
  - `getRecentFiles()` (HEAD L95-L107)
  - `addRecentFile(name, content, type = 'nadoc')` (HEAD L108-L117)
  - `clearRecentFiles()` (HEAD L118-L120)
- The new file must NOT import anything from `./client.js` (intentional — leaf module).
- `client.js` must `export * from './recent_files.js'` so existing callers continue working.

## Out of scope

- Any other section of `client.js`.
- Any other file in `frontend/src/`.
- Backend.
- Tests.
- Renaming or restructuring the moved functions.
- The `// ── Recent files ───` block's section header comment can move with the functions OR stay in client.js as a "// (moved to recent_files.js)" pointer — worker chooses.

## Verification plan

### Pre-state capture
```bash
git status > /tmp/04A_dirty_pre.txt   # precondition #9
just lint > /tmp/04A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/04A_lint_pre.txt
just test > /tmp/04A_test_pre1.txt 2>&1
just test > /tmp/04A_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/04A_test_pre1.txt | sort > /tmp/04A_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/04A_test_pre2.txt | sort > /tmp/04A_baseline2.txt
comm -12 /tmp/04A_baseline1.txt /tmp/04A_baseline2.txt > /tmp/04A_stable_failures.txt

git show HEAD:frontend/src/api/client.js | wc -l > /tmp/04A_client_loc_pre.txt   # HEAD baseline per #13
rg -nE "getRecentFiles|addRecentFile|clearRecentFiles" frontend/src --glob '!**/client.js' --glob '!**/recent_files.js' | sort > /tmp/04A_callers_pre.txt
```

### Implementation
1. Create `frontend/src/api/recent_files.js`. No imports.
2. Move the 3 functions verbatim. Preserve existing comments.
3. In `client.js`, replace the moved block with `export * from './recent_files.js'` (or named re-exports if `export *` would collide).
4. Run `just test`. If any non-baseline failure → revert this hunk and stop.

### Post-state capture
```bash
just lint > /tmp/04A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/04A_lint_post.txt
just test > /tmp/04A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/04A_test_post.txt | sort > /tmp/04A_post_failures.txt
diff /tmp/04A_stable_failures.txt /tmp/04A_post_failures.txt   # ⊆ baseline ∪ flake

wc -l frontend/src/api/client.js > /tmp/04A_client_loc_post.txt
wc -l frontend/src/api/recent_files.js > /tmp/04A_recent_loc.txt

rg -nE "getRecentFiles|addRecentFile|clearRecentFiles" frontend/src --glob '!**/client.js' --glob '!**/recent_files.js' | sort > /tmp/04A_callers_post.txt
diff /tmp/04A_callers_pre.txt /tmp/04A_callers_post.txt   # MUST be empty
```

## Stop conditions

- If `git status` shows uncommitted edits at session start in `frontend/src/api/client.js` or `recent_files.js`: stop. (Worktree should start clean; report if it doesn't.)
- Test post-failure not in `stable_baseline ∪ flakes`: revert and stop.
- Caller diff non-empty after move: revert and stop.
- `recent_files.js` ends up needing to import from `./client.js`: stop and report — that means I picked the wrong candidate; the leaf-extraction premise is wrong.

## Output (the worker's final message)

Manager will copy this directly to master's `REFACTOR_AUDIT.md`. Do NOT modify `REFACTOR_AUDIT.md` from inside the worktree (per precondition #14).

```markdown
## 04-A client.js recent-files extract — <REFACTORED|UNSUCCESSFUL>

[NOT VERIFIED IN APP — <reason>]   ← if applicable; pair with USER TODO block below

### Pre-existing dirty state declaration
<git status output at session start; expect "nothing to commit" since worktree is fresh>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 13. `client.js` recent-files leaf extraction — `low` ✓ REFACTORED
- **Category**: (c) god-file decomposition (leaf-pattern proof)
- **Move type**: verbatim
- **Where**: `frontend/src/api/client.js:87-130` (deleted block + re-export shim); `frontend/src/api/recent_files.js` (new)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 2; other-files-in-worker-session: none
- **Transparency check**: <PASS|FAIL — sorted caller diff>
- **API surface added**: 3 re-exports (already exported from client.js; net surface unchanged)
- **Visibility changes**: **none** (leaf extraction; no private internals exposed) — contrast with Finding #12 which had 3
- **Callsites touched**: 0
- **Pre-metric → Post-metric**: client.js LOC <pre> → <post>; recent_files.js LOC 0 → <K>; tests baseline-equivalent
- **Raw evidence**: `/tmp/04A_*.txt`
- **Linked Findings**: #12 (animation-endpoint extract; same shape but with 3 visibility changes — this one has zero, proving the leaf pattern)
- **Queued follow-ups**: none

### USER TODO (if NOT VERIFIED IN APP)
1. <Concrete steps the user runs to validate>
```

## Success criteria

- [ ] `frontend/src/api/recent_files.js` exists, contains 3 functions verbatim, NO imports from `./client.js`
- [ ] `client.js` shrunk by ≥ 30 LOC (rough; the moved block is 43 LOC, the shim adds 1)
- [ ] `git diff frontend/src --stat` shows only the two API files
- [ ] Caller-diff empty
- [ ] `just lint` Δ ≤ 0
- [ ] `just test` post ⊆ stable_baseline ∪ flakes
- [ ] Findings entry written exactly as above; manager will paste into master REFACTOR_AUDIT.md

## Do NOT

- Edit any caller. Test files / scenes / panels that read `getRecentFiles` etc. via `import * as api` must keep working unchanged.
- Add new helpers.
- Touch any other section of `client.js`.
- Commit. Manager handles git operations.
- Append to `REFACTOR_AUDIT.md` from the worktree (precondition #14).
