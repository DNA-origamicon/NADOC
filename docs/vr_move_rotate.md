# VR Move / Rotate

Open **Tools → Move / Rotate**. The **Selection** field arms scene picking;
choose the target with either trigger, using the left touchpad selection filter
for clusters, domains, strands, overhangs or individual bases. Selecting a target
returns to editing. The left trigger can also change selection.

Point the right controller at the selected geometry or its cyan preview. Hold
**trigger** to translate along the pointing ray; hold **grip** to change orientation
about the target center. Release retains the preview. Repeated grabs and numeric
adjustments accumulate until **Apply** or **Cancel**. Unclaimed grips retain scene
navigation and panel-border grips retain their normal controls. Tracking loss or
scene movement during a translation cancels the unfinished preview.

The panel shows authored-axis **X/Y/Z offsets in nm**, rounded to three decimals,
and **RX/RY/RZ angles in degrees**. Each has a 20%-exposed 0–100 thumbwheel design
and down/up buttons. One detent or button press changes the value by **1 nm** or
**1 degree**; the wheel's nominal design range does not clamp the pose. The
**15 degree snap** toggle quantizes controller rotation; manual controls retain
one-degree increments. Apply waits for grabs and wheel inertia to settle.

**Cancel** is on the left and restores the original pose. Green **Apply** is on the
right and commits one desktop feature-log edit for the entire preview. **Undo**
and **Redo** use the same versioned design-history channel as the VR radial menu,
and refresh the native scene. They operate on the shared desktop/VR history.
Changing the target cancels the old draft. The menu button hides/shows controls;
**Return to tools** leaves the tool. Desktop and VR share the saved pose, including
after reopening the part.

Each applied preview also appears in the desktop **Feature Log**. Clusters use
the ordinary `cluster_op` entry; bases and overhangs use one
`nucleotide-transform-batch` snapshot, labeled with the number of nucleotides
moved. These are the same entries used by desktop Move / Rotate, with the same
saved history and Undo behavior.

The cyan preview samples native geometry; saved edits use exact endpoint ownership.
Saving does not regenerate every representation. Related handles follow the
edit, so moving a cluster and then adjusting one of its bases uses the new pose.
Another edit becomes available when the backend acknowledges the saved edit.

## Tours and validation

Debug's VR tour catalog contains separate **Move / Rotate cluster**, **overhang**,
and **base** entries. Each creates a fresh temporary part, paints a desktop 6HB,
and adds an overhang and a named helix cluster through public desktop APIs. The
measured selection, menu controls and move/rotate gesture use physical-runtime
ScryWrite controller input. No fixture or existing workspace file is edited.

```sh
uv run python -m tools.vr_workflows.move_tour --target cluster
uv run python -m tools.vr_workflows.move_tour --target overhang
uv run python -m tools.vr_workflows.move_tour --target base
uv run python -m tools.vr_workflows.move_tour --validate
```

Validation uses the four unchanged human controller profiles sequentially. It
checks grip scene movement, exact selection, centroid acquisition, translation and
rotation, saved target scope, unchanged other bases, exactly one correctly typed
feature entry, its visible desktop row, unchanged earlier history, Undo, and exact
feature-log persistence through save/reopen. Registered submitted-eye ID/depth captures check visible target
movement and stationary reference geometry in both eyes. Framing adjustments are
recorded separately from measured reaches. Evidence is retained under
`.development-artifacts/vr-move/`; it establishes submitted-eye rendering, not
through-lens comfort or hand tracking accuracy.

## Live point preview

During a Move / Rotate draft, a cyan point cloud shows the
translated and rotated selection alongside the original geometry. Release retains
the draft; Apply commits it. Cancel or tracking loss during a grab removes the preview. The cloud remains visible
while the commit is pending and is replaced by detailed committed geometry.

Move shares Bend/Twist's bounded resident-buffer samples: at most 8,192 selected
primitives per channel (49,152 points per eye). Dragging updates only the rigid
matrix and does not transform/upload detailed geometry each frame. The existing
weighted geometry path runs once when successful commit feedback arrives, if a
refreshed authoritative scene has not already arrived. Undo retains that path's
exact baseline. Boundary cylinders are approximate point guides; committed
geometry still uses the backend ownership weights.

## Controller and history regression

`nadoc-vr-move-panel` checks coordinate frames, three-decimal translation, rotation
snapping, manual detents and panel layout. `nadoc-vr-move-hands` drives the production
trigger/grip/wheel handlers, verifies release retains the draft, cancellation,
Apply and both history-button intents, and retains a rendered panel with a visible
green Apply check and an offscreen negative. The browser transaction suite checks
Cancel, commit, Undo and Redo against the actual backend feature history.
These checks do not establish physical headset comfort.
