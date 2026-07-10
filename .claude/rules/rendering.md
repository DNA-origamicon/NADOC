---
name: rendering
description: Three.js scene rendering pipeline + diagnostics. Store keys, instanced-mesh layout, color merge, relax/deform overlays, ghost preview.
paths:
  - "frontend/src/scene/design_renderer.js"
  - "frontend/src/scene/helix_renderer.js"
  - "frontend/src/scene/glow_layer.js"
  - "frontend/src/scene/domain_ends.js"
  - "frontend/src/scene/crossover_connections.js"
---

# rendering

## Pipeline

## Entry & Initialization
- **design_renderer.js**: `initDesignRenderer(scene, storeRef)` — main.js ~line 106, initialized FIRST
- **helix_renderer.js**: called by design_renderer via `buildHelixObjects(scene, design, geometry, designRenderer, opts)`
- Reactive: subscribes to `store.currentGeometry` + `store.currentDesign` → rebuilds on change

## Store Keys
| Key | Semantics |
|-----|-----------|
| `currentGeometry` | Array of NucleotidePosition dicts from `GET /design/geometry` |
| `currentHelixAxes` | `Map helix_id → {start, end}` for axis arrows |
| `cgRelaxPositions` | mrDNA-relaxed positions overlay (applied via `applyFemPositions`) |
| `deformVisuActive` | Lerp helices between straight (t=0) and deformed (t=1) |
| `straightGeometry` | Straight (un-deformed) geometry — t=0 anchor |
| `straightHelixAxes` | Straight helix axes — t=0 anchor |
| `staplesHidden` | All staples hidden |
| `isolatedStrandId` | Only this strand fully visible; others ghosted |
| `strandColors` | Per-strand hex overrides |
| `strandGroups` | `[{id, name, color, strandIds}]` — group color overrides per-strand |
| `loopStrandIds` | Circular staples → rendered red |
| `showSequences` | Base-letter sprites visible |
| `atomisticMode` | `'off' \| 'vdw' \| 'ballstick'` |
| `surfaceMode` | `'off' \| 'on'` |

## Rendering Architecture
```
designRenderer.rebuild(design, geometry)
  → helix_renderer.buildHelixObjects()
    → 4 instanced WebGL draw calls:
       iFwd/iRev: backbone spheres (per nucleotide)
       iCones:    5' cube markers + direction cones
       iSlabs:    base-pair slab geometry
  → returns { backboneEntries, coneEntries, slabEntries, ... }
```

## Color Merge
`_effectiveColors(strandId)`: checks `strandGroups` first (group color wins), then `strandColors` per-strand override, then STAPLE_PALETTE default.

## Position Overlays (mrDNA relax / Deform / Unfold)
```
mrDNA relax ON:  applyFemPositions(updates) → moves backbone beads in-place
mrDNA relax OFF: applyFemPositions(null) → revertToGeometry()  (clearFemOverlay)

Deform:      applyDeformLerp(straightPosMap, straightAxesMap, t)
Unfold:      applyUnfoldOffsets(helixOffsets, t)
```
Note: the legacy XPBD/oxDNA physics overlay and the FEM RMSF heatmap were removed
2026-05-22. `applyFemPositions`/`clearFemOverlay` are retained — they are the mrDNA
relaxed-position overlay (historically FEM-named). The standalone physics simulation
is deprecated; do not reintroduce a physics-overlay store key.

oxDNA flexibility map (2026-06-14): a NEW per-base scalar recolor, distinct from the
removed FEM heatmap. `helix_renderer.applyScalarColors(colorByKey)` /
`clearScalarColors()` recolor backbone beads + base slabs + direction cones by a
`"helix:bp:dir"→hex` map (captures + restores prior colors, no rebuild);
`design_renderer` mirrors them and fires `_scalarArcUpdater` →
`unfold_view.applyFemArcColors` so crossover arcs match. Driven by the oxDNA RMSF
display (`oxdna_display.js`); positions still flow through `applyFemPositions`.

## Deform Tool preview overlay (current solid + result ghost — 2026-05-27)
During a bend/twist preview the deform tool shows BOTH the current design and a ghost
of the result, for the CG reps (full/beads/cylinders). Hull-Prism auto-switches to full
on edit (main.js `deformToolActive` branch), so the CG overlay covers it too.
- `designRenderer.beginDeformPreview(ghostOpacity)` — called once per session (from
  `deformation_editor.previewDeformation`, BEFORE the first preview op) for BOTH the
  new-op and edit-in-place paths. Sets `_captureNextAsFrozen`; the next `_rebuild`
  keeps the OLD (committed) root in the scene at FULL opacity (`_frozenRoot` = "where
  the design is now"), and every subsequent deformed rebuild renders at `_ghostOpacity`
  (`PREVIEW_GHOST_OPACITY` = 0.38 — the translucent "where it will be").
- `designRenderer.endDeformPreview()` — called from `deformation_editor._cancelPreview`
  (the universal teardown reached by confirm/cancel/escape/exit). Disposes `_frozenRoot`,
  clears `_ghostOpacity`, restores the live root to solid (or the 0.15 tool dim if the
  tool is still active placing planes).
- NOTE the opacity is FLIPPED vs the old "before-ghost": reference is now SOLID, result
  is the ghost. `setToolOpacity` and `_tryPatchInPlace` both early-out while
  `_ghostOpacity !== null`. While placing planes (no preview yet) the scene is dimmed to
  0.15 via the `deformToolActive` branch in `_rebuild`.
- `deformView`'s straight↔deformed LERP (`straightGeometry`/`straightHelixAxes`) is a
  SEPARATE system (lerps the same beads, no second copy) and is untouched.

## LOD System
LOD levels: Full (default), Cylinders, Sticks. Change via View menu. Groups are **color-only** — no rebuild on group change.
Arc colors sync with strand/group colors via unfold_view subscriptions.

## Cross-Feature Interactions
- After any `revertToGeometry()` (e.g. `clearFemOverlay()` ending an mrDNA-relax overlay) → reapply an active deform lerp via `deformView.reapplyLerp()`, or helices snap back to straight when a deformation exists
- Unfold active → `applyUnfoldOffsets()` translates helix positions; called in unfold_view animation frame
- Selection → glow layer updated on `selectedObject` change

## Diagnostics → `RUNBOOK_RENDERING.md`

## Diagnostics

## Symptoms
- Scene goes blank after mutation
- Geometry doesn't update after API call
- Deformation not visible even though deformVisuActive = true
- Strand colors not updating after `setStrandColor()` call
- Scene rebuilds but ignores group color assignment
- **Beads flash to 3D for one frame after strand resize in cadnano/unfold mode**

## First-Check Invariants

1. **Design + geometry must arrive together** — `_syncFromDesignResponse` does one `store.setState()` with both `currentDesign` and `currentGeometry`. If they arrive separately (two setState calls), design_renderer subscribes to both and rebuilds twice. Check that `_design_response_with_geometry` is used for mutation endpoints.

2. **Revert sequence** — after any `revertToGeometry()` (e.g. `clearFemOverlay()` ending an mrDNA-relax overlay), call `deformView.reapplyLerp()`. Missing it leaves helices straight when a deformation exists.

3. **Group color wins** — `_effectiveColors(strandId)` checks `strandGroups` first. If a strand is in a group with a color, the group color overrides `strandColors[strandId]`.

## Diagnosis Tree

### Scene blank after mutation
1. Check `store.currentGeometry` — is it null? If yes, geometry wasn't fetched.
2. Check `store.currentDesign` — is it null?
3. Check `store.lastError` — did the API call fail?
4. If design non-null but geometry null: call `api.getGeometry()` or check that the route uses `_design_response_with_geometry`

### Geometry doesn't update (stale scene)
1. Check browser console for errors during the API call
2. Check `store.currentGeometry` — timestamp/length changed?
3. Check `design_renderer.js` subscription — does it compare `currentGeometry` identity or deep-equal?
4. If geometry updated but scene unchanged → check if `buildHelixObjects` is being called


### Strand color not updating
1. Check `store.strandColors[strandId]` — is it set?
2. Check `store.strandGroups` — does a group contain this strand? Group color overrides.
3. Check `_effectiveColors()` in `design_renderer.js`
4. After color change, `helix_renderer.setEntryColor(entry, hex)` must be called for the entry

### instanceColor null error
- `instanceColor.needsUpdate` can throw if Three.js hasn't allocated instanceColor yet (lazy allocation on first `setColorAt`)
- Pattern: `if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true`

### Beads flash to 3D for one frame in cadnano or unfold mode

**Symptom**: After a strand resize (or any topology mutation) while cadnano/unfold is active,
all beads visually jump to 3D geometry positions for exactly one frame, then snap back.

**Root cause**: A store subscriber registered AFTER `cadnanoView`'s reapply subscriber calls
`revertToGeometry()`, overwriting cadnano/unfold positions. Subscribers fire in registration order —
any late subscriber calling `revertToGeometry()` wins.

**Known culprit (fixed 2026-04-01)**: a late store subscriber that called
`designRenderer.clearFemOverlay()` → `_helixCtrl.revertToGeometry()` after every topology
change, regardless of cadnano/unfold state. Fixed by the cadnano/unfold guard now in
`clearFemOverlay()` (which today only backs out the mrDNA-relax overlay).

**How to diagnose** — set `window._cnDebug = true` before reproducing, then look for
`[INTERCEPT f…]` logs. They show a stack trace pointing to the exact function writing the
3D position value. Or add this snippet in the console after a resize to intercept manually:
```javascript
const e0 = window._cnEntries().find(e => !e.nuc.helix_id.startsWith('__'))
let _xVal = e0.pos.x
Object.defineProperty(e0.pos, 'x', {
  configurable: true, enumerable: true,
  get() { return _xVal },
  set(v) {
    if (Math.abs(v - _xVal) > 0.5) console.trace('[INTERCEPT] pos.x →', v.toFixed(3))
    _xVal = v
  },
})
```
The intercept must be installed AFTER `_rebuild()` creates new entries (e0 from before rebuild
is a stale object and won't receive the bad write).

**Fix pattern**: Any function that calls `_helixCtrl?.revertToGeometry()` must guard:
```javascript
const { cadnanoActive, unfoldActive } = storeRef.getState()
if (!cadnanoActive && !unfoldActive) { _helixCtrl?.revertToGeometry() }
```

**Also check**: If the one-frame flash happens from a second `_rebuild()` (not `revertToGeometry`),
add `window._cnDebug = true` and look for `[CN f…] design_renderer._rebuild()` logs.
A second rebuild fires if a `store.setState` with `geoChanged/designChanged/loopChanged = true`
is triggered by a late subscriber (e.g. from `selectNucleotide` → subscriber → `loopStrandIds` change).

## Files to Read
- `frontend/src/scene/design_renderer.js` — store subscription, rebuild trigger, ghost preview, `clearFemOverlay`
- `frontend/src/scene/helix_renderer.js` — `buildHelixObjects`, `setEntryColor`, `revertToGeometry`
- `frontend/src/main.js` — mrDNA relax overlay callbacks (`applyFemPositions` / `clearFemOverlay`)

## Related
- `MAP_RENDERING.md` — full rendering architecture

