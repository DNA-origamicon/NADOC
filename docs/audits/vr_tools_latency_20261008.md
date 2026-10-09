# VR Nick, Ligate, Bend, Twist and Sweep latency — 2026-10-08

This audit follows the resize optimization. Evidence is retained under
`.development-artifacts/vr-tools-latency/`; the original resize evidence and
uncommitted implementation are preserved. Measurements use actual OpenXR/Vive
controller input, production browser mutations, canonical native scene export,
rendered stereo/mirror checks and independent compositor timing.

## User fixture correction

The user explicitly excluded `Circle_spiral.nadoc` from further tests. Bend had
already switched to the independent straight 24-helix bundle after its rejected
Circle diagnostic. On receiving the correction, the remaining Circle campaign
was stopped; the in-progress Nick case exited 130 before any reach. All further
final measurements use the independent **24-helix, 48-strand, 12,000-nucleotide
straight bundle**, with zero input deformations, forced ligations or feature
history. Its SHA256 is
`94058dfa359eff20c263caf62fac39f657b374a40d9c07a0e5b4b6550d7ce7f2`.
Historical Circle trials below remain diagnostic evidence only, not final
fixture acceptance. No further Circle runs are scheduled.

## Workloads and measurement boundaries

Historical baseline Nick, Ligate, Twist and Sweep trials used
`workspace/Circle_spiral.nadoc` (24 helices,
11,997 nucleotides; SHA256
`8b13f60d26fd56ce7250da7de4d6b4e7248f66ffffa099e528f28064275f458e`).
Bend and all final five-tool trials use a generated, independent
24-helix / 12,000-nucleotide straight bundle,
retained as `bend-12000.nadoc`. Circle's existing overlapping bends correctly
reject the tour's fixed-endpoint Bend commit. No scientific guard was relaxed.
Switching off manual manipulation does not clear fixed endpoints; the proposed
numeric-mode workaround was discarded before relying on it.

`operation_latency_ms` includes the whole measured workflow (including reaching
Confirm for Bend/Twist/Sweep). `input_to_ready_ms` measures from host dispatch of
the final edit input to observed native completion, where available; dispatch is
not a hardware trigger timestamp. For Confirm button clicks this is the final
button edge (release); the press can already have initiated the mutation tens
of milliseconds earlier (38 ms in the straight steady-fast Twist trace). These
are approximate interaction timings, not an exact button-down latency claim.
Native completion requires scene revision
advancement. Compositor polling boundaries have roughly 100 ms uncertainty.
`input-window-summary.py` additionally re-attributes complete native frames and
compositor samples to that final-input-to-ready window, leaving the original
whole-operation reports intact. Whole-operation timing also contains the
controller approach to Confirm, so its hitches cannot automatically be assigned
to mutation/export work.
Captures/review pauses stay outside edit intervals. Desktop 3D drawing uses the
normal VR preference to yield resources, while desktop state synchronization
continues. The four existing motion presets and visibility thresholds remain
unchanged. In the two steady Sweep cases, the observed whole-operation drops
preceded the final Confirm input; the deliberate case's drop samples were ~766 ms
before it. Both steady Sweep input-to-ready intervals had zero repeated/dropped
frames and ~89.53 FPS. The pre-commit hitches remain in the original reports;
this timing distinction is not a claim to have fixed them.

## Diagnosis and implementation

The browser waited for desktop geometry synchronization before requesting native
scene export. Twist's initial Circle trace spends about 1.2 s fetching desktop
geometry, followed by about 1.8 s exporting the native scene. These stages can
overlap because the mutation response already identifies the committed design
and revision. Export still uses canonical geometry in a separate CPU process;
native publication, revision checks and bounded GPU uploads remain intact.
The shared refresh request also bypasses the unrelated async simulation-preparation
step (VR publication never requests a simulation projection). Without this, the
nominally early request yielded before `fetch`, allowing synchronous desktop
subscribers to delay its dispatch. A client test verifies immediate dispatch.
Nick/Ligate and their history requests can use the existing `X-NADOC-Skip-Geometry`
contract; complete desktop geometry is still fetched and applied, concurrently
with native export.

Sweep previously returned full geometry for an independent addition. The
existing desktop partial-geometry path can update only new helices and axes.
Continuation or ligation that changes existing strands must retain the full
response. Geometry parity is checked against the complete response, including
nucleotide metadata, authoritative poses and axes.

### Redundant view-tools atlas found during the profile matrix

The first deliberate Ligate trial with corrected viewing passed functionality but
failed the performance objective: 3.68 s and 72.82 FPS for one commit. One native
frame spent **640.4 ms in `feeds_view_tools`** (649.2 ms total), with 50 dropped
compositor frames across the two commits. GPU scene staging itself stayed around
1 ms. The retained `final-ligation-steady_deliberate-framed` case is not accepted
as a framerate pass. The phase includes other auxiliary feeds, so this evidence
alone does not identify the precise blocked syscall or GL call.

Inspection found unnecessary work in that phase: the browser republished the
entire 2048×2048 RGBA view-tools atlas after every design/geometry change even
when `flags == 256`, where native canonical geometry is displayed and the atlas
contains only the unchanged tablet. Normal-mode edits now keep that existing
atlas and skip scene fingerprint traversal. Real overlay/layout streams still
follow geometry/design changes, and explicit actions/reset still publish.
Regression tests cover all three behaviors. A new `atlas-*` profile campaign
checks publication counts and native timing; earlier profile results remain
retained rather than being relabeled as final evidence. Its first deliberate
Ligate run made exactly one view-tools publication at startup and none during
both commits. Atlas versions stayed constant; maximum feed-phase time fell to
0.083/0.032 ms, input-to-ready to 2.640/2.642 s, and cadence to 89.53 FPS with
zero dropped frames (one repeated frame per commit). This supports removal of
the redundant update as a practical fix; it does not identify the exact syscall
behind the earlier isolated 640 ms wall-time sample.

## Observation failures retained

- Original full-size trials exposed inspector overhead: repeatedly formatting
  and transferring the entire Nick bond catalog delayed controller playback.
  Motion observations now omit that catalog; explicit `observe targets` and
  capture evidence include it. Serialized positions are cached by catalog
  version, model transform and bond count. This changes observation transport,
  not controller behavior or molecular geometry.
- A stale native object initially omitted the new observation command. A clean
  recompilation after the final source edit resolved the protocol mismatch.
- One runner retry omitted Node from PATH and failed before launching a viewer.
  Subsequent browser runs retain the normal Node environment; native builds use
  the established system compiler environment.
- The small Ligate fixture's empty-space point overlapped valid Circle termini.
  The imported-design probe now chooses a point toward the eye, clear of the
  actual endpoint catalog. Both unchanged preview and committed-bond pixel
  checks passed in the baseline, for both endpoint polarities.
- Nick's small-fixture framing placed the eye inside Circle. Imported designs
  use a farther normal scene-grip placement. Target choice uses frontmost
  stereo-framed geometry; a background molecular pixel behind a blade is not
  automatically an occluder. Actual scissors/glow pixel checks remain decisive.
  Frame audits omit the independent quiver/tablet demonstration; ordinary tours
  still run it.
- The final Ligate trial initially began its second polarity before the previous
  desktop Undo's published scene finished loading. Its no-edit assertion then
  observed that late Undo revision during a correctly cancelled gesture. The
  tour now waits for the returned published revision before the next trial.
  `candidate2-ligation` retains the failure; no gesture threshold was changed.
- Deliberate Ligate's empty-space pull pointed almost straight toward the eye:
  both eye checks passed, but mirror coverage was zero after downsampling. The
  imported-design probe now chooses a clear point with a transverse component
  and at least 80 eye-pixel projected span, inside both eye views. This is a
  recorded observation adjustment outside the commit interval; pixel thresholds,
  controller presets and production hit geometry are unchanged. The original
  failure is retained under `final-ligation-steady_deliberate`; the framed retry
  is a separately named case.
- The independent view-tools overlay tour initially captured a tablet behind
  the head: its quiver gesture opens at the invoking controller's pose under
  current placement behavior. The probe now records that original placement,
  derives tablet orientation from live tile centers and uses an ordinary border
  grip to bring it into the eye view. No head pose, panel scale, hit geometry or
  pixel threshold changes. `atlas-view-tools` retains the original failure.
  The first framed attempt hit a 349 ms playback delay during quiver opening;
  the next used the same headed/Desktop-3D-off observation condition as the
  latency runs. Its tablet was correctly moved but occluded by the molecule
  (75% eye coverage), so the review placement was moved in front of the model.
  Length on/off and Sequence acknowledgement subsequently worked, but the
  checker still reported 75% coverage. Moving the model right and farther back
  ruled out the suspected occlusion: the pixel mask omitted the actual active
  Sequence green and Deform orange. The checker now reads the exact active icon
  colors from the UI definition, retaining the 80% coverage threshold and
  offscreen negative control. The complete overlay tour then passed
  (`atlas-view-tools-palette`). All attempts retain their original pixel verdicts.
- The first straight-bundle Nick run presented the scissors edge-on; the
  blades were obscured in the right eye (1/6 samples), although glow was visible.
  The retry uses an ordinary 90-degree wrist rotation about the same cut center
  to face the blade plane toward the observer. All open/half/almost squeeze
  stereo/mirror checks and their offscreen negatives then passed, followed by
  cut, Undo and Redo (`straight-nick-steady_fast-faced`). The failed original
  remains retained; no target/hit geometry or threshold changed. The deliberate
  retry exposed another observation limit: nearly closed blades obscured the
  tiny glow in the downsampled mirror, while both eyes passed. Size-derived
  model distance (~0.912 m here) alone did not solve it. The final wrist pose
  additionally derives blade orientation from the projected bond so the glow
  remains visible beside the blades. All failed and adjusted views are retained.
- The straight-bundle Ligate negative trial's most isolated same-polarity end
  was only 24.1 mm from a compatible end, inside the unchanged 25 mm sphere.
  Motion jitter explained its inconsistent pass. The final negative pose is
  12 mm from a same-polarity end and at least 32 mm from compatible ends; its
  exact clearance is recorded. Both polarities then pass no-target/no-edit
  assertions without changing the selection radius or molecular endpoints.
- Variable-fast Twist committed successfully but its first Undo was refused
  with HTTP 404, "Nothing to undo." The retained browser trace shows a later
  autosave forked the project ID: the helper's synthetic import filename differed
  from the actual browser autosave destination. Save As correctly clears history.
  The import helper now uses the browser's test-owned workspace destination and
  waits for New Part's initial save to establish that destination (the modal
  hides before its save completes), and completes a public save before launching
  VR, so identity initialization occurs
  before any measured edit. The original failed case is retained and the retry
  is separately named `straight-twist-variable_fast-identity`.
- The first variable-deliberate Sweep run stopped before commit: its ray to
  control point 1 passed through point 0's nearer pick sphere. Native hover
  correctly reported point 0. The retry derives a side approach with >30 mm
  clearance from the other point, retaining the native 16 mm point-ray radius,
  pixel assertions and motion presets (`straight-sweep-variable_deliberate-clear`).
- The first generated Bend fixture needed the normal default-cluster migration
  before the import parity assertion. Both fixture versions are retained.

## Validation and results

Initial results (not final acceptance):

| Tool | Baseline | First candidate | Boundary |
|---|---:|---:|---|
| Nick | 3.27 s | 3.36 s | Final trigger dispatch to native completion |
| Ligate | 3.09–3.29 s | Motion trial interrupted | Trigger release to native completion |
| Bend | 3.95 s | 2.72 s | Final Confirm input to native completion; 12k bundle |
| Twist | 5.26 s | 7.64 s | Whole operation including Confirm reach |
| Sweep | 5.66 s | 4.56 s | Whole operation including Confirm reach |

Sweep mutation HTTP time fell from 1,750 ms to 349 ms. Nick's first candidate
still paid for the embedded desktop payload before starting export. The next
candidate uses the existing geometry-free mutation contract and fetches desktop
geometry in parallel. The combined candidate campaign reached a 6,442,713,088-byte
scope memory peak against a 6 GiB high-water limit; later cases need isolated
reruns under the same limits before interpreting their regression. The failed
campaign is retained rather than discarded.

Nick's existing history assertion assumed an empty document (Circle already had
one Nick child). It now asserts exactly one newly added child by identity. The
pending radial indicator remains visible during Undo/Redo; probes assert its
pending action and eventual clearance rather than requiring it to disappear
before acknowledgement.

Focused checks: 71 frontend tests passed; 53 backend tests passed with 8 native
transport tests skipped without their opt-in executable. Native Ligation passed.
The live application harness passed the new catalog checks but subsequently
failed an existing Move-panel Undo expectation: Move now uses document history,
while that assertion expects the older tool-specific transaction/haptic path.
Its previously stale radial-pending assertion was corrected; cancellation also
now tolerates a not-yet-created GL scene. This unrelated Move expectation remains
an explicit validation limitation; it was not resolved in this task.

Final non-circular profile measurements are collected in `final-summary.json`,
generated by `final-summary.py` in the evidence directory. Only `straight-*`
cases and the same-fixture `atlas-bend-steady_fast` case contribute. Earlier
`final-*`, `candidate*` and other `atlas-*` edit cases are historical diagnostics;
their names do not imply acceptance under the corrected fixture policy.

All **20 tool/profile combinations passed** on the straight bundle, covering
24 commits (Ligate tests both polarities) plus 8 Nick Undo/Redo operations.
Approximate final-input-to-ready and frame measurements for the commits:

| Tool | Four-profile latency range | Submission FPS range | Repeated / dropped frames |
|---|---:|---:|---:|
| Nick | 1.86–1.92 s | 89.52–89.54 | 1 / 0 |
| Ligate | 1.91–2.02 s | 89.03–89.55 | 23 / 3 |
| Bend | 2.39–2.52 s | 89.51–89.53 | 0 / 0 |
| Twist | 2.03–2.16 s | 89.52–89.53 | 0 / 0 |
| Sweep | 2.14–2.22 s | 89.51–89.53 | 0 / 0 |

Bend’s matched straight-bundle baseline was **3.95 s**: the resulting 2.39–2.52 s
range is a ~36–40% reduction. The other tools’ historical Circle baselines are
not paired comparisons against this different fixture. The measured short-term
1–3 s target is met here; sub-second completion is not achieved and larger or
more complex designs are not covered by this final matrix.

Across the 24 commit intervals, maximum non-runtime-wait native wall time was
6.18 ms (11.11 ms frame budget), maximum per-case GPU p99 was 5.71 ms and the
largest GPU sample was 8.02 ms. These are separate measurements, not additive
CPU+GPU execution costs. The 24 repeats and 3 drops remain explicitly reported;
normal cadence does not establish perfect frame delivery or through-lens comfort.
Nick’s one repeat falls in the slightly wider final-input window; the earlier
whole-operation report began after that input and reported zero.

The original Nick history captures immediately preceded wheel release. Their
wider input windows contain 46 dropped and 36 repeated compositor frames across
eight Undo/Redo operations; in the inspected steady-fast case, drop samples
landed 21/28 ms after release and native stalls were in `xrEndFrame`. A separate
control inserts a 350 ms diagnostic hold after the wheel capture, **before** the
timed release, with no production-code, motion-profile or threshold change.
`straight-nick-history-capture-control` passes cut/Undo/Redo at 1.87/1.81/1.97 s,
~89.52 FPS, zero repeats/drops, and maximum non-runtime-wait wall time 3.77 ms.
This supports capture/readback carryover and compositor polling-boundary effects
as the cause of those immediate history samples. It is one steady-fast control,
not a claim that all four history profiles were remeasured without capture
carryover. Original history evidence and all pre-Confirm Sweep hitches remain.

All 32 edit/history intervals retain the unchanged Deform-mode tablet atlas.
Maximum validation-scope peak memory was 5,235,724,288 bytes, below the existing
6 GiB high limit, with no high/max/OOM events in the accepted cases.


The shared immediate-dispatch correction initially passed a full-size resize
regression at 2.64/2.86 s. After atlas reuse, the repeated check passed at
**2.64/2.75 s**, with zero repeated/dropped commit frames, Undo and retained
selection (`atlas-resize-regression`).
This is one steady-fast regression, not a replacement for the preceding resize
four-profile campaign.

Historical browser resource timelines establish the overlap directly: steady-fast
Nick's mutation returned in 26 ms; native refresh began immediately and took
1.73 s, overlapping its 970 ms desktop geometry request. Twist's deformation
returned in 24 ms; its 1.84 s native refresh overlapped 1.23 s desktop geometry.
Sweep's final mutation took 463 ms and export 1.91 s. HTTP duration is not the
input-to-visible-completion measurement; native loading/activation and final
feedback account for the remaining latency.


### Complete software validation

`just test-smart` selected **FAST**: 10,296 passed, 90 skipped, 96.91 s.
The initial archive temporary path caused two Unix socket path-length failures;
using an explicit short pytest base directory fixed them without changing tests
or production transfer behavior. The native IPC server entry point now runs
independently of unrelated panel unit assertions, retaining the full native unit
entry point separately. Both native catalog and Ligation CTest checks passed.
The final frontend suite after atlas reuse: **7,736 passed, 1 skipped** (649 files, 139.34 s). The immediate
VR dispatch and overlap regression subset: **78 passed**.

The test guard flagged three filesystem-heavy tests in the archive run. Focused
triage retained their real tiny preparation/transfer workloads and moved only
throwaway fixtures to `/dev/shm`: assembly simulation parity fell from 10.35 s
to 0.56 s call time, bidirectional peer synchronization from 5.20 s to 0.01 s,
and peer push from 5.19 s to <0.005 s (peer fixture setup ~1.1 s). All three
passed. Simulation launch is disabled/mocked in the parity test; no scientific
simulation ran. These stalls are archive temporary-storage I/O, not genuinely
heavy tests to reclassify. No test budget or marker changed. The three individual
focused results are in `slow-triage.log`; the broad run remains the 96.91 s result
above, not a claimed rerun with different storage.

The opt-in native IPC suite passed **26 tests** against the rebuilt production
handler harness (`native-ipc-final.log`); the production-handler motion test
passed separately. The production frontend build after atlas reuse passed (6.25 s; existing chunk-size
warning retained).

Broad-suite deferral (verbatim):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```


### Artifact ownership

Each tour owns a temporary workspace and private backend/frontend ports. Test
parts use `__e2e__`; afterEach stops only the matching viewer PID, global teardown
removes test parts/project stores and the isolated bridge credential, and the
Python TemporaryDirectory removes the private workspace on success or failure.
Captures, logs, fixtures and timing evidence remain under `.development-artifacts`.

The straight trials also exposed retained `.volumes-state` sidecars after a
fixture Undo/reopen invalidated the old document binding. The frame-audit runner
now handles these in its finally path after the viewer exits: it copies only
exact journal paths reported by its own private backend into case evidence,
verifies the copy and removes those exact temporary sidecars. It never globs or
removes shared SteamVR runtime files. Earlier cases are checked with the same
ownership rule at final cleanup. No pending user volume edits are discarded.


Final cleanup verification: 24 exact test-owned volume sidecars were retained as
hashed evidence and removed from temporary storage. All 22 recorded owned
workspace/bridge paths are absent, as is the explicit backend pytest base folder.
No audit/native-viewer process or test part remains in the shared workspace.
Two pre-existing named Sweep temporary folders and shared SteamVR memory were
left untouched. Evidence is retained under the archive-backed artifact directory
(~56 GiB); `cleanup-verification.json` records ownership checks. The native
molecular-placement review gate and `git diff --check` pass.
