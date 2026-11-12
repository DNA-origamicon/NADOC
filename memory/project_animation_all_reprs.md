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

## Compiled offline presentations (2026-11-11)

`Pre-compile` and `Load` share a row (8px gap) below `Start Presentation`.
Matching film icons mark compilation of the full presentation or one trajectory
keyframe. Video size has an explicitly themed select. Compilation renders one WebM
per selected keyframe, exact entry/exit images, captions and companions into an
import-free HTML player. Play/pause, skip, jump, replay, held endpoints and fullscreen
work without any server or trajectory files. This is not an authored molecular part.

`scene/compile_presentation.js` prepares the schedule once and reuses regular export
readiness/compositing/encoding. Individual previews prepare preceding context but
omit later keyframes and encode only the chosen clip; their result does not replace
the full presentation. 720p/1080p, 1–60 FPS, minimum one-frame holds, 256 MiB video cap.
Renderer and player flags restore on success/error/cancel. Entry images reuse the
first sampled frame; separate exact endpoints avoid ending short of the authored pose.
Native WebCodecs prefers supported hardware VP9/VP8, falls back automatically, and
retains quality timing/bounded queuing. WebGL renders the shared scene serially;
no multi-GPU scheduling or large-origami performance benchmark is claimed.

Completed files save to `NADOC_WORKSPACE/compiled_presentations` (default
`workspace/compiled_presentations`). `routes_presentations.py` streams bounded uploads
into temporary files; `core/presentation_library.py` publishes immutable SHA-256-named
HTML and metadata, lists only complete records, and rejects path/symlink escapes.
Downloads are attachments with sandbox/nosniff headers, never app-origin execution.
`Open compiled presentation…` now uses a single library modal outside sidebar mirrors,
not an OS file picker. It lists server entries and this origin's IndexedDB copies.
Opening fetches all videos before playback, validates data-only metadata, and rebuilds
the trusted sandboxed player. Browser persistence is requested; storage failure is
reported without blocking in-tab playback. No arbitrary Downloads-folder access or
remote-machine guess is used. Downloaded standalone HTML remains the independent
backup: local browser storage does not install the NADOC app shell for offline boot.

`Play compiled` embeds video above the canvas. `Inspect in 3D` pauses it, maps the
encoded sample or exact held endpoint into the saved animation schedule, restores
initial camera/joints, and waits for the existing live pipeline. Orbit/zoom and normal
app controls then remain available. Return restores video position and play/pause state.
Cancel, unavailable frames, source changes and obsolete completions leave video usable.
An editor action can take scene ownership without being stopped on return. Live 3D
needs the matching source and reachable/cached data; the HTML carries a source fingerprint,
not molecular data. Fullscreen inspection reveals the normal app and can return fullscreen.

Browser verification covers selected synthetic NAMD frames with ions/box and a read-only
existing example. A second browser profile downloads a server presentation, caches it,
then opens/plays with networking disabled; standalone HTML also makes zero HTTP requests.
Server tests cover complete publication, deduplication, bounded uploads, cleanup and
path protection. Browser files/reports/workspaces and build output use failure-safe scratch.
Library checks: 4 API tests and 2 browser workflows passed; 10,347 frontend assertions
passed / 1 skipped, but the final native-placement audit failed. Build/lint passed.
Follow-up fixed omitted display-field contracts and leaking test mocks. Eight native
incidents were individually reviewed/acknowledged; placement gate is clear. 380 focused
checks, 78 metadata checks and two offline browser workflows passed. The intermediate
FAST rerun had 20,697 passes/45 failures; 44 schema failures subsequently passed focused
checks. One experimental CPD preview-contract failure and deferred FULL-suite debt remain.
See ISSUE-186 and `.development-artifacts/native-review-20261111/`.
`main.js` LOC delta: 0.

## Local presentation mode (2026-11-10)

The parts editor's Animations tab has a red **Start Presentation** button above
Camera Poses. `ui/animation_presentation.js` owns local fullscreen and manual
navigation; it reuses the existing player's preparation, seek and settle paths.
Each keyframe plays its transition and hold, then waits with its caption visible. Click, Space, Right/Down
or PageDown advances, interrupting any remaining transition/hold and starting the next
keyframe. Forward during the final keyframe exits immediately. Right-click, Left/Up,
PageUp or Backspace jumps directly to the previous keyframe endpoint and waits
without replaying its transition. Navigation generations discard obsolete async
frame completions, including rapid input while scene preparation settles. Esc,
native fullscreen exit, cancellation/errors, document teardown, or completion of
the last keyframe restores the editor. Loop/bounce and disabled-pose settings are
restored; saved animation timing is unchanged. If native fullscreen is unavailable,
the canvas fills the browser viewport. Assemblies and assembly part contexts are
excluded by the requested initial scope. This does not create a shared presentation.

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

November 10, 2026: captured/updated camera poses store a small JPEG thumbnail of
the rendered 3D canvas. Pose rows and the keyframe pose listbox display it on
hover/focus; legacy poses need Capture/Update to acquire an image. V, pose-list Capture
and keyframe Capture share the saved-pose snapshot/name/thumbnail helper. Keyframe Capture
creates a normal Pose N and selects its ID only, preserving other settings. Keyframe cards
collapse while keeping selection, play/pause and delete available. Trajectory scrubbers
sit below titles with bounded first/play-pause/stop/last controls underneath; collapsed
play shares that state. Title selection seeks to the endpoint. Whole-animation controls
also sit below their scrubber. Per-keyframe `Smooth playback` (default off) reuses Simulation
interpolation, bounded neighbors and stage breaks; video compilation awaits the same subframes. Annotation checkboxes select all/none/a subset of the
right-sidebar entries (now renameable/collapsible). Null selection retains legacy
visibility; explicit IDs transiently override it without changing working notes.

On `stopped` or `finished` events: `_atomDataCache = null` + re-fetch atomistic, `_surfaceDataCache = null` + re-fetch surface. Restores strand colours and correct deformed state after animation ends.

**Why:** Pre-baked states leave atom positions and surface mesh in the last lerped frame. Re-fetching from the live backend restores the correct deformed geometry including strand colours.

<a id="automatic-trajectory-preparation-2026-09-04"></a>
- [Automatic trajectory preparation (2026-09-04)](details/project_animation_all_reprs/02-automatic-trajectory-preparation-2026-09-04.md#automatic-trajectory-preparation-2026-09-04)
