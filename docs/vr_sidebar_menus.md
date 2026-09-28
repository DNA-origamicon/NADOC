# VR sidebar menus

Each controller's menu button independently toggles its matching sidebar. Both
can remain open. Tabs preserve desktop order, labels, dark backgrounds and blue
active styling; their text runs vertically on the outside edge. Controls are
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
With a menu open, click its trackpad to enter focus navigation; up/down moves
focus, left/right switches tabs, and the same trigger activates. When the scrollbar
is focused, up/down pages the content while retaining focus; left/right leaves the
scrollbar for the last row or Close button. No trigger is needed to scroll.
A short tab has a gray, inactive scrollbar. Center-click
returns to pointing, as does moving the ray away and then aiming steadily at a
button for 450 ms. See [UI style and input standard](vr_ui_style.md).

Card titles use the desktop's section names and nesting. Point at a title and
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
