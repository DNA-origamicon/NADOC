# VR frame calculation audit

The later [Ball & Stick 90 Hz campaign](vr_ballstick_90hz_20261002.md) supersedes
Surface optimization priority: the user excluded Surface frame-rate work. It
also records the retained packed Move commit/Undo path, a subsequently reverted
asynchronous mirror-readback experiment, and a desktop-animation dependency that makes browser
minimization unsuitable for complete VR authoring. Earlier measurements below
remain historical evidence; they are not proof of isolated native GPU limits.

This audit tracks Full, Stick, Ball & Stick and Quick Surface from desktop/backend
publication through native calculation, GPU submission and SteamVR delivery.
It distinguishes source inspection, measured live workloads, and untested cases.
Normal whole-model grips and selected-part edits are separate workloads.

The [full-size 24HB follow-up](vr_24hb_tool_performance_20261002.md) retains a
separate dataset with 24 helices and 6,720 nucleotides in every source design,
four controller profiles, a fresh baseline and controlled runtime resets.
Use that report for full-size results; the tool counts below describe this
earlier mixed-size campaign.

The strongest result is selected Quick Surface Move: repeated ~45 ms style
rebuilds break the 11.11 ms frame budget, despite healthy normal Surface rendering.
Recurring synchronous mirror readback is a second optimization target. A separate
standalone representation-activation defect was fixed. Final baseline coverage
is 48 successful idle/grip intervals; the tool campaign has 54 runs across 44
unique tool/representation pairs, of which 16 complete the full workflow and 28
retain unresolved acquisition, visibility or timing boundaries.

## Measurement contract

`NADOC_VR_FRAME_AUDIT=1` records every completed native outer frame through the
bounded asynchronous trace sink. The default is off. No GPU wait or readback was
added. `frame_audit.hpp` measures exclusive wall-time phases plus separately named
**inclusive** calculation scopes; those two sets must not be added together.
Per-frame records include representation, frame-end tool mode, runtime period,
focus, submission state, phase durations and calculation call counts. Clock and
scope overhead is included; final record formatting/enqueue is outside timed
phases but affects cadence. These are instrumented-run results, without a paired
uninstrumented overhead calibration.

The recorder measures the native frame thread; asynchronous export/preparation
workers and backend/browser CPU require their own traces. Their polling and
activation costs are included here, but worker CPU is not silently attributed
to the frame thread.

The outer loop includes event polling, startup, representation activation, jobs,
visualization and trajectory updates before `renderFrame`. Within rendering,
OpenXR waits/synchronization, input and tools, scene drawing, mirror, capture and
post-submit work are separated. Driver calls can block: CPU wall time is neither
pure CPU execution nor GPU time. Whole-loop wall time includes runtime pacing.
The legacy `scene_p95_within_budget` flag covers only its scene interval and
cannot establish a complete frame budget or tool responsiveness.

Application submission FPS estimates cadence from outer-loop start timestamps
of consecutive focused submitted frames, never a reciprocal of CPU render cost. Disjoint frame groups do not get an invented FPS.
The compositor sampler separately records GPU duration, repeated frames,
drops and mispresents. Its polling timestamps have about 100 ms boundary
uncertainty. Short gesture percentiles remain spot checks. Stereo PNG/class/ID
captures are outside measured intervals and prove submitted-eye geometry,
not physical panel scanout or wearer comfort.

Trace overflow invalidates reports. Missing intervals, fallback/unfocused
frames, failed input deadlines and failed authoring assertions remain explicit.
The tool runner retains setup/menu reaches; native mode and representation label
those rows. An open tool panel alone does not prove an edit occurred.

## Calculation and invalidation inventory

The table is a source-level inventory of the principal calculation families,
not a claim that every branch or GPU instruction has been profiled.

| Calculation family | Trigger and current behavior | Audit boundary or next check |
| --- | --- | --- |
| Desktop design/helix geometry | Store/geometry revisions rebuild or update helix, crossover, slab and connector matrices. Simulation updates preserve live display transforms. | `design_renderer.js`, `helix_renderer.js`; distinguish geometry revisions from color/UI updates. |
| Slab display changes | Thickness decomposes live slab matrices, changes thickness, recomposes and refreshes connectors. FEM slab export occurs only with active FEM updates. | Test unchanged settings and transformed/hidden slabs; a naive cached equality check must not suppress application to newly built geometry. |
| Desktop VR snapshot | Clones displayed FEM positions/colors/slab frames; atomistic visualization visits atoms and builds semantic keys. | `main.js` VR snapshot producer and `vr_visualization_snapshot.js`; applicable during simulation, not normal idle design frames. |
| Native event publication | `publishEventState` serializes and truncates/writes the event file synchronously; presenter poses use the asynchronous latest-file writer. | One Full Bend reach contained a 19.95 ms event-publication wall outlier; Full Twist publication maxima stayed below 0.17 ms. Reproduce before attributing disk versus scheduling cost. |
| Browser event and feedback transport | Native events poll at 50 ms; jobs at 1500 ms; queued publishers coalesce updates. Tool configuration and preflight use monotonic sequence/generation guards. | `vr_session.js`, `vr_tool_preflight_coordinator.js`; profile commits and pending feedback separately from continuous motion. |
| Backend scene export | Geometry, axes, owner aliases, endpoint weights, atom templates and surface geometry become scene records. | `routes_vr.py::_snapshot`; selective export avoids generating unrelated representations. Export time is not headset frame time. |
| Startup and lazy representations | Worker parses/prepares geometry; context thread stages GPU buffers and atomically activates a representation. | `pollStartup`, `pollRepresentationLoading`, `prepared_style_controller.inc`; include activation and cache eviction spikes. |
| Visualization snapshots | File mtime skips unchanged files. A new sequence reconstructs position/color/slab/coordinate maps and invokes `setStyle`. Colors/slab presence conservatively advances visualization revision. | `pollVisualizationSnapshot`, `GlScene::setVisualization`; identical republished colored/slab snapshots are a candidate for stronger equality/revision guards. |
| Coordinate playback | New trajectory packets update resident coordinates; interpolation samples only eligible atomistic representations. | `pollTrajectoryFeeds`, `updateAtomCoordinates`; topology/style changes fall back to general rebuild. |
| Input and model placement | Runtime pose/action sync, controller transforms, grips, ray-panel intersections, snapping, menus, haptics and input ownership. | `syncActions`; tracking/runtime waits are separate from application calculations. |
| Selection | Partial trigger and eligibility gate volume picking; semantic resolution chooses owners. Every focused frame checks highlight membership. | `updateSelectionVolumeCandidates`, `selectVolume`, `setSelectionHighlights`; unchanged sets return without `setStyle`. |
| Move/Rotate | Owner validation, transform equality, indexed packed transform, endpoint weights, bounds and affected-buffer upload. | `setToolPreview`, `applyPackedPreview`, `rigid_preview.hpp`; Full/Stick/Ball & Stick/VDW use packed path when eligible. |
| Surface or visualized-slab Move/Rotate | Excluded from packed-preview representation gate; changing previews can use general `setStyle` rebuild. | High-priority live tool case. Do not infer cheap selected edits from cheap whole-model grips. |
| Bend/Twist | Plane picking, handle/arc preparation, wheel/range updates, browser preflight and authoritative geometry feedback. | `processBendPlanes`, `processBendHandles`, `prepareBendArc`; guard unchanged configuration without losing commit/Undo changes. |
| Extrude and end resize | Lattice plane/cell mapping, painted drafts, wheel transforms, endpoint handles and browser-authoritative execution. | `processLatticeInput`, `end_resize.hpp`, `vr_extrude_draft`, preflight coordinator; distinguish draft redraw from geometry commit. |
| Nick/Ligate | Sidecar version parsing, endpoint/bond hit tests, hover and preview guides; browser performs topology edits. | `ligation.hpp`; polling currently opens/reads a header every focused frame even when inactive. Geometry parses only on new versions. |
| Dimensions | Per-entry world/source conversion and serialization; ack read and pending journal publication. | `dimension_sync.hpp`; serializes attached-independent valid entries each update and rewrites pending journal until acknowledged. Candidate revision-based work. |
| View tools, volumes and simulations | Feed polling, panel layout, clipping masks, transformed per-volume scene renders, job rows and selection. | `view_tools.hpp`, `view_volume_panel.hpp`, `simulation_panel.hpp`, `renderVolumes`; volume passes can multiply geometry drawing. |
| Guides and UI | Controller beams, paths, panels, glyph geometry, hover/highlight meshes, blur and overlays. | `updateControllerGuides` and eye draw; closed-panel measurements do not establish open-panel cost. |
| Shadow pass | Light/view bounds, light projection, primitive instancing and depth map render per rendered frame. | `renderShadowMap`; CPU submission duration excludes asynchronous GPU execution. Static shadow caching requires geometry/light/model invalidation. |
| Stereo scene passes | Projection/view/model matrices; instanced sphere/bond/box transforms; normals, lighting, shadow sampling, alpha and clipping. | Two production eye draws, plus highlight geometry. Atomistic pixel coverage and selections can dominate GPU time. |
| Picking/capture passes | Object-ID attachment and capture readbacks when requested, plus class/depth buffers and encoding. | Captures deliberately excluded from baseline/gesture intervals; inspector work is not free. |
| Mirror and presentation | Eye blit/downsampling, desktop swap, presenter pose publication, live measurement/capture completion. | Separate phases; desktop contention and swap blocking can affect frame delivery despite low scene CPU times. |

## Confirmed defect and correction

The standalone snapshot launch queued prepared representation styles but never
polled them: `pollRepresentationLoading` returned whenever lazy startup was not
enabled. A real Stick request was accepted while rendered frames remained Full.
The poller now advances prepared styles for standalone viewers too. Lazy startup
retains its existing path. The retained failed run times out on Stick; the
corrected smoke run displays and measures all four representations.

This is a correctness fix found by the performance audit, not a claimed GPU
optimization. Production geometry, quality, lighting, shadows and motion presets
were preserved.

## Initial live evidence

24HB private immutable export from `workspace/24hb_0xT.nadoc`; requested source
representations Full, Stick, Ball & Stick and Quick Surface. Native defaults,
physical OpenXR/SteamVR, no competing test browser in the baseline. Model
orientation is isometric, placement distance 1.30 m and scale setting 3.0;
normal grip gestures move and return it. Captures retain actual eye poses.
The host uses an RTX 3080 Ti (12 GiB, driver 580.178.04); captured eye buffers
are 1852 × 2056 each. The runtime period is 11.1111 ms (90 Hz). These numbers
are specific to this host, view, design and production settings.

The first `steady_fast` smoke pass has 10 seconds idle plus two approximately
0.8 second whole-model gestures per representation. All four pass visible
stereo model checks. About 89.5 application submissions/s in every interval;
no compositor repeats/drops were sampled in these intervals.

| Representation | Idle GPU p95 ms | Worse grip GPU p95 ms | Idle frames |
| --- | ---: | ---: | ---: |
| Full | 2.60 | 2.53 | 894 |
| Stick | 8.58 | 8.69 | 894 |
| Ball & Stick | 8.90 | 9.00 | 894 |
| Quick Surface | 4.20 | 4.29 | 894 |

Runtime period is 11.111 ms. GPU figures are compositor pre-submit GPU durations,
not combined CPU-plus-GPU budgets. No `setStyle`, visualization map rebuild,
coordinate update or packed-preview transform occurs in these idle intervals.
Preview/highlight equality checks occur once per frame and individually cost
less than 0.001 ms at p95; controller guide calculation is under 0.008 ms at p95.
These inexpensive calls are poor first optimization targets for this workload.

Evidence: `.development-artifacts/vr-frame-audit-20261001-fixed-smoke/` contains
raw per-frame log, interval JSON, compositor JSONL, both-eye PNG/IDs/classes and
machine-readable summaries. All-four-profile and authoring results are tracked
separately; this table does not claim selected-part edit or commit performance.

## Reproduction

Debug → VR Tours & Tests → Controls & layout → VR frame calculation audit.
Tool campaign: Tools · Authoring → Tools across representations · frame audit.

```sh
uv run python -m tools.vr_workflows.frame_audit_tour --validate --output /new/audit
uv run python -m tools.vr_workflows.tool_frame_audit --validate --output /new/tools
```

The second command uses the existing private tool fixtures, which differ in
model size. It is not a same-24HB scaling comparison. Specific cases can be run
with `--tools move --representations full stick`. Existing tool assertions and
input deadlines are unchanged. Tool requests unsupported by a representation
must remain reported failures or explicit unsupported cases.

Any existing owned live tour can record native timing using
`NADOC_VR_FRAME_AUDIT=1`. `frame_audit --log viewer.log --intervals intervals.json
--output report.json` summarizes explicit intervals. On-screen user sessions can
also be recorded with the flag at launch; it does not alter controller ownership.

Retained setup failures: initial all-representation export was interrupted to
avoid unrelated high-detail work; selective launch first lacked `uv` on the
runtime-sanitized PATH (corrected to absolute executable); control mode with an
event file was rejected by the existing ownership guard (corrected to explicit
transactions mode); the next live run exposed the standalone style-poll bug.
No failed attempt is counted as successful coverage.

## Longer baseline matrix and capture boundaries

The first all-four-profile matrix completed all 48 idle/grip intervals and all
stereo motion checks. GPU p95 ranges across intervals were Full 2.10–3.55 ms,
Stick 8.35–8.56 ms, Ball & Stick 8.82–9.03 ms and Quick Surface 3.62–4.41 ms.
Its raw counts were Full 12 repeated/10 dropped, Stick 11/0, Ball & Stick 18/13,
and Surface 39/16. These counts must **not** be interpreted as clean idle-drop
rates: the first roughly 100–140 ms of several next-profile idle intervals
includes compositor samples from the preceding capture/recovery boundary.
The next run adds one second of unmeasured settling before each idle interval.
The original matrix and all raw counts remain retained.

The same matrix also has unambiguous mid-interval hitches: Ball & Stick has
repeats during return grips; Quick Surface has repeats/drops several seconds
into idle and inside both deliberate grips. Those cannot all be explained by
capture-boundary assignment. Source geometry did not rebuild in idle; low GPU
p95 is insufficient to rule out runtime/driver/system contention or rare GPU
stalls. No universal 90 Hz guarantee is established.

Evidence: `.development-artifacts/vr-frame-audit-20261001-matrix/`.

## Final baseline with capture settling

The repeated matrix adds one second of unmeasured settling before every idle
window. All 48 intervals (four representations × four unchanged motion presets ×
idle plus two grips) and their stereo motion checks completed. There were no
missing intervals, malformed records or trace overflows. Across all 18,452 measured
frames, `setStyle`, `setVisualization`, `updateAtomCoordinates` and
`applyPackedPreview` were each called zero times. This replaces the first
matrix for baseline interpretation, while retaining that earlier evidence.

| Representation | Native measured frames | Application FPS range | GPU p95 range, ms | Compositor samples | Repeats / drops |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full | 4,612 | 89.43–89.55 | 2.02–3.02 | 4,598 | 0 / 1 |
| Stick | 4,613 | 89.44–89.56 | 8.27–8.62 | 4,648 | 0 / 0 |
| Ball & Stick | 4,614 | 89.51–89.83 | 8.62–8.94 | 4,622 | 0 / 0 |
| Quick Surface | 4,613 | 89.52–89.53 | 3.39–4.74 | 4,634 | 0 / 0 |

Ranges span the 12 measured intervals per representation, not repeated estimates
of one pooled percentile. Non-runtime-wait application wall p95 spans roughly
0.46–1.16 ms, but includes driver blocking and excludes only the explicitly named
runtime waits. Its p95 still misses much of the periodic readback. GPU and CPU
wall measurements overlap; do not add them. One sampled Full drop and the earlier
mid-interval hitches remain evidence against an unconditional no-drop guarantee.

Evidence: `.development-artifacts/vr-audit-20261001-baseline-final/` contains raw
logs, exact intervals, compositor samples, summaries and all stereo captures.

## Slab regression connection

The recent rigid bead/slab fix is specifically in the export projection:
`full_slab_reference_geometry` undoes authored residue poses before the paired
slab contact solve, then carries each solved slab/connector with its own residue.
Solving again against an already moved mate had moved nominally stationary slabs.
That is an authority/invalidation problem, not simply a slow matrix multiply.
The native frame loop consumes those solved primitives; the measured idle/grip
runs do not rerun the contact solver or `setStyle`. Future caching must retain
separate topology, authored pose, simulation slab frame, appearance, selection
and presentation revisions instead of treating every change as new geometry.

## Recurring GPU readback cost

`sampleSpectatorPixels` runs every 30 mirror frames whenever a mirror exists,
not only during explicit captures or when a diagnostics output file is requested.
It downsamples and synchronously reads RGBA and stencil bytes, then assesses
pixel changes/coverage. This can force queued GPU work to complete on the XR
thread between the eye passes. The explicit `glFinish` calls elsewhere in
`main.cpp` belong to the isolated benchmark, not the normal VR loop.

In the first four-profile 24HB matrix, the containing `mirror_blit` phase has
these idle p99 ranges (four 10-second windows per representation):

| Representation | Mirror phase p99 ms | Worst mirror phase ms |
| --- | ---: | ---: |
| Full | 1.18–1.39 | 2.75 |
| Stick | 4.65–4.87 | 6.47 |
| Ball & Stick | 5.04–5.11 | 6.93 |
| Quick Surface | 1.88–2.85 | 15.99 |

These are CPU wall intervals containing blit, diagnostic readback and related
work, not isolated shader times. At roughly one sample per 30 frames, p95 can
miss the recurring readback cost. The source mechanism and p99 evidence make
this a strong candidate for asynchronous PBO/fence readback. Such a change must
retain each sample's original frame, pose, source and classification metadata;
reading a delayed result with the newest pose would create a correctness bug.
Do not remove quality, shadows or visibility evidence to make timings pass.

Other source-level optimization candidates are per-query reconstruction of
`resolveSelectionVolumeHits` token/kind vectors (including empty-hit queries),
linear alias scans during owner resolution, and per-frame dimension serialization
and pending-journal rewriting. Cache these against the correct immutable source
or journal revision. Their priority requires measured active-tool cost and
correctness tests for selection/style replacement, commit, Undo and simulation
frame changes; source complexity alone is not a benchmark.

## Authoring observation limits found during the campaign

The original Move probe enumerated only rendered `nuc:*:backbone` points. That
cannot acquire a target in Stick and does not establish a production picking
failure. The extended performance setup selects in Full, changes representation
through the ordinary menu, then points at selected geometry reconstructed from
submitted-eye IDs/depth. Its metadata explicitly excludes direct atomistic
selection coverage. Edit input, commit and persistence checks remain unchanged.

Bend/Twist's former framing used a fixed world translation and left the other
controller hovering over the panel. A retained failed capture shows the model
matrix did not change during the attempted grip. The observer now derives a
translation from stereo projected targets/handles and parks both simulated
controllers before gripping. Head tracking, panel dimensions, model scale and
visibility thresholds are unchanged. Failed attempts remain separate evidence;
a predicted clear layout alone never passes without the actual captured layout.


## Selected Quick Surface edit: reproduced budget failure

The Surface Move probe successfully selected in Full, switched through the real
menu, and pointed at the selected Surface geometry. The changed-preview reach
then failed the unchanged playback deadline by 168 ms. In its 11 complete native
frames, six `setStyle` calls cost 44.85 ms median / 45.93 ms p95; containing
`setToolPreview` reached 47.27 ms p95. Application submission cadence fell to
25.56/s. Preceding Surface menu/pointing reaches were approximately 89.5/s.
This is a small 6HB fixture, not the 24HB baseline. The short failed reach is
reproduction evidence, not a stable throughput benchmark or a completed edit.

This confirms the source-level exclusion from packed preview is consequential:
changed selected-part Surface previews reconstruct style on the frame thread.
A Surface-compatible affected-geometry preview path is the leading tool-specific
optimization target. It must preserve surface ownership, affected neighborhoods,
selection, authoritative commit, Undo and representation switching. Whole-model
grip performance cannot establish selected-part edit performance.

Evidence: `.development-artifacts/vr-tool-frame-audit-20261001-detailed/move-surface/`
(`frame-audit.json`, `reaches.jsonl`, native log, stereo captures and failed tour).


## Authoring coverage matrix

These are `steady_fast` runs on each existing tool's private fixture, not all
tools run against one common 24HB scene. Pass means the existing input, pixel and
authoritative document assertions completed; it does not assert an FPS threshold.
The latest retry supersedes the earlier attempt only for that tested condition.

| Workflow | Full | Stick | Ball & Stick | Quick Surface |
| --- | --- | --- | --- | --- |
| Move selected base | Pass | Pass after Full selection | Pass after Full selection | Preview rebuild exceeds budget; motion deadline fails |
| Bend | Both handle previews visible; angle-wheel acquisition fails | Probe lacks required plane targets | Probe lacks required plane targets | Feedback timeout before edit |
| Twist | Pass | No probe deformation geometry | No probe deformation geometry | Feedback timeout before edit |
| Extrude | Profile-wheel acquisition fails | Same Full-only setup failure | Same Full-only setup failure | Same Full-only setup failure |
| Nick | Scissors visibility fails | Scissors/bond visibility fails | Scissors visibility fails | Scissors visibility fails |
| Ligation | Compatible-bond pixels fail | Pass | Compatible-bond pixels fail | Stretched-bond pixels fail |
| End Resize | Pass | Pass | Pass | Cyan feedback pixels fail |
| View tools | Tablet pixels fail | Tablet pixels fail | Tablet pixels fail | Tablet pixels fail |
| Simulation results | Job/menu pixel checks fail | Job/menu pixel checks fail | Job/menu pixel checks fail | Job/menu pixel checks fail |
| Dimensions placement/persistence | Pass | Pass | Pass | Pass |
| View Volumes manipulation/persistence | Pass | Pass | Pass | Pass |

Extrude's requested representation was never reached. Likewise, a failed
pre-edit target acquisition cannot validate changed geometry costs. Simulation
uses the existing static-result tour; continuous trajectories are not covered.
Failures can be harness/observation limitations or product defects; the matrix
alone does not distinguish them. Error traces and original captures are retained.

Move's successful changed-preview reaches each contained 68 complete frames at
about 88.2 application submissions/s. Stick and Ball & Stick each performed 17
packed updates with zero `setStyle` calls; active-update p95 wall time was
0.122 ms and 0.254 ms respectively. Full also used the packed path. This is
single-base coverage, not a guarantee for large selections.

Successful workflow FPS ranges below span all requested-representation reaches,
including menu/pointing/setup reaches. They are not pooled steady-state editing
FPS, and a functional pass does not promise uninterrupted 90 Hz.

| Successful workload | Full | Stick | Ball & Stick | Quick Surface |
| --- | ---: | ---: | ---: | ---: |
| Move base | 88.21–89.54 | 83.75–89.54 | 88.21–89.52 | Failed reach: 25.56 |
| Twist | 89.49–89.58 | — | — | — |
| Ligation | — | 85.58–89.56 | — | — |
| End Resize | 89.50–89.55 | 89.52–89.56 | 89.50–89.53 | — |
| Dimensions | 88.25–89.55 | 88.23–89.57 | 88.21–89.57 | 88.22–89.54 |
| View Volumes | 86.94–89.55 | 86.95–89.55 | 86.98–89.55 | 86.95–89.55 |

A dash means no completed workflow, not zero FPS. Raw reached-stage timings for
failed cases are retained in the normalized reports.

Latest evidence roots:
- `.development-artifacts/vr-tool-frame-audit-20261001-prebuilt/` — original Full.
- `.development-artifacts/vr-tool-frame-audit-20261001-detailed/` — other representations.
- `.development-artifacts/vr-audit-20261001-move-retry/` — corrected target setup.
- `.development-artifacts/vr-audit-20261001-deformation-retry/` — stereo framing correction.
- `.development-artifacts/vr-audit-20261001-additional/` and
  `vr-audit-20261001-dimension-retry/` — Dimensions and View Volumes.
- `.development-artifacts/vr-audit-20261001-summary/index.json` — latest outcomes
  for all 44 tool/representation pairs, links to original evidence and normalized
  motion/session reports; manifest and validation logs are alongside it.

Dimensions needed explicit transaction-mode observation and retrying the initial
unfocused observation. Both standalone API fixtures now wait for startup, request
the chosen representation through the normal visualization-feedback endpoint, and
wait for actual readiness. Launch intentionally starts Full regardless of the
requested style; the first incorrect setup attempt is retained. No product
launch or input thresholds were relaxed.

## Reproduction and retained outputs

Run isolated sessions sequentially; an existing native viewer is never silently
replaced. Defaults use private copies/fixtures and close only owned sessions.
The gallery replacement for this campaign was explicitly authorized.

```bash
uv run python -m tools.vr_workflows.frame_audit_tour --validate --output .development-artifacts/my-frame-audit
uv run python -m tools.vr_workflows.tool_frame_audit --output .development-artifacts/my-tool-audit
```

Use `--tools move end_resize` and `--representations full stick ballstick surface`
to narrow the tool campaign. `--validate` repeats the existing four motion
profiles. The baseline can reuse its immutable `scene.nadocvr` with `--snapshot`;
retain the original export provenance alongside that snapshot.

For ordinary live use, set `NADOC_VR_FRAME_AUDIT=1` in the viewer launch
environment. The tools pass it automatically. `frame_audit.py --log … --intervals …
--output …` regenerates summaries; intervals are JSON objects with `name`,
`start_ms` and `end_ms`. Tool `reaches.jsonl` is newline-delimited JSON; convert
it to an array for that standalone CLI. Per-case outputs retain native logs,
compositor samples, reached-operation intervals, original tour assertions and
stereo captures. `session-frame-audit.json` includes setup, captures, asynchronous
commits and playback; it is intentionally unsuitable as a clean idle FPS gate.

## Optimization order and correctness gates

1. Add affected-geometry preview support for selected Quick Surface edits. The
   observed 45 ms rebuild already exceeds a 90 Hz frame budget several times.
   Compare original and optimized pixels/ownership, and validate boundary
   neighbors, Cancel, commit, Undo, save/reopen and representation switching.
2. Move recurring spectator diagnostics to asynchronous readback. Preserve
   frame/pose provenance and demonstrate actual p99/frame-delivery improvement
   with the same eye resolution, shadows, mirror and visibility checks.
3. Measure and cache semantic lookup preparation, pending dimension journal
   serialization and identical visualization publications by their actual
   source/revision. Do not use one broad dirty flag for geometry, appearance,
   simulation coordinates, selection and presentation.
4. Close the failed tool visibility/acquisition boundaries before interpreting
   their partial timing samples as successful tool performance. Repeat successful
   scenarios under the unchanged four profiles and larger selections/designs.

The audit does not establish complete backend/browser CPU attribution, every
shader's GPU time, all selection sizes, all combinations of view toggles/volumes,
continuous trajectory playback, thermal endurance, or physical wearer comfort.
Source coverage, successful live operations and those remaining validation gaps
are distinct. No rendering quality reduction is proposed as an optimization.


## Code validation and final state

The instrumented native viewer built successfully. Focused native staged-style
activation and rigid-preview tests both passed (2/2). Python recorder, interval,
framing, representation-setup, motion-input and tour-catalog checks passed
(66 tests; 26 existing FastAPI deprecation warnings). `git diff --check` passed.
Live success/failure assertions are listed separately above; unit tests do not
override failed visibility checks. Builds/tests ran sequentially outside measured
VR work. All audit-owned viewers were closed; the original user documents and
production quality settings were preserved. Changes remain uncommitted.
