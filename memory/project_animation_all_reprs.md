---
name: Animation system — all representations
description: CG beads, atomistic, and molecular surface all participate in the animation pre-bake + lerp pipeline
type: project
originSessionId: 7e08699f-f784-4b54-ac56-e0a843377a6f
---

# Animation across representations

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

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

<a id="shared-presentation-playback-2026-09-30"></a>
- [Shared presentation playback (2026-09-30)](details/project_animation_all_reprs/01-shared-presentation-playback-2026-09-30.md#shared-presentation-playback-2026-09-30)

<a id="pre-bake-endpoints-called-once-before-playback-starts"></a>
- [Pre-bake endpoints (called once before playback starts)](details/project_animation_all_reprs/01-shared-presentation-playback-2026-09-30.md#pre-bake-endpoints-called-once-before-playback-starts)

<a id="per-frame-lerp-inside-_applyat"></a>
- [Per-frame lerp (inside `_applyAt`)](details/project_animation_all_reprs/01-shared-presentation-playback-2026-09-30.md#per-frame-lerp-inside-_applyat)

<a id="surface-topology-aware-lerp"></a>
- [Surface topology-aware lerp](details/project_animation_all_reprs/01-shared-presentation-playback-2026-09-30.md#surface-topology-aware-lerp)

<a id="apply_deformations_to_atoms"></a>
- [`apply_deformations_to_atoms`](details/project_animation_all_reprs/01-shared-presentation-playback-2026-09-30.md#apply_deformations_to_atoms)

## Stop/finish cleanup

On `stopped` or `finished` events: `_atomDataCache = null` + re-fetch atomistic, `_surfaceDataCache = null` + re-fetch surface. Restores strand colours and correct deformed state after animation ends.

**Why:** Pre-baked states leave atom positions and surface mesh in the last lerped frame. Re-fetching from the live backend restores the correct deformed geometry including strand colours.

<a id="automatic-trajectory-preparation-2026-09-04"></a>
- [Automatic trajectory preparation (2026-09-04)](details/project_animation_all_reprs/02-automatic-trajectory-preparation-2026-09-04.md#automatic-trajectory-preparation-2026-09-04)
