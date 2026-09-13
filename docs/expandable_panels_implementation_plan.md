# Expandable controls implementation plan

Selected approach: option 2, revised by user feedback to side-by-side sidebar instances over a shared scene.

## Revised checkpoint 1 — approved layout

Each left rail click appends another full-height sidebar from left to right, including duplicate tab types. The right sidebar now mirrors this behavior: new columns grow inward from the right edge, with its rail immediately to the left of the stack. Duplicates share one controller/state and have independent scrolling and draggable widths. Each sidebar has an X at its top right. The left rail stays at the left stack's right edge. Headers use subtle purple (Feature log), blue (Simulations), green (Animation), yellow (Appearance), and neutral (Plates & tubes) accents. Strip buttons match. Right-side headers and buttons use purple Assembly, blue Visualization, green Clustering, yellow Overhangs, and neutral Properties.

New panels are refused when the available width cannot accommodate their minimum width. A 320px viewport reserve and the opposite sidebar stack/strips are excluded from that budget. Resizing is clamped; on window shrink, columns narrow before excess newest columns are closed with a notice. Closing/hiding controls never turns lighting or playback off. Left layout preferences migrate from v1/v2 to v3; right preferences migrate from v1 to v2 and retain duplicate types and individual widths.

Detached browser controls were requested as an assessment only. See `docs/detached_controls_feasibility.md`; no popup UI is implemented.

The original staged scope below remains, but its stage-1 accordion layout is superseded by this revision.

## Invariants

- Opening, focusing, collapsing or hiding controls does not change applied lighting, simulation geometry, coloring or playback.
- Explicit user actions control scene state. Document close/change still performs lifecycle cleanup.
- Displayed physical positions never become authored topology or geometry.
- Automated tests use synthetic designs and mocked trajectories, not filenames or contents from small_plate.nadoc. That real file is a manual diagnostic example only; do not modify it as part of validation.
- Part and assembly hosts retain the shared controls.

## Stage 1 — shared sidebar stack and explicit lighting

Implement full-height sidebar columns with independent widths and scrolling,
retained rail shortcuts, accessible close/resize controls, shared duplicate
views, saved layout preferences, and migration from the old active-tab/accordion
preferences. Keep scene ownership independent of controls visibility. Document
close/change still performs lifecycle cleanup. Internal navigation focuses an
existing sidebar; explicit rail clicks append a copy.

Keep simulation job/setup content together for this layout review. The timeline
remains in the Animation column until the layout and next-stage needs are reviewed.

Validation: shared-view identity/actions/property synchronization, width budget,
sidebar lifecycle and display policy unit tests; synthetic-design browser exercise;
complete frontend tests; build/lint; smoke/teardown checks. Inspect the rendered
canvas and both duplicate panels.

**Checkpoint 1 — user validation, before stage 2:** Open any design
(small_plate.nadoc is a useful example). Open Appearance twice; scroll each to a
different area, resize one, and change lighting from each copy. Close one with X,
then hide/reopen the stack. Open Simulations and Animation, inspect their subtle
header colors and the strip at the right edge. Try adding panels until the width
limit is reached. Repeat duplicate editing, scrolling, resizing and closing with right-side Visualization columns. Confirm the right rail stays at the left edge of its stack and neither stack crowds the viewport. Check Properties tools and assembly-only controls remain usable. No simulation/export
fidelity claim at this checkpoint.

## Stage 2 — simulation display and animation ownership

Separate simulation results/display controls from job setup where this reduces navigation. Add useful collapsed-state summaries (selected source/frame and animation status). Position the timeline below the viewport if checkpoint 1 confirms that layout. Replace remaining legacy tab lifecycle assumptions with explicit display/playback ownership. Pause independent live/trajectory clocks when the animation takes ownership, not when a panel opens. Make camera-only motion retain simulation geometry. Define behavior for mixed authored-geometry and simulation segments. Snapshot and restore incoming display state on stop/cancel/failure.

Validation: synthetic controller tests for every supported engine, camera-only geometry preservation, clock ownership and restoration; browser tests with generated trajectories; part/assembly checks.

**Checkpoint 2:** Display a real result, choose one frame, enable lighting and create a camera move/spin. Scrub, stop, restart and collapse controls. Confirm the displayed shape and metric colors remain correct and Stop returns to the incoming view. Report frame/job/representation details for failures; no fixture-specific assertions.

## Stage 3 — consistent preview and export

Route animation export through the selected rendering settings, avoiding divergent raw/photo behavior. Persist the supported presentation settings with animations so reopening is reproducible. Define frame/trajectory sources and companion/legend settings explicitly. Confirm capture settles all owners before each frame and restores state on completion/cancellation/error. Additional engine timeline adapters are implemented according to their available trajectory data rather than inferred from painted overlays.

Validation: synthetic trajectories, decoded GIF/WebM frame comparison, rendering/overlay checks, save/reload and cancellation/cleanup tests. No hard-coded real-file dependency.

**Checkpoint 3:** Export a lit still-frame camera animation and a lit trajectory. Compare decoded output to preview; check colors, legends, ions/box, framing and the scene after export.

## Stage 4 — real-file usability and final regression pass

Exercise the agreed workflow with small_plate.nadoc as a manual example and a representative assembly. Address actual usability findings, update labels/help, and remove obsolete tab-driven code/comments. Run the relevant full regression checks and document remaining limitations.

**Checkpoint 4:** User completes simulation result → appearance → animation → export without needing to reopen controls to reactivate a feature. Confirm panel density, keyboard focus, sidebar resize, saved settings and final output.

## Progress

Revised stage 1 is implemented and its layout has been accepted. The requested
sidebar refinements and default animation are included. Stages 2–4 remain
outstanding, with their validation checkpoints retained.

Verification (2026-09-11):
- `just test-frontend`: 403 files, 6,305 tests passed.
- Final focused shared-view/sidebar/display-policy run: 31 tests passed.
- `just lint` and frontend production build passed.
- Generated-design stack browser test passed: native lighting edits in a duplicate,
  synchronized values, independent scroll and drag-resize, capacity rejection,
  closing a copy, and lighting persistence through hide/show. Screenshot inspected.
- `just smoke`: 22 passed; assembly fixture setup returned 404 before the teardown
  test could run. The smoke backend also logged the previously observed mrDNA
  job-status temporary-file race. The isolated assembly retry passed (1/1).
- `main.js` LOC delta for this revision: 0 (two existing navigation calls changed).
- No edits to small_plate.nadoc. Tests do not depend on it.
- Generated workspace fixtures and Playwright output directories were cleaned up.

Known limits: job setup and display still share a Simulations column; the timeline
remains inside Animation; independent simulation clocks, animation geometry
ownership, state restoration and unified exports remain stages 2–3. Shared views
reuse one controller/live DOM tree per tab and mirror changed DOM nodes, form
properties and canvases into the other views. The real-file review should include
native inputs, dynamic job lists, plots and plate canvases across duplicate views.
This is not a detached-window implementation.

### Right-side stack and matching rail colors (2026-09-11)

Both sides now share `ui/sidebar_stack.js`. Right-side columns grow inward with
individual widths, scrolling and close buttons; copies share their original
controllers. Opening another right column leaves Dimensions active while
Properties remains open. Contextual Primitives/Orientation controls live in
Properties and reveal it when activated. Assembly columns are removed on exit
from assembly mode. Detached controls remain unimplemented.

Verification: 403 frontend files / 6,307 tests passed; production build and lint
passed. Both generated-design browser stack tests passed and their screenshots
were inspected. The initial browser run encountered the known fixture-creation
404 on the left; the right test incorrectly closed automatically opened
representation options, which was corrected before the successful rerun.
Smoke: 22 passed, with the known assembly fixture-creation 404; the isolated
assembly teardown retry passed (1/1). Generated fixtures and Playwright output
were removed and absence verified. `main.js` LOC delta for this addition: 0.

### Default animation (2026-09-11)

An empty loaded design, assembly or embedded part context receives a real empty
`animation 1` through its existing animation API/part patch path. It is selected
by the Animation controls and persists with the document on save. Existing
animations are preserved. Initialization runs once per context per frontend
session, so duplicate sidebars do not create duplicate defaults, and deleting the
last animation does not immediately recreate it. Reloading an empty document
creates the default again. Initialization failures are reported without a retry
loop. Additional animations use the same lowercase numbered naming convention.

Stage 1 layout was accepted by the user. Stages 2–4 (simulation ownership,
preview/export consistency and real-file fidelity review) remain outstanding;
this delivery does not claim to fix those audited playback/export gaps.

Final delivery verification: 404 frontend test files / 6,311 tests passed;
production build and lint passed; the default-animation/sidebar browser check
and assembly teardown passed (2/2), with the rendered screenshot inspected.
`NADOC_E2E_API_BASE=http://127.0.0.1:8001 just smoke` passed all 23 checks against
the dedicated smoke backend. Test fixtures and Playwright output were cleaned.
No small_plate.nadoc edits or fixture-dependent assertions. Overall `main.js`
LOC delta for this delivery: −4; the default-animation addition changes it by 0.
