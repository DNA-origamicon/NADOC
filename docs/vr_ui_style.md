# Native VR UI style and input standard

Reviewed against primary sources on 2026-09-27. The implementation uses native
OpenGL panels; Unity prefabs are references, not drop-in dependencies.

## Sources and reusable assets

| Resource | Useful material | Fit for NADOC |
| --- | --- | --- |
| [Microsoft mixed-reality buttons](https://learn.microsoft.com/en-us/windows/mixed-reality/design/button) | Focus/press feedback, shared opaque backplates, distance-aware targets | Interaction and visibility reference |
| [Meta component guidance](https://developers.meta.com/horizon/design/components/) | Button variants, panel structure, UI Set links for Figma/Unity/Spatial SDK | Reference for states and consistency; platform-specific components |
| [MRTK3](https://mixedrealitytoolkit.github.io/MixedRealityToolkit-Unity/) | UX components and design toolkit | Open-source reference; current repository is [BSD-3-Clause](https://github.com/MixedRealityToolkit/MixedRealityToolkit-Unity/blob/main/LICENSE.md), not the older MRTK MIT assumption |
| [Material Symbols](https://developers.google.com/fonts/docs/material_symbols) | Filled/outlined SVGs and adjustable weight | Best candidate for a future filled icon atlas; Apache-2.0 |
| [Lucide](https://lucide.dev/license) | Consistent simple outline icons | Alternative for desktop continuity; ISC, with inherited Feather icons under MIT |
| [Kenney UI Pack](https://kenney.nl/assets/ui-pack) | Free buttons, panels and control graphics | CC0 prototyping assets; not specifically VR-tested |

No third-party assets or SDKs are bundled by this change. Native geometry keeps
borders crisp under resizing. An eventual icon atlas should import only needed
icons and retain the relevant license notices.

## Local style rules

These are NADOC defaults informed by the references, not a universal VR standard.

- **Panels and lighting:** use one opaque dark backing per menu. Keep text and
  controls unlit, independent of molecular lights and shadows. Avoid transparency
  behind labels. Distinguish panel depth from control feedback; a scene shadow
  must not imply that a disabled control is interactive. Microsoft recommends
  opaque/shared button backplates for legibility and grouping. [Source](https://learn.microsoft.com/en-us/windows/mixed-reality/design/button)
- **Borders and states:** neutral thin borders at rest, an inset blue hover ring,
  blue fill for selected values/tabs, and an amber inset ring plus a mode label
  for trackpad focus. Focus does not mean activated. Disabled controls retain
  muted text/borders even when focused. This follows the separation of hover,
  pressed and disabled states in Meta's button guidance. [Source](https://developers.meta.com/horizon/design/buttons_bp/)
- **Click response:** accepted sidebar actions receive a 160 ms surface response
  and a controller haptic pulse; trackpad navigation receives a smaller pulse.
  Disabled triggers do nothing. Detailed panels also receive an inset focus ring; their other established
  hover visuals and activation feedback remain. Audio may supplement these cues later,
  but is not implemented here. Microsoft's examples combine visual and sound
  feedback; our current controller implementation uses visual and haptic cues.
  [Source](https://learn.microsoft.com/en-us/windows/mixed-reality/design/button)
- **Spacing:** preserve non-overlapping hit rectangles. At default 0.65 scale,
  body rows are about 70 mm high with 7.8 mm gaps; tabs are 65 mm wide; the
  shortest footer controls are about 47 mm high. Do not copy screen pixels into
  metres: Meta specifies UI targets in dp, while Microsoft relates physical size
  to viewing angle/distance. Verify rendered size and controller acquisition at
  the actual placement. [Meta targets](https://developers.meta.com/horizon/design/styles_inputs_hit_targets/),
  [Microsoft sizes](https://learn.microsoft.com/en-us/windows/mixed-reality/design/button)
- **Grippable frames:** sidebars reserve a 40 mm local rail outside the controls
  (26 mm at the default scale), with textured corners and side grip marks.
  Near blue / moving amber / resizing green states pair color with status text;
  grab and resize acquisition pulse the controller. One nearby grip moves, two
  resize; the existing 75 mm world-space proximity allowance is unchanged.
  Neighboring frames resolve by nearest physical border and retain held ownership.
  Detailed tool and lattice panels use the same outlined corner/rail treatment.
- **Perimeters:** sidebar fills, outlines and focus rings use rounded corners.
  Borders follow the desktop strong-border token (`#484f58`); enabled buttons
  get a restrained accent tint, with Close using the desktop danger color.
  Disabled controls remain neutral gray. Rounded visuals retain forgiving rectangular hits.
- **Color:** prefer soft light text on dark gray. Preserve desktop blue selection.
  Pair color with shape/text, particularly the inset focus ring and navigation
  hint. Check text contrast and actual headset rendering rather than assuming a
  color swatch guarantees legibility. [Meta color guidance](https://developers.meta.com/horizon/design/styles_color/)
- **Icons versus labels:** keep explicit text for scientific operations and
  uncommon actions. Use simple familiar icons with labels when an atlas is added;
  icon-only controls need an accessible label/tooltip. Prefer a consistent filled
  family for immersive readability rather than mixing delicate outlines and
  filled symbols. [Meta icon guidance](https://developers.meta.com/horizon/design/styles_icons_images/)

Shared sidebar tokens and spacing rules live in `native/vr_viewer/src/ui_style.hpp`; input arbitration
lives in `menu_focus.hpp`. The new style tokens currently apply to the sidebars.
Detailed native panels retain their drawing styles with an added focus ring;
unsupported tool choices are gray and inert there as well.

## Trackpad and pointer contract

The left touchpad owns the six-sector selection wheel: hold, slide to highlight,
release to select; center release cancels. Drill is top, followed clockwise by
Cluster, Strand, Domain, Crossover and Bases. Entering a sector highlights it and
requests a light haptic pulse. Left menus use pointer/Trigger and unclicked swipes.
The right controller navigates its own open menu with the pad; its radial Tools
shortcut is available when that menu is closed. Opening or closing
the other sidebar does not cancel the active controller's focus.

1. Click the right trackpad once to enter focus mode on the pointed-at sidebar control,
   falling back to the selected tab (or first tool-panel control). This first click does not activate anything.
2. Click top/bottom to move within the current column, stopping at its ends.
   It never wraps into a neighboring column. Gray controls remain focusable
   for discovery; their triggers are inert.
3. Click left/right to move spatially between tabs, scrollbar, and content,
   or between buttons on the same row. Tab changes
   require Trigger. In tool panels, left/right steps through the bounded list. There is one step per click, no uncontrolled repeat.
4. Pull the same controller's trigger to activate the focused control. A card
   title toggles its contents, retaining title focus for a second press to reopen.
   Card titles remain enabled even if their children are unsupported. When the
   **scrollbar** is focused, top/bottom clicks page up/down directly and retain
   scrollbar focus. Left/right leaves the rail for the nearest row or tab at the entry height.
   The thumb shows the visible fraction, with a minimum size for visibility;
   pointer trigger positioning works along the rail. Short tabs have an inactive thumb.
5. Center-click again to return immediately to pointing. Alternatively, move the
   ray off the button it was resting on at the last trackpad click, then aim continuously
   at one button for 450 ms. A resting ray cannot silently take focus back.
   Holding the trigger suspends that handoff, preventing an in-progress press
   from changing targets.

Dwell resumes pointing; it never activates a button. The 450 ms value is a local
starting point, not a platform-mandated timing rule. Closing a sidebar and
releasing the ScryWrite control session reset its focus. Continuous controls
such as trajectory dragging and the desktop mouse surface still require pointing;
trackpad focus operates their surrounding native buttons.

## Live checks

```sh
just vr-menu-tour --focus-checks --validate --hold 0 --exit
```

Uses the existing owned empty viewer, real SteamVR/OpenXR submission and all four
unchanged motion presets for pointer reacquisition. It checks no-pointing
navigation, disabled triggers, paging, explicit and dwell-based return to pointer,
resting-ray protection and detailed-menu trigger activation. It retains stereo
focus pixels, controller trials and the actual desktop mirror check. Without
`--exit`, the viewer remains open for review. With no `--focus-checks`, the command
retains the complete tab/page tour.

Synthetic input and screenshots do not establish physical headset comfort or
whether 450 ms feels right for a particular user.

## Menu layout contract (2026-10-03)

Use these rules when adding or reviewing rectangular native sidebar menus. Values
are **local metres before panel scale**, not screen pixels or headset comfort
claims. At the default 0.65 scale, multiply by 650 for physical millimetres.
`ui_style.hpp` owns the spacing tokens; `SidebarMenu::controls()` owns the shared
rendering, picking and inspector geometry.

| Rule | Local value | Check |
| --- | --- | --- |
| Grip rail | 0.040 | Reserved inside the panel perimeter |
| Clear space after the rail | At least 0.024 | Every visible control silhouette stays 0.064 inside the panel bounds |
| Neighboring controls | At least 0.012 | Applies horizontally and vertically, including tabs and compound row controls |
| Raised action columns | 0.036 between nominal faces | Leaves 0.017 between the full rim/shadow envelopes |
| Tool content rails | x = −0.375 and +0.375 | Full-width rows and paired rows share outer edges; columns are equal width |
| Tool footer | Two columns, 0.108 high | Green Confirm/Apply left, red Back right; below every field and option |
| Footer section separation | At least 0.024 | Measured from raised silhouette to the lowest content/scrollbar edge |
| Text inset | At least 0.012 horizontally | Fit or wrap within the owning field; minimum stroke scale 0.002 |
| Sidebar body rhythm | 0.108 high / 0.120 pitch | 0.012 clear row gap |
| Ordinary targets | At least 0.150 × 0.065 | Compact tool adjustments retain 0.070 height |
| Compact row targets | At least 0.090 × 0.065 | Visibility/delete icons and View Volumes' On/Off chip |
| Wheel / scrollbar / tab targets | 0.050 × 0.065 / 0.060 × 0.150 / 0.090 × 0.150 | Dedicated interaction types, not ordinary buttons |

Extrude reserves 0.080 of its content width for the scrollbar column; its footer
still spans both outer tool rails. Nested sidebar rows keep their explicit
hierarchy indent. Tool heights follow the footer plus its shadow, clear space,
and grip rail; do not hard-code a panel bottom through the footer shadow.

Raised slate faces have decorative overhang: left 0.004, right 0.015, bottom
0.008, top 0.004. `ui_style::raisedEnvelope()` describes that silhouette for the
spacing audit. Keep it synchronized with `SolidUi::raisedSlate()`. Decorative
rim and shadow pixels do not expand the button's hit target. Disabled controls
obey the same spacing rules. Scroll animation uses clipped visible rectangles
for spacing; partially clipped rows are exempt only from the full target-size
and text-containment check. Frame instructions belong to the grip rail and are
not body controls.

### Review inventory

| Surface | Review and coverage |
| --- | --- |
| All catalog sidebar tabs, both hands, Part and Assembly | Checked on every page; tab gaps increased from 0.003 to 0.012 |
| Bend, including cluster-picker pages | Centered rails; wheel/readout and adjustment gaps fixed; footer clears frame; compacted the oversized gap below Cancel |
| Twist | Shared tool rails and footer; Units/Reverse gap corrected |
| Extrude | Shared centered tool rails, scrolling content and raised footer; footer clears frame |
| Move/Rotate | Shared centered rails, equal three-column selection row and two-column footer |
| Dimensions | Empty, single and multi-page lists, including scroll animation; 0.012 gaps and icons clipped with their rows |
| View Volumes | Empty, single and multi-page lists, including scroll animation; clipped icons, 0.012 gaps and an explicit compact On/Off target rule |
| Simulations | Empty, single and multi-page jobs/views, collapsed and expanded view pane; engine gaps corrected |
| Legacy Options, Tools, tool configuration, Jobs, job detail, Trajectory | Source reviewed; **not yet compliant with this sidebar contract**. They use `MenuItem`/`appendMenuGuides`, a 0.025 grip rail and narrower panels. Options has 0.005 row gaps, Jobs/Tools have 0.010 gaps, and controls reach the frame. Existing overlap/text checks remain; migrate geometry and picking together before claiming compliance. |
| Lattice painter | Spatial grid, exit control and external length wheel are a separate interaction surface. Its 0.018 edge inset is smaller than its 0.025 rail. Needs a dedicated grid/chrome clearance contract rather than applying sidebar row sizing to paint cells. |
| Detached desktop and legacy desktop display | Captured application pixels are external content. Detached Close sits above the image/frame by 0.025; image aspect and pixel-to-ray mapping must stay coupled. Sidebar row rules do not govern the captured application's controls. |
| Radial tools and in-scene handles | Polar/spatial controls have no rectangular menu border; use their existing acquisition/geometry checks. |
| Component gallery | Component/style reference, not a form layout; raised slate geometry is shared with the tool footer. |

This inventory distinguishes verified sidebar compliance from the remaining
legacy layout debt. A menu migration must update this table and add its cases to
the spacing suite; passing sidebar tests alone does not certify legacy surfaces.

### Repeatable checks

```sh
PATH=/usr/bin:/bin cmake --build native/vr_viewer/build --target \
  nadoc-vr-menu-spacing-test nadoc-vr-menu-layout-test nadoc-vr-sidebar-test
PATH=/usr/bin:/bin ctest --test-dir native/vr_viewer/build \
  -R 'nadoc-vr-(menu-spacing|menu-layout-unit|sidebar-unit)$' --output-on-failure
```

The spacing matrix exercises all catalog pages and the tool/list variants in the
inventory, including disabled actions. It verifies text fit, target sizes,
spacing and tool row alignment against actual production geometry. Negative
audit tests deliberately introduce crowded rows and a shadow inside frame
padding. The runtime audit also reports `border_clearance` and `control_spacing`
through existing layout diagnostics.

For visual review, inspect the native renderer with the complete panel in frame,
including its lowest shadow and all four grip rails. Check enabled, disabled,
hover/pressed, empty and last-page states; confirm labels remain legible and
rays acquire the visible control faces. The existing `vr-menu-tour` above checks
live controller interaction. An offscreen native render establishes appearance,
not physical through-lens readability or comfort.
