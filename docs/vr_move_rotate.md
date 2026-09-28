# VR Move / Rotate

Open **Tools → Move / Rotate** on the right controller. Choose **Clusters**,
**Overhangs / domains**, or **Individual bases**, then pull the trigger near the
object to select it. The closest object wins when several overlap the selection
sphere. Overhang beads select their entire overhang in the overhang/domain mode.

The selected center has an axis handle. Bring either controller within 9 cm:
the handle highlights yellow. Hold the trigger to translate and rotate the target
about its center. Release saves one undoable edit. A stationary click does not
save an edit. Losing tracking or starting scene movement cancels an unfinished
grab. Grips continue moving/scaling the part, and menu borders retain their grip
controls.

The menu button hides/shows the controls while keeping the tool active. **Return**
leaves the tool. **Cancel** restores an unfinished preview; **Apply** saves it;
**Undo** reverses the last VR edit, provided another desktop edit has not replaced
its history position. The panel shows when saving is in progress. Desktop and VR
share the saved pose, including after reopening the part.

Preview and saved edits reuse the native geometry and exact endpoint ownership.
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
rotation, saved target scope, unchanged other bases, one history entry, Undo, and
save/reopen. Registered submitted-eye ID/depth captures check visible target
movement and stationary reference geometry in both eyes. Framing adjustments are
recorded separately from measured reaches. Evidence is retained under
`.development-artifacts/vr-move/`; it establishes submitted-eye rendering, not
through-lens comfort or hand tracking accuracy.
