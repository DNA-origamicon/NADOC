# VR room appearance

Native menu panels use a barely visible white veil (10% white, 90% blurred scene).
The blur sampling radius is 15 pixels, increased 50% from 10 pixels.
Light lettering stays sharp. Button fills are faint, with stronger outlines for
selection. The view-tools tablet reads desktop computed colors and reuses the
original SVG icons, retaining their explicit RGB values and gradients. Native-only
controls retain a subtle stable accent. Disabled controls have fainter fills.
Each eye samples its own scene; molecular geometry itself is not blurred.

The floor has 0.5 m grid spacing, stronger 1 m lines, and a cyan play-area outline.
It uses SteamVR's calibrated OpenXR STAGE pose and bounds, independent of model
movement, rotation or scaling. The outline is the runtime's rectangular play area,
not the arbitrary room perimeter. NADOC does not modify SteamVR room setup.
When bounds are unavailable, only the calibrated grid is drawn. When STAGE cannot
be located, neither is drawn; the viewer does not invent a floor height or bounds.
The distant grid fades out. Floor graphics do not intercept object selection.

Launch **Debug → VR Tours & Tests → Controls & layout → Frosted menus & SteamVR
floor demo**. It opens a separate viewer with a small example design, places a
menu in front of the design and floor using ordinary grips, and leaves the menus
available for review. The corresponding validation runs all four controller
motion profiles and exits. It requires a working, calibrated SteamVR runtime.

Command-line equivalent:

```sh
uv run python -m tools.vr_workflows.menu_tour --room-checks --preset steady_fast
uv run python -m tools.vr_workflows.menu_tour --room-checks --validate --exit
```

The validation checks both stereo eyes, menu text, floor pixels, projected
calibrated bounds and the actual desktop mirror. Negative cases distinguish blur
from plain transparency and opaque gray, and reject a boundary shifted 30 cm.
See [white glass validation](audits/vr_white_glass_20260928.md) and
[original floor validation](audits/vr_room_ui_20260928.md). Through-lens readability
and comfort still need a worn-headset review.
