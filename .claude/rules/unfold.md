---
name: unfold
description: 2D unfold view — animated bezier arcs, helix offsets, minimap, subscription order.
paths:
  - "frontend/src/scene/unfold_view.js"
---

# unfold

## Architecture

## Entry & Initialization
- **File**: `frontend/src/scene/unfold_view.js`
- **Init**: `initUnfoldView(scene, designRenderer, () => bluntEnds, () => loopSkipHighlight, () => sequenceOverlay, () => overhangLocations)` — main.js ~line 859
- **Key**: initialized at line 859; `bluntEnds` initialized at line ~1753. All deps are lazy getters.
- **Minimap**: `frontend/src/scene/cross_section_minimap.js` — 224×224px canvas, top-right corner

## Store Keys
| Key | Semantics |
|-----|-----------|
| `unfoldActive` | Whether 2D unfold view is active |
| `unfoldSpacing` | Row spacing in nm (default 2.5) |
| `unfoldHelixOrder` | `string[] \| null` — helix ID order top-to-bottom |
| `showHelixLabels` | Axis number labels visible (default true) |

## Animation Flow
```
toggle() → animate t: 0→1 (500ms linear)
  each frame:
    helix[i].position.y = -i * spacing (lerp from 3D to unfold stack)
    update backbone/cone/slab instance matrices
    notify: bluntEnds.applyUnfoldOffsets(offsets, t)
             loopSkipHighlight.applyUnfoldOffsets(...)
             sequenceOverlay.applyUnfoldOffsets(...)
             overhangLocations.applyUnfoldOffsets(...)
```

## CRITICAL: Subscription Order Bug
`unfoldView` subscribes to store BEFORE `bluntEnds` (unfoldView initialized at ~line 859, bluntEnds at ~line 1753). After undo/redo:
1. unfoldView fires → calls `getBluntEnds().applyUnfoldOffsets()` → hits OLD sprites
2. bluntEnds fires → `_rebuild()` creates NEW sprites at 3D positions → unfold offsets lost

**Fix**: `unfoldView` exposes `reapplyIfActive()`. `blunt_ends._rebuild()` calls `getUnfoldView?.()?.reapplyIfActive()` after creating new sprites.

## Undo/Redo Behavior
- Topology mutations while unfold active → re-apply offsets at current `_currentT` (stay in unfold)
- New design load: `main.js` explicitly sets `unfoldActive: false` → unfoldView resets `_active=false, _currentT=0`
- Unfold state is NOT preserved across undo when a new design was loaded

## Minimap Details
- 224×224px canvas overlay, `position: absolute; top: 8px; right: 8px`
- Helix radius: `Math.max(6, fitScale * 1.125)` px
- Amber highlights for helices of selected strand (`#ffa726` with shadowBlur glow)
- Pan: pointer drag; Zoom: wheel (cursor-anchored, scale 2–300 px/nm); Reset: double-click
- Visible when `unfoldActive`, hidden otherwise

## Cross-Feature Interactions
- `deformView.snapOff()` called before unfold activates (need straight geometry for unfold)
- View cube hidden when unfold active
- Atomistic hidden when unfold active
- Cadnano mode builds on unfold; see `MAP_CADNANO.md`

## Diagnostics → `RUNBOOK_UNFOLD.md`

## Diagnostics

## Symptoms
- Unfold view snaps back to 3D on undo/redo
- Helix number labels missing after undo in unfold view
- Labels appear at 3D positions instead of unfold stack positions
- Arcs disappear when zoomed in during unfold
- Minimap not showing / not highlighting selected strand
- Unfold toggle does nothing

## First-Check Invariants

1. **Subscription order** — `unfoldView` subscribes before `bluntEnds` (init order ~859 vs ~1753). After topology mutation, unfoldView's store callback fires first → calls `bluntEnds.applyUnfoldOffsets()` on OLD sprites that are about to be disposed → then bluntEnds rebuilds at 3D positions. Fix: `bluntEnds._rebuild()` calls `unfoldView.reapplyIfActive()` at end.

2. **Arc frustumCulled** — `THREE.Line` arc objects must have `frustumCulled = false`. Missing this causes arc disappearance when zoomed.

3. **Undo/redo stays in unfold** — topology mutations while unfold active should re-apply offsets and stay in unfold view. Only a new design load (File > New / open) should exit unfold.

4. **deformView.snapOff()** before unfold activates — unfold needs straight geometry.

## Diagnosis Tree

### Labels at wrong position after undo in unfold view
1. This is the subscription order bug.
2. Find `bluntEnds._rebuild()` (or `bluntEnds._rebuildSprites()`) in `blunt_ends.js`
3. Check if the last line calls `getUnfoldView?.()?.reapplyIfActive()`
4. If missing → add it. This re-applies unfold offsets to the newly created sprites.

### Unfold snaps back to 3D unexpectedly
1. Check `main.js` — does anything set `store.setState({ unfoldActive: false })`?
2. Should only happen on: File > New, open design, design load API call
3. If happening on undo/redo → check unfoldView store subscription — it should NOT reset on `currentDesign` change if `unfoldActive` remains true

### Arcs disappear on zoom
1. Check `unfold_view.js` arc creation loop
2. Each arc `THREE.Line`: `arc.frustumCulled = false` must be set

### Minimap not showing
1. Check `store.unfoldActive` — minimap subscribes and shows/hides based on this
2. Check `cross_section_minimap.js` subscription is registered
3. Minimap DOM element must be inside `#viewport-container`

### Unfold toggle does nothing
1. Check `unfoldView.toggle()` is called (main.js U key handler)
2. Check that `deformView.snapOff()` completes before unfold animation starts
3. Check console for errors in `_buildArcMap` or `initUnfoldView`

### Extensions not showing in unfold
1. `_buildExtArcMap` in unfold_view.js fans extensions horizontally past strand terminus
2. `applyUnfoldOffsetsExtensions` must be called at all 3 unfold update sites

## Files to Read
- `frontend/src/scene/unfold_view.js` — `toggle()`, `reapplyIfActive()`, arc creation
- `frontend/src/scene/blunt_ends.js` — `_rebuild()`, check for `reapplyIfActive()` call at end
- `frontend/src/scene/cross_section_minimap.js` — store subscription

## Related
- `MAP_UNFOLD.md` — unfold view architecture

