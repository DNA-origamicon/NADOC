# ScryWrite unified VR inspector

Origami position tracking (2026-10-13): the [tracking workflow](vr_origami_tracking.md)
measures real molecular landmarks in original eye images and compares application
pixels with coherent model/eye projections. An opt-in bounded pose journal can
accompany the final-output recorder. Debug → VR Tours & Tests → Controls & layout
→ Origami tracking · pixels and expected pose opens its maintained entry point.
Final lens-distorted coordinates and application coordinates remain distinct.

Extrude source-plane selection: native settings expose `EXTRUDE FROM` (XY/XZ/YZ),
and observation includes `extrude.extrude_from` plus `extrude_from_reason`. The
canonical plane is independent of the tablet's diagnostic viewing orientation.
Source defaults and remaining authoring work: [mapping audit](vr_extrude_lattice_mapping_audit.md).

Status audited **2026-09-22** against source, Git history and the running Vive
viewer's read-only observation endpoint. Search terms: live visual inspector,
VR inspector, scene inspector, inspection mode, menu debugging.

**The unified graphical VR inspector is implemented.** It reuses the native live
API, stereo object IDs and human-motion probes rather than introducing a second
controller driver.

For the desktop-mapped controller sidebars, `just vr-menu-tour` starts an isolated
viewer and performs a visible tab/page tour using this same live bridge and human
motion tooling. See [VR sidebar menus](vr_sidebar_menus.md) for full validation
and retained stereo/desktop evidence.

## Open the inspector

The active local instance is `http://127.0.0.1:8766`. Session-specific socket,
path file and process IDs are recorded in
`.development-artifacts/vr-human-motion-live/launch.json`; inspect that file rather
than assuming a stored PID is still current. To start a fresh inspector:

```sh
/usr/bin/python3 -m tools.scrywrite_inspector \
  --socket /private/session/viewer.sock \
  --path-file /private/session/extrude-intended.path \
  --output .development-artifacts/scrywrite-inspector/new-session
```

Use a new/empty output directory. The viewer must already expose its live API and
load the same `--controller-path` file. Observation/capture work in inspect mode;
profile tests require an isolated physical-runtime **control** session.

- Capture either eye, select a retained frame, click a design pixel for its native
  identity/owner, or select a control/cell to inspect captured geometry. Bounds and
  rays are projected using that capture's eye pose/FOV, not the latest live pose.
- Live state reports production input ownership, hover, trigger, wheel and draft
  state. Target details distinguish captured dimensions from live ray metrics.
- Run **steady_fast** first. Final validation requires that initial pass in the
  same viewer session and runs **all four** presets with the scene restored.
  Mutating actions/captures are locked during a run; Stop releases simulated input.
  Failed assertions remain red even when all trials finish. Open the report for
  desired/observed paths, hit and wheel outcomes.
- Use **Hidden — interface diagnostics** after fixture-dependent identity/scene
  checks finish. User policy: do not leave the chiral fixture obscuring interface
  debugging. Restore Normal when a test needs scene geometry/occlusion, then hide
  it again. Hiding suppresses rendering in headset, mirror and captures while
  preserving normalization and interaction geometry; underlying scene picking
  remains active outside UI targets.

Image history retains four captures; optional two-second refresh pauses during
profile tests. These are submitted-eye snapshots, not compositor scanout. Capture
adds overhead. Profile artifacts remain under the selected output directory on
the archive drive. The controller viewer loop is not started by this inspector.

Implementation: `tools/scrywrite_inspector/`, `frontend/scrywrite/inspector/`.
Shared session validation, sequence checks, capture provenance and release logic:
`tools/vr_motion/session.py`. Profile policy: `tools/vr_motion/presets.py`.

## What exists and how to find it

| Capability | Status / scope | Entry point |
| --- | --- | --- |
| Unified native VR inspector | Implemented September 22: stereo picking, hit boundaries/rays, live input ownership, scene visibility, initial/final human-profile controls and reports. | `python3 -m tools.scrywrite_inspector`; launch instructions above. |
| Desktop scene inspector | Implemented, wired into the browser app. Click a Three.js object for type, material, user data, ancestry and instance details. Does not inspect the native headset renderer. | `window.__nadocInspect.toggle()` in the app's browser console; Ctrl/Cmd+Shift+I is also registered but may conflict with browser shortcuts; Esc exits. [Source](../frontend/src/scene/scene_inspector.js), initialization in `frontend/src/main.js`. |
| Live native inspection API | Implemented. Session/frame/focus, controls, hand poses, hover, menu/layout and Extrude state. `inspect` is read-only physical-controller mode, not a graphical inspector window. | [Live-agent runbook](scrywrite_live_agent.md); `frontend/scrywrite/mcp_bridge.py`, `scrywrite_observe`. |
| Submitted-eye inspection | Implemented. Stereo PNG, depth, stencil classes, per-pixel primitive IDs, owner mapping and frame/state provenance. Captures are snapshots, not a rolling interactive timeline. | `scrywrite_capture`; [September 16 retained validation](generated/scrywrite/live_agent_20260916/README.md). |
| Menu layout / framing diagnostics | Implemented. Text fitting, control/hit-region overlap, minimum size and panel framing assertions; Witness PNG/state evidence attached to Playwright traces. Not a live graphical hitbox picker. | [Layered debugging contract](scrywrite_architecture.md#layered-menu-debugging-contract); `menu_layout.hpp`, `scrywrite_visual.hpp`, `just scrywrite-menu-trace`. |
| Live physical-eye mirror | Implemented. Submitted/fallback/tracking/pixel diagnostics, view framing. Does not provide click-to-inspect. | [Mirror](scrywrite_desktop_mirror.md), [framing](scrywrite_scene_framing.md). |
| Motion and Extrude diagnostics | Implemented September 22. Intended/observed path overlays, hit geometry telemetry, profile matrix and HTML/JSON reports. | [Human-motion runbook](vr_human_motion.md), `tools/vr_motion/extrude_probe.py`. |

For a browser-launched read-only session, append `scrywrite=inspect` to the existing
document URL and choose **View in VR**. Enabling this flag does not alter an
already-running viewer. See the live-agent runbook for endpoint discovery and
standalone launch options. Do not turn on a second controller writer to inspect
an existing test session: `scrywrite_observe` is read-only in control mode too.

The current standalone diagnostic launch is recorded in
`.development-artifacts/vr-human-motion-live/launch.json`. Its PIDs/socket are
session-specific, not permanent configuration. During this audit, observation
confirmed a focused physical-runtime session, 12 controls, exported hit geometry,
Extrude state and a completed capture. No controller mutation or restart was needed.
The desktop scene inspector was verified by source and initialization wiring;
its browser shortcut was not exercised during this audit.

## History and why this was easy to miss

- **2026-05-17 — `31b0bbfe`:** desktop scene inspector shipped; later instance-level
  picking refinements appear in `b5397da5` (2026-08-01).
- **2026-08-21 — `4f2222bf`:** live-view diagnostics and framing.
- **2026-08-22 — `b254e593`:** layered ScryWrite menu debugging, layout/fault tests,
  Witness screenshots and Playwright artifact integration. Some project notes date
  the work August 21; the commit date is August 22.
- **2026-09-16 — `40468fa4`:** live agent inspection/control and stereo object identity
  evidence, physically validated on Vive. This is the recent inspection work.
- **2026-09-22:** controller path visualization, geometry metrics and four-profile
  Extrude probing added in the current workspace.

Older architecture/POC sections still describe historical implementation stages.
Their references to a “future socket,” future stereo capture or a pending initial
physical check are not current missing-feature claims. Use this index and the
live-agent runbook to establish present status before proposing new work.

## What remains to build

- A synchronized scrubbable timeline joining commands, native frames, browser commit
  acknowledgements and screenshots. Current capture history is bounded snapshots.
- Reusable semantic locators with auto-waiting actionability assertions for arbitrary
  tasks, and precise per-control occlusion evidence.
- Dimmed/isolated object views beyond the implemented normal/hidden scene toggle.
- Human usability/calibration checks: simulated presets are descriptive synthetic
  variations, not evidence about athletes, children or any demographic group.

Testing policy: start with `steady_fast`; final validation includes all four motion
presets. Submitted-eye evidence is not compositor scanout or human legibility proof.

Latest retained validation: `.development-artifacts/scrywrite-inspector/validation/README.md`.

## Visible-motion acceptance (2026-09-22 follow-up)

State-only successes were insufficient: the user could not see the painting or
paths. `tools/vr_motion/visual_checks.py` now independently projects intended and
applied ray contacts using captured eye poses/FOV. Native contact traces have
separate stencil classes (6 intended, 7 actual), drawn after the UI; controller
body visibility remains classes 4/5. Gold is the wide intended **surface contact**
route, magenta the narrower actual contact route. Thin floating trails remain
controller body paths, not surface hits. A wide gold underlay plus a thin gold centre line keeps the intended route visible even under repeated noisy magenta crossings.

Every stage checks pose error, route coverage/alignment, surviving coloured trace
pixels and controller pixels in **both eyes**. Paint additionally requires visible
selected-cell highlights for all three cells. A second capture checks persistence
after four seconds; this dwell is outside timed motion and preserves the preset's
speed. The inspector automatically displays each stage capture during that hold.
Magnification enlarges the same captured pixels and is explicitly labelled.

Native captures include `mirror.png`: the actual desktop backbuffer after the
submitted-eye blit, its selected eye and viewport. The checker independently
reconstructs GL_LINEAR scaling and compares RGB values, plus requires visible
coloured paths (two matching blank images cannot pass).

The **Paint and retain for review** button runs steady_fast painting only. It
leaves three cells and completed paths visible after releasing input; this does
not unlock the full-validation gate. The normal initial test still covers paint,
erase and both wheel directions. Final validation still includes all four presets.
Menus are placed facing the real eye by compensating the simulated wrist using
observed production placement; headset pose, tablet defaults and hit sizes are
unchanged. These view-facing tests do not cover every oblique viewing angle.

For actual desktop visibility, separately run (X11 workstation):

```sh
DISPLAY=:1 XAUTHORITY=/run/user/1000/gdm/Xauthority \
  /usr/bin/python3 -m tools.vr_motion.desktop_check SOCKET NEW_OUTPUT_DIRECTORY
```

Requires Pillow/numpy and the existing xwininfo/xprop utilities. It locates the
current viewer PID, captures fresh mirror evidence and compares actual desktop
client pixels. Covered/offscreen/blank windows fail; it does not raise windows.
Only a passing client crop is retained, avoiding screenshots of unrelated apps.
The native backbuffer check alone is not proof that the window is unobscured.
Neither check proves physical HMD panel scanout or human legibility: MV-38 remains
open for the user's through-headset confirmation.

Visibility regressions retained during development: (1) a repositioning segment
contaminated wheel-down, fixed by moving to the start before rearming the trace;
(2) repeated variable-profile crossings erased the reference route, fixed by a
thin intended centre line over the actual trace; (3) narrow lines lost magenta
pixels when the submitted eye was downsampled into the default desktop mirror,
fixed with wider diagnostic strokes. These are opt-in overlays, not scene geometry.
The actual-desktop gate also failed while another app covered the viewer and passed
when the existing mirror was activated; backbuffer similarity alone missed that.

For a failed profile, `python3 -m tools.vr_motion.extrude_probe SOCKET PATH_FILE OUT
--preset variable_deliberate` reruns just that case; this is explicitly a partial
check, not a complete final matrix. Default remains steady_fast and `--final`
remains all four. Transport errors retain the failed operation/frame/sequence in
report.json where available; never raise the motion-lateness budget to hide a
loaded-runtime failure. Consolidated evidence must identify each source attempt.

Latest visible-motion evidence: `.development-artifacts/scrywrite-inspector/visibility-05/validation.md` and `visible-matrix.html`.

## Fast numerical visual checks (2026-09-22)

Use MCP `scrywrite_measure`, authenticated inspector `POST /api/measure`, or:

```sh
python -m tools.scrywrite_inspector.visual_metrics \
  --socket /private/session/viewer.sock --roi 0 0 1 1 --expect expectations.json
```

MCP arguments: `session`, `expected_sequence`, optional `roi`. ROI is normalized
**top-left x, y, width, height**, contained in the image. It rounds outward to pixel
boundaries; results give the actual integer ROI. The command advances the session
sequence and waits for a newly submitted frame. Concurrent captures/measurements
fail busy. The four-second deadline is a timeout, not a mandatory wait.

The native module reads only final stencil bytes: no RGB, depth, object-ID
readback, PNG encoding, or files. Seven masks per eye report pixel counts, bounds,
pixel-center centroids, fill ratios, and moment-equivalent ellipse axes. Coordinates
are full-eye pixels with top-left origin; bounds are x/y/width/height. Absent masks
have zero pixels and null geometry. IDs: design 1, reference grid 2, overlay 3,
left controller 4, right controller 5, intended contacts 6, actual contacts 7.

Example expectations:

```json
[
  {"eye":0,"class_id":3,"ranges":{"pixels":[1000,null],"width":[100,null]}},
  {"eye":1,"class_id":3,"ranges":{"pixels":[1000,null],"width":[100,null]}}
]
```

Eyes: left=0/right=1. Metrics: `pixels,x,y,width,height,cx,cy,fill_ratio,major,minor`.
Range endpoints are inclusive; null means unbounded on that side. Empty rules,
unknown metrics, invalid ranges and nonfinite numbers are rejected. Missing shape
measurements fail their ranges. Explicit pixels=[0,0] tests absence. HTTP accepts
`roi` and `expectations`, returning the measurement and optional evaluation. CLI
exits nonzero on failed measurements/expectations. MCP returns compact structured
text with no image attachment; internal bridge state retains ownership checks.

**Limits:** these are render-class masks, not per-control identities or connected
components. UI controls share class 3. An ROI isolates a region but cannot distinguish
overlapping controls. Moment axes describe mask spread, not exact circle fits,
especially for outlines, disconnected shapes or clipping. Counts can include dark
panel backgrounds. They do not prove legibility, contrast, correct color, desktop
visibility, compositor delivery or physical headset comfort. IDs can be correct
when RGB shading is wrong. Continue full captures and actual desktop image checks
at milestones and on discrepancies; markers alone cannot replace these.

Physical-runtime benchmark: five samples each, median full measure 23.25 ms,
60%×60% ROI 22.34 ms, small corner 22.31 ms; three full capture-and-copy samples
median 251.10 ms (~10.8× faster). Capture includes additional data and disk I/O:
this compares workflows, not equivalent payloads. Bridge polling is 20 ms.
Both-eye interface checks passed; empty-corner presence checks failed as intended.
Against separate captured frames, count differences were <0.08% and centroid
distances <0.2 pixels. Physical tracking jitter remains.

Evidence and benchmark script: `.development-artifacts/scrywrite-fast-metrics/`
resolves to `/media/jojo/Archive/NADOC_archive/runtime/development-artifacts/scrywrite-fast-metrics/`.
See `report.json`, `benchmark.py`, `capture-2/left.png`, `desktop-review.png`.
Rerunning the benchmark requires fresh capture output directories.

Established approaches: [OpenCV shape statistics and moments](https://docs.opencv.org/4.13.0/d3/dc0/group__imgproc__shape.html),
[RenderDoc pixel inspection](https://github.com/baldurk/renderdoc/blob/v1.x/docs/how/how_inspect_pixel.rst),
[AprilTag fiducials](https://github.com/AprilRobotics/apriltag).
Integer masks avoid display-color ambiguity and require no extra dependency.
Next: stable semantic UI IDs in the actual draw pass, followed by component/contour
measurements and expected projected bounds. Optional marker flashes could verify
coordinate registration, but cannot prove that the actual control rendered.
Human-review holds remain separate from machine measurement timing.

### Read-only placement mapping evidence

Native observe/capture state includes `presentation` with
`model_to_tracking_rows` (row-major4x4), `source_center_nm`,
`normalization_model_per_nm`, and `normalized_offset_model`. Source coordinates
first become `(source-center)*normalization+offset`, then the4x4 matrix maps
them to OpenXR_LOCAL metres. The matrix is observational data from the current
scene manipulator; it does not change authored geometry or head tracking. Float
values retain round-trip precision.

`tools/vr_workflows/placement_oracle.py` independently forward-projects the saved
freeform cluster through these two mappings and compares it to the recorded
**actual applied** capture pose. It checks all rotation axes, not just the extrusion
axis, and rejects nonuniform/sheared/reflected presentation, nonzero authored pivot
or parented placement. Tolerances are0.1mm tracking position and0.05degrees rotation;
they measure mapping error, not distance from the user's intended pose. The
combined workflow writes `freeform/placement-mapping.json`; failure output is
retained separately. This is coordinate consistency, not a physical headset
visibility or human motor-performance claim.

## Bend controller validation

`just vr-bend-demo` runs the guided, isolated Bend authoring tour;
`just vr-bend-test` runs all four motion profiles in one viewer session. Both use
the existing ScryWrite bridge and `LiveSession` transaction opt-in. Read-only
`bend` observation exports plane indices, handle/end positions, current grab hand,
wheel ownership, angle/direction, contour length, and rendered pick targets.
The probe checks real controller inputs and stereo handle pixels; the browser
checks desktop geometry, feature-log identity, saved endpoint constraints, reload,
and Undo. See [VR Bend](vr_bend.md#scrywrite-test-and-guided-vr-tour).

Use non-circularized inputs for Bend validation. The user explicitly excludes
`Circle_spiral.nadoc` from test files and fixtures. The five-tool latency audit
uses an independent straight 24-helix/12,000-nucleotide bundle without existing
deformations or feature history; see [latency evidence](audits/vr_tools_latency_20261008.md).

## Twist controller validation

`just vr-twist-demo` runs the guided Twist authoring tour; `just vr-twist-test`
runs all four controller profiles in one viewer. The `twist` observation includes
plane indices/frames, signed amount and units, total angle, wheel/rotation-handle
ownership, and rendered pick targets. Tests require stereo handle pixels, fixed
plane positions/normals, desktop feature identity, persistence and exact Undo.
See [VR Twist](vr_twist.md) for controls, evidence, and validation entry points.

### Large Nick catalogs

Ordinary live observations and controller replies omit `ligation.bonds` to keep
motion playback responsive on large designs (`bonds_omitted: true`). Request
`scrywrite_observe` with `include_targets: true` (wire command `observe targets`)
for the full read-only catalog. Capture evidence includes it automatically.
Catalog coordinates are cached until the target version or model pose changes.


## Normal VR launch and timing recordings (2026-10-13)

The normal **View in VR** path supports the optimized viewer and final-output
recorder through the owner-controlled workstation file
`~/.config/nadoc/vr-capture.json` (`NADOC_VR_CAPTURE_CONFIG` can select another).
Its pinned layer library, viewer build directory, captures, private sockets,
pose journals and bulk scene/feed temporary files live on mounted Archive storage. A configured
host reuses its live capture compositor. When the runtime is fully stopped,
NADOC starts the same stock SteamVR stack with the process-local capture layer.
It never replaces an already running uninstrumented runtime silently.

Use right **Tools → Record final output 2s**. Wait through the countdown and
preparation until **Final output 2s** appears, reproduce the movement, then wait
for **Saved**. **Duration** selects two or five seconds; two seconds is the
memory-conscious default. Saving occurs after capture and can take longer than
the recording. **Open recordings folder** opens the actual final-output directory.
The explicit fallback label on unconfigured hosts is **Record app eyes 5s**;
that earlier boundary is not a final SteamVR recording.

Normal configured launches use a private ScryWrite **inspect** socket, keeping
physical controllers active, plus a bounded pose journal. Frame markers draw
only while the journal collects (preparation, capture, and100ms tail), not during
ordinary use. Marker `enabled:true` means configured capability; each eye's
`frame_identity.rendered` receipt proves drawing. Rendering optimizations are
on by default; GPU timing queries remain off.

The recorder saves the live viewer executable SHA256 and process start identity
before the measured interval. Required marker capability, authenticated journal
arming and OpenXR-to-monotonic clock mapping are checked before sending the
capture request. A saved pixel pack with failed/missing pose diagnostics is
reported **Partial**, retaining its useful pixels. Completion validates the saved
journal's session, capture window, clock metadata, successful stereo submissions,
and both eyes' frame-marker CRC receipts across the window. Pixel integrity and exact
image-to-journal association still require the offline decoder/auditor; menu
completion does not certify optical output or physical scanout.

A configured but unavailable recorder reports a setup/readiness error rather
than switching to application-eye recording. On this workstation, close SteamVR
normally and reopen VR from NADOC to prepare a stopped runtime. Do not repeatedly
restart a healthy instrumented runtime. The configured layer library is pinned;
install future versions in a fresh Archive directory, never over the mapped file.
`viewer_build_directory` selects the normal native build path while preserving
an explicit `NADOC_VR_BUILD_DIR` override. `restore_presentation_file` is an
optional owner-controlled Archive handoff for deliberate restoration; remove it
after the intended launch so later documents do not inherit an old placement.

The original integration evidence and reversible configuration/source baselines are
in `.development-artifacts/vr-output-capture-20261012/normal-launch-integration-20261013/`.
The subsequent menu-hover follow-up is in
`.development-artifacts/vr-output-capture-20261012/menu-hover-followup-20261013/`.
The user reports substantially reduced doubling, with remaining lag as menus
enter view or the other controller hovers/vibrates. Its complete stereo decode
proves 35 reused-image pairs per eye among 179 final presentations; zero capture
drops does not mean every presentation contains a new application image.
ISSUE-77 tracks this timing problem; physical doubling remains open as MV-44.

Configured recordings also collect bounded host timing for actual haptic API
dispatches, hover changes, sidebar texture updates and per-eye menu/backdrop GL
calls. The offline `summarize-interactions` command and optional bounded marker
ROI following are documented in [Origami tracking](vr_origami_tracking.md#menu-hover-and-haptic-timing).
Old recordings without these fields report them as unavailable. Call durations
are host elapsed time, menu draw counts are not visible coverage, and haptic
dispatch is not an independent observation of vibration. These diagnostics do not
change rendering or establish the cause of the lag.

The diagnostic viewer was deployed through the normal launch path and the actual
browser reattached. Its closed-menu 179-frame recording verifies collection with
zero UI activity; it does not exercise physical hover. The reload closed both
sidebars and did not restore their previous positions. Reopen and place the menus
before reproducing the issue with a two-second recording. Retain a menus-closed
comparison and the user's symptom description; optical output remains separate.

## Final SteamVR output capture (2026-10-12)

`native/vr_capture` is an explicit, process-local Vulkan layer for the stock
Linux SteamVR compositor. It records the final direct-display swapchain before
`vkQueuePresentKHR`: both eyes in the original panel layout, retaining the observed
lens warp and overlays, and any reprojection rendered into that swapchain. The ordinary NADOC eye
recorder is earlier in the pipeline. The desktop mirror is a different surface
and is deliberately excluded from final-output recordings.

This is a diagnostic tool. A complete presentation-boundary recording is **not**
a verified image-to-physical-refresh mapping or optical measurement. Present IDs,
completion waits, sampled vblank counters and pixel accounting are reported
separately. Vulkan permits imprecise timing between present completion and actual
display; a software buffer cannot measure panel illumination, persistence or the
headset's lenses. See the [present-wait contract](https://docs.vulkan.org/refpages/latest/refpages/source/vkWaitForPresentKHR.html).

The implementation uses bounded asynchronous GPU readback and lossless Zstandard
compression. Missing pixels, failed presents, failed writes, lost telemetry and
incomplete requests remain failures. It never inserts duplicated or interpolated
frames to make a recording appear complete. Raw buffering is capped by
`NADOC_VR_CAPTURE_MAX_BYTES` (16–512 MiB; launcher default 128 MiB). A separate
`NADOC_VR_CAPTURE_COMPRESSED_BYTES` buffer defaults to 1 GiB (16 MiB–2 GiB);
the workstation launcher uses a 1280 MiB cap to accommodate visible menus.
Requests shorter than five seconds scale that cap proportionally, rounded up to
a page with a 16 MiB floor. The default two-second menu recording therefore uses
512 MiB for compressed frames; five seconds uses the full 1280 MiB. The raw/GPU
buffers and 2 GiB reserve do not shrink with duration. Preparation and start
metadata retain both the configured cap and actual allocation.
Vulkan staging buffers and compression contexts add to these limits. Preparation
rejects insufficient memory headroom, prefaults buffers, warms codecs, verifies
compressed-buffer residency and preserves a 2 GiB available-memory reserve.
It then allows one second to settle before acknowledging the recording start.
Compressed pixels remain in RAM during recording; Archive writes begin afterward.
Buffer exhaustion fails explicitly; there is no filesystem spill fallback.
Saving writes the independent compressed frames into one bounded capture pack,
with a byte offset and length for each frame. This preserves random access and
avoids a disk synchronization barrier for every frame. It synchronizes the pack,
checks close and directory-sync results, and releases the raw and compressed recording buffers
before acknowledging completion. It never flushes unrelated files or drops the
system's caches. Metadata logs are flushed, not separately certified for recovery
after a machine crash. This can still cause visible contention during Saving;
measure it separately from the recording window.

The Archive writer uses direct disk I/O, at most 1 MiB per write and a 32 MiB/s
ceiling, after recording only. It requires filesystem-reported alignment and
dedicated buffers excluded from child processes on fork. An aligned, zero-padded
last block is truncated to the exact logical pack length before synchronization.
Unsupported direct I/O fails explicitly; there is no buffered fallback.
Once compression/readback is finished, it releases the raw pool
and unused compressed capacity. After each successful write it discards only the
complete anonymous source pages already copied by that write. This prevents
retained capture RAM and dirty filesystem pages from doubling memory pressure.
Do not replace this with buffered writes: a giant buffered write caused severe
reclaim and a SteamVR watchdog abort on this workstation, despite complete pixels.
Smaller paced buffered writes still caused multi-second stalls during Saving.
The actual cost must be calibrated on
the current scene and system; a stable display rate alone does not prove zero cost.
Detailed successful present/wait records are retained from preparation through
Saving and a two-second tail. Idle sessions keep a nominal one-second heartbeat and all
failures; suppression counts are distinct from lost records. Vulkan completion
bookkeeping and counter queries still run while idle, so reduced logging does not
mean zero idle instrumentation cost.

### Prepare and record

Keep an isolated checkpoint and save the active viewer assets/configuration before
restarting VR. All builds and captures belong on mounted Archive storage. Build
`native/vr_capture` with CMake under the original checkout's
`scripts/validation_guard.sh`. Use a new build directory for every revision:
**never overwrite a shared library mapped into a live compositor**. `ctest` runs
lossless-codec and Vulkan synchronization/failure contract tests. The optional
`nadoc_capture_probe` is a synthetic desktop-surface test; its results are not
headset evidence.

With the current VR session closed, launch the stock runtime through:

```bash
python -m tools.vr_capture.launch_compositor --start-runtime \
  --layer-directory /absolute/archive/capture-build \
  --output /absolute/archive/new-capture-session
```

This passes the explicit layer only to `vrcompositor`. It uses the installed stock
launcher and preserves its existing capabilities. No global Vulkan manifest,
driver, installed runtime binary or SteamVR setting is edited. Launch output means
processes were spawned; require successful direct-display events and visible
pixels before declaring a session healthy. `--diagnostic-fds` optionally records
one bounded, allowlisted device-descriptor snapshot during swapchain creation.

For the VR menu button, start the rebuilt viewer with
`NADOC_VR_COMPOSITOR_CAPTURE_DIR=/absolute/archive/new-capture-session/compositor`.
The existing Tools button becomes **Record final output 2s**. A **Duration** row
switches between two and five seconds and is disabled while recording or saving.
The duration row appears only in final-output mode. The button gives a two-second
countdown, reports preparation, waits for the compositor's acknowledgement, and reports saving,
partial capture or failure. The ordinary application-eye recorder stays inactive
in this mode. Without the opt-in variable, its original behavior is retained.
The helper runs outside the render thread; menu status does not decode pixels or
certify physical scanout.

The same acknowledged recording is available from the registered **Debug → VR
Tours & Tests → SteamVR final output · capture and calibration** terminal entry:

```bash
python -m tools.vr_workflows.compositor_capture_check \
  --directory /absolute/archive/new-capture-session/compositor --record
python -m tools.vr_capture.audit /absolute/archive/new-capture-session/compositor
python -m tools.vr_capture.review /absolute/archive/new-capture-session/compositor \
  --output /absolute/archive/new-frame-review
```

The auditor decodes every saved frame, checks byte length/dimensions/format and records decoded-pixel hashes,
and requires a one-to-one match to successful captured presentation calls. It
validates disjoint, complete pack ranges and reads each frame separately rather
than loading the entire pack. Legacy separate-frame captures remain readable. It
keeps direct-display provenance, physical headset identity, refresh association
and optical verification separate. SteamVR's device log plus inspected pixels
establish the headset identity for the retained Vive experiment; generic
`direct_display` metadata alone does not. The review exports original lossless PNG
frames offline; viewing them on a desktop does not reproduce the headset's refresh
or optics. Raw requests and all failed attempts remain available beside the files.

### Measure overhead and recover

`uv run --no-project --with openvr python -m tools.vr_capture.calibrate` records
independent SteamVR application timing plus host/process resource evidence.
Its timing samples remain in RAM until the measured windows finish. Preparation,
active recording and saving have separate timestamped resource snapshots;
active entry follows the start acknowledgement and active exit can overlap the
first saving work. Use those actual intervals when computing resource costs.
Use `--directory CAPTURE_DIR --seconds 2 --output NEW_DIR` for repeated
quiet/recording windows. The low-level helper and calibration CLI retain their
five-second defaults for compatibility; the viewer passes its selection explicitly.
Quiet windows include the loaded layer's telemetry cost. A separate
`--baseline-only --compositor-pid PID --output NEW_DIR` run under an ordinary,
uninstrumented launch measures the earlier baseline; retain launch provenance to
establish layer absence. Close the SteamVR dashboard and retain scene, presentation
and tracking conditions. The sampler excludes recent provisional frame records and
0.3 seconds at each phase boundary. Pixel phases require acknowledged capture
intervals and exact completion accounting. Stationary calibration does not claim
to reproduce head-plus-controller rotation.

The October12 checkpoint, system inventory, saved executable/scene/Flex sidecars,
research, failed mirror attempts and calibrated runs are under
`.development-artifacts/vr-output-capture-20261012/`. `baseline-system/rollback.txt`
describes recovery. `python -m tools.vr_capture.baseline BASELINE --restore-plan`
verifies hashes and produces a read-only conflict report; it never overwrites live
settings. SteamVR normally rewrites calibration and runtime databases, so a later
difference must be attributed before restoring anything. To remove the capture
layer, close this VR runtime and relaunch SteamVR normally without the diagnostic
environment. No global uninstall is necessary.

The private viewer recovery tool copies saved assets, optionally restores their
source-to-tracking placement, and keeps physical controllers enabled in `inspect`
mode. Private recovery sidecars are disconnected from browser editing, and physical
tracking registration after a runtime restart requires headset verification.

Research also tested [NVIDIA Capture SDK9's direct Vulkan PID backend](https://developer.nvidia.com/capture-sdk).
This workstation's installed API initialized but returned `NVFBC_ERR_UNSUPPORTED`
when creating a DIRECT/EGL handle, before any capture session. That result does not
identify whether GPU support or backend/context policy caused rejection. The
capability-only probe and offline mock checks are in `native/vr_capture`; they
never create a capture session. OpenVR mirror probes were followed by compositor
failures on this setup; that experimental path is disabled by default and is not
the recorder. Available public timing extensions do not establish the exact native
surface-to-headset scanout identity; retained research identifies NVIDIA NVKMS
flip/completion correlation as the next instrumentation boundary.

### Retained workstation result

Frozen V12's two repeated two-second recordings passed 179/179 exact images each,
at 89.5192 and 89.5287 Hz with zero drops and 512 MiB compressed allocations.
Preparation took 1.11/1.09 seconds; saving took 12.54/11.44 seconds. GPU copy
medians were 0.418/0.402 ms per image. Independent application timing stayed at
approximately 44.763 Hz in all five quiet/recording windows. Full per-frame audits
are retained in `calibration-v12/capture-1.json` and `capture-3.json` under the
artifact root. This calibration measures the final launcher memory profile.
Incremental compositor CPU cost versus adjacent quiet windows was 1.35/1.33 core
equivalents. The two-second preflight required approximately 2.652 GiB available,
including the unchanged 2 GiB reserve. Saving maintained 89.527 Hz compositor
presentation with maximum present-entry gaps below 15 ms and consecutive sampled
vblank counts. Independent application timing was not sampled during Saving.

The ordinary-controller menu validation passed the 2→5→2 duration selection,
disabled duration changes while busy, and then actual recordings at both lengths.
With menus visible, two seconds saved 180/180 images and five seconds saved
447/447, both with zero drops and approximately 20% compressed-buffer headroom.
Their 433 MB and 1076 MB packs took 13.48 and 33.21 seconds to save; compositor
presentation continued at approximately 89.527 Hz with consecutive sampled
vblank counts. The application-eye recorder stayed inactive. Exact request audits
are in `menu-validation-v12/capture-audit-2s.json` and `capture-audit-5s.json`;
Saving analysis is `research/menu-v12-saving-progress.json`.

Frozen V11's two repeated two-second recordings each passed 179/179 exact images
at 89.5331 and 89.5295 Hz, with zero pixel or telemetry drops. Both used exactly
384 MiB of compressed capacity and retained the 2 GiB reserve. Preparation took
1.08 and 1.07 seconds; saving the approximately 365 MB packs took 12.12 and
12.53 seconds. Median GPU copy cost remained 0.402 ms per image. The five quiet
and recording windows all measured the application's existing approximately
44.763 Hz rate. These are stationary results, not a reproduction of the reported
head-plus-controller motion.

The V11 menu-visible request exposed a capacity limit: all 179 images were copied,
but only 167 fit in 384 MiB and 12 were explicitly reported as dropped. Its
approximately 2.406 MB compressed frames were larger than the stationary scene's
approximately 2.041 MB frames. This motivated the final 512 MiB two-second /
1280 MiB five-second launcher profile. The decoder accepts bounded random access
within packs up to the native 2 GiB hard cap; it never loads a whole pack to read
one image. Keep the partial clip as evidence; do not count it as a successful menu
recording.

Frozen V10 captured all 448 final direct-display swapchain images in five seconds at 89.5278 Hz.
Every image decoded exactly, all presentation waits matched, and all sampled
vblank increments were one. No pixel or telemetry drops were recorded. Median
GPU copy cost was 0.402 ms per image; median wait-hook observation cost was
0.211 ms. Incremental compositor process CPU during recording was about 1.34
cores, with 128 MiB raw and 960 MiB compressed buffer limits. These are measured
costs, not a negligible-overhead claim.

Preparation took 1.21 seconds after the helper sent its request. The 914 MB pack
took 37.44 seconds to save and synchronize on Archive. During Saving, compositor
presentation continued at 89.526 Hz, with a maximum 16.23 ms present-entry gap and
consecutive sampled vblank counts. Independent application timing was sampled
before recording, during recording and after Saving, at 44.763 Hz in each window;
application timing was not independently sampled during Saving itself.

The V10 repeated run did not pass as a whole: its second request was rejected
for insufficient memory. The rendered Tools button and ordinary controller input
were verified, but its live request also hit the memory guard. The helper reports
`Low memory - close unused apps and retry` and preserves the exact rejection
values. That five-second configuration needs about 3.09 GiB available before preparation,
including its 2 GiB reserve; it checks again after allocating and warming buffers.
Do not label a rejected request as a recording or lower the reserve to make a
test appear successful.

Evidence and current session/rollback details are in
`.development-artifacts/vr-output-capture-20261012/REPORT.json`. The complete V10
pixel audit is `calibration-v10-retry/completed-capture-1-audit.json`; its Saving
timeline is `research/v10-saving-progress.json`. These were stationary tests.
The user's upper-body rotation and visible monocular doubling remain to be
recorded with this final-output path. The latest full lossless desktop review is
`review-v12-full/index.html`. Start **Tools → Record final output 2s**, wait for
**Recording**, then reproduce the grip-and-turn motion. Wait for **Saved** before
starting another clip. That historical recovered viewer used private sidecars disconnected from browser
editing. The normal-launch integration above supersedes that runtime arrangement.
