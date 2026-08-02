---
name: Animation system — all representations
description: CG beads, atomistic, and molecular surface all participate in the animation pre-bake + lerp pipeline
type: project
originSessionId: 7e08699f-f784-4b54-ac56-e0a843377a6f
---
All three representations are animated via the same pre-bake pipeline in `animation_player.js`.

> **Scope (2026-08-02):** this file covers the **feature-log** pre-bake only. **Trajectory
> keyframes no longer bake here at all** — they drive the jobs panels' display controllers via
> `scene/trajectory_keyframes.js`, so they inherit that path's per-job cache, memory budget,
> topology-once fetch and serialised fetch queue. See `.claude/rules/animation.md` →
> "Trajectory keyframes". The player's private trajectory pipeline (`_bakedTrajectories`,
> `_bakedTrajAtom`, `_bakedTrajSurf`, the fixed 40/20-frame caps) is **deleted**.

## Pre-bake endpoints (called once before playback starts)

| Representation | Endpoint | Storage |
|---|---|---|
| CG beads | `POST /design/features/geometry-batch` | `_bakedStates` Map |
| Atomistic | `POST /design/features/atomistic-batch` | `_bakedAtomistic` Map |
| Surface | `POST /design/features/surface-batch` | `_bakedSurface` Map |

All three are fetched in parallel inside `_bakeStates`. A `baking` event with `hasSlow=true` is emitted when atomistic or surface is active so the UI shows an indeterminate loading bar.

## Per-frame lerp (inside `_applyAt`)

- **CG**: `helixCtrl.applyPositionLerp(fromBaked, toBaked, t, clusterHelixIds)` — cluster helices excluded (handled by rigid-body transform instead)
- **Atomistic**: `atomisticRenderer.applyPositionLerp(fromAtom, toAtom, t, _liveAtomistic, clusterTransforms, clusterHelixIds)` — cluster atoms use rigid-body rotation (`incrRot(base − center) + dummy`), where `_liveAtomistic` is the play-start atom array captured before playback
- **Surface**: `surfaceRenderer.applyPositionLerp(fromData, toData, t)` — topology-aware (see below)

## Surface topology-aware lerp

Different feature-log positions produce different marching-cubes vertex counts. `applyPositionLerp` handles this:

- **Same vertex count** (from.vertices.length === to.vertices.length): in-place lerp each frame; resizes buffer once if live mesh differs
- **Different vertex count** (topology mismatch): snaps to from-state at t<0.5, to-state at t≥0.5; rebuilds geometry buffer with `_rebuildTopology(data)` which also disables vertex colours (baked states carry no strand colour data — restored by `update()` on stop/finish)

The `surface_batch` endpoint returns both `vertices` and `faces` for each position so the frontend can rebuild the Three.js BufferGeometry when topology changes.

## `apply_deformations_to_atoms`

`backend/core/deformation.py` — applies bend/twist deformations and cluster rigid-body transforms to `Atom` objects in-place (same math as `deformed_nucleotide_arrays`). Called at the end of `build_atomistic_model` so exported PDB and animation frames always reflect the deformed state.

## Stop/finish cleanup

On `stopped` or `finished` events: `_atomDataCache = null` + re-fetch atomistic, `_surfaceDataCache = null` + re-fetch surface. Restores strand colours and correct deformed state after animation ends.

**Why:** Pre-baked states leave atom positions and surface mesh in the last lerped frame. Re-fetching from the live backend restores the correct deformed geometry including strand colours.
