---
type: project
status: active
authority: canonical
review_after: 2026-09-21
---

# ScryWrite VR troubleshooting

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

## Next after POC

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
