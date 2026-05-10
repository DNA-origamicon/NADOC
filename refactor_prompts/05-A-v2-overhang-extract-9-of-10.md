# Refactor 05-A-v2 — Overhang extract, 9-of-10 (defer `relaxLinker`)

**Continuation of 05-A.** Worker 05-A hit a stop condition: `relaxLinker` depends on private helpers `_syncClusterOnlyDiff` (client.js:539) and `_syncPositionsOnlyDiff` (client.js:562) — both used by 6 *other* call paths in `client.js` (joints, deformation seek, scaffold). Widening them is a separate decision the user has not opted into.

**Path chosen: (A) — extract the 9 clean functions, leave `relaxLinker` in client.js with a TODO.**

## Pre-read

1. `refactor_prompts/05-A-client-js-overhang-extract.md` — the original prompt (your baseline)
2. The original 05-A worker's UNSUCCESSFUL report (in `REFACTOR_AUDIT.md` Finding #15 stub or in chat history)
3. `frontend/src/api/client.js:1230-1311` — read the full overhang block

## Goal

Same as 05-A but extract **9 functions** instead of 10:

- `extrudeOverhang`
- `patchOverhang`
- `patchOverhangRotationsBatch`
- `generateOverhangRandomSequence`
- `clearOverhangs`
- `createOverhangConnection`
- `patchOverhangConnection`
- `deleteOverhangConnection`
- `generateAllOverhangSequences`

**Leave `relaxLinker` (around L1291-L1305) in `client.js`.** Add a one-line comment immediately above its definition:

```js
// TODO(05-A-v2): extract to overhang_endpoints.js once _syncClusterOnlyDiff / _syncPositionsOnlyDiff are factored
```

Do NOT widen `_syncClusterOnlyDiff` / `_syncPositionsOnlyDiff` — they stay private.

## In scope

Same as 05-A except:
- 9 functions, not 10. `relaxLinker` stays.
- Add the TODO comment above `relaxLinker`.
- Expected `client.js` LOC reduction: ≈ −74 (vs original 05-A target of ≈ −85).
- `clearAllLoopSkips` (L1268) still stays in client.js per original 05-A.

## Out of scope

- `relaxLinker` body or signature (do NOT touch).
- The 2 private helpers (`_syncClusterOnlyDiff`, `_syncPositionsOnlyDiff`) — do NOT prefix with `export`.
- Anything in 05-A's "out of scope" list.

## Verification plan

Same as 05-A. Re-use `/tmp/05A_*` paths but with `_v2` suffix to distinguish:

```bash
git status > /tmp/05Av2_dirty_pre.txt
just lint > /tmp/05Av2_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/05Av2_lint_pre.txt
just test > /tmp/05Av2_test_pre1.txt 2>&1
just test > /tmp/05Av2_test_pre2.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05Av2_test_pre1.txt | sort > /tmp/05Av2_baseline1.txt
grep -E '^FAILED|^ERROR' /tmp/05Av2_test_pre2.txt | sort > /tmp/05Av2_baseline2.txt
comm -12 /tmp/05Av2_baseline1.txt /tmp/05Av2_baseline2.txt > /tmp/05Av2_stable_failures.txt

git show HEAD:frontend/src/api/client.js | wc -l > /tmp/05Av2_client_loc_pre.txt
rg -n "api\.(extrudeOverhang|patchOverhang|patchOverhangRotationsBatch|generateOverhangRandomSequence|clearOverhangs|createOverhangConnection|patchOverhangConnection|deleteOverhangConnection|generateAllOverhangSequences|relaxLinker)" frontend/src --glob '!**/client.js' --glob '!**/overhang_endpoints.js' | sort > /tmp/05Av2_callers_pre.txt
```

After move:
```bash
just lint > /tmp/05Av2_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/05Av2_lint_post.txt
just test > /tmp/05Av2_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/05Av2_test_post.txt | sort > /tmp/05Av2_post_failures.txt
diff /tmp/05Av2_stable_failures.txt /tmp/05Av2_post_failures.txt   # ⊆ baseline ∪ flake

wc -l frontend/src/api/client.js > /tmp/05Av2_client_loc_post.txt
wc -l frontend/src/api/overhang_endpoints.js > /tmp/05Av2_overhang_loc.txt
rg -n "api\.(extrudeOverhang|patchOverhang|patchOverhangRotationsBatch|generateOverhangRandomSequence|clearOverhangs|createOverhangConnection|patchOverhangConnection|deleteOverhangConnection|generateAllOverhangSequences|relaxLinker)" frontend/src --glob '!**/client.js' --glob '!**/overhang_endpoints.js' | sort > /tmp/05Av2_callers_post.txt
diff /tmp/05Av2_callers_pre.txt /tmp/05Av2_callers_post.txt   # MUST be empty
```

## Stop conditions

- `relaxLinker` accidentally moved to `overhang_endpoints.js`: revert.
- Any private helper besides `_request` / `_syncFromDesignResponse` gets exported: revert and stop.
- Caller-diff non-empty: revert.
- Test post-failure not in stable_baseline ∪ flakes: revert.

## Output (worker's final message)

```markdown
## 05-A-v2 client.js overhang-endpoints extract (9-of-10) — <REFACTORED|UNSUCCESSFUL>

[NOT VERIFIED IN APP — pair with USER TODO]

### Pre-existing dirty state declaration
<expect "nothing to commit, working tree clean">

### Findings entry (manager appends; replaces 05-A's UNSUCCESSFUL stub)

### 15. `client.js` overhang-endpoints extraction (9-of-10) — `low` ✓ REFACTORED
- **Category**: (c) god-file decomposition
- **Move type**: verbatim (9 functions); `relaxLinker` deferred with TODO
- **Where**: `frontend/src/api/client.js:1230-1311` (3 hunks: pre-`clearAllLoopSkips`, post-`clearAllLoopSkips`, plus the TODO insertion above `relaxLinker`); `frontend/src/api/overhang_endpoints.js` (new)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 2; other-files: none
- **Transparency check**: <PASS — sorted caller-set diff empty; 26 callers unchanged>
- **API surface added**: 9 re-exports
- **Visibility changes**: **none** — `relaxLinker`'s 2-helper dependency was the reason 05-A stopped; v2 sidesteps by deferring
- **Callsites touched**: 0
- **Symptom**: same as 05-A: 10 overhang functions sandwiched in mis-banner'd block. v2 ships 9 and queues `relaxLinker` for a future prompt that explicitly opts into widening `_syncClusterOnlyDiff` / `_syncPositionsOnlyDiff`.
- **Change**: created `overhang_endpoints.js`, moved 9 functions verbatim, added TODO above `relaxLinker`, added `export *` re-export.
- **Effort**: S
- **Three-Layer**: not applicable
- **Pre-metric → Post-metric**: client.js LOC <pre>→<post> (Δ≈−74); overhang_endpoints.js 0 → <K>; lint Δ ≤ 0; tests baseline-equivalent
- **Raw evidence**: `/tmp/05Av2_*.txt`
- **Linked Findings**: #12 (visibility precedent), #13 (leaf-pattern variant)
- **Queued follow-ups**: re-issue an `05-A-v3` prompt that explicitly authorizes promoting `_syncClusterOnlyDiff` / `_syncPositionsOnlyDiff` to public so `relaxLinker` can be moved alongside future cluster/deformation/seek extractions. The 2 helpers are used by 6 other call paths, so a single decision unblocks multiple future extractions.

### USER TODO (NOT VERIFIED IN APP)
1. `just frontend` and load any saved `.nadoc`.
2. Open the **Overhangs** panel; create a 5'/3' overhang.
3. Edit sequence, rotation, label.
4. Connect two overhangs and click **Generate sequence**.
5. **Skip `relaxLinker`** — it stayed in client.js, no behavior change to test.
6. Confirm no DevTools console errors. If clean, mark Finding #15 as USER VERIFIED.
```

## Success criteria

- [ ] `frontend/src/api/overhang_endpoints.js` exists with 9 functions verbatim
- [ ] `relaxLinker` STILL in `client.js` with the TODO comment immediately above it
- [ ] No new exported underscore-prefixed identifiers in `client.js`
- [ ] `git diff frontend/src --stat` shows only the 2 API files
- [ ] Caller-diff empty (26 callers unchanged)
- [ ] Lint Δ ≤ 0
- [ ] Test post ⊆ stable_baseline ∪ flakes

## Do NOT

- Move `relaxLinker`.
- Export `_syncClusterOnlyDiff` or `_syncPositionsOnlyDiff`.
- Touch any caller, `clearAllLoopSkips`, or other section.
- Commit.
- Append to `REFACTOR_AUDIT.md` from the worktree.
