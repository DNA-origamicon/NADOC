# unfold — diagnostics runbook
Loaded on demand from the `unfold` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

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
