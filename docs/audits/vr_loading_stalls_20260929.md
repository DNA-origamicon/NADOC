# VR representation loading stalls — diagnosis, 2026-09-29

This is the retained pre-fix diagnosis. See the subsequent
[implementation and finer profile](vr_loading_frame_delivery_20260929.md).

Previous VR changes were committed and pushed to `origin/master` as
`067a910d2221db539af0e6a733eaa558fc256a93`. This follow-up adds local diagnostics,
not a performance fix. ISSUE-50 remains open. Frontend `main.js` delta: zero.

## Reproduction and measured limits

Three real browser launches used isolated copies of the user's 24HB document,
the real desktop acknowledgement path and ScryWrite controller selection with
the `steady_fast` profile. All reached 100% and rendered the selected model in
both submitted eyes. No screenshot/readback was requested during the measured
loading interval. This is application/stereo evidence, not through-lens comfort
or a count of compositor-dropped frames. These are single trials, not repeated
cold-reboot benchmarks or a complete representation matrix.

The runtime reported 90 Hz (11.11 ms per frame). CPU wall-time measurements:

| Representation | Blocking style application | Equivalent 90 Hz intervals | Largest frame gap at displayed 40–50% |
| --- | ---: | ---: | ---: |
| Stick | 226.1 ms | 20.3 | 11.5 ms |
| Ball & Stick | 393.3 ms | 35.4 | 11.6 ms |
| Surface | 805.8 ms | 72.5 | 111.9 ms |

The large style blocks occurred at 99%. End-to-end maximum observed application
frame gaps were 235.7, 395.2 and 807.8 ms respectively. These equivalent intervals
are **not measured missed scanouts**: reprojection can continue while the app stalls.

Surface also reproduces an earlier hitch at 49.198%: 107.0 ms in the `frame`
phase, 111.9 ms between frame completions. Other gaps cluster nearby. This phase
includes XR pacing, rendering, submission and mirror work. The available trace
does not distinguish scheduling, GPU contention, driver synchronization or
runtime pacing there. The 40–50% Surface p99 observed gap was 22.5 ms. Do not
claim the later style-application cause explains this earlier burst.

## Identified blocking path and measurement gap

`eventLoop()` calls `pollVisualizationSnapshot()` before `renderFrame()`.
The desktop acknowledgement calls `GlScene::setVisualization()` / `setStyle()`
on that same thread. Existing `phase=frame_timing` starts within `renderFrame`,
omits this work and excludes `xrWaitFrame`; therefore
`scene_p95_within_budget=true` does not establish continuous VR frame delivery.

The acknowledgements were only 46–50 bytes; parsing took less than 0.02 ms.
The expensive operation was applying geometry:

| Representation | Instances | Preparation | Remaining instance construction/upload |
| --- | --- | ---: | ---: |
| Stick | 154,917 cylinders | 61.4 ms | 164.3 ms |
| Ball & Stick | 137,721 spheres + 154,917 cylinders | 106.8 ms | 286.0 ms |
| Surface | 852,180 triangle/box records + 3 axis cylinders | 250.9 ms | 550.4 ms |

The existing `upload_ms` label includes CPU instance generation, transforms,
bounds and GL calls. It is **not GPU timer-query duration**. GPU cache capture
also follows that timing interval. Async file parsing alone does not cover these
main-thread costs.

Additional code findings: selective `installRepresentation()` clears all
representation buffer/source-index caches. `RepresentationBuffers` restores
cached geometry by allocating/copying GL buffers rather than simply binding
resident storage. These are avoidable work candidates, not individually measured
causes of the earlier 49% hitch.

Host monitoring retained at least 5.1 GiB available RAM in these runs and only
small swap-page deltas. Full configured swap is not evidence that paging caused
these stalls. Half-second GPU samples cannot exclude brief contention or driver
synchronization; use GPU/compositor timings before attributing the 49% burst.

## Researched fix order

1. **Prepare immutable CPU geometry on a worker.** Move indexes, ownership,
   transforms, instance arrays and bounds out of the XR frame thread. Bound
   concurrency and retained memory; support cancellation/supersession. Keep
   showing the previous representation until the new one is ready. Never wait
   for a worker from the frame loop. OpenXR permits pipelining but requires
   correct ordering and synchronization of frame calls; preserve a continuously
   serviced XR loop. [Khronos frame submission](https://github.com/KhronosGroup/OpenXR-Guide/blob/main/chapters/frame_submission.md).
2. **Budget GPU staging per frame.** Upload chunks to separate pending buffers,
   with both byte and CPU-time limits. Start experiments around 1–2 ms only when
   measured frame margin permits; this is a tuning proposal, not an established
   safe budget. Poll completion fences without blocking and swap buffer handles
   only when complete. Reuse resident buffers instead of copying the cache on
   every switch; invalidate only affected entries and bound cache memory.
   Unity's asynchronous upload pipeline uses a bounded staging ring and a
   per-frame upload timeslice. [Unity's implementation](https://unity.com/blog/engine-platform/understanding-the-async-upload-pipeline).
   OpenGL streaming can stall implicitly when storage is still in use. Multiple
   buffers or persistent mapped ranges with proper fences avoid overwriting
   in-flight data. Do not substitute `glFinish` or unsafe unsynchronized writes.
   [Khronos buffer streaming](https://wikis.khronos.org/opengl/Buffer_Object_Streaming).
3. **Provide a loading guard that survives expensive work.** Maintain the XR
   loop with a simple loading scene; a compositor layer can help keep loading UI
   stable, but does not itself unblock NADOC or animate progress. If an operation
   truly cannot be split, fade before it starts and restore after it finishes;
   this is a fallback, not permission for recurring stalls. A popup or watchdog
   on the blocked thread cannot protect the user.
   [Google VR's head-tracking guidance](https://developers.google.com/vr/develop/unity/guides/maintain-head-tracking)
   describes splitting work and pre-emptive fades; the platform is archived but
   the main-thread failure mode applies.
4. **Measure contention before changing priority.** Consider limiting export
   workers and deferring redundant desktop uploads while VR is active. NVIDIA's
   context-priority mechanism is principally for timely compositor/timewarp
   execution; higher application priority cannot remove a CPU block and can
   compete with the compositor. [NVIDIA context priority](https://developer.nvidia.com/vrworks/headset/contextpriority).
   This machine does not advertise `GLX_EXT_context_priority` or
   `XR_EXT_performance_settings`. The GLX extension is a context-creation hint,
   not a general GPU reservation.
   [GLX specification](https://github.com/KhronosGroup/OpenGL-Registry/blob/main/extensions/EXT/GLX_EXT_context_priority.txt).

## Verification needed for a fix

Capture per-phase CPU time including worker/export activity, asynchronous GPU
timer queries and SteamVR compositor frame timing around both 40–50% and the
final handoff. Valve exposes actual dropped/mispresented frames and reprojection
flags through compositor timing; these should supplement application gaps.
[Valve timing API](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming).

Repeat cold and warm loads across all representations and detail levels, with
head/controller motion, cancellation and superseded requests. Establish p99 and
maximum frame-time gates against the runtime period, not an average or a loading
completion assertion. Run all four controller motion profiles after behavioral
changes. Ball & Stick also showed frequent roughly 22 ms frame intervals after
loading: steady-state rendering needs its own budget check, separate from the
single installation stall. Physical comfort remains manual validation debt.

## Evidence, instrumentation and cleanup

Evidence is retained under `.development-artifacts/vr-loading-stalls/`:
`run-{stick,ballstick,surface}/`, native logs and stereo captures, host/GPU samples,
`summary.json`, `loading-stalls.png` / `.svg`, runtime extension inventory,
`analyze.py`, and `cleanup-verification.json`. Native logs append across runs;
analysis filters by requested representation and each run's observation timestamps.
The first Stick reach needed a timing retry before loading; the failed attempt
is retained, with the existing threshold unchanged.

Local diagnostic changes add an opt-in ScryWrite CPU phase trace, timestamped
loading observations, optional post-ready sampling and native-log retention.
No rendering/scheduling fix is applied. Native build, JS syntax and Python
compilation passed. All three browser runs passed model/acknowledgement checks.
Cleanup verifies stopped owned viewers, removed IPC paths, removed private
documents/caches and unchanged original documents. No broad regression suite was
run for these diagnostic-only changes.
