# ScryWrite unified VR inspector

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
