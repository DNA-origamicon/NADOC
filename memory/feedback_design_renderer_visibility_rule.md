---
name: Design renderer visibility rule — full scene geometry inventory
description: Hiding/showing design geometry requires covering five modules. design_renderer now has ONE scene object (root); extra-base beads/slabs are children of root. Arc lines are in unfold_view._arcGroup (separate sibling).
type: feedback
originSessionId: 56d058db-5d5d-46e6-a16b-461336fcaa1e
---
Design geometry is spread across **five separate modules**, each owning its own Three.js scene objects. Any visibility/opacity/LOD operation must cover all of them.

## Within `design_renderer.js` — ONE scene object

**`_helixCtrl.root`** — backbone beads, base-pair slabs, axis arrows, 5′ markers, fluorophores, extension beads (`__ext_` helix IDs), **and extra-base crossover beads+slabs** (as children via `buildCrossoverConnections`).

The `buildCrossoverConnections` group (`'crossoverConnections'`, `userData.debugType = 'xoverExtraBasesGroup'`) is added to `_helixCtrl.root` via `root.add(xoverResult.group)`, NOT via `scene.add()`. This means `root.visible` covers everything — no separate second object needed. The canonical entry point is `designRenderer.setDesignVisible(bool)`.

**Previous two-object split is gone**: `_crossoverGroup` no longer exists as a separate scene sibling. If you see old code referencing `_crossoverGroup` as a scene child, it is stale.

## `unfold_view.js` — _arcGroup (the actual arc line geometry)

**`_arcGroup`** — the `THREE.LineSegments` objects for ALL crossover arc lines (straight and Bezier arcs). Scene name: `'xoverArcLines'`, `userData.debugType = 'xoverArcGroup'`. Children are named `'xoverArcMerged_scaffold'` and `'xoverArcMerged_staple'`.

This IS a separate scene sibling (not a child of root). It cannot be moved into design_renderer because `_updateArcPositions()` mutates its merged position buffers at 60 Hz for unfold/cadnano/deform/cluster-drag animations — this is fundamentally animation-loop-driven, incompatible with design_renderer's rebuild-on-change model.

Toggle via `unfoldView.setArcsVisible(bool)`.

## Across modules — five scene owners

When hiding the entire design (e.g. assembly mode), five modules must be called:

| Module | What it owns | Method | Scene object name |
|--------|-------------|--------|------------------|
| `design_renderer.js` | beads, slabs, axis arrows, exts, extra-base beads+slabs (all in one root) | `designRenderer.setDesignVisible(bool)` | `_helixCtrl.root` |
| `blunt_ends.js` | helix-end rings **+ number-sprite axis labels** | `bluntEnds.setVisible(bool)` | |
| `end_extrude_arrows.js` | drag-to-resize handles on helix ends | `endExtrudeArrows.setVisible(bool)` | |
| `joint_renderer.js` | cluster joint axis indicators | `jointRenderer.setVisible(bool)` | |
| `unfold_view.js` | crossover arc LINE geometry | `unfoldView.setArcsVisible(bool)` | `'xoverArcLines'` |

The single coordinated entry point in `main.js` is `_setDesignGeometryVisible(bool)`. If a new scene module is added that renders design data, its `setVisible` call must be added there.

**Why:** These modules add objects directly to the Three.js scene as siblings of each other. There is no shared parent to toggle.

## CG/atomistic mode

`_setCGVisible(visible)` in main.js hides the CG model when atomistic overlay is active:
```js
const root = designRenderer.getHelixCtrl()?.root
if (root) root.visible = visible   // extra-base beads/slabs are children → covered
unfoldView?.setArcsVisible(visible)
// setXoverExtraBasesVisible() removed — no longer needed
```

## Debug tool

`window.__nadocDebugXovers()` in the browser console inspects all layers and prints a visibility report with per-arc detail. Also available as `unfoldView.getArcDebugInfo()` for the arc-lines layer specifically. The `'crossoverConnections'` group is now found via `scene.traverse()` (child of root), not as a direct scene child.
