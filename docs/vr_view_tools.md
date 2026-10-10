# VR view tools

Reach above the **left shoulder** with the left controller pointing upward and
backward to toggle the view panel; the matching **right shoulder** pose equips or
stows scissors. Detection is immediate, with no dwell. Return the hand in front
before repeating. Buttons must be released and tracking valid.

Each shoulder volume is 12–45 cm to its matching side, 10 cm below to 30 cm above
eye height, and from the ear plane to 35 cm behind it, relative to horizontal head
facing. The controller's pointing axis must be within 45 degrees of the diagonal
upward/backward direction. A reach needs at least 18 cm of hand travel.

The panel starts attached to the left controller and continues following its
position and orientation after the hand comes forward. Tiles remain interactive.
Click **Dock** to hold the panel in place, or **Follow** to attach it to the left
controller again. Reaching back again dismisses it in either mode; reopening
always starts attached. Its interactive border supports deliberate grip movement
and two-hand resizing. Trigger grabs use the shared menu border controller,
including rotation, release, and two-hand resize behavior. Either hand can hold
the border with a trigger or grip and reach to its matching shoulder to dismiss
the tablet. This consumes the grab without equipping scissors; release before
starting another gesture. **Close** in the header dismisses it normally.
Point either controller at the tablet to show its pointer beam, and click a tile
with the trigger.
Opening or closing the panel does not change scissors mode. Open sidebars,
modeling tools and pending edits on the right hand do not disable left-hand
access. Scissors still require leaving the modeling tool first; a shoulder reach
never confirms Bend or adds a Sweep point. After tracking loss, return the hand
in front before reaching again. Release the invoking controller's buttons.

Inspector observations expose `ligation.quiver.blocked` (one reason per hand)
and `view_tools.following`. `pending_edit` waits for the browser acknowledgement;
failed feedback delivery is retried without repeating the topology operation.
Debug → VR Tours & Tests → Controls & layout → **Reach-back · tool exit and
reactivation** checks production native lifecycle handlers and GPU lighting
without taking over the physical headset. **View tablet · grab, stow and close**
exercises Dock, trigger/grip shoulder dismissal, pointer beams, and Close live. The Nick and View Tools tours retain four-profile stereo
validation and now also check controller following and explicit docking.

October 9 validation: native lifecycle/Dock/Follow regression checks and 44 tour
registration tests pass. Physical reach-back checks pass `steady_fast`,
`steady_deliberate`, and `variable_deliberate`, including both rendered eyes,
the mirror, negative visibility controls, and unchanged topology. `variable_fast`
was interrupted by a 0.342 s playback delay. The view-tools tour verified Dock
and six toggles on/off before a 0.156 s playback delay at Clashes; it is not a full
view-tools pass. Thresholds were unchanged. Evidence and cleanup record:
`.development-artifacts/vr-quiver-reactivation-20261009/` (`quiver-following`,
`quiver-following-variable-deliberate`, `view-tools-following`). Earlier full Nick
tours stopped at blade/bond-glow pixel checks; these shoulder-access results do
not establish cutting or through-lens comfort.

Additional tablet-controls validation (October 9): native lifecycle/grab/Close,
real GPU lighting/shadows and broader GL regressions pass, along with 11 focused
frontend, 7 transport and 44 tour tests. The live `steady_fast` visualization tour
passes all eight toggles on/off and stow. The final controls tour passes
`steady_fast`; the noisy `variable_fast` pointer did not acquire Close, and the
other final profiles hit playback timing limits during setup. A prior
`steady_deliberate` controls run passed before hover feedback was added. These
results do not establish a clean four-profile stress pass. No motion thresholds
or button hit bounds were relaxed. Full frontend: 7,794 passed, two MD panel
failures. Backend FAST: 10,332 passed, 51 failures outside VR, 89 skipped; FULL
remains deferred by the existing session gate. Evidence, failed attempts and
cleanup: `.development-artifacts/vr-tablet-controls-20261009/verification-summary.json`.

Visualization snapshots now carry surface normals (display schema 5; legacy
schema 4 remains readable). Molecular surfaces use the native lighting and soft
shadow calculation instead of the former unlit material. Recoloring and labels
retain the canonical model's shadow map; switching Deform off renders the changed
geometry into the shared shadow pass. Text, icons, and line overlays stay unlit.

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
