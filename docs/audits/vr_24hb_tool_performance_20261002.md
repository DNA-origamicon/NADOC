# Full-size 24HB VR performance dataset

Subsequent [90 Hz optimization work](vr_ballstick_90hz_20261002.md) found that
Playwright can leave the desktop page reporting focus and drawing approximately
60 FPS while native VR is active. Existing tool-run GPU/cadence numbers therefore
may include desktop contention; they are not isolated native-renderer limits.
The original evidence is preserved. A separately minimized-browser diagnostic
paused animation callbacks and blocked a cluster commit, so it is not a valid
replacement for complete authoring validation.

The controlled 192-case collection and separately labeled four-case Full Nick
observation retry are complete. This report supplements the
[calculation audit](vr_frame_calculations_20261001.md), which contains the native
calculation inventory and the earlier, mixed-size tool results.
The new CSV tables include only the full-size campaigns and the fresh 24HB
baseline. Earlier small-fixture campaigns are not merged into those tables.

Open the [offline review](../../.development-artifacts/vr-24hb-audit-dataset-20261002/review.html)
or [dataset index](../../.development-artifacts/vr-24hb-audit-dataset-20261002/index.json).
The [compact ZIP](../../.development-artifacts/vr-24hb-audit-dataset-20261002.zip)
contains nine CSV tables, the offline review, four baseline mirror images,
reports, source snapshots, provenance and validation evidence. Complete raw
frame logs and capture trees remain at the host archive paths in the CSVs;
they are not included in this compact ZIP.

The export retains **409 full-size tool attempts**, **192 unique combinations**,
**4,592 measured interval rows**, **820 whole-session representation/tool rows**,
and **411 named operation spans**. These row counts are not independent sample
counts: intervals overlap, sessions split by style/tool, and operation spans
include stationary observation windows and failures. The 48 fresh baseline
intervals are included in the interval table, separately labeled.

## Fresh full-size baseline

After runtime recovery, all **48** normal idle/whole-model grip intervals passed,
with **18,450** recorded frames. Source geometry is 24 helices, 76 strands and
6,720 nucleotides. The immutable snapshot is tied to source SHA-256
`bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
This is physical OpenXR with synthetic controller profiles, not wearer testing.
Extrude adds a six-helix part to the full imported design; “6HB” in that
workflow's older title describes the new part, not the size of its input scene.

| Representation | Application FPS range | Compositor GPU p95 range (ms) | Largest interval work p95 (ms) |
| --- | ---: | ---: | ---: |
| Full | 89.52–89.64 | 2.61–3.88 | 0.49 |
| Stick | 89.52–89.53 | 6.75–7.06 | 0.45 |
| Ball & Stick | 89.36–89.53 | 7.13–7.43 | 0.45 |
| Quick Surface | 89.50–89.54 | 3.92–4.18 | 0.42 |

Ranges cover separate intervals, not pooled FPS. No compositor drops were
reported in the sampled baseline intervals. Work is native outer wall time
minus named runtime waits; it is not pure CPU execution. GPU and CPU durations
overlap and must not be added. Fixed frame budget is **11.111 ms at 90 Hz**.
Raw baseline: `.development-artifacts/vr-24hb-baseline-controlled-20261002/`.
Compositor summaries cover each whole named interval. If native tool or
representation changes split that interval into multiple CSV rows, those rows
share the interval's compositor summary; GPU samples are not independently
attributed to each split. The baseline and selected stationary examples above
have stable representations.
The exported `gpu_ms` statistic is OpenVR `m_flPreSubmitGpuMs`. It is a
compositor-reported scene-rendering span, not GPU utilization or a per-shader
profile. Valve documents that GPU timing can include other processes' work
because of scheduling. CPU wall time and this span can overlap; they must not
be added. This audit has no independent GPU busy-time or per-pass timestamp
measurement. See [Valve's frame-timing definition](https://github.com/ValveSoftware/openvr/blob/master/headers/openvr.h#L2003-L2019).

## Runtime recovery and controlled repeat

The first validation matrix stopped after 186 attempted cases when SteamVR's
server and compositor watchdogs aborted. Host memory was under pressure: about
11 GiB of shared memory was allocated, and the Steam web helper mapped about
10 GiB of it. A graceful Steam shutdown released that allocation and restored
about 16 GiB of available RAM. This does not establish an application leak.
The campaign repeatedly launched isolated viewers; it does not establish the
same memory growth in one uninterrupted user VR session.
Runtime logs, resource counters and mapping inventories are preserved in
`.development-artifacts/vr-24hb-runtime-recovery-20261002/`.

The controlled repeat uses the full-size harness, resets Steam/SteamVR before each
representation batch and records host memory, shared memory and paging counters
at every case boundary. It stops before launching a case below an 8 GiB
available-memory floor. These host-wide counters include setup and cleanup;
they are not per-frame process attribution. Earlier attempts remain in the
dataset, including setup failures with no measured representation frames.
Native renderer/instrumentation code is unchanged during the controlled repeat.
Observation setup refinements made during the Full batch (simulation footer
activation and Nick target selection) are identified below; those attempts are
not presented as identical-input A/B trials.

## Controlled tool results

All **192 requested cases** were attempted: 12 workflows × 4 representations ×
4 motion profiles. **31 complete workflows pass** both authoring and audit
coverage checks. The other 161 retain their failures and any valid measurements;
this is complete attempted matrix coverage, not successful coverage of every
tool stage. Dimensions passes all 16 representation/profile combinations.

| Representation | Attempts | Complete workflow/audit passes | Minimum case-boundary available RAM (GiB) | Host swap-out pages across cases |
| --- | ---: | ---: | ---: | ---: |
| Full | 48 | 14 | 11.86 | 2,684 |
| Stick | 48 | 6 | 11.13 | 64 |
| Ball & Stick | 48 | 7 | 11.73 | 0 |
| Quick Surface | 48 | 4 | 11.37 | 184 |

RAM minima are only before/after-case samples, not during-frame minima. Paging
counters are host-wide and include setup/cleanup, not isolated application I/O.

The latest chronological attempt has a structurally valid trace and normal
native process-end record in all 192 cases. Measured intervals contain frames
in the requested style for **48/48 Full, 45/48 Stick, 44/48 Ball & Stick and
43/48 Surface** cases. The 12 gaps are failed setup/observation paths; a valid
trace in another style does not satisfy the requested representation coverage.
No declared intervals are missing from those latest trace reports, but tool
stages never reached by a failed workflow are still unmeasured.

Requested-style interval gaps: Bend variable-deliberate in Stick/Ball & Stick/
Surface; Twist both variable profiles in those three styles; Ball & Stick
End Resize variable-fast; Surface End Resize variable-deliberate; and Surface
View Tools variable-fast. Counts of reached named commit intervals are not
equivalent to successful edits or full workflow coverage.

The Full batch completes **48 attempts / 14 full workflow passes**: base Move
3/4, cluster Move 3/4, Bend 2/4, Twist 2/4 and Dimensions 4/4. Other Full
workflows retain failed attempts and their measured intervals. The minimum
recorded case-boundary available memory is **11.86 GiB**; host swap-out totals
2,684 pages across the batch, including setup and cleanup. These boundaries
do not establish a minimum available memory during each individual frame.
The subsequent Steam/SteamVR reset succeeds before Stick starts.
Stick completes **48 attempts / 6 full workflow passes**: base Move 2/4 and
Dimensions 4/4. Minimum case-boundary available memory is **11.13 GiB**, with
64 host pages swapped out across the batch. The reset before Ball & Stick
releases the accumulated shared memory before the next batch starts.
Ball & Stick completes **48 attempts / 7 full workflow passes**: base Move 2/4,
cluster Move 1/4 and Dimensions 4/4. Minimum case-boundary available memory is
**11.73 GiB**, with **no host swap-out pages** recorded across the batch. The
runtime reset succeeds before Quick Surface starts.
Quick Surface completes all **48 attempts / 4 full workflow passes**, all four
Dimensions profiles. Its minimum case-boundary available memory is **11.37 GiB**,
with 184 host pages swapped out. All four representation resets pass.

Full base Move passes both steady profiles and variable-deliberate; variable-fast
fails the unchanged assertion that the selected geometry is pointed at. In the
steady-fast case, selected stationary rendering is **89.53 FPS** both without
and with continuous observation. Its commit interval has 19 complete contained
frames, **67.14 FPS** and a **36.41 ms** maximum outer frame. The workflow passes
editing, Undo, save and reopen despite this commit-time budget spike. This fresh
case has no host swap-out activity at the case boundaries.

Full Bend steady-fast also passes with stationary rendering at **89.53 FPS**.
Its Confirm-acquisition-plus-acknowledgement span is **5.80 seconds**; 492 complete
contained frames average **85.03 FPS** and include a **262.23 ms** outer frame.
The commit interval's input phase reaches 253.40 ms and inclusive `setStyle`
reaches 64.86 ms. Scope maxima need not occur in the same frame and are not
additive. Host boundary counters show five swapped-in pages and zero swapped-out
pages. The slower frame therefore persists after the runtime reset, without
evidence of contemporaneous host swap-out in that case.

Stick base Move steady-fast passes with **89.53 FPS** selected stationary
rendering. Commit acknowledgement takes **1,034.7 ms**; its 70 complete contained
frames average **69.40 FPS**, including a **193.76 ms** outer frame. The case
records 17 swapped-in pages and no swapped-out pages at host boundaries. This
confirms that the earlier Stick commit spike is reproducible after a runtime
reset; a smooth normal or stationary scene does not establish smooth commits.

Stick cluster Move steady-fast reproduces **44.76 FPS** while stationary, with
or without continuous observation. Compositor GPU p95 is **14.10 / 13.97 ms**,
above the fixed 11.111 ms budget; native non-runtime-wait work p95 is only
**1.33 / 1.85 ms**. It records four swapped-in pages and no swapped-out pages.
The later remote-grab assertion fails before commit. The compositor-reported
GPU span exceeds budget in this selected, closer-view workload after reset;
low frame-thread work supports further GPU/driver investigation. It does not
isolate a shader stage, selection overhead from the changed view, or commit behavior.

Ball & Stick base Move steady-fast passes despite reduced stationary cadence:
**48.47 FPS** without continuous observation and **47.46 FPS** with it. GPU p95
is **12.33 / 12.31 ms**, while non-runtime-wait work p95 is **0.54 / 1.55 ms**.
Commit acknowledges after **1,272.1 ms**; 45 complete contained frames average
**36.11 FPS**, with a **372.83 ms** maximum outer frame. Host boundary counters
show 52 swapped-in pages and no swapped-out pages. The closer selected scene
differs from the normal overview; a successful workflow does not establish
that either its stationary or commit rendering meets the 90-Hz target.
Ball & Stick cluster Move steady-deliberate also passes, with **44.77 FPS**
selected stationary rendering. Commit acknowledges after **1,768.6 ms**; its
48 complete contained frames average **27.65 FPS**, with a **672.21 ms** maximum
outer frame. The inclusive `setStyle` total reaches **654.08 ms in one frame**.
Host boundary counters show no swap-in or swap-out activity for this case.
This records a substantial render-thread rebuild/upload stall in a workflow
that still passes editing, Undo, save and reopen checks; the scope is wall time,
not pure CPU execution.

Quick Surface base Move steady-fast measures **21.31 FPS** without continuous
observation and **20.72 FPS** with it. Native `pick` active-frame p95 is
**32.74 / 32.70 ms**; overall non-runtime-wait work p95 is **33.93 / 33.81 ms**.
All **63 / 62** complete contained frames exceed the fixed 11.111 ms work budget.
There are **no `setStyle` calls** in these windows. The case records two
swapped-in pages and no swapped-out pages. Compositor GPU-span p95 is
**42.30 / 43.50 ms**, which must not be added to the CPU-side wall time or
interpreted as an isolated shader-execution cost. The native picking scope
alone is already over budget, reproducing the earlier CPU finding after reset.

Full End Resize steady-fast reaches a native `+6` commit, but the saved strand
is **six nucleotides shorter**, failing the unchanged length assertion. The
captured identity is the forward 3′ end `h_XY_1_4:55:FORWARD`; its terminal domain
is bp 49–55 on a 147-bp helix. `end_extrude_arrows.js` chooses non-singleton
outward direction by the nearest helix axis endpoint, then `_commitResize`
multiplies the native delta by that sign. A forward 3′ end inside the lower half
of a helix needs increasing bp for extension, despite being nearer the helix
start. This source path is consistent with the observed sign reversal. The audit
preserves the failing native/desktop evidence and makes no production sign fix.
Stick steady-deliberate and variable-deliberate reproduce the same expected
`+6` versus observed `-6` length change. The two fast Stick cases instead lose
the observer connection during feedback waits and do not establish the saved
length assertion. Their native logs end normally; that is not proof of a crash
or of successful edit completion.

Full Ligation reaches a commit for one polarity in some attempts but still has
visibility failures; its fixed 15-cm “loose” offset can also lie near another
compatible endpoint in the dense full-size scene. That negative-fixture
assumption remains a coverage limitation, not proof of erroneous endpoint
picking. Inspect each attempt rather than treating all Ligation failures as
performance defects.

Full and Stick View Volumes stop at the centroid-highlight pixel check. The
retained Full `steady_fast-box-centroid/mirror.png` shows the grab point inside
the dense origami. Initial setup fits a volume around all helix axes, but the
manipulation fixture subsequently replaces it with a head-relative box with
13/13/18-cm half extents. Its occluded centroid is not clear enough for the
unchanged stereo oracle. These attempts do not establish successful face
resizing or persistence; the pixel failure alone is not a frame-rate finding.

The controlled Quick Surface Bend steady-fast case illustrates why operation
waits and frame stalls are separate measurements. Confirm acquisition through
acknowledgement takes **22.792 seconds**, with no recorded operation error;
the later stereo layout check fails. Its 2,031 complete contained commit frames
run at **89.18 FPS**, with a **22.37 ms** maximum outer frame. The same session's
stationary Bend interval is **89.53 FPS**, unlike Surface Move's expensive
picking path. The whole session includes an **884.77 ms** Surface/Bend frame
and an inclusive `setStyle` maximum of **870.35 ms**, including setup/captures;
those maxima are not attributed to the contained commit interval. Host boundary
counters show zero swapped-in or swapped-out pages for this case.

The controlled Surface Ligation steady-fast stationary pair stays near
**89.53 FPS** both without and with continuous observation, while work p95 rises
from **0.41 to 5.61 ms**. Neither window has a work-budget overrun (267 and 270
complete frames). This demonstrates observer overhead without a cadence drop;
it does not establish a successful ligation. The subsequent workflow fails a
controller playback deadline. Host boundary counters record no paging activity.

## Retained exploratory results and resource-pressure limits

These are named measured intervals, including failed workflows; they are not
averages across differently framed tools. Runtime resource pressure confounds
late timings in this first campaign; the following numbers are retained evidence,
not final attribution of every delay to NADOC.

- In `vr-24hb-audit-validation/move-surface-steady_fast`, selected Move is
  stationary at **22.38 application FPS**. `pickSelected` falls back to `pick`,
  whose active-frame p95 is **32.97 ms** across 66 measured frames. `setStyle`
  is not called in this interval. Inspection of `GlScene::pick` shows CPU ray
  tests over the current source's points, cylinders, half-cylinders and boxes.
  The fallback in `pickSelected` is used when the packed preview cache is not
  active for the selected owner. This is a picking cost before a drag, distinct
  from the previously identified Quick Surface preview rebuild cost. Whole-cluster
  Move independently measures 22.38 FPS with `pick` p95 33.02 ms; `ownerHandle`
  is only 0.030 ms at p95 in that interval.
- In `bend-ballstick-steady_fast`, the stationary interval without continuous
  observer requests measures **44.60 FPS**, with compositor GPU duration p95
  **18.83 ms**. The ordinary overview baseline was near 90 FPS. The tool scene,
  view, desktop bridge and selection state differ from that overview.
- In `view_tools-ballstick-steady_fast`, paired stationary intervals measure
  **47.64 FPS** without continuous observation and **48.13 FPS** with it.
  Event/IPC phase p95 rises from **0.00965 ms** to **5.328 ms**; reported GPU
  duration p95 stays near **13.8 ms**. Observation is measurable overhead but
  does not explain that case's reduced stationary cadence.
- In `extrude-full-steady_fast`, the same observer comparison stays near
  **89.52–89.53 FPS**, while event/IPC p95 rises from **0.0074 ms** to **5.239 ms**.
  The subsequent grip still misses its scripted deadline. Native observation
  serializes the full Nick bond list outside the Move/Bend omission path, a
  source-level candidate for control-channel overhead. This does not establish
  a poor human-controller frame rate; synthetic motion and rendering have
  separate evidence and failure gates.
- Earlier full-size Full-mode plane-selection intervals contain
  `setSelectionHighlights` / `setStyle` spikes of approximately **37–38 ms**.
  These are inclusive, overlapping scopes, not two additive costs.
- `move_cluster-full-steady_fast` passes move/rotate, Undo, save and reopen.
  Its selected stationary interval is **89.53 FPS**, with non-runtime-wait
  wall time p95 **0.78 ms**. The commit acknowledgement takes **413.9 ms**;
  the 22 complete contained commit frames include a **62.75 ms** outer frame
  and inclusive `setStyle` p95 **45.91 ms**. A passing authoring workflow still
  contains a frame-budget spike.
- `bend-full-steady_fast` passes its preview, wheel, commit, save and Undo
  checks. Its Confirm interaction and acknowledgement span **5.33 seconds**, with
  **89.53 FPS** across 474 complete contained frames and a **14.52 ms** maximum
  outer frame. The operation includes acquiring/clicking Confirm; it is not a
  backend-only execution timer.
- `move-stick-steady_fast` passes individual-base editing, Undo, save and reopen.
  Selected stationary rendering is **89.53 FPS**. Commit acknowledgement takes
  **1,098.6 ms** and includes a **182.06 ms** complete frame; the contained commit
  interval averages **72.93 application FPS** across 77 frames. The stationary
  result alone would conceal this edit-adoption spike.
- `move_cluster-stick-steady_fast` has a different cost profile: selected
  stationary rendering is **44.76 FPS**, with compositor GPU duration p95
  **13.68 ms** and `pickSelected` p95 only **0.616 ms**. Its commit acknowledges
  after **5.415 seconds**, failing the unchanged 5-second gate. The contained
  commit frames include a **370.15 ms** outer frame and `setStyle` active-frame
  p95 **358.03 ms**. It reaches commit but does not complete later persistence
  checks after failing that latency gate.
- `bend-stick-steady_fast` fails with 548 ms of accumulated controller lag.
  The failed reach contains native frame 4213, lasting **501.35 ms**: its menu/
  manipulation phase is **134.39 ms**, including `publishEventState` at
  **134.35 ms**, and `xrEndFrame` takes **365.40 ms**. Those exclusive phase
  measurements explain the outer frame; the nested publication scope must not
  be added again. The publisher synchronously serializes/writes the event file,
  but wall time alone does not distinguish execution, I/O blocking and scheduling.
- `bend-surface-steady_fast` reaches preview and wheel interactions, but the
  commit feedback times out after **46.48 seconds**. A frame straddling the end
  of that interval lasts **13,069 ms** in the whole-session trace while applying
  scene revision 8. Native style diagnostics report 848,552 Surface boxes and
  a 1,238 ms upload during that adoption; inclusive `setStyle` reaches 2,126 ms
  elsewhere in the session. These are not additive measurements. Complete
  contained commit frames alone misleadingly remain near 89 FPS because the
  straddling stalled frame is excluded. The timeout and whole-session trace are
  therefore essential evidence of the full-size commit cost.

The compositor's GPU duration is a runtime timing measurement, not a hardware
utilization measurement. A long CPU interval and a long GPU timing span must
not automatically be labelled two independent bottlenecks or added together.

Optimization candidates should preserve selection and invalidation correctness:
accelerate the full-scene picking fallback using geometry/owner indices; avoid
rebuilding all geometry solely for selection coloring; and profile Quick Surface
preview updates separately from the stationary picking path. Re-test against
the retained full-size scenes and all four profiles after any production change.
The fallback currently picks the nearest object in the whole scene before
checking its ownership. An acceleration must preserve that occlusion behavior;
simply testing selected owners would change selection semantics. Invalidate its
spatial data for geometry, authored pose, simulation coordinates and preview
changes, and continue applying the current model/controller transforms.

## Input and measurement conditions


The authored source is `workspace/24hb_0xT.nadoc`: 24 helices, 76 strands,
6,720 nucleotides, seven existing nucleotide transforms, and one cluster covering
all 24 helices. SHA-256:
`bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
Both the earlier normal-render baseline and this tool campaign use that source.
The full-size tool fixtures preserve the authored geometry and existing poses.
Private workspace metadata and external loadout revision pointers are reset;
the original document is not edited. Extrude adds six helices to a private copy
and asserts that the original helices are unchanged.

Measurements use the physical OpenXR/SteamVR runtime and synthetic controller
profiles, not human wearer trials. The host has an RTX 3080 Ti, 12 GiB VRAM,
driver 580.178.04, and 1852 × 2056 eye buffers. The 90 Hz runtime budget is
11.1111 ms. Native rendering quality stays at production defaults. Tests run
sequentially, with no competing benchmark, build, or test suite.

The normal-render baseline uses an immutable 24HB snapshot without a browser
editing bridge, at an isometric overview. Tool sessions include the desktop
application and use operation-specific framing. Move includes a closer view
for selecting an individual nucleotide. These are different workloads and
views; their difference is not an isolated estimate of tool overhead.
View-volume workflows can draw a different representation inside the volume;
the per-frame representation column identifies the main scene. Captured state
retains those local overrides. Simulation results likewise have their own display
handoff. Native `renderVolumeScene` replaces the main scene when the view-tool
stream has a version and flags differ from 256. The per-frame representation
then still labels the main scene's selected style, not the overriding MD or
view-tool geometry. Later intervals record stream flags/version and override
state last observed at their boundaries, together with the observed native frame
number. Stationary intervals without observer requests retain the same last
observed state; these fields are not per-frame telemetry. Earlier intervals
require the captured state and mode logs. Do not treat an overriding simulation stream as a direct benchmark
of all four main-scene drawing styles.

The four representations are Full, Stick, Ball & Stick, and Quick Surface.
The four motion presets are `steady_fast`, `steady_deliberate`, `variable_fast`,
and `variable_deliberate`. Each final tool/profile case gets an independent
private session, so an earlier failure does not suppress later profiles.
Motion presets, deadline thresholds, and visibility thresholds are retained.
Completed reach reports retain seeds and sampled poses. A reach that raises on
its deadline retains the interval/error and native frame trace, but may lack its
partial controller samples. Additional setup reaches can change the later seed
sequence and path, so revised retries are separate diagnostic conditions, not
identical-input A/B measurements.
Stationary-after-representation windows can precede activation of the requested
workflow tool. `native_tool` is the native tool-shell mode at frame end, not a
complete set of auxiliary panel/overlay states; Nick/Ligate and other auxiliary
controls also require captured state and named stage evidence. A workflow label
alone is not proof that an edit or its tool-specific calculations occurred.

## Data interpretation

- `review.html` is an offline, filterable view of coverage, measured intervals,
  whole sessions and operation waits/failures.
  It defaults to baseline/stationary data and the latest attempt; earlier attempts
  remain available. It does not compute a pooled FPS score.
- `runs.csv` records workflow outcomes, source proofs, failures and raw log paths.
  `workflow_passed` reflects the tour's exit status; `audit_passed` additionally
  requires the recorder's trace/interval/representation coverage checks. A
  completed workflow with missing timing data is not a valid complete audit.
  Neither flag is a frame-budget pass.
- `coverage.csv` has one row per requested tool/representation/profile, selecting
  the latest chronological attempt and retaining the attempt count. An earlier
  pass cannot conceal a later failure.
- `intervals.csv` records complete contained frames, application cadence,
  frame-budget overruns, wall-time percentiles, and compositor GPU/repeat/drop
  observations. Representation is the actual frame representation, separately
  from the requested representation.
- `calculations.csv` records instrumented call counts and inclusive active-frame
  calculation timings. `phases.csv` records exclusive outer-loop wall phases.
  Inclusive calculation scopes overlap the phases and must not be summed.
  Calls count function entries, including inexpensive early returns; a call is
  not by itself evidence that geometry was rebuilt.
- `operations.csv` records named operation spans with an explicit latency
  definition. Move, Ligation and End Resize span release through acknowledgement;
  Bend/Twist also include acquiring/clicking Confirm. Nick's feedback wait starts
  after trigger input and its initial observation. Stationary intervals are
  deliberately timed observation windows, not commit latencies.
- `sessions.csv`, `session_calculations.csv`, and `session_phases.csv` retain
  whole-session measurements, including stalls that cross interval boundaries.
  They also contain capture and setup overhead and are labelled accordingly.

Application FPS is inferred from consecutive focused, submitted frame starts;
it is not headset scanout. Compositor samples have approximately 100 ms boundary
uncertainty. GPU time is not combined CPU/GPU time. Wall phases include driver
waits. A frame straddling an interval boundary is excluded, so operation latency
and the raw whole-session trace must be consulted for boundary stalls.
Acknowledgement is not a measurement of the first visibly committed frame.
Post-commit capture and persistence checks are separate gates. For example,
`twist-stick-steady_deliberate` acknowledges after a 17.11-second Confirm span,
then times out during post-commit observation; its whole workflow remains failed.
`runs.csv` also flags whether the log tail contains a native exit record. A
structurally valid trace does not by itself prove that shutdown's final frames
were retained. Later retry runs wait for owned cleanup before collecting logs.

OpenXR's predicted display period is adaptive: it reaches 44.444 ms in the
22.38 FPS Surface Move case. The CSV therefore includes the fixed 90 Hz target
(`target_budget_ms = 11.1111`) and recomputes target-budget misses from raw
frames. Columns mentioning the *reported runtime period* preserve the original
adaptive-period comparison; they are not the 90 Hz performance gate. Later
compositor samples also record the headset's `hmd_display_hz` property.

Captures and review holds are outside measured reaches. Whole-session summaries
retain setup, captures, waits, scene refresh and controller playback, but cannot serve as
clean FPS gates. Short reaches have fewer samples than stationary intervals;
their p95 values should not be treated as equally precise estimates.

Failed workflows remain failures even when useful timing data was recorded.
An operation with a recorded error measures time until that failure/timeout,
not a successful acknowledgement latency. A clean native process-end record
does not turn a preceding observer connection failure into a completed edit.
Missing GPU observations are empty, not zero. Zero calls to an instrumented
function do not establish that every internal calculation was eliminated.
Native calculation fields are sparse: an entered scope emits its counter.
The exporter infers zero only for a scope in the supplied source inventory and
a valid trace; unknown or invalid-trace missing counters remain empty.
A controller playback deadline failure reports accumulated schedule lag; it is
not, by itself, a native frame of that duration. Use native frame timings and
the stationary observation comparisons to distinguish rendering cost from
controller-driver and observation overhead.
Reach and commit intervals can overlap, and an interval can contain more than
one actual representation or tool. Summing their frame counts or compositor
totals would double-count observations; use whole-session data for unique frames.

## Setup revisions and retained failures

Early full-size attempts exposed assumptions in the smaller test fixtures:
lazy feature-history placeholders differed from the complete saved history;
UI-decorated geometry differed from the authoritative geometry after Undo;
End Resize could clear its selected arrow after commit; and a held Bend/Twist
handle deliberately makes `ready` false. The audit now reads complete history
and authoritative geometry, checks committed geometry independently of a cleared
arrow, and includes captured handles in its layout check while they are held.
These corrections do not turn earlier failed workflows into passes.
The initial Dimensions shutdown assertion also checked the pending journal only
0.3 seconds after the asynchronous stop request. One retained journal entry
exactly matches the saved document. The corrected check waits for the owned
cleanup to finish before checking the journal and reopening the document; the
early assertion is not evidence of a lost measurement.
The first two Full Move steady-profile attempts also expose a missing import in
the audit's commit-latency recorder. The import is corrected for later cases;
these attempts are harness failures and require separately recorded retries.
Full Ligation's original negative target is only 14 mm from a compatible end;
the tool legitimately picks that neighboring end. Later fixtures choose the
same-polarity endpoint with the largest clearance from compatible ends (132 mm
in the inspected case), using live geometry. They retain the original selection
radius, motion profile, no-target assertion and no-edit assertion. Earlier
negative-target failures are not classified as application defects.

The owned mirror is enlarged for observation, without changing eye rendering.
Dimensions panel placement can be adjusted using captured molecular bounds and
an ordinary border grip; the original and adjusted captures use the same pixel
oracle. Occluded features, missed targets, late motion, persistence failures and
failed commits remain reported boundaries.
Later Nick cases can choose a controller observation pose that clears captured
molecular pixels in both eyes, using the same motion profile. The model and head
remain fixed, and both original and adjusted captures are retained. Full Nick
initially failed because the candidate search considered only the occupied right
side. Later diagnostic candidates include positions across the front of the
body and above the model; the original quiver gesture endpoints remain fixed.
The controlled Full Nick steady-fast case reaches the analog preview but fails
scissors/glow visibility in the right eye. Its original bond was selected by
array index. Later cases select the nearest bond with room for scissors in both
captured eye views. This is a framing heuristic, not proof of visibility: the
unchanged stereo/mirror pixel oracle and offscreen negative still decide the
result. That first adjustment makes the bond glow visible in both eyes in
variable-deliberate, but the scissors still fail coverage. A later setup also
requires the predicted open blade samples to clear captured molecular pixels.
Closed-blade visibility cannot be established from background clearance because
the blades converge on the bond; all three squeeze states still use the same
pixel oracle. Original and target-setup captures are retained. The four earlier
Full cases are repeated separately in
`vr-24hb-audit-nick-observation-retry-20261002` after another successful runtime
reset. All four final-setup retries still fail `open: scissors or bond glow
missing`; none establishes a completed cut/Undo/Redo workflow. These are the
latest Full Nick coverage records, and the original attempts remain retained.

Representation setup is recorded per case. Initial attempts used profile-driven
menu navigation or a native display feedback update. Later setup uses ordinary
trackpad focus and trigger input, with the desktop style acknowledgement. For
Bend/Twist, schematic plane acquisition happens in Full; an owned loopback
Playwright bridge invokes the existing desktop native-style handler before the
requested representation is measured. Direct plane acquisition in atomistic
styles is not covered by that setup.

Later `steady_fast` cases also pair a stationary interval without observer
requests with a stationary interval that continuously observes native frames.
These pairs quantify observer overhead in the same scene; they are not motion
trials and do not replace the unchanged controller-profile checks.

Available full-size simulation evidence uses an existing completed NAMD job.
Trajectory files are immutable inputs; metadata and writable caches are private
copies. No new simulation is computed. Other simulation engines lack equivalent
completed 24HB fixtures and are not covered by this dataset.
The selected NAMD topology contains 6,720 nucleic-acid residues and 1,320,174
atoms including solvent. Its historical job has no design fingerprint or revision
identifier, so this proves full-size molecular coverage, not exact conformation
identity with the current source. Surface and Full simulation cases reach the MD display
but fail native navigation to `sim:frame`; later result modes and playback are
not established by those cases.
The controlled repeat uses an ordinary profile-driven ray click on the separate
Frame result footer button. It does not change native touchpad focus rules or
erase the earlier navigation failure. This setup adjustment is specific to
simulation result framing and is recorded separately from measured controller reaches.
This existing simulation tour validates static result modes; it does not drive
trajectory animation. Dynamic MD trajectory playback remains outside its
coverage even if all static-mode checks pass.

## Reproduction

Final focused validation: **76 Python tests pass** across the recorder, dataset,
runtime recovery, motion/control and observation checks; **10 JavaScript syntax
checks pass**; undefined-name lint and `git diff --check` pass. A real headless
Chromium check verifies all four offline table modes, representation and combined
tool/profile filters, pagination, latest-attempt filtering, and all four loaded
baseline images, with no page errors. The resulting page is also visually
inspected. Logs and the screenshot are included with the export.

The original source hash remains unchanged after collection. Native binary
SHA-256 is `f553e46a0d5c5b947a7f0f36d173ea7ea47c83a9e8bf08f65c40d3f096137649`;
its October 1 22:07 MDT build predates the full-size campaigns. Provenance records
git HEAD, current source hashes/copies, binary and snapshot hashes, hardware,
4,096-byte host pages, resets and per-case resources. The final source snapshot
does not retroactively replace earlier harness versions; setup revisions are
documented above. Two early simulation attempts have source-path/count proofs
but no contemporaneous source hash, so their per-run hash remains empty. Other
early proofs can lack a nucleotide-count field; missing proof fields are not
invented from current state.

The runner refuses to compete with another active viewer. With the headset
runtime available and no other viewer running:

```sh
uv run python -m tools.vr_workflows.tool_frame_audit \
  --design workspace/24hb_0xT.nadoc --validate \
  --restart-runtime-between-representations --min-available-gib 8 \
  --output .development-artifacts/vr-24hb-audit-new
```

This requests 12 workflows × 4 representations × 4 motion profiles. A nonzero
exit is expected if any workflow fails; it does not invalidate all recorded
intervals. Inspect each trace-validity and coverage field independently.

The fresh baseline is retained at
`.development-artifacts/vr-24hb-baseline-controlled-20261002/`, with its source
proof in that directory's `source-proof.json`. It reuses the immutable snapshot
whose original export proof is
`.development-artifacts/vr-frame-audit-20261001-selective/export.json`.
Full-size pilot attempts are retained at `vr-24hb-audit-smoke`,
`vr-24hb-audit-initial`, and `vr-24hb-audit-stick-continuation` beneath
`.development-artifacts/`. The four-profile campaign is
`.development-artifacts/vr-24hb-audit-validation/`. The controlled repeat is
`.development-artifacts/vr-24hb-audit-controlled-retry-20261002/`.
