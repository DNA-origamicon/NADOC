---
type: project
status: active
authority: canonical
review_after: 2026-09-21
---

# ScryWrite VR troubleshooting

**Active persistent goal (2026-09-22):** [two VR authoring workflows](../docs/vr_authoring_workflows.md).
Latest checkpoint2026-09-23: all four presets pass VR-first diagnostics with noisy
30cm normal approach to menu controls AND each paint cell (NADOC_VR_APPROACH_CELLS=1).
Native wheel now30mm travel per detent at default scale, formerly10.5mm; honeycomb
still7bp. Variable presets paint with retained retries and correct49→42with7fine
clicks.35focused,36native,23smoke pass. Combined steady-profile diagnostic passes
3.3m through desktop6HB→default→blunt→freeform→native Undo→cadnano/save/reload;
blunt-end selection/activation/buttons and freeform placement remain ideal.
Both verified review outputs published in workspace/VR Testing (desktop-then-vr:
19helices/2frames/1554positions; vr-first:7helices/504positions, each includes one
empty editor cell). Never read review outputs as test oracles.
Next: ISSUE-41 visual review weakness: native whole-design eye image is tiny/end-on
(82x64authored-pixel bounds); presence>=100pixels passes but is not useful review.
Desktop reload image is useful. Improve ordinary view orientation/zoom and require
meaningful projected coverage; actual desktop-window delivery remains pending.
Then finish profiled end/freeform/setup and run fixed80trial cohorts (still zero
credit). Evidence: .development-artifacts/vr-workflows/cell-approach-validation.md,
cell-approach-policy.json and combined-review-publication.json. Keep serial caution.
Editable review parts: `workspace/VR Testing/` (Archive-backed). Retests delete all
.nadoc parts there even after user edits; never use these as validation fixtures.
Start steady_fast, final all four; completion requires ≥18/20 whole-workflow passes
in each workflow × variable_fast/variable_deliberate group, independent oracles and
all default/blunt-end/freeform modes implemented. Painted footprint transport now carries bounded cell arrays and lattice type
through native events, backend parsing and browser reduction; paints/resets advance
configuration sequence. Explicit persisted frame identity and independent-bundle candidate builder now exist;
frame-aware membership and collision-free cadnano export added. HC/SQ and
XY/XZ/YZ candidate pose/file-roundtrip checks pass; two-frame desktop import/render
and export reviewed. Evidence: `.development-artifacts/vr-workflows/frames-validation.md`. Cadnano slice frame selection and cell add/remove now pass a real browser check;
far-cell cluster membership and undo are covered. Rendered-bound centering keeps
occupied cells visible on frame switching. Evidence:
`.development-artifacts/vr-workflows/frame-editor-validation.md`. Remaining:
frame-aware continuation/crossover neighbors and native-to-browser commit adapter.
Independent-frame API now has design/revision guards, read-only preflight and
snapshot commit/undo/redo; browser addFrameExtrusion synchronizes real geometry.
An empty-part plus oblique-frame API-driven browser check passed (3D/cadnano).
Evidence: `.development-artifacts/vr-workflows/frame-commit-synced/`.
Empty-part painted drafts now resolve to revision-pinned initial-frame plans and
run real read-only backend preflight; browser check verifies no mutation before
commit. Evidence: `.development-artifacts/vr-workflows/painted-preflight-browser.log`.
Native actions now snapshot their config sequence, backend/browser preserve it,
and preflight retains a copied one-shot plan, invalidated on new draft/cancel.
Late feedback cannot restore a canceled plan. Native build/36 CTests and browser
plan-retention check pass (`action-binding-*` evidence). Browser Confirm/Undo handler and targetless feedback are now connected and pass
the actual app event-dispatch/mutation/render/undo check. Pending feedback must
publish before mutation; lost terminal feedback never replays the edit. Native
extrusion acknowledgements skip Move/Rotate GL transforms. Evidence:
`painted-commit-*`. Native Confirm now gates on current painted preflight. First physical browser-
launched empty-part paint/Confirm committed two one-bp helices and native acknowledged
COMMITTED. Canonical topology refresh now publishes a revision-checked snapshot,
then atomically replaces native GL scene while preserving normalization/view/input.
Physical refresh run reached revision 3; after panel exit/recenter, actual authored
objects covered only 5/9 pixels in the eyes. This proves presence, not legibility.
RECENTER now fits authored bounds without changing normalization/topology. Physical
repeat showed 3774/3724 canonical pixels (previous 5/9); reviewed eye/mirror show bases.
Commit/Undo physical check passes: revisions 3→4, authored pixels disappear in both
eyes and browser helices return to zero. Probe lives in tools/vr_workflows, not
Archive fixtures. Evidence: fit-validation.md and fit-undo-atomic/.
Repeated runs fixed null-draft crash (ISSUE-33) and state-publication/status-reader
race (ISSUE-34). Next: 6HB/profile-driven paths, target toasts/commit diagnostics,
source-frame/blunt/freeform placement, real desktop-window and round-trip checks.
Ideal aim/semantic entry only; no profile-cohort pass yet.
Physical initial 6HB baseline now passes (six cells,42bp, exact browser cells and
lengths, cadnano export+viewer, native Undo). Snapshot took12.185s; bounded same-
design revision retry fixes autosave invalidation (ISSUE-35). Retained failure
artifacts distinguish stale snapshot from the old10s tiny-part observation limit.
Mirror remains end-on; ideal input only, no noisy-profile acceptance. See
vr-workflows/sixhb-validation.md and sixhb-timed/.
Cell aiming now uses profile_input.py with actual noisy reaches and119-pose
measurement evidence for steady_fast seed0. One initial neighboring-cell mistake
exposed acquisition sensitivity. Declared hover-feedback correction (max3 reaches,
all misses retained) achieved6 correct cells after7 reaches, then passed baseline
6HB/cadnano-read/Undo. Menus/length remain ideal-input; no full profile acceptance.
See profile-corrected/, profile-motion-summary.json and docs/vr_authoring_workflows.md.
Latest zoom/approach diagnostics:4x existing scene grip enlarges paint radius
6.48→25.92mm. Baseline wrist ray was66–71degrees oblique; normal approach25cm
from panel allowed first three variable_fast cells, but next cell(2,1) is clipped
out of viewport. Need production lattice pan/recenter; no change to noise or
three-reach limit. Evidence zoom-acquisition-validation.md / profile-normal4/.
CENTER PAINT now implemented in native lattice footer; view-only midpoint of
painted cell bounds, exported bounds/view_origin. Physical variable_fast seed0
with4x zoom+normal approach now passes6HB/cadnano-read/Undo:8 reaches,6 clicks;
centering[0,0]→[1,1] preserved cells.36 CTests pass. Evidence center-paint-validation.md
and profile-centered/. General pan, all-control noisy input and desktop text
legibility remain open; no cohort success.
No whole-workflow success yet. Empty documents now have an explicit v14
`Q empty_authoring` snapshot contract; native physical-runtime XY draft painting
verified, no committed geometry. Evidence: `.development-artifacts/vr-workflows/empty-live-check.json`.


Fast visual metrics (2026-09-22): MCP `scrywrite_measure`, authenticated inspector
`POST /api/measure`, and `python -m tools.scrywrite_inspector.visual_metrics` read
final stencil masks directly, with normalized ROI and numeric range assertions.
Live benchmark ~23 ms vs ~251 ms full capture/copy. No images/files in measurement.
Classes group UI; individual button IDs/contour fits are not implemented. Keep real
image/desktop checks. [Usage and Archive evidence](../docs/scrywrite_inspector.md#fast-numerical-visual-checks-2026-09-22).

Extrude source-plane increment (2026-09-22): `EXTRUDE FROM` cycles XY/XZ/YZ in native
settings, carried as `extrude_from` in drafts/observation. Scene v13 adds the
`F <plane> <lattice> <reason>` default record; older scenes use XY/unknown.
Desktop's existing dropdown now resolves loaded geometry too. Source IDs take
precedence over rest-axis alignment; mixed/oblique inputs remain explicit fallbacks.
Future blunt-end/freeform options are deferred; user-approved freeform semantics are
canonical-plane topology plus persisted placement. Frame ownership and commits remain
outstanding. See the audit below and `.development-artifacts/vr-extrude-from/validation.md`.

VR Extrude persistence/coordinates audit (2026-09-22):
[findings and implementation contract](../docs/vr_extrude_lattice_mapping_audit.md).
Painted cells are native drafts; existing-end plans preflight but have no attached
Extrude commit executor. Arbitrary orientation needs explicit lattice-frame ownership,
frame-aware cell consumers and a browser-authoritative transaction. Mixed-plane same-cell
segments reproduce duplicate cadnano export coordinates; do not assume UI paint proves authoring.

User preference and reusable skill: [make debugging observable](feedback_debug_visibility.md).
Proactively improve viewing conditions while preserving the behavior under test.

## Start here: live visual inspector status (audited 2026-09-22)

[Inspector capability index and entry points](../docs/scrywrite_inspector.md).
Implemented: unified native VR inspector at `http://127.0.0.1:8766` (when running),
`tools/scrywrite_inspector/` and `frontend/scrywrite/inspector/`. It combines stereo
pixel identity picking, frame-bound hit geometry/rays, production input ownership,
normal/hidden scene rendering and the existing Extrude human-profile workflow.
`tools/vr_motion/session.py` shares the transport/session/capture/release safeguards.
Use steady_fast first; final validation all four in the same viewer session.
Hide the chiral fixture after tests requiring its scene/object identity complete;
restore it only for scene-dependent checks and hide again afterward. Rendering-only
hiding preserves sizing/normalization; scene picking remains active outside UI.
Session launch/socket/PIDs: `.development-artifacts/vr-human-motion-live/launch.json`.
Remaining: synchronized scrubbable native/browser timeline, general actionability
locators and per-control occlusion assertions. The desktop Three.js inspector remains
`frontend/src/scene/scene_inspector.js`; it serves a different renderer.


Human-motion testing (2026-09-22): [dataset location and modeller](project_vr_human_motion.md),
with [CLI/runbook](../docs/vr_human_motion.md). Seeded synthetic traces and imported
Vive recordings feed existing Witness/live interfaces; human-profile calibration and
physical validation of the new modeller remain open.

For Vive recovery or a requested dummy left-eye window, first read
[VR recovery guardrails](feedback_vr_restore_proven_path.md). The existing physical
mirror and view-relative framing were user-confirmed working on 2026-09-08; do not
substitute a scripted actor view or new display method.

## Mission

Give NADOC's custom Linux C++ OpenXR viewer a Playwright-style troubleshooting
surface: deterministic controller/head input, semantic locators, auto-waiting
assertions, combined browser/native traces, stereo evidence, and tiered CI/headset
execution. ScryWrite is a gray-box application driver; it is not a competing design
model or a replacement OpenXR runtime.

Detailed research, sources, architecture, script contract, metrics, and phase scope:
[`docs/scrywrite_architecture.md`](../docs/scrywrite_architecture.md).
Adversarial findings, remediations, and explicitly unproven claims:
[`docs/scrywrite_adversarial_audit.md`](../docs/scrywrite_adversarial_audit.md).
Physical-HMD mirror contract and dummy validation:
[`docs/scrywrite_desktop_mirror.md`](../docs/scrywrite_desktop_mirror.md).

## Binding decisions

1. Reuse Playwright Test as the outer runner and artifact/reporting system. Add a
   `scrywrite` fixture; do not build a second scheduler.
2. Production remains OpenXR-driven. Deterministic test input enters only through an
   explicit test adapter/entry point and must be impossible to enable accidentally.
3. Locate by stable v12 semantic primitive/owner/tool-scope identities and roles, not
   draw indices or pixels.
4. The browser/backend remain authoritative for mutations. Native scripted feedback
   is a state-machine test, never evidence of a persisted design edit.
5. Use explicit virtual frame steps and observable-state waits, never timing sleeps.
6. Keep all control/trace formats bounded, versioned, private where live, and strict
   about malformed, non-finite, stale, or future input.
7. Separate fast logic, deterministic render, OpenXR-runtime, and physical-headset
   gates. Never claim haptics, comfort, reach, or legibility from simulation.
8. Preserve the current numeric scene oracle (`1e-6 nm`, `1e-5°`) and add visual
   evidence as a separate gate rather than loosening geometry tolerances.

## POC acceptance

- A standalone headless native CLI consumes a `SCRYWRITE 1` script.
- It drives real `ToolShell`, `PendingRigidTransform`, and `HandPose` code.
- The representative scenario covers Cluster selection, Move/Rotate Preview,
  controller drag, exact Cancel, Confirm acknowledgement, retained committed pose,
  exact Undo, and semantic assertions.
- Every command emits deterministic JSON state; a failed assertion reports its exact
  script line and preserves the trace prefix.
- Native CTest and a Playwright fixture both execute the same scenario.
- No OpenXR runtime, headset, live server, or user design is touched.

## Historical next-after-POC plan (superseded by later implementation)

The private socket, captures and live Vive inspection now exist; see the inspector
index and September 16 section. The combined native/browser transaction gate remains open.

Extract a narrow production/test input and frame-source interface from `main.cpp`,
then connect the fixture over a private live socket. The first live end-to-end gate is
Move/Rotate Cancel/Confirm/Undo against an isolated Playwright design copy. Add scene
identity validation and ray-picking before advertising general semantic locators.
Rendered stereo capture, Monado, and real-Vive observation follow only after that
transaction path is deterministic.

## POC implementation (2026-08-21)

- `native/vr_viewer/src/scrywrite.hpp` implements the bounded v1 script parser,
  virtual frames, real interaction-core driving, assertions, coverage summary, and
  deterministic JSON trace.
- `native/vr_viewer/src/scrywrite_main.cpp` is the standalone stdin/file CLI.
- `native/vr_viewer/examples/scrywrite_move_rotate.scry` is the canonical shared
  Cancel/Confirm/Undo scenario.
- Native unit/CLI CTests and `frontend/scrywrite/poc.spec.js` execute the proof;
  Playwright attaches the JSON trace.
- `just test-scrywrite` is the focused verification entry point.

Evidence: all 14 native viewer tests passed with the documented system toolchain, the
Playwright POC passed, and all 5,846 frontend unit tests passed. The first broad native
link attempt found Conda's linker through `PATH`; selecting `/usr/bin` resolved that
environment issue without a source change.

## Witness Mode implementation (2026-08-21)

- `--scrywrite-witness` runs an explicit live OpenXR observer session. Physical HMD
  views remain untouched; only application hand/button samples are scripted.
- The viewer draws ghost hands/rays and the actor head frustum, and renders the
  scripted actor camera into a head-following in-VR monitor.
- `aim_menu` resolves labels against the currently active real menu; `expect hover`
  verifies the independent production hit-test. Missing controls and mismatches pause
  visibly at the failing line.
- Physical left-menu toggles pause; physical right-menu single-steps while paused.
- Safety is fail-closed: Witness Mode refuses `--events`, suppresses haptics, and
  blocks X11 desktop clicks. It cannot publish a browser design mutation.
- Canonical scenario: `examples/scrywrite_witness_menu.scry`. Parser-only check:
  `nadoc-vr-viewer --validate-witness <script>`.
- Automated evidence: 19/19 native tests passed. Physical Vive appearance remains
  unverified and is tracked as MV-SCRYWITNESS.

## Headset-free evidence export (2026-08-21)

- `nadoc-vr-scrywrite-export` consumes a natural Full `.nadocvr` scene and a
  `SCRYWRITE_WITNESS 1` script, reuses the viewer's normalization/placement, and
  deterministically exports actor POV and X-Z plan SVGs plus JSON metrics.
- `frontend/scrywrite/render_evidence.mjs` rasterizes the SVGs with Playwright so the
  checked evidence can be viewed as PNG without OpenXR or a headset.
- The original yawed six-helix tile is retained as historical POC output. The
  canonical fixture and its strict thresholds are now the `scrywrite_chiral_*`
  example files described in the audit tranche below; regenerate with
  `just scrywrite-evidence`.
- This is a deterministic geometry/pose diagnostic, not a capture of the OpenGL
  stereo renderer. Physical stereo orientation, comfort, and legibility remain
  MV-SCRYWITNESS.
- Verification after adding the exporter: 19/19 native CTests, all six focused
  ScryWrite CTests, and the Playwright ScryWrite scenario passed.

## Adversarial audit tranche (2026-08-21)

- The former `visible_primitives > 0` success condition was disproved: a 55-degree
  wrong-facing actor could return success with a virtually blank PNG. Evidence v2
  now distinguishes in-front, in-frame, fully-contained, clipped, readable, and
  projected-bounds metrics. PASS requires a strict checked-in expectation manifest;
  unchecked exports are `not_evaluated`, and checked failures exit nonzero.
- The default perspective fixture is now a rigid diagnostic derivative of
  `workspace/Chiral_test.nadoc`, preserving its asymmetric 12-axis long/short-arm
  silhouette and adding four colored endpoint markers. It is not a hull-render or
  topology oracle. The canonical result is 16/16 fully in frame/readable, zero
  clipped, `0.024265` projected-bounds fraction, and zero gaze error; a 55-degree
  mutation fails.
- Witness scripts can independently assert live `tool` and `status`; the canonical
  menu flow now verifies `move_rotate` / `select_target`. Failure and completion
  neutralize held test buttons. The frustum guide now matches the 72-degree vertical,
  16:9 actor camera.
- Physical-dummy mirror POC: normal browser launches select the physical left eye.
  While OpenXR accepts rendering, the GLFW window copies that undistorted swapchain
  image before release. When the runtime reports `shouldRender=false`, it switches to
  a labeled live pose/FOV rerender. The title reports source, render class,
  liveness, tracking, yaw/pitch, and local frame/motion; full XYZ remains in JSONL.
  A colored corner heartbeat exposes presentation liveness. It remains observational
  until OpenXR submission correlation.
- Highest-priority remaining work is production scene-model reuse, depth/per-object-ID
  capture beyond the implemented design-vs-grid classes, and one browser-correlated Move/Rotate
  transaction. HMD color/liveness sampling is now implemented but remains diagnostic.

## Physical-HMD desktop mirror POC (2026-08-21)

- `native/vr_viewer/src/spectator_mirror.hpp` owns strict eye selection, aspect-fit,
  title telemetry, and heartbeat behavior. `main.cpp` blits the selected eye before
  swapchain release in `SUBMITTED` mode or rerenders its latest located pose/FOV in
  `SPECTATOR FALLBACK` mode when the runtime suppresses HMD rendering.
- Browser/API launches default `mirror_eye` to `left`; direct CLI launches remain
  off unless `--mirror-eye off|left|right` is supplied. `just vr-hmd-mirror` launches
  the chiral fixture, and `just scrywrite-witness` now includes the physical mirror.
- `SUBMITTED` is the eye-specific app image. `SPECTATOR FALLBACK` is a diagnostic
  rerender because there is no current submitted image. Neither is compositor lens
  warp, SteamVR overlays, the headset camera, or the scripted actor POV.
- Automated checks cover parser/view selection/aspect fit/title, backend argument
  propagation, native compilation, and surrounding regressions. Dummy/headset visual
  confirmation is still manual validation debt.
- The first physical attempt stayed black while the headset moved. A root-composited
  window capture proved it contained the VR clear color, not a transparent window,
  but the fixture was outside the eye frustum. `--reference-grid room` now renders a
  5 m, 0.5 m-spaced six-face cage at OpenXR LOCAL origin regardless of controller
  focus: +X red/−X cyan, +Y green/−Y magenta, +Z blue/−Z yellow. A live desktop
  capture visibly contains the cage. `just vr-hmd-mirror` and Witness enable it by
  default; normal app launches keep it off. Telemetry showed the previous freeze was
  SteamVR returning `shouldRender=false` after frame one. The fallback subsequently
  advanced from F1185 to F1950 while tracked and visibly rendered the cage/heartbeat.
  User confirmation of deliberate same-direction physical motion is still required.
- Disabling SteamVR's **Pause VR when headset is idle** kept a clean physical-HMD
  session in `SUBMITTED` beyond the former five-second cutoff. The diagnostic launch
  now supports `--place-scene-in-view on` (`just vr-hmd-mirror` defaults it on): the
  first stable 15-sample tracked window centers the fixture 1.30 m down gaze, carries its authored
  presentation orientation with the head, and applies 2× scale. A retained submitted
  left-eye capture visibly contains the asymmetric chiral origami and room grid.
- User physically confirmed that the desktop mirror follows headset motion and that
  the `SUBMITTED` grid/origami image is present through the headset lenses. After the
  dummy was leveled, live pitch was approximately −0.6 degrees. The implemented trace adds
  64×64 eye-viewport samples every 30 mirror frames: black detection, pose-conditioned
  `STABLE`/`FROZEN?`/`CHANGING`, `PX` title state, and optional JSONL correlating local frame,
  wall time, OpenXR predicted display time, source, signature/luminance/change, and
  pose delta. Same-pass stencil classification now distinguishes design, reference
  grid, and overlays: a 74-sample mutation stayed `GRID ONLY` with zero design while
  a 276-sample framed run stayed `DESIGN+GRID` with up to 2.44% design coverage.
  It remains vulnerable to wrong-design false passes, raster-noise false changes,
  downsampling loss, and the absence of compositor acknowledgement. Startup fixture
  placement now waits for 15 stable fully tracked poses after a transient tracked
  SteamVR pose exposed premature placement.
- Reproducible view framing is now a one-command contract: `just scrywrite-frame`
  targets the mirrored eye with `front`, 1.30 m, and 2× defaults. The first three
  optional arguments select named orientation, target view (`mirror`/`head`/left/right),
  and mirror eye. Seven presets plus bounded local yaw/pitch/roll cover refinements;
  the title reports `O <PRESET>`, the console records application, and every mirror
  JSONL sample persists all placement parameters and applied state. Paired live
  front/top runs produced distinct color signatures while retaining `DESIGN+GRID`.

## Live menu positioning validation (2026-08-21)

- Witness v1 now supports `touch_menu <hand> <left|right|top|bottom>`, which resolves
  a controller position from the current production panel bounds rather than from
  authored world coordinates. `expect placement following|docked` and
  `expect menu_moved <meters>` expose the real `MenuPlacement` state and displacement.
- The canonical menu witness now opens Options, grip-drags its right border into a
  world-docked pose by at least 0.20 m, resets the ray origin away from the panel,
  then opens Tools and activates Move/Rotate with the existing independent hover,
  tool, and status assertions.
- A connected physical SteamVR/Vive run stayed in `SUBMITTED EYE`, passed the complete
  open/position/interact chain at ScryWrite frame 942, and reported a tracked physical
  observer pose. This validates application-side menu behavior on this runtime; it
  does not close the separate wearer-only legibility, stereo, comfort, or reach debt.

## Layered menu debugging and fault oracles (2026-08-21)

- `MenuLayoutAudit` is wired into production menu rendering. It uses the same fitted
  stroke geometry as drawing and exposes `expect layout valid`; the focused fault
  suite catches long-label overflow, below-floor fitted text, control overflow,
  undersized/misaligned/overlapping hit regions, and invalid geometry.
- `expect framing valid` projects the four actual panel corners into the scripted
  72-degree 16:9 actor camera. This was added after the first real actor-eye PNG
  revealed the lower menu was clipped; the corrected capture pose frames the complete
  tablet and excludes witness-only frustum/status overlays from its own image.
- Witness `snapshot` writes a real 960×540 OpenGL actor-eye PNG, a tolerant 32×18
  luminance fingerprint, and semantic JSON. The canonical trace retains five
  baselines: Options open, Tools hover, Tools open, Move/Rotate hover, and active.
  Playwright validates their ordered menu/hover/tool/status/layout sequence and
  attaches all images/state records under tracing.
- Live assertions distinguish `display submitted` from spectator fallback and require
  `tracking tracked` plus `overlay visible`. The final bounded run passed all five
  visual baselines and application assertions at frame 284 on the active Vive.
- `scripts/vr_diagnostics.sh` wraps loader-matched OpenXR core validation and API dump,
  Nsight Systems OpenGL/OS-runtime profiling, and an availability-gated RenderDoc
  workflow. Core validation passed the complete trace with no errors; API dump kept
  the frame-284 pass; Nsight emitted an 18 MB `.qdstrm` (this install lacks its report
  importer and kernel CPU sampling); RenderDoc is not installed and is not claimed.

## Full-origami atomistic MD validation (2026-08-24)

- Canonical runbook: [`docs/scrywrite_atomistic_md.md`](../docs/scrywrite_atomistic_md.md).
  Fixture is downloaded Alpine job `fc12195d0636` for `24hb_2xT`: 151,013 displayed
  DNA-heavy atoms and about 169k bonds from a 1,354,425-atom solvated topology.
- Root cause was native `GlScene::setStyle` doing repeated linear ownership/alias/tool
  searches per primitive plus large source copies/uploads. Hash indexes, immutable
  source pointers, atom-token indexing, and a validated shared Ball+Stick/Stick buffer
  path reduced repeated switches from crash-scale work to about 0.001 ms.
- Native atomistic rendering uses sphere impostors, line-bond LOD, and no dense-scene
  shadow pass. Exact physical-HMD scene work measured about 0.22 ms p50 / 1.6 ms p95.
  OpenXR loop duration is not render duration: runtime synchronization may block.
  Judge `scene_p95_within_budget` and active-headset SteamVR compositor statistics.
- Browser MD frames now use `atomisticRenderer.updateFrame`: stable topology updates
  matrices in place and emits `geometryPath: coordinates`; topology changes fail back
  to `rebuild`. Browser Ball+Stick/Stick changes reuse sphere and bond instances.
- `scripts/vr_atomistic_diagnostics.py` has `system`, `capture-md`, and
  `steamvr-stats`; all emit private JSONL process start/progress/end telemetry. The
  SteamVR gate rejects absent/inactive/timed-out HMD samples.
- `scrywrite_witness_atomistic_24hb.scry` semantically asserts the complete native
  representation boundary chain: Ball+Stick → Full → Ball+Stick → Stick → Full →
  Ball+Stick. The extended Vive run remained submitted/tracked, captured all six
  states, and passed at frame 514. Exact transition times were 309 ms Ball→Full,
  798–815 ms Full→Ball, 0.0005 ms Ball→Stick, and 321 ms Stick→Full. A clean 960×540
  submitted left-eye image visibly contained the complete CPK atom/bond assembly.
- Remaining cost is startup, not interaction: snapshot creation is about 58 seconds;
  the 82 MiB gzip expands to about 726 MiB, parses in about seven seconds, and leaves
  native RSS near 2.9–3.3 GiB. A future versioned format may deduplicate identical
  atomistic bond/ownership blocks only if semantic identity and Expanded parity remain
  strict.

## Live agent interface (2026-09-16)

- Runbook: [`docs/scrywrite_live_agent.md`](../docs/scrywrite_live_agent.md).
- Production viewer has opt-in private Unix-socket control (`--scrywrite-live`,
  modes inspect/control/transactions). `frontend/scrywrite/mcp_bridge.py` provides
  stdio MCP tools and follows the backend's private state file across relaunches.
- Browser launch opt-in: `?doc=<isolated-copy>&scrywrite=transactions`, then View in VR.
  Observe supplies session/sequence; stale actions and unsafe input fail closed.
- Native application/IPC gates exercise actual viewer handlers for lattice targets,
  paint/erase, wheel detents/input priority, panel drag, cancellation and input leases.
- Isolated browser gate exercises actual native-event receiver and real backend
  Move/Rotate Cancel/Confirm/Undo. Only the missing headset feedback transport is
  intercepted. This does not close combined native/browser/headset execution.
- Submitted stereo capture adds color, window depth, coarse render classes and
  semantic/transaction metadata. Same-pass uint32 primitive IDs now map to canonical
  owner tokens in `objects.json`, stable within the viewer session. Final overlay
  stencil masks IDs; decorative glow creates none. Compositor acknowledgement is
  still not claimed.
- Painted Extrude footprints remain explicitly unresolved/noncommittable. No new
  extrusion geometry mutation executor was added. Physical comfort/reach gates stay open.
- `just test-scrywrite-browser` uses dedicated ports/workspace and disables backend
  lifespan to avoid cloud autoconnection/job supervision alongside CPD work.

- Physical Vive validation 2026-09-16 passed on the existing SteamVR/X11 direct-mode
  path: focused/tracked submitted stereo, paint/erase, +21 bp wheel adjustment,
  0.10 m real grip drag, Cancel/release. Framed panels occluded design IDs correctly;
  baseline/final identity mappings stayed consistent. The diagnostic scene was the
  chiral fixture, standalone control mode, not browser-linked design editing.
- Retained report/images: `docs/generated/scrywrite/live_agent_20260916/README.md`.
  Raw stereo color/depth/classes/IDs and command traces are under
  `/tmp/nadoc-scrywrite-physical-20260916/` (ephemeral).
- New real-GL regression covers primitive shaders, front/rear occlusion, impostor
  discard, identity persistence, owner mapping, glow exclusion and overlay masking.

Visible-motion follow-up (2026-09-22): state success did not establish visible paint
or traces. Native contact layers now have dedicated stencil IDs and overlap-safe
strokes; new `visual_checks.py` verifies both-eye RGB/route/paint/persistence and
mirror-buffer parity, `desktop_check.py` verifies real X11 client pixels. Inspector
adds stage previews, magnification, and Paint and retain. All four profiles have
completed visibility confirmations; variable wheel detents still fail and long
combined runs have intermittent transport/timing failures. Evidence:
`.development-artifacts/scrywrite-inspector/visibility-05/validation.md`.

## Cautious execution after VSCode crash (2026-09-22)

User reported an unexpected VSCode crash and requested caution. Continue the VR goal with one test/build/runtime workload at a time; use bounded workers (browser1, unit tests/builds at most2) and focused checks before broad mandatory verification. Do not overlap full frontend/backend suites or native builds with physical VR tests. Inspect process handles before relaunching; preserve crash evidence and user editor sessions. No automatic VSCode/SteamVR restarts for diagnostics.

Initial read-only check: about21GiB available RAM, swap unused, no pytest/Vitest/Playwright workload remaining. Current-boot journal search found no OOM/segfault/NVIDIA Xid match; this does not establish the cause of the earlier crash. Older Code log shows an unresponsive extension host around17:39, without a confirmed causal link. Keep goal active; caution is not a user-requested goal pause.

Caution command detail: use `PYTEST_XDIST_AUTO_NUM_WORKERS=2 just test-smart`; the recipe passes `-n auto`, so omitting this environment variable uses all detected cores. The continuation-guard checkpoint accidentally omitted it; subsequent backend checks must set it explicitly. Frontend uses `VITEST_MAX_WORKERS=2`, Playwright `--workers=1`.

2026-09-23 recovery checkpoint: no active test/build workload; about19GiB RAM
available. Recent2h kernel journal has no OOM/segfault/NVIDIA Xid entry; cause of
reported editor crash remains unknown. Preserve serial/worker limits above.
Review visibility helper now has passing combined and variable_deliberate VR-first
pilots, with both-eye bounds/cluster/RGB checks and actual X11 mirror matching.
Temporary workspaces verified absent; no new runtime workload during reconciliation.
See docs/vr_authoring_workflows.md and review-view-validation.md in the workflow
artifact directory. Goal remains active, zero final acceptance cohort credit.

Freeform placement follow-up2026-09-23: optional NADOC_VR_PROFILE_PLACEMENT=1
uses shared explicit-pose noisy reach, preserves wrist roll and records applied
capture pose.40focused checks and steady_fast combined physical pilot pass. See
docs/vr_authoring_workflows.md and placement-validation.json. End gestures still
ideal; independent tracking-to-saved-placement oracle needs presentation-transform
telemetry; trace delivery/fixed cohorts still open. Zero cohort credit.

Blunt-end profile follow-up2026-09-23: shared menu_navigation preserves exact selected
end identity while fresh paint resets Inspect. NADOC_VR_PROFILE_END=1 profiles
terminal reach, menus, length clicks and Confirm. Steady_fast combined pilot passes
3.6m;34focused checks pass. Review parts republished from verified end-profile and
VR-first-review-desktop runs (end-profile-publication.json). High-variability end
pilots, applied-pose geometry oracle, setup/clear policy, trace delivery and final
cohorts remain open; zero acceptance credit. See docs/vr_authoring_workflows.md.

User-requested stopping point2026-09-23: visible terminal command is
`uv run python -m tools.vr_workflows.demo`; guide docs/vr_workflow_demo.md. Both
headed workflows passed under demo-kzp60tl9, with profiled end/freeform and real
pose→saved-placement oracle.69focused checks and36native checks passed. Review
parts republished, temporary workspace absent, idle focused viewer restored.
Three unrelated lint findings remain. User asked to stop, summarize, package demo,
commit and push; pause the persistent goal at this checkpoint, not complete it.
Fixed80trial90%acceptance, full authoring traces and headset comfort remain open.
