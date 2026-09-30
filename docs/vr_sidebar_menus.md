# VR sidebar menus

The left-hand **VR** tab contains **View desktop** and **Exit VR**. View desktop
opens a separate, world-fixed X11 desktop window. Hand-menu buttons only toggle
hand menus; the desktop remains open at its own position and scale. Grab its
outer border to move it, or grip opposite borders with both hands to resize.
The **Close** button and title are above the desktop image, outside its mouse
hit area. No menu controls cover desktop pixels.

Aim at the desktop and lightly pull Trigger (starting at 15%) to show a circular
3× magnifier at the pointer. A full trigger click selects the desktop location
at the lens center; release removes the lens. The pointer has an open center so
it does not obscure the click target. Swipe the touchpad vertically to scroll.
The desktop panel uses the same full-click threshold/hysteresis as other VR
controls. Scripted control/witness sessions inject neither OS pointer motion nor
OS clicks. Physical mouse interaction still needs a normal controller session.
Exit VR uses normal OpenXR shutdown, leaving the browser and SteamVR running.
This X11 capture path does not depend on SteamVR's Desktop tab.

Trajectory, job-list and tool-menu Back buttons return to the current sidebar
and selected tab, preserving placement. Earlier desktop Back-button evidence
under `.development-artifacts/vr-menu-return-final-20260930/` describes the
superseded embedded tablet. The detached desktop has an external Close button.
The old detail-panel ray-placement fix remains in place.

September 30 validation: the generated catalog and three native tests pass.
`just vr-menu-tour --tab left:vr --preset steady_fast --validate --exit` exercises
the new tab and native desktop capture with all four motion profiles. Retained
passing results and mirror checks are under
`.development-artifacts/vr-desktop-tab-review-20260930/`. Native eye images show
the captured X11 desktop. A separate diagnostic temporarily minimized the mirror
and showed VS Code and the GNOME dock inside the tablet; its final monitor
comparison failed after restoring the minimized window, so that attempt is not
an overall pass (`vr-desktop-tab-visible-20260930/`). The normal workflow leaves
the mirror visible and can therefore capture its own image recursively. These
are submitted-eye observations, not physical headset or mouse-click validation.

A floor grid follows SteamVR’s calibrated floor, with a cyan outline of its
play-area rectangle. Neither moves when the molecular model is moved or scaled.
See [VR room appearance](vr_room_ui.md) for the demo and runtime fallback behavior.

The left **Simulations** tab has desktop-order engine tabs, a scrollable Jobs card,
and a rightward Visualizations extension after job selection. Both lists support
the same touchpad focus/Trigger and pointer controls described below. The result
extension has its own scrollbar. See [VR simulation results](vr_simulations.md)
for job-specific options, the `2hb_1xT` demo and validation limits.

Each controller's menu button independently toggles its matching sidebar. Both
can remain open. Menus have translucent white backgrounds that blur the scene
behind them, with sharp text and blue active styling. Tabs preserve desktop order
and labels; their text runs vertically on the outside edge. Controls are
larger for ray selection. The wide framed border has textured corner handles and
side grip marks. Bring a controller within 7.5 cm of an edge: the nearest frame
highlights blue. Hold one **Grip** to move (amber frame), add the other controller's
**Grip** at another edge to resize (green frame), and release to set the panel.
Grab feedback includes haptics and a status label. The grip frame sits outside
the buttons, tabs and scrollbar. You can also use
**Dock / Follow**. Scrollbars mirror each other: left of the left menu content,
right of the right menu content. Use the vertical scrollbar: point and hold the trigger to
position its thumb, or swipe the trackpad while pointing at a panel. Buttons have
rounded borders, subtle blue accents for enabled actions, and a muted red Close
button; unsupported controls remain gray. The right-trackpad Tools shortcut remains available when the right menu is closed.
With a menu open, click its trackpad to focus the pointed-at control (or the active
tab when pointing away). A directional click also moves focus immediately. Moving
down past the last visible item reveals the next row with a 200 ms smooth scroll;
up reverses this at the top edge. This also applies to simulation jobs and views. Up/down stops at the ends of the current column; it never
wraps or crosses into another column. Left/right moves spatially between tabs,
scrollbar, and content (mirrored on the left menu), or between buttons on the same
row. Trigger activates the highlighted control, including tab changes. When the scrollbar
is focused, up/down smoothly advances one row while retaining focus; left/right leaves the
scrollbar for the nearest row or tab at the entry height. No trigger is needed to scroll.
A short tab has a gray, inactive scrollbar. Center-click
returns to pointing, as does moving the ray away and then aiming steadily at a
button for 450 ms. See [UI style and input standard](vr_ui_style.md).

Card titles use the desktop's section names and nesting. Children are indented
slightly for each level of ancestry, including nested category titles. Point at a title and
pull the trigger, or focus it with the matching touchpad and pull that trigger,
to collapse or expand it. `+` means collapsed and `-` means expanded. Titles remain
usable even when every child control is unavailable. Hidden children are removed
from pointer targets and touchpad navigation; the scrollbar updates to the visible
content. Each card remembers its state across tab switches and menu closing within
the current viewer session, including nested cards. Cards start expanded for discovery.

| Hand | Tabs, in order |
| --- | --- |
| Left | Feature Log, Simulations, Animations, Appearance, Plates & tubes |
| Right | Assembly, Properties, Visualization, Clustering, Overhangs, Annotations, Tools |

The generated [inventory](../native/vr_viewer/sidebar_catalog.json) records every
mapped control, its desktop source, source hashes, options and native action. Static controls
come from the desktop DOM after the actual right-sidebar relocation and simulation
card-order code runs. Section IDs and ancestor lists preserve repeated titles as
independent cards.
Data-driven widgets use explicit control templates: the inventory does not copy
someone's jobs, annotations, configurations or plate contents. Advanced desktop
controls and dropdown choices remain reachable by expanding their cards and
paging, even where the desktop normally hides them. This is a control mapping, not an editable copy of
the desktop forms.

Unsupported controls are gray and consume clicks without executing an action.
Implemented controls include representation, coloring, recentering, job and
trajectory panels, and existing native tools. Tool availability follows the
current selection; trajectory playback requires a loaded trajectory. Tools also
provides **View / selection controls**, **Tool settings / Confirm / Cancel /
Undo**, and **Desktop**, retaining the existing detailed native panels.

## Live review

With SteamVR and the headset available, run from the repository root:

```sh
just vr-menu-tour
```

This starts an isolated native viewer with an empty fixture, raises/enlarges its
desktop mirror, opens both menus, and uses ScryWrite controller input to open
every tab and scroll every page. It uses the imprecise `variable_fast` human
motion preset by default. Each page pauses for 1.5 seconds. Menus remain open
at the end; Ctrl+C closes the owned viewer. No design is saved or submitted.

```sh
# Complete automated coverage with all four unchanged human-motion presets:
just vr-menu-tour --validate --hold 0 --exit
# Exercise border movement, two-hand resizing, release and visible feedback:
just vr-menu-tour --grip-checks --validate
# Exercise collapse/expand with pointer and touchpad on both hands:
just vr-menu-tour --focus-checks --validate
# Short visual preview, only the first page of each tab:
just vr-menu-tour --quick
# Check that checked-in mappings still match desktop source:
just vr-menu-catalog-check
```

Artifacts go to `.development-artifacts/vr-sidebar/tour-<timestamp>/` (or
`--output <new-directory>`). Each page retains stereo images, the mirror,
ScryWrite state and pixel checks. Trials retain noisy reaches and retries;
`result.json` records completed presets. The final desktop check compares the
actual owned X11 window with the submitted-eye mirror. It samples the desktop
during native capture encoding to avoid comparing different moving-head frames.
The 95% pixel agreement threshold is unchanged; per-sample scores are retained in
`desktop/desktop-check.json`. Failed desktop pixels are never saved.
If desktop verification fails, interaction results remain available and the viewer
stays open for review unless `--exit` was requested. The command still returns a
nonzero status when that review ends. Failed runs keep their evidence. `--socket` can target an existing isolated ScryWrite control session;
never run two input producers against the same session.

The checks verify catalog coverage, layout, disabled behavior, controller
acquisition, visible text, gray disabled controls and blue active controls.
They do not establish through-lens legibility or physical headset comfort.
For desktop changes, regenerate with
`node frontend/scripts/generate-vr-sidebar-catalog.mjs`; review the dynamic
control templates when their source modules change. Source hashes make such changes visible to the drift check.

### Controller dimensions

Select **Dimensions** (or **Measure**) under right-hand Properties to enter the
focused measurement panel. Both sidebars are hidden, preserving their tabs and
scroll positions. A cyan line follows the two controller tips; its live label is
in nanometers. Each trigger pins or recalls its corresponding endpoint. Amber
endpoint markers indicate pinned ends. Menu and entry controls consume triggers
before the measurement tool, so activating an icon never pins an endpoint.

**New dimension** freezes and retains the previous line. The list provides the
desktop eye/eye-off and delete icons; select a row to edit that dimension. Its
endpoints stay pinned until recalled. Either controller's menu button, or the
main **Dimensions – Return to menus** button, restores the sidebars and freezes
the current line. Clear all removes the session's measurements. Measurements are
stored in the active document and included in normal desktop saves. Placed measurements appear in the desktop Dimensions list; saved measurements load into VR at launch.

Model grip movement and two-hand resizing carry all measurements with the model.
Beginning a model grip also pins any live endpoints. Presentation scaling changes
the line's displayed size, not its molecular length. Tracking loss preserves the
last valid endpoint until tracking resumes. Panel grips retain their usual move
and resize behavior.

Run `just vr-menu-tour --dimension-checks --validate` for a live review of entry,
controller pin/recall, model movement/resizing, icon controls and both exit routes
under all four controller-motion presets. Add `--exit` for automatic cleanup.
The Dimensions, New, and Clear controls stay visible while the entries scroll;
new measurements automatically come into view. Focus the list scrollbar with the
trackpad, then click up/down to scroll its entries.

The dimension tour separates measurement and menu phases. It derives a workspace
beside the full menu frame, checks controller rays and input ownership before
endpoint triggers, and freezes newly created lines there before resuming menu
navigation. Each profile starts with a clean measurement list. Clearance evidence
is recorded in `measurement-clearance.json`; controller motion profiles are unchanged.

## Debug tour launcher

Open **Debug → VR Tours & Tests → category → demo/validation** on the desktop.
Nested menus organize every sidebar tab plus controls/layout, Dimensions, and
Tools/authoring. Click a final entry to launch directly; descriptions are tooltips.
Demo uses `steady_fast`; validation uses all four profiles. The quick overview
is explicitly partial coverage. **Stop tour** closes the owned viewer; status and
its tooltip retain the outcome, evidence path and recent output. Closing menus
leaves the run active. Backend shutdown closes its owned run. Active viewers or
tours block another launch under the same workstation-local access policy.
The legacy authoring entry remains disabled with its prerequisite in the tooltip.
Evidence lives beneath `.development-artifacts/vr-debug-tours/<run>/`.

**Right sidebar → Visualization demo** snapshots the currently open individual
design, including unsaved changes, without saving or changing the original.
It closes the left sidebar, moves the right menu aside using its grip, and uses
an enlarged isometric view. Submitted-eye checks require visible, unclipped model
pixels and separation from the right menu before switching and after each switch.

Focused command-line example:

```bash
just vr-menu-tour --tab right:properties --preset steady_fast
just vr-menu-tour --tab left:photo --validate --hold 0 --exit
```

## Adding future tours and tests

This is a standing user requirement for future VR development sessions.

1. Create or extend a reusable workflow alongside the VR behavior it exercises.
   Keep focused software regression tests as well; menu entries represent useful
   demo/validation workflows, not a button for every individual unit assertion.
2. Register the workflow in `tools/vr_workflows/tour_catalog.py`. Give it a stable
   ID, clear title, accurate coverage description and the category corresponding
   to its desktop sidebar tab or shared interaction. Add a category only when an
   existing one does not fit. Per-tab page tours are generated from the sidebar
   catalog; regenerate/check that catalog when adding desktop tabs.
3. Supply demo and validation arguments in `arguments()`. Preserve steady_fast
   for initial demos and all four unchanged profiles for interactive validation.
   State partial coverage and prerequisites explicitly. Do not label a unit-only
   check as physical headset or rendered-pixel validation.
4. For direct launch, accept `--output`, isolate test documents/viewers, refuse
   conflicting sessions, and clean up owned inputs/processes on interruption.
   Use the existing named-workflow launcher, status and Stop controls. If special
   setup prevents direct launch, register a terminal-only card with the command
   and prerequisite explanation so the workflow is still discoverable.
5. Update catalog/launcher tests as appropriate. Exercise the new category/card,
   command, mode and error/stop behavior in the desktop app; validate the workflow
   itself at the scope required by the change. Retain evidence under
   `.development-artifacts/` and verify disposable test files are removed.
6. Update the relevant VR documentation/current-state memory with the menu route,
   coverage, results and any remaining physical validation debt.

## Representation loading benchmark

**Debug → VR Tours & Tests → Right sidebar → Visualization demo**
runs all 110 directed transitions among Hull, Cylinders, Beads, Full, Surface,
VDW, Ball & Stick, Stick, mrDNA Coarse, mrDNA Fine and oxDNA.
VDW and Beads share source geometry with Ball & Stick and Full; meshes and
coarse-grained previews reuse the desktop builders. Validation repeats all
transitions with all four controller profiles (440 switches).
**Right sidebar → Representation colors** provides a shorter cycle through all
eleven styles and both coloring pages, with disabled-control pixel checks.
Demo uses steady_fast; validation runs all four controller profiles. The open design
is snapshotted read-only, including unsaved edits. CLI defaults to `24hb_0xT`;
use `--design PATH` for another file. Each run owns a private snapshot, viewer and native style responder;
it measures renderer application separately from controller approach time and does
not include the browser polling/desktop rebuild delay. Evidence includes export and
load timing, per-transition style metrics, submitted stereo images, design-pixel
coverage, desktop verification and controller trials.

```bash
uv run python -m tools.vr_workflows.representation_tour
uv run python -m tools.vr_workflows.representation_tour --validate
# Short visual pass, including both coloring pages and disabled-control pixels:
uv run python -m tools.vr_workflows.representation_tour --cycle
```

Visualization tours retain a content-addressed export cache under
`.development-artifacts/vr-scene-cache/` (at most two entries / 2 GiB).
It survives viewer and backend resets, but design edits, exporter/template code
changes or dependency updates invalidate reuse. Each hit verifies the complete
snapshot checksum. Run snapshots are immutable hard links when possible and remain
valid after cache eviction; retained run evidence has its own lifetime.
`export.json` reports `cache_hit` and preparation time; `loading.json` reports
`startup_to_live_ready_s` including preparation and viewer startup. A new or changed
design still pays the full export cost. The native loader prewarms the complete catalog, including the surface mesh.
Use `--no-cache` for a fresh-export benchmark without reading or populating the cache.
The Debug Visualization demo/validation entries use caching automatically.

For paired native renderer comparisons, reuse the same previously exported v15 asset (older four-representation snapshots
do not contain the complete catalog):

```bash
uv run python -m tools.vr_workflows.representation_tour \
  --snapshot .development-artifacts/vr-all-representations/steady/scene.nadocvr \
  --output .development-artifacts/vr-representations/new-comparison --validate
```

Static representation geometry and ownership indexes are warmed before interaction.
GPU buffer caches retain one coloring per representation, and only apply with no
live positions/colors, expansion, edit transforms or selection highlights. Baked
edits invalidate the caches. Dynamic trajectories retain their existing update path.

### View volumes

The Visualization **View Volumes** title opens a list like Dimensions, with
Square and Hex creation buttons and per-volume outline, enable, and delete
controls. Return or the controller menu button restores the prior sidebars.
Creation uses a centered 20 cm viewer-space volume. Bring either controller
within 7.5 cm of its centroid to highlight the center marker, then hold Trigger
to move and rotate the volume. While holding the center, bring the other
controller within 5 cm of a face to highlight it; hold that Trigger and move
along the face normal to resize. Resizing is symmetric about the held centroid.
Box faces change one dimension; hex side faces change the regular hex radius
and end faces change length. Ranges use physical metres, independent of scene
zoom. Release the second Trigger to resume rigid movement, or the first to
release the volume. Grip continues moving/scaling the scene and rebases the
trigger anchors so the volume stays attached to the part during scene movement. Disabled volumes retain editable outlines, drawn
gray in VR; hiding an outline is independent of enabling its representation.

Part volumes are shared metadata in `.nadoc` files. Native controls use an
acknowledged, document-bound journal, preserving unrelated desktop changes.
Trigger edits stream through the same journal, with an immediate final write
on release. Older feed snapshots cannot overwrite an active or unacknowledged
drag. Hidden outlines have no grab targets; disabled but outlined volumes remain
editable. Tracking loss ends the grab and requires a fresh trigger press.
The live feed imports desktop additions, transforms and switches into VR, and
the desktop polls native edits and schedules normal workspace autosave. New
unsaved parts still require their first Save. Assembly volume management is
not enabled. Native rendering in this change shows volume outlines; per-volume
representation rendering continues through the existing desktop renderer.

Tests cover rotated box/hex outline coordinates, journal replay, invalid and
wrong-document writes, desktop field patches, part-file reload, pagination,
outline visibility, and live desktop record discovery/deletion. The trigger
workflow adds all box/hex faces, controller rotation, two-hand resize, scene-grip
coexistence, tracking loss and submitted-eye highlight checks. See
[trigger-grab validation](audits/vr_view_volume_grabs_20260927.md).

### Extrude

Tools → Extrude opens a dedicated right-sidebar panel and an adjacent lattice
painter. Return, Confirm and Cancel remain visible while scrolling length
(7/21 bp for honeycomb; 8/24 bp for square), direction, source plane, strand filter, ligation,
painter recall, freeform placement, Frame model and Undo. The displayed lattice
comes from the part. Confirm is enabled only for the current validated draft;
Undo follows the existing transaction acknowledgement. Frame model and Return
work without navigating through the legacy tool menus.

Native view volumes now use their saved representation, color and opacity to
render a clipped layer inside each enabled box or hexagonal prism. Overlapping
volumes remain independent layers. Hidden outlines do not disable the layer.
The global representation remains outside the volumes; moving a volume changes
its clipping transform without editing the design geometry.

The Extrude length controls use paired minus/plus buttons: 7 and 21 bp steps
for honeycomb, 8 and 24 bp for square. Labels and actions follow the part lattice. The length
thumb wheel belongs to the lattice window and follows its pose/size. Grip inside
the painting grid with both controllers to zoom the lattice; border grips retain
window movement/resizing. Interior grips acquire within 9 cm in front or behind
the panel, excluding the border grab zone. Yellow/green contact crosses indicate
available/held interior grips. See the [control audit](audits/vr_lattice_controls_20260928.md).

Assembly visibility follows document context: Part sessions omit Assembly from the
right-hand tabs and controller navigation. The native viewer currently launches
Part sessions only; future assembly hosts must explicitly pass assembly context
to the sidebar. Properties remains the initial right-hand tab in either context.

September 30 appearance regression: commit `a5eb541e` (September 29, 21:38 MDT)
removed the Quick Expand accent entry while retaining a 15-element array. The
remaining 14 initializers left an empty-key/black entry; substring matching
selected it for every otherwise-unmatched button, bypassing danger, tab and
fallback accents. The table now infers its size with `std::to_array`. Regression
checks cover Close, Visualization tab and an unmapped representation button.
The 19:56 reference is
`.development-artifacts/vr-motion-shadows/run-motion-native/native/steady_fast-scroll-before/left.png`.
Pre-fix runtime comparisons are retained under
`.development-artifacts/vr-appearance-investigation-20260930/`.
Comparing only against the 23:01 commit missed this earlier regression. Font
source and sidebar text drawing are unchanged across the reference interval;
the reference and current diagnostic both report sidebar scale 0.65. These
facts do not establish physical-headset legibility or explain a separately
reported apparent font-size difference.
The rebuilt viewer restores colored outlines/tints in
`vr-appearance-investigation-20260930/accent-fixed-initial/steady_fast/right-visualization-0/left.png`.
Native sidebar tests pass (957 controls); Visualization stereo pixel checks
pass under all four motion presets in `accent-fixed-final/`. The initial
desktop-mirror comparison passed, but the final run's desktop comparison failed
(matching fraction 0.018); retain that failed result rather than claiming full
desktop-delivery or physical-headset validation. No pixel thresholds changed.

The user confirmed the accent fix also resolved the apparent font-size change;
no font-size adjustment was needed. The accent fix is committed and pushed as
`63caa1d1`.

Detached desktop initial evidence is retained under
`.development-artifacts/vr-desktop-detached-20260930/`. The first `initial/` run
passed input assertions but revealed a blank desktop when both hand menus closed;
`visible/` corrects the render condition and passes stereo lens-rim checks (with
released-trigger negative controls) and the desktop mirror comparison. The
probe minimizes only its owned mirror for X11 desktop observation, then restores
it before the final monitor check. These captures do not establish physical
headset comfort or actual OS click delivery.

Final detached-desktop validation: all four motion profiles passed the separate
panel, grip movement, two-hand resize, external Close, partial/full/released
trigger states, and stereo lens-rim positive/negative checks in
`vr-desktop-detached-20260930/final/`. The magnifier capture shows actual VS Code
text enlarged inside the lens. Three native regression tests passed. The final
monitor comparison failed after restoring the minimized mirror (0.0119 matching
fraction), while the earlier `visible/` monitor comparison passed; the final
run therefore is not an overall desktop-delivery pass. No thresholds were relaxed.

Remote borders (September 30): the desktop Close button is now above the outer
VR frame with a visible gap, not merely outside the captured image. Its chrome
has separate render/hit bounds; the desktop image and border bounds remain
independent. Controller sidebars initially use scale 0.45 at 0.60 m forward
(previously 0.65 at 0.95 m), with centers 0.24 m either side and 0.10 m below
the eye. A user-selected size survives reopening.

Aim at any interactive window border and hold Trigger to move it around the
head at its current radius. Release fixes it in space. Quickly trigger twice
and hold the second pull to resize by sweeping outward/inward from the window
center. The shared handler covers both sidebars, desktop, View tools, legacy
tool/trajectory/job panels and the lattice window; ordinary nearby grips remain
available. The nearest whole panel blocks border hits behind it. Tracking loss,
dashboard focus loss and panel closure release the gesture. Scale range is
0.25–8.0 and panel ray reach is 30 m, allowing large distant windows to remain
accessible. Frame feedback uses blue hover, amber movement and green resize.

Remote border targets include an outside-only margin of at least 5 cm, so
smaller nearby windows tolerate hand tremor without expanding into their
buttons. Overlapping margins defer to actual foreground content, then the
nearest rail. External desktop chrome, including Close, is excluded from the
margin. A ray endpoint and colored frame show which border will receive a click.

Remote-border validation is retained in
`.development-artifacts/vr-remote-borders-20260930/final-pass/`: all four motion
profiles passed both hands, fixed-radius movement, center-fixed resize, unchanged
scene/tab, stereo frame-color checks and final monitor delivery. Five focused
native tests and the automatic-build budget regression test also passed.
Earlier failed runs remain alongside it. No motion-noise presets or pixel
thresholds were relaxed: corrective aims use observed ray error, and gesture
completion uses observed movement/size feedback. The desktop probe uses the
same corrections after its first four-profile run missed a rail in variable_fast.
Restoring the owned mirror now requests normal EWMH activation, resolving the
previous covered-window monitor comparison failure without changing thresholds.

Final desktop validation passed all four profiles plus the final monitor
comparison in `vr-remote-borders-20260930/desktop-feedback-final/`: independent
panel persistence, nearby grip movement/two-hand resize, remote trigger movement
and resize, partial-trigger lens pixels with released-trigger negative controls,
and external Close. The native desktop stereo capture visibly separates Close
from the outer frame. Acquisition allows up to six measured corrective aims;
`desktop-verified/` retains the slow/noisy miss with the previous three-attempt
budget after cumulative panel enlargement. This verifies rendered stereo and
monitor delivery, not physical headset comfort or OS click injection (disabled
for scripted tests). Validation ran without builds overlapping VR sessions;
available memory stayed around 14 GiB.
