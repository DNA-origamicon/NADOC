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

## Construction sequences (2026-10-08)

Existing state-pinned keyframes now traverse all intervening **top-level** feature-log
states during their transition, in either direction. Initial (`-2`) and all-active
(`-1`) are chronological endpoints; the last explicit entry and all-active do not
add a spurious extra operation. Null pins inherit, identical pins hold, and zero
transition duration is an intentional cut. Routing children remain grouped under
their top-level tick, matching the existing State picker.

`feature_animation_sequence.js` owns tick planning and adjacent-pair interpolation.
Camera, spin, binding and joint channels retain the whole-keyframe timing. Each
representation uses the same adjacent build pair. Preparation processes one feature
position at a time (with representation requests together), reports progress, and
fails on missing states instead of quietly exporting an incomplete animation.
The compact batch geometry uses the same optimized evaluation/native slab path as
scrubbing; it never seeks the editable document or pushes undo history.

Historical DNA rendering now uses `feature_animation_display.js` and the existing
external-snapshot renderer API: geometry-batch also supplies `display_design`
without feature-log snapshot bodies. This restores earlier routing and sites that
are absent from the currently edited state. Nanoparticles use the same historical
snapshot lifecycle. A larger adjacent topology carries grow/shrink interpolation;
exact tick endpoints use exact historical topology. Stop restores the editor.
Sweep additions reveal in authored path order using the stored bp range and
`SweepParams.direction`, including continuation toward lower bp. Reverse playback
retracts from path end. `sweep_animation_reveal.js` supplies per-site scales for
beads/slabs/atoms/bonds and cached triangle draw ordering for curved tubes/surfaces.
Existing material stays visible. Surface batches retain per-vertex nucleotide IDs;
no molecular coordinates, topology or feature timings are changed by the reveal.
The same seek path drives preview and frame-by-frame video capture.
Rigid cluster motion starts from the historical pair's source shape; unchanged
clusters no longer suppress deformation/position interpolation.

An already-prepared preview can supply CG states to export/replay while the source
Design and geometry objects remain unchanged. Explicit Stop releases the cache.
Background hydration of omitted snapshot bodies does not invalidate preparation;
actual history/model edits still do. The editable topology, feature cursor, and
undo stack are not animation state.
Ordinary snapshot replay now restores all three nanoparticle collections too;
the earlier generator-only restoration left future cargo present during scrubs.

Atomistic batch requests can opt into historical atom/bond metadata with
`include_topology`. Matching identities interpolate; changed atom identities
switch to the appropriate historical model instead of lerping unrelated serials.
`feature_atomistic_display.js` owns that choice. Topology changes in the heavy
representations are discrete model changes, not chemical reaction simulations.

WebM export in both Animations and Photo uses `encode_webm.js` with Mediabunny /
WebCodecs, explicit presentation timestamps, per-frame readiness, and encoder
backpressure. Wall-clock rendering delays cannot stretch or truncate the movie.
Unsupported WebCodecs produces an actionable error; GIF remains available.
An export whose FPS cannot sample every intermediate operation is rejected with
a minimum FPS / longer-transition instruction rather than silently skipping it.
The regular exporter composites the canvas over its visible CSS background.
API references: [WebCodecs](https://www.w3.org/TR/webcodecs/) and
[Mediabunny output](https://mediabunny.dev/guide/writing-media-files).

Verification evidence is retained under `.development-artifacts/build-animation/`;
the final headed Voltron check passed (1.3m): forward/reverse/hold pixels,
historical particle visibility, unchanged editable cursor, preview bake reuse,
132-frame/11s Animations WebM and 22-frame/11s Photo WebM. Actual downloads
were decoded and inspected. Source SHA-256 stayed unchanged; test copies were
removed. The repeatable headed browser workflow is
`frontend/e2e/animation_build_sequence.spec.js`. It uses an isolated Voltron copy,
visits forward/reverse/held states, downloads WebM, and decodes the actual file
with ffmpeg/ffprobe. Source workspace designs are not modified.

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
