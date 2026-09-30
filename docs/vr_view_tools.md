# VR view tools

Reach behind your head with the **left controller**, pause briefly, and bring it
back in front to open the view panel. Repeat to put it away. The panel stays where
it opened; point either controller at a tile and click the trigger. A highlight
shows the hovered tile and ON/OFF shows the desktop's actual state.

The **right controller** alone equips scissors with the corresponding quiver
gesture or the radius wheel's Nick sector. The left controller remains a selection
sphere. Opening or closing the view panel does not change the scissors mode.

The panel uses the desktop's original SVG icons in a two-column grid:

| Left column | Right column |
| --- | --- |
| Length | Sequence |
| Undefined | Loop / skip |
| Grid | Overhang names |
| Clashes | Deform |
| Unfold | Cadnano 2D |

Quick Expand is removed from VR. Resize the model and move inside it for close
inspection. Desktop Expanded remains available, but its geometry is not sent to VR.

Each tile invokes the existing desktop action. Visible meshes, instance colors,
transparency and text textures are sent to the native renderer and drawn with
its own stereo cameras and the current model transform. These are spatial view
controls, not a desktop screenshot. Desktop changes also update the panel.

The desktop prerequisites apply: Unfold and Cadnano require a non-atomistic
representation and straight geometry; turn off Deform first when the design has
active deformations or cluster transforms. Deform has no effect on an already
straight design. The panel explains these cases. Straight and 2D layouts are
inspection views: return to the deformed 3D layout before editing, so canonical
bond/end pick targets cannot cut or resize geometry at a different visible pose.
World manipulation and panel input remain available.

Debug → VR Tours & Tests → Right sidebar → **Left-hand view tools** provides an
isolated generated-part demo and four-profile validation. The test opens and
stows the panel with physical left-hand reaches, operates the tiles with trigger
input and compares the resulting desktop and native states. Evidence includes
both stereo eyes, the delivered mirror and desktop screenshots.

```sh
uv run python -m tools.vr_workflows.view_tools_tour --validate
```

Implementation: `frontend/src/scene/vr_view_tools.js`,
`backend/api/vr_view_tools.py`, and `native/vr_viewer/src/view_tools.hpp`.
The local document-bound endpoint validates the binary snapshot and atomically
replaces the sidecar consumed by native VR. Trigger actions use the existing
sequenced native event journal and browser deduplication.


Validation details, retained attempts and the large-design transfer benchmark:
[view-tools audit](audits/vr_view_tools_20260928.md).
