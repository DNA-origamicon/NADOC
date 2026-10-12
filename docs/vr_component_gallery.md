# VR component gallery

Open **Debug → VR Component Gallery → Component evaluations** and select
**Ridged thumbwheels VR demo** or **Ridged thumbwheels desktop demo**.
The gallery is also registered under Debug → VR Tours & Tests.
No design is needed or edited. Both modes run the same native geometry,
controller state and renderer. Desktop opens a separate Linux window on this
machine, suitable for remote desktop; it does not initialize OpenXR or SteamVR.

## Simulation menu review — current round 5 (2026-10-12)

**Debug → VR Component Gallery → Component evaluations → Simulation menus A/B
desktop demo** now compares trajectory controls. Both retain the accepted compact
split, narrow engine tabs, larger left buttons and **horizontal colour scale**.

- **A — Flat scrubber:** a thin filled slider with a simple handle, a full-width
  Load button, and Previous / Play-Pause / Next / Smooth in a row below.
- **B — Raised scrubber:** a recessed rail in a bevelled housing, ridged raised
  handle, ticks and endpoint labels. Play/Pause sits beside the rail; stepping
  buttons are below. Load sits beside Smooth in the setup area.

Choose **Trajectory**, **Chain trajectory** or **Full trajectory** under SNUPI,
oxDNA or NAMD. Selecting the mode does not load frames. Set **Start**, **End** and
**Every** (frame interval), inspect the selected count, then press **Load**.
Playback, frame stepping, exact seeking and scrubbing remain disabled until the
three-second sample Download/Prepare sequence finishes. **Cancel Load** returns
to setup. Editing a range or interval invalidates prepared frames and requires a
new explicit Load; applying an unchanged value preserves the prepared frames.
A/B retains configuration, loading progress, position and playback state. Leaving
the job or trajectory mode pauses playback and cancels an unfinished load.

Every numeric field opens a keypad popup that also accepts desktop digits,
Backspace, Enter and Esc. Clicking the current frame opens **Go to source frame**,
which snaps to the nearest loaded sample. Source frame numbers are one-based;
counts use the inclusive requested range. The sample source has 100000 frames.
Invalid values and reversed ranges cannot load. Full trajectory defaults to every
frame; the other sample trajectories begin with 200 selected frames.

At **500 or more selected frames**, Load opens a confirmation popup using the
existing desktop threshold (`TRAJ_FRAME_CONFIRM` in `md_trajectory_presentation.js`).
It shows the exact count, range and interval, with **Edit range / Cancel**,
**Use about 200 frames**, and **Load N frames**. Reducing the count returns to setup
without loading automatically. Large source frame IDs alone do not trigger this
warning: the count of frames to load does. **All frames** makes this flow easy to
review. Background clicks are blocked while either popup is open.

Drag the scrubber to pause and seek; its hover readout shows the full source frame
number. Playback stops at the last sample. These are isolated menu/frame-counter
mockups: no real trajectory download, molecular rendering or simulation action.

The round 4 colour mapper remains horizontal in both A/B variants. It retains
hover-highlighted draggable bounds, per-map ranges, six desktop palettes and the
triple-pulse prompt with desktop Space/mouse emulation. Engine order, job metadata,
occupancy/scope and other visualization suboptions remain unchanged.

**F** front; **O** angled; right-drag orbit; **S** capture. Launcher:

```bash
uv run python -m tools.vr_workflows.component_gallery_tour --component simulations --desktop
```

Round 5 evidence lives under `.development-artifacts/vr-simulation-menu-round5/`.
Earlier rounds are historical. Native build and trajectory model tests passed,
including count/stride arithmetic, the 499/500 confirmation boundary, exact seeking,
invalid input, cancellation and preserving prepared frames on unchanged settings.
Real desktop input passed for both scrubbers, loading gates, playback/stepping,
large-number entry and warning choices, A/B state retention, and horizontal colour
scale retention. All 47 launcher tests and scoped lint passed. Front and oblique
captures were inspected. The review opens at NAMD / R2 Alpine / Trajectory,
awaiting the explicit Load action. `frontend/src/main.js` gained 0 lines in this round.

## Thumbwheel comparison

Columns expose 20%, 35%, or 50% of the cylinder circumference. Rows compare
integer ranges 0–10, 0–100, and 0–1000. Each wheel uses solid trapezoidal ribs,
shaded side faces, and geometry clipping at its panel opening. Occlusion is
explicit, so a transparent menu cannot reveal the wheel's hidden back half.
Larger ranges imply larger hidden cylinders. Radius is compressed logarithmically
(45 / 82.5 / 120 local mm) rather than growing 100-fold; labels report actual
world-space diameters at the menu's normal 0.75 scale (68 / 124 / 180 mm rounded).
Each detent advances one integer for a controlled comparison of range and shape.

Trigger-grab either controller and move up/down; release to coast. The desktop
uses left-mouse drag. Aiming highlights the wheel and, in VR, draws a pointer
beam ending on the raised cylinder. Values clamp to their stated range and stop
momentum at endpoints. **Play demo** automatically flicks each wheel in turn;
manual grabbing interrupts it. **Reset** restores midpoints. **Recenter**
places the VR gallery ahead of the tracked user.

Desktop shortcuts: **F** front, **O** oblique, right-drag orbit, scroll zoom,
**Space** toggle demo, **R** reset, **S** retain image/state, **Esc** close.
Debug's **Stop tour** closes the owned demo. Closing the native window also exits.
Capture output is listed in the Debug status tooltip, under
`.development-artifacts/vr-debug-tours/<run>/evidence/`.

Extrude uses the approved **0–1000 / 35%** geometry (120 mm local radius).
Bend uses **0–100 / 35%** (82.5 mm) for its angle, curvature and direction
wheels. All have 90 mm width and 32 physical ridges. Their numeric units, limits
and inertia remain unchanged; these are geometry presets, not replacement value
ranges. Bend's layout and raised-surface ray targets accommodate the larger wheels.

## Button comparison

Choose **Button styles desktop demo** or **Button styles VR demo** in the same
menu. Six samples share one release-to-toggle action, so differences in geometry,
contrast, depth and feedback can be compared directly:

| Sample | Design reference | Treatment |
| --- | --- | --- |
| Raised slate | [MRTK pressable buttons](https://learn.microsoft.com/en-us/windows/mixed-reality/mrtk-unity/mrtk3-uxcomponents/packages/uxcomponents/button) | Rectangular raised face, rim and sloping sides |
| Soft capsule | [Apple buttons](https://developer.apple.com/design/human-interface-guidelines/buttons) | Light capsule with dark text, inspired by visionOS |
| Filled pill | [Material buttons](https://developer.android.com/develop/ui/compose/components/button) | Purple filled face and rounded ends |
| Outline | [Material buttons](https://developer.android.com/develop/ui/compose/components/button) | Thin outline with minimal depth |
| Operator | [Blender operator buttons](https://docs.blender.org/manual/en/5.0/interface/controls/buttons/buttons.html) | Squared dark face with a compact bevel |
| Round push | [MRTK circular buttons](https://learn.microsoft.com/en-us/windows/mixed-reality/mrtk-unity/mrtk3-uxcomponents/packages/uxcomponents/button) | Circular face with deeper physical travel |

These are original native studies inspired by the references, not platform widget
ports or copied assets. Each supports either controller's pointer and trigger,
or desktop mouse input. Pressing depresses the face; releasing over it toggles
selection and increments its counter. Releasing outside cancels. **Disable**
blocks activation. **Play demo** cycles idle, hover, pressed, selected and disabled
states together across all six; manual input interrupts playback. **Reset**
restores the comparison. Desktop orbit exposes the actual geometry and depth.

## Cards and expandable lists

Choose **Cards and lists desktop demo** or **Cards and lists VR demo** in
**Debug → VR Component Gallery → Component evaluations**. The six studies are
raised card, outlined card, flat disclosure list, exclusive accordion, indented
tree list, and inspector property group.

Click a header (or point and release the VR trigger) to expand or collapse it.
Open content animates into the reserved sample area; collapsed rows cannot receive
input. Select a child to highlight it. The accordion reveals one section's details
at a time; inspector rows demonstrate label/value alignment. Selection persists
when closing and reopening a sample. **Play demo** cycles collapsed, expanded and
selected examples. **Disable**, **Reset**, **Recenter** and desktop view controls
work as in the button gallery. All content is evaluation data; no design is changed.

```sh
uv run python -m tools.vr_workflows.component_gallery_tour --component cards --desktop
uv run python -m tools.vr_workflows.component_gallery_tour --component cards
uv run python -m tools.vr_workflows.component_gallery_tour --component cards --validate
```

## Reproduce

```sh
uv run python -m tools.vr_workflows.component_gallery_tour --desktop
uv run python -m tools.vr_workflows.component_gallery_tour
uv run python -m tools.vr_workflows.component_gallery_tour --validate
uv run python -m tools.vr_workflows.component_gallery_tour --component buttons --desktop
uv run python -m tools.vr_workflows.component_gallery_tour --component buttons
uv run python -m tools.vr_workflows.component_gallery_tour --component buttons --validate
```

Validation uses the real native live input bridge, starting with `steady_fast`
then all remaining motion presets. It resets between profiles, acquires and
trigger-drags one wheel from each exposure/range diagonal, and retains stereo
captures and movement traces. The native `nadoc-vr-component-gallery-test`
checks all nine wheels, release/inertia, range limits, automatic playback, and
front/oblique rendered pixels with an offscreen negative control.
`nadoc-vr-thumbwheel-mesh-test` verifies real raised ribs, cutoff and range scale.

Desktop images and submitted stereo captures establish rendering and input
behavior; physical headset legibility, comfortable scale and preferred exposure
remain human evaluation tasks.

## Validation record — 2026-10-01

- Native gallery: all nine trigger grabs, flick inertia, settling, bounds,
  automatic demo and front/oblique pixel checks pass; offscreen negative passes.
- Four focused native mesh/interaction/Bend tests pass.
- Physical OpenXR session: all four motion presets pass with all 18 wheel regions
  visible per stereo capture. Seven first-attempt acquisitions missed in the
  variable profiles and succeeded on their second attempt. The original failed
  run is preserved: it caught the missing gallery-only render condition and a
  reset acquisition miss. The pixel check correctly rejects all 18 regions in
  that old invisible-gallery capture. No hit sizes or motion thresholds were
  changed to make the rerun pass.
- Frontend suite: 589 files, 7,341 passed, one skipped. Backend tour tests: 33 passed.
- Real Debug-menu desktop launch passed in Playwright; 23 browser smoke checks
  passed. Owned processes, launch files and `__e2e__` workspace parts were cleaned.
- `just lint` and focused workflow lint pass.
- `just test-smart` decision: **FAST**. 9,495 passed, 93 skipped, six failures in
  existing geometry scalar/loop-skip agreement, simulation surface extraction,
  and fixed representation coloring. None of those implementation paths were
  changed by the gallery. Two timing flags disappeared in isolated focused
  diagnosis: status-poll test 0.34 s, cache test 0.94 s setup / 0.01 s call. They
  stub heavy work; no slow markers or budgets were changed.

The broad-suite deferral was:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

Evidence: `.development-artifacts/vr-component-gallery/final-desktop/` contains
front/oblique/offscreen PNGs; `physical-2/` contains stereo pixels and all movement
trials, and `physical-1/` retains the failed attempt. Test summaries are alongside
these directories. Physical through-lens comfort and aesthetic preference are
still tracked under `MV-VR-GALLERY`.

Final desktop review also exercised actual X11 mouse input in the delivered
1920×1080 desktop: dragging the first wheel changed 5 → 7, and Reset restored all
nine midpoints. The final Debug-owned desktop run is
`.development-artifacts/vr-debug-tours/20261001-200529-440a5989/`; it is intentionally
previously left open in the angled view for review (closed for the button evaluation) and can be closed with Esc or Stop tour.
The repeated real-launch check passes in 7 seconds, including graceful cleanup.


## Button evaluation and approved presets — 2026-10-01

- The six-style native gallery passes trigger/release, press travel, cancel,
  disabled activation, front/oblique renders and offscreen negative checks.
- Real OpenXR validation passes all four motion profiles and all 12 button
  regions in each stereo capture. Eleven first acquisitions missed in variable
  profiles; second attempts succeeded. All attempts are retained, with unchanged
  motion profiles and hit geometry. This establishes rendering and input behavior,
  not through-lens comfort.
- Approved wheel mesh tests, Bend controller/layout/preview and ScryWrite unit
  checks pass. The first Bend audit caught four undersized coarse-adjustment
  buttons; their height was corrected to 70 local mm, preserving the 65 mm floor.
  A stale socket from the aborted test prevented its first rerun; a fresh private
  absolute output directory passed. The final Bend panel image includes the
  actual solid wheels next to the readouts.
- Frontend: 7,341 passed, one skipped. Backend tour tests: 34 passed. Both real
  Debug-menu desktop launches and all 23 browser smoke checks pass. Lint passes.
- Broad FAST backend: 9,496 passed, 93 skipped, the same six unrelated failures
  listed above. FULL remains deferred by the test-session scope guard. Nine
  timing flags were investigated individually: all passed below 1.9 seconds total
  on focused recheck. They cover source scans, small geometry with mocked solvers,
  stubbed API/job preparation, local revision stores, catalogue reads, and a fake
  transfer. No slow markers or timing budgets were changed.

Evidence: `.development-artifacts/vr-button-gallery/` contains native front,
oblique and offscreen images; `bend-final/bend-panel.png`; all-four-profile stereo
captures and trials in `physical-1/`; test logs and original timing diagnostics.

The button desktop review is intentionally left open in the angled view under
Debug-owned run `20261001-204313-9cb64668`. Actual X11 mouse input selected Raised
slate and incremented its counter; Reset restored the comparison. The delivered
1920×1080 screenshot is `desktop-delivered.png` in the button evidence directory.
Close with Esc or Debug → Stop tour.


## Card/list validation and cautious resumption — 2026-10-01

The initial overlapping compile and auto-parallel test runs were interrupted by
workstation memory exhaustion. Kernel logs recorded OOM kills; neither interrupted
suite is a passing result. The backend selector chose **FAST** and reported:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

The broad FAST run did not finish, so it has no reliable final pass count. Its
slow-test banner read the previous run's stale candidate report; those nine entries
were already investigated in the button evaluation. No budgets or markers were
changed based on an interrupted, resource-starved run.

Resumed with a single reduced-priority compiler and sequential checks. Native
interaction and front/oblique/offscreen rendering pass for all six card/list
samples. The 35 launcher tests pass; the complete frontend suite passes with two
workers (7,341 passed, one skipped). A single-worker Playwright check opens the
actual card desktop demo through Debug and verifies its six samples; its owned
process and evidence directory are removed in failure-safe teardown.
`frontend/src/main.js` gained **0 lines** for the card/list feature.

Evidence is retained under `.development-artifacts/vr-card-gallery/`, including
the interrupted logs and native render images. Through-lens comfort remains a
human review item in `MV-VR-GALLERY`.

Final card/list validation: all 23 smoke checks and lint pass. All four real
OpenXR controller profiles pass, including exact child-row acquisition, selection
and disabled input. Twelve acquisition misses are retained in `physical-2/trials.json`;
one child required a third attempt. `physical-1/` preserves the initial script
failure, which accepted header hover when seeking a child. Debug telemetry now
exposes `hovered_row` and validation requires the exact child. Geometry and motion
profiles were unchanged.

All 12 header regions pass per stereo capture. Card visibility checks recognize
the actual dark slate header palette in addition to bright text, retaining the
20-sample floor. A blank stereo negative detects zero of 12 controls. Native
front/oblique/offscreen evidence and submitted stereo evidence do not establish
through-lens comfort.

The standalone desktop review is left open with all six samples expanded and the
first child selected, verified through actual X11 mouse input. `desktop-expanded.png`
records the delivered desktop; `desktop-review/desktop-1.json` records its state.
Use Esc to close it. Browser-test processes, owned evidence and workspace test
parts were cleaned. Only this intentional review window remains from validation.

## Scrollable sets (2026-10-08)

Choose **Scrollable sets desktop demo** or **Scrollable sets VR demo** under
**Debug → VR Component Gallery → Component evaluations** (also in VR Tours & Tests).
These are six interactive studies for future feature integration, using isolated
sample data; they do not change saved dimensions, sweep points, or simulation jobs.

| Study | Intended use | Grouping and row controls |
| --- | --- | --- |
| Inset tray | Dimensions and visibility lists | Recessed shared well; visibility and pin buttons |
| Outlined table | Numeric dimensions | Thin enclosing border, aligned values, decrement/increment |
| Job cards | Simulation queues | Individually raised rows inside one queue; pause/resume and pin |
| Sweep rail | Ordered sweep points | Connected point markers; position decrement/increment |
| Grouped set | Related simulation stages | Sticky group context and per-row group stripe; pause/resume and pin |
| Pinned inspector | Select and inspect long sets | Selected item's summary stays below the scrolling rows; visibility and pin |

Each set contains twelve items, with three complete rows visible at once. Drag its
right-hand rail or use **UP/DN**. A persistent range/count shows where you are.
The viewport moves by whole rows, so clipped labels and partially active controls
cannot occur. Selection and per-item changes persist outside the viewport. Actions
have separate targets from selection, activate on release, and cancel on release
outside or tracking loss. Either controller works. **Disable** blocks the six
sets; **Reset** restores sample data; **Play demo** cycles scroll positions and
selection; manual interaction stops it. Mouse wheel remains gallery zoom.

The reusable `ScrollableSet` model owns items, bounded viewport and selection;
`ListGallery` owns the six presentation studies and their example actions.
Adopting a study in a production feature still requires binding its items/actions
to that feature's existing state and persistence.

```bash
uv run python -m tools.vr_workflows.component_gallery_tour --component lists --desktop
uv run python -m tools.vr_workflows.component_gallery_tour --component lists --validate
just validate-safe native/vr_viewer/build/nadoc-vr-component-gallery-test .development-artifacts/vr-list-gallery/render
```

The native check exercises ray selection, independent actions, endpoint bounds,
state retention, outside release, tracking loss, scrollbar drag, disabled input,
and empty/short model bounds. It renders front, oblique and offscreen controls.
Through-lens readability and controller comfort remain in `MV-VR-GALLERY`.

Validation for scrollable sets: native build and interaction/render checks passed;
all six samples passed real X11 desktop selection, independent row action, scroll
and retained-selection checks. Tour catalog tests: **44 passed**. Evidence is in
`.development-artifacts/vr-list-gallery/`, with final front/angled captures in
`desktop-verified/desktop-3.png` and `desktop-verified/desktop-4.png`. Earlier desktop
attempts targeted the window-manager decoration rather than the PID-owned client;
those failed attempts are retained. No saved designs or simulation jobs were
created. Test viewer processes were closed. This run did not exercise OpenXR or
claim headset comfort. `frontend/src/main.js` gained **0 lines**.

Repository lint remains blocked by the existing unused `pathlib.Path` import in
`tests/test_cpd_cube_validation_v6.py:1`; the changed tour test passes scoped lint.

The final desktop review window is intentionally left open; **Esc** closes it.
Its launch record and initial capture are under `vr-list-gallery/review/`.
The extended menu-render-audit target also builds successfully. Retained evidence
is about 2.8 MB; no disposable designs were created in `workspace/`.

## Simulation menu design round 1 (2026-10-12)

Open **Debug → VR Component Gallery → Component evaluations → Simulation menus
A/B desktop demo**. The same desktop-only entry appears in VR Tours & Tests.
This study runs in the established native desktop gallery without initializing
OpenXR or SteamVR. It uses isolated sample data; its options change menu state,
not a live simulation or molecular rendering.

- **A — Inline expansion:** engine buttons select a job list; selecting a job
  expands visualization options immediately beneath it. Neighboring jobs remain
  visible, and selecting the open job closes it.
- **B — Focused detail:** selecting a job replaces the list with its options.
  **< Jobs** returns to the same list page. The engine remains visible.

A/B switching preserves the selected job and per-job visualization settings.
Both offer representation choices, colour cycling, input-reference and RMSF
overlay toggles. These are layout placeholders, not an engine capability matrix.
Names such as **R2 Alpine** appear with date/time. Running jobs show percentage;
completed production jobs show total ns; completed relaxation jobs show a
checkmark. The second page includes queued and failed states with no viewable
result. Reset clears the sample selections while retaining the chosen layout.

```bash
uv run python -m tools.vr_workflows.component_gallery_tour --component simulations --desktop
```

The study builds under `.development-artifacts/vr-simulation-menu-round1/build`
(unless `NADOC_VR_BUILD_DIR` is explicitly supplied), with Archive scratch.
Use **F** for front, **O** for angled, right-drag to orbit, wheel to zoom,
**S** to capture state/image, and **Esc** to close.

First-review questions: Which layout makes selecting a job and returning to the
list clearer? Should the focused view keep any additional job context visible?
Which representation, colour or overlay controls belong in the next iteration?
Desktop review covers navigation and appearance; headset legibility and reach
remain for a later VR round.

Round 1 verification: native build and real X11 mouse checks pass for both
layouts, selection, representation/colour/overlays, A/B state retention, return,
pagination, queued/failed states, per-job persistence and release-outside cancel.
Final front/angled images and state are in
`.development-artifacts/vr-simulation-menu-round1/desktop-final/`; the intentionally
open review window uses `review/` and closes with Esc. No headset was started.
All **47** tour-launcher tests and **24** browser menu/smoke tests pass. Browser
teardown removed its six test artifacts and one project history; post-run checks
found no prefixed designs, new project stores, browser output or credentials.
`frontend/src/main.js` gained **0 lines** for this task.

Broader repository checks are not green: frontend **7,858 passed, 2 failed,
1 skipped** (trajectory warning assertions in the untouched MD jobs panel);
backend **FAST: 10,685 passed, 30 failed, 8 errors, 93 skipped**. The backend run's
initial shell lacked Node; other failures include unavailable scientific assets
and executable permissions. No failure was in the tour-launcher tests. Scoped
lint passes; repository lint reports five unused imports outside changed files.
Full logs are retained in the same evidence directory. The selector reported:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
```

Timing triage: the placement-report subprocess test dropped from 17.22 s to
0.62 s call / 1.12 s setup in isolation. The worker-process check dropped from
5.01 s to 4.25 s using short Archive scratch paths; all eight worker tests pass.
These exercise tiny synthetic data and process lifecycle, not heavy scientific
work. No budgets or classifications changed. Disposable test/compiler/browser
scratch was removed; captures, logs, build and active review scratch are retained.
