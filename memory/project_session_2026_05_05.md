---
name: 2026-05-05 polish session — UX, hull-prism reliability, atomistic-mode linker bridge
description: Cluster-of-fixes session — export clearing, welcome sidebar collapse, hull rebake, cadnano editor parity (Gen button, overhang strip, F-key, ruler), 5 s busy threshold, atomistic-mode linker bridge alignment. Read before touching any of these surfaces.
type: project
originSessionId: fdc481cc-d1e5-40f0-848f-0796d43300bb
---
# Session 2026-05-05 — Polish & reliability fixes

Branch: `master` at this point. All changes built and committed.

## What shipped

### 1. Video/GIF export — frame accumulation
**File:** `frontend/src/scene/export_video.js`
**Bug:** `_captureWebM` and `_captureGIF` drew the WebGL canvas onto a temp 2D canvas without clearing it; transparent regions of the WebGL frame let prior frames bleed through.
**Fix:** `ctx.clearRect(0, 0, w, h)` before each `ctx.drawImage` in both capture loops.

### 2. Welcome screen — sidebar must be collapsed
**File:** `frontend/src/main.js`
**Bug:** `_setLeftPanelEnabled(false)` added `hidden`+`locked-hidden` early in init, but the controller's `_render()` ran later (after persisted state load) and unconditionally toggled `hidden` based on its internal `collapsed` flag — so a previously-expanded session popped the sidebar open at the welcome screen.
**Fix:**
- `_render()` now treats `locked-hidden` as forcing visual `hidden` regardless of internal `collapsed`.
- `_leftSidebar` exposes `refresh()`.
- `_setLeftPanelEnabled(true)` calls `window.__leftSidebar?.refresh?.()` after unlocking, so the persisted state is reapplied.

### 3. Hull prism tracking after cluster transforms
**Files:** `frontend/src/main.js`
**Root cause:** Plan B's commit path keeps `currentHelixAxes` stale (skipGeometry: true). The hull prism is rebuilt from helix_axes, so any later rebuild puts the hull at the pre-move position. The live drag's rigid-transform of hull groups is also lost on subsequent topology mutations that trigger a rebuild.
**Fix — new helper `_rebakeHelixAxesForClusterDelta(helixIds, oldCt, newCt)`:**
- Applies `f_new ∘ f_old⁻¹` to `ax.start`, `ax.end`, `ax.samples`, `ax.segments[*].start/end`, and `ax.ovhgAxes[*].{start,end,samples,direction}` in place — keeping the outer object reference stable so identity-gated subscribers don't fire spurious rebuilds.
- Wired into three commit paths:
  - `_confirmTranslateRotateTool` standard commit: snapshots `oldCt` from `currentDesign` before `commitPendingTransforms`, rebakes axes per moved cluster, calls `jointRenderer.rebuildHulls()`.
  - Same function's `cluster_op` edit branch.
  - `_applyClusterUndoRedoDeltas`: uses cluster_diffs' old/new transforms, looks up `domain_ids` from live design (cluster_diffs don't include them), single `rebuildHulls()` after the loop.
**Sub-cluster guard:** rebake skipped when `cluster.domain_ids?.length` (helix isn't rigidly transformed when only part of it moves).

### 4. Cadnano editor spreadsheet parity with 3D NADOC
**Files:** `frontend/src/cadnano-editor/strands_spreadsheet.js`, `frontend/src/cadnano-editor/api.js`, `frontend/cadnano-editor.html`
**Issues fixed:**
- Sequence column included terminal `NNNN…` overhang bases (3D version trims them, since they're in dedicated ovhg_5p/ovhg_3p columns).
- No `Gen` button on overhang cells.
- Visual mismatch — `.sheet-gen-btn` CSS lived only in `index.html`.

**Fix:**
- Ported 3D NADOC's `_strandDisplaySequence` overhang-stripping logic.
- Ported `_makeOverhangCell` (input + Gen button, label-with-edit + Gen button for unsequenced).
- Added `generateOverhangRandomSequence(overhangId)` to cadnano editor's api.js (mutate-helper wrapped, broadcasts design-changed).
- Ported `.sheet-gen-btn` (and `:hover`/`:disabled`) CSS to cadnano-editor.html.

### 5. "Working" popup threshold raised
**File:** `frontend/src/api/client.js`
**Change:** `_BUSY_POPUP_DELAY_MS` 1500 → 5000. The user found the 1.5 s flash-popup more annoying than helpful; 5 s only triggers for genuinely long ops (large autostaple, big imports, full-design relax).

### 6. Sliceview — fit on active helices, F-key
**Files:** `frontend/src/cadnano-editor/sliceview.js`, `frontend/src/cadnano-editor/main.js`
**Bug 1 (auto-fit at design load):** `_fitDone = activeCells.length > 0 || true` was always true — so the very first render (with no design) "fit" the empty grid and any later design load was ignored. Fixed to gate on `activeCells.length > 0`.
**Bug 2 (svg-pan-zoom NaN crash):** computing absolute zoom via `targetReal / ratio` where `ratio = realZoom/zoom` blew up to `Infinity` when `sizes.zoom` was 0 (viewBox not yet settled), giving `Failed to execute 'scale' on 'SVGMatrix': non-finite`.
**Fix:** switched to `zoomBy(targetReal / currentReal)` (relative, robust to weird viewBox states) plus `isFinite()` guards on zoom factor and pan values; falls back to native `fit() + center()` on bad sizes.
**F-key:** `pathview.fitToContent()` + `sliceview.fitToContent()` exposed; window keydown handler routes `f`/`F` to both. Optional chaining (`?.`) on the calls so a partially-init editor doesn't crash.

### 7. Path view — adaptive ruler intervals
**File:** `frontend/src/cadnano-editor/pathview.js` (`_drawRuler`)
**Behaviour:** when zoomed out, the natural 7-bp (HC) / 8-bp (SQ) ruler labels overlapped. Now picks `baseMajor × 2^k` (smallest power of two such that step ≥ digit-width × digit-count + 6 px gap). Labels still align with the 7/8 cadnano grid.

### 8. Atomistic-mode linker bridge alignment ★ KEY FINDING
**File:** `backend/core/lattice.py` (`_make_virtual_linker_helix`)
**Root cause (subtle):** Two functions place the ds-linker bridge in 3D and they were silently disagreeing:
- `_emit_bridge_nucs` (CG geometry path) → `bridge_axis_geometry` → axis is **offset perpendicular to chord** by `−(radial_a + radial_b) / 2 * R` so boundary beads sit at native B-DNA radius and colocalize with OH anchors.
- `_make_virtual_linker_helix` (atomistic path, also stored in `Design.helices`) → axis at **chord midpoint, no offset**.

Result: atomistic linker atoms placed ~1 nm off from where the CG bridge beads were — visually appeared as "missing bridge".

**Fix:** `_make_virtual_linker_helix` now calls `bridge_axis_geometry(p_a, n_a, p_b, length_bp, comp_first_a, comp_first_b)` and uses its `axis_start`/`axis_end`. Falls back to chord-midpoint on any exception (legacy designs without comp_first inputs). 57 overhang tests still pass.

**Why fixing here was correct (not in atomistic.py):** the stored helix.axis_start should match the rendered bridge in ALL paths, not just atomistic. Aligning the storage means CG, atomistic, exports, and any future consumer agree.

### 9. CG bake during atomistic/surface modes — clarification, not a fix
**Why CG bake is still needed when only atomistic/surface is visible:**
- Helix axis sticks read positions from `_bakedStates`.
- Joint indicators read positions from `_bakedStates`.
- Hull prisms read positions from `_bakedStates`.
- Blunt-end labels.
- **Linker-bridge fade-in/fade-out scales** (`overhangLinkArcs.setConnectionScales`) read `strandSet` from CG bake.

CG bakes are also fast (visible as the first 4/N units to complete); the slowness the user saw was from surface marching-cubes and atomistic build, not the CG path.

## Atomistic speedup — deferred

Backend `build_atomistic_model` is the actual bottleneck; FastAPI's sync `def` thread pool can't truly parallelize GIL-bound Python loops. A real speedup would need:
- `ProcessPoolExecutor` inside `atomistic_batch` and `surface_batch`, OR
- Rewrite hot loops in numpy-vectorised form so GIL is released, OR
- Server-Sent Events to keep incremental progress reporting if we batch all positions in one call.

Not implemented this session — user said "completely understandable if not possible" and asked for the linker fix as the firm requirement. Leave the diagnostic-friendly per-position requests in place; they give correct progress reporting at the cost of N× the per-call overhead (negligible compared to the compute).

## Critical gotchas / DO NOT BREAK

- **`_rebakeHelixAxesForClusterDelta` mutates the per-helix axis dicts in place** but keeps the `currentHelixAxes` outer object reference stable. The hull-rebuild subscriber gates on `n.currentHelixAxes !== p.currentHelixAxes` — that gate is intentionally NOT tripped by this in-place mutation. The explicit `jointRenderer.rebuildHulls()` call in the same code paths is what triggers the rebuild. Don't replace the mutation with a clone-and-replace; you'll cascade rebuilds across unrelated subscribers.

- **Sub-cluster (`domain_ids` non-empty) clusters skip the axis rebake.** Their helices aren't rigidly transformed (only some domains move), so applying a rigid R/T to the axis would lie. Hull prisms also aren't tracked for sub-cluster moves (the live-drag `applyClusterTransform` callback in `clusterGizmo` skips `jointRenderer` when `domainIds?.length`).

- **`_make_virtual_linker_helix` axis_start now matches `bridge_axis_geometry`.** Anything that builds geometry from the stored helix (atomistic, exports, oxDNA, GROMACS, FEM) now lands at the same position as the CG bridge. If you change one of these formulas, change the other in lockstep — they MUST stay in sync.

- **Welcome-screen sidebar:** the `locked-hidden` class has no CSS rule on its own; it's a marker for the controller. Don't add visual rules to it — the visual hidden comes from the `hidden` class which `_render()` sets when `collapsed || locked-hidden`.

- **Cadnano editor F-key:** registered on `window`, not `document`. Pre-existing dev-debug handler at line 189 is on `document` for Ctrl+Shift+D. Both fire because key events bubble; don't consolidate.

- **Adaptive ruler:** the `digits` calc factors in negative-bp range (`+1` for the minus sign). HC and SQ both use `baseMajor` because the cadnano grid alignment is sacred — labels must always land on bp positions that are multiples of 7 (HC) or 8 (SQ).

## Files touched

```
backend/core/lattice.py                              (+13 -1)  — atomistic linker bridge alignment
frontend/cadnano-editor.html                         (+19)     — .sheet-gen-btn CSS
frontend/index.html                                  -          (referenced for parity)
frontend/src/api/client.js                           (+1 -2)   — _BUSY_POPUP_DELAY_MS = 5000
frontend/src/cadnano-editor/api.js                   (+8)      — generateOverhangRandomSequence
frontend/src/cadnano-editor/main.js                  (+8)      — F-key handler
frontend/src/cadnano-editor/pathview.js              (+19 -3)  — fitToContent, adaptive ruler
frontend/src/cadnano-editor/sliceview.js             (+71 -8)  — fit-to-active-cells, fitToContent
frontend/src/cadnano-editor/strands_spreadsheet.js   (+98 -27) — overhang strip, Gen button
frontend/src/main.js                                 (+~110)   — sidebar refresh, hull rebake
frontend/src/scene/export_video.js                   (+2)      — clearRect before drawImage
frontend/src/ui/spreadsheet.js                       (+5 -1)   — strandsChanged guard (defensive)
```
