---
name: Crossover extra-base lerp system
description: Extra-base beads+slabs ride crossover arcs during all view transitions via updateExtraBaseArc() — any new arc-moving operation should call this
type: project
originSessionId: 98703278-3f45-4b55-bf2c-d8e8f4a72d22
---
Extra-base beads+slabs now track the crossover arc during all transitions (unfold, cadnano, deform, cluster drag) via `designRenderer.updateExtraBaseArc(crossoverId, posA, ctrl, posB)` + `flushExtraBaseMeshes()`.

**Why:** Previously beads/slabs were hidden during transitions; now they ride the arc like beads on a string.

**How to apply:** Any new operation that moves crossover arcs should call `designRenderer.updateExtraBaseArc()` per arc + `flushExtraBaseMeshes()` once after all arcs. Currently hooked into `_updateArcPositions()` and `applyCadnanoPositions()` in unfold_view.js, which covers all existing animation paths.
