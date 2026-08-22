# ScryWrite: deterministic VR troubleshooting for NADOC

Status: headless proof, live VR Witness Mode, and fail-closed headset-free evidence
export implemented; physical headset visual check pending. Adversarial findings and
remaining claims are tracked in `docs/scrywrite_adversarial_audit.md`.

## Decision

ScryWrite is NADOC's Playwright-style VR troubleshooting layer. It is a gray-box
driver for the native Linux C++ OpenXR viewer, not a replacement OpenXR runtime.
Playwright remains the outer test runner and supplies timeouts, reporters, artifact
attachments, and later browser coordination. ScryWrite supplies deterministic VR
input, semantic state inspection, VR-specific assertions, and trace artifacts.

The first proof of concept is intentionally headless. It drives the same pure
`ToolShell`, `PendingRigidTransform`, and `HandPose` code used by the native viewer,
but it does not start OpenXR, render stereo images, or mutate a design. This proves
the scripting, assertion, deterministic-time, trace, and Playwright-fixture seams
before runtime and rendering complexity is added.

## Why this is plausible

NADOC already owns the difficult application-level contracts:

- v12 scene records have stable semantic primitive, owner, and tool-scope identities;
- selection and tool feedback are bounded, sequenced, and browser-authoritative;
- interaction state and rigid preview transforms have pure native implementations;
- model-space scene parity already has numeric position, dimension, orientation, and
  color oracles;
- the real frame loop already records runtime display period and CPU percentiles.

The automation boundary is therefore small: substitute deterministic poses/actions
at the application input seam, observe semantic state, and preserve real OpenXR as a
separate integration gate.

Functional and transaction troubleshooting is highly automatable. Stereo rendering
is automatable once deterministic per-eye color, depth, and object-ID capture exists.
Real compositor performance, haptics, physical reach, legibility, and comfort still
require a fixed-hardware or human gate.

## Software landscape reviewed (2026-08-21)

No current tool covers NADOC's combination of custom C++, Linux, OpenXR/SteamVR,
semantic scene identities, and browser-authoritative transactions.

- [OpenXR CTS](https://registry.khronos.org/OpenXR/conformance/cts_usage.html) tests
  runtimes rather than application workflows. Khronos API-dump, core-validation, and
  best-practices layers remain useful diagnostics.
- [Monado](https://monado.freedesktop.org/) is a conformant open-source Linux runtime
  with simulated and remote devices. Its simulated driver is intentionally basic; it
  can underpin a later CI integration tier but supplies no locators, assertions, or
  application traces.
- [NVIDIA VCR](https://docs.nvidia.com/vcr-sdk/overview/overview.html) is the closest
  black-box capture/replay tool and records HMD/controller poses and buttons. Its
  documented workflow is Windows/OpenVR, it has no NADOC semantic oracle, and replay
  timing can lose inputs when application state diverges.
- [GameDriver](https://kb.gamedriver.io/working-with-the-unity-input-system-and-xr-using-gamedriver)
  supplies simulated XR input and hierarchy queries, but its agent targets Unity or
  Unreal projects rather than a custom native viewer.
- Unity XR Simulator and Mock Runtime are Unity-only.
- Research tools such as
  [VRTest](https://par.nsf.gov/servlets/purl/10333591) and
  [XRintTest](https://github.com/ruizhengu/XRintTest) establish useful object and
  interaction-flow coverage models, but their released implementations instrument
  Unity scenes.
- [PLUME](https://github.com/liris-xr/PLUME) is valuable for recording and analyzing
  6DoF user studies but is also a Unity recorder, not an application test driver.

## Architecture

```text
Playwright Test
  ScryWrite fixture
    native ScryWrite CLI / future private socket
      deterministic input + virtual frame clock
      semantic locators and assertions
      NADOC interaction/tool core
      trace recorder

Production integration tiers
  OpenXR adapter -> SteamVR -> Vive
  OpenXR validation/API-dump layers
  SteamVR compositor timing
```

ScryWrite must preserve these invariants:

1. Production input continues to come from OpenXR. Test input is enabled only by an
   explicit ScryWrite entry point.
2. Tests address stable semantic identities and roles, never draw order. Coordinates
   are reserved for spatial boundary and robustness tests.
3. The browser remains authoritative for design mutation. A scripted native success
   acknowledgement must never stand in for an actual browser/backend commit in the
   end-to-end tier.
4. Time advances by explicit frames. Tests wait for observable state rather than
   sleeping.
5. Control records and future sockets are bounded, private, versioned, and fail
   closed on malformed or future input.
6. Trace artifacts are diagnostic evidence, not an alternative source of design
   truth.

## Script and trace contract: POC v1

Scripts are portable printable ASCII, line-oriented, begin with `SCRYWRITE 1`, and
use finite numeric values. The POC commands cover semantic selection, tool activation, Preview,
controller poses, grip state, explicit frame steps, Cancel, Confirm/Undo feedback,
and assertions on status, selection, transforms, and transaction flags.

Example:

```text
SCRYWRITE 1
select cluster cluster:c1
tool move_rotate
preview
pose right 0 0 -0.5 1 0 0 0
grip right down
step
pose right 0.05 0 -0.5 1 0 0 0
step
expect pending_translation 0.05 0 0 0.00001
cancel
expect pending_identity true
```

Every command produces a deterministic JSON trace event containing the script line,
virtual frame, command outcome/error, selection, tool/status flags, and
pending/effective translation. The trace summary records assertions, virtual frames,
unique commands, visited states, and selection kinds. Failures retain the successful
prefix plus an explicit failed event and exact line-numbered error.

## Metrics and acceptance model

The 2025 [systematic mapping study of XR software testing](https://link.springer.com/article/10.1007/s10515-025-00523-7)
identifies four established coverage families: method, model, requirement-flow, and
interactable-object coverage. ScryWrite will use the following concrete metrics:

- interaction-flow coverage: exercised target/action/condition flows divided by the
  required flow catalog;
- model coverage: visited valid and invalid tool states/transitions;
- interactable coverage: controls and semantic target classes exercised;
- negative-space coverage: misses, occlusion, clipping, unsupported targets, stale
  feedback, tracking loss, and empty-space actions that correctly do nothing;
- transaction correctness: zero duplicate commits or stale acknowledgements, exact
  Cancel restoration, and feature-bound Undo;
- spatial robustness: pass rate and acquisition margin under bounded pose jitter and
  event-order permutations;
- geometry fidelity: stable identity/type/count/topology plus RMS/max position,
  angular, dimension, and color errors at the existing NADOC tolerances;
- visual fidelity: object-ID/depth parity before calibrated per-eye L1/L2/SSIM.
  [StereoID](https://doi.org/10.1145/3660803) demonstrates those image metrics for
  automated stereoscopic inconsistency detection;
- replay determinism: identical semantic trace and final-state hash across repeats;
- physical performance: CPU/GPU p50/p95/p99/max, dropped/mispresented/reused frames,
  and CPU/GPU reprojection reasons. Valve documents these in
  [Compositor_FrameTiming](https://github.com/ValveSoftware/openvr/wiki/Compositor_FrameTiming).

Performance thresholds are runtime-relative. OpenXR's `xrWaitFrame` supplies the
predicted display period, and SteamVR's assessment uses a rolling 32-frame average,
runtime-derived compositor headroom, and repeated excursions rather than one hard
11.11 ms rule. See [OpenXR frame synchronization](https://registry.khronos.org/OpenXR/specs/1.1-khr/html/xrspec.html)
and [SteamVR performance assessment](https://partner.steamgames.com/doc/steamhardware/steamframe/compat/perf_criteria).

Human task time/error counts, workload, and pre/post VRSQ/CSQ remain physical gates;
automation must not claim comfort or discoverability from a simulated pass.

## Delivery phases

- POC: headless deterministic Move/Rotate script, assertions, JSON trace, native
  tests, and a Playwright fixture.
- MVP: extract the viewer input/frame interface, add a private live control channel,
  auto-waiting semantic locators, browser/native transaction correlation, and one
  troubleshooting flow each for selection and Move/Rotate.
- Render tier: deterministic stereo color/depth/object-ID artifacts and calibrated
  visual diffs.
- Runtime tier: Monado smoke execution plus Khronos validation layers.
- Physical tier: real Vive replay/observation, compositor metrics, haptics, reach,
  legibility, and comfort checklist.

## Explicit POC limits

The POC does not validate that a scripted identity exists in a `.nadocvr` scene,
does not ray-pick rendered geometry, does not drive the live browser transaction
adapter, and does not start an OpenXR runtime. Execution-feedback commands exercise
the native transaction state machine only. Those omissions are visible boundaries,
not implied coverage.

## Implemented proof

The POC lives in `native/vr_viewer/src/scrywrite.hpp` with a thin CLI in
`scrywrite_main.cpp`. Both native CTest and `frontend/scrywrite/poc.spec.js` execute
the shared `examples/scrywrite_move_rotate.scry` scenario. `just test-scrywrite`
builds the two native targets, runs the native parser/scenario checks, then runs the
Playwright fixture. The trace is attached to the Playwright result for diagnosis.

Validation on 2026-08-21: both focused native tests passed, the Playwright POC passed,
and all 5,846 frontend unit tests passed. No headset/runtime/render claim was tested.

## Live VR Witness Mode

The native viewer accepts `--scrywrite-witness <script.scry>`. In this explicit mode:

- the real OpenXR headset pose remains the observer camera;
- scripted head/controller/button state replaces only application hand input;
- ghost controller guides, rays, selection volumes, and a scripted-head frustum are
  drawn by the normal viewer guide path;
- a head-following 16:9 monitor shows a separately rendered actor-eye view from the
  scripted head pose, including the actual live scene, menu, and controller guides;
- semantic `aim_menu` resolves a label on the active live menu, while a later
  `expect hover` independently checks the ordinary menu ray hit-test;
- a missing menu/control or state mismatch pauses the replay and leaves the failed
  view visible with a red `SCRYWRITE FAILED` marker;
- the observer's physical left menu button pauses/resumes, and the physical right
  menu button advances one replay frame while paused.

Witness scripts use the bounded `SCRYWRITE_WITNESS 1` format. Commands are `head`,
`pose`, `button`, explicit-frame `step`, `aim_menu`, semantic
`touch_menu <hand> <left|right|top|bottom>`, named `snapshot`, and
`expect menu|hover|tool|status|placement|menu_moved|layout|framing|display|tracking|overlay`.
`touch_menu` resolves against
the current live panel bounds and records its starting world position; the placement
assertions can then prove a grip interaction docked and displaced that same panel.
Failure or completion neutralizes every scripted button. Validate
without OpenXR using:

```bash
native/vr_viewer/build/nadoc-vr-viewer --validate-witness \
  native/vr_viewer/examples/scrywrite_witness_menu.scry
```

Run the shipped visual scenario against any valid snapshot using:

```bash
just scrywrite-witness
# Or: just scrywrite-witness scene.nadocvr path/to/test.scry
```

Witness Mode fails startup if an event-output path is also supplied. It suppresses
haptics and real X11 desktop clicks as an additional safety boundary. Local visual
state may change, but scripted input cannot publish a browser-authoritative design
event. Actor-eye and observer shadow passes use their respective head orientations.

Automated validation covers strict parsing, deterministic frame/button progression,
semantic expectation failure/pausing, the canonical scenario, viewer compilation,
and all existing native regressions. The actual Vive appearance is deliberately
recorded as manual validation debt: panel scale, stereo orientation, legibility, and
comfort cannot be established without wearing the headset.

Live validation on 2026-08-21 exercised the complete canonical chain on the connected
SteamVR/Vive runtime: open Options, resolve the right panel border, grip-drag the panel
at least `0.20 m` into a docked world pose, leave the panel plane, semantically hover
and click Tools and Move/Rotate, and observe `move_rotate` / `select_target`. The
runtime remained `SUBMITTED EYE` and the final replay passed at ScryWrite frame 942.

## Layered menu-debugging contract

Menu debugging deliberately uses several oracles instead of treating a desktop
screenshot as proof:

1. `MenuLayoutAudit` shares the production stroke-width/fitting calculations and
   records text bounds, owning regions, visual controls, and ray-hit regions. It
   rejects overflow, unreadably shrunken fitting, off-panel controls, undersized
   targets, hitbox mismatch, and overlapping hitboxes.
2. The actor-frustum oracle projects all four live panel corners and rejects panels
   behind or clipped by the deterministic 72-degree, 16:9 actor camera.
3. `snapshot` reads the real OpenGL actor-eye framebuffer into PNG, a tolerant 32×18
   luminance fingerprint, and semantic JSON metadata. Five stored menu-state
   fingerprints cover Options open/Tools hover/Tools open/Move-Rotate hover/active.
4. `frontend/scrywrite/witness_artifacts.spec.js` orders those artifacts by replay
   frame, checks semantic transitions and valid layout, and attaches every image and
   state record to a Playwright trace. `just scrywrite-menu-trace` runs this chain.
5. Live provenance assertions independently require a runtime-submitted mirrored
   eye, tracked HMD pose, and visible overlay. The OpenXR validation/API-dump and
   Nsight/RenderDoc wrappers live in `scripts/vr_diagnostics.sh`.

The focused fault suite proves each deterministic oracle with an intentional defect:
long-title overflow, text below its scale floor, control overflow, undersized or
misaligned hit targets, overlapping hit targets, clipped/behind panel placement,
and a large visual occluder. These checks establish application geometry and captured
composition. They still do not establish stereo fusion, wearer legibility, reach,
comfort, compositor overlays/lens warp, or physical interaction quality.

Final live validation on 2026-08-21 used the connected Vive/SteamVR runtime. The
five-state trace passed stored visual baselines, layout, framing, submitted-eye,
tracking, overlay, hover, tool, and status assertions at frame 284. The loader-matched
OpenXR core-validation layer completed the same trace without a validation error;
API dump retained the pass, and Nsight Systems captured an 18 MB OpenGL/OS-runtime
stream. RenderDoc was not installed, so frame-debugger execution remains an explicit
tool-availability boundary rather than an implied result.

## Headset-free visual evidence

`nadoc-vr-scrywrite-export` provides an additional deterministic check when the Vive
is unavailable. It reads natural Full primitives from the real `.nadocvr` snapshot,
applies the viewer's centering/`0.60 m` normalization and `-1.30 m` placement, reads
the initial scripted Witness pose, and exports two software-rendered diagnostic
views plus machine-readable metrics. The default fixture is a rigidly tilted
diagnostic derivative of `workspace/Chiral_test.nadoc`: its asymmetric twelve-axis
long/short-arm silhouette and four colored endpoint markers expose depth and
front/back reversals without claiming topology or hull-render parity. Run it with:

```bash
just scrywrite-evidence
# Override SCENE, SCRIPT, EXPECT, or OUTPUT for another checked Full snapshot.
```

The output prefix produces `_pov.svg`/`.png`, `_topdown.svg`/`.png`, and
`_evidence.json`. An export is diagnostic-only (`validation.status=not_evaluated`)
unless it receives a strict `SCRYWRITE_EVIDENCE 1` manifest. Checked metrics separate
in-front, in-frame, fully-contained, clipped, and minimally readable primitives;
screen occupancy; actor yaw/pitch; structure long-axis telemetry; target distance;
and gaze error. A failed threshold exits nonzero while retaining artifacts.

Canonical result on 2026-08-21: all 16 primitives are fully in frame and minimally
readable, none are clipped, projected bounds occupy `0.024265` of the frame, and
gaze error is `0.000°`. A 55-degree wrong-facing mutation fails. This remains a
software projection oracle—not OpenGL pixels, stereo capture, OpenXR compositor
output, occlusion proof, or evidence of physical scale, legibility, comfort,
tracking, haptics, or menu behavior.

## Physical-headset desktop mirror POC

The native companion window aspect-fits a selected physical eye. While OpenXR accepts
frames, it blits the undistorted eye swapchain after NADOC drawing and immediately
before release (`SUBMITTED`). If OpenXR suppresses rendering—for example, when a
dummy does not trigger the headset wear sensor—it continues locating the eye pose and
renders a clearly labeled `SPECTATOR FALLBACK` directly to the desktop. Normal browser
launches default to the left eye; direct CLI launches use
`--mirror-eye off|left|right`.

The title prioritizes source, periodic pixel-liveness status, tracking, yaw/pitch,
local frame/motion counters, eye, and grid state; full position remains in the trace.
An alternating corner square gives a pixel-visible heartbeat.
Only `SUBMITTED` is the actual application eye image. The fallback is intentionally a
second render because no submitted image exists in the suppressed state.

The mirror downsamples its eye viewport to 64×64 every 30 frames and correlates color
signature/luminance/change with pose delta, local frame, wall time, source, and OpenXR
predicted display time. Optional JSONL makes this trace persistent. Black is detected
independently; invariant pixels are `STABLE` while pose is still and only `FROZEN?`
when pose moved; materially different samples are `CHANGING`, never `OK`. The actual
eye render target also receives visible-layer stencil classes for design, room grid,
and overlays. The same 64×64 sample reports independent class coverage, making a
grid-only frame explicit without relying on palette assumptions. This remains a
coarse presence diagnostic: the wrong design object can pass, thin geometry can be
lost during sampling, raster noise can mask useful invariance, and no compositor
acknowledgement is available.

The POC does not show lens-warped compositor output or SteamVR overlays and does not
yet expose live eye/split selection, recording, depth/per-object IDs, or OpenXR submission
IDs. Its local frame/predicted-time trace must not be mistaken for compositor
correlation. See
`docs/scrywrite_desktop_mirror.md` for operation and the dummy-headset validation.

View-relative fixture placement is an explicit configuration rather than an inferred
world transform. `just scrywrite-frame` selects a target (`mirror`, binocular `head`,
`left`, or `right`), a named model orientation, distance, scale, and optional local
yaw/pitch/roll. Placement consumes only a 15-sample stable fully tracked window and
persists the complete contract in diagnostic JSONL. This makes the pose reproducible
without carrying headset coordinates between runs; see
`docs/scrywrite_scene_framing.md`.
