---
type: project
status: active
authority: canonical
review_after: 2026-09-01
---

# Native VR expansion

## Standard 24HB representation latency recheck — 2026-10-22

Current work: standard saved `24hb_0xT` and `24hb_2xT` designs (24 helices,
76 strands, 6720 nt), rather than the earlier 12000-nt audit fixture. Before/after
private 0xT fixtures have identical canonical geometry and scientific-field hashes,
even though saved-document metadata changed. Final evidence and workflow
results: `.development-artifacts/24hb-90fps-20261022/`.

The earlier trace-loss verdict was a parser bug: the GPU diagnostic description
contained the words `VR_TRACE_DROPPED`. Only an actual line beginning with that
marker invalidates coverage. Regression tests retain the genuine-loss failure.
Selective offline audits now export requested styles plus Full, avoiding an
unrequested Surface export. This does not change production export behavior.

Static selected Stick was CPU-picking limited (~6.5 ms p95, ~44.8 submissions/s).
A prepared immutable spatial index preserves primitive ordering, exact narrow
phase intersections and closest-unselected occlusion. A first insufficiently
conservative bound was rejected by GL parity; corrected bounds pass 360 rays
across both styles, scales and rotations. Dynamic layouts/poses retain fallback.
Prepared IDs/colors, unique owner rows and background preview copies remove
first-commit molecular hashing/copying. Dense prepared handle aliases/ownership
remove commit-time string hashing while retaining exact accumulation order,
fractional/zero weights, related pivots and Undo. A consecutive-commit lifetime
failure was caught and fixed; pixel/depth/picking/handle parity passes.

Periodic mirror health sampling was another real tail-latency cost. Pixel-buffer
readback alone, including native packed depth/stencil, still stalled ~6.4 ms in
the stencil call. A GPU stencil-to-R8UI conversion reduces that median to ~0.028
ms; all 256 classification values pass exact-byte validation. Sampling keeps the
captured frame/pose/time, uses a zero-wait fence, and leaves the visible mirror,
heartbeat and health diagnostics enabled. No molecular shaders/geometry changed.

Final render-path matrices on both designs pass 48 idle/grip intervals across
Stick/Ballstick and all four profiles, with zero compositor repeated/dropped
frames. Idle mirror p99 is ~0.15–0.17 ms (formerly ~7.8 ms). Nominal headset
refresh is 90 Hz; measured application cadence is ~89.53/s on this runtime.
These are instrumented OpenXR/compositor checks, not through-lens comfort proof.

Exact unchanged-shadow reuse removes another ~2.2–2.3 ms GPU timeline cost per
frame. Resident identity, packed geometry revision, model/light projection and
detail inputs key the cache; layout callbacks and visualization updates bypass
it. Pixel/depth parity checks cover reuse, model/light changes and GL state.
Median steady-fast drag GPU timeline: Stick 6.30 → 4.29 ms, Ballstick 6.82 → 4.43 ms.

Final `shadow-*` validation: both-design matrices pass all 48 idle/grip intervals
with zero compositor repeated/dropped frames. All eight Move/Undo/save/reopen
workflows pass behavioral assertions across both representations and four
profiles. Only 16/24 measured drag/hold/commit intervals are entirely free of
compositor repeats/drops. Both variable Ballstick profiles are clean; do not
cherry-pick these to claim universal 90 FPS. One Ballstick steady-fast outer frame
was 67.61 ms, including 59.36 ms in `xrEndFrame`, despite that drag's application
CPU max 3.27 ms and GPU timeline max 6.61 ms. Runtime submission is localized;
its underlying cause is unresolved. Some other commit misses correlate with
MemoryHigh events in the unchanged 6 GiB validation scope. Capture/warmup and
menu-acquisition stalls are reported separately. Strict no-drop editing is not
achieved, despite clean nominal-90-Hz baseline rendering.

Two harness corrections:
expected remote translation follows the fixed-depth controller ray, including
wrist rotation (unchanged 2 mm tolerance); large molecular captures determine the
pointing-hand clearance (old fixed 45 cm approach could be inside the origami).
Optional `--setup-trackpad` uses production focus/trigger only for recenter setup;
noisy recenter acquisition is not claimed. Seeds, profiles and deadlines remain.
Move audits now support `--playwright-trace off|retain-on-failure` (off default),
while explicit captures, browser-frame instrumentation and native/compositor
records remain enabled. A trace-on browser grew ~700 MB during one 30 s drag;
that campaign eventually hit the unchanged 6 GiB MemoryHigh limit. Controlled
trace-off replays are complete; the remaining misses above persist. No timing
thresholds, profiles, seeds or deadlines were relaxed.

18 focused Python tests and the native picking, mirror readback, staged-upload
and rigid-preview parity checks pass. The verified binary is deployed at the
configured normal `vr-clipboard-all-20261016/native-build/nadoc-vr-viewer` path;
SHA-256 `fb5b7c394f0c3fa22abed21245829c73347518d07227649f0a5e8c6d39e624c5`.
The performance fixes are tracked separately from preserved unrelated edits.
Task `report.json`, `interval-summary.json`, `workflow-results.json`, final GPU
and pressure summaries, deployment/source manifests, and two mirror PNGs remain.
Cleanup removed 53.7 GB of this task's raw captures, ID/depth buffers, copied
fixtures, traces and build outputs after active-reference checks. Raw paths in
historical records are now provenance only. Test workspace/scratch is clean and
owned VR runtime was restored to stopped; unrelated artifacts were preserved.

## Shared edit-ready upload pacing — 2026-10-22

Tab changes were committed/pushed as `8d52817f`. The subsequent native-only
latency change batches 1024 records per upload call (previously 256) and permits
up to 1 MiB per frame (previously 256 KiB). The 1 ms time check between batches,
separate allocation work unit, zero-timeout GPU fences, old-scene visibility and
atomic scene-ready acknowledgement remain. An individual driver call is not
preemptible; the time check is not a hard 1 ms maximum.

On the same 12000-nt Full fixture and steady-fast Twist reach, staging decreased
from 18 frames / 189.9 ms to 14 frames / 145.3 ms. Confirm-to-ready measured
2285 ms before and 2139 ms after (6.4% lower). This is one matched replay per
candidate; only about 45 ms is directly localized to shorter staging. The rest
can include export/runtime variation. Increasing only the byte ceiling measured
2083 ms overall but 167.5 ms staging, illustrating that total timing varies.

All four final Twist/Undo workflows pass, at 2096–2162 ms input-to-ready.
Measured application work peaks at 6.67 ms, with zero compositor drops/repeats
inside the named interaction intervals. Strict 90 FPS still fails: maximum
submission gap is 15.07 ms and measured cadence remains below 90. Do not infer
through-lens latency or a universal no-drop guarantee. Failed controller reaches
and normal retries remain in `review/acquisition.json`; presets/seeds/dwell and
performance thresholds were not relaxed.

Focused native staged-upload and scene-activation tests pass, covering 80000
records, byte/zero-time budgets, GPU contents, cancellation/reuse, atomic swaps,
exact pixels/depth/picking, stable IDs, style restart and repeated edit/Undo.
Final eye/mirror captures are retained and the mirror was visually inspected.
Serializer experiments were rejected: uncompressed transport saved ~51 ms but
expanded storage ~8x; format caching saved ~19 ms; cross-export immutable-string
caches saved ~59 ms with inconsistent pairs. No backend/frontend behavior or
molecular math changed in this task. Canonical serialization (~1 s on this
fixture) remains the main shared latency cost.

Evidence: `.development-artifacts/edit-ready-20261022/report.json`, `stages.json`,
benchmark JSON and native check logs. Debug → VR Tours & Tests → Tools across
representations · frame audit remains the reusable workflow. Disposable captures,
builds and owned scratch were removed; runtime returned to stopped. The upload
change remains uncommitted for review.

## Full-height sidebar tabs — 2026-10-22

Per user request, normal sidebar tabs now share spare space across the entire
available menu height. The existing border inset, column width, gaps, font sizes
and 200 ms hover/focus animation remain. Hover expansion redistributes spare space
with fixed rail endpoints instead of pushing the remaining column downward.
Drawing, exported targets and ray hits use the same actual bounds; no hidden hit
padding or relaxed motion/dwell thresholds were introduced.

The native sidebar test covers both sides and Assembly context, all selected/hover
pairs, fixed endpoints throughout animation, full expanded labels, glyph visibility
and matching ray geometry. In matched Tools-entry reaches (seed 4200), variable-fast
target movement fell from 80.7 to 3.0 mm and acquired on its first attempt. Variable-
deliberate movement fell from 115.6 to 7.1 mm; its first attempt retained hover for
200 ms rather than the required 300 ms, then the second attempt acquired. Previously
both profiles failed all three attempts. Steady profiles now acquire on the first
attempt as well. This reduces movement; it does not make every noisy reach succeed.

All four complete Twist/Undo workflows pass. The separate no-retry all-tab tour
acquires 11/11 tabs in each steady profile, 0/11 in variable-fast and 2/11 in
variable-deliberate (24/44 strict acquisitions total; 36/44 correct selections
when counting brief contact). Stereo pixel checks and blank-image negatives pass
for both menus in all profiles. Thus the targeted failure improves, while variable
motion still exposes unreliable single-attempt acquisition.

Detailed final workflow and all-tab outcomes are retained in
`.development-artifacts/full-height-tabs-20261022/report.json`; review images are
under `review/`. Debug → VR Tours & Tests → Full-height tabs · controller hit/miss
comparison remains the reusable direct tab test. The separate export/mirror latency
limitations below are unaffected by this UI change.

## Scene refresh parsing and per-eye submission — 2026-10-22

The residual rendering hitch was directly localized: one diagnostic replay spent
433.40 ms inside the per-eye `glFlush` (437.05 ms non-runtime-wait frame wall time).
The explicit per-eye flush is removed; required upload/readback fence flushes
remain. `calc_eyeRelease` separately measures OpenXR release, and acceptance also
checks `xrEndFrame`, full submission gaps and compositor counters so waits cannot
be hidden by phase accounting. Khronos hello_xr's OpenGL RenderView likewise does
not explicitly flush each eye. This does not establish universal no-drop operation.

`SceneInput` replaces locale-aware numeric extraction of scene coordinates/colors
with ASCII `from_chars`, retaining legacy metadata readers, gzip validation and
canonical geometry. A 12000-nt Full snapshot takes a median 220 ms to load versus
283 ms in five final alternating before/after pairs (22% less; first series 25%). All 16 focused native
checks pass, including float bit parity, malformed input, legacy scene versions,
compressed/corrupt input and asynchronous logging/refresh. Threaded gzip writing
and owner-metadata caching experiments showed no repeatable benefit and were removed.
Canonical Python scene export still costs about one second; total edit-to-ready
remains seconds. Do not describe this as an instant edit path or a 90-FPS guarantee.

Sidebar reach diagnostics now retain failed attempts, initial and per-sample live
rectangles, actual controller poses and hover IDs. Compact tab hover expansion
moves later tabs (`SidebarMenu::layoutControls` stacks animated lengths); the
synthetic approach aims at the rectangle captured at the start of each reach.
This can invalidate the target during motion, independently of deformation math
or frame latency. Motion presets, seeds, hit geometry and dwell thresholds remain
unchanged. See the final campaign and detailed acquisition report for current
pass/fail counts; successful diagnostic entry is not an unchanged variable-profile
workflow pass.

Evidence: `.development-artifacts/visibility-hitch-20261022/report.json`,
`parser-benchmark.json`, `twist-acquisition.json`, and `check-final-clean-env.log`.
Final focused campaign: Nick 4/4 and Twist steady 2/2 pass; both variable Twist
profiles fail Tools acquisition before trigger. Variable-fast's longest hover is
50 ms versus the required 120 ms (up to 88 mm target drift); variable-deliberate
reaches 200 ms versus 300 ms (up to 116 mm drift). These failures have no measured
frame stall. Steady runs also need acquisition retries. Fix moving tab targets,
not the profile thresholds, in a separate interaction change.

Across 18008 measured final frames, most cases peak at 3.18–7.37 ms non-runtime-wait
wall time. One Nick variable-fast frame still reaches 49.90 ms, with 49.52 ms in
mirror presentation. This is unresolved; the precise driver call was not isolated.
Nick edit/Undo/Redo ready times range 1.75–3.94 s, Twist 2.20–2.27 s. Submission gaps
and compositor misses remain. Strict 90 FPS fails. Two intermediate variable runs
failed viewer startup during an unintended rebuild; prebuilt retries are retained
separately. A standalone build attempt also failed due to Conda's linker path;
the clean-environment build and all 16 tests subsequently passed.

Reusable entry: Debug → VR Tours & Tests → Tools across representations · frame audit.

## Render-thread logging stall fix — 2026-10-21

Runtime console diagnostics bypassed `TraceSink` and wrote directly to stdout,
including hover snaps and the flushed `VR_SCENE_APPLIED` acknowledgement. They
could wait on blocked output or on the stream lock held by the frame-audit writer.
All runtime console records now use the existing bounded background queue; the
worker flushes quiet acknowledgements, and overflow remains explicit (invalidates
frame audits). Geometry, motion seeds, hit thresholds and refresh settings are unchanged.

The new blocked-stdout scene-activation regression fails against the original
header and passes with this fix. Both native CTest targets pass, covering blocked
output, bounded overflow, quiet acknowledgement delivery and scene refresh/retry.
Final-code Full/12000-nt headset checks: Nick 4/4 profiles; Twist 2/4. Both variable
Twist profiles still miss the Tools tab three times, with <5 ms measured frame
work; those are retained failures. A separately labelled diagnostic used steady
motion only for Tools/Twist entry, then the original variable-deliberate selection
and edit motion. It completed commit and Undo without the prior playback timeout:
selection-update peak 2.71 ms versus the historical 537.48 ms; total non-runtime-wait
wall peak 6.15 ms. Its temporary probe adjustment was restored and it does not clear
the two normal menu-validation failures. Nick variable-fast peak fell from 264.22
to 4.35 ms; final steady-fast Nick/Twist peaks were 4.01/5.65 ms. No trace loss.

**Strict 90-FPS/no-drop acceptance still fails.** One Nick steady-deliberate frame
had 37.55 ms non-runtime-wait wall time, mainly the `eye_setup` interval (which also
contains the previous eye's GL flush/swapchain release tail). Compositor misses and
submission gaps persist; edit-to-visible remains roughly 2–3.4 s. Do not interpret
non-runtime-wait wall time as pure CPU execution or the diagnostic as an unchanged
end-to-end variable-profile pass. Original stall stack traces were not retained;
the diagnosis combines phase evidence, a negative-control regression and replays.

Evidence: `.development-artifacts/headset-stall-fix-20261021/report.json` plus
`check.log` and `legacy-blocking-regression.json`. Normal replay remains registered
under Debug → VR Tours & Tests → Tools across representations · frame audit.
Disposable captures/builds and private workspaces are cleaned after analysis;
owned SteamVR/viewers return to the initially stopped state. Historical audit below
is retained as the before measurement, not the current implementation verdict.

## Headset latency acceptance — 2026-10-21

**FAIL: no-lag / never-below-90-FPS is not achieved.** Current source was built on
Archive and exercised through native OpenXR/SteamVR direct mode on the Vive/3080 Ti,
using the independent straight 24-helix/12000-nt fixture, Full representation and
all four unchanged motion profiles. Latest authoring results: 15/20 workflows pass.
Three variable-profile attempts miss the Tools tab, variable-deliberate Twist misses
its playback deadline by 0.509 s, and variable-deliberate Sweep times out waiting
for its warning tooltip after committing. Do not count those as passing coverage.

Observed input-to-native-ready: Nick 1.97–3.71 s; Ligate 1.86–2.36 s; Bend 2.55–4.47 s;
Twist 2.18–2.21 s; Sweep creation 2.13–2.22 s. Nick Undo/Redo measurements are retained
separately in the report. Native non-runtime-wait frame stalls reach 539.40 ms in
the instrumented authoring campaign. Phase attribution includes feed/input and
selection-update work, but the nested measured calculations are much smaller;
blocking I/O/logging/scheduling remains to be isolated before blaming selection math.

A separate standalone Full idle/grip baseline passes all four profiles: 4613 measured
frames, 89.50–89.56 application submissions/s, maximum non-runtime-wait work 4.13 ms,
zero recorded compositor drops/repeats. It excludes browser editing and drains
capture work before timed intervals. The runtime reports 90 Hz; this is not proof
of never falling below 90 FPS or optical scanout. Authoring drop counters cluster
near capture boundaries (about 100 ms sampling uncertainty); keep the original
counts and interior sensitivity checks, not a capture-free production claim.
Some later campaign cases experienced validation-scope memory.high reclamation;
the first Nick spikes preceded that pressure. Saved Sweep feature editing and
other representations remain outside successful coverage.

Startup dashboard focus was recovered through the existing return-to-game mailbox,
without changing Home, display or driver settings. The Ligate probe's stale
six-items-versus-four-enabled-booleans assertion now checks its original four edit
commands while preserving all six label checks; corrected Ligate runs pass all
profiles. No production behavior was changed for these tests. Temporary viewers,
private workspaces, raw captures and the isolated native build were removed;
SteamVR returned to its initially stopped state. Compact evidence and limitations:
`.development-artifacts/headset-latency-20261021/report.json`. Raw captures/frame
dumps were pruned; use Debug → VR Tours & Tests → Tools across representations ·
frame audit for a new run. Prioritize shared full-scene refresh delay, then native
blocking stalls and the variable-motion interaction failures; do not relax gates.

## Edit-to-visible synchronization — 2026-10-21

Deferred VR mutations apply design and geometry in one store update instead of
rebuilding new topology against old nucleotide records first. Late responses are
checked again; a failed geometry read still preserves committed feature/Undo
identity. Canonical export releases the lifecycle lock during CPU work, serializes
refresh publication separately and rechecks session identity before publishing.
Nick/Ligate retain the existing partial helix scope through geometry-free responses;
the follow-up GET preserves the desktop partial-update hint. Sweep creation/edit and
Bend/Twist/Sweep Undo use early geometry-free acknowledgements; Sweep edits now
start native export before desktop synchronization. Bend/Twist creation already
acknowledged before geometry and gains the shared atomic synchronization.

A private 24-helix/12000-nt Nick fixture measured full vs partial geometry at
275–288 ms / 15.84 MB versus 8–34 ms / 0.486 MB. Warm canonical native snapshot
serialization remains ~0.9 s; formatting-cache experiments did not reliably improve
it and were removed. No molecular/topological equations or native scene format changed.

Validation: 8419 frontend passes, 1 skip; focused publication/partial geometry tests
pass. Visible desktop app check covers Nick/Ligate, Bend/Twist, Sweep creation and
Undo. Saved Sweep editing is **not verified successful in app**: both deferred and
ordinary requests hit the existing `recipe_not_reproducible` metadata comparison;
no replay guard was bypassed. The headset follow-up above subsequently failed the
strict latency/FPS target.
Backend FAST: 14669 passed, 8 failed, 4 errors; native IPC + two worker failures pass
with shorter Archive scratch paths, leaving 5 unrelated failures/4 CPD fixture errors.
FULL deferred without a test session. Four slow-test flags all passed below the
budget when isolated; budgets/registry unchanged. Evidence and exact test verdict:
`.development-artifacts/edit-visible-20261021/report.json`. Reusable checks:
`frontend/e2e/vr_edit_latency.spec.js`, `tests/test_vr_edit_latency.py`, and the
registered **Tools across representations · frame audit** workflow.

## View tablet preparation and lossless panel transport — 2026-10-21

The following round prewarms icon decodes at native activation and decodes independent
icons concurrently. Identical instance records can be reused after exact byte and
world-matrix comparisons, including edits before GPU upload; retained cache storage
is bounded at 8 MiB. Busy publication polls skip scene fingerprint work. Surface-grid
movement, clash-result application, display rebuilds and deformation poses explicitly
notify the stream, as do relevant store changes; the 700 ms fallback remains for
unnotified mutations. Notifications coalesce while a publication is in flight.

Negotiated schemas 10/11 retain schema 8/9 geometry/base semantics with lossless
run-length-compressed RGBA panel pixels. Both backend and native decoder bound expansion
to exactly 768×768×4 bytes and reject zero runs, truncation, excess output and trailing data.
Older viewers retain raw panels. A direct pixel-run scan avoids general-purpose codec and browser task overhead.
Panel resolution and every antialiasing pixel are unchanged.

Final app sample: 145 ms first activation plus 4.5 ms icon prewarm; 72–98 ms warm
click-to-mocked-upload, with 442–474 KiB warm packets (previously ~2.5 MiB).
This is not a physical headset or p95 latency measurement. Evidence and validation:
`.development-artifacts/view-menu-round3-20261021/report.json`. Prior approved round
was committed and pushed as `f62fe82c`; these subsequent changes await review.

## View tablet glow and atlas reuse — 2026-10-21

Loop/skip annotations now use camera-facing analytic ring/X glyphs with shared
desktop/native glow, bright cores, dark rims, and an 18-framebuffer-pixel minimum
plane extent. Their centres remain at the molecular annotation positions; native
annotations remain depth independent. Two six-vertex templates replace curved
marker meshes. Native schema 8 carries scene plus a 768-square panel patch;
schema 9 updates only the panel without replacing the scene or transform base.
Both validate the retained base version. Capability negotiation retains full
snapshots for older viewers, texture changes rebuild/upload the atlas as needed,
and failed delivery forces a full retry. Cold and document-notified overlay
updates no longer wait 1.2 seconds; the 700 ms fingerprint fallback remains for
changes without notifications. Normal Deform edits still use the canonical feed.

Evidence and remaining ranking: `.development-artifacts/view-menu-round2-20261021/report.json`.
The registered Left-hand view tools tour records click-to-ack timing alongside
stereo/mirror captures. Browser and native GL evidence is not a physical headset
measurement; this round did not restart the viewer or SteamVR.

## Publication GC isolation — 2026-10-21

A measured 149.6 ms generation-2 collection blocked a publication before handler
entry; validation/delivery then took 10 ms. The dedicated server factory in
`server_bootstrap.py` freezes only the startup heap before serving requests,
leaving later cycles collectible and GC thresholds unchanged. `start.sh` and
`just dev` use it on the next normal start; the existing backend was not reloaded.
60-second ball-and-stick upload maxima improved 160.8→31.8 ms raw and
58.8→26.7 ms Smooth. A separate browser encoding long task remains, and this does
not prove every historical stall was GC. CPD benchmark diagnostics and the
server-pipe startup race fix are documented in
[playback notes](../docs/vr_cpd_playback.md#publication-stall-isolation--2026-10-21).

## Smooth pacing and compact grouped vertices — 2026-10-21

Smooth is now a slower presentation clock: prepare first, then seven interpolation
samples plus the exact endpoint over at least 250 ms. Per-sample pacing follows
browser publication cost and waits for busy delivery, without catch-up skipping.
Raw saved-frame playback remains 12 Hz. Four-isomer checks pass; 24HB dense
sphere GPU cost remains above the headset budget. No change to saved coordinates,
trajectory selection, topology, tessellation or normal arithmetic.

Opaque constant-color/UV sphere and small bond groups can use 24-byte GPU vertex
records with generic color/UV attributes; original fallback buffers remain.
Packing is bounded to 1 MiB extra CPU storage per full view and reused by transform
updates. NADOC_VR_COMPACT_VIEW_VERTICES=0 is the diagnostic fallback. Narrow
sphere-only packing did not reproduce the earlier whole-group gain; benchmark
scope must be preserved when interpreting small differences. Evidence:
[follow-up audit](../docs/audits/vr_gpu_iterations_20261021.json). Physical review:
MV-51. Main.js task delta remains zero.

## Initial GPU investigation — 2026-10-21

Trajectory sphere export uses 24×16 tessellation (720 triangles/atom); 24HB P1
draws ~99 million sphere triangles per eye. Corrected offline exact-pixel group
sweeps show no repeatable gain over eight. Culling saves ~5–6 ms but changes
depth/color pixels, so production is unchanged. Next target: explicit sphere
primitives with perspective-correct analytic GPU rendering, retaining centers,
radii, bond endpoints and stereo/depth/occlusion semantics. Do not substitute the
existing approximate billboard shader without those checks. Registered playback
GPU export must apply backend launch-camera rotation before replay; version
identity alone missed this in the first experiment. Evidence and exclusions:
[GPU audit](../docs/audits/vr_gpu_20261021.json).

## Decoder tuning and diminishing returns — 2026-10-21

Transform reads now use bounded 1,024-instance blocks (48 KiB scratch), preserving
exact matrices and normalization. Scalar-reference/block-boundary and production
GL byte/pixel parity pass. 24HB P1 native preparation improves ~74→65 ms and
58→51 ms for ball-and-stick/stick, but median scene cadence stays ~167/112/67 ms.
Further decoder tuning is incremental; significant large-model gains require
GPU work and broader browser/publication optimization, with independent fidelity
checks. See [final-pass audit](../docs/audits/vr_final_pass_20261021.json).

## Persistent transform stream — 2026-10-21

Compatible atomistic updates use negotiated schema 7: absolute Float32 display
translations/affine columns against an immutable full-snapshot base. Native keeps
mesh/index/group resources and alternates fenced instance buffers within the
existing upload budget. Structural/material changes and older viewers use full
snapshots. Source Float64 coordinates and molecular geometry are unchanged.
24HB P1 resident median scene gaps improved 302→168 ms (ball-and-stick), 156→112 ms
(stick); VDW remains ~67 ms and large-scene GPU limits remain. Exact CPU/GPU-byte
and rendered-pixel parity tests cover the production native path. Reuse the
registered CPD playback benchmark; `NADOC_VR_TRANSFORM_UPDATES=0` is the full-stream
comparison switch. See [audit](../docs/audits/vr_transform_stream_20261021.json).
Physical review remains MV-50.

## Exact-frame hitch follow-up — 2026-10-21

Browser VR packing now caches immutable local vertex templates and packs current
instance matrices/colors directly. Native acknowledgements of the already-settled
desktop style use `ensureRepresentation`, avoiding duplicate rebuilds and unsolicited
trajectory pauses; explicit `setRepresentation` still forces rebuilds. No coordinate,
topology or molecular geometry changes.

The registered CPD playback check also supports `--large` for two completed 24HB
jobs, four-frame resident diagnostics, and separate delivered-scene/headset/GPU
metrics. Remove setup request interception and wait for native lazy-style readiness
before interpreting steady playback. Large ball-and-stick/VDW GPU costs exceed
the 90 Hz budget even with zero coordinate reads. Through-lens review remains MV-49.
See [playback policy and measurements](../docs/vr_cpd_playback.md) and
[the audit](../docs/audits/cpd_vr_hitches_20261021.json).

## CPD production playback — 2026-10-20

Small VR atomistic trajectory selections now prepare exact coordinates before
Ready (200 selected frames maximum, 32 MiB atom cache, separate 32 MiB coarse
bound). Smooth defaults on for fitting atomic loads, respecting explicit choices.
One scene upload/read remains in flight; native upload budget stays 1 ms.
Cached playback avoids repeated ion/cell preparation and loading toasts.
All 24 final playback windows made zero coordinate requests; two Smooth
windows still failed the throughput gate. Native median intervals were ~11.17 ms
(with occasional hitches); scene delivery was 7–24 Hz. This is not yet consistently
smooth molecular animation. Follow-up SteamVR logs show a Home launch/abort
storm (~35–38 attempts/s) during measured windows. Residual timings are
confounded. Follow-up disabled Home autostart through live OpenVR settings: zero
retries, all 24 throughput gates passed, but mixed scene timings (7–21 Hz) and
a 1.843 s worst gap remain. Stopping the loop did not establish consistently
smooth playback. See the [repeat audit](../docs/audits/cpd_vr_home_fix_20261020.json). See [policy, reusable benchmark, and evidence](../docs/vr_cpd_playback.md).
The workflow is registered under Left sidebar in VR Tours & Tests and preserves
source jobs and existing runtime sessions.

Fidelity-first follow-up: saved-frame-only pipeline traces show no coordinate
fetches, <=1.6 ms cached apply and <=2.25 ms native read/parse. Archive is a
rotational HDD; synchronous scene-file write/replace blocks up to 468 ms, with
backend event-loop resume delays up to 388 ms and submitted scene gaps ~983 ms.
Three initial windows pass; a VDW repeat fails throughput (75 endpoints). This is
a measured disk-backed handoff contributor, not proof that HDD alone causes all
stalls or a smoothness fix. Implemented byte-preserving IPC for scene packets plus simulation/presenter
control snapshots; the latter also had 160–230 ms replacement stalls. Initial
cis-syn-I saved-frame gaps improve to 102/101/268 ms, with ~90 Hz native cadence.
All four isomers pass all 12 saved-frame windows at 11.955–12.059 scene updates/s;
p95 gaps ≤89.8 ms, worst 268 ms; native p95 ≤11.55 ms, worst 35 ms.
Existing viewers retain file fallback; packet receipt is bounded and keeps scene
atlas ordering and presenter heartbeat expiry. Persistent native mesh reuse remains
future work. No new interpolation. See [IPC audit](../docs/audits/cpd_vr_ipc_20261020.json). See [pipeline audit](../docs/audits/cpd_vr_pipeline_20261020.json).

## CPD Full parity — 2026-10-20
Full now exports the desktop's two CPD slab bars using shared projected sites and
the chemical graph. Slab-frame visualization moves/rotates both endpoints; Beads
hides the bars. Atomic CPD bonds already used the shared atomistic builder.
Crossover CPD Full beads/slabs now use the saved product landmarks and residue
poses; the previous exporter silently reconstructed ordinary unconverted inserts.
The reusable native rendering audit is registered under Visualization in VR Tours
& Tests. See [scope and workflow](../docs/vr_cpd_rendering.md). Molecular coordinates
and placement authorities are unchanged.
Verification: 48 native representation cases and 20 physical-runtime submitted
stereo cases across the four saved isomers. Saved Full/atomic sites match exactly.
The optional closer repeat failed recorder readiness before opening a viewer;
both runtime and viewer returned to their initial stopped state. Details and
remaining broad-suite failures: [audit](../docs/audits/cpd_vr_rendering_20261020.json).

## Current Ball+Stick grouped-index candidate (2026-10-15)

The user's requested fix is deployed; physical motion confirmation is pending.
24hb_0xT / P1 Alpine Aug 7 / Flex / Ball+Stick now groups eight exact indexed
sphere meshes per hardware instance. Complete vertex records, instance matrices,
colors, triangle order, normal arithmetic and shadows are unchanged. Four sphere
batches have 420 original records / 91 unique records each; their grouped buffers
have 728 records / 3360 indices. Existing small-stick grouping remains active.
Derived CPU/GPU storage is 280896/217728 bytes; optional allocation/capability
failures retain plain indexing or original arrays. Both indexing and grouped
indexing default on; `NADOC_VR_GROUPED_INDEXED_MESHES=0` isolates plain indexing,
and `NADOC_VR_INDEXED_VIEW_MESHES=0` restores original large-mesh draws.

Quiet live baseline was approximately 13.02 ms GPU / 22.33 ms app interval
(45 Hz). Plain indexing alone did not improve it. Grouped indexing now measures
87.343 Hz mean application cadence, median interval 11.166 ms, p95 16.218 ms,
maximum 22.447 ms. Three complete 120-result GPU windows have medians
8.497/8.473/8.577 ms, p95 9.027/9.168/9.139 ms, maximum 9.567 ms, zero query
skips. Occasional missed refreshes remain: this is not stable 90 Hz or proof that
the monocular temporal splitting is gone. User was asked for a new two-second
gripped-model torso recording; retain MV-44 and ISSUE-97 until that is evaluated.

Current normal physical-inspect PID 2374833 / session 2374833-144926698728966,
binary SHA256 af4e887c0591a0f9f452ecfca593a9557d6fecebd057bdad24089fa4153065f2,
build `vr-temporal-fix-20261015/native-build-2`. Existing compositor 2210586 was
preserved. Scientific export and all geometry payloads are unchanged, actual
browser publication is verified, and desktop renderer frame 71052 was frozen
during the measurement. Per-pass profiling is off. The saved model placement is
restored; reload closes the menus. Rediscover identities rather than reusing PIDs.

Eight native checks passed without skips, including 34 grouped exact rendering
comparisons, 12 fallback comparisons and 75765 ordered 22-word vertex records.
Fifty focused tour tests passed. Application-eye capture visibly confirms the
expected Flex model. Live GPU OOM was not forced; optional CPU failures and
resource-size predicates are tested, staged GL cleanup is statically reviewed.
No frontend JS or backend behavior changed (`main.js` LOC delta 0).

Headless deployment restores coordinates before trajectory, then visualization,
simulation and View Tools feeds; wait for representation loading to finish.
**Configure the actual ELF:** a temporary shell wrapper enabled profiling but
failed the backend's `/proc/PID/exe` identity check, disconnecting the browser.
Its desktop renderer resumed and inflated GPU time to 17.7 ms. Restoring the
direct build path and reattaching the existing tab to the same PID froze desktop
rendering again; clean profiling measured 12.32 ms total (2.27 shadow, 4.84 right,
5.15 left). The left pass includes mirror/swap/release, not only scene shading.
Retain the contaminated sample, but do not attribute it to query overhead.

Evidence root: [current review](../.development-artifacts/vr-temporal-fix-20261015/index.html),
[live timing](../.development-artifacts/vr-temporal-fix-20261015/candidate2-performance/summary.json),
[deployment](../.development-artifacts/vr-temporal-fix-20261015/deployment-2/verification.json),
[browser verification](../.development-artifacts/vr-temporal-fix-20261015/candidate2-reconnect/verification.json),
[native tests](../.development-artifacts/vr-temporal-fix-20261015/candidate2/native-tests.log).
Original binary/config/assets and unsuccessful trials remain under that root.
The unshipped analytical-sphere prototype is archived separately under the task
root; it is not compiled into the viewer. The original manual recording below
remains the regression target.

## Current Ball+Stick temporal splitting evidence (2026-10-15)

User capture 140701076018774 (11:33 local, two seconds) confirms temporal position
splitting in 24hb_0xT / P1 Alpine Aug 7 / Flex / Ball+Stick. All 179 final stereo
presentations are retained with zero recorder drops; all 358 eye markers join.
There are 90 distinct application images and 89 reused presentations per eye:
approximately 44.76 application Hz versus 89.53 final-present Hz.

Actual molecular landmarks, independently of the frame-ID panel, move left then
return right. Capture indices 45/46/47 decode app IDs 23973/23973/23974 at
502.564/513.733/524.992 ms after the first captured present. Left upper landmark
x is 342.5/326.5/342.5 pixels;
right upper is 1289.5/1274.5/1290.5 in full stereo coordinates. Two landmarks per
eye agree. Fixed first-frame templates were chosen retrospectively; unchanged
score >=0.80 and distinct-peak gap >=0.05 reject many other frames. Preserve those
rejections. Inspected individual originals show no second complete silhouette.
Alternating final-image placement is measured; reprojection of a moving object
at half-rate is a plausible mechanism, not optical/scanout or GPU-cause proof.
Across 46/89 held intervals with accepted pixel matches, median displacement
correlates with neighboring application-pose head speed (Pearson r=0.983).
These are selected, temporally dependent samples, not compositor late-pose data.

Both menus stay open, but all 146 retained journal rows have zero hover changes
and zero haptic requests/dispatches. Tracking flags remain valid. Recorded model
transforms follow the current gripped controller within 3.22e-7 m; no CPU stale
model transform is evident. Ball+Stick draws 22.95M triangles/eye (6.20 times
Stick-only geometry); opaque optimization is active. This is a load candidate,
not a measured GPU bottleneck. No viewer/config/placement changes were made.

Evidence and raw-frame review: [October 15 report](../.development-artifacts/vr-ballstick-capture-20261015/index.html),
[pixel tracking](../.development-artifacts/vr-ballstick-capture-20261015/temporal-motion.json),
[journal findings](../.development-artifacts/vr-ballstick-capture-20261015/journal-findings.txt),
and [runtime baseline](../.development-artifacts/vr-ballstick-capture-20261015/baseline/summary.json).
Observed viewer PID 2110721/session 2110721-140414220546292 uses the vr-join-20261013
build. Rediscover live identity before acting; older PIDs/builds below are history.
The config's active-capture path was stale; the live final_capture.directory
correctly selected runtime-1792085254393766426/compositor.

## Earlier menu-hover timing follow-up (2026-10-13)

The user reports substantially reduced doubling after normal deployment, with
remaining lag/frame drops as menus enter view or the other controller aims,
hovers or vibrates while moving the model. ISSUE-77 is open; MV-44 is improved
but remains open. This follow-up adds diagnostic coverage, not a rendering or
haptic behavior fix. The earlier normal-launch evidence below is historical.

User recording 962531370889719 saved all 179 final presentations, zero accounting
drops. The completed stereo decode joins all 358 eye images to exact CRC/session/
eye/frame records: 144 distinct submitted images, 35 two-presentation runs per
eye, matching left/right IDs, no unknowns/gaps/regressions. Reuse accounts for
19.55% of final presentations. The journal has 143 predicted-in-window rows;
boundary membership differs from the 144 decoded image IDs. The original fixed-ROI
result (313 joins, 45 unknowns, 22 proven pairs per eye) is preserved. Opt-in
following used a fixed 80-pixel allowance and 20-pixel adaptive margin, changed
no acceptance thresholds, and was evaluated retrospectively on this recording.

The 242-row journal reports head and hand tracking flags 15 throughout: no flagged
dropout, not proof that tracking jitter is absent. Both menus are logically open
while their visible coverage changes. Application prediction intervals mix 11/22 ms.
Input/actions reaches 1.61 ms; xrEndFrame reaches 20.88 ms. This locates the long
host wait, without attributing it to GPU work, hover, haptics or a tracking fault.
The exact-ID groups correlate with that wait: reused-image application frames have
median host duration 22.242 ms and xrEndFrame 20.259 ms, versus 11.104/2.347 ms for
single-presentation frames. This association is not a menu/haptic causal test.
The old recording has no per-frame hover/haptic diagnostics. Native inspection
found event-triggered haptic dispatch and possible hover-driven texture refresh;
visible menu shading/backdrop work is another candidate. None is proven causal.

Current normal physical-inspect viewer: PID 545874, session
545874-963676394554697, native SHA256
65bcd41e1de02d1d6271c19a1aa7d04683087358eb0dd78a17d4eb282cb8a4d3,
frozen at menu-hover-followup-20261013/native-build/nadoc-vr-viewer.
Existing SteamVR compositor 2783034 was retained. Scientific export is unchanged;
the restored normalization matrix differs by at most 1.0547e-7. The actual browser
reattached: feed 480591238→480591239 and coordinate sequence 2, unchanged placement,
Help → Exit VR available. Menu open state and former sidebar positions were not
restored; both menus are closed after reload. Reopen/place them before another
physical reproduction. Verify live process identity again before future actions.

New capture-only capture_ui_diagnostics version 1 records requested/dispatched
haptics with result and host duration, bounded hover IDs/changes, sidebar texture
updates/cache hits, and eye menu/backdrop host spans. Idle collection uses zero
diagnostic clocks. Fixed storage adds 1,240 bytes per frame, 10,158,080 bytes across
8,192 journal slots. The module adds no GPU queries, pixel readbacks or active
file writes. Event overflow, string truncation and clock errors remain explicit.
Host call time is not GPU busy time; a draw is not visible coverage; API dispatch
does not independently observe physical vibration. Nested spans overlap.

Use python -m tools.vr_tracking summarize-interactions --journal JOURNAL
--identities IDENTITIES --output NEW_DIRECTORY after capture. Identities are
optional and, when supplied, must match the exact journal/session/request. Older
journals report missing telemetry as unavailable. Optional marker ROI following
is a manifest setting; the ordinary identify-frames command is unchanged.

Deployment check 963838453284914 saved 179 final frames with zero accounting drops
and 288 journal rows. Both menus were closed; all UI activity/clock counters were
zero, with zero overflow/clock errors. Physical hands were invalid in this check;
it does not exercise worn-controller hover or vibration. The first verification
incorrectly required positive UI clocks; its failure is retained, and the corrected
zero-demand check passed without recapture or native edits. Actual GL hover/cache
and haptic API dispatch/result tests passed separately. Six native checks,
45 interaction-reader tests and 69 marker-decoder tests passed. No broad/full-suite
rerun was performed; the previously documented psfgen/CPD and timing-guard debt
remains open, and no clean-worktree claim is made.

Evidence: [native audit](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-audit.json),
[complete stereo identity proof](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/recording-analysis/identity-follow-summary.json),
[native freeze](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/native-freeze.json),
[closed-menu live check](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/verification.json),
[interaction findings](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/interaction-timing-findings.json),
[final deployment verification](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/final-verification.json),
[retained initial verification failure](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/live-capture-proof/initial-verification-failure.json),
[browser attachment](../.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/deployment/browser-connected.png),
and [reusable tool documentation](../docs/vr_origami_tracking.md#menu-hover-and-haptic-timing).

## Earlier normal-launch integration (2026-10-13)

Normal browser launch now uses the integrated optimized renderer and final SteamVR
recorder. The earlier private-viewer deployment gap below is historical. This checkpoint's
viewer is managed by the normal backend and uses inspect mode with physical input.
The existing NADOC browser tab was reattached through View in VR without restarting
the viewer: PID/session and presentation stayed identical, visualization sequence
advanced 2→3, and the 53,789,512-byte view-tools file changed only one sequence-header
byte. Its geometry payload and scientific export are unchanged. The Help menu
shows Exit VR enabled. This publication evidence proves attachment; the native
browser_events_connected flag alone only means an events path exists.

The stale backend-recovery dialog was cancelled after checking the durable design;
no document was reimported. NADOC was brought from a background tab to the foreground.
Desktop 3D during VR remains at its original true setting. The captured cadence
evidence predates this foreground change; it does not independently certify the
current combined desktop/VR load. Verify live identities before further action.

Earlier verified viewer: PID 378253, start ticks 96081361, session
378253-960813655398269, native v2 SHA256
1e830a7fd2e8c273cec04aba917e64903ccc3b166a692659158314cac8c53b76.
Grouped instances and opaque shading are default-selected and actually active.
The original 24hb_0xT P1 Alpine Aug 7 Flex Stick display has flags 2304 and
462,606 instances. Its source-to-tracking placement differs by at most 2.4e-7 m
from the saved placement (2e-5 m limit); the scientific export is unchanged.
Both controllers were untracked at the final snapshot, so physical input mode
is verified but a worn-controller gesture is still user validation.

The per-user ~/.config/nadoc/vr-capture.json pins the Archive viewer build and
capture layer. The one-shot placement restore binding was removed after verification.
All four saved global OpenVR/SteamVR configuration hashes remain unchanged.
Compositor PID 2783034/start 91106869 remains the existing V12 process; SteamVR
was not restarted for this integration. The build path must not change while its
viewer runs, because backend ownership checks authenticate the configured executable.

The actual Tools menu action saved 179 final images with zero accounting drops
(request 960763488058772); a second recording in the final physical inspect viewer
saved 179 with zero drops (request 960881582120081). Both retain executable identity,
coherent per-eye/controller/model journals, recording-only image markers and
durable pixel files. Full pixel audits verified all 179 original frames in each clip and durable
direct-I/O accounting. The final calibrated decoder joins all 716 eye images to
their exact CRC, full session, eye and application frame: 179 distinct consecutive
IDs per eye per clip, with zero repeats, gaps or regressions and matching left/right
IDs. Menu IDs are 29136–29314; physical-inspect IDs are 6330–6508.

The earlier wide ROI and first tight-ROI failures are retained. A narrow fix ignores
components already below the existing minimum area before applying the unchanged
64-candidate cap. CRC, geometry, contrast and bit thresholds remain unchanged.
The tighter ROIs were calibrated only on menu frame 0; its remaining 178 frames
and all 179 physical-inspect frames were held out. These are stationary integration
checks, not a torso-motion reproduction. Saving took about 15–16 seconds.

To record: open VR Tools, leave Duration at 2 seconds (or select 5 seconds), then
choose Record final output. Wait through countdown and preparation, then reproduce
the motion during the live recording countdown; afterward wait for Saved. Open final-output folder locates the evidence.
Markers appear only during journal collection, including preparation and a brief
tail; they disappear afterward. Recorder readiness is checked fresh. If this
configured final recorder is unavailable, the action reports an error rather than
silently switching to application-eye recording. Other unconfigured workstations
retain their portable application-eye recorder.

This closes ISSUE-76's launch/recorder integration gap, not the reported optical
symptom. MV-44 remains open: repeat torso/head/controller motion and model-only
motion, monocularly, with menus closed and open. Final queued images and exact
application IDs do not prove physical scanout timing or optical equivalence.
Overhead is measured, not negligible. Source changes are uncommitted; no clean
worktree or all-tests-green claim is made.

Validation: 101 focused backend checks, four fresh-readiness cases and five native
v2 checks passed; 175 tracking/decoder checks plus 24 subtests also passed.
Prior optimization/Join evidence is retained. The broad FAST run
was not green: initially 10,830 passed, 14 failed, 8 errors, 92 skipped and
2,500 warnings. After short Archive test paths resolved three Unix-socket failures,
the final FAST rerun reports 10,832 passed, 11 failed, 8 errors, 92 skipped and
2,500 warnings (134.82 seconds in pytest, 137 seconds in the guard). Five timing
budget overruns remain subject to triage. psfgen path and CPD stereochemistry
failures remain recorded; broad/full-suite debt is not cleared.

Evidence: [normal-launch handoff](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/launch-handoff.json),
[all-frame recording review](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/index.html),
[complete calibrated identity proof](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/recording-validation/postfix-summary.json),
[final physical state](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/physical-path-proof/final-state.json),
[configuration and document verification](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/final-config-document-verification.json),
[browser reattachment proof](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/browser-reconnect/verification.json),
[rollback plan](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/rollback-plan.txt),
and [retained test triage](../.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/test-smart-triage/triage-report.txt).

## Historical final-output recorder handoff (2026-10-12)

**Historical manual torso follow-up before normal integration (2026-10-13):** [review and findings](../.development-artifacts/vr-output-capture-20261012/torso-followup-20261013/index.html).
The user still perceives doubling. The new recording`stereo-1791913892856-242100`
contains204 application-eye pairs/12 writer drops, predominantly22.22ms predicted
application periods. Accepted bilateral molecular displacement11360→11361 is
41–42px horizontally; selected original eye crops show no clear second silhouette.
This cannot exclude temporal doubling or establish stale model poses. All-frame
fixed-template analysis accepts557/1224 candidates and retains667 rejects.

**Historical deployment gap, superseded above:** normal VR launch was using the original renderer and
application recorder. PID242100/start95755777 hashes to pre-work`5b350522…`, not
optimized`bf1ac6c…`; the prior private optimized viewer103293 has exited.
Do not call this a controlled post-fix retest. This clip has no final SteamVR
images, encoded frame identity or model/controller pose journal. Verify launch
provenance before the next worn-headset comparison. No live inputs, scene,
SteamVR settings or behavior source were changed during this recording analysis.
The [runtime audit](../.development-artifacts/vr-output-capture-20261012/torso-followup-20261013/runtime-audit.json)
supersedes earlier current-process claims. Reauthenticate identities before action.

**Earlier frame-identity/rendering follow-up (2026-10-13):** start with the
[measured review](../.development-artifacts/vr-output-capture-20261012/frame-identity-20261013/index.html)
and [current runtime, limits and rollback](../.development-artifacts/vr-output-capture-20261012/frame-identity-20261013/FINDINGS.json).
Full session/eye/frame/CRC encoding proves the original 24HB Flex Stick repeated
89 images in 179 final presentations (about45 new images/s). Actual molecular
landmarks held then jumped up to12px. Opaque shading plus order-preserving groups
of eight instances brings the same moving Stick to about90Hz without changing
scientific geometry or colors. Same-map Full/oxDNA and physically smaller2HB Stick
also run near90Hz. One original Full run was stationary after an input lease
expired; the preserved corrected run and new motion/rigid-transform safeguards
prevent that false pass. Physical monocular doubling remains unverified; MV-44
still requires model/torso movement with each menu state in the worn headset.

Historical diagnostic viewer (now exited): PID103293, start ticks95491503,
session`103293-954916762775429`. Reauthenticate these against the saved plan before any
process action. Binary`bf1ac6c59ca02231dd5dbcb0d9bc1f5de063d53c0e5b14a60a6e91502e15142d`;
mode inspect, physical input, original24HB Flex/pose restored, markers/timing off,
rendering optimizations on. Private cloned sidecars remain disconnected from
browser editing. SteamVR was not restarted or globally reconfigured in this follow-up.
Both optimization flags can be explicitly set to0; an unlaunched legacy rollback
plan and source/configuration/binary baselines are saved. New source is uncommitted
in the isolated Archive worktree, on top of`ef7a74a4`; it is not merged here.
The following paragraphs retain earlier historical diagnostics; the latest torso
follow-up above supersedes their runtime identities and launch assumptions.

SteamVR final direct-display capture is implemented in the isolated Archive
worktree, branch `codex/vr-final-output-capture-20261012`, commit `ef7a74a4`;
it has not been merged into this checkout. Start with the
[report and rollback record](../.development-artifacts/vr-output-capture-20261012/REPORT.txt)
and [capture runbook](../.development-artifacts/vr-output-capture-20261012/worktree/docs/scrywrite_inspector.md#final-steamvr-output-capture-2026-10-12).
Tools defaults to 2 seconds with 5 selectable. Both menu recordings passed
(180/180 and 447/447 final images, zero drops, approximately 89.53 Hz); overhead
is calibrated, not negligible. Physical scanout identity and optical equivalence
are unverified. The recovered viewer uses private sidecars, disconnected from
browser editing; revalidate runtime identities rather than reusing old PIDs.

**Rapid model motion tested:** four 2-second final-output clips, menus closed/open,
using normal one-hand grip with unchanged `steady_fast`, then a separate 2 Hz
synthetic sweep. All four saved 179/179 images with zero recorder drops. The faster
path moved 35 cm at a sampled peak of about 2.23 m/s; controller RPC updates reached
about 44.8 Hz. See the [motion review](../.development-artifacts/vr-output-capture-20261012/rapid-motion-20261012/analysis/index.html)
and [reproduction/timing handoff](../.development-artifacts/vr-output-capture-20261012/rapid-motion-20261012/motion-handoff-summary.json).
Inspected originals, including 12 consecutive fast frames in each eye with each
menu state, show one coherent model per eye, without a clear second silhouette.
Successive images show paired/stepped positions; this is not proof of the reported
perceptual doubling. All 716 images received descriptive pixel-motion analysis;
visual inspection covered selected originals, not every frame.

**Interpretation corrected 2026-10-13:** the user did not require two copies in one
frame. Model-only movement also doubles; torso/head/controller motion keeps the
model approximately head-relative fixed, with separation proportional to speed.
Single-frame clarity cannot rule out perceptual doubling. Temporal image pairing
was captured. Before recording, 421/421 application frames were presented twice
at 44.763 Hz, GPU reprojection flag 0x02, total GPU median 13.804 ms. Active
Stick/Flex uses an exported mesh path (nominal 12.36M triangles/frame including
shadows), but no extra moving-model copy or temporal history was found. Controller
and eye queries share predictedDisplayTime. Half-rate rendering is a strong current
lead, not a complete explanation: September 30 retained residual physical doubling
during mostly fresh 90 Hz delivery. See the [reassessment and primary sources](../.development-artifacts/vr-output-capture-20261012/doubling-investigation-20261013/FINDINGS.txt).
The new pose journal now retains coherent rendered eye/controller/model poses and
validity flags with an OpenXR-to-monotonic clock conversion. Remaining work includes
final-image distortion and app-to-present association, symptom timing and
representation comparisons.

**Origami tracking added 2026-10-13:** uncommitted implementation and tests remain
in the isolated worktree above. See the [tracking runbook](../.development-artifacts/vr-output-capture-20261012/worktree/docs/vr_origami_tracking.md)
and [tracking findings](../.development-artifacts/vr-output-capture-20261012/origami-tracking-20261013/TRACKING_REPORT.txt).
The [original-frame review](../.development-artifacts/vr-output-capture-20261012/origami-tracking-20261013/final-output-review/index.html)
tracks actual molecular features without recoloring strands. A left-eye landmark
moves 321.5→349.5→349.5→377.5 pixels at ~11 ms intervals. The explicit spatial
matching filter leaves originals unchanged; 61/72 matches accepted, 11 ambiguous.
Held-out application captures after all four motion profiles accepted 19/24
landmarks, median residual 0.675 px and maximum 1.935 px against same-frame poses;
five rejections retained. These snapshots do not establish absence of a transient
motion error. A synthetic 16 px stale-render fault is detected by the tests.

With `--pose-journal DIRECTORY`, Tools → Record final output also saves bounded
coherent application poses after recording. Live validation saved 179/179 final
images (all decoded/verified) and 144 journal frames, 89 in the capture interval,
with no overflow or clock conversion failure. App cadence was 44.763 Hz. Command
acknowledgement is usually one sequence ahead of the rendered image; join by
application frame, not the latest command reply. Journal sampling/IPC overhead is
not separately calibrated yet. Expected positions in final distorted pixels are
withheld until calibrated; physical scanout and optical equivalence remain open.

**Full recording reanalysis (2026-10-13):** the original manual torso capture is
retained at `.development-artifacts/vr-recordings/stereo-1791855106976-2397910`.
All 180 original stereo pairs were reprocessed; 1,080/1,080 individual molecular
landmarks accepted. Recorded view yaw spans 75.46°, versus 3.72–5.19° feature
bearing changes, supporting approximately head-relative placement. It predates
final-output capture/model journaling and has irregular ~36 Hz application
sampling, including a 241 ms gap. The prior 381.996°/s head-speed figure used host
acquisition intervals; predicted-view-time differentiation peaks at 92.767°/s.
Neither is physical speed ground truth. See the [combined review and findings](../.development-artifacts/vr-output-capture-20261012/motion-reanalysis-20261013/index.html).

The complete new journal-associated final clip accepted 1,074/1,074 landmarks
across 179 frames. Both eyes show hold–jump pairing (e.g. 384.5→384.5→372.5→372.5
px), maximum horizontal jump 13 px; jump magnitude correlates with model speed
(r=.967–.989 under an empirical temporal fit). Draw-time CPU transforms follow the
applied synthetic controller; this does not independently verify GPU matrix use
or app-to-present identity. **Secondary-copy detection failed sensitivity:** only
3/48 injected copies recovered correctly, with all 6/8 px and faint 25% copies
missed. Zero detections in 742 original frame-eye cases cannot exclude doubling.
Next discriminating instrumentation is an encoded app-frame ID in submitted eye
textures, joined to the journal and calibrated lens mapping. This pass changed no
runtime, production source or global configuration; original pixels preserved.

Current physical-input viewer is the frozen tracking build in
`origami-tracking-20261013/runtime-final-inspect/recovery-plan.json` under the
Archive task directory; frozen V11 rollback plan is `runtime-rollback-inspect/`.
Both preserve private assets and source-to-tracking placement. Live validation
restored menus closed, Stick/Flex flags2304/version619350753, physical controllers,
and the original model placement; SteamVR PID/start identity stayed unchanged.
Use the saved plans and revalidate identities before action, not remembered PIDs.

During controlled final-output tests, the physical headset stayed still (tracked
translation below 0.4 mm). Coordinated head-plus-controller rotation with the new
final recorder remains **untested** and is the next decisive wearer comparison. No result rules out the reported monocular
effect. Saved placement and physical controllers were restored; SteamVR was not
restarted. Keep persistent viewer launch outside `validation_guard.sh`: its EXIT
trap stops the scope and its detached children. Use the guard for bounded checks.

## Live simulation menu (2026-10-12)

Accepted round 5's **raised scrubber**, horizontal mapper, compact split and curved
engine tabs now drive the native left Simulations panel. Real job rows and desktop
visualization handlers feed Full representation. Trajectory metadata is separate
from explicit Load. Start/End/Every use the smallest 20%-exposed gallery cylinders
in both the component viewer and live panel. `trajectory_range_wheels.hpp` uses
single-frame detents at slow speed, 10-frame steps at 100+ source frames and
100-frame steps at 1,000+ frames for faster drags. Values are bounded, stop on
release, and publish once. Heartbeats preserve drafts and pending configuration;
desktop configuration publishes atomically (ISSUE-72). The source-frame readout
retains exact entry, and the 500-frame Load confirmation remains. The registered
Simulation jobs tour checks slow/fast gestures and stereo wheel pixels.
NAMD/oxDNA/LAMMPS stream eight-frame pages (two retained); SNUPI seeks indexed
frames. NAMD ion/cell companions use the exact sparse page, cached PSF row/species
tables and the shared affine; drawing waits for matching DNA. Shared suboptions and
real progress are mirrored, including indeterminate preparation and buffering.
The six-map wheel is docked around the left controller's touchpad using the
existing prompt and triple haptic pulse. Its sectors show radial gradients only;
the tablet keeps the horizontal scale. Input is modal through the release frame.
P1 RunPod's periodic-image correction and picker checks are documented in the
[follow-up audit](../docs/audits/vr_palette_pbc_20261012.md).

Native scene reads/normalization/bounds run on a worker; geometry uploads stage
under a per-frame budget and playback reuses the atlas. See the
[October implementation audit](../docs/audits/vr_simulations_20261012.md) for actual
24HB compositor measurements, validation coverage and remaining physical checks.
90 FPS is a measured target, not an unconditional guarantee. Atomistic remains
outside this iteration. The desktop A/B gallery remains available for reference;
its artificial loader is isolated from the real native simulation menu.

## Join clusters (2026-10-13)

**Retention update:** per the user's October 13 instruction, the completed Join
campaign's raw captures, extracted images, depth/ID buffers, detailed pose/frame
logs, traces and copied designs were deleted after validation. Historical raw
paths in this section are no longer replayable. Compact results and deletion
inventory remain in `vr-join-20261013/verification-summary.json` and
`bulk-cleanup.json` under `.development-artifacts/`. Keep the configured build and
active runtime; do not accumulate large captures after each feature check.

Current follow-up adds desktop-equivalent 0.3–10 nm Reach, cluster scope locking,
stale-pose rejection and the duplicate-preview/reselection fix (ISSUE-78). A
persistent Nick/Ligate worker removes header I/O, thread creation and old-table
destruction from the headset loop. Debug → VR Tours & Tests also exposes **Join
clusters · final output and release**. Its optional recorder serializes journal
and controller commands; released poses require terminal exact-sequence feedback,
and Apply waits for native scene refresh.

Current software checks pass: 7,906 Vitest, 130 focused backend (including seven
recorder checks), four native, two browser and 23 smoke. All four unchanged
physical motion profiles pass Cancel/reselection/Apply/Undo with one routed
scaffold and unchanged staples. Across 20 Join intervals: 89.51–89.55 application
FPS, maximum non-runtime-wait CPU 4.85 ms, no over-budget frames and no compositor
drops. Moving/released intervals have zero repeats; Apply has 1–2 per profile.
Do not claim uninterrupted 90 FPS or universal scene-size performance.
Final compositor recordings retain 179 translation +179 rotation +448 Apply
stereo frames, with all 1,612 eye markers joined and no unknown/reused/gapped
submitted images. Apply's clip includes the scene revision transition. Raw pixels,
first-frame ROI calibration/failures, journals and interaction reports are retained
under `final-pixels/` in the same evidence folder. Optical scanout is not verified.
Nick/Ligate max fell from 82.60 ms before the worker to 0.0025 ms; host memory
pressure also changed after restart, so overall improvement is not a controlled
worker-only comparison. Keep MV-VR-JOIN open for human comfort and strict output
cadence. Evidence and broader test debt:
`.development-artifacts/vr-join-20261013/verification-summary.json`.

**Remote recovery after restart:** source/binary hashes survived; no restart cause
was established. SteamVR rendered but had its dashboard visible and application
input unavailable. The ordinary Steam client was started remotely to stop Home's
launch retries. Close the dashboard through the installed dashboard's existing
mailbox handler: websocket `ws://127.0.0.1:27062`, origin
`http://localhost:27062`; send `mailbox_open nadoc_join_recovery/remote`, then
`mailbox_send vrwebui_dashboard {"type":"hide_dashboard_requested","reason":"return_to_game","source_is_vrlink_remote":false}`.
Close that temporary websocket. A background OpenVR query then reported dashboard
false/input available, and all four tours gained actual OpenXR focus. No physical
user action, focus bypass, driver/display setting change or runtime restart was
needed. Do not ask the remote user to wear the headset before checking this path.
The configured normal-launch viewer now points to the validated Archive Join
build; the prior build/config backup remains preserved in the evidence folder.

### Earlier Join implementation and measurements (2026-10-11)

Tools → Join forces Cluster selection and reuses native Move / Rotate's rigid
preview, trigger pointing/translation and grip rotation. Position/Rotation
thumbwheels snap to 1 nm / 15°; Cancel discards every draft transform. The shared
sidebar renderer supplies frost, borders, stroke fonts, beams and Cancel/Apply
footer. `join_preview.hpp` keeps a cached spatial index with bounded site samples,
comparisons and provisional guides; full validation runs outside the render loop.
`vr_join.js` coalesces desktop Join previews and commits only the current validated
pose through desktop routing/history and canonical native refresh. Generation,
document, revision and target guards reject obsolete work; ambiguous Apply results
require authoritative reload before retrying. A session ending during Apply lets
the owned transaction finish, then retires its event cursor.

Reusable Debug → VR Tours & Tests → Tools · Authoring entries are **Join clusters ·
move, rotate and connect** and **Join clusters · routing regression**. The isolated runner uses short
Archive scratch paths for Unix sockets, owns only its fixture/viewer, and verifies
workspace cleanup. Build overrides use `NADOC_VR_BUILD_DIR`; defaults are unchanged.
See [VR Join](../docs/vr_join.md), `.development-artifacts/vr-join-20261011/`, and
MV-VR-JOIN for verification evidence and remaining human headset review.

Native core/gesture/GL/transition checks, two browser routing/menu checks and 23
smoke tests pass. All four scripted motion profiles pass on the Vive/OpenXR
runtime (source checkpoints retained). The eight explicit movement intervals
cover 1,036 frames at 89.50–89.57 application FPS, GPU p95 1.93–2.60 ms and zero
compositor repeats/drops. Apply/refresh windows include 13 repeated and 10 dropped
frames across the four retained runs, with GPU max 19.36 ms. Above-90-FPS delivery
is not achieved on the 90 Hz headset; no general scene-size guarantee is claimed.
Broader test debt and cleanup: `verification-summary.json` in the evidence folder.

## Movable sweep start (2026-10-09)

New-bundle Sweep origins now use the same position controls as later knots:
Trigger drag / XYZ arrows in VR, XYZ fields / translation gizmo on desktop.
Moving the first knot reshapes the start while keeping subsequent knots fixed.
Moving an attached start detaches its source connections with ordinary nick
operations, leaving source helices fixed. The saved `detach_source` intent
prevents silent reconnection on returning to zero. Free Draw and
smoothing preserve a moved start; the native/browser transport accepts bounded
nonzero first coordinates. Existing Sweep history carries these coordinates
through edit, save/load and Undo/Redo. The registered S-shaped Sweep tour also
drags the origin and verifies the other knots remain unchanged.

Validation: four-profile native Sweep tour including commit/edit/Undo/Redo,
three native checks, desktop creation/continuation/detachment browser tests,
23 smoke checks, and focused history/detachment tests pass. Evidence and broader
suite failures: `.development-artifacts/sweep-origin-20261009/verification-summary.json`.

## Edit latency (2026-10-08)

`Circle_spiral.nadoc` Full resize reproduced ~27 s, dominated by two 12–13 s
exports: autosave invalidated the first despite unchanged scene inputs. Export
now compares active source fields, batches spline/slab math with scalar authority
parity, caches export-local metadata, skips unrequested coarse geometry, and runs
in one warmed spawned CPU worker. Parent document/revision/integrity gates remain.
Resize refresh overlaps desktop synchronization; native ligation target parsing
is asynchronous, manifest polling is three frames, and GPU staging stays 1 ms.
Four real Vive/OpenXR profiles passed +12/-6, retained selection, stereo/mirror
pixels and independent Undo: 2.97–3.36 s, 89.5 FPS, no repeated/dropped commit
frames. Sub-second edits and consistently <3 s remain open; larger gains need
incremental regeneration/transport. See `docs/audits/vr_edit_latency_20261008.md`.

## Nick / Ligate / Bend / Twist / Sweep latency (2026-10-08)

User fixture policy: do not use `Circle_spiral.nadoc` as a test input or fixture.
In particular, Bend validation must start from non-circularized designs. The
current latency campaign uses an independent straight 24-helix, 48-strand,
12,000-nucleotide bundle with no deformations, forced ligations or feature
history. Earlier Circle evidence is historical only; its interrupted campaign
was stopped when the user supplied this correction.

All five VR commit controllers start revision-pinned canonical export immediately
after the mutation response, overlapping normal desktop synchronization. Nick,
Ligate and their history use the existing geometry-free response header followed
by normal desktop geometry fetch. Detached Sweep reuses desktop partial geometry
only when existing strands survive unchanged; continuations retain full geometry.
VR scene refresh dispatch skips unrelated async simulation preparation, also
improving resize. Normal Deform mode retains its unchanged view-tools tablet:
geometry edits no longer rebuild/transfer/upload its 16 MiB atlas or traverse
scene fingerprints. Overlay streams and explicit action/reset acknowledgements
still update. Export remains in the warmed worker; GPU staging stays bounded. The final
20-case non-circular Full-representation matrix passes: Nick 1.86–1.92 s, Ligate
1.91–2.02 s, Bend 2.39–2.52 s, Twist 2.03–2.16 s, Sweep 2.14–2.22 s. Native
submission cadence is ~89.5 FPS; three compositor drops remain across eight
Ligate commits, with none in the other tools' commit windows. Sub-second edits
and arbitrary-design guarantees remain open.

Inspector observations are compact even with Nick active; use `observe targets`
or MCP `include_targets: true` for the full cached bond catalog. Captures retain
it. The registered Authoring **Tools across representations · frame audit** now
includes Sweep and input-to-ready commit timing. Circle's fixed-endpoint Bend
conflict remains correctly rejected; latency uses an independent 24-helix/12k-nt
straight bundle. All four Bend motion profiles pass on that bundle at
2.39–2.52 s final-input-to-ready (matched pre-change baseline 3.95 s), ~89.5 FPS
and zero repeated/dropped commit frames. Save/reopen and Undo pass. See
`docs/audits/vr_tools_latency_20261008.md` for measured results,
retained failures, observation adjustments and validation limits.

## Bend / Twist exact multi-selection (2026-10-06)

Bend and Twist retain clusters, strands, domains, and mixed canonical sets.
`vr_deformation_selection.js` supplies a session aggregate token; changing any
member invalidates native drafts. Exact refs reach desktop deformation target
resolution and frozen ranges. Startup and live feedback preserve the whole set.
The panel's Change selection / Use selection flow reuses fixed-level accumulation
and the selection volume; plane defaults/projection exclude unselected intervals.
Native cluster/strand/domain picking resolves live topology independently of
whether desktop LOD has bead meshes. Group bend shape handles control shared
curvature from Plane 2; only single-cluster/End poses send world endpoints.
The registered Authoring regression is `deformation_selection_check`; see
`docs/vr_bend.md`. Browser/native software validation is separate from physical
headset review (MV-VR-DEFORMATION-SET).

## End resize pointer and group retention (2026-10-05)

Selected terminal arrows support remote ray hover and trigger-held resizing as
well as proximity grabs. Only the hovered arrow highlights before acquisition;
all selected arrows share the snapped delta while dragging. A controller-to-tip
line carries a signed base count at its midpoint. The browser retains all moved
Base/End refs after commit, supporting repeated equal group resizes. Inspector
state includes pointer/label coordinates and cancellation reasons. Four profiles
pass +12/-6 on two selected ends with stereo/mirror evidence and independent Undo;
variable-deliberate required one retry after an uncommitted cancellation. No
through-lens review. Full unit suite: 7,409 passed, one skipped; builds and focused
native/API checks pass. Failures, framing adjustments and evidence paths:
`.development-artifacts/vr-end-pointer-validation-20261005.json`.

## Controller-relative menus and tip-sphere grips (2026-10-05)

Sidebars now spawn 40 cm along the invoking controller's -Z pointer, with a
30° backward local-X tilt, then remain world-docked. Head pose no longer chooses
menu placement. Desktop uses the same controller orientation at 1.35 m;
View tools now opens following the left controller (October 9 correction below).
Attached authoring/lattice panels inherit their parent pose.
Follow mode and both touchpad wheels share the 30° tilt. Border targeting uses
selection-sphere center (-.12 m in controller space) and the current per-hand
radius against the visible rail band, including its inner edge at minimum
sphere size. Contact metadata preserves the real controller origin for drag/resize
anchoring. Sidebar, desktop, View tools and lattice borders use the same contact
path; lattice interior zoom keeps its existing interaction. Semantic Witness
`touch_menu` and physical grip tours place the tip sphere on the border.
The registered `grips` tour checks both controller spawn poses, midpoint-only
rejection, world-fixed placement, move/resize/release and stereo frame colors.
All four profiles pass for sidebar grips, detached Desktop and both wheels,
including stereo pixels and actual desktop delivery. 72 native tests, 48 focused
Python tests, 7,375 frontend tests and the 397-state menu render audit pass.
Evidence, retained timing/acquisition attempts and cleanup:
`.development-artifacts/vr-controller-menus-20261005/validation.json`. Physical
feel and through-lens comfort remain MV-41.

## Right touchpad Edit wheel (2026-10-05)

The Edit wheel now shares the left wheel's `TouchpadWheel` gesture/render module:
thumb-axis sector hover, light tick on entry, last-held selection on release,
center cancellation and controller-following pose. As of October 16, the six
sectors run counterclockwise from the right: Ligate, Nick, Undo, Redo, Copy, Paste.
The [clipboard workflow](../docs/vr_clipboard.md) snapshots the selected supported
elements and carries a bounded wire preview on the right hand until Paste.
Cluster, minimum-owning-domain, and rigid-element Copy/Paste/Undo pass all four
motion profiles. Small picks promote to their owning domains; overlapping scopes
are deduplicated. The backend supplies the resolved preview, and native scene
exports now include selectable protein traces and nanoparticle cores. See the
[October 16 audit](../docs/audits/vr_clipboard_20261016.md) for scope and retained failures. The old `RadialToolMenu` world-volume
hit implementation is removed. Right-sidebar focus navigation remains when open.
`edit-wheel` is registered under Controls & layout; its empty-scene metadata
fixture verifies history request publication without editing a user document.
Ligate/Nick/avatar probes use profile-driven pad axes. The separate
`edit-wheel-history` tour exercises real document Undo/Redo. Broader Nick/Ligate
pixel workflows still fail (ISSUE-57/58); do not claim their full flows validated. Physical haptic feel and
through-lens comfort remain manual validation (MV-40). Both wheels and real
document history pass all four profiles; 72 native tests and 397 rendered states
pass. Full evidence, failures and cleanup: `.development-artifacts/vr-edit-wheel-20261005/validation.json`.

## Left touchpad selection wheel (2026-10-05)

`selection_wheel.hpp` owns the six-sector thumb gesture and rendering. Hold the
left pad; clockwise from up: Drill, Cluster, Strand, Domain, Crossover, Bases.
Amber hover plus light haptic requests precede release-only scope publication;
center release and focus/tracking loss cancel. The controller-following wheel
uses thumb axes, not world controller translation. It replaces general selection
rows and Move/Rotate scope buttons. Right pad focus stays; left sidebar tours use
pointer scrollbars. Scope changes cancel Move previews, preserving panels.
Registered `selection-wheel` (`menu_tour --selection-checks --validate`) covers
four motion profiles, stereo highlights, haptic requests, delayed commits and
sidebar independence. Physical feel remains MV-39. `selection_wheel` live JSON
exposes six item axes/centers, current scope, hover and visibility.

## Sidebar-only menus and history feedback (2026-10-05)

The old Options/Tools/selection/representation/coloring/jobs/trajectory menu
renderer, hit targets and navigation state have been removed. Current sidebar
panels own settings and tool transactions; Tools contains direct authoring actions
and the left touchpad wheel selects scope. Visualization retains recentering, Simulations owns job
selection and trajectories, and the left VR tab owns the detached desktop.
Radial Undo/Redo dispatch history and pulse the initiating controller without
opening menus. ScryWrite exposes per-hand haptic request counts/amplitudes; its
synthetic input records requests while physical vibration remains suppressed.

The registered Nick/Undo/Redo tour now asserts haptic requests and unchanged,
closed sidebars both at dispatch and after acknowledgement. Navigation, focus,
Extrude/selected-end probes, wheel fixtures and formatting atlas coverage use
only current sidebars/tool panels. The registered Current menu routes entry
(`menu_tour --action-checks --validate`) exercises all five authoring choices,
selection scopes and trajectory controls with four profiles on an empty viewer
and a temporary metadata fixture. See [sidebar guide](../docs/vr_sidebar_menus.md).
Final validation results belong in the current task report; this records the
implemented contract, not a physical headset or vibration verification claim.

## Continuous Move/Rotate at nominal 90 Hz (2026-10-03)

Final full-24HB Ball & Stick cluster drags sustain 89.50–89.53 measured FPS across
all four profiles (the workstation's nominal 90 Hz cadence), zero repeats and
0/1/0/0 drops. All four pass stereo, save/reopen and Undo. Retained changes:
self-shadows off + eight-to-four-sided ordinary bonds during changing previews;
restore full detail after 180 ms settled or preview cleared; ordered atomic event
publication on a worker; mirrored eye rendered last. Full-detail final-binary
control remains 86.37 FPS with 93 repeats / 3 drops, so temporary reduction is
still needed. Motion GPU span p95 is now 5.91–6.12 ms. A fused transform/bounds
experiment showed no clear gain and was reverted. Event publication previously
blocked for 3.1 s; its worker preserves snapshot order and drains at shutdown.

Remote acquisition feedback now includes the original >15 cm condition, fixing
early near-hover termination without changing profiles or thresholds. The settled
tour retains motion/settled stereo captures outside measurement. Six native
checks, full-quality parity, 39 focused Python tests and scoped lint pass.
This is sustained-drag evidence, not a universal no-hitch claim: first-grab setup
is separate; one stationary control shows a 134 ms grouped feed-polling stall.
Through-lens transition comfort remains MV-VR-MOTION-QUALITY. See
[audit](../docs/audits/vr_motion_optimization_20261003.md) and
`.development-artifacts/vr-motion-20261003/`. `NADOC_VR_MOTION_DETAIL=0` provides
full-quality A/B mode; default enables temporary reduction.

## Settled Move/Rotate drag (2026-10-02)

Long held-trigger Ball & Stick cluster tests exclude initial preview and >=5 s
warm-up. Steady-fast/deliberate sustain 77.27/78.39 FPS over 30.38/31.90 s;
last ten seconds remain 77.01/74.59 FPS. Subsequent 10 s stationary holds reach
89.53 FPS with zero compositor repeats/drops. Motion GPU-span p95 ~10.0 ms
versus hold ~7.64 ms; active packed-preview p95 3.00–3.11 ms. Prioritize recurring
transform/upload/presentation costs for continuous motion; this is not merely
startup recovery. Rare event-publication stalls of 62–76 ms are a separate
worst-case-latency issue. Exact upload vs shader vs synchronization attribution
still needs isolation. Both steady profiles pass persistence/Undo; both variable
profiles fail remote-grab acquisition before measurement, so no all-four pass.
Reusable Debug authoring tour `move-settled-drag`; frame audit accepts
`--settled-drag`. 38 focused tooling tests pass. See
[audit](../docs/audits/vr_settled_drag_20261002.md) and
`.development-artifacts/vr-settled-drag-20261002/` for retained evidence and limits.

## Move/Rotate first-grab cache reuse (2026-10-02)

Current-code baseline identified first-grab setup, not continuous transforms, as
the dominant preview stall. Static Full/Stick/Ball & Stick/VDW now construct the
packed preview from the displayed prepared representation, preserving explicit
endpoint weights, aliases, colors, IDs and resident-cache isolation. Visualized
and committed-pose cases retain the general path. Full-24HB Ball & Stick cluster
first-preview work: 560.5 ms baseline → 116.5 ms final steady-fast (79% reduction);
all four final cluster profiles pass edit, stereo, save/reopen and Undo, with
113–123 ms first previews. This is still above the 11.111 ms budget. Continuous
motion/uploads are unchanged; no sustained-90-Hz claim. Eight isolated setup
cases improve; all 32 paired images match exactly. Five native checks pass.
Live nucleotide acquisition fails before preview, also reproduced in the baseline;
do not claim full live nucleotide coverage from the isolated renderer results.
The existing Debug authoring renderer regression now covers prepared first grabs
and accepts `--compare-setup` with `--scene-dir` for reproducible A/B measurements.
See [audit](../docs/audits/vr_preview_preparation_20261002.md) and
`.development-artifacts/vr-preview-20261002/` for results and failed attempts.

## Staged static scene activation (2026-10-02)

Static refresh now reuses the live renderer and stable object IDs, uploads prepared
buffers with a 1 ms/256 KiB per-poll target, then atomically swaps after a nonblocking
fence check. Old geometry/picking remain active until ready; CPU caches retire on
the worker. Nonempty visualization snapshots retain the synchronous fallback.
Full-24HB Ball & Stick isolated blocking activation 976 ms becomes <=1.15 ms
staging polls. Two physical OpenXR reloads: staging/swap at nominal 90 Hz with no
long submission gaps, max stage 1.30 ms / swap 0.062 ms. The broader parse-to-ready
interval still had three gaps in the first reload; no universal 90 Hz claim.
Six native checks and 35 tour tests pass; FAST suite has 9525 passes, 93 skips,
and six failures in unchanged geometry/surface/representation-control code.
Subsequent user-authorized FULL validation ran 10,130 tests: 10,002 passed,
94 skipped, 18 failed and 18 setup errors. Explicit GROMACS thread-MPI rank
selection repaired all 18 setup errors (18/18 focused reruns pass); the 18 other
failures remain and FULL debt is retained. See
`.development-artifacts/deferred-validation-20261002/findings.txt`.
Debug > VR Tours & Tests > Authoring includes scene-activation regression.
Evidence: `.development-artifacts/scene-activation-20261002/findings.txt`.
This supersedes the static activation stall below, not active visualization or
End Resize correctness limitations. Before this round, cluster tint removed the
duplicate glow and selection-triggered rebuild; older glow timings are historical.

## Researched CPU fixes and desktop-off validation (2026-10-02)

Retained: indexed owner lookup, selection-aware hover, cached preview bounds,
async parsing and one-pass style activation/CPU-source retirement. Audit drawing
now defaults off; production preference and native mirror unchanged. Full-24HB
Bend lookup <1 ms, hover ~0.31 ms, highlights ~39 ms (first candidate ~392 ms).
End Resize activation ~423 ms (first candidate ~1,282 ms); +6/−6 failure remains.
Both GPU candidates rejected: conservative depth ineffective; cached cylinder
frames regressed live rotation ~45→36 FPS despite isolated GPU improvement.
Original renderer restored. Final 28 attempts, 9 workflow/audit passes; no 90 Hz
certification or hardware ceiling proven. Native 4/4 and focused Python 62 pass.
See [research and feature table](../docs/audits/vr_research_fixes_20261002.md), with
remaining style/activation/GPU/pacing limits and evidence links.

## Desktop contention isolation (2026-10-02)

Fresh full-24HB Ball & Stick draw-only controls confirm desktop GPU contention:
selected nucleotide idle 47.46→89.53 FPS, compositor GPU p95 12.71→7.51 ms.
Cluster idle remains 44.76 FPS although GPU p95 falls 18.21→12.69 ms. Device-wide
utilization is only ~56% for desktop-off cluster: half-rate pacing leaves idle
GPU time; do not require 100% utilization to diagnose missed 11.111 ms deadlines.
Both corrected draw-only edit/save/reopen/Undo controls pass. Selection lookup
scans, full style rebuilds on changed highlights, synchronous scene refresh and
model-sized preview uploads were separate software targets at that point. The End Resize
4.19 s input stall coincides with VR_SCENE_APPLIED; not all of it is pure CPU.

Help → Desktop 3D during VR now provides a persisted draw preference (default
on), paused notice/resume control, and automatic normal desktop drawing after
VR exits. Callbacks and scene updates continue; WebXR is unaffected. This does
not fix hidden-tab requestAnimationFrame suspension or disable native mirroring.
Four-profile preference validation passes all four steady workflows; all four
variable workflows retain prior target-acquisition failures. Final UI/edit/Undo
verification passes. See [bottleneck report](../docs/audits/vr_bottleneck_isolation_20261002.md)
for controlled conditions and remaining limits. A diagnostic Playwright route
must be removed before synchronous native probes, otherwise browser network
feedback stalls; failed setup traces are retained. Test teardown now resolves
the actual frontend root and random smoke port for bridge-credential cleanup.

## Ball & Stick 90 Hz follow-up (2026-10-02)

User time box ends 18:00:40 UTC; two optimization candidates maximum per workflow,
Surface performance excluded. Shader experiment was pixel-identical but ineffective
and reverted. Retained candidate avoids first eligible Move commit/Undo rebuilds.
A PBO/fence readback experiment was also reverted after only a ~0.19 ms median
sample-cost change with no cadence gain. Final native parity/diagnostic checks pass. Comparable full-size Move/cluster edit/save/reopen/Undo pass; longest measured
frames fell ~307→34 ms and ~715→34 ms, but sustained cadence still misses 90 Hz.
Desktop Playwright focus emulation can retain ~60 FPS desktop draws during VR.
Minimizing stops draws but pauses callbacks and can block cluster commits; that
experiment was archived and its dependency/harness focus changes restored. Do not
use it as a production remedy or attribute all GPU cost to native rendering.
Completed 48 second-candidate cases across all four profiles (8 workflow passes),
then both final retained-code Move checks passed. All 12 feature categories remain
unresolved for consistent 90 Hz; Bend selection reached 838 ms and End Resize
commit 4.21 s. Browser-free idle/grip baseline passed 12 intervals / 4,612 frames.
See [campaign report](../docs/audits/vr_ballstick_90hz_20261002.md) and its compact
review ZIP. No fundamental hardware limit proven; original 24HB preserved and
audit viewers closed.

## Full-size 24HB audit (2026-10-02)

Full-size follow-up uses private copies of `workspace/24hb_0xT.nadoc` (24 helices,
76 strands, 6,720 nucleotides; original SHA unchanged). Fresh physical OpenXR
baseline: 48 idle/grip intervals, 18,450 frames, roughly 89.36–89.64 FPS across
Full/Stick/Ball & Stick/Quick Surface. Synthetic controller profiles, not wearer
validation. Controlled 12-tool × 4-style × 4-profile matrix completes 192 attempts;
31 complete workflow/audit passes (14/6/7/4), plus four separately failed Full
Nick observation retries. Latest requested-style measured coverage is 48/45/44/43
of 48 respectively; valid traces alone do not imply tool-stage success.

Confirmed full-size candidates: selected Surface Move `pick` p95 ~32.74 ms,
~21 FPS without repeated `setStyle` calls; Ball & Stick cluster commit includes
~654 ms inclusive `setStyle`; End Resize native +6 can save -6 at an interior
forward 3′ end because non-singleton outward sign follows nearest helix endpoint.
The initial dataset collection did not implement these fixes; the later 90 Hz
follow-up above addresses eligible Move commits. Preserve failures, selection
semantics and invalidation correctness.

An earlier long multi-launch campaign exhausted Steam shared memory; graceful
Steam/SteamVR reset reclaimed it. Controlled batches reset between styles and
record host resource counters; this does not establish a NADOC leak or growth
in one uninterrupted session. Fixed benchmark budget is 11.111 ms at 90 Hz,
independent of adaptive OpenXR pacing. Compositor GPU spans overlap CPU wall
time and are not isolated shader cost. Dataset retains 409 attempts and 4,592
interval rows, with an offline browser, CSVs and compact provenance ZIP; complete
raw logs/capture trees stay in the archive. See the
[full-size audit](../docs/audits/vr_24hb_tool_performance_20261002.md).

## Frame calculation audit (2026-10-01)

Opt-in native `NADOC_VR_FRAME_AUDIT=1` records exclusive outer-frame phases and
inclusive calculation counts/times. Live audit entry points are
`tools.vr_workflows.frame_audit_tour` (private 24HB idle/grip, four representations)
and `tool_frame_audit` (isolated tool fixtures). Raw compositor delivery and GPU
timing are separate from application wall time; scene-only p95 is not a full
budget check. Findings, reproduction, failed attempts and coverage boundaries:
[frame calculation audit](../docs/audits/vr_frame_calculations_20261001.md).

Confirmed: standalone deferred representation activation needed polling even
without lazy startup (fixed). Quick Surface selected Move still rebuilds style
(~45 ms per changed preview on a small 6HB fixture); Full/Stick/Ball & Stick use
packed updates. Spectator diagnostics synchronously read pixels every 30 mirror
frames, causing recurring p99 wall costs invisible to p95. Neither candidate
optimization has been implemented by this audit. Preserve readback provenance
and slab geometry authority when optimizing; do not lower render quality.

## Production scrollable sets and history (2026-10-08)

Sweep points now use a grouped rail; Dimensions uses aligned outlined-table
columns; simulation jobs use native beveled cards with status detail. Feature
Log has a versioned desktop-authoritative native rail: preview notch while
trigger-held, seek on release, independent list scroll, per-row edit/revert/delete,
F0 and expanded routing children, and desktop assembly/part/configuration targets.
Specialized editors and confirmations use the interactive in-headset desktop
surface. Pending seeks/operations/scene exports disable history actions; stale
versions and duplicate commands are rejected. The reusable review is registered
under Controls & layout → Feature history and production lists. See
[production list behavior](../docs/vr_sidebar_menus.md#production-scrollable-sets-and-feature-history-2026-10-08).

## Component gallery (2026-10-01)

Debug → VR Component Gallery now offers native VR and headset-free desktop
thumbwheel evaluation demos. Both share solid ridged meshes and inertia, with
20/35/50% exposure columns and 0–10/100/1000 range rows. Extrude and Bend share
the new clipped solid rendering. Launch, controls and validation:
[component gallery](../docs/vr_component_gallery.md). Range-dependent sizing is
approved by the user: Extrude uses 0–1000 / 35%, and Bend uses 0–100 / 35% with expanded layout and raised-surface hit testing. The gallery also offers six button styles inspired by MRTK, visionOS, Material and Blender, with VR/desktop demos and all-four-profile validation. Cards and lists adds six expandable studies with selectable children and the same launch modes. Scrollable sets (2026-10-08) adds six bounded-list studies: inset tray, outlined table, job cards, sweep rail, grouped set, and pinned inspector. Twelve sample rows per set have independent actions and persistent selection, draggable rails and UP/DN targets. Desktop/VR launch and profile validation are registered; native interaction/render checks cover the new lists. Production feature binding and through-lens comfort remain separate.

## Resource limits after the October 1 UI evaluation crash

The workstation exhausted RAM while native C++ builds, the auto-parallel backend
suite and unrestricted Vitest ran together. The user requested cautious resumption.
For subsequent local VR UI work, run these jobs sequentially: native builds with
`-j1` and reduced priority; Vitest with `--maxWorkers=2`; focused backend checks.
Check available RAM and memory pressure before launching the next job. Preserve
suite guards and report interrupted broad checks as incomplete. Do not stop user
applications to make room for validation.

## Selected-part Move/Rotate slowdown (2026-10-01)

User clarified the FPS drop concerns the selected-part Move/Rotate tool. A
controlled production-GlScene diagnostic reproduces full representation rebuilds
on every changed preview: single-base translation medians are Full 18.5 ms,
Stick 161 ms, Ball & Stick 294 ms, VDW 130 ms on the saved 24-helix part.
This is separate from whole-model grip/browser contention investigations below.
Packed preview caching is now implemented for Full/Stick/Ball & Stick/VDW.
Full update+draw p95 is 2.4 ms in the controlled 24-helix test; VDW and single-base
atomistic selections also fit 11.1 ms. Large Stick/Ball & Stick cluster draws
remain above budget (14.1/16.5 ms total p95). All 32 renders exactly match baseline.
Four live Full base-edit profiles pass with 520 compositor samples and no
repeats/drops during measured edits (GPU p95 1.73–2.51 ms). The 24-helix numbers
remain isolated renderer timings, not live atomistic FPS. See the
[optimization audit](../docs/audits/vr_move_rotate_optimization_20261001.md) for
correctness, live validation, remaining setup hitches and reproduction.

## Motion regression (2026-09-29)

The user confirms loaded-model motion was satisfactory before the loading-freeze
changes. Isolate that regression rather than changing shadow quality or lighting.
Rendering experiments did not clear the timing gate and were reverted.
See [investigation](../docs/audits/vr_motion_regression_20260929.md).

## Quick Expand removed from VR (2026-09-29)

VR now exports, parses and caches natural geometry only. The View Tools tablet
has ten entries; the Expanded control and native animation are removed. End,
plane, ligation and resize catalogs no longer calculate expanded placements.
Legacy feedback readers accept old paired fields only for wire compatibility;
there is no expansion rendering or interaction state. Desktop expansion stays
separate and cannot override the natural VR model. Use model scaling and physical
movement for close inspection. See the startup/load-time comparison in
[removal audit](../docs/audits/vr_quick_expand_removal_20260929.md).

## Visible model during representation loading (2026-09-29)

The frame-gap guard now draws an unlit point cloud from the displayed GPU
buffers instead of suppressing the model. Atoms, bond endpoints and surface/box
centres retain colors, object IDs, depth and model transforms; CPU picking remains
on the displayed representation. No extra export or geometry upload is needed.
Normal rendering resumes on completion, cancellation or failure. The existing
on-demand representation tour checks both-eye model pixels during loading and
covers Surface → Stick. See [visibility audit](../docs/audits/vr_loading_visibility_20260929.md).

## Loading frame delivery (2026-09-29)

Static natural representations prepare geometry/indexes on the parsing worker,
upload in 1 ms / 256 KiB slices, and activate after a nonblocking GL fence. GPU
inactive cache is 256 MiB; CPU inactive sources are budgeted at 512 MiB (Full,
active and view-volume sources protected). CPU disposal and latest avatar-file
publication run off the XR thread. The earlier loading hitch was avatar I/O,
not merely GPU draw time. Shadow reuse was removed during investigation of the subsequent motion regression;
the original head-relative lighting and shadow pass are restored.
Debug → VR Tours & Tests → Representation loading frame delivery retains outer
loop/subphase timing and actual SteamVR compositor samples. Logs are asynchronous;
trace overflow fails acceptance. Use the fastest observed runtime period for
the guard/gate: SteamVR may lengthen predicted periods during reprojection.
Existing draw-only green metrics are insufficient. Full-state RPC progress polling
uses 100 ms spacing; motion profiles and their 150 ms deadline are unchanged.
Dynamic deformation/expansion paths and physical comfort remain distinct checks.
See [implementation audit](../docs/audits/vr_loading_frame_delivery_20260929.md).

## Browser/native verification and backend lifetime (2026-09-29)

Use the registered `browser-representations` tour for real browser launch/style
acknowledgements; `startup_tour` has a private responder and cannot establish that
path. Browser readiness requires loaded geometry and a dismissed Welcome screen,
not only backend document metadata. The tour opens an isolated __e2e__ copy,
asserts identifiable geometry in both eyes, and owns cleanup. `backend-lifetime`
checks real worker shutdown. `vr_lifecycle` tracks Popen ownership and joins native
cleanup on FastAPI lifespan teardown. Do not ask the user for the View in VR click
when automated browser orchestration can perform it.

## Early VR loading and menu depth (2026-09-29)

Normal launch now enters OpenXR before model export, with a head-height,
view-facing loading panel and named preparation stages. Export uses a private
copy of the document; native parsing is asynchronous, and GPU preparation submits
loading frames during preparation. First-frame readiness continues to mean the part.
Startup loads Full in its natural pose only. Other styles export and
parse on demand, with a counted-work percentage/bar inside the selected button;
previous geometry stays visible. Cached CPU geometry is reused until scene refresh or budgeted eviction.
Menu blur uses same-eye depth rejection; controller sticks, spheres and other
world-space guides write depth so foreground elements remain sharp.
See [startup and depth behavior](../docs/vr_startup.md). Debug Controls & layout
includes reusable `startup`, `representation-loading`, and `menu-depth` checks. Stereo evidence does not
establish worn-headset comfort or a fresh operating-system reboot.

## Frosted menus and calibrated floor (2026-09-28)

Native menus now use per-eye blurred white glass (`frosted_glass.hpp`), including
sidebars and the view-tools tablet. The user prefers barely visible frosting: 10% white, 90% blurred scene, with light
lettering and very faint button fills. Tablet SVGs retain desktop RGB/gradients
and computed styles; native-only controls use stable subtle accents. See the
[white-glass audit](../docs/audits/vr_white_glass_20260928.md). `room_floor.hpp` anchors a 0.5 m grid and cyan
play-area rectangle to OpenXR STAGE, never model transforms or invented bounds.
Debug → VR Tours & Tests → Controls & layout → Frosted menus & SteamVR floor
runs the isolated `room-ui` demo/validation. All four profiles pass stereo blur,
calibrated-edge and actual desktop checks. Worn-headset review remains pending.
See [usage](../docs/vr_room_ui.md) and [audit](../docs/audits/vr_room_ui_20260928.md).

## Earlier static simulation results (2026-09-28)

The initial static-only implementation and its 22-mode coverage are historical:
[September audit](../docs/audits/vr_simulations_20260928.md). The October native menu
above replaces its separately expanding pane and adds trajectory transport. The
known CanDo small-design predicted-shape bug remains deferred by the user; framing
that result establishes visibility, not scientific correctness.

## Standing user requirement: organized VR tours

Every future session adding or changing VR behavior must create or extend a
reusable tour/test and organize its entry in **Debug → VR Tours & Tests…**.
Register it in `tools/vr_workflows/tour_catalog.py` under the related sidebar tab
or interaction category; follow the [registration checklist](../docs/vr_sidebar_menus.md#adding-future-tours-and-tests).
Do not leave new major demos or validation workflows as undiscoverable shell commands.

## Quiver gesture for scissors (2026-09-28)

Right reach-back equips/stows Nick; left reach-back independently opens/stows the
view-tools tablet. Matching shoulder position and upward/backward controller aim
trigger immediately; returning in front rearms, without dwell. Tracking loss and
focus/button guards disarm, and require a fresh front-to-shoulder reach.

October 9 lifecycle repair: ordinary open sidebars no longer disable reach-back.
The left shortcut remains available during right-hand tools/pending edits; right
scissors require leaving the active modeling tool first (user preference).
The shoulder path no longer shares Bend/Sweep's contextual radial action mapping.
The tablet starts and remains attached to the left controller, including after
returning in front. Tiles stay active. Dock freezes it; Follow reattaches to the
left hand. Reaching back dismisses either mode, and reopening starts attached.
Either hand holding its border by trigger or grip can stow it with the matching
shoulder gesture; this consumes the grab without toggling scissors. Header Close
and nearest-panel pointer beams are supported. Trigger borders retain the shared
RemotePanelControl movement/resize rules. Schema 5 carries normals for native
lighting/shadows; color/label toggles keep the canonical shadow map. Layout
changes cast their displayed geometry; labels/lines remain unlit.
`ligation.quiver.blocked` and `view_tools.following` expose these states to the
inspector. Failed browser publication of nick/ligation and resize completion
feedback must remain retryable: `_request` returns null rather than throwing.
Never mark that null delivery as acknowledged, or native pending-edit state can
remain locked indefinitely.

`--quiver` in the production live-test binary checks lifecycle transitions;
Debug → VR Tours & Tests → **Reach-back · tool exit and reactivation** runs it.
The existing Nick and View Tools physical tours check all four profiles and now
assert continuous controller following. Old September 28 evidence predates this lifecycle fix;
see `docs/vr_view_tools.md` for current behavior and physical validation limits.

## Radius-wheel Nick and history (2026-09-28)

All four wheel sectors are now active. Undo/Redo use the ordinary desktop design
history and refresh native geometry. Nick replaces both selection spheres with
scissors: analog trigger pressure closes the blades and brightens the candidate
backbone bond; the existing full-click threshold creates one backend nick. A held
trigger cannot repeat the edit. The browser shares the versioned, serialized
ligation transaction path for Nick/Undo/Redo; requests are deduplicated per session.
Nick keeps the canonical selection level `base` while owning bond targeting itself
(the event protocol does not have a `bond` selection level).
Debug → VR Tours & Tests → Tools · Authoring → **Nick with scissors, Undo and Redo**
is the discoverable demo and four-profile validation route. The API excludes
synthetic/loop-copy/ambiguous-coordinate targets. See [workflow](../docs/vr_ligation.md).
All four physical runtime profiles passed nick, partial-pressure pixels, empty
click, held-trigger non-repetition and exact wheel Undo/Redo. Evidence:
`.development-artifacts/vr-nick/145d008fa4/`; see the
[audit](../docs/audits/vr_nick_history_20260928.md) for the retained protocol failure
and remaining Expanded/large-design/human checks. User deferred the previously
reported apparent moving/resetting base; do not claim this work resolves it.

## Radius-wheel Ligate (2026-09-28)

Latest user direction replaces the four radial tool sectors with Ligate/Nick/Undo/
Redo. Ligate was implemented first; Nick and history now also work as described
above. Existing tools retain sidebar entry points. Either controller can
trigger-pick a real 3′ or 5′ end, stretch a cyan preview, snap green to a compatible
opposite end on another strand, and release to create one forced ligation through
the desktop API. Versioned catalogs and deduplicated release events protect the
transaction; scene/menu/tracking changes cancel active drags. Each saved bond is
independently undoable on desktop.
Debug → VR Tours & Tests → Tools · Authoring → **Ligate ends with the touchpad wheel**
runs the reusable demo or four-profile validation. All four profiles passed both
pickup polarities, invalid release, native refresh, stereo/mirror preview pixels,
saved-bond pixels and exact Undo. Evidence: `.development-artifacts/vr-ligation/69c3958ea7/`.
See [workflow](../docs/vr_ligation.md) and [audit](../docs/audits/vr_ligation_20260928.md)
for the retained acquisition failure/retry and human/Expanded/large-design limits.

## Selected-end trigger resizing (2026-09-28)

Selected end arrows now accept either controller's trigger grab: outward extends,
inward shortens, release saves through the desktop strand-end-resize API. Shared
collision/terminal limits and whole-bp snapping apply to all selected arrows;
each release is independently undoable. Grips still move the scene and cancel
an active end drag. Versioned handles reject changed targets/designs.
Debug → VR Tours & Tests → Tools · Authoring → **Resize selected ends** runs an
isolated demo or all four motion profiles. Final campaign passed +12/−6 bp,
scene refresh, projected stereo/mirror pixels, negative control and Undo for all
profiles. Evidence: `.development-artifacts/vr-end-resize/42939ae168/`.
See [workflow](../docs/vr_end_resize.md) and [audit](../docs/audits/vr_end_resize_20260928.md)
for retained failures and the remaining human/Expanded/multi-end validation scope.

## Mission and current state

VR recovery starts with [the restoration guardrails](feedback_vr_restore_proven_path.md)
and [the workstation fix record](project_steamvr_drm_lease_fix.md). On 2026-09-08 the
user confirmed the existing physical left-eye mirror displaying `24hb_0xT` worked
after restoring direct mode/GPU selection and using existing dummy framing. Do not
recreate that method; this confirmation does not close controller/editing gates.

Make NADOC's native VR view a faithful, comfortable counterpart to the desktop application without creating a second geometry, selection, or job model. As redirected on 2026-08-20, the active implementation priority is now complete in-headset **Extrude** and **Move/Rotate** UI/UX; Twist/Bend and simulation-result expansion remain secondary until those two workflows have safe Confirm/Cancel/Undo transactions and pass their physical gates.

Current integration branch: `master`; optimization branch integrated in `7c235bb4`. The older native navigation baseline was developed on `feature/native-vr-navigation`.

Shipped baseline:

- `87ba1698` — native OpenXR viewer fallback.
- `dcc9eb4e` — molecular inspection controls and Steam dashboard access.
- `93da06b1` — self-shadowing and a more faithful Full representation.
- `44353007` — faithful overhang half-cylinders and extension markers.
- Current VR supports headset/controllers, grab and two-hand scale, recenter, in-VR representation/color menus, near inspection, and SteamVR desktop access.

## Representation switching benchmark (2026-09-27)

Debug → VR Tours & Tests → Right sidebar → Visualization demo (current open design)
runs the maintained `tools.vr_workflows.representation_tour` workflow. The nested
Debug menu directly launches a private snapshot of the active document, including
unsaved edits; CLI defaults to workspace/24hb_0xT.nadoc. It exports all eleven desktop representation choices (Beads and VDW share source geometry),
and exercises all 110 directed transitions with physical OpenXR and ScryWrite.
Its private style responder isolates native renderer latency from browser polling.
Visualization tours now reuse byte-verified immutable exports across resets via
`tools/vr_workflows/snapshot_cache.py`, capped at two entries / 2 GiB under
`.development-artifacts/vr-scene-cache`. Keys cover full design bytes, backend
exporter/geometry/template files, workflow exporter and uv.lock; edits invalidate.
`--no-cache` provides an explicit cold measurement. The earlier four-representation 24hb baseline was
42.93 s cold versus 11.09 s warm to live readiness (export 32.54 s vs 0.317 s).
That baseline loaded in roughly 10.6 s; the complete eleven-style catalog includes a much larger surface mesh. See `docs/audits/vr_all_representations_20260927.md` for current measurements.
The tour waits for tracked-eye placement, closes the left sidebar and moves the
right sidebar 0.35 m along its own horizontal axis using the real grip path.
An enlarged isometric view and submitted-eye pixel checks require an unclipped
design separate from the menu before and throughout the switches.

`representation_buffers.hpp` caches GPU instance buffers for unchanged static
styles; one color per representation, prepared before interactive rendering.
Natural ownership indexes are retained so object IDs remain
correct without rebuilding large hash maps on every style change. Highlighted,
transformed and trajectory geometry bypasses the static GPU cache;
baked changes clear caches. See `docs/audits/vr_representation_switching_20260927.md`
for timings, validation and remaining scope limits.

Complete representation validation: all 440 directed switches passed across the
four controller profiles; the final color cycle passed 22 menu-pixel checks and
actual desktop correspondence 1.0. Unsupported color choices use the desktop
support table and remain gray. The new **Representation colors** Debug entry runs
that shorter cycle on the current design. Current 24hb export is 1.62 GB, 80.48 s
cold, with 23.63 s native readiness; cached checksum preparation varies from
0.70 s warm to 16.21 s on the Archive drive after a long tour. See the audit above;
the older four-style startup timings are not the complete-catalog timings.

## Controller Dimensions (2026-09-27)

`dimensions.hpp` owns model-space measurements;
`dimension_panel.hpp` owns focused panel/restore and input arbitration. Dimensions
or Measure in right Properties hides both sidebars. Each trigger pins/recalls its
controller tip; new/exit freezes the old line. Model grip movement/resizing carries
measurements, preserves nm, and pins live endpoints. Eye/eye-off and X match the
desktop entry controls. Commands stay fixed above five scrolling entries, with
new-entry auto-scroll; menu-button or main Dimensions-button restores both menus.
Use `just vr-menu-tour --dimension-checks --validate` for physical-runtime synthetic
input and stereo/desktop evidence. See `docs/audits/vr_dimensions_20260927.md`.
Measurements persist through the document-bound native journal and appear in the desktop Dimensions list. Saved document measurements import at VR launch. Human through-lens validation remains separate from synthetic checks.

## Desktop-mapped sidebars (2026-09-27)

Desktop verification now samples X11 concurrently with native capture encoding,
retaining per-sample scores without pausing XR rendering or relaxing the 95%
threshold. A desktop mismatch keeps the default tour open for review and reports
failure; `--exit` still fails immediately. See `docs/audits/vr_desktop_capture_20260927.md`.

Left/right controller menu buttons independently open their matching desktop
sidebar; both can remain open. Outer vertical tabs preserve desktop ordering,
labels and dark/blue styling. Tools is appended on the right; the right-trackpad
shortcut is retained. Unsupported controls are gray and consume clicks. Existing
native representations/colors, recenter, tools, jobs and trajectory panels remain
connected through thin adapters. Tool and trajectory availability is contextual.

`sidebar_menu.hpp` owns layout/state and `sidebar_runtime.hpp` owns placement,
rendering and input. `frontend/scripts/generate-vr-sidebar-catalog.mjs` generates
851 rows/options in `sidebar_catalog.json` and its native header from the desktop
DOM plus source-linked dynamic control templates. Check drift with
`just vr-menu-catalog-check`. Detailed usage: [VR sidebar menus](../docs/vr_sidebar_menus.md).
`just vr-menu-tour` runs a visible isolated ScryWrite tour; `--validate --hold 0
--exit` covers all pages with all four unchanged human-motion profiles. It keeps
stereo/pixel evidence and checks the actual owned desktop mirror. Headset comfort
still requires physical human review. Evidence lives under
`.development-artifacts/vr-sidebar/`; failed iterations are retained. Final full
tour: all four presets passed 113 pages / 851 controls each; imprecise fast and
deliberate profiles required 43 and 41 retries respectively, all successful on
the second attempt. Native 37/37 and focused Python 8/8 passed. See the
[audit](../docs/audits/vr_sidebars_20260927.md).

## Grippable menu frames (2026-09-27)

Sidebars now reserve wide outer rails with corner/side grip marks, proximity and
move/resize colors plus status text, and acquisition haptics. Shared MenuPlacement
keeps the 75 mm physical near-grip tolerance; sidebar targeting chooses the nearest
edge and retains grip ownership. Capture metadata exports frame targets/state and
panel position/scale. `just vr-menu-tour --grip-checks --validate` exercises both
menus, model isolation and pixel feedback. Evidence: `.development-artifacts/vr-grip-frame/`.
Detailed menu/lattice outlines share the frame styling.

## Collapsible VR cards (2026-09-27)

The sidebar catalog now includes desktop card titles and ancestry, including
nested simulation cards and details. Native sidebars toggle sections via either
pointer/trigger or touchpad focus/trigger, keep independent session state, hide
collapsed descendants from input/export/rendering and recalculate scroll ranges.
Cards start expanded; toggling retains the title on the current visible page.
The existing focus tour now checks both input paths for both hands. Evidence:
`.development-artifacts/vr-cards/`; see `docs/vr_sidebar_menus.md`.

## UI style and trackpad focus (2026-09-27)

Sidebar buttons now have rounded fills/outlines, desktop muted borders and subtle
blue action / red Close accents. Scroll up/down buttons are replaced by a vertical
scrollbar, on the left of left-menu content and right of right-menu content.
With rail focus, pad up/down pages while retaining focus; left/right
exits to adjacent controls. Pointer trigger positioning also scrolls. Tests and
live evidence are in `.development-artifacts/vr-scrollbar/`.

`ui_style.hpp` centralizes native sidebar colors/focus/press tokens;
`menu_focus.hpp` owns input arbitration. Per-controller trackpad clicks navigate
its open sidebar or sidebar tool panel. Sidebar up/down stays in its column
and clamps at both ends (including unavailable controls); left/right moves
spatially between tabs, scrollbar, and content, mirrored on the left hand.
Tab selection requires trigger. Initial focus uses the pointed-at control or
the active tab. Detailed lists also clamp rather than wrap. Trigger activates; center
click explicitly restores pointing. A ray must leave its initial resting target
and dwell on one target for 450 ms to restore pointing automatically. Held
triggers suppress handoff. Gray controls remain inert. The radial Tools shortcut
now applies when the right menu is closed, as approved by the user. Physical
trackpad touch scrolling is suppressed while navigation focus is active.

ScryWrite exports mode/focus and accepts validated `trackpad_axis` input before
ordinary click events. `just vr-menu-tour --focus-checks --validate --hold 0
--exit` exercises both hands and pointer handoff with all four motion profiles.
Evidence: `.development-artifacts/vr-ui-focus/`; style research and asset/license
shortlist: [VR UI standard](../docs/vr_ui_style.md). No third-party assets bundled.
Final focus checks passed all four profiles (one extra reach per pointer
handoff); 37 native, 20 live-bridge and 3 pixel tests passed. The actual desktop
comparison passed at 99.04%. See [focus audit](../docs/audits/vr_ui_focus_20260927.md).
Headset comfort/haptic strength remains on the manual validation debt list.

## Binding invariants

VR loading optimization (2026-09-27): export-local bounded caches now reuse
selection tokens and per-base atomistic ownership; validated atom base keys are
reused at bond endpoints. Synthetic 6k/30k-atom serialization is 1.92–1.94× faster
with exact wire/manifest parity. Both natural and expanded outputs of the real
1,740-atom two-helix fixture are byte-identical and pass native gzip validation.
77 focused VR tests pass; FAST has 9,257 passes and one unchanged scalar/array
geometry exact-equality failure. These are export timings, not headset startup
or FPS measurements. See [loading review](../docs/audits/vr_loading_20260927.md)
for measurements, incoming optimization review, and larger transport candidates.

Atomistic shadow parity (2026-09-27): Ball-and-Stick and Stick now cast and
receive the same 2048² soft self-shadows as Full; the representation-specific
shadow bypass was removed. Native build and all 36 CTest checks pass with the
system linker. SteamVR was not running during verification, so rendered shadow
appearance and dense-scene headset frame timing remain unverified.

2026-09-29 correction: the atomistic color pass still used an unlit GL_LINES
branch despite the earlier shadow-pass fix. It now uses Full's lit cylinder
renderer. A real GL removed-occluder control proves cast shadows (36 receiver
pixels); the browser/ScryWrite tour captures visible Stick/Ball & Stick in both
eyes. Sidebar pad navigation now reveals one logical row with 200 ms easing and
ancestry indentation. See [shadow/scroll audit](../docs/audits/vr_shadow_scroll_20260929.md).

1. Desktop geometry, topology, job data, and visualization state remain authoritative. VR is a projection and intent source, never a competing model.
2. VR selection emits normalized intents through the canonical selection controller; it does not become a second state writer. Assembly selection remains an explicit boundary.
3. DNA polarity and topology follow `REFERENCE_DNA_TOPOLOGY.md`. Ask before encoding an ambiguous handedness, strand order, loop/skip, crossover, or spatial relation.
4. Keep the composition root thin. Cohesive VR logic belongs in testable modules, not `main.js` or route handlers.
5. Never mutate a shared live server merely to verify behavior. Use pure/unit tests, isolated fixtures, or read-only inspection.
6. A visual change needs both a numeric/snapshot oracle and an actual rendered-image or headset check. A status label is not visual verification.
7. Each phase ends in a narrow, reversible checkpoint commit. Stage only phase-owned files in the shared worktree; never stash, reset, restore, or sweep up unrelated edits.
8. Preserve user scale and spatial context across representation changes. Display element sizes must be derived from model-space geometry and one world transform, never camera distance or FOV visibility.

## Phase-boundary loop

At every phase boundary:

1. Record shipped behavior, evidence, known debt, and unresolved questions here; move obsolete history to `project_native_vr_archive.md` only when this head approaches 200 lines.
2. Re-evaluate the complete headset workflow for discoverability, reach, visual legibility, comfort, error recovery, dominant-hand assumptions, and desktop escape hatches.
3. Research or refresh appropriate fidelity, interaction, comfort, and performance metrics from primary/official sources; revise thresholds when evidence warrants it.
4. Update later phases from what was learned, run proportionate automated checks, and record any manual headset validation still owed.
5. Make a clean checkpoint commit after review. Push checkpoints that are useful for remote recovery or user testing.

## Phase ledger

| Phase | Scope | Exit checkpoint | State |
|---|---|---|---|
| 0 | Durable plan, source inventory, validation metrics, fixture strategy | Memory lint; inventory and first acceptance matrix recorded | Complete |
| 1 | Exact static visual fidelity: overhangs, crossovers, forced ligations, extra bases, extensions, same-helix domain gaps, ends/markers/arcs | Primitive/topology parity tests plus headset visual check | Manual gate |
| 2 | Scene-projection contract and representative VR regression fixtures | Stable-ID scene snapshots, tolerance tests, failure diagnostics | Complete |
| 3 | Expanded Quick View controller shortcut | Superseded: right trackpad now owns radial Tools; no quick-expand binding | Superseded |
| 4 | VR picking and selection intents from cluster through smallest supported element | Canonical selection matrix passes in desktop and VR | Manual gate |
| 5A | Complete Move/Rotate UI/UX: exact previews, Confirm/Cancel, transaction-bound one-step Undo, recovery | Cluster/Base/End/Domain/Strand workflows pass transaction and headset gates | Automated gate complete — physical gate required |
| 5B | Complete exact-End Extrude UI/UX: settings, preview, revalidation, Confirm/Cancel, one-step Undo | One-cell continuation workflow passes safety, fidelity, and headset gates | Queued behind 5A |
| 5C | Twist/Bend editing transactions | Safe preview/commit/undo with plane-pair fidelity | Deferred by user redirect |
| 6 | Unified job-list shell and simulation-result navigation in VR | Job identity/status/action parity with desktop | Active (read-only live-status foundation) |
| 7 | Every simulation engine's visualization options and time/result controls | Engine-by-option parity matrix and playback checks pass | Queued |
| 8 | UX polish, accessibility, comfort, performance, resilience | Sustained task tests and headset regression checklist pass | Queued |

## Provisional validation contract

Ratify thresholds during Phase 0 research; do not silently turn provisional numbers into science gates.

- Geometry fidelity: primitive count/type/visibility by stable design identity; topology-edge parity; position RMS and maximum error in nm; orientation angular error; dimension/scale error; negative-space checks for intentional gaps.
- Styling fidelity: representation/color parity and, where screenshots are deterministic, perceptual image difference. Lighting may differ stereoscopically but must not obscure topology.
- Interaction: selection hit/miss and false-positive rates; task completion time; accidental activation, re-grab, cancel, and undo counts; menu acquisition time; controller travel/reach.
- Comfort/performance: target the active headset refresh rate (original Vive normally 90 Hz); record application CPU/GPU frame-time p50/p95/p99, missed frames/reprojection, long-frame bursts, and scale/pose stability. The 90 Hz frame interval is 11.11 ms, but application budgets must leave compositor margin.
- Manual comfort: short symptom rating before/after demanding tasks, with explicit stop criteria for eyestrain, nausea, disorientation, or loss of balance. Never optimize comfort by merely blocking close inspection.
- Simulation UX: job/state mapping completeness; engine-option parity; frame/time identity; seek latency; playback stalls; overlay correctness; preserved user context when switching results.

## Archived foundations

Detailed Phase 0–4 inventory, acceptance reasoning, and scene-contract lineage moved to `project_native_vr_archive.md`. The active invariants, phase states, manual gates, and unresolved questions remain here.

Radial-tools / Extrude-interface slice (2026-08-21): the right trackpad no longer toggles Expanded Quick View. Historical implementation (superseded by the 2026-10-05 thumb wheel): holding it snapped a world-fixed, depth-extruded four-sector radial menu around the right Selection Volume; its pose includes the same sign of backward X tilt as the tablet, now exactly 45°. Controller motion produces hover/haptics and release activates Extrude, Twist, Bend, or Move/Rotate, while release in the dead zone cancels. Extrude opens an already-docked settings tablet and a separate docked lattice tablet; both reuse the established one-border-grip move and two-border-grip uniform resize contract. Private End feedback v4 carries the validated desktop lattice type and exact footprint cell, so the picker centers on the real cell without native geometry inference; v1–v3 remain parseable. VR now duplicates the measured desktop/caDNAno formulas exactly: HC `x=col·1.125√3`, `y=row·3.375 + (odd(row+col)?1.125:0)` nm, Square pitch `2.25 nm`; a direct test measures the representative HC neighbour at exactly `2.25 nm`. Panel-local pitch and circle radius are recalculated from immutable nm→view normalization, live scene scale, and panel scale, making every circle's world radius equal the displayed DNA radius of `1 nm`. Rendering and picking share exact circle/viewport intersection enumeration across the full grid; clipped edge arcs remain selectable only through their visible viewport portion. A held right trigger paints multiple cells, with the first cell choosing add/erase and a visited set preventing repeat toggles during one stroke. Free-cell parity and colors match desktop/cadnano (even row+column Forward blue `#29b6f6`, odd Reverse red `#ef5350`); selected cells are amber and visibly labeled `VR DRAFT`. Each selected cell now draws a live wireframe cylinder normal to the lattice plane with exact `1 nm` radius and `length_bp × 0.334 nm` depth after scene/panel scaling; cyan/amber shows outward/inward direction. The Extrude tablet's depth-bearing thumbwheel uses lattice-repeat clicks—7 bp Honeycomb, 8 bp Square. A deliberate slow release cancels sub-click travel and sticks to the last detent, while a release above the provisional flick threshold preserves signed velocity under exponential damping. Wheel capture has priority over panel buttons, lattice paint, and scene selection. A bounded, ray-highlighted `EXIT` control emits Cancel, clears the draft/configuration and wheel motion, and closes both Extrude windows. All tablet text now uses measured 5×7 glyph width and fits/shrinks within explicit bounds. This checkpoint is deliberately interface-only: lattice picks do not yet cross the authoritative extrusion footprint protocol or enable Confirm/design mutation. Pure tests cover fixed tilted radial pose, sector/depth hit testing, exact HC/Square coordinates, physical preview depth/scale, full/partial circle intersection and clipping, add/erase paint strokes, lattice detents, slow-release settling, thumbwheel direction/inertia, bounded text width, parity, reversible cell toggles, and v4 lattice metadata. Physical headset legibility, preview depth perception, acquisition, thumbwheel damping/flick threshold, panel overlap/reach, and grip-priority checks remain required.

Phase 5 transactional-shell slice: the in-headset options panel now opens a separate, explicitly **READ ONLY** Tools page with Inspect, Move/Rotate, Extrude, Twist, and Bend modes plus Preview, Confirm, Cancel, Undo, and Back. Tool actions travel in the existing bounded/sequenced private event record; the browser owns one pure reducer that requires a canonical selection and preview-before-confirm, returns typed effects, and performs no API/store mutation. Native status text says `SELECT TARGET`, `PREVIEW ONLY`, `CONFIRM STAGED`, or `NO VR COMMIT` rather than claiming an edit occurred. Confirm emits an unexecuted `commit_requested` effect until a desktop-authoritative adapter is attached; Undo is deliberately inert before the first real VR commit. Focused evidence: 30 frontend tests, 22 route tests, 4 native tests, and a production Vite build pass.

Phase 5 selection-seed slice: a pre-existing desktop primary selection now crosses launch only as its URL-safe canonical `selectionRefKey` owner token. The local route bounds the token list and passes each token as a distinct process argument; no renderer ID or shell string is accepted. The native viewer resolves the token against the immutable v8 owner-alias table for the launch representation, then preserves the alias fallback across representation changes. An absent/non-rendered owner does not create a false native selection. This removes the reselect-in-VR requirement while keeping the browser selection controller authoritative.

Phase 5 desktop executor inventory:

| Tool | Desktop target/input | Preview ownership | Commit/undo boundary | Safe first VR adapter |
|---|---|---|---|---|
| Move/Rotate | One or many canonical movable Clusters; Assembly Instance is a separate mode | `clusterGizmo` applies local renderer/pending transforms; cancel restores committed geometry | `commitPendingTransforms({log:true})`, feature edit path, or Assembly commit; several overlay/axis reconciliation steps | Cluster only; reuse pending gizmo transform and cancel path, never generalize Base/Atom to Cluster silently |
| Bend/Twist | Two global-bp planes plus optional Cluster scope; current selection is only an entry hint | `deformation_editor` creates/patches a backend preview op and ghost rendering | Delete preview before non-preview `addDeformation`; feature-edit cancel restores original params | Read-only plane/axis preview first; Cluster scopes directly, Base/End may suggest a plane only after explicit confirmation |
| Extrude | Lattice cells/plane/length or explicit continuation/blunt-end/overhang context; empty-design new bundle needs no target | Slice-plane and overhang ghost geometry are local | Four different API routes plus topology/ligate options; normal feature history/undo is backend-owned | End/continuation affordance only after target-owner and parameter UI exist; do not treat arbitrary selected elements as extrudable |

The requested “all levels from cluster to atom” is therefore a UI selection ladder, not a promise that every tool accepts every level. Cluster is the only current direct Move/Rotate edit owner; atom remains a transient visualization pick because canonical design selection stops at Base. Domain/Strand/Base/End/Bond inputs need visible promotion or tool-specific handles rather than implicit widening.

Phase 5 first visual-preview slice: canonical selection acknowledgements now include a bounded kind discriminator in feedback v3, while retaining v1/v2 parsing. Kind cannot identify a target by itself; native readiness still requires its opaque owner alias to resolve in the immutable scene. Both browser and native shells enforce Cluster-only Move/Rotate, reporting `UNSUPPORTED TARGET` for finer refs rather than widening them. Preview draws a model-following RGB translation triad around the acknowledged cluster representative; Cancel removes the triad by clearing pure preview state, including when selection changes mid-preview. No design/store/API/history mutation or transform executor exists yet, and Confirm remains staged only. The representative marker is not yet a centroid/pivot oracle, so actual dragging remains disabled until owner-wide bounds and desktop pivot rules are shared. Evidence: 26 focused frontend tests, 23 route tests/Ruff, four native tests, production Vite build, and the 7,073-test fast suite pass; 114 tests are skipped and the guarded slow suite remains deferred.

Phase 5 owner-bounds slice: the Move/Rotate locator now resolves the most-specific canonical owner token, accumulates every matching sphere, cylinder/half-cylinder, and oriented box in the active natural/Expanded representation, and positions the triad at that owner-wide bounds center. A pure bounds accumulator supplies a numeric center/radius oracle and follows the single model transform, while the displayed handle radius is reach-capped. This removes the arbitrary first-primitive locator and keeps representation fallback deterministic. Bounds center is still not the desktop cluster transform pivot; controller-driven rotation remains disabled until pivot metadata is projected explicitly rather than inferred from display geometry. Native build and all four native tests pass.

Phase 5 authoritative-handle slice: scene v9 adds bounded `K` records keyed by opaque canonical Cluster owner token in every natural/Expanded representation. Each record is the mean live backbone position of exactly the member set used by desktop `clusterMemberFilter`, which is the current visual point at which desktop pivot rebasing leaves its TransformControls dummy; it never trusts or mutates stale persisted `cluster.pivot`. The native reader normalizes handles in the same coordinate frame as geometry, requires natural/Expanded token parity, retains v4-v8 compatibility, and uses v9's handle center with owner-wide bounds only for reach-scaled triad size. The numeric contract parser compares handle position at the same `1e-6 nm` geometry tolerance. Primitives now retain the smallest containing Cluster as the direct-click default while advertising up to the bounded alias budget for larger overlapping containing Clusters, so a sidebar-selected parent Cluster can resolve without changing VR click semantics. Evidence: 33 focused Python tests/Ruff and six native validator/interaction tests pass.

Phase 5 controller-pending foundation: Move/Rotate Preview now owns a pure, reversible model-local rigid transform with an identity activation snapshot. Right-trigger-only motion accumulates controller translation/rotation across re-grabs; left trigger remains model grab and both triggers retain uniform model resize. Model scale is removed from controller displacement before accumulation, so tool motion stays in selected-model space. Changing/clearing the canonical target, changing tools, re-entering Preview, or Cancel restores the pending value exactly to identity. For honesty, only the v9 RGB handle moves in this foundation slice: design geometry, backend state, undo history, and the native scene remain unchanged until endpoint-aware transform ownership is versioned. Native tests lock scaled-model conversion, multi-grab accumulation, rigid rotation, and exact Cancel; all six native test targets pass.

Phase 5 endpoint-ownership contract: scene v10 adds bounded `T` records that bind a primitive to opaque Cluster owner tokens with independent start/end weights. Whole beads, slabs, atoms, domain cylinders, and same-owner connectors receive `(1,1)`; ordinary backbone bonds, direct crossovers/forced ligations, and atomistic bonds derive each endpoint from its actual nucleotide owner, yielding `(1,0)` or `(0,1)` at Cluster boundaries. Natural and Expanded poses must have byte-identical transform ownership, tokens must name a v9 handle in the same representation, and both Python/native readers reject unknown owners, duplicates, out-of-range weights, and pose mismatches while retaining v4-v9 compatibility. The numeric comparator reports ownership regressions independently of geometry. Crossover inserts, flexible/linker interpolation, and warning-marker motion remain explicit debt rather than receiving guessed endpoint semantics. Evidence: 35 focused Python tests/Ruff and all eight native validators pass.

Phase 5 native endpoint-preview slice: the reversible controller delta now projects through scene-v10 weights when CPU instance buffers are refreshed. Points, boxes, and atoms use their whole-owner weight; cylinders/half-cylinders transform start and end independently, so internal connections stay rigid and Cluster-boundary connections stretch only at the selected endpoint. Box axes rotate without inheriting translation. The transformed instance buffers feed both-eye color and the shared shadow pass, while ray picking and exact selected-primitive anchors apply the identical weighted pose instead of targeting stale source geometry. The v9 handle remains the rigid transform center/locator and Cancel reuploads the immutable source pose. Pure tests lock endpoint isolation and axis-vector rotation; all eight native targets pass. Performance of per-frame CPU/VBO refresh for large atomistic scenes is now an explicit headset/frame-time gate before this implementation is considered final.

Phase 5 desktop-mirror preview slice: native now converts its normalized model-local pending matrix back into the immutable snapshot's view-coordinate nanometres before publishing a separately sequenced 4×4 affine record. The localhost backend validates finiteness/affine form/bounds, conjugates it through the launch camera's stored view rotation, and returns a column-major NADOC-space matrix. The browser queues the latest matrix while the existing desktop Move/Rotate tool attaches, snapshots the pivot-rebased Cluster transform exactly once, and derives every absolute target position/quaternion from that baseline rather than integrating 50 ms polling samples. `clusterGizmo.setTransform` remains the sole live-paint/pending-transform authority. A pre-existing desktop tool is never commandeered; VR-origin preview blocks Confirm, and Cancel or native-session exit discards pending transforms and restores store-backed geometry. No backend mutation, feature-log entry, or undo entry exists yet. Evidence: 36 focused Python tests/Ruff, 52 focused frontend tests, production Vite build, and eight native targets pass.

Phase 5 interpolated-detail slice: scene-v10 weights now describe continuously attached small visuals instead of only binary rigid ownership. Each crossover-insert bead/slab/slab connector receives its geometric `(i+1)/(n+1)` parameter between the two canonical crossover endpoints, and every insert-backbone cylinder stores the independent parameters of its two adjacent sites. Flexible ssDNA bases use their ordered interior parameters while all 32 Catmull-Rom edges use exact sample parameters from 0→1. ss-linker bases and 48-segment quadratic paths similarly interpolate between the two canonical overhang anchors, including the FJC path variant that omits explicit anchor sites. Overlapping Clusters saturate at weight 1 instead of double-moving. Native linear skinning applies these weights consistently to render/pick/shadow preview; endpoint translation is exact, while large rotations remain linear-blend skinning and require the headset visual gate. ds-linker bridge/connector ownership remains queued. Focused route/contract tests and Ruff pass.

Phase 5 remaining-attachment slice: each ds-linker boundary connector now moves rigidly with its own overhang-anchor Cluster, while the recovered coarse bridge cylinder assigns its A/B endpoints independently to the two canonical anchors. This keeps both short connector arcs attached while allowing the bridge body to span a moved boundary. The amber unligated-crossover warning is midpoint-skinned at 0.5/0.5 (or weight 1 when both endpoints share a Cluster), so the diagnostic stays with the junction instead of floating at the immutable launch pose. Extension/modification markers and overhang half/full cylinders already inherit whole nucleotide/domain ownership through v10; no extra rule was needed. Focused route/contract tests and Ruff pass.

Phase 5 preview-timing slice: a bounded nearest-rank timing window now reports p50/p95/p99/max every 240 active-preview samples. One window measures the CPU transform projection plus dynamic instance-buffer uploads; a second measures the complete post-`xrWaitFrame` CPU submit interval through `xrEndFrame` and prints the runtime-provided predicted display period beside it. Output is flushed to the private VR log so it can be tailed during the headset gate. This deliberately does not claim GPU time: SteamVR's official performance overlay remains the authority for GPU/reprojection and rolling target/headroom behavior. Pure tests lock percentile calculation, invalid-sample rejection, and reset behavior; all eight native targets pass.

Phase 5 action-target snapshot slice: every native tool intent now captures the exact browser-acknowledged primitive identity, canonical selection kind, and bounded opaque owner aliases at controller-click time. The localhost reader validates target presence/kind/token consistency, and the browser resolves the snapshot against live topology plus the current canonical ref before the reducer can emit any preview/commit effect. Preview state stores a collision-safe target key; Confirm naming a different primitive/owner is rejected with `target_changed_preview_required` even when both selections share the same kind. This closes the asynchronous polling race that could otherwise apply Cluster A's preview state to Cluster B. Exact atom/bond identity remains transient session metadata beneath the stable canonical Base/Bond selection, creating an atom-level tool seam without inventing renderer-index-backed design identity. A canonical selection change during a VR-origin desktop preview cancels/restores the gizmo rather than retargeting it; the native shell also disarms Preview when feedback changes identity/aliases, and transform samples outside the narrow async-attach window are discarded so stale motion cannot seed the next session. Confirm and design/history mutation remain disabled pending the physical gate. Evidence: 26 route tests/Ruff, 69 focused frontend tests, production Vite build, native build, and all eight native targets pass before the full fast gate.

Phase 5 semantic-atom identity slice: scene v11 replaces atomistic draw indices with collision-checked `(base key, chemical atom name)` identities and names each atomistic bond by a canonicalized pair of those semantic atom references. Bond endpoint order, emitted positions, and transform-owner weights are canonicalized together, so reversing an undirected topology edge produces a numerically identical scene contract. Snapshot generation fails on a missing or duplicate chemical atom name instead of inventing an order suffix. The browser decodes the opaque URL-safe identity into transient `atomRef`/`atomRefs` metadata under the existing canonical Base/Bond owner, while the native reader remains compatible with v4-v10. This establishes rebuild-stable exact atom targeting for later tools and simulation results without yet expanding NADOC's persistent selection model. Evidence: 38 focused Python route/contract tests and Ruff, 70 focused frontend tests, native build, and all nine native validators pass; the checkpoint gates pass 7,080 fast backend tests (114 skipped), all 5,676 frontend tests, and the production Vite build. Slow simulation debt remains guarded pending a user-opened test session.

Phase 5 generalized-scope preview slice: scene v12 adds representation-independent Base, End, Domain, and Strand pivots plus Ball-and-Stick semantic Atom pivots. Every primitive can carry endpoint-specific weights for those exact scopes; canonical owner aliases imply rigid 1/1 ownership, while explicit weights preserve boundary bonds and interpolated detail. A collision-checked compact owner dictionary prevents repeating long selection tokens in `A`/`T`/`W` records; v4–v11 remain readable. Native Move/Rotate and the desktop nucleotide adapter now preview Base/End/Domain/Strand without widening to a Cluster, use an action-time exact ref even under co-selection, and restore on Cancel, selection change, or session exit. Bond/Crossover and persistent Atom editing remain refused; Confirm still has no mutation executor. Real-design size gate: the first uncompressed encoding inflated `6hb_validated.nadoc` 683.5 MB→1.148 GB and was rejected; the compact final natural pose is 666.5 MB (295,388 atoms/331,178 bonds, 51.3 s serialization), while `2hb_control.nadoc` is 3.884 MB versus the observed v11 3.805 MB (+2.1%). The large-design launch size/time is pre-existing architectural debt and a future streaming/binary-contract gate, not evidence that a 1.3 GB paired snapshot is acceptable. Evidence: 40 focused Python tests/Ruff, 23 focused frontend tests, 10 native validators, 7,082 fast backend tests (114 skipped), all 5,679 frontend tests, and the production Vite build pass; slow simulation debt remains guarded behind the user-opened test session.

Phase 5 streamed-transport slice: launch serializes natural and Expanded v12 records directly into a private mode-0600 gzip file; constant-size category/count digests preserve backend parity checks without retaining either pose or a bundled copy. The native zlib stream reader transparently accepts both gzip production snapshots and plain v4–v12 fixtures, and rejects truncated/checksum-invalid gzip. No new system package or sudo is required (`zlib.h`/`libz` were already installed). On `6hb_validated.nadoc`, gzip level 1 reduces 666.5 MB to 68.0 MB in 1.35 s; direct stream+compression peaks at 744,220 KiB versus 2,925,328 KiB for the text-return path (−74.6%), with 54.8 s versus 53.2 s natural serialization. A real `2hb_control` natural/Expanded stream is semantically identical to the legacy bundle. Evidence: 42 focused Python tests/Ruff, 12 native validators, and all 7,084 fast backend tests pass (114 skipped); the prior v12 checkpoint also covers all 5,679 frontend tests and the production Vite build. Remaining latency is dominated by atom/record construction; later work should measure launch-to-first-frame and consider representation-on-demand or a binary numeric payload rather than weakening geometry fidelity.

Phase 5 first-frame diagnostic slice: each launch records backend snapshot start/finish and viewer-process start, while native publishes the first successfully submitted stereo frame's wall-clock milestone, post-`xrWaitFrame` CPU interval, and runtime-predicted display period through the existing bounded event file. `/vr/status` derives snapshot, process-to-first-frame, and total launch latency on the same workstation; Firefox reports the metrics once per launch. This is diagnostic-only and does not imply that `xrEndFrame` submission equals photon presentation. Native timestamps retain full double precision; old event/state files default safely to “not ready,” and non-finite/inconsistent telemetry fails closed. The system toolchain is required for native linking when Miniforge shadows `/usr/bin/ld`; no sudo/package change is needed. Evidence: 30 focused route tests/Ruff, seven focused session tests, all 12 native validators, all 7,085 fast backend tests (114 skipped), all 5,680 frontend tests, and the production Vite build pass.

Phase 5 capability-matrix slice: the tool shell no longer claims that every canonical target can be previewed. A canonical definition classifies exact v12 Move/Rotate for Cluster/Base/End/Domain/Strand as `direct_preview`; End Extrude and Cluster/End Twist/Bend as `configuration_required`; every unlisted pairing as unsupported without implicit promotion. Native compiles from that definition, and a frontend parity test locks its exported policy to the same rows. Amber menu tools plus `CONFIG REQUIRED` distinguish valid targets still missing length/direction/footprint or plane-pair/amount controls; unsupported rows are dim/red and Firefox explains that no widening occurred. Preview remains unarmed for both categories, so no generic “PREVIEW ONLY” state can masquerade as visual feedback. Confirm and mutation remain disabled. Evidence: 19 focused frontend contract tests, all 12 native validators, all 5,683 frontend tests, and the production Vite build pass.

Phase 5 configuration-draft slice: valid parameterized targets now open a separate in-headset **DRAFT** page. Extrude adjusts length (bp), direction sign, strand filter, and adjacent ligation; Twist adjusts signed amount and total-degrees/degrees-per-nm units; Bend adjusts angle and cross-section direction. A fixed, sequenced localhost record binds every draft to the exact acknowledged target identity/kind/owner aliases; malformed, stale, non-finite, and transport-unbounded values fail closed in backend and browser reducers. Target changes reset settings rather than retargeting an old draft. Geometry inputs are deliberately not guessed: extrusion always says `MISSING FOOTPRINT`, deformation says `MISSING PLANES A/B`, and the panel says `DESIGN UNCHANGED`; Preview/Confirm remain disabled for these tools. Transport caps (1,000,000 bp, signed 32-bit plane indices, 1,000,000 twist magnitude) are defensive IPC limits, not scientific or operation-validation claims. Existing repository/system toolchains suffice; no sudo or package installation is needed. Evidence: 31 route tests/Ruff, 22 focused frontend configuration/session/shell tests, native build and all 12 native validators, all 7,086 fast backend tests (114 skipped), all 5,688 frontend tests, and the production Vite build pass.

Phase 5 exact-End-context slice: every rendered desktop domain-end face now retains all exact `(strand, domain, direction)` owners instead of exposing only the strand that won face deduplication. A pure resolver binds a canonical End ref to one live terminal nucleotide and exactly one such face, then returns helix/bp/disk/continuation bp, open side, plane/offset, end role, overhang identity, deformation/cluster-transform state, and any crossover or forced-ligation occupying that site. Internal same-helix gap faces remain valid; synthetic extension/linker tips, loop-copy beads, stale/nonterminal owners, mismatches, malformed rows, and duplicate faces fail closed without choosing a neighbor. The resolved context is carried only in the browser's target-bound draft state; native still says `MISSING FOOTPRINT` or `MISSING PLANES A/B`, and no visual preview/API/store/history write exists. This is the geometry seam for later read-only footprint/plane adapters, not permission to extrude through a connected or occupied end. Evidence: 30 focused End/config/shell tests, all 5,700 frontend tests, and the production Vite build pass; the preceding checkpoint covers the unchanged backend/native gates.

Phase 5 exact-End-locator slice: the browser now returns the resolved physical face center and outward continuation normal through a separate private mode-0600, atomic, bounded, sequenced feedback file. The backend rotates both into the immutable launch-view frame; native accepts only the current End draft identity/sequence, applies the scene's exact normalization, and draws a model-following ring plus outward normal. Cyan marks an ordinary open face, purple a face affected by deformation/cluster transform, and red an occupied crossover/forced-ligation site; the settings panel says `FACE LOCATED`/`OCCUPIED` while retaining `MISSING FOOTPRINT` or `MISSING PLANES A/B` and `DESIGN UNCHANGED`. The locator follows grab, rotation, and two-hand scale, but creates no footprint/plane inference, Preview, API/store mutation, or history entry. Malformed, non-finite, out-of-bounds, stale, mismatched, synthetic, ambiguous, or nearby-only candidates remain invisible. No sudo or package installation is needed. Evidence: 32 focused route tests/Ruff, 17 focused End/config frontend tests, all 7,087 fast backend tests (114 skipped), all 5,701 frontend tests, production Vite build, native build, and all 12 native validators pass.

Phase 5 single-End-footprint slice: selecting an exact physical End now explicitly supplies that helix's one canonical lattice cell—using validated `grid_pos` or the same legacy ID recovery as desktop—and never invents a cell for ungridded/non-lattice helices. Extrude settings render a wireframe helix-volume from the desktop continuation anchor using exactly `length_bp × 0.334 nm`, outward/inward direction, and the scene normalization; cyan is outward, amber inward, and red occupied. The visible domain-end ring and continuation anchor intentionally remain distinct at near ends: the ring is one disk slot outside the first bead, while desktop continuation starts at the actual axis endpoint. Domain-end endpoint metadata now follows deformation interpolation, unfold/cadnano poses, Cluster transforms, and revert so this distinction remains live rather than launch-stale. The volume follows the single model transform and two-hand scale. It is labelled `READ ONLY`; multi-cell footprint selection, collision validation, Preview, Confirm, API/store/history mutation, and deformation plane pairs remain unresolved. No sudo/package change is needed. Full checkpoint evidence: all 7,087 fast backend tests pass (114 skipped), all 5,702 frontend tests pass, the production Vite build succeeds, and the native build plus all 12 validators pass.

Phase 5 explicit-plane-pick slice: Twist and Bend settings now expose `PICK PLANE A` and `PICK PLANE B`. Choosing one closes the panel for an aim-and-right-trackpad hit without changing the canonical tool target; a separately sequenced, target/config-bound, private atomic feedback channel lets the browser resolve that exact native primitive against current topology. Only one live physical nucleotide cross-section, a semantic atom owned wholly by it, or an intra-base atom bond is accepted. Domain cylinders, ordinary bonds spanning two bps, crossovers, flexible/linker visuals, extensions, crossover-insert copies, stale helices, and out-of-range bps fail closed. On acknowledgement the panel reopens with the exact global bp, retains A/B independently, and reports reversed/equal order instead of silently sorting it. Full and Ball-and-Stick are the supported placement views for this checkpoint; Cylinders is intentionally too coarse, while Stick may only succeed on an unambiguous intra-base bond. Values remain `READ ONLY`: no bundle-wide plane quad/frame, deformation preview, feasibility request, API/store/history mutation, or Confirm exists yet. The dedicated plane channel avoids racing the existing exact-End locator response. No sudo/package change is needed; use the system linker (`PATH=/usr/bin:/bin`) when Miniforge shadows `/usr/bin/ld`. Full checkpoint evidence: all 7,089 fast backend tests pass (114 skipped), all 5,705 frontend tests pass, the production Vite build succeeds, and the native build plus all 12 validators pass.

Phase 5 authoritative-plane-frame slice: one pure numeric helper now supplies both desktop deformation meshes and VR with the same scoped bundle center, averaged contour tangent, fixed 8 nm half-extent, 7-bp curved-axis interpolation (including a short final interval), straight-axis stagger/extrapolation semantics, and fail-closed handling of malformed or cancelling axes. A Cluster target explicitly scopes the frame to that Cluster instead of borrowing incidental desktop UI state. The private plane response v2 carries the bp and complete frame through the launch camera rotation; native rejects missing/non-finite/degenerate/unbounded geometry, normalizes it with the immutable scene, and draws A as yellow and B as orange 16 nm squares with center crosses and normal ticks. Guides follow model grab/rotation/two-hand scale and are deliberately hidden in Expanded Quick View until Q-VR-013 has an authoritative coordinate projection. Repicks replace one slot; rejected repicks retain the prior configured plane. Everything remains read-only, and Preview/Confirm/API/store/history mutation remain disabled. No sudo/package change is needed. Evidence: 34 focused VR route tests and Ruff pass, all 5,708 frontend tests pass, the production Vite build succeeds, and the native build plus all 12 validators pass. The broad backend run reports 7,458 passed, 154 skipped, one expected xfail, and two isolated pre-existing `tests/test_fem_solver.py` failures; neither FEM source nor test is touched by this slice.

Phase 5 Expanded-plane-frame slice: desktop Expanded Quick View and the VR plane resolver now share one pure 2.25→5 nm per-helix lateral-offset calculation with the desktop's deterministic Z/Y/X dominant-axis tie order; the Python immutable-snapshot generator is locked to the same fixture semantics, correcting its former `argmax` X-first tie. Each accepted A/B response v3 carries a complete natural and Expanded frame, both camera-rotated, finite/bounded, normalized independently, and rejected as a unit if either is absent or degenerate. Native selects the matching pose while right grip is held, so yellow A/orange B remain centered across the visibly separated scoped helices without camera/FOV inference; extent and tangent remain fixed because Expanded is translation-only. Older v2 records still parse for diagnostics but cannot arm a new guide without the Expanded frame. The menu says `PLANES A/B EXPANDED READ ONLY`; Preview, Confirm, design/history mutation, and all other parameterized tool geometry remain disabled. The existing `1e-6 nm` projection contract remains the numeric gate—no threshold change is warranted for an exact translation. Evidence: 35 VR route tests and Ruff, all 5,711 frontend tests, the production build, native build, and all 12 validators pass. No sudo/package change is needed.

Phase 5 Expanded-End-tool-geometry slice: the exact End locator and single-cell extrusion footprint now carry an all-or-nothing natural/Expanded pose pair in private feedback v3. The browser validates the physical continuation face first, applies the same shared per-helix translation used by desktop Expanded Quick View, and never infers an offset from camera pose or rendered visibility. The backend independently validates and launch-camera-rotates both poses; native selects the matching ring, normal tick, and wireframe origin while right grip is held, and hides legacy natural-only v2 geometry rather than displaying it at a false location. The settings page reports `1 CELL EXPANDED READ ONLY`; releasing grip restores the natural pose. This is locator/preview geometry only: no extrusion, API/store/history mutation, Preview, or Confirm has been enabled. Evidence: 35 VR route tests and Ruff, all 5,711 frontend tests, the production Vite build, native build, and all 12 validators pass. No sudo/package change is needed.

Phase 5 parameterized-transaction descriptor slice: one pure, non-executing browser module now converts a target-bound VR draft into the exact existing desktop operation contract. A free, flat End maps to `addBundleContinuation` with face-relative signed length and copied one-cell footprint; occupied Ends and deformed Ends lacking an authoritative frame fail closed. Twist/Bend map to the existing `validateDeformation` preflight, transient `addDeformation` preview, mandatory preview deletion before non-preview commit, and desktop feature-log undo. End-targeted deformation now resolves the same most-specific containing Cluster as desktop picking, so its read-only A/B frames no longer silently span every helix in a multi-Cluster design. Invalid/stale targets, missing or reversed planes, and unresolved scopes produce typed refusal reasons. The descriptor has no API calls and is not wired to Preview or Confirm. Evidence: 83 focused tests, all 5,718 frontend tests, and the production Vite build pass. No backend/native/package/sudo change is needed.

Phase 5 continuation-preflight slice: `POST /design/bundle-continuation/validate` now dry-runs the exact pure continuation builder and returns `ok`/`block` plus the new/extended helices and new/affected strands, without replacing the active design or adding history. A shared 0.4-bp-stripped interval guard matches the desktop slice-plane boundary-touch rule and is also enforced by the real continuation route, so reversing an exact End extrusion through existing DNA is blocked even when a caller bypasses the UI. Duplicate cells, malformed cells, non-finite offsets, zero length, and invalid planes fail closed. The frontend client and non-executing VR descriptor name this preflight explicitly; no runtime call, Preview, Confirm, or mutation was enabled. Evidence: three new endpoint/state-invariance tests, 35 existing VR route tests, 164 CRUD/lattice/feature-log tests (two skipped), 24 focused frontend tests, Ruff, and the production Vite build pass. No package or sudo change is needed.

Phase 5 sequenced-preflight-feedback slice: every complete exact End Extrude or Cluster/End Twist/Bend draft now invokes only its existing read-only desktop validator and reports `OK`, `WARN`, `BLOCK`, or `ERROR` in the native settings page. A private mode-0600 atomic v1 record binds the verdict to the configuration sequence, mode, canonical target kind, and exact target identity; native rejects late, malformed, mismatched, oversized, or superseded responses. Any draft or target change immediately returns the display to `PREFLIGHT WAITING`, so a slow older request cannot authorize a newer configuration. Local descriptor failures are reported without making an API request. This remains status-only: parameterized Preview and Confirm are disabled, and no design, store, history, or preview mutation is reachable. Evidence: 39 focused backend route/continuation tests and Ruff, all 5,720 frontend tests, the production Vite build, the native build, and all 12 native validators pass. Native linking required clearing the inherited Miniforge `LD`/`PATH` shadow so the system linker could resolve the installed OpenXR/X11 libraries; no source, package, or sudo change was needed.

Phase 5 design-state-aware preflight-delivery slice: an active parameterized draft now revalidates whenever the desktop design or geometry object is replaced, publishing a neutral `PREFLIGHT WAITING - DESIGN CHANGED` or `GEOMETRY CHANGED` before the new verdict. A superseding browser coordinator suppresses completed work from older requests. Feedback protocol v2 adds a second monotonic sequence within each tool-configuration sequence, so backend atomic publication and native parsing both refuse out-of-order messages even when network completion order differs from logical order. The backend reports its current sequence when a reconnected Firefox page starts below an already-running native session; only the current final verdict may rebase and retry, never an older WAITING message. Six exhaustive arrival permutations converge on the newest record, and synchronous delivery failures remain contained. Parameterized Preview/Confirm remain disabled and all validators remain read-only. Evidence: 40 focused backend route/continuation tests and Ruff, all 5,725 frontend tests, the production Vite build, the native build, and all 12 native validators pass. No package or sudo change is needed; the established `.venv` is required for backend checks and the clean system-linker environment remains required for native linking.

Cross-phase periodic-seam/owner-parity slice: native launch now snapshots the desktop `End-to-End Crossovers` visibility state. Periodic-seam forced ligations remain absent by default, but when the desktop toggle is on their exact authored endpoint chord, forced-ligation owner, natural pose, and Expanded pose enter the same immutable scene contract as ordinary cross-helix ligations. Extension beads/markers/atoms and Overhang beads/domain-axis half-cylinders now also advertise their exact canonical Extension or Overhang owner token in addition to Base/Domain/Strand ownership, so a pre-existing desktop selection can seed native VR and survive representation fallback without being silently demoted. Default click promotion and all tool-capability rules are unchanged. Evidence: 50 focused route/scene-contract tests and Ruff, all 5,725 frontend tests, the production Vite build, and the previously unchanged native 12-validator gate pass. No package or sudo change is needed.

Cross-phase loop-insertion parity slice: one pure projection rule now derives missing `copy_k` identities from canonical geometry emission order independently per strand/site, matching desktop without mutating the shared payload; sequence coloring and backbone emission consume that same rule. Reverse strands thread copies from highest to lowest copy index, so their 5′→3′ backbone and sequence colors remain monotone instead of zig-zagging or collapsing every inserted nucleotide onto duplicate copy-0 identities. Natural and Expanded poses retain the same stable identities and connector order. Evidence: 58 focused route/scene-contract/projection tests and Ruff pass; the real `exp18` loop/skip fixture projects all 672 nucleotides, gives unique identities to all ten repeated sites, and preserves identical order across 3,464 natural/Expanded Full primitives. No frontend/native/package/sudo change is needed; the physical appearance remains part of the Phase 1 gate.

Cross-phase semantic base-color slice: extension geometry now carries the exact residue letter already used by atomistic generation: `ext_k` grows root→tip, so a 5′ tail reverses its stored 5′→3′ sequence while a 3′ tail does not. Desktop bead colors and letter sprites now share one semantic sequence map, while VR applies the equivalent authoritative assembly; all paths prefer explicit residue identity and exclude extensions from the independent core `Strand.sequence` walk, preventing a 5′ tail from shifting every core base color or a 3′ tail from becoming uncolored. Reverse-loop traversal agrees across paths, and the OverhangSpec fallback honors assembled sub-domain sequence overrides when a strand sequence is absent. Natural/Expanded colors and identities are locked together. Evidence: 75 focused geometry/VR tests and Ruff, all 5,727 frontend tests, and the production build pass; the real `NS_trans_fix` fixture maps and compactly transports all 334 extension sequence bases exactly. No native/package/sudo change is needed.

Phase 6 unified-job snapshot foundation: native launch now reads the active design's existing `GET /simulate/jobs` unified nodes and projects at most 64 rows into a private immutable launch file; it does not scan job directories or create a second job store. Engine-qualified job identity, parent hierarchy, canonical status, bounded progress, stale/viewable/archive flags, and a display label cross a strict URL-escaped v1 contract; duplicate identities, malformed counts/booleans/escapes, controls, and oversized fields fail closed. An unavailable fetch is distinguished from a genuinely empty design and says `JOB LIST UNAVAILABLE AT LAUNCH` instead of falsely claiming no runs; a list over the transport cap explicitly says `SHOWING 64 OF N` instead of silently omitting older rows. The options page opens a paginated five-row **SIMULATION JOBS SNAPSHOT** and a progressive-disclosure detail page with an engine-qualified canonical ID and an explicit statement that actions remain on desktop. Running status is intentionally a launch snapshot, not falsely live; Run/Stop/Delete/result-loading intents do not exist yet. The first-frame timing record now includes the job-list fetch and browser-click-to-first-frame interval, closing the earlier blind spot before the backend request. Evidence: 17 focused frontend projection/client/session tests, all 5,731 frontend tests, the production build, 40 VR route tests plus Ruff, native build, and all 12 validators pass. No package or sudo change is needed; the clean system linker path remains required when Miniforge shadows `ld`.

Phase 6 live-status checkpoint: while native VR is active, Firefox now refreshes the same document-scoped unified list every 1.5 s and publishes only successful reads; it never replaces a known list with false emptiness after a transport failure. The localhost backend owns a monotonic sequence across browser reloads and atomically replaces the private mode-0600 v2 feed, while the native reader accepts only newer complete records and retains legacy v1 launch parsing for diagnostics. An open detail page follows the same engine-qualified job identity across reorder/status updates and returns safely to the list if that job disappears. The panel says `LIVE READ ONLY` for a feed no more than five seconds old and `LINK STALE READ ONLY` thereafter, including capped lists; action controls and result loading still do not exist. Evidence: 44 VR route tests plus Ruff, 19 focused frontend projection/client/session tests, all 5,772 frontend tests, the production build, native build, and the interaction validator pass. The physical mixed-engine/status/staleness gate remains required before widening Phase 6. No package or sudo change is needed.

Tailscale-origin bridge checkpoint: native VR endpoints retain their host-local boundary but now accept both the exact HTTPS `*.ts.net` origin exported as `NADOC_PUBLIC_URL` and the exact Tailscale self-address exported as `NADOC_TAILSCALE_IP` by `start.sh --tailscale`. The self-address is required because Tailscale Serve/Vite may preserve it as the FastAPI client instead of presenting loopback; origin-less same-origin GET polling is therefore also admitted only from that declared self-address. A different tailnet client, hostname, port, scheme, URL path, non-tailnet setting, or ordinary network peer still fails closed. Paired workspace discovery does not redirect VR: the viewer always starts on the active URL's host. Evidence: focused VR route/network-boundary tests and Ruff pass, and source-level checks cover the running Compy5000 launcher's exact public URL plus `100.89.83.24` self-address. The non-reload backend must be restarted after this checkpoint before it serves the change; no live VR session was launched during automated verification.

2026-08-20 goal redirect and transaction audit: stop broadening the VR surface until Move/Rotate and exact-End Extrude are complete workflows. Existing Move/Rotate preview is exact and reversible for Cluster/Base/End/Domain/Strand, but Cluster commit currently refuses VR ownership, residue-scope persistence can create multiple undo entries, and native has no authoritative committing/succeeded/failed acknowledgement. Existing Extrude has exact End context, one-cell footprint, natural/Expanded preview geometry, configuration, and sequenced preflight, but Preview/Confirm remain disabled. Both tools therefore need one shared browser-authoritative transaction state machine with action/target identity, final-state revalidation, duplicate-confirm suppression, exact Cancel, completion feedback, and an Undo token that refuses to consume an unrelated desktop edit. Phase 5A will first add atomic residue-scope persistence and Move/Rotate commit/undo; Phase 5B will reuse the lifecycle for `addBundleContinuation`. Atom editing, multi-cell extrusion, deformed-End extrusion, Twist/Bend execution, job actions, and simulation results are explicitly out of the critical path.

Phase 5A atomic-transaction foundation: `PUT /design/nucleotide-transforms` now validates a bounded, duplicate-free exact residue set before mutation, composes every pose in one state mutation, emits one `nucleotide-transform-batch` snapshot/feature-log entry, refreshes all affected helices once, and returns an explicit VR transaction identity. This removes the former one-request/one-undo-entry-per-residue failure mode for Domain/Strand moves. The nucleotide VR mirror now keeps its hidden persistence pose aligned with the native matrix—previously it moved only renderer matrices, so a future Confirm would have saved an identity transform—and exposes an atomic commit adapter; the Cluster adapter can likewise commit its existing pending transform and capture the resulting log identity. A pure coordinator serializes duplicate Confirm attempts and permits Undo only while that exact feature entry remains the current desktop log tail. These adapters are intentionally **not yet connected to the native Confirm button**: the launch scene needs an acknowledgement-driven committed-transform layer before clearing Preview, otherwise a successful desktop commit would visually snap back in the headset. Focused evidence currently covers atomic backend undo/refusal, Base/Domain persistence, Cluster commit identity, duplicate execution, and stale-desktop Undo refusal. Next checkpoint is the native pending/succeeded/failed protocol plus retained committed transform and exact Undo rendering; only then may Move/Rotate Confirm become reachable.

Phase 5A acknowledged Move/Rotate checkpoint: Confirm is now reachable for exact Cluster/Base/End/Domain/Strand previews. Native locks tool/menu actions at `COMMITTING`; Firefox executes the corresponding Cluster or atomic residue adapter; and a new private mode-0600 monotonic feedback record returns pending/succeeded/failed/refused plus the exact feature-log entry. Out-of-order pending writes cannot replace a terminal result, terminal feedback can safely rebase after Firefox reconnect, duplicate controller Confirm is suppressed, and failed Confirm remains retryable. Native promotes a preview only after success, retains it through representation and Expanded changes, bakes an older accepted layer when a newer commit succeeds, and removes only the newest layer after an exact feature-bound Undo. Picking, anchors, owner bounds, handles, shadows, and every representation use the same committed-plus-pending geometry. If any unrelated desktop mutation changes the feature-log tail, VR refuses Undo and invalidates its token rather than consuming that desktop edit. Automated evidence: 59 focused backend tests, 71 focused frontend tool tests, all 5,782 frontend tests, production build, clean-system-linker native build, and all 12 native validators pass. No package or sudo change is needed. Physical Full/Ball-and-Stick and recovery checks remain the Phase 5A go/no-go gate before exact-End Extrude is enabled.

## Workstation VR runtime gotcha (system-local, not a NADOC feature)

**2026-09-08 saved-session regression:** the workstation was logged into GNOME Shell 46
Wayland. `wayland-info` exposed no `wp_drm_lease_device_v1`; SteamVR 2.16.7 failed
with `VRInitError_Compositor_GnomeNoDRMLeasing`. Forcing SDL/Xwayland found the
Vive's 2160×1200 Vulkan display and selected 90 Hz, but Xwayland could not acquire
it and failed with `VRInitError_Compositor_CannotDRMLeaseDisplay`. This is distinct
from the Xorg connector-ownership case below. `_assert_vr_display_lease_available()`
now fails before launching SteamVR when a Wayland session does not advertise the
lease protocol. Boot journals show the successful 2026-08-17 and 2026-08-28 runs
were automatically selected GDM X11 sessions. The 2026-08-30 reboot instead used
Wayland after the account's saved session reverted to generic `ubuntu`. Persist
`Session=ubuntu-xorg` and `SessionType=x11` through AccountsService, then sign out
and back in; no per-login gear-menu choice is required. A process-local X11
override cannot transfer DRM master ownership away from a running Mutter session.

The 2026-08-17 Codex transcript and preserved 2026-08-28 SteamVR logs settle the
architecture: the custom component was NADOC's native OpenXR companion, including
the real submitted-eye mirror, while SteamVR remained the runtime/compositor. The
physical success path recorded `CHmdWindowSDL: Using X11`, `Direct mode: enabled`,
`Headset is using direct mode`, and `Startup Complete`; no alternate runtime or
bespoke headset driver participated.

SteamVR's compositor fails `xrCreateSession` with `CannotDRMLeaseDisplay` ("Failed to acquire xlib
display" / "VR requires direct mode") whenever the Vive's `HDMI-0` connector is a live ordinary
GNOME/X desktop monitor: the Vive's own EDID does not self-report as non-desktop, so X does not
release the connector for SteamVR's DRM lease. Fix is `xrandr --output HDMI-0 --set non-desktop 1
--off`; this is **session-local** and resets on every connector re-link (headset standby/wake,
replug, logout) — a one-off manual run does not stick. `_detach_hmd_from_desktop()` in
`backend/api/routes_vr.py` now runs unconditionally at the top of `_start_steamvr()`, before the
already-running early-return — deliberately unconditional, because `_runtime_payload()`'s
"steamvr_running" only checks process names (`vrserver`/`vrcompositor` present), which says nothing
about whether direct mode actually succeeded. Gating the detach behind "not already running" (the
first version of this fix) meant it silently never ran whenever SteamVR was already up from an
earlier, possibly-failed attempt — exactly the case that matters most. Regression-tested by
`test_start_steamvr_detaches_hmd_even_when_already_ready` in `tests/test_vr_routes.py`.
`--reload-dir backend` means editing this file should hot-reload `just dev`; verify the running
uvicorn worker PID actually changed (`ps -o pid,lstart -p <pid>`) before assuming a code edit here is
live — reload has been observed to silently not fire. If `CannotDRMLeaseDisplay` recurs, check
whether the backend serving the request is actually running the current file before assuming the fix
regressed.

This is orthogonal to a **genuinely disconnected** `HDMI-0` (`xrandr --query` shows no mode line, or
the headset is idle/asleep) — no xrandr property can lease a connector with no live signal. That's a
physical link-state check, not a desktop-ownership one; don't conflate the two when triaging.

**The launch environment is a two-sided constraint.** `_build_environment()` must satisfy *both*:

1. Drop conda/Miniforge `LD_LIBRARY_PATH` — it shadows SteamVR's own bundled Qt5 and kills
   `vrmonitor` (`libQt5OpenGL.so.5: cannot open shared object file`), after which SteamVR silently
   falls back to SteamVR Home and never hands off to NADOC.
2. Keep `/usr/sbin` on `PATH` — Valve's `vrsetup.sh:40` does `command -v getcap` to verify
   `vrcompositor-launcher`'s `CAP_SYS_NICE`. A PATH of `/usr/local/bin:/usr/bin:/bin` (the first
   version of fix 1) makes that lookup fail, and `vrstartup` then raises a **blocking zenity
   dialog** ("SteamVR setup is incomplete") that stalls the launch until a human clicks it —
   observed stalling ~59 s and causing the whole VR launch to fail. The capability itself is
   already correctly set; the dialog is a false alarm with a real blocking cost.

Locked by `test_build_environment_keeps_sbin_on_path_but_drops_conda`.

**Steam must be fully restarted for an env fix to take effect.** `steam steam://rungameid/250820`
against an already-running client just hands the URL to that client, which keeps its original
environment; `vrsetup.sh` then runs under the *old* `steam-runtime-launcher-service`. Verify with
`tr '\0' '\n' < /proc/$(pgrep -f steam-runtime-launcher-service)/environ | grep ^PATH=` before
concluding an environment fix did not work.

**`SYNCHRONIZED` is not a failure.** A healthy viewer sits in `XR_SESSION_STATE_SYNCHRONIZED`
(rendering, submitting frames, holding Scene Focus) while the headset is **not being worn** — the
Vive's proximity sensor gates presentation. It advances `SYNCHRONIZED → VISIBLE → FOCUSED` only when
someone puts the headset on. A 2026-08-18 live run measured a 65 s gap that was purely the human
picking the headset up. Do not read `SYNCHRONIZED` as a hang. The real failure signature is
`STOPPING`/`EXITING` arriving seconds after start (seen when SteamVR was half-started behind the
zenity dialog); a healthy run logs **zero** of those.

Verified end-to-end on 2026-08-18 19:33–19:35 after both env fixes, with Steam fully restarted:
no getcap error, no zenity, `Acquired xlib display` → `Direct mode: enabled` → `Headset is using
direct mode` → `Startup Complete (1.72 s)`; SteamVR Home cleanly disconnected and NADOC captured
Scene Focus 60 ms after connecting, then held `SYNCHRONIZED` with zero `STOPPING`/`EXITING`.

## Metrics research decisions

- Runtime cadence is authoritative: OpenXR `xrWaitFrame` supplies `predictedDisplayTime`, `predictedDisplayPeriod`, and `shouldRender`; advance one frame from that shared predicted time and skip heavy rendering when `shouldRender` is false. Do not hard-code 90 Hz even though the original Vive normally uses it. Source: [OpenXR frame synchronization](https://registry.khronos.org/OpenXR/specs/1.0-khr/html/xrspec.html#frame-synchronization).
- SteamVR's official performance assessment compares rolling average frame time over 32 frames with a runtime-derived target that already includes compositor headroom, and records repeated excursions rather than failing one isolated frame. Phase gates therefore record rolling timing plus burst/p95/p99 evidence and the in-headset assessment; they do not use 11.11 ms as the only pass line. Source: [SteamVR Performance Assessment Overlay](https://partner.steamgames.com/doc/steamhardware/steamframe/compat/perf_criteria).
- First-frame CPU submission and `predictedDisplayPeriod` are app diagnostics, not GPU/compositor proof. The physical gate must also capture SteamVR compositor timing: total render GPU time, dropped/mispresented frames, reused presentations, and CPU/GPU reprojection reasons over a sustained interaction window. Source: [Valve `Compositor_FrameTiming`](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming).
- Comfort regression uses a short pre/post VR-specific symptom measure, with symptom-level stop criteria. The original SSQ remains a historical reference, but later validation found VRSQ/CSQ more psychometrically suitable for consumer HMD environments; scores are compared to this user's own baseline, not treated as a population diagnosis. Sources: [Kennedy et al. SSQ, DOI 10.1207/s15327108ijap0303_3](https://doi.org/10.1207/s15327108ijap0303_3), [Sevinc and Berkman 2020](https://doi.org/10.1016/j.apergo.2019.102958), [Josupeit 2023 environment-specific VRSQ analysis](https://doi.org/10.3389/frvir.2023.1291078).
- Interaction trials collect objective task completion, wrong-control activations, cancel/undo/re-grab counts, then the six NASA-TLX workload dimensions when a workflow is mature enough to compare. Source: [NASA Task Load Index](https://www.nasa.gov/human-systems-integration-division/nasa-task-load-index-tlx/).
- Preflight freshness is a hard safety invariant, not a latency percentile: zero stale verdicts may be accepted. Automated coverage must permute every arrival order in each bounded test set, while the physical gate must force rapid config changes, desktop design/geometry replacement, and Firefox reconnection with native still running. Latency is measured separately from freshness so a fast wrong verdict cannot pass.
- Projection-space geometry copied from the same authoritative numeric records must agree within `1e-6 nm` and `1e-5°` after serialization, unless a primitive explicitly uses a documented approximation. Rendered-image and human comfort checks are separate gates and do not loosen topology parity.
- Scene-contract changes are benchmarked on both a small interactive design and a large atomistic design. Reject avoidable byte amplification; separately track serialization time, natural/paired bytes, atom/bond/record counts, native parse time, and launch-to-first-frame latency. Large paired text snapshots now require a streaming/binary follow-up even when a new version is byte-neutral.
- In-headset job rows are placed on the existing head-relative panel at 1.0 m. Their 46 mm hit height subtends about 2.63°, above Microsoft's 2° minimum comfortable target recommendation; five rows plus a separate details page implements progressive disclosure rather than dense scrolling. The physical gate still checks aim error and fatigue on the original Vive wands because another headset's nominal guidance is not proof. Sources: [Microsoft head-gaze/dwell guidance](https://learn.microsoft.com/en-us/windows/mixed-reality/design/gaze-and-dwell-head), [Microsoft interactable-object sizing](https://learn.microsoft.com/en-us/windows/mixed-reality/design/interactable-object).
- Keep the job panel in the central frame with minimal head/neck movement, avoid rapid near/far focus changes, and do not animate depth to indicate status. Apple recommends keeping spatial controls within the field of view and minimizing repetitive gestures; Microsoft recommends most immersive content at least 1 m away and explicitly testing near content for comfort. Sources: [Apple spatial accessibility](https://developer.apple.com/design/human-interface-guidelines/accessibility), [Microsoft mixed-reality comfort](https://learn.microsoft.com/en-us/windows/mixed-reality/design/comfort).

## Current UX review and manual debt

- Representation switching still preserves one model transform; all new primitives therefore scale through the same two-hand world transform rather than changing apparent size with view/FOV.
- The v5 half-cylinder is closed and shadow-casting. Its axial roll follows the same deterministic but visually arbitrary default as the desktop straight-domain cylinder; no new biological orientation is inferred.
- Loop-insertion checkpoint: open a design containing both +1/+2 loop insertions and a skip on FORWARD and REVERSE strands. In Full, follow each backbone through the repeated site and confirm it stays monotone in 5′→3′ order with no long zig-zag, missing bead/slab, duplicate selection, or wrong sequence color; the skip must remain an actual absence. Hold right grip and repeat in Expanded, then inspect Ball-and-Stick/Stick for the same residue and bond order. **No-go** on duplicate/missing geometry, reverse-copy order inversion, an atom/bond attached to the wrong copy, or any natural/Expanded identity mismatch.
- Base-color checkpoint: choose Base coloring on a design with distinguishable 5′ and 3′ extension sequences plus an OverhangSpec whose parent strand is unassigned and whose sub-domains override its parent sequence. In Full, compare desktop letter sprites/bead colors and VR from root→tip: 5′ extension letters/colors must appear in reverse storage order, 3′ in direct order, the adjacent core strand must retain its own first/last colors, and each overhang sub-domain must use its override. Repeat in Expanded and Ball-and-Stick against atom residue colors. **No-go** on a shifted core sequence, disagreement between desktop labels and bead colors, strand-color fallback for a known extension/overhang base, ignored sub-domain overrides, natural/Expanded disagreement, or CG/atomistic residue mismatch.
- Phase 6 live-status checkpoint: with at least seven mixed-engine runs including a parent/child pair, one running run, one stale result, one archived result, and one viewable result, open Menu → Jobs and compare every identity, hierarchy indent, status/progress, and flag against the desktop unified list. Leave one detail page open while that run advances and while list order changes; it must stay on the same engine/job identity. Pause/close Firefox for over five seconds and require `LINK STALE READ ONLY` without row loss, then reopen/reload Firefox and require `LIVE READ ONLY` plus current values without relaunching VR. Remove the selected fixture job and require a safe return to the list. Page forward/back and verify each 46 mm row is acquired reliably at the panel's 1 m placement. **No-go** on wrong/missing/duplicate identity, sequence rollback after reload, false empty data during an outage, stale status labeled live after five seconds, detail retargeting by array index, page loss, unreadable ambiguous truncation, any job/design/history mutation, or any Run/Stop/Delete/result-load implication. Record click-to-first-frame, initial job-fetch, and observed update latency. Selection mirroring, job actions, and result visualization remain later Phase 6/7 gates.
- Manual checkpoint: relaunch VR to obtain a fresh immutable snapshot, then verify (a) a same-helix empty interval stays empty in Full and Cylinders, (b) an unbound overhang reads as a half-cylinder while a direct-bound overhang reads full, (c) 1xT/2xT crossover inserts show ordered beads/slabs and no direct chord, (d) a Cy3 extension tip is a larger orange marker, (e) an unrelaxed ss linker has the same bowed path/base count in desktop Full and VR Full while Cylinders retains only its thin path, (f) each pre-relax ds linker shows two short boundary arcs that collapse after relaxation, while Cylinders reads as two two-tone bound-overhang shafts joined by one full bridge cylinder, (g) a slack flexible run bows away from the bundle with the same base count in desktop/VR Full, straightens when taut, and disappears—not breaks into rigid remnants—in Cylinders, (h) a known cycle-closing crossover has a readable amber warning centered over it in Full only, and (i) an end-to-end periodic forced ligation is absent with the desktop toggle off and appears at the exact same endpoints after relaunch with the toggle on, in both natural and Expanded views. Record mirrored/headset evidence before calling Phase 1 complete.
- Phase 3 headset checkpoint: launch a two-or-more-helix part, hold the right wand grip, and confirm helices move laterally apart while beads/slabs/atom radii remain constant; crossovers and linkers must stretch continuously rather than detach. Release must restore the exact natural pose. Repeat in all eleven representations, while holding a trigger, and at close-inspection scale. **Go** if grip never latches, model/world scale stays fixed, and there is no disorienting viewpoint jump; **no-go** on missing input, detached junctions, pose drift, or a grip/trigger conflict.
- Phase 4 hover checkpoint: with triggers released, point the right wand at a bead, slab, connector, cylinder, and atom. The cyan ray/marker should land on the visible surface, prefer the nearer primitive through overlaps, clear on empty space, and disappear during grab/resize. **No-go** on sticky markers, hits behind the wand, systematic slab misses, or frequent coarse-cylinder false positives.
- Desktop mirror checkpoint: while native VR is open and the normal desktop is visible in SteamVR Dashboard, VR hover over a nucleotide/domain/crossover should produce the same yellow desktop preview as mouse hover at the active selection level, and clear within one poll after leaving the model or exiting VR. **No-go** if canonical green selection changes, undo/history changes, Assembly selection is touched, or stale yellow preview remains.
- Selection checkpoint: at each cluster/strand/domain/end/xover/base level, aim at a valid target and fully pull the trigger. Desktop and VR should show the same canonical green selection; invalid target/level pairs must be no-ops, repeated pulls must follow desktop toggle/drill semantics, and selecting must not move/scale the model. **No-go** on duplicate selections, missed selections during a steady hover, any trigger/grip conflict, or selection surviving an Assembly boundary incorrectly.
- Selection-menu checkpoint: launch while a non-default desktop level is active and confirm that row starts green in VR. Change through all seven in-headset rows and confirm the matching desktop filter state changes exactly once without selecting or moving geometry; representation/color choices must still work. **No-go** on cramped/overlapping text, ambiguous section labels, wrong desktop level, trigger-driven model motion while using the menu, or a level reverting after the panel closes.
- Selection-feedback checkpoint: click one valid target and confirm a larger green marker replaces ambiguity around the cyan hover cue after the desktop turns green; move/scale and hold Expanded View to confirm the marker follows. Switch through all eleven representations and confirm exact Base/Bond/Crossover ownership falls back deterministically to the matching Domain, Strand, or Cluster when the finer primitive is absent. Click again to deselect, then try an invalid target at End and Crossover levels. **No-go** if green appears before canonical acknowledgement, survives deselection, attaches outside the selected canonical owner, jumps between primitives on repeated representation switches, lags noticeably, or appears for an invalid pair.
- Bond/backbone checkpoint: in Full, select a thin ordinary backbone connector through default drill and confirm the same desktop bond/cone becomes green. In Ball + Stick and Stick, an inter-residue bond should reach that same connector, an intra-residue bond should select its Base only at a compatible level, and flexible/ss-linker curve edges should choose a nearby visible base rather than an arbitrary curve segment. ds-linker connector arcs must remain no-ops. **No-go** on cross-strand jumps, reversed/wrong connector selection, a green acknowledgement for display-only arcs, or materially biased nearest-base ownership along a curve.
- Phase 4 consolidated gate: run the hover, desktop-mirror, selection, selection-menu, selection-feedback, and bond/backbone checkpoints above in one fresh VR launch. Include an unbound overhang half-cylinder: point through its missing curved side and confirm the hit lands on the visible flat face or the next actual primitive, never the absent half. Before two additional launches, select one canonical Overhang and then one Extension on desktop; each must seed the native green selection on its actual primitives and remain exact across Full/Cylinders or Full/Ball-and-Stick fallback without becoming merely Domain/Strand/Base. **Go** only if canonical green state, native green acknowledgement, active selection level, and representation fallback agree throughout without stale or duplicate intents; otherwise stop at this checkpoint and report the failing target/level/representation tuple.
- Phase 5 shell checkpoint: test Cluster, Base, End, Domain, and Strand separately. Each must report `READY`, place the triad at its authoritative v9/v12 pivot, and move only the exact selected scope; a boundary bond's selected endpoint follows while the opposite endpoint remains fixed. Right trigger manipulates the target, left trigger still grabs the model, and both triggers still resize it. Change targets mid-preview: both mirrors must restore the old target, require a fresh Preview, and restart at identity. Cancel/session exit must restore exactly. Bond, Crossover, and transient Atom targets must remain `UNSUPPORTED TARGET`, never widen. Exercise Confirm/Undo and verify staged/inert wording. Record Full and Ball-and-Stick timing plus SteamVR reprojection. **No-go** on coarse/wrong ownership, detached/interpolated detail, target retargeting, stale motion, trigger/menu conflict, pose jump, false Atom persistence, implied edit success, or any design/history mutation.
- Tool-capability menu checkpoint: with Cluster selected, Move/Rotate must be directly ready, Twist/Bend amber `CONFIG REQUIRED`, and Extrude unsupported; with End selected, Move/Rotate must be ready and all three parameterized tools amber; with Base/Domain/Strand, only Move/Rotate may be ready. Press Preview on amber and unsupported rows: neither may arm target manipulation or claim a visual preview, and Firefox must explain configuration versus exact-contract absence. **No-go** on browser/headset disagreement, an implied preview, silent selection promotion, or loss of the current selection.
- Tool-settings checkpoint: with an End target, open Extrude and verify length ±1 bp, direction toggle, Both→Scaffold→Staples cycling, and Ligate Yes/No; `MISSING FOOTPRINT` and `DESIGN UNCHANGED` must remain visible. With Cluster and then End targets, open Twist and Bend, verify 5° total/0.1°·nm⁻¹ twist steps, 1° bend steps, 5° wrapped bend-direction steps, and unit toggling; `MISSING PLANES A/B` must remain visible. Change target after adjusting each tool and confirm defaults reset. Back must preserve the current draft for the same target, while selecting Move/Rotate clears it. **No-go** on a stale-target carryover, Preview becoming armed, any desktop geometry/history change, unreadable overlap, or accidental controller/model manipulation while using settings.
- Extrude lattice/thumbwheel checkpoint: at minimum/default/maximum scene and window scales, verify Honeycomb and Square circles maintain the displayed DNA radius, fill the grid to every edge, and expose selectable clipped arcs without accepting rays in the title/footer. Hold the right trigger across several cells and require one add/erase decision for the whole stroke with no revisit toggle. At 1, 7/8, and a long length, every selected cell must show a 1-nm-radius cylinder growing by exactly `bp × 0.334 nm`, cyan outward and amber inward, including clipped edge cells. Grab the attached wheel and verify Honeycomb clicks land on 7-bp multiples and Square clicks on 8-bp multiples; slow/sub-click releases must settle without coasting, while fast flicks coast smoothly and stop without reversal. Wheel use must never activate the overlapping panel or scene. Exit during/after a stroke or coast must clear all selection, preview, and motion. **No-go** on gaps at the viewport edge, desktop/VR cell-position disagreement, wrong preview radius/depth/direction, duplicate paint toggles, stale momentum after Exit/tool change, text overflow, or wheel/menu input leakage.
- Preflight-delivery checkpoint: first settle an Extrude/Twist/Bend draft at a known verdict. While its settings page remains open, make a harmless desktop design change or Undo and require neutral `PREFLIGHT WAITING - DESIGN CHANGED`, followed by a verdict for the new state only; force a geometry-only refresh and require the analogous geometry transition. Change the same setting twice before either validation settles and verify no older WAITING/final status reappears. Finally reload Firefox while leaving native VR running, reconnect, adjust one setting, and require the current final verdict to recover despite the browser's reset feedback counter. **No-go** on a red WAITING state, retained `OK` across a desktop state replacement, an older status overwrite, a reconnect that never settles, Preview/Confirm becoming active, or any mutation caused by validation.
- Exact-End locator checkpoint: test Extrude, Twist, and Bend settings on an ordinary outer blunt end, each side of an internal same-helix domain gap, an unbound overhang tip, and a crossover/forced-ligated terminal site. A ring must sit on the exact desktop face and its line must point into the open continuation side; connected sites must be red and say `OCCUPIED`. Grab, rotate, and resize the model, then switch representation: the locator must stay attached and scale with the model. Hold right grip and require the ring to translate with the selected separated helix without changing its normal or size; releasing grip must restore the exact natural pose. Extension tips, ss/ds-linker synthetic tips, ambiguous/stale refs, and a nearby-but-different face must show no ring rather than snapping. **Go** only if all natural/Expanded positions, directions, occupancy, and restoration agree and the design/history remain unchanged; **no-go** on a wrong face, inward direction, stale locator, Expanded drift, scale change, hidden mutation, or any inferred footprint/plane.
- Single-End footprint checkpoint: on a gridded outer End, set Extrude length to 1, 7/8 (matching the design lattice period), and a visibly long value. The wireframe must begin at the actual helix endpoint, grow by the expected bp length, remain one helix diameter, and reverse amber when Direction is flipped. The outward direction must settle at `PREFLIGHT OK`; the reversed, into-body direction must settle at `PREFLIGHT BLOCK` and never become committable. Change length/direction quickly and require an immediate `PREFLIGHT WAITING`, followed only by the newest verdict—an older result must never overwrite it. At a near end, verify the start is one rise inward from the locator ring; at a far end they coincide. An occupied face must be red and an ungridded/synthetic target must show no volume. Resize/switch all representations and confirm exact attachment and uniform scale. Hold right grip and require the locator and footprint to translate together with the selected separated helix while dimensions and continuation direction remain unchanged; releasing grip must restore the exact natural pose. **No-go** on ring-origin growth at the near end, wrong length/radius/direction, an inward `OK`, a stale verdict after any setting/target change, camera/FOV-dependent size, Expanded mismatch or drift, or any design/history change.
- Deformation-plane input checkpoint: select a Cluster and then an End, open Twist and Bend, choose `PICK PLANE A`, aim at a known bp bead in Full, and fully pull the trigger; the settings page must reopen with that exact global bp while the original Cluster/End remains selected. Repeat for B in Ball-and-Stick and verify ordered A < B reads cyan. Pick B before/equal to A and require the explicit order warning with no silent swap. Aim at a Cylinders domain shaft, cross-bp backbone/atom bond, crossover insert, extension, or linker and require `NOT SET`; press the Vive System/menu button while aiming and require a clean return to settings without a pick. Repeat while Expanded is held only for semantic bp retention—there is no plane geometry gate until Q-VR-014. **No-go** on target replacement, a rounded/coarse bp, stale response, menu/trigger motion, hidden mutation, or Preview/Confirm becoming active.
- Deformation-plane frame checkpoint: after selecting A/B above, close the settings panel and compare the yellow A/orange B squares with desktop deformation planes at the same global bps. Test one straight staggered bundle and one already curved bundle, first as a Cluster target and then as an End target. Each square must remain centered across the same scoped helices, perpendicular to the local contour, visibly 16 nm wide, and attached through grab, rotation, two-hand scale, and representation changes. Hold right grip: helices must separate while both squares recenter across their separated scope, retain orientation/size, and return exactly on release; the settings page must say `PLANES A/B EXPANDED READ ONLY`. Repick only A and verify B does not move; make a rejected coarse pick and verify the prior guide remains. Complete A/B should settle at the same `PREFLIGHT OK`, `WARN`, or `BLOCK` class as desktop validation. Repick a plane or change amount rapidly and require `PREFLIGHT WAITING` followed only by the newest verdict; an old response must not reappear. **Go** only if desktop/VR natural and Expanded centers, orientation, scope, ordering, color, transform behavior, and preflight status agree with no design/history mutation; **no-go** on an averaged wrong Cluster, camera/FOV-dependent size, stale guide or verdict after target/tool/config change, Expanded jump/drift, or Preview/Confirm becoming active.
- Next slice after the manual gate: run the physical geometry, status-fidelity, stale-response, and timing gates. If they pass, design one parameterized preview/commit/one-step desktop undo transaction at a time, starting with exact End Extrude; if upload/CPU timing or SteamVR reprojection threatens the compositor budget, evaluate a GPU-weighted path first. Keep Preview/Confirm disabled until mirrored fidelity, Cancel/session-exit restoration, preflight status fidelity, and timing all pass. Phase 1, Phase 3, and Phase 4 remain pending their headset gates.

## Open questions log

- **Q-VR-001 — Right-grip semantics (implemented, validate):** hold-for-expanded/release-to-restore. Reopen only if headset testing finds grip fatigue or trigger conflict.
- **Q-VR-002 — Smallest selection identity:** atom spheres and intra-residue bonds currently resolve to canonical Base because the design selection model has no atom ref. Before atom-level editing/simulation inspection, decide whether individual atoms become canonical design selections or transient tool/result picks beneath Base; do not infer atom identity from an atomistic draw index.
- **Q-VR-003 — Edit safety:** what confirmation, preview, cancel, and undo affordances should VR tools share with desktop editing?
- **Q-VR-004 — Handedness/accessibility:** should menus and tools auto-mirror by dominant hand, expose an explicit setting, or both?
- **Q-VR-005 — Lighting:** should photo shadows remain scene-locked, offer a head-light fill, or expose a small lighting menu for inside-model inspection?
- **Q-VR-006 — Simulation defaults:** which job fields, plots, overlays, and playback controls deserve persistent wrist/panel placement versus on-demand menus?
- **Q-VR-007 — FJC transform authority:** desktop visibly stretches relaxed ssDNA representatives along the live chord, while the older Python `transform_to_chord` currently only rotates/translates despite its docstring. VR intentionally matches desktop locally; decide in a separate science-aware change whether the shared Python helper should be corrected and migrated.
- **Q-VR-008 — Warning-marker style:** the current physical triangular sign stays in model space and scales with the design; when billboard support exists, decide whether unligated warnings should instead remain head-facing like desktop sprites or keep the spatial sign for depth stability.
- **Q-VR-009 — Right trackpad:** resolved for this checkpoint as hold-to-open radial Tools with release-to-activate. Selection remains on full trigger; the old Expanded Quick View click binding is removed. Validate sector acquisition, accidental activation, and dominant-hand comfort before freezing the gesture across controller profiles.
- **Q-VR-010 — Tool manipulation binding (provisional, validate):** explicit Preview arms right-trigger-only target manipulation; left trigger remains model grab and both triggers remain model resize. Reopen if headset testing finds mode errors, two-trigger transition jumps, or dominant-hand/accessibility problems.
- **Q-VR-011 — Cross-level tool semantics (design-aware sequenced preflight implemented, validate):** Move/Rotate has exact preview coverage for Cluster/Base/End/Domain/Strand. End Extrude and Cluster/End Twist/Bend now have scalar drafts, exact read-only geometry, non-executing desktop-operation descriptors, read-only preflight APIs, and target/config/design-aware sequenced native status feedback, but remain non-previewable pending physical gates and transaction attachment. Decide whether Base/Domain/Strand should gain explicit plane/footprint handles; Bond/Crossover/Atom remain refused rather than promoted.
- **Q-VR-012 — Atom edit semantics:** v11 now supplies stable transient `(base key, atom name)` and semantic atom-bond refs beneath canonical Base/Bond, but NADOC has no persistent per-atom design selection or transform owner. Decide whether atom editing should persist those semantic refs/overrides, remain a simulation-results-only interaction, or expose residue transforms with an atom-local handle.
- **Q-VR-013 — Expanded tool geometry (read-only exact poses implemented, validate):** A/B planes, the exact End locator, and the single-cell extrusion footprint now carry exact natural/Expanded geometry using the shared 5 nm per-helix translation. Physical gates remain required, and actual deformation/extrusion execution still needs an authoritative transaction contract; do not infer that every future tool handle supports Expanded pose from these read-only projections.
- **Q-VR-014 — Deformation plane geometry (natural/Expanded read-only frames implemented, validate):** validate both poses in the physical frame checkpoint before enabling a deformation preview. Decide whether the final controller gesture should remain point-then-trackpad or become direct plane-handle dragging.
- **Q-VR-015 — Periodic seams (launch parity implemented, validate):** the desktop End-to-End Crossovers toggle is now honored when creating the immutable native snapshot. Decide whether the final VR options page should expose a live seam-arc toggle; until then changing it requires relaunch so natural/Expanded identity sets remain immutable.
- **Q-VR-016 — Job panel persistence and actions (sequenced live status implemented, validate):** decide after the physical live-status gate whether the unified job panel should be a head-recentered modal, wrist/hand-attached view, or user-placeable world panel. Do not enable Run/Stop/Delete or result loading until confirmation, stale-job refusal, focus restoration, and desktop selection mirroring have explicit contracts.
- **Q-VR-017 — Transaction acknowledgement (priority):** Confirm must remain visually pending until the desktop-authoritative mutation response identifies the committed feature-log entry. Native should then expose committed/failed/cancelled status and enable Undo only for that exact transaction; a later desktop edit must make the VR Undo token stale rather than undoing unrelated work.
- **Q-VR-018 — Move/Rotate residue granularity (priority):** Base/End/Domain/Strand previews already resolve to exact residues. Persist the whole target set atomically as one feature-log/undo entry; do not loop single-residue endpoints or silently promote them to Cluster.
- **Q-VR-019 — Extrude scope after exact End (deferred expansion):** finish one-cell continuation first. Multi-cell slice footprints, overhang extrusion, new-bundle extrusion, and deformed-End continuation need separate discoverable target/footprint contracts and must not be hidden behind the current End action.

## Immediate handoff

Implement Phase 5A's shared transaction identity and atomic residue-scope persistence, then attach Move/Rotate Confirm and exact transaction-bound Undo for Cluster/Base/End/Domain/Strand. Native must display pending/succeeded/failed state from browser feedback, suppress duplicate Confirm, keep Cancel exact before commit, and refuse stale Undo after any unrelated desktop edit. Run focused backend/frontend/native tests and then the physical Move/Rotate gate in Full and Ball-and-Stick, including selection change, Firefox reload/session exit, controller transition, large rotation, and SteamVR frame timing. Only after that passes, attach the same lifecycle to exact one-cell End Extrude: final preflight immediately before mutation, explicit footprint/direction summary, duplicate-confirm suppression, committed geometry refresh, and exact one-step Undo. Keep Twist/Bend commits, broader extrusion modes, atom persistence, job actions, and simulation results deferred until 5A/5B are complete or the user redirects again.

## Debug tour entry points (2026-09-27)

Desktop **Debug → VR Tours & Tests…** groups Overview, Left sidebar, Right sidebar,
Controls & layout, Dimensions and Authoring. Catalog lives in
`tools/vr_workflows/tour_catalog.py`; `routes_vr_tours.py` owns allowlisted isolated
subprocess launches/status/cancellation. `menu_tour --tab side:key` scopes page
coverage. Demo uses steady_fast; validation uses all four profiles. The existing
authoring demo remains terminal-only because of its special viewer/review assets.

## Hand-specific quiver tools (2026-09-28)

Scissors/Nick now belongs to the **right hand only**, including the radius-wheel
entry point. Left quiver gestures independently toggle a two-column view tablet.
Its eleven controls use the original desktop SVGs and invoke the shared desktop
view handlers: Length, Sequence, Undefined, Loop/skip, Grid, Overhang names,
Clashes, Expanded, Deform, Unfold and Cadnano 2D. The native stereo renderer reads
validated document-bound binary geometry/texture snapshots, retaining mesh
instancing; world manipulation remains native. Straight and 2D inspection layouts
suppress canonical edit picks whose positions no longer match. Panel feedback
explains desktop layout prerequisites. See `docs/vr_view_tools.md` and the
`view-tools` Debug tour (`tools.vr_workflows.view_tools_tour --validate`).


Validation for the hand-specific view-tablet checkpoint: all four profiles passed
both the complete eleven-toggle menu workflow and scissors/left-menu independence,
left-trigger non-nicking, right nick and Undo/Redo. Evidence and retained failed
attempts: `docs/audits/vr_view_tools_20260928.md`; aggregate
`.development-artifacts/vr-view-tools/view-validation.json`, plus
`scissors-final/result.json`. Through-lens comfort remains a human check.

### Share sidebar (2026-09-28)

Prior VR authoring/view tools pushed as `d9f9f252`. Left menu-button Share tab now
controls existing desktop presentation: pause/resume perspective and End all links.
No creation/start/link management in VR. `vr_share.js` delegates to existing desktop
presentation controls; `backend/api/vr_share.py` publishes doc-bound `.share` status;
native sequenced events are acknowledged, busy-gated and status expires after 3 s.
Camera source remains desktop; headset/model-grab presentation is not broadcast.
Assessment: `docs/vr_sharing.md`. Four-profile isolated mock-hosting controller tour
passed with stereo and delivered-mirror checks (`.development-artifacts/vr-share/final`).
Debug tour: Left sidebar → Share presenter controls. Internet guest transport and
through-lens comfort were not verified by this tour.

### VR presenter avatar (2026-09-28)

Share tab adds native-local default-on `Show VR model`. Head/controller metric poses
plus exact model normalization/manipulation are atomically sampled in `.avatar` at
20 Hz. `/api/vr/presenter-pose` inverts the complete source-nm-to-tracking transform;
local doc binding and 1 s feed freshness apply. Desktop `vr_avatar_publisher.js`
sends bounded latest poses at 10 Hz to existing room's host-only `/avatar` endpoint,
including paused-perspective rooms. `vr-avatar-v1` capability required. Guest SSE
state validates revision and expires after 1.5 s. No model edits or snapshot churn.
`vr_avatar.js` draws primitive headset/controllers, shoulder bar and analytic two-link
estimated arms outside `current.scene`. Reattach after prepared scene replacement;
overlay mode explicitly renders the transient figure too. Inverse scale applies to
all avatar dimensions. Research/algorithm: `docs/vr_presenter_model.md`.
Debug → VR Tours & Tests → Left sidebar → VR presenter model uses real local hosting
and guest SSE with physical profile-driven poses; no public invitation.

## VR menus in guest presentation (2026-09-28)

Show VR model now includes native menu textures and tracking-space controller/tool
lines. Both sidebar tablets, the desktop-icon view tablet, legacy/desktop panels,
selection aids, radius wheel, scissors, nick glow, ligation and resize guides use
actual XR draw data and the avatar's inverse source transform. Guest controls are
read-only. Hidden/closed/stale presence removes them. PNGs cache natively and per
SSE connection; changed images send once, positions/guides continue at pose cadence.
Room SSE now handles backpressure by coalescing the latest pending state instead
of destroying the connection on a menu-sized write. The Debug Left-sidebar
**VR menus and tools in guest view** entry runs the real-host guest pixel checks.
Details: [presenter model](../docs/vr_presenter_model.md#guest-visible-vr-controls).

## QR calibration and cube (2026-09-29)

VR Share has Calibrate QR code / Cancel and status rows. `qr_calibration.hpp`
launches an offline isolated `tools.vr_qr.worker` for the original Vive V4L2 feed,
serial-specific FTHETA calibration, OpenVR camera-to-head and standing poses.
The native OpenXR STAGE-to-LOCAL mapping registers a stable QR anchor. Source
scene origin snaps to it, preserving presentation scale/orientation and geometry.
An RGB axis marker persists; the camera panel is an edge-filtered mono preview.
The helper needs cached openvr 2.12.1401 / opencv-python-headless 4.12.0.88 in uv's
isolated Python 3.12 environment; no research-venv dependency changes. The sanitized
VR PATH omits ~/.local/bin, so the launcher explicitly resolves uv there first.
Physical target accuracy/comfort remain pending. See docs/vr_qr_calibration.md,
manual_validation_debt.md and Debug's qr-calibration tour. `generate-qr-cube.mjs`
produces a 150 mm core and six paint/two-color face plates with stable IDs; these
are separate from expiring meeting invitations. Mobile cube registration is pending.

### 2026-09-29: representation parity and real-browser coverage

- Both API client visualization publishers must use `nativeRepresentation` from
  `scene/vr_representations.js`; the former four-name list silently acknowledged
  Surface/Hull/Beads/VDW/input previews as Full and stranded their VR buttons at 99%.
- Selective native scene installation must check `incoming.available[i]` before
  replacing blocks. `loadScene` injects reference axes into Full after deriving
  availability, so nonempty geometry alone can erase resident Full/Beads.
- Cylinder exports reuse desktop `buildHelixObjects(..., 'cylinders')`, including
  default radius and saved strand/group colors. They are triangle-backed native
  geometry, like Surface/Hull. Transient desktop radius-slider changes after
  export are not synchronized by this static export bridge.
- Sidebar hover rays use the same panel intersection as input and do not require
  the trigger to be held. GL regression checks open/closed panels.
- Browser representation checks now cover every representation and require
  nonzero model IDs in both eyes for every style, in addition to 100% and correct
  acknowledged style. Let delayed display uploads settle outside measured reaches;
  do not run broad parallel suites during timing-sensitive controller playback.
  Details and retained attempts: `docs/audits/vr_representation_parity_20260929.md`.

## 24HB live follow-up (2026-10-01)

See `docs/audits/vr_move_rotate_24hb_live_20261001.md`. Full single-base drags on
24HB (6,720 nt versus generated 6HB 511 nt) complete all four profiles at GPU
p95 3.27–4.26 ms. Fresh 6HB p95 is 1.41–2.26 ms. Rare hitches occur on both
(24HB max 24.50 ms, 6HB max 66.01 ms); do not claim a strict 90 Hz guarantee.
Mixed desktop focus/rendering and additional 24HB presentation zoom are recorded.
24HB stereo/scope/commit/save pass, but Undo after save returns 404 Nothing to
undo; full authoring matrix stays failed. Fresh 6HB complete matrix passes.
Use complete `workspace/24hb_0xT.nadoc` via private `move_tour --design` copies,
not API summaries missing snapshot payloads. `--direct-activation` isolates drag
from known large-response menu replay delays; it does not validate menu acquisition.
Inactive Nick bond arrays are omitted while Move/Rotate or Bend is active in
ScryWrite; `scene_hover` exposes the actual molecular hover separately from menus.

## Feature performance guards (2026-10-01)

View Volumes now skip same-style `setStyle` calls (including restoration), skip
clipping work when no volume is active, and retain unchanged clipping-buffer
contents between eyes/frames. Do not add a general early return inside `setStyle`:
callers also use it to invalidate geometry after selection/configuration changes.
Bend/Twist cache sidebar rows by all displayed inputs/status; opening and panel
replacement invalidate the cache. Pending volume journals are rewritten only when
the immutable sequence range changes, with failed writes remaining retryable.

Evidence and reproducible benchmark script:
`.development-artifacts/vr-feature-guards-20261001/report.json` and `benchmark.py`.
24HB whole-cluster Move/Rotate with one same-style opaque volume, production
shadows and two 1852x2056 draws: worse motion p95 wall time before → after is
Full 296.80 → 7.30 ms, Stick 2261.79 → 29.18 ms, Ball & Stick 3988.16 → 25.50 ms,
VDW 2889.04 → 5.19 ms. Five warmups plus 20 samples per mode; all 16 before/after
images byte-identical. Timings exclude XR/UI/commit work. Old-path GPU query times
include CPU submission gaps and must not be called pure GPU execution time.
Generated-fixture live volume movement/resizing passed all four motion profiles
for square and hexagonal volumes. Native Bend/Twist guide rendering, menu cache
invalidation and volume journal retry/ack tests pass. This is not new live 24HB
Bend/Twist deformation timing. Different-style volume transitions and synchronous
View Tools scene/atlas refreshes can still hitch; large highlighted Stick/Ball &
Stick with a volume remain over 11.1 ms. No geometry or lighting quality reduced.

## Move/Rotate hand-role trial (2026-10-01)

While Move/Rotate is active, only the left trigger/selection sphere acquires
molecular targets. Only the right trigger can grab by pointing at selected geometry;
release still commits. The right selection sphere and radius scrolling are
suppressed, and right clicks away from selected geometry cannot clear selection. Selection
is frozen while the right hand drags. Exiting Move/Rotate restores normal selection
for both hands; scene grips and menu controls retain their existing behavior.
The native viewer binary is rebuilt for trying this mapping. Performance work was
pushed separately as `eb637ca5`; this hand-role trial remains a local change.

Move/Rotate pointing trial: removed selected-element axis/cross overlays. A green
beam connects the right hand to selected geometry when aimed, and follows the
grabbed point during manipulation. Picking uses cached selected packed instances;
owner-token parent aliases must not be mistaken for multiple selections. Pointing
padding is one degree, bounded to 2–12 mm in tracking space. The Move menu has a
Selection options card with three inline icon buttons: Base, Domain, Cluster.
Native panel/hand tests pass, including remote acquisition and pointing away.
Live generated-6HB Base, Domain, and Cluster workflows each passed. Across four
motion profiles, high-jitter acquisition can miss a tiny base. Observer-side beam
captures pass both stereo-eye pixel checks; an earlier behind-model cluster beam
capture was occluded in one eye. One observer-side steady-fast reopen assertion
failed on quaternion roundoff (~1e-16), after manipulation passed. Failed attempts
are retained in `.development-artifacts/vr-move-ray-card-20261001/report.json`.
These are rendered/injected-controller checks, not physical through-lens validation.

## Full slab registration after residue moves (2026-10-01)

VR Full export previously solved paired slab placement after persisted nucleotide
transforms. Moving a domain therefore re-seated its slabs against stationary
mates and also moved those mates' slabs. Desktop live edits keep the native
bead/slab offset. `full_slab_reference_geometry` now undoes saved residue poses
for the contact solver, then the exporter carries each solved slab/connector by
its own pose. Five-prime cube orientation follows the saved residue rotation too.
Simulation slab-frame delivery remains separate. This does not change underlying
saved geometry or the general cluster/deformation placement pipeline.

Read-only reproduction on the current `workspace/24hb_0xT.nadoc` (7 saved residue
poses): old moved primitive error up to 0.62956 nm; stationary partner error up to
1.13316 nm. Fixed: all 20,160 bead/slab/connector primitives agree with rigid
reference within 6.7e-6 nm (text export precision), stationary primitives exact.
77 backend checks and native packed-preview parity pass. Native close-up renders
show the corrected bead contacts. Evidence, failed framing attempt, scripts and
scope: `.development-artifacts/vr-slab-rigid-20261001/report.json`. No new physical
headset/motion-profile validation was run for this snapshot-only correction.

## Part origin and room-centered startup (2026-10-01)

Previous move controls and slab fixes pushed as `a360c112`. The following origin
correction remains local: native axes previously started at hard-coded normalized
(-.28,-.28,-1.3), independent of the part. NADOCVR v16 now carries O metadata
(source X/Y/Z directions after desktop-camera rotation); native axes use source
zero and 4 nm lengths matching desktop AxesHelper(4). Geometry normalization and
coordinate conversions stay fixed. Legacy snapshots assume identity source axes.
Normal startup anchors source zero 1.1 m above the calibrated OpenXR STAGE center,
with horizontal head yaw and existing 2x presentation scale. Stable tracked poses
and completed initial geometry are required. Without STAGE, LOCAL X/Z zero is
used at head Y minus .35 m. Explicit inspector in-view placement and QR anchors
still override this default; manual Fit/Recenter remains head-relative.
76 backend tests and native origin/preview checks pass. Read-only live 24HB launch
placed the origin within .004 mm of the expected stage target. First capture was
out of view with headset set aside; user repositioned it toward center and the
second submitted stereo capture shows the model. Diagnostic viewer was left open
for inspection. Evidence: `.development-artifacts/vr-origin-20261001/report.json`.

## VR routing and sequence tools (2026-10-06)

Right Tools now exposes the nine active desktop routing/sequencing actions plus
Undo/Redo. `vr_routing.js` bridges actual DOM handlers and allowlisted dialogs over
a document-bound versioned `/api/vr/routing` snapshot. `routing_panel.hpp` owns a
separate foreground SidebarRuntime; dialogs preserve the underlying menu and
block click-through. Custom scaffold input uses a DNA keypad. Background autosave
is excluded from operation busy tracking. See `docs/vr_routing_sequence.md` and
`frontend/e2e/vr_routing{,_physical}.spec.js` for validation and retained evidence.

## Five-second stereo recording (2026-10-12)

Right Tools has Record 5 seconds, status, and Open recordings folder. A two-second
countdown allows the user to keep or close menus. `stereo_recording.hpp` captures
full-resolution submitted eye pairs into bounded asynchronous PBO/compression
queues; `tools/vr_recording.py` exports timestamped left/right videos and a review
page after capture. Lossless RGB pairs, eye poses, predicted times, menu state,
readback CPU time and skipped-pair reasons remain in `.development-artifacts/vr-recordings`.
The recorder cannot observe compositor reprojection or physical display persistence.

Three native checks and 52 focused Python checks passed. Real 24HB/P1 Alpine Aug 7
Flex Stick captured distinct 1852×2056 eyes with menus open and closed. Steady-fast
completed both clips; the other three final profiles exceeded the unchanged 150 ms
input timing limit (376/737/480 ms). Do not claim all-profile motion success.
The full-scene recordings have substantial application frame gaps; recording also
adds overhead. Desktop 3D was explicitly disabled through its normal toggle for
the final labeled pass, with stopped render counters verified. A tested RGBA
readback alternative increased CPU cost and was discarded. The final implementation
uses RGB and warms up readback during countdown. Build/test logs, failed attempts,
recordings and review session ownership: `.development-artifacts/vr-stereo-recording-20261012`.
Discoverable regression: Debug → VR Tours & Tests → Controls & layout → Tools ·
five-second stereo recording (`menu_tour --recording-checks --validate --exit`).
Physical double vision remains manual debt MV-44.


2026-10-16: QR shared-position AR tools retired at user request. Earlier QR calibration, cube printing, reference-marker and phone tracking entries are historical, not active validation debt. Guest QR invitations remain. VR Share now starts and ends presentations through the desktop lifecycle; see docs/vr_sharing.md.

2026-10-16: VR Share → Share headset perspective now drives opt-in guest Follow from the native mid-eye camera in source coordinates. Browser-side quaternion/position smoothing: 180 ms damping, 90°/s turn cap, 1 tracking metre/s translation cap. Independent of Show VR model, 10 Hz bounded publication, tracking-loss hold and host-issued expiry. Desktop source preserved. Four-profile real-local-host test covers desktop/mobile guest rendering and lifecycle; evidence `.development-artifacts/headset-follow-20261016/`. See docs/vr_sharing.md for limitations and retained test-harness failures.

## FPS process audit — 2026-10-22

Audit only; no production fixes. Evidence: `.development-artifacts/fps-audit-20261022/report.json` and `ranked-findings.json`. Fresh 12k/24-helix matrix retained 45 idle/grip intervals: Full ~89.52 FPS, Stick/Ballstick ~44.76, Surface ~89.43–89.53. Compositor GPU p95 Stick 11.78–12.10 ms / Ballstick 12.52–12.98 ms, with 2311/2326 repeated frames; Full/Surface sampled intervals had zero repeated/dropped. All-style scope experienced MemoryHigh reclaim, and the initial parser reported dropped records (corrected by the standard-24HB recheck above): these are observations, not clean acceptance proof. Surface variable-fast ownership failed and variable-deliberate was absent.

Current Surface lazy-load attempt stalled 4575.4 ms in driver upload (204800 bytes), adjacent guide scope 3249 ms, while scope hit 6 GiB MemoryHigh and swapped. Do not describe this as ordinary Move computation or proven unbounded normal-use memory. Ballstick browser off/on both reached representation but then failed workflow; ~29–30 FPS, pressure and incomplete traces prevent causal comparison. Isolated mirror control built, but recorder startup failed before measurement. Preserve failed attempts; do not claim successful A/B.

Ranked candidates: (1) Stick/Ballstick rendering, (2) synchronous periodic spectator health readbacks/presentation (recent 49.52ms mirror phase), (3) upload blocking/residency under pressure, (4) duplicate browser drawing, (5) picking/Surface fallback, (6) Desktop-panel XGetImage/upload, (7) simulation visualization refresh, (8) audit capture overhead. Last two interactive workloads are source-review only. Prior explicit per-eye glFlush and synchronous stdout stalls were already fixed. Edit-to-ready serialization remains responsiveness latency, not established FPS cause. Audit artifacts retain logs, reports, PNGs and failure traces; bulk capture arrays/exported snapshots/build outputs pruned with manifest.
