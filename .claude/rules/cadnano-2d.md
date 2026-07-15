---
name: cadnano-2d
description: Cadnano 2D mode (K key) — ortho camera, two-track flat view, arcs, slice indicator, loop/skip markers.
paths:
  - "frontend/src/cadnano/**/*.js"
  - "frontend/src/scene/cadnano_view.js"
---

# cadnano-2d

## Architecture

## Files
- **Main**: `frontend/src/scene/cadnano_view.js` — `initCadnanoView(...)`
- **Modified**: `frontend/src/scene/unfold_view.js` — `applyCadnanoPositions()` method
- **Modified**: `frontend/src/scene/blunt_ends.js` — `applyCadnanoPositions()`, `reapplyIfActive()` guard
- **Modified**: `frontend/src/scene/loop_skip_highlight.js` — `applyCadnanoPositions()`, cadnano quaternions
- **Modified**: `frontend/src/scene/helix_renderer.js` + `design_renderer.js` — `setAxisArrowsVisible()`
- **Init site**: `main.js` line ~878

## Init Signature
```javascript
initCadnanoView(sceneCtx, designRenderer,
  getUnfoldView, getSequenceOverlay, getSlicePlane,
  getBluntEnds, getLoopSkipHighlight)
```
`sceneCtx` must expose: `camera`, `controls`, `scene`, `renderer`, `setRenderCamera`,
`restoreRenderCamera`, `pushControls`, `popControls`, `setResizeCallback`, `clearResizeCallback`,
`animateCameraTo`, `captureCurrentCamera`.

## Store Keys
| Key | Semantics |
|-----|-----------|
| `cadnanoActive` | Whether cadnano mode is active (set true inside activate, false inside deactivate) |

## Activation Guard Flags
- `_active` — true after full activation; false while in transition or inactive
- `_inTransition` — set true at start of activate/deactivate; cleared at end; prevents re-entry

## Two-Stage Animation (activate)
```
Stage 1 (250ms): unfoldView.activateWithDuration(250) — helices stack
Stage 2 (250ms): parallel
  _animate(_unfoldPosMap, _cadnanoPosMap, ...) — beads lerp to flat positions
  animateCameraTo(X- orbit, same dist + target)  — camera rotates to X- view
After animation:
  designRenderer.setAxisArrowsVisible(false)
  getBluntEnds().applyCadnanoPositions(_rowMap, _spacing, _midX)
  getLoopSkipHighlight().applyCadnanoPositions(_rowMap, _spacing, _midX)
  _buildRowBands()       — YZ-plane translucent band meshes
  _activateOrthoCamera() — copies perspective camera exactly; frustum = dist*2*tan(fov/2)
  _showSlicePlane()      — cadnano BP indicator in YZ
  _active = true; cadnanoActive = true
  _enableSideEffects()   — NO-OP since 2026-06-29 (the base-sequence overlay is KEPT
                           in cadnano; reapplyPositions remaps its letter instances to
                           flat bead positions, and the quads face +X = the ortho view
                           axis. Previously this force-hid showSequences → cadnano had
                           no base display at all.)
```

## Position Map Keys
`_cadnanoPosMap` and `_unfoldPosMap`: `Map<"helix_id:bp_index:direction", THREE.Vector3>`
Same key format as `unfold_view.js` `_straightPosMap`.

## Glow Positioning Invariant (CRITICAL)

The selection glow reads `entry.pos` **at the moment `setGlowEntries()` is called** and bakes
those positions into the glow InstancedMesh. It does NOT update automatically when `entry.pos`
is later mutated.

**selectionManager's rebuild subscriber fires BEFORE cadnanoView's reapply subscriber.**
After `_rebuild()` creates new entries (at 3D positions), selectionManager re-applies the glow
at the unfold/3D positions. Then `reapplyPositions()` mutates `entry.pos` to cadnano coordinates
but the glow mesh is not updated — glow stays at the stale 3D position.

**Fix**: every path that mutates `entry.pos` to cadnano coordinates must follow with
`designRenderer.refreshAllGlow()` to re-read the updated positions into the glow mesh:
1. `_animate()` frame loop — after `applyCadnanoPositions()`
2. `reapplyPositions()` — after all position calls (last line before debug exit)

The unfold animation already does this correctly (`refreshAllGlow()` on every frame in unfold_view.js).

## Arc Positioning Invariant (CRITICAL)
Arcs must always track the beads they connect. `unfold_view.applyCadnanoPositions(toMap, t, fromMap)` is called:
1. Every animation frame in `_animate()` (cadnano activation/deactivation)
2. From `reapplyPositions()` after any geometry/design rebuild

`blunt_ends.js` guards its `reapplyIfActive()` call with `!store.getState().cadnanoActive`
to prevent unfold offsets overwriting cadnano bead positions after a rebuild.

## reapplyPositions()
Called from main.js subscribers whenever `currentGeometry` OR `currentDesign` changes while
cadnano is active. Fires on design-only changes too (API sometimes delivers design first,
geometry in a separate async fetch → two separate store.setState calls).
```javascript
designRenderer.applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)
getSequenceOverlay().applyUnfoldOffsets(new Map(), 1.0, _cadnanoPosMap, null)
getUnfoldView().applyCadnanoPositions(_cadnanoPosMap, 1, _unfoldPosMap)
getBluntEnds().applyCadnanoPositions(_rowMap, _spacing, _midX)
getLoopSkipHighlight().applyCadnanoPositions(_rowMap, _spacing, _midX)
designRenderer.refreshAllGlow()
```

### _unfoldPosMap — MERGE-ONLY (CRITICAL)
`_unfoldPosMap` is built with a **merge-only** pattern — only insert keys that are NOT already
present. Never reassign the whole map or call `snapshotPositions()`:

```javascript
if (!_unfoldPosMap) _unfoldPosMap = new Map()
for (const entry of designRenderer.getBackboneEntries()) {
  if (entry.nuc.helix_id.startsWith('__xb_'))  continue
  if (entry.nuc.helix_id.startsWith('__ext_')) continue
  const key = `${entry.nuc.helix_id}:${entry.nuc.bp_index}:${entry.nuc.direction}`
  if (!_unfoldPosMap.has(key)) _unfoldPosMap.set(key, entry.pos.clone())
}
```

**Why**: `reapplyPositions()` is called twice per geometry change — once synchronously
(beads at unfold positions → correct baseline) and once via a deferred async callback
(beads already at cadnano positions → would corrupt the baseline). The merge-only approach
ignores the second call because all keys are already present.

## Deactivation (reverse)
```
_restoreSideEffects(); _hideSlicePlane(); setCamera(perspCamera); _removeRowBands()
Capture ortho state → compute matching perspective position (same dist via FOV)
designRenderer.setAxisArrowsVisible(true)
_deactivateOrthoCamera()
Place perspective camera at: orthoTarget + camDir * -perspDist
await _animate(_cadnanoPosMap, _unfoldPosMap, ...) — beads reverse-lerp
unfoldView.setSpacing(...) — re-applies unfold offsets to all overlays (restores loop/skip quaternions)
_active = false; cadnanoActive = false
if (!keepUnfold && !_wasUnfoldActive) unfoldView.deactivate()
```

## View Transitions (all supported combinations)

`deactivate({ keepUnfold = false })` — `keepUnfold` controls whether unfold stays active on exit.

| From | To | Key | Code path |
|------|----|-----|-----------|
| 3D | Unfold | U | `_toggleUnfold()` → `unfoldView.activate()` |
| 3D | Cadnano | K | `_toggleCadnano()` → `cadnanoView.activate()` (auto-enables unfold) |
| Unfold | 3D | U | `_toggleUnfold()` → `unfoldView.deactivate()` |
| Cadnano | 3D | K | `cadnanoView.deactivate()` — unfold deactivated if auto-activated |
| Unfold | Cadnano | K | Same as 3D→Cadnano; `_wasUnfoldActive=true` → unfold stays on K exit |
| **Cadnano** | **Unfold** | **U** | `_toggleUnfold()` intercepts: `cadnanoView.deactivate({ keepUnfold:true })` — exits cadnano, stays in unfold |
| Cadnano→Unfold | 3D | U | Second U press hits normal unfold→3D path |

**U-key intercept in `_toggleUnfold()`** (main.js):
```javascript
if (cadnanoView.isActive()) {
  await cadnanoView.deactivate({ keepUnfold: true })
  // minimap/slice cleanup same as K exit
  document.getElementById('mode-indicator').textContent =
    '2D UNFOLD — helices stacked by label order · [U] to return to 3D'
  return
}
```

`unfoldView.setSpacing()` (called at end of deactivate) triggers `applyUnfoldOffsets` on all
overlays including `loopSkipHighlight` — this restores skip arm quaternions to the 3D/unfold
orientation (XY plane) after cadnano overwrote them with YZ-plane quaternions.

## Loop/Skip in Cadnano Mode

`loop_skip_highlight.js` has `applyCadnanoPositions(rowMap, spacing, midX)`:
- **Loop torus**: positioned at `(midX, -row*spacing, bpIndex*RISE)` — helix centre (between tracks)
- **Skip X arms**: same position; quaternions changed from XY-plane (Euler Z ±45°) to YZ-plane
  (Euler X ±45°) so the × is visible from the ortho X- camera direction
- `applyUnfoldOffsets` restores arm quaternions back to XY-plane when exiting cadnano

Position formula uses `bpIndex * BDNA_RISE_PER_BP` for Z, matching the bead cadnano posmap convention.
Loop/skip markers are NOT animated during the 250ms bead lerp — they snap to cadnano positions
after the animation (same as bluntEnds).

## Minimap & Slice Highlights (main.js)
- `_hideSlicePlane()` calls `sp.hide()` but does NOT clear the minimap/highlights.
- `_toggleCadnano()` and `_toggleUnfold()` (when exiting cadnano) both call after exit:
  ```javascript
  if (!slicePlane.isVisible()) {
    crossSectionMinimap.clearSlice(); crossSectionMinimap.hide(); _clearSliceHighlights()
  }
  ```
- `_resetForNewDesign()` also calls all three cleanup functions after `slicePlane.hide()`.

## forceExit() (synchronous hard-exit for new-design load)
Cancels any running animFrame; calls _restoreSideEffects, _hideSlicePlane,
setCamera(perspCamera), setAxisArrowsVisible(true), _removeRowBands,
_deactivateOrthoCamera. Resets _active=false, _inTransition=false, maps to null.
Does NOT clean up minimap/highlights — _resetForNewDesign() does that.

## Ortho Camera
- Position/quaternion/up copied from perspective camera exactly → seamless visual switch
- Frustum: `halfH = dist * tan(fovRad/2)`, `halfW = halfH * aspect`
- Resize: preserves `halfH` (zoom level), adjusts `halfW` for new aspect
- OrbitControls: rotate disabled, damping disabled, pan + zoom only
- Shift+right-click: capture-phase listener strips `shiftKey` before OrbitControls sees it
  so shift+right-click pans (same as 3D). Registered in `_activateOrthoCamera`, removed in
  `_deactivateOrthoCamera`.

## Subscriber Ordering Hazards (CRITICAL)

Any subscriber registered in main.js AFTER the cadnanoView reapply subscriber (~line 952)
that calls `designRenderer.clearFemOverlay()`, `designRenderer.applyPhysicsPositions(null)`,
or `_helixCtrl.revertToGeometry()` will OVERWRITE cadnano bead positions with 3D geometry
positions. This causes a one-frame flash to 3D after every topology mutation.

**Known culprit (fixed 2026-04-01)**: FEM "clear stale results" subscriber at main.js:2475.
When topology changes, it called `clearFemOverlay()` → `revertToGeometry()` after reapplyPositions.
**Fix in design_renderer.js `clearFemOverlay()`**:
```javascript
clearFemOverlay() {
  const { cadnanoActive, unfoldActive } = storeRef.getState()
  if (!cadnanoActive && !unfoldActive) {
    _helixCtrl?.revertToGeometry()
  }
  _helixCtrl?.clearFemColors()
},
```
If you add a NEW subscriber that calls `revertToGeometry()` anywhere late in main.js,
apply the same `cadnanoActive && unfoldActive` guard.

## Debugging → [.claude/runbooks/RUNBOOK_CADNANO.md](../runbooks/RUNBOOK_CADNANO.md)
Bead-position intercept technique, debug globals, and known issues live in the runbook.

## Cross-Feature Interactions
- Requires unfold view to be active; auto-activates it; auto-deactivates on exit if it
  was not previously active (`_wasUnfoldActive` flag)
- U key while cadnano active: exits cadnano but stays in unfold (`keepUnfold: true`)
- `_enableSideEffects()` runs AFTER `_active = true` so `cadnanoView.isActive()` is true
  when store callbacks fire — prevents `reapplyIfActive()` from overwriting cadnano positions
- Deformation tool: blocked while cadnano is active (same guard as unfold)
- Expanded spacing: forced off before cadnano activation
- Selection highlight: in cadnano mode `_highlightBead()` sets non-target beads to 1.0×
  (not 1.2×) — whole-strand highlight is suppressed since only the end bead is meaningful

