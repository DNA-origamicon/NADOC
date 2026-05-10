# Refactor 09-A — Extract lattice-math helpers from `slice_plane.js`

You are a **worker session** in a git worktree. Small leaf-pattern extraction (same shape as Finding #13's `recent_files.js`). No visibility widening expected.

## Pre-read

1. `CLAUDE.md`
2. `REFACTOR_AUDIT.md` § "Universal preconditions" — note **#1 (3× baseline)**, **#15 (CWD-safety)**, **#16 (≤5 LOC hand-apply)**
3. `REFACTOR_AUDIT.md` § "Findings" #13 (`recent_files.js` leaf-pattern reference) and #23 (08-A audit naming `slice_plane.js` as a top-5 god-file candidate; this is a small slice of that work)
4. `frontend/src/scene/slice_plane.js:1-145` — read the entire pre-`initSlicePlane` section
5. This prompt

## Step 0 — CWD safety
```bash
pwd && git rev-parse --show-toplevel
# Both must equal $WORKTREE_PATH; if not STOP and report.
```

## Goal

`frontend/src/scene/slice_plane.js` (1625 LOC) has 5 pure lattice-math helpers between L107-137 (above the 1469-LOC `initSlicePlane` monolith). Extract them to `frontend/src/scene/slice_plane/lattice_math.js`. Re-import them at the top of `slice_plane.js`. **Leaf pattern**: the new file imports nothing from `slice_plane.js`.

## In scope — exact functions

Move these 5 functions verbatim:

- `_mod(n, m)` (L107)
- `isValidHoneycombCell(_row, _col)` (L112)
- `honeycombCellWorldPos(row, col, plane, offset, ox, oy)` (L114)
- `isValidSquareCell(_row, _col)` (L125)
- `squareCellWorldPos(row, col, plane, offset, ox, oy)` (L127)

Plus the section-comment lines marking them (L104, L109, L123).

The new file at `frontend/src/scene/slice_plane/lattice_math.js`:
```js
// Pure lattice-cell math helpers extracted from slice_plane.js (Refactor 09-A).
// Honeycomb (cadnano2 system) + square lattice cell positions.
// Leaf module: imports nothing from slice_plane.js or other slice_plane/* modules.

import * as THREE from 'three'

// (paste the 5 functions verbatim, including section-comment headers)
```

Update `slice_plane.js` top to import them:
```js
import {
  _mod,
  isValidHoneycombCell,
  honeycombCellWorldPos,
  isValidSquareCell,
  squareCellWorldPos,
} from './slice_plane/lattice_math.js'
```

Delete the 5 function definitions from `slice_plane.js` after moving.

## Out of scope

- The 1469-LOC `initSlicePlane` monolith — separate Pass 10+ candidate (Finding #23 #4).
- Cell label sprite helpers (L205-356) — different submodule extraction.
- The `PLANE_CFG` constant (L60-103) — keep in `slice_plane.js` for now.
- The colour constants (L142-145) — keep.
- Any change to `initSlicePlane`'s body.
- Any change to callers of `slice_plane.js` (it's still the same default-export contract).

## Verification plan

### Pre-state (3× baseline per precondition #1)
```bash
git status > /tmp/09A_dirty_pre.txt
just lint > /tmp/09A_lint_pre.txt 2>&1 ; echo "EXIT $?" >> /tmp/09A_lint_pre.txt
for i in 1 2 3; do just test > /tmp/09A_test_pre$i.txt 2>&1; done
for i in 1 2 3; do grep -E '^FAILED|^ERROR' /tmp/09A_test_pre$i.txt | sort > /tmp/09A_baseline$i.txt; done
comm -12 /tmp/09A_baseline1.txt /tmp/09A_baseline2.txt | comm -12 - /tmp/09A_baseline3.txt > /tmp/09A_stable_failures.txt

git show HEAD:frontend/src/scene/slice_plane.js | wc -l > /tmp/09A_slice_loc_pre.txt
```

### Implementation rhythm
1. Read `slice_plane.js:1-145`. Confirm the 5 functions are exactly where the prompt says. If the file structure has drifted, document and adjust.
2. Create `frontend/src/scene/slice_plane/` directory + `lattice_math.js` file. Move the 5 functions verbatim.
3. Add the named import block at the top of `slice_plane.js`.
4. Delete the 5 function definitions from `slice_plane.js`.
5. Run `just test` — failure set must be ⊆ stable_baseline ∪ flakes.

### Post-state
```bash
just lint > /tmp/09A_lint_post.txt 2>&1 ; echo "EXIT $?" >> /tmp/09A_lint_post.txt
just test > /tmp/09A_test_post.txt 2>&1
grep -E '^FAILED|^ERROR' /tmp/09A_test_post.txt | sort > /tmp/09A_post_failures.txt
diff /tmp/09A_stable_failures.txt /tmp/09A_post_failures.txt   # ⊆ stable_baseline ∪ flakes

wc -l frontend/src/scene/slice_plane.js > /tmp/09A_slice_loc_post.txt
wc -l frontend/src/scene/slice_plane/lattice_math.js > /tmp/09A_lattice_loc.txt
```

### Static smoke (no app required for leaf extraction)
The new file imports only `three`. Confirm:
```bash
grep -nE "from\s+['\"](\.|\.\.)/" <worktree>/frontend/src/scene/slice_plane/lattice_math.js
# Should show only `from 'three'` — NO relative imports back to slice_plane.js or sibling modules.
```

## Stop conditions

- Step 0 CWD assert fails: STOP.
- The new file would need to import from `./slice_plane.js` (i.e. it's not a leaf): STOP, document, do not widen visibility — that means the extraction picked the wrong scope. Manager re-scopes.
- Any other `frontend/src` file in the diff: revert, stop.
- Test post-failure not in stable_baseline ∪ flakes: revert, stop.

## Output (worker's final message)

```markdown
## 09-A slice_plane.js lattice-math extract — <REFACTORED|UNSUCCESSFUL>

[NOT VERIFIED IN APP — pure leaf-module move; pair with USER TODO below]

### CWD-safety check (precondition #15)
- Match: yes/no

### Pre-existing dirty state declaration
<git status>

### Findings entry (manager appends to master REFACTOR_AUDIT.md)

### 26. `slice_plane.js` lattice-math leaf extraction — `low` ✓ REFACTORED
- **Category**: (c) god-file decomposition (leaf-pattern; same shape as Finding #13)
- **Move type**: verbatim (5 functions)
- **Where**: `frontend/src/scene/slice_plane.js:107-137` (block deleted + 7-line import); `frontend/src/scene/slice_plane/lattice_math.js` (new, ~35 LOC including header comment + import)
- **Diff hygiene**: worktree-used: yes; files-this-refactor-touched: 2; other-files: none
- **Transparency check**: PASS — sorted caller-set diff empty (callers reference `initSlicePlane`, not the moved math helpers; helpers were unexported)
- **API surface added**: 5 named exports from `lattice_math.js` (previously module-private in `slice_plane.js`; now module-private in `lattice_math.js` but importable by sibling modules — minor expansion of internal surface, no public surface change)
- **Visibility changes**: 5 functions changed from module-private to package-private (named exports from `lattice_math.js`). Acceptable — they're pure math, no side effects.
- **Callsites touched**: 0 external; 5 internal (5 callsites within `slice_plane.js` updated to use the import)
- **Symptom**: 5 pure lattice-cell math helpers buried at the top of a 1625-LOC monolith. Leaf-pattern candidate per Finding #23.
- **Why it matters**: makes a future test prompt for these helpers possible (currently they're un-importable from tests since they're `slice_plane.js`-private). Also seeds the `slice_plane/` subdirectory pattern for future submodule extractions.
- **Change**: created `slice_plane/lattice_math.js`, moved 5 functions verbatim, added named import in `slice_plane.js`, deleted the 5 originals.
- **Effort**: S
- **Three-Layer**: not applicable (frontend rendering layer)
- **Pre-metric → Post-metric**: slice_plane.js LOC <pre> → <post> (Δ ≈ −30); lattice_math.js 0 → <K>; tests baseline-equivalent; lint Δ ≤ 0
- **Raw evidence**: `/tmp/09A_*.txt`
- **Linked Findings**: #13 (recent_files.js leaf-pattern reference); #23 (slice_plane.js #4 god-file candidate; this is a small slice)
- **Queued follow-ups**: extract `slice_plane/label_sprites.js` (L205-356, ~150 LOC; harder — escapes the `initSlicePlane` closure); the full 1469-LOC `initSlicePlane` decomposition.

### USER TODO (NOT VERIFIED IN APP)
1. `just frontend` and load any saved `.nadoc`.
2. Press the slice-plane shortcut (S key, or whatever your binding is) to enter slice-plane mode.
3. Confirm the cell-grid renders correctly for a HONEYCOMB design.
4. Switch to a SQUARE-lattice design and confirm the cell-grid renders correctly there too.
5. Confirm no DevTools console errors. If clean, mark Finding #26 as USER VERIFIED.
```

## Success criteria

- [ ] Step 0 passed
- [ ] `frontend/src/scene/slice_plane/lattice_math.js` exists, imports only `three`
- [ ] 5 functions moved verbatim
- [ ] `slice_plane.js` shrunk by ≥ 25 LOC
- [ ] Only 2 files modified
- [ ] Caller set unchanged (no `frontend/src/scene/*.js` other than the two API files modified)
- [ ] Test post-failure ⊆ stable_baseline ∪ flakes
- [ ] Lint Δ ≤ 0

## Do NOT
- Touch `initSlicePlane`'s body.
- Extract additional submodules in this pass.
- Change function signatures.
- Commit. Append to REFACTOR_AUDIT.md from the worktree.
