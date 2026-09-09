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

## Automatic trajectory preparation (2026-09-04)

The animation sidebar now prefetches trajectory coordinates when rendering/selecting
trajectory keyframes and changing their job/scope/stride. It uses the same display
controller through `trajectory_keyframes.prefetch`; `trajectory_downloads.js` stores
single-flight downloads keyed by job, alignment, scope and stride. Prefetch does not
activate the controller, move the scene, or change topology. Off-screen sessions now
prepare heavy display frames too (`trajectory_preparation_cache.js`), keyed by job,
resolution, representation and surface settings. Rows report frame counts, readiness
and cancellation. Play joins the same work using inline progress rather than a modal
and refuses missing/failed frames. Preview remains optional
for authoring scrubs. Downloads are retained only for the active animation; explicit
refresh bypasses them and cancellation aborts pending requests.

Bottom Play's dirty signature now includes trajectory identity, engine, scope, stride
and start/end. Paused playback cannot silently reuse a pre-edit trajectory schedule.
Prepare tracks frame counts per job **and resolution**, including later jobs sharing
one controller. Job/stride swaps settle the requested frame before playback advances;
the animation clock pauses for asynchronous preparation. Both video exporters already
await `player.settleFrame`, so they share that guarantee. Heavy geometry remains bounded
by the existing memory plan; completed per-job caches are adopted when switching jobs.
Representation changes warm a new cache. Cancel releases the UI immediately and stops
subsequent background work; an in-flight server request may finish without adoption.

Browser verification uses an isolated in-memory API fixture and actual sidebar/player/
display modules: cold background load does not move the model; bottom Play waits, plays
frames in order without Preview, downloads once, and honors range edits on replay.
No workspace files, jobs or exported videos are created by that check.

Non-modal follow-up verification: real VoltronCoreScad's saved 51/151-frame jobs reached
ready; VDW Play exposed inline progress, allowed Help-menu interaction and cancelled
cleanly (browser test passed, no console errors). The final UX check hides software
WebGL drawing to isolate preparation; it is not a full-model FPS benchmark. Private
job/design copies and Playwright artifacts are cleaned even on failure. See the audit
for full-suite/smoke failures and the scope of the large-model check.

Sequence readiness follow-up: download + frame preparation now share an authored-order
queue across engines (`trajectory_preparation_queue.js`). The bottom scrubber exposes
per-keyframe, duration-weighted prepared coverage (`animation_readiness.js` and
`animation_readiness_bar.js`), with download work distinguished from usable cache cells.
Later job metadata allows Play to begin the ready prefix while remaining jobs warm.
Visible job lists bypass the idle timing gate; default background waits expire after
2 seconds without cancelling the timed operation. Metadata/preparation no longer wait
for job dropdown population. See the audit for focused and browser verification.

2026-09-05 correction: segment labels now show live parser/transfer stage percentages
with blue loading fill; green remains actual prepared coverage. The initial version
hid those intermediate work percentages in tooltips and therefore appeared binary
for coarse-grained trajectories. Parser polling stops once transfer begins.
