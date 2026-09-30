# Representation loading frame delivery — implementation and finer profile

Final-state note: shadow reuse described below was subsequently removed. The
original lighting and shadow pass are restored; see the
[motion-regression follow-up](vr_motion_regression_20260929.md). Measurements below
record their stated historical variants, not a fresh acceptance run of the final build.

Follow-up to [the original diagnosis](vr_loading_stalls_20260929.md), ISSUE-50.
The previous feature commit remains `067a910d`; these fixes are subsequent work.
Frontend `main.js` delta: zero. Molecular geometry and saved designs are unchanged.

## Two distinct causes, measured separately

The original final-handoff stalls were 226 ms for Stick, 393 ms for Ball & Stick
and 806 ms for Surface. CPU preparation and GL staging ran synchronously in
`pollVisualizationSnapshot()` before the old frame timer began.

Finer profiling reproduced the earlier hitch near 50% and also later in export.
It was **`publishPresenterPose()`**, which opened, wrote, closed and renamed an
avatar-state file every 50 ms on the XR thread, even when sharing was disabled.
One run recorded a 335.5 ms publication block; its 40–50% maximum frame gap was
229.2 ms and whole-load maximum 342.1 ms. GPU draw timing alone did not expose
this post-submission work. The blocking primitive within the filesystem call
sequence was not separately traced; this is measured publication wall time,
not evidence of a specific disk/driver fault.

In the first corrected Surface run, a background pose write still took 105.6 ms,
but 40–50% frame gaps stayed below 12.4 ms. Activation stayed below 14.4 ms.
Whole-load p99 was 11.62 ms. SteamVR reported one dropped frame rather than 180
in the preceding reproduction. The remaining 30.89 ms outlier was in the
XR-end/release interval (22.28 ms there), not avatar writing or geometry upload.
These are different trials, not a controlled identical operating-system load.

## Implemented pipeline and guards

- The existing parsing worker also prepares immutable static geometry, bounds
  and semantic indexes. Main-thread batches apply color and diagnostic object IDs
  to at most 256 primitives at a time.
- Uploading has a 1 ms CPU timeslice and 256 KiB byte ceiling per frame. The
  pending buffers are separate from displayed buffers. A zero-timeout GL fence
  poll gates atomic activation; no `glFinish` or blocking fence wait is used.
  An individual driver allocation can still exceed the timeslice, so slow
  allocation/upload calls are recorded separately rather than called bounded
  merely because the loop has a timer.
- Completed GPU buffers are rebound directly on warm switches. Selective loads
  invalidate only affected representations. Inactive resident geometry has a
  256 MiB cache budget, in addition to the active view and one pending view.
- Inactive CPU sources have a conservative 512 MiB cache budget. Full, the
  active source and sources used by view volumes are protected. Eviction moves
  raw geometry and prepared indexes to the CPU disposer; later selection reloads
  them. This bounds retained inactive geometry, not total process RSS or an
  individual representation.
- The startup shell now receives the prepared Full representation through the
  same staged path instead of constructing a second renderer and uploading Full
  synchronously. Placeholder authoring availability is cleared before installing
  actual model availability.
- A head-level loading panel reports export, CPU preparation, upload and
  activation. Three over-budget frames within one second of loading enable the simple
  loading scene; controllers and menus keep their normal interaction path. The
  budget uses the fastest observed positive runtime period: SteamVR can report
  22/33 ms predicted periods while reprojecting, which must not redefine a
  healthy frame on a 90 Hz headset.
- Avatar publication uses one writer with one latest pending value. Disk work
  happens outside its queue lock; superseded poses are coalesced. Ordered edit
  events are not sent through this coalescing channel. Failures and maximum write
  latency are exposed in ScryWrite `loading_diagnostics`.
- Cancelled parse results are retired on one CPU disposer, with backpressure,
  rather than freeing large scenes on the frame thread. Superseding a pending
  upload preserves the last active representation.
- Diagnostic object IDs use small hash buckets and segmented identity storage.
  This removes 14–65 ms rehash/growth pauses revealed after the larger style
  stall was removed. Scene copies discard borrowed prepared pointers; moves
  preserve their ownership relationship.
- The first matrix exposed a separate dense Ball & Stick steady-state GPU cost
  of 12–13 ms. All representations now reuse their shadow map while geometry,
  model transform and light remain unchanged within a subtexel angular tolerance.
  Geometry updates, activation, trajectories and meaningful light/model movement
  invalidate it. The shader, shadow resolution, primitive radius and color are
  unchanged; this does not disable atomistic shadows.

No compositor priority or workstation setting was changed. The confirmed early
cause was CPU/file I/O, and the machine does not expose the priority/performance
extensions discussed in the research. The implementation follows the worker,
timeslice and nonblocking-fence approaches linked in the original diagnosis.

## Repeatable measurements

Debug → VR Tours & Tests → **Representation loading frame delivery** runs the
real browser launch and controller tour, retains native timing, and samples
SteamVR compositor timing as a background application. It never submits images
or calls `WaitGetPoses`. Its optional Python `openvr` binding is supplied through
`uv run --with openvr`; the normal viewer has no new runtime dependency.

The maintained tools are `loading_performance_tour`, `loading_profile`, and
`compositor_timing` under `tools/vr_workflows`. Application traces cover work both
before and inside `renderFrame`, with GPU query timestamps for correlation.
Hot-path timing output uses a bounded asynchronous FIFO so profiling does not
reintroduce synchronous file writes. Explicit overflow invalidates the measured
interval; retained logs are copied after viewer shutdown. Event polling is split
into GLFW, XR and live-control phases.
Compositor drop/reprojection counts are distinct from application wall-time gaps.
Compositor membership at interval boundaries has up to 100 ms polling uncertainty.

The regression gate uses runtime cadence: p99 ≤1.2 periods, maximum ≤3 periods,
and compositor drop rate ≤0.1%. These engineering limits catch large freezes;
they are not a promise of zero dropped frames or physical comfort. Very short
warm switches have functional checks but too few frames for percentile inference.
Captures occur outside measured loading intervals. Full semantic observations can
consume 5–10 ms on the XR loop. Progress polling now defaults to 100 ms between
observations (previous traces used 40 ms); controller motion remains at 20 Hz.
The final trace writer records every completed outer frame. Earlier trials
omitted frames with render-phase CPU <5 ms and total gap <25 ms; their percentile
estimates are from that retained subset, with all larger freezes still recorded.

## Retained attempts and validation

Evidence lives in `.development-artifacts/vr-loading-fixes/`.

- `run-surface`: launch-readiness failure, before controller input; the harness
  now waits for actual runtime focus, without changing motion deadlines.
- `run-surface-ready`: staging worked but object-ID table growth caused hitches.
- `run-surface-sharded`: activation improved; post-submission hitches persisted.
- `run-surface-postframe`: isolated blocking avatar publication.
- `run-surface-async-pose`: caught startup placeholder availability leaking into
  the installed model; visible-pixel assertion failed despite reaching 100%.
- `run-surface-async-fixed`: verified background write isolation and actual
  Surface pixels in both submitted eyes.
- `run-all-representations`: retained three controller deadline failures at
  151–179 ms while Ball & Stick exceeded the steady-state GPU frame budget.
  No threshold was relaxed; this motivated shared shadow-map reuse.

- `run-final-matrix`: all eleven representations completed, but the next
  controller profile failed its unchanged 150 ms reach deadline at 166 ms.
  Retained CPU geometry coincided with available memory falling to about 2.4 GiB,
  nearly full swap and memory pressure. Background pose writes reached 2.5 s.
  This motivated the inactive CPU cache budget and asynchronous trace output.

Real GL tests cover upload bytes, radii/colors/IDs, cancellation, activation,
resident reuse and startup availability. A blocked-writer test proves publication
does not wait for disk and coalesces superseded poses. Shadow tests cover geometry,
light and model invalidation; the existing occluder-removal control checks actual
cast shadows. Profile tests reject a long frame gap even when the old draw-only
timer claims success, and reject compositor drops with healthy application timing.
The application smoke suite passed 23/23. The focused Python check passed 53/53.

`run-bounded-final` completed all eleven styles, including a warm Cylinder return,
with visible geometry in both eyes. Whole-load maximums were 24.85 ms Ball &
Stick, 11.59 ms VDW, 14.65 ms Stick, 22.56 ms Surface, 11.77 ms Hull,
12.99 ms Cylinders, 12.20 ms mrDNA coarse, 12.70 ms mrDNA fine and 13.88 ms
oxDNA. Immediate Full/Beads/warm Cylinder switches had insufficient samples for
percentile claims. Ball & Stick recorded two compositor drops in 2,870 samples;
all other measured loads recorded zero. Surface still failed p99 (22.33 ms),
with 96 reprojection-flagged samples, despite removing the long freezes.

The second motion profile again failed its scroll reach deadline (151 ms).
This is retained as a failed attempt, not a complete four-profile pass. The
bridge's frame predicate used a 20 ms retry sleep against 50 ms motion samples;
frame-specific polling now uses 1 ms, while the predicate, input sequence, motion
paths and 150 ms deadline remain unchanged. The loading guard now recognizes
clustered misses within one second, including nonconsecutive ones. The follow-up `run-guard-profiles` completed `steady_fast`, `steady_deliberate`
and `variable_fast`; `variable_deliberate` failed its scroll reach at 162 ms.
All completed loading intervals passed the timing gates, but this is explicitly
**not a complete four-profile pass**. Surface whole-load p99 was 11.65/11.58/11.61 ms;
maximum was 22.36/12.55/13.63 ms; compositor drops were 1/0/0. The lightweight
guard was not activated in these samples, so improvement cannot be attributed
to that guard (the preceding displayed model and system conditions also differed). Inactive source retirement was observed; RSS still
reached about 4.5 GiB, so no total-memory cap is claimed.

## Scope and remaining limits

The staged fast path is for immutable natural representations. Active coordinate
visualizations, tool deformations, expansion interpolation and selection glow
retain their existing dynamic rendering path; this work does not establish a
frame-time guarantee for those paths or mixed-representation view volumes.
Shadow reuse helps stable lighting; continuous model/head motion can require
fresh shadow draws. Submitted stereo evidence does not establish through-lens
comfort. MV-VR-LOADING-COMFORT remains the physical-headset review.

## Complete-frame diagnostic follow-up

`run-final-cadence` recorded every completed frame and reduced full-state progress
polling to 100 ms between observations; controller motion was unchanged. Stick
p99/max were 12.01/22.43 ms. Surface p99/max were 22.34/22.58 ms, with 92
reprojection flags and two compositor drops among 5,784 samples. This failed the
Surface p99 gate and showed that the loading guard had never activated.

The runtime log contained predicted periods of 11.11, 22.22 and 33.33 ms. The
guard had compared a half-rate frame against that temporarily relaxed predicted
period. Both guard and regression analyzer now retain the fastest observed
positive period; the analyzer scopes the appended log to the current viewer.
A regression explicitly checks that a 22 ms predicted period cannot relax the
previously observed 11 ms target. This is a software guard correction, not a
SteamVR setting change. The final guarded result follows below.

## Final guarded result and open boundary

`run-nominal-guard` passed the browser/controller/submitted-stereo functional check
for Stick → Surface. The guard activated in 182/187 Stick and 494/531 Surface
progress observations and cleared at readiness. This verifies the runtime-period
fix through the actual loading path, beyond the unit regression.

| Measured interval | Stick | Surface |
| --- | ---: | ---: |
| Whole-load p99 | 11.77 ms | 11.80 ms |
| Whole-load maximum | 22.40 ms | 73.87 ms |
| 40–50% maximum | 11.88 ms | 22.67 ms |
| Activation maximum | 12.97 ms | 14.01 ms |
| Compositor drops / samples | 1 / 2,058 | 12 / 5,963 |

Surface **still fails** maximum-frame and compositor-drop gates. At 75%, the
73.87 ms frame contained 65.53 ms in the XR-end/release trace. Nearby SteamVR
samples recorded 62.13 ms `m_flWaitForPresentCpuMs`, while total render GPU time
stayed below 5.87 ms and compositor GPU below 0.16 ms. The adjacent host sample
had about 5.3 GiB available and zero 10-second memory pressure. This correlates
the residual with runtime/presentation waiting; it does not identify the
underlying SteamVR/driver cause. Raw correlation is retained in
`residual-xr-submission.json`. No GPU-priority or runtime settings were changed.

The original 226–806 ms preparation/upload blocks and 335 ms avatar write stall
are addressed, but ISSUE-50 remains OPEN for this residual frame-delivery failure,
the fourth motion-profile deadline failure, and physical headset comfort.
Do not label the final timing run or the complete four-profile matrix green.

Validation: native build and five focused native checks passed (including real GL,
blocked writer, shadow invalidation, clustered-miss and reprojection-period guards);
53 focused Python tests passed; application smoke passed 23/23. Final syntax and
whitespace checks passed. Twelve retained browser attempts have cleanup evidence:
private source/cache removed, original unchanged, no owned viewer/IPC remaining.
Smoke ports 8001/5174 are closed; its private credential and workspace artifacts
are absent. The user's backend/frontend and documents remain intact. Changes are
local after the earlier `067a910d` push.
