# Refactor 05-A — Extract overhang endpoints from `client.js`

You are a **worker session** in a git worktree. Execute exactly this one refactor.

## Pre-read (in order)

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" (#1, #2, #8, #9, #13, #14)
3. `REFACTOR_AUDIT.md` § "Findings" #12 (animation-endpoint extract — your reference for the pattern, including the visibility-changes caveat) and #13 (recent-files leaf extract — the simpler shape)
4. `frontend/src/api/client.js` lines 1195-1285 (read the full overhang block)
5. This prompt

## Goal

Extract the 10 overhang-related endpoint helpers from `client.js` into `frontend/src/api/overhang_endpoints.js`. Re-export from `client.js` so the 26 existing callers (`import * as api from '../api/client.js'` plus named imports) continue working unchanged.

## In scope

Move these functions verbatim from `client.js` to `frontend/src/api/overhang_endpoints.js`:

- `extrudeOverhang` (L1198)
- `patchOverhang` (L1211)
- `patchOverhangRotationsBatch` (L1220)
- `generateOverhangRandomSequence` (L1226)
- `clearOverhangs` (L1231)
- `createOverhangConnection` (L1241)
- `patchOverhangConnection` (L1248)
- `deleteOverhangConnection` (L1254)
- `relaxLinker` (L1259) — overhang-adjacent (linkers bridge overhangs); include in the extraction
- `generateAllOverhangSequences` (L1275)

The new file must:
- `import { _request, _syncFromDesignResponse } from './client.js'` if needed (check each function's body — most use `_request`)
- Re-export all 10 functions
- Have `client.js` add `export * from './overhang_endpoints.js'` at the bottom (with the existing re-export line for animation_endpoints + recent_files)

## Out of scope (explicitly skip)

- `clearAllLoopSkips` at L1235 — it's wedged in the middle of the overhang block but is a loop-skip endpoint, not overhang. **Leave it in client.js.** This means the moved functions will not be a contiguous block deletion in `client.js`; expect 2 separate hunks (one for the overhang block before `clearAllLoopSkips`, one for after).
- Any other section of `client.js`.
- Any caller. Specifically `frontend/src/scene/overhang_*.js`, `frontend/src/ui/overhangs_manager_popup.js`, etc. — they all reach overhang endpoints via the namespaced `api` import; transparency must be preserved.
- `package.json` / backend / tests.

## Verification plan

### Pre-state capture
```bash
git status > /tmp/05A_dirty_pre.txt
just lint > /tmp/05A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/05A_lint_pre.txt
just test > /tmp/05A_test_pre1.txt 2>&1
just test > /tmp/05A_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05A_test_pre1.txt | sort > /tmp/05A_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/05A_test_pre2.txt | sort > /tmp/05A_baseline2.txt
comm -12 /tmp/05A_baseline1.txt /tmp/05A_baseline2.txt > /tmp/05A_stable_failures.txt

git show HEAD:frontend/src/api/client.js | wc -l > /tmp/05A_client_loc_pre.txt
rg -n "api\.(extrudeOverhang|patchOverhang|patchOverhangRotationsBatch|generateOverhangRandomSequence|clearOverhangs|createOverhangConnection|patchOverhangConnection|deleteOverhangConnection|generateAllOverhangSequences|relaxLinker)" frontend/src --glob '!**/client.js' --glob '!**/overhang_endpoints.js' | sort > /tmp/05A_callers_pre.txt
```

### Implementation
1. Survey: read L1195-L1285 of `client.js`. Note each moved function's `_request` / sync-helper dependencies. If any depends on a private symbol *other than* `_request` / `_syncFromDesignResponse`, **stop and report** — the prompt didn't anticipate it.
2. Create `frontend/src/api/overhang_endpoints.js`. Imports at top, then 10 functions verbatim.
3. In `client.js`: delete the 10 moved functions (2 hunks separated by `clearAllLoopSkips`). Add `export * from './overhang_endpoints.js'` at the bottom alongside existing re-exports.
4. Run `just test`. Any non-baseline failure → revert and stop.

### Post-state capture
```bash
just lint > /tmp/05A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/05A_lint_post.txt
just test > /tmp/05A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05A_test_post.txt | sort > /tmp/05A_post_failures.txt
diff /tmp/05A_stable_failures.txt /tmp/05A_post_failures.txt   # ⊆ baseline ∪ flake

wc -l frontend/src/api/client.js > /tmp/05A_client_loc_post.txt
wc -l frontend/src/api/overhang_endpoints.js > /tmp/05A_overhang_loc.txt

rg -n "api\.(extrudeOverhang|patchOverhang|patchOverhangRotationsBatch|generateOverhangRandomSequence|clearOverhangs|createOverhangConnection|patchOverhangConnection|deleteOverhangConnection|generateAllOverhangSequences|relaxLinker)" frontend/src --glob '!**/client.js' --glob '!**/overhang_endpoints.js' | sort > /tmp/05A_callers_post.txt
diff /tmp/05A_callers_pre.txt /tmp/05A_callers_post.txt   # MUST be empty
```

## Stop conditions

- Worktree dirty at session start: stop, report.
- Caller-diff non-empty after move: revert, stop.
- New private-helper dependency surfaced: stop, document, do NOT widen visibility beyond what 03-B already widened (`_request`, `_syncFromDesignResponse` already public).
- Test post-failure not in stable_baseline ∪ flakes: revert, stop.
- `clearAllLoopSkips` accidentally moved into `overhang_endpoints.js`: revert that change.

## Output format (worker's final message — manager will paste into master tracker)

```markdown
## 05-A client.js overhang-endpoints extract — <REFACTORED|UNSUCCESSFUL>

[NOT VERIFIED IN APP — pure extraction; pair with USER TODO below]

### Pre-existing dirty state declaration
<git status output at session start; expect "nothing to commit" since worktree is fresh>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 15. `client.js` overhang-endpoints extraction — `low` ✓ REFACTORED
- **Category**: (c) god-file decomposition
- **Move type**: verbatim (10 functions)
- **Where**: `frontend/src/api/client.js:1195-1285` (2 hunks around `clearAllLoopSkips`); `frontend/src/api/overhang_endpoints.js` (new)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 2; other-files: none
- **Transparency check**: <PASS — sorted caller-set diff empty | FAIL — list>
- **API surface added**: 10 re-exports (no net surface change for them)
- **Visibility changes**: **none** — `_request` and `_syncFromDesignResponse` were already made public by Finding #12; this prompt rides that change rather than widening further
- **Callsites touched**: 0
- **Symptom**: 10 overhang-related endpoints sandwiched between unrelated nicks/loop-skips/strands in `client.js` despite a misleading `// ── Nicks ──` section banner.
- **Why it matters**: continues the (c) god-file decomposition pattern; surfaces the section-banner-vs-actual-cohesion issue Pass 4 documented.
- **Change**: created `overhang_endpoints.js`, moved 10 functions verbatim, added `export *` re-export.
- **Effort**: S
- **Three-Layer**: not applicable (frontend HTTP wrapper layer)
- **Pre-metric → Post-metric**: client.js LOC <pre>→<post> (Δ≈−85 expected); overhang_endpoints.js 0 → <K>; lint Δ ≤ 0; tests baseline-equivalent
- **Raw evidence**: `/tmp/05A_*.txt`
- **Linked Findings**: #12 (set the visibility precedent), #13 (leaf-pattern variant)
- **Queued follow-ups**: continue with `cluster_rigid_transforms`, `cluster_joints`, `camera_poses`, `assembly` extractions in future passes.

### USER TODO (NOT VERIFIED IN APP)
1. `just frontend` and load any saved `.nadoc`.
2. Open the **Overhangs** panel; create a 5'/3' overhang on any helix end.
3. Edit the overhang's sequence, rotation, label.
4. Connect two overhangs to form an overhang connection.
5. Click **Generate sequence** and **Relax linker**.
6. Confirm no errors in DevTools console for any of the above. If clean, mark Finding #15 as USER VERIFIED.
```

## Success criteria

- [ ] `frontend/src/api/overhang_endpoints.js` exists, contains 10 functions verbatim
- [ ] `client.js` shrunk by ≥ 75 LOC (target ≈ 85)
- [ ] `git diff frontend/src --stat` shows only the two API files
- [ ] Caller-diff empty
- [ ] `clearAllLoopSkips` still in client.js (NOT moved)
- [ ] Lint Δ ≤ 0
- [ ] Test post ⊆ stable_baseline ∪ flakes
- [ ] Findings entry written; manager will paste

## Do NOT

- Edit any caller.
- Move `clearAllLoopSkips` (it's loop-skip, not overhang).
- Combine functions or rename.
- Touch any other endpoint group.
- Commit. Manager handles git operations.
- Append to `REFACTOR_AUDIT.md` from the worktree.
