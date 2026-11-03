# Shared presentation playback (2026-09-30) — supporting detail

[Topic head](../../project_animation_all_reprs.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Shared presentation playback (2026-09-30)

The editor player now publishes settled animation frames through
`viewer/animation_sharing.js` whenever a presentation link is active. Camera and
styled text metadata travel with each geometry patch. Scene/material/layout
changes replace the prepared scene; texture-backed assembly placements are baked
before patch capture. Paused seeks also publish. Export/upload waits hold the
player clock, so preparation does not consume animation time. Normal sampling is
15 Hz; large scenes and slow connections can reduce delivery speed.

The presenter controls include a guest-perspective lock icon. The manual lock and
animation lock are independent server state: an animation forces the lock on,
including while paused, and completion/Stop restores the manual choice. Guest
orbit, zoom, reset, view-cube navigation and saved-view jumps respect the lock.
Animation lease expiry clears its automatic lock. Stop republishes the restored
native model on the same invitation. Requires `animation-stream-v1` and
`view-lock-v1` hosting capabilities; existing host processes need restarting.

Verification: the two-guest browser test covers changing geometry/camera, styled
captions, late join, pause/seek/resume, completion, locked drag/zoom and manual
lock preservation. Frontend: 583 files / 7,321 passed, one skipped; sharing host
and proxy: 27 passed; smoke: 23 passed; production build and lint passed.
The guarded backend FAST run had 9,485 passed, 93 skipped and six failures in
unchanged scalar geometry, surface extraction and VR color-control tests. Its
FULL sweep remains deferred in `.nadoc-slow-pending`. Concurrent verification
triggered workstation memory pressure; recovery checks ran sequentially with
limited workers. Task-created designs, histories, credentials and browser
reports were removed; older unrelated test stores were preserved.

## Pre-bake endpoints (called once before playback starts)

| Representation | Endpoint | Storage |
|---|---|---|
| CG beads | `POST /design/features/geometry-batch` | `_bakedStates` Map |
| Atomistic | `POST /design/features/atomistic-batch` | `_bakedAtomistic` Map |
| Surface | `POST /design/features/surface-batch` | `_bakedSurface` Map |

Representations are fetched together for each position; positions are processed sequentially inside `_bakeStates`. A `baking` event with `hasSlow=true` is emitted when atomistic or surface is active so the UI shows an indeterminate loading bar.

**2026-09-25 display parity fix:** CG `geometry-batch` explicitly selects the
accepted measured display placement, matching `GET /design/geometry` for bent
and straight states. Its compact wrapper forwards this option while retaining
the raw-geometry default for other callers. Existing endpoint parity tests cover
both cases; no placement constants or atomistic goldens changed.

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
