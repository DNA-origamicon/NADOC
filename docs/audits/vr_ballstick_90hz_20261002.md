# Full-size Ball & Stick 90 Hz optimization campaign

**Collection and verification finished; the 90 Hz editing goal remains unmet.**
User-directed time box: 2026-10-02 16:00:40–18:00:40 UTC
(10:00:40 AM–12:00:40 PM MDT). Target: consistent 90 Hz / 11.111 ms while
editing the full 24HB. Maximum two optimization candidates per workflow.
Quick Surface performance is excluded. No geometry or visual-quality reduction
is authorized by this experiment.

Source: `workspace/24hb_0xT.nadoc`, 24 helices, 76 strands, 6,720 nucleotides;
SHA-256 `bc51978e952aeaf7880c3892fa47ade2105eedd08b17ad25706709422ef7f45f`.
Tests use private copies, physical OpenXR and synthetic controller profiles.
Extrude starts with the full 24HB and adds a six-helix part; that part size is
not the size of the input origami.
This is not wearer comfort or through-lens validation. Captured eye resolution
remained **1852 × 2056** in both candidates and the fresh baseline; the GPU is
an RTX 3080 Ti 12 GB and the CPU is a Ryzen 9950X.

The [compact review ZIP](../../.development-artifacts/vr-ballstick-90hz-20261002-review.zip)
contains the feature table, CSVs, final patch, provenance and representative images.
Raw logs/captures remain in the local archive.

Evidence root: [campaign artifacts](../../.development-artifacts/vr-ballstick-90hz-20261002/).
Earlier [full-size dataset](vr_24hb_tool_performance_20261002.md) and
[calculation inventory](vr_frame_calculations_20261001.md) remain available.

Follow-up: [bottleneck isolation and optional desktop drawing](vr_bottleneck_isolation_20261002.md) distinguishes desktop contention, native GPU deadline misses and synchronous selection/scene-refresh stalls.

## Two optimization candidates

1. Skip irrelevant fragment lighting in emissive and depth-only passes.
   Full-size isolated renderer output was byte-identical in all four captured
   modes; parity tests passed. GPU and serial frame cost did not materially
   improve. All 12 `steady_fast` workflows were attempted. This change was
   **reverted** before candidate 2.
2. Keep already transformed packed geometry on the first eligible Move commit
   and restore exact saved instance values on Undo, avoiding a full style
   rebuild. Periodic mirror diagnostics use one bounded pixel-pack buffer and
   a zero-timeout fence poll, retaining source-frame metadata. All three native
   checks passed for that measured bundle, and its complete 48-case/four-profile
   matrix finished. **The readback sub-experiment was then reverted**: a controlled
   idle comparison found only a 0.19 ms median reduction per diagnostic sample
   (once per 30 frames), without a submission-rate gain. The final retained code
   contains **only packed Move commit/Undo reuse**. Removing the unsuccessful
   sub-experiment is followed by final-build verification, not a third optimization
   candidate. The exact measured bundle and binary remain archived.

The packed commit shortcut is conditional: an existing committed layer, changed
owner/style or refreshed scene can still require the old rebuild path. It is
not a general elimination of commit stalls. The discarded asynchronous diagnostic queue
never overwrites a pending sample and rejects failed/corrupt readbacks. Its
reported readback CPU cost spans enqueue and completion frames; it is not a
single frame's wall time or GPU latency.

## Observation conditions and limits

The first candidate's browser remained focused and rendered about 60 desktop
frames per second during native VR. Thus its GPU timings include possible
contention from the desktop. Earlier audit tool runs using this same browser
setup must also be interpreted with that limitation; standalone baselines have
different workload conditions.

Several candidate-2 setup checks failed before reaching measured tool motion:
activating the PID-verified native window did not clear Chromium's reported
page focus. These failed setup trees are retained. They are harness diagnostics,
not extra production optimization candidates. Native candidate-2 code remains
unchanged throughout them. The separate minimized-browser diagnostic reached nominal 90 Hz during selected
single-nucleotide Move, but Cluster Move remained near 45 Hz and timed out in
COMMITTING. Hidden-window animation callbacks paused. This observation condition
is unsuitable for complete authoring and cannot establish dynamic trajectory
performance. Cluster transform restore/commit paths in
`frontend/src/scene/translate_rotate_tool.js` explicitly await two
`requestAnimationFrame` callbacks (restore at line 456, edited-cluster commit at
line 504, ordinary dirty-cluster commit at line 570), providing a concrete dependency on desktop animation progress. The temporary Playwright dependency modification and focus/minimize
harness changes were restored/removed; their exact source is archived under
`focus-experiment-source`. Production render policy and quality were unchanged.

The accepted second-pass comparison uses the original desktop-active condition
(`attempt2-live-comparable`). The separate `attempt2-real-background-live` results
must not be substituted for it. In that diagnostic, single-nucleotide Move passed
edit/save/reopen/Undo: selected idle was 89.53 FPS, two motion reaches were 89.53
and 88.22 FPS, and commit was 84.67 FPS with four long submission gaps. Its largest
commit frame was 22.37 ms, compared with 307.04 ms in candidate 1. The earlier
281.57 ms setStyle call was absent from that commit. Desktop workload also changed,
so the entire speedup cannot be attributed to C++ optimization.

Application FPS measures focused submitted frame cadence, not headset scanout.
A roughly 89.5 FPS mean can represent nominal 90 Hz pacing on this runtime;
long frame gaps, work-budget exceedances and compositor repeats/drops must also
be considered. A workflow correctness pass alone is not a 90 Hz performance pass. Variable-profile
Move target-acquisition and cluster remote-grab failures also occurred in the
earlier controlled full-size audit (`prior-variable-acquisition.json`); they
are not newly observed failures of the retained candidate.
An early tool failure leaves later operations unverified. Repeated failure after
two candidates does not establish a fundamental hardware limit.

## Results

Both optimization candidates have completed the initial `steady_fast` pass for
all 12 workflows. Candidate 2 also completed the remaining three
profiles: 48 cases total, eight complete workflow passes. These are further observations of the same unchanged candidate, not
additional optimization attempts. The table below describes that fully measured bundle before the unsuccessful
readback sub-experiment was reverted. Final retained-code verification is reported
separately. A running/aborted case cannot count as a completed workflow.

All rows below remain unresolved for **consistent 90 Hz across all operations**.
FPS ranges are separate measured Ball & Stick motion/menu/commit intervals,
not pooled averages and not necessarily the final edit stage. Max frame includes
all contained Ball & Stick intervals, including stationary observations. A
workflow can pass correctness while failing performance. Early failures leave
later edit/commit/Undo stages unverified. Neither a failed workflow nor an
unmeasured stage establishes a rendering bottleneck by itself.

| Feature | Optimization candidates | Measured interval FPS range | Longest frame (ms) | Complete workflows / profiles attempted | Remaining issue |
| --- | ---: | ---: | ---: | ---: | --- |
| Move/rotate nucleotide | 2 | 44.78–56.08 | 33.70 | 2 / 4 | Sustained rate and frame gaps despite fast eligible commit |
| Move/rotate cluster | 2 | 39.58–44.76 | 33.75 | 2 / 4 | Preview/upload/draw cost and frame gaps; repeated-commit fallback remains |
| Bend | 2 | 43.57–44.77 | 838.00 | 0 / 4 | Sub-90 cadence; 838 ms selection/style rebuild stall; workflow incomplete |
| Twist | 2 | 44.62–44.77 | 33.77 | 0 / 4 | Sub-90 cadence; workflow incomplete |
| Extrude / subsection | 2 | 47.96–90.14 | 33.69 | 0 / 4 | Occasional gaps and controller-profile failure; later stages incomplete |
| Nick | 2 | 48.23–54.05 | 33.58 | 0 / 4 | Sub-90 cadence; controller/visibility gate can block edits |
| Ligation | 2 | 46.20–54.95 | 33.48 | 0 / 4 | Sub-90 cadence; later edit stages incomplete |
| End Resize | 2 | 46.43–89.56 | 4211.52 | 0 / 4 | 4.21 s commit/input stall; timing gate and known resize-sign issue |
| View Tools | 2 | 47.38–56.52 | 33.55 | 0 / 4 | Sub-90 cadence; toggles beyond failure remain unverified |
| Simulation result controls | 2 | 45.79–49.15 | 33.55 | 0 / 4 | Sub-90 cadence; static-result tour only, not trajectory playback |
| Dimensions | 2 | 86.85–89.60 | 22.40 | 4 / 4 | Mostly nominal cadence with occasional long frames |
| View Volumes | 2 | 44.77–46.28 | 23.71 | 0 / 4 | Sub-90 cadence; workflow incomplete |

The complete operation rows, profile names, errors and raw-case paths are in
[cases.csv](../../.development-artifacts/vr-ballstick-90hz-20261002/cases.csv) and
[intervals.csv](../../.development-artifacts/vr-ballstick-90hz-20261002/intervals.csv).
These preserve failures and do not pool overlapping intervals into a misleading
single FPS number. The baseline and minimized-browser experiment are separate.

### Browser-free normal viewing

Candidate 2 passed all four profiles: **12 idle/grip intervals, 4,612 frames**,
89.51–89.57 application FPS, zero gaps over 1.5 × the fixed 11.111 ms budget,
zero frames exceeding that budget after subtracting named runtime waits, and
zero sampled compositor repeats/drops. Compositor GPU p95 ranged 7.26–7.45 ms.
This supports nominal 90 Hz for normal viewing/whole-model grips under these
conditions, not every editing operation or physical wearer comfort.

The live asynchronous diagnostic trace contains 173 samples, all completed one
frame after their source frame with consistent source/completion metadata and
zero readback errors. CPU transport plus assessment cost was still 4.10 ms median
and 5.43 ms maximum across enqueue/completion frames. PBO use is not proof that
every driver readback call is stall-free or that diagnostics became cost-free.

### What improved and what remains

The extended profiles also exposed two major remaining stalls. End Resize's
`variable_fast` commit contained a **4,211.52 ms** frame, with **4,187.00 ms** in
the native input/application phase and a 763.63 ms inclusive style scope.
Bend's `steady_deliberate` selection contained an **838.00 ms** frame: selection
candidate processing was 834.79 ms, including a 427.14 ms hit-resolution scope and
a 400.87 ms style scope. Capture phases were not the source of these stalls.
Scopes overlap and are not summed. A long final frame can also outlast the
interval's last observed submission-start gap, so FPS alone can hide this cost.


In comparable `steady_fast` runs, single-nucleotide Move commit lost its 281.57 ms
style rebuild and cluster commit lost its 704.50 ms rebuild. Largest measured
Ball & Stick frames changed **307.04→33.53 ms** and **715.11→33.75 ms** respectively.
Both complete workflows passed edit/save/reopen/Undo. These are individual-run
observations, not a statistical guarantee; sustained cadence still missed 90 Hz.

Cluster preview still incurred an inclusive packed-preview update of up to
5.99 ms in this run. Eligible commit feedback still had a 12.48 ms phase maximum.
These calculation/phase scopes overlap; do not add them or add CPU wall time to
compositor GPU spans. Dense selected rendering, desktop contention, packed-buffer
updates and fallback rebuilds remain plausible software targets. VR transaction completion
must also be decoupled from desktop animation waits before hidden-window draw
suppression can safely cover every authoring path. No fundamental
hardware/software limit has been established within two candidates.

Changes to shader geometry/quality were not retained. Only the eligible Move commit/Undo change remains local and uncommitted;
the periodic readback experiment was reverted after the control comparison. Surface frame-rate
work was excluded. End Resize's previously observed sign issue was not changed.
Full/Stick editing, active simulation compute and dynamic trajectory playback were not revalidated in this
Ball & Stick time box. Repeated commits that bake an existing layer, representation
changes and selection/owner invalidations can still rebuild; those paths are not
claimed to achieve 90 Hz.

### Readback control and final retained build

The 30-second idle A/B control used the same full-size snapshot and unchanged
rendering settings. Each run supplied 90 diagnostic samples in the idle interval.

| Diagnostic path | Median sample CPU (ms) | p95 (ms) | Idle application FPS | Long submission gaps |
| --- | ---: | ---: | ---: | ---: |
| Original synchronous path | 4.323 | 5.071 | 89.527 | 0 |
| Experimental asynchronous path | 4.132 | 4.782 | 89.493 | 1 |

The ~0.19 ms median difference occurs once per 30 frames and did not establish a
cadence benefit. The added PBO/fence transport was reverted rather than retained
as a claimed performance win. This also shows why the successful earlier
12-interval baseline is a bounded observation, not a guarantee of zero future
jitter. Source/completion metadata correctness of the experiment is preserved in
its trace and native test evidence.

Final retained code keeps only the eligible packed Move commit/Undo optimization.
Two native tests and 14 timing-audit tests pass. The following fresh physical-VR
checks use the final binary after readback rollback; they are cleanup verification,
not a third optimization candidate. The full 48-case table above remains explicitly
attributed to the earlier measured bundle.

| Final-build check | Workflow passed | Measured interval FPS range | Longest frame (ms) |
| --- | --- | ---: | ---: |
| Move/rotate nucleotide | True | 44.76–60.03 | 33.66 |
| Move/rotate cluster | True | 38.73–44.77 | 87.12 |


All recorded CPU phases and inclusive calculation distributions are exported in
[phases.csv](../../.development-artifacts/vr-ballstick-90hz-20261002/phases.csv) and
[calculations.csv](../../.development-artifacts/vr-ballstick-90hz-20261002/calculations.csv).
The latter includes timings on frames where the calculation actually ran, so
rare rebuilds are not hidden by zero-valued inactive frames. Compositor spans and
repeat/drop counters are in
[gpu-spans.csv](../../.development-artifacts/vr-ballstick-90hz-20261002/gpu-spans.csv).
The calculation inventory describes uninstrumented boundaries; this is not a
per-instruction GPU profile or proof that every possible edit sequence was covered.
