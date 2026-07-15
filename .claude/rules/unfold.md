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

## Diagnostics → [.claude/runbooks/RUNBOOK_UNFOLD.md](../runbooks/RUNBOOK_UNFOLD.md)

## Files to Read
- `frontend/src/scene/unfold_view.js` — `toggle()`, `reapplyIfActive()`, arc creation
- `frontend/src/scene/blunt_ends.js` — `_rebuild()`, check for `reapplyIfActive()` call at end
- `frontend/src/scene/cross_section_minimap.js` — store subscription

## Related
- `MAP_UNFOLD.md` — unfold view architecture

