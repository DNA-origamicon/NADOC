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

Shared sidebar tokens live in `native/vr_viewer/src/ui_style.hpp`; input arbitration
lives in `menu_focus.hpp`. The new style tokens currently apply to the sidebars.
Detailed native panels retain their drawing styles with an added focus ring;
unsupported tool choices are gray and inert there as well.

## Trackpad and pointer contract

Each controller navigates its own open menu. The right-trackpad radial Tools
shortcut is available when that controller's menu is closed. Opening or closing
the other sidebar does not cancel the active controller's focus.

1. Click the trackpad once to enter focus mode on the selected sidebar tab (or
   first detailed-menu control). This first click does not activate anything.
2. Click top/bottom to move focus through tabs, visible controls and footer
   controls. Gray controls remain focusable for discovery; their triggers are inert.
3. Click left/right to switch sidebar tabs. In detailed menus, left/right also
   steps through controls. There is one step per click, no uncontrolled repeat.
4. Pull the same controller's trigger to activate the focused control. A card
   title toggles its contents, retaining title focus for a second press to reopen.
   Card titles remain enabled even if their children are unsupported. When the
   **scrollbar** is focused, top/bottom clicks page up/down directly and retain
   scrollbar focus. Left/right leaves the rail for the last row / Close button.
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
