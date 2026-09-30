# VR view tools

Reach above the **left shoulder** with the left controller pointing upward and
backward to toggle the view panel; the matching **right shoulder** pose equips or
stows scissors. Detection is immediate, with no dwell. Return the hand in front
before repeating. Buttons must be released and tracking valid.

Each shoulder volume is 12–45 cm to its matching side, 10 cm below to 30 cm above
eye height, and from the ear plane to 35 cm behind it, relative to horizontal head
facing. The controller's pointing axis must be within 45 degrees of the diagonal
upward/backward direction. A reach needs at least 18 cm of hand travel.

The panel opens fixed in space. Its interactive border highlights on approach:
one grip moves/rotates it, two border grips resize it, and release leaves it fixed.
The **Dock / Follow** control switches between fixed placement and controller
following. Point either controller at a tile and click the trigger.
Opening or closing the panel does not change scissors mode.

The panel uses the desktop's original SVG icons in a two-column grid:

| Left column | Right column |
| --- | --- |
| Length | Sequence |
| Undefined | Loop / skip |
| Grid | Overhang names |
| Clashes | Deform |

Quick Expand, Unfold and Cadnano 2D are desktop-only. Their controls and layout
snapshots are excluded from VR; VR keeps its canonical 3D scene while one is active
on desktop. Other tiles invoke the existing desktop actions and stream the resulting
geometry and labels to the native stereo renderer. Deform still supports straight
3D inspection; restore Deform before editing a posed design.

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

September 30 refinement checks: five focused native tests, three frontend unit
checks, six backend checks and two browser integration checks pass. Browser panel
pixels were inspected; the initial detached-document failure and passing retry are
retained in `.development-artifacts/vr-view-tools-refinement-20260930/`.
SteamVR was not running: the revised shoulder gesture and movable border still
need the physical four-profile tour and human headset comfort review.
