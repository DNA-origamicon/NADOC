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

## Diagnostics → [.claude/runbooks/RUNBOOK_RENDERING.md](../runbooks/RUNBOOK_RENDERING.md)

## Files to Read
- `frontend/src/scene/design_renderer.js` — store subscription, rebuild trigger, ghost preview, `clearFemOverlay`
- `frontend/src/scene/helix_renderer.js` — `buildHelixObjects`, `setEntryColor`, `revertToGeometry`
- `frontend/src/main.js` — mrDNA relax overlay callbacks (`applyFemPositions` / `clearFemOverlay`)

## Related
- `MAP_RENDERING.md` — full rendering architecture

