# CPD production trajectory playback

The October 20, 2026 benchmark uses the four completed October 19 CPD isomer
NAMD production jobs: cis-syn-I `d6bcdef3d59f`, cis-anti-I `972af34aa9c5`,
trans-syn-I `37d39cc6b88f`, and trans-syn-II `9b08bed08561`.
These are temporary workload references, not scientific validation fixtures.
The default selection is 200 of 1,000 saved frames (interval 5), with 1,963
heavy display atoms. No production job is launched, resumed, or modified.

## Playback policy

- Prepare small selections completely before reporting Ready: at most 200
  selected frames, 32 MiB of retained exact atom data, and 32 MiB of coarse
  coordinate data. The benchmark's exact coordinate response is approximately
  9.4 MB; retained arrays and serial maps occupy approximately 11 MB.
- Larger selections and surfaces retain bounded streaming (two eight-frame
  coarse pages). Exact atom retention remains byte bounded. Cached frames are
  scoped to job, display epoch, alignment, scope, and stride; cancelled requests
  cannot populate a replacement load.
- Retain source Float64 coordinates and serial mappings. Interpolation is display
  state only. It does not change saved trajectories, topology, bonds, or geometry
  authorities. There is no interpolation across the loop boundary.
- Enable Smooth by default for fitting atomistic selections; honor an explicit
  user choice on subsequent loads. Saved endpoints remain paced at 12 Hz, with
  three intermediate display samples targeting 48 Hz. Late interpolation samples
  are skipped rather than queued.
- Prepare ions and periodic-cell companions on load/page changes or explicit
  control refresh, then advance them with the DNA. Cached playback avoids loading
  toasts and repeated companion preparation.
- Publish the latest scene with one upload in flight, coalescing intervening
  updates. Browser animation-frame throttling does not govern native delivery.
  The native atomistic playback reader checks continuously while playing; its
  asynchronous reader and 1 ms per-frame upload budget remain bounded.

## Final optimization pass — October 21

The native transform decoder now reads bounded blocks of 1,024 instances instead
of one 12-byte vector at a time. Scratch is capped at 48 KiB; instance order,
finite-value rejection, matrix components and normalization arithmetic are
unchanged. The regression compares exact bytes with the original scalar reader,
including block boundaries, truncated packets and a nonfinite value in the final
block. The production GL test still checks exact CPU/GPU buffers and rendered
pixels. Repeat the isolated comparison with
`nadoc-vr-view-transform-update-test --benchmark` (under the validation guard).
Its warm-buffer medians isolate decoding work, not complete frame latency.

For 500,000 affine instances, isolated decode improved 13.59→7.25 ms. In resident
24HB P1 playback, native preparation medians improved 73.60→64.64 ms (ball-and-stick)
and 57.98→50.65 ms (stick). Delivered-scene medians stayed approximately
167 / 112 / 67 ms for ball-and-stick / stick / VDW. GPU medians remained
26.99 / 4.99 / 22.29 ms. This is a small CPU-headroom improvement, not a major
playback-cadence gain. The scope recorded memory-high and socket throttling;
large-model tail comparisons are therefore confounded.

The longer cis-syn-I CPD repeat uses three 60-second windows with the default
200-frame resident selection, Smooth OFF and looping ON. Each style advances
723 saved endpoints with zero coordinate requests. One of 2,170 scene intervals
exceeds 125 ms (223.1 ms, ball-and-stick); stick/VDW maxima are 111.8/111.7 ms.
Native frame p95 stays below 11.48 ms; one of 16,115 frames exceeds 16.67 ms
(maximum 17.29 ms). No browser long tasks, missing GPU samples or CPD-scope
memory throttling were observed. This does not establish perfectly seamless
playback or physical headset comfort.

The outlier takes 151.3 ms in browser upload, including 137.2 ms before the
backend handler's timing begins; browser requestStart follows resource start by
0.4 ms, and measured backend work takes 10.9 ms. A contemporaneous simulation
control publication takes 141.5 ms. This localizes the remaining issue to the
publication path, not trajectory reads or decoding. Synchronous session/config
reads and lock acquisition in async publishers are an identified candidate for
further investigation, not a proven cause; proxy/logging/scheduling effects have
not been separated. Do not label this a fundamental model-size limit.

Further decoder micro-optimizations have diminishing end-to-end returns.
Substantial 24HB gains need a separate GPU-rendering effort (ball-and-stick/VDW)
and reductions across browser capture, encoding and publication (especially stick).
Preserve atom coordinates/radii, bond semantics, stereo/depth and selection when
evaluating such changes. No tessellation reduction or interpolation change was
made in this pass. Headset-rate rendering and saved-endpoint delivery remain
separate requirements.

See [the final-pass audit](audits/vr_final_pass_20261021.json) for the longer CPD
repeat, exact comparisons, environmental limits, validation and cleanup. The
registered CPD benchmark supports `NADOC_PLAYBACK_WINDOW_MS=60000` for longer
samples. Through-lens review remains MV-50.

## Persistent transform stream — October 21 follow-up

Atomistic playback now negotiates schema 7 with the native receiver. After a full
snapshot, compatible updates carry absolute translation vectors for unchanged
linear transforms, or all 12 affine matrix components otherwise. Meshes, instance
colors and layout remain in the immutable full snapshot. Any material, mesh,
instance-count or atlas change falls back to a full snapshot. Older viewers keep
the existing full-snapshot path; `NADOC_VR_TRANSFORM_UPDATES=0` disables negotiation
for a full-snapshot comparison.

Updates refer to the full snapshot version, never the preceding animation frame.
Coalescing therefore cannot accumulate errors. Float64 source coordinates and the
existing Float32 display matrices are unchanged; no quantization, bond
reconstruction, interpolation or mesh simplification is introduced. The receiver
rejects stale bases and malformed updates. It retains vertex/index/group buffers
and alternates two instance buffers, reusing each only after its GPU fence signals.
The existing 1 ms staging budget and 256 KiB upload chunks remain unchanged.

The production GL regression compares full/update CPU matrices, GPU buffer bytes
and visible rendered pixels, checks buffer reuse, and rejects stale layout bases.
Its moved-image negative case excludes agreement between two blank captures.
Backend rotation and frontend encoding have independent exact-value tests.

Final CPD validation covers all four isomers × three styles. Each 12-second window
advanced 144 saved endpoints with zero coordinate requests. All 1,752 measured
publications used transform packets. Ball-and-stick packets fell from 1,105,048 to
341,616 bytes (69%); VDW from 572,128 to 23,928 bytes (96%). One of 1,729 submitted
scene intervals exceeded 125 ms (179.3 ms); 11/12 windows passed the stricter
boundary-inclusive cadence diagnostic. Native frame p95 stayed below 11.48 ms;
two of 12,891 intervals exceeded 16.67 ms, maximum 19.39 ms. This is not perfectly
hitch-free playback. The outlier upload took 98 ms in the browser versus 7.6 ms in
backend handling, leaving publication scheduling as a separate target.

The final CPD window ends before the intentional pause acknowledgment, which is
now recorded separately. Earlier measurements included that stopped interval in
their boundary diagnostic. Scene-to-scene gaps and the 125 ms threshold are
unchanged. A startup log-interleaving failure is recorded; the parser now reports
malformed records and refuses to certify affected timing windows.

Resident 24HB P1 Alpine median delivered-scene gaps improved from approximately
302 to 168 ms (ball-and-stick) and 156 to 112 ms (stick); VDW remained near 67 ms.
All six windows across both 24HB jobs made zero coordinate requests. P1 median
GPU times remained 27.45 / 4.73 / 22.51 ms: transfer optimization does not remove
the large ball-and-stick/VDW rendering limit. The validation scope recorded 1,004
memory-high events across setup/runs, no OOM and no socket throttling; this is a
workstation comparison, not a controlled storage benchmark.

Validation: 8,389 frontend tests (one skipped), 23 app smoke checks, 84 focused
Python transport/metrics/tour checks and two native exact-buffer/pixel tests passed.
The backend selector chose `FAST`: Archive scratch produced 14,660 passes, five
unrelated failures, four chemistry-preview errors and 92 skips. The broad timing
gate also reported transient outliers; isolated checks passed. Full-suite coverage
remains deferred without a test-dedicated session. Existing repository lint and
memory-structure debt remains; task Python lint and diff checks pass. The audit
retains exact failure names, selector deferral text and timing-triage evidence.

See [the transform-stream audit](audits/vr_transform_stream_20261021.json) for
CPD results, boundary stalls, failed attempts, validation and cleanup. Submitted
stereo evidence establishes molecular output, not through-lens comfort (MV-50).

## October 21 hitch investigation

The exact-frame follow-up keeps Smooth OFF and desktop 3D drawing OFF, measures
12-second playback windows, and separately records browser endpoints, first native
submissions of new scene versions, headset frame intervals and GPU time. A browser
endpoint count alone is insufficient: a large scene can coalesce several endpoints
before a new scene reaches the headset. `metrics.json` reports scene gaps, missing
GPU records, boundary stalls and a 125 ms delivery diagnostic; it does not certify
physical headset comfort. Native style preparation finishes before the timed window.

Two runtime changes preserve existing geometry and coordinate precision:

- Cache immutable local vertex templates by attribute identity/upload version,
  material properties, draw range and atlas coordinates. Pack current world matrices,
  instance colors and visibility directly into typed arrays every frame.
- Treat the native viewer's acknowledgement of an already-settled desktop style
  as a no-op. Previously it rebuilt the display and emitted a representation-change
  event that could pause playback. Explicit forced rebuilds remain available.

The harness also removes setup-only browser request interception before measurement:
Chrome debugging interception inflated large binary upload timings. Initial lazy-style
loads and failed synthetic launch attempts are recorded separately from steady playback.

Compare the two completed 24HB jobs with `--large`; use
`NADOC_PLAYBACK_RESIDENT_FRAMES=4` to loop four exact resident frames and isolate
rendering/transfer costs from coordinate reads. With no override the normal selected
range and bounded streaming policy apply. `NADOC_CPD_SAVED_ONLY=1` selects the
exact-saved-frame condition; `NADOC_PLAYBACK_WINDOW_MS` extends timing windows.
The older 24HB package lacks a frozen design snapshot; the harness retains that
absence and uses the existing workspace design through the application's legacy path.
These comparisons measure rendering scale, not molecular-geometry correctness.

Final exact-frame CPD results (four isomers × three styles): 143–144 browser
endpoints per 12-second window; zero coordinate requests; capture maximum 3.1 ms
versus 123.3 ms in the initial ball-and-stick sample. Across 1,728 delivered-scene
intervals, five exceeded 125 ms (maximum 234.6 ms). Native frame p95 stayed below
11.50 ms; one of 13,007 submitted frames exceeded 16.67 ms (maximum 24.07 ms).
Thus the severe packing stall is removed, but rare publication hitches remain.
One VDW outlier spent 153.4 ms in browser upload versus 9.7 ms in backend handling;
its exact scheduling cause remains unresolved.

For 24HB P1 Alpine, resident four-frame playback had median delivered-scene
intervals of 302 ms (ball-and-stick), 156 ms (stick), and 67 ms (VDW). Median GPU
times were 27.36, 4.74 and 22.73 ms respectively: stick can sustain head tracking
at approximately 90 Hz, while ball-and-stick/VDW settled near 30 submitted frames/s.
These resident windows made zero coordinate requests. In the default-range runs,
both 24HB jobs remained playing throughout all styles but failed the unchanged
throughput gate: 15–76 browser endpoints per 12 seconds, with 10–23 coordinate
requests and delivered-scene gaps as large as 3.28 s. The validation scope recorded
6 GiB memory-high and socket throttling events (no OOM); those streaming stalls are
not a pure HDD benchmark. GPU timings establish a separate rendering-size limit.

The next implementation (below) addresses transform updates into persistent native
buffers. Remaining targets include publication scheduling diagnostics for CPD
outliers and equivalent
atom/bond rendering optimizations with image/depth parity checks. None of those
future changes is implemented or claimed validated here.

Final measurements, failed attempts, cleanup and verification are recorded in
[the hitch audit](audits/cpd_vr_hitches_20261021.json). Exact saved samples at 12 Hz
cannot provide continuously varying 90 Hz molecular motion without interpolation;
head-tracked rendering should nevertheless remain smooth. No additional interpolation
or reduced-fidelity geometry was introduced.

## Reproduce

Use **Debug → VR Tours & Tests… → Left sidebar → CPD production · atomistic playback benchmark**, or:

```sh
.venv/bin/python -m tools.vr_workflows.cpd_playback_check --validate
```

The launcher requires Archive mounted and refuses to replace an active viewer.
It runs under the normal validation resource guard, uses a private Archive
workspace with copied metadata and read-only DCD symlinks, and checks source
metadata hashes and trajectory sizes/mtimes afterward. Existing SteamVR and
Alpine workers remain running. Only its own viewer is stopped. Private workspace
and scratch are removed on exit; summarized capture output needs normal
post-validation cleanup. Without `--validate`, it measures cis-syn-I only.

The app loads the default trajectory, switches through the real Ball & Stick,
Stick, and VDW menu actions, reloads the default selection, and measures 12-second
saved-frame and Smooth windows. Quantitative runs disable Playwright tracing
(the traced diagnostic runs retained hundreds of MB and are reported separately).
The isolated browser sets the existing Desktop 3D during VR preference to Off:
Playwright otherwise keeps the browser focused and redraws it alongside native VR.
Desktop frame counters verify that drawing is paused while control callbacks
continue. Set `NADOC_CPD_DESKTOP_RENDERING=on` for a separate desktop-on condition;
this does not change the normal application's saved preference or default.
Geometry is placed in the physical runtime's
view using the existing inspector placement action before measurement. Submitted
left/right-eye captures verify the requested representation and identifiable
model pixels after timing. No synthetic tracking or headset configuration
changes are used. Surface representations are outside this benchmark.

## Direct playback transport — October 20

New native viewers receive the existing validated scene packet through a local
Unix socket rather than a repeatedly replaced file. Simulation status and
presentation controls use separate channels with their existing text formats and
parsers. Moving scene packets alone was insufficient: a private-process timing
probe found 160–230 ms synchronous replacements of the smaller control files.
All three transfers now run outside the async backend event loop.

The transport checks the local peer UID and keys each channel to its session's
event path. Frames are length bounded (256 MiB maximum), incomplete packets are
rejected, and acknowledgment follows complete receipt. Each channel has one
receiving packet and one pending packet. Scene packets apply backpressure to
preserve atlas-before-update ordering; complete control states coalesce to the
latest, matching the prior file semantics. Presenter heartbeats retain their
three-second expiry. An established IPC reader never reloads a stale legacy file.
An unavailable listener retains compatibility with already-running older viewers;
a timeout or partial transfer fails rather than silently writing an alternate file.
Set `NADOC_VR_VIEW_IPC=0` before launch for a deliberate legacy-path comparison.

This is byte-preserving transport optimization. Coordinate selection, rotation,
render precision, geometry, shading, source Float64 retention, and the native
1 ms upload budget are unchanged. Full scene packets are still parsed and staged;
persistent mesh-buffer reuse and a coordinate-only protocol remain separate work.
No new interpolation was added. Saved-frame tests explicitly disable Smooth.

The cis-syn-I saved-frame repeat delivered 144/144/143 endpoints in its three
12-second Ball & Stick/Stick/VDW windows. All scene transfers used IPC with zero
coordinate fetches. Maximum submitted-scene gaps changed from 458/469/983 ms in
the diagnostic baseline to 102/101/268 ms. Across all four isomers, all 12 saved-frame
windows pass: 143–145 endpoints, 11.955–12.059 scene updates/s, zero coordinate
fetches, and scene/control packets using IPC throughout playback. Legacy control
fallbacks occur only during startup and after viewer stop. Maximum per-window p95
scene gap is 89.8 ms; the worst gap remains 268 ms. Native frame medians stay around
11.17 ms, maximum per-window p95 11.55 ms, worst interval 35.0 ms. These short
sequential trials establish a substantially steadier path, not a guarantee that
every hitch is eliminated or that molecules update at headset refresh rate.

Thirty focused transport/control tests and 50 tour tests pass. The native build
and submitted-stereo checks pass for all four isomers/styles. Final `test-smart`
selected `FAST  (fast suite only)`: 14,643 passed, four failed, four errors, 92
skipped. Remaining failures concern existing streptavidin/photoproduct/preview
paths; FULL remains deferred. Flagged slow mocked tests pass below budget in
isolation; guards and markers were unchanged. An initial native include-placement
build failure and a stale job-selection setup failure are retained in the audit;
the harness now retries only an unselected job, with unchanged playback thresholds.
No frontend runtime code changed in this task. Source jobs and existing runtime
processes were preserved. See the [IPC audit](audits/cpd_vr_ipc_20261020.json).

## Fidelity-first pipeline diagnosis — October 20

Use `NADOC_CPD_SAVED_ONLY=1` with the launcher to measure only saved frames;
`NADOC_CPD_STYLES=vdw` limits a diagnostic repeat to one style. The registered
benchmark now captures bounded browser stage records and opt-in backend/native
stage timings (`NADOC_VR_VIEW_PIPELINE=1`). Normal application sessions do not
activate this logging. Records correlate source frame, scene version, capture,
upload, file publication, native read/parse/upload, and first submitted frame.
Submission is not a physical display timestamp. Native read/parse includes CPU
work, so it is an upper bound on file-read time.

Archive is a rotational HDD (`/dev/sdb`); both DCDs and transient scene files live
there. All four new twelve-second windows (three styles plus a VDW repeat) made
**zero coordinate requests** after Ready. Smooth was explicitly off. Cached
coordinate application took at most 1.6 ms; native read/parse at most 2.25 ms.

The synchronous scene-file publication path does stall:

| Measured stage | Ball & Stick max | Stick max | VDW max |
|---|---:|---:|---:|
| Scene capture | 9.2 ms | 5.7 ms | 5.5 ms |
| Backend file write/chmod/replace | 131 ms | 218 ms | 251 ms |
| Browser upload round trip | 437 ms | 253 ms | 764 ms |
| Gap between submitted scene versions | 458 ms | 469 ms | 983 ms |

The follow-up VDW run split the file operations: write/close reached 250 ms and
atomic replacement reached 468 ms (replacement p95 279 ms). Validation inside its
worker took at most 2.8 ms, while waiting for the async backend to resume reached
388 ms. Synchronous file operations block that same event loop. Browser long tasks
also occurred (213/254 ms); the measurements do not attribute every delay to disk.
Native frame interval medians remained 11.16–11.18 ms. The initial three windows
passed the endpoint-throughput gate; the repeat failed with 75 endpoints against
the unchanged >80 threshold. This is diagnostic instrumentation, not a hitch fix.

The HDD-backed scene handoff is a measured contributor. This does **not** show
that reading the DCD limits resident playback, or that rotational media alone
explain all stalls. There was no SSD/RAM control; file-operation wall times include
scheduling, device counters include other processes, and diagnostic logs add load.
No caches were dropped and no production data were moved.

The diagnosis motivated the direct transport implemented above. A further step is: retain
native atom/bond buffers and deliver bounded, versioned **exact saved coordinates**
through IPC. Preserve serial mapping, bond topology, representation parity,
Float64 source retention, cancellation rules, and the native upload budget.
Measure endpoint delivery separately from headset cadence; do not introduce
invented intermediate positions or claim continuous motion from a throughput pass.
Moving synchronous publication off the async event loop is a narrower mitigation,
but does not by itself eliminate storage latency.

Validation: nine focused backend tests pass; 8,379 frontend tests pass (one skipped);
normal app launch rebuilt the native viewer and submitted stereo checks passed in
both diagnostic runs. `test-smart` selected `FAST  (fast suite only)` and reported
14,627 passed, eight failed, four errors, 92 skipped. Three socket-related failures
pass with a short Archive TMPDIR (12 Alpine, one native motion test); five other
failures and four errors remain unresolved outside the tracing changes. Four
placement collection cases also pass in isolation. No slow markers or guards
were changed. FULL remains deferred without a test-dedicated session; the exact
selector output, failures, timings, and cleanup are in the
[pipeline audit](audits/cpd_vr_pipeline_20261020.json).

## Home loop containment and repeat

Home's launch client could not connect to `steam-runtime-launcher-service`; no
launcher service was running. Setting `steamvr.enableHomeApp=false` through the
live OpenVR API stopped the retry storm without restarting SteamVR. The saved
setting remains off. This disables Home autostart; it does not repair Home's
launcher integration. NADOC application code was unchanged for the comparison.

The repeat covered all four isomers and 24 playback windows. There were **zero
Home launch retries and zero coordinate reads during playback**. All 24 existing
throughput gates passed, including cis-syn-I Smooth Stick (75 → 120 saved endpoints)
and trans-syn-I Smooth VDW (75 → 122). An initial trans-syn-I attempt failed setup
before timing; the harness now verifies/retries stale read-only mode selection,
and the isolated `--job 37d39cc6b88f` repeat completed.

**Trajectory hitches remain.** Scene updates averaged 7.18–20.90 Hz and the worst
scene gap was 1.843 seconds. Timing changes were mixed across cases; these short
sequential trials do not establish a general smoothness improvement. Native app
interval medians were 11.155–11.181 ms, maximum per-window p95 11.701 ms, with a
120.122 ms worst interval. Passing the endpoint-throughput gate is not a continuous
motion guarantee. The launch storm was real, but stopping it did not resolve the
remaining playback bottleneck. See the [follow-up audit](audits/cpd_vr_home_fix_20261020.json).

## Runtime confounder found after measurement

The user observed vrmonitor rapidly alternating NADOC and “Starting SteamVR Home”.
Read-only inspection confirmed a Home launch/abort/retry storm, approximately
35–38 launches per second **during the final NADOC playback windows**. In the
cis-syn-I repeat, retained logs show 425–460 Home launch attempts per window.
The SteamVR server/compositor processes stayed alive; this was repeated Home
application launching, not a repeated restart of the entire runtime.

Zero coordinate reads remains verified, but the remaining timing results below
are confounded. They cannot establish that scene publication alone caused the
stalls. This finding prompted the Home-off repeat above. No runtime settings were
changed during the initial read-only inspection.

## Measured result

The final desktop-off condition covers four isomers × three styles × two playback
modes (24 twelve-second windows). All 24 made **zero coordinate requests after
Ready**. Submitted left/right eyes showed the requested atomistic representation
in every case. The original Ball & Stick run made 68/57 coordinate requests in
its saved/Smooth windows, with a saved-frame stall of 2.4 seconds. Storage and
measurement conditions differ, so these are diagnostic observations, not a
controlled speedup claim.

Native application intervals had medians 11.157–11.177 ms and p95 values
11.465–11.555 ms. Occasional hitches remain: the worst application interval was
276.715 ms. Molecular scene delivery averaged **7.05–24.45 updates/s**, with a
worst gap of 1.788 seconds. This is **not consistently smooth playback**.
Two windows missed the unchanged >80 saved-endpoints gate: trans-syn-I Smooth
VDW and cis-syn-I Smooth Stick each delivered 75. All remaining windows passed.
The optimization removes fetch starvation and redundant work, but the Home relaunch storm must be isolated before attributing the remaining
stalls to capture/transfer. Increasing cache size cannot resolve stalls in
windows that already have zero coordinate reads.

Validation: 8,379 frontend tests passed (one skipped), 50 tour tests, 23 private
app smoke checks, ten final trajectory tests, successful native build, and
submitted-eye app checks. The benchmark remains failing on the two performance
windows above. Repository lint has five pre-existing unused-import errors;
memory lint has three pre-existing structural errors. Task Python lint and
`git diff --check` pass. See the audit for every failed attempt and condition.

## October 20 interpretation (historical)

Zero coordinate requests after Ready establishes resident playback, not continuous
headset-rate molecular animation. Report saved endpoint cadence, delivered scene
versions, application frame cadence, and GPU time separately. The October 20 path
rebuilt/transferred complete display snapshots; native render rate can stay
near 90 Hz while molecule updates arrive more slowly. Through-lens comfort and
head motion are not established by submitted-eye captures.

See the [measurement audit](audits/cpd_vr_playback_20261020.json) for results,
failed attempts, validation, and cleanup. Further work toward 90 Hz molecular
motion should measure a native coordinate/interpolation stream that reuses
unchanged atom/bond meshes, rather than increasing snapshot queue depth or GPU
upload budgets. Such a change needs independent atom/bond parity validation.
