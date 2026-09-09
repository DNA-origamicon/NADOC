# Animation trajectory loading audit — 2026-09-04

## Findings

The sidebar's initial trajectory request loaded only metadata (frame count and stage
markers). Coordinate download and representation preparation were explicitly triggered
by the row's Preview button. Bottom Play did have its own preparation path, but several
holes made its results depend on earlier preview state:

- The paused-schedule signature omitted trajectory job, engine, scope, stride and
  start/end. Editing those fields could resume the old schedule.
- Failed coordinate loads and failed heavy reconstruction could silently become
  zero-frame/skipped segments instead of a visible playback failure.
- Only the first job on each controller received a prepared frame count. Later jobs
  could never reach the swap path because the player skipped zero-frame segments.
- A swap displayed its old frame until asynchronous preparation completed. The playback
  clock kept advancing; companion ions/box preparation also ran independently of that
  clock. Export awaited companions, but did not previously await trajectory swaps.
- Frame counts were keyed only by job, so different resolutions of one job shared a
  frame space even though their indices referred to different simulation times.

## Changes

`trajectory_downloads.js` holds coordinate downloads for the active animation, keyed
by job/alignment/scope/stride. It joins concurrent identical requests, retains completed
payloads, retries failures, evicts inactive requests and cancels pending transfers.
Different resolutions of one job are serialized to avoid competing for NAMD's single
analysis-worker slot. The existing display controller owns this cache; there is no
second trajectory API/representation pipeline.

The sidebar starts those downloads while rendering or changing trajectory keyframes,
without activating the display or moving the model. Each row reports download status.
Preview is optional authoring scrubbing. Bottom Play joins pending downloads, finishes
representation preparation, and reports failures rather than playing missing frames.
The dirty signature includes all trajectory fields.

Preparation records frame counts per job/resolution, including later jobs sharing a
controller. Switching jobs/resolutions settles the requested frame before playback
advances. The clock pauses for asynchronous preparation, including ion/box companions.
Both exporters already call `player.settleFrame`, and now await trajectory swaps too.
Cancellation and stale-completion guards prevent an abandoned load from taking over a
new playback session. Explicit trajectory refresh still fetches newly written frames.

Heavy atomistic/surface data remains subject to the existing memory budget. Background
loading now prepares coordinates and heavy display frames in off-screen sessions.
Play joins unfinished work and adopts completed per-job caches. Companion setup or
uncached representation changes can still need preparation at a job boundary. These changes do not make unbounded atomistic trajectories
resident in GPU/browser memory.

## Verification

Browser regression uses the real sidebar, player and display controller with isolated
in-memory APIs: background load does not move the model; bottom Play waits for that
load, renders frames 1/2/3 without Preview, downloads once, and rebuilds after a range-only
edit. It creates no jobs, designs, session files or exported videos. Playwright cleanup
was verified; no test artifacts remained.

Focused tests cover single-flight downloads, resolution isolation, refresh/cancellation,
strict preparation failures, later same-engine jobs, per-resolution frame counts,
NAMD adapter progress, the player, and both export paths. This is client-side/browser
verification with synthetic trajectory data, not a new live NAMD simulation or a
full-size molecular video export.

Initial coordinate-loading fix results: **249 focused tests passed**; **1 browser regression passed**.
`just test-frontend`: **6,150 passed, 3 failed** (375 passing files). The three
failures also existed before this animation change: accessibility layout contract,
extra-base alpha-visibility rendering contract, and JSON GET coalescing. The NAMD
adapter progress regression was corrected and passes in the focused and full suites.
`git diff --check` passed. The later non-modal change only updates two comment lines
in `main.js` (LOC delta 0).

## Non-modal display-frame preparation (2026-09-04)

The remaining delay came from warming coordinates alone: Play still reconstructed
atomistic/surface frames while the animation panel opened a blocking operation dialog.
The controller now owns `trajectory_preparation_cache.js`, with off-screen sessions
using the existing reconstruction pipeline. Sessions have no scene renderers; completed
buffers are adopted by the live controller. The active animation retains its jobs,
including multiple jobs on one engine. Keys include resolution, representation and
surface settings. Heavy requests share the foreground queue; processing yields between
chunks. Existing memory limits still apply and capped detail is explicitly reported.

Play preparation uses `animation_preparation_progress.js`: an inline, accessible
progress bar, stage/counts, elapsed time and Cancel. Keyframe rows independently show
background preparation and readiness. Backend parsing progress is polled while loading.
Cancel immediately releases the waiting UI, invalidates unfinished work, and preserves
completed caches. An already running backend reconstruction request may finish, but
its cancelled result cannot become a ready cache. Ready requires every planned frame.

Professional precedents consulted:

- [Final Cut Pro background tasks](https://support.apple.com/en-euro/guide/final-cut-pro/ver64e71609/mac): background work with completion percentages and task controls.
- [After Effects previews](https://helpx.adobe.com/mena_en/after-effects/desktop/view-and-preview/preview-video-and-audio/previewing.html): reuse cached previews and indicate cached frames.
- [ParaView parallel visualization](https://docs.paraview.org/en/latest/ReferenceManual/parallelDataVisualization.html): interactive versus still rendering, with reduced detail during interaction.
- [NN/g waits and interruptions](https://www.nngroup.com/articles/designing-for-waits-and-interruptions/): communicate progress and let people continue other work during long operations.

These informed the non-modal cache/progress design; this implementation does not add a
new molecular reconstruction algorithm or change saved geometry/topology.

The full frontend check after this follow-up reported **6,153 passing / 4 failing**.
Three failures are the established accessibility, extra-base visibility and GET
coalescing failures. The fourth was the existing oxDNA panel poll timing assertion
under concurrent heavyweight verification; its entire **127-test file passed** on
isolated rerun. The preceding full run had **6,154 passing / the same 3 established
failures**. Focused final cache/keyframe/display checks passed **184 tests**; progress
UI and NAMD adapter checks also passed in the full suite. `just lint` passed.

`just smoke`: **22 passed, 1 failed**. The assembly-exit harness failed before entering
an assembly: `/design` for its `e2e-asm-exit` document returned 404 instead of 200.
The temporary workspace fixtures and Playwright output were removed and checked.

### Real VoltronCoreScad check

`animation_voltron_preparation.spec.js` passed against the saved animation's two
actual trajectories (51 and 151 frames), using private copies of jobs `35f1a833c203`
and `b0ce0d0aa40b`. Rows showed backend frame-processing counts and both reached
“Trajectory preview frames ready.” Switching to VDW then pressing bottom Play showed
inline preparation, with no operation modal. The Help menu remained clickable, and
Cancel re-enabled Play. No browser errors occurred. Final run: **1 passed in 2.9 min**.

The full visible-model run confirmed coordinate readiness, but software WebGL drawing
was taking seconds per frame. The final background UX check hides scene drawing to
isolate preparation from that rasterization cost. It exercises the real application,
real trajectory API and atomistic preparation; it does not establish full-model GPU
playback FPS or completion of every atomistic frame (that preparation is cancelled).
Off-screen atomistic completion/adoption without rebuilding is covered by the display
controller test. Surface completion at Voltron scale was not separately benchmarked.

Temporary design/job copies and all Playwright artifacts were removed and their absence
verified. Original design, job metadata and job design snapshots retained their checksums.

## Ordered preparation and sequence readiness (2026-09-04)

Trajectory preparation now queues the download and off-screen frame build together in
first-keyframe order across oxDNA and NAMD controllers. Pending work follows reordered
keyframes; currently running work is allowed to finish. Duplicate job/resolution requests
join the same cache entry. Ready earlier jobs remain usable while later jobs prepare;
metadata supplies later frame counts, and playback waits at an unprepared job boundary.

The bottom scrubber has a duration-weighted readiness rail with one labeled percentage
per keyframe. Green marks prepared playback cache coverage for the selected frame range,
including reverse ranges; parsing/download counts are shown separately and never count
as ready frames. Memory-limited detail caches carry an asterisk and explanatory tooltip.
Range/duration edits refresh the rail without rebuilding row controls. Preparation stays
off-screen and uses the existing display-only pipeline.

Visible job dropdowns bypass the background performance-timing idle gate. Metadata and
preparation subscriptions start independently of job-list lookup. Background idle waits
also have a two-second deadline: an orphaned POST /design/import timing record can no
longer leave every row at Loading jobs indefinitely. Expiry does not cancel the operation.

Verification: 196 focused tests passed. An isolated browser fixture using the real
panel, player, and display controllers verified A ready/playing while B loads and C is
queued, followed by B/C readiness in order; the existing cold-Play test also passed.
No saved designs, jobs, exports, or browser artifacts remain from those checks. This
check uses small synthetic trajectories; the earlier Voltron check remains the large
model evidence and was not repeated here. main.js LOC delta for this follow-up: 0.

Final follow-up gates: `just test-frontend` **6,163 passed / 3 failed**, the same
accessibility, extra-base alpha visibility, and JSON coalescing failures listed above.
`just smoke`: **22 passed / 1 failed**; assembly fixture initialization again returned
404 for document `e2e-asm-exit` before exercising assembly teardown. A separate mrDNA
job-status save race was logged by the smoke backend; the smoke assertions otherwise
passed. `just lint` and `git diff --check` passed. The duration-refresh DOM assertion
also passed after the full run. Workspace/scratch `__e2e__` inventory and browser report
paths were empty after cleanup. No live NADOC server was stopped or restarted.

## Live intermediate segment percentages (2026-09-05)

The initial rail exposed preparation coverage as its only visible percentage, leaving
coarse-grained trajectories at 0% until the atomic coordinate payload was decoded.
Parser/transfer progress arrived but appeared only in the tooltip. Segments now show
measured per-stage loading percentages and a blue fill while parsing/transferring/decoding,
then green prepared-cache coverage during frame building and on completion. Loading
is explicitly labeled so transfer progress is not mistaken for playable frames. No
invented elapsed-time progress is used; stages without a total remain unquantified.
The parser poll stops when transfer begins to prevent stale counters overriding it.

Live-percentage validation: 58 focused tests passed; the browser sequence regression
explicitly observed 25%, 50%, and 75% while the coordinate request remained pending.
The final DOM check also verifies 100% loading remains distinct from ready coverage.
`just test-frontend`: 6,164 passed / the same 3 pre-existing failures.
`just smoke`: all 23 passed. Lint and diff whitespace checks passed. Test workspace
files and browser reports were removed by failure-safe cleanup; main.js LOC delta 0.
