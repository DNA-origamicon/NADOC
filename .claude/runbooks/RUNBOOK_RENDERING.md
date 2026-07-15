# rendering — diagnostics runbook
Loaded on demand from the `rendering` rule's Diagnostics pointer. Symptom → diagnosis content; not auto-loaded.

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
