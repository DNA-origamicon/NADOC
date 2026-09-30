# Ligate with the VR radius wheel

Hold the right trackpad to open the existing four-volume wheel. Its sectors are
now **Ligate**, **Nick**, **Undo**, and **Redo**. Move the selection sphere into
Ligate and release the trackpad to enter Ligate mode. All four sectors are active.
Extrude, Twist/Bend and Move/Rotate retain
their existing sidebar entry points.

In Ligate mode:

1. Put either controller's selection sphere on a 3′ or 5′ strand end.
2. Hold its trigger to pick up that end. The source is highlighted in green.
3. Move the controller while holding the trigger. A cyan bond preview stretches
   to the selection sphere. It snaps green onto a compatible end; incompatible
   ends give red feedback.
4. Release over the compatible end to create one forced ligation. Releasing over
   empty space or an incompatible end cancels without editing the design.

A compatible target has the opposite end polarity and belongs to another strand.
The shared desktop ligation rules supply eligibility: synthetic residues, loop
copies and ambiguous one-nucleotide terminals are not offered. Pickup order can
be either 3′→5′ or 5′→3′. The browser maps that order to the same canonical forced
ligation API, refreshes the native geometry and leaves Ligate ready for another
bond. Each successful release is one independently undoable desktop minor edit.

Choose Ligate again to leave the mode, or switch to a sidebar authoring tool.
Opening a menu, moving/scaling the scene with grips, losing tracking/focus, or a
changed endpoint catalog cancels the active drag. Selection-sphere radius keeps
its existing trackpad adjustment. End-resize arrows do not acquire triggers while
Ligate owns the gesture.

Debug → VR Tours & Tests → Tools · Authoring → **Ligate ends with the radius wheel**
provides an isolated demo and four-profile validation. It uses ordinary wheel
volume targeting and triggers, tests both pickup polarities and incompatible
release, checks preview and saved-bond pixels, and verifies exact desktop Undo.

```sh
uv run python -m tools.vr_workflows.ligation_tour --validate
```

Implementation: `native/vr_viewer/src/ligation.hpp`, the browser coordinator in
`frontend/src/scene/vr_ligation.js`, and `/api/vr/ligation-ends`. The native event
journal supplies a monotonic release sequence and catalog version; the browser
refuses stale pairs before issuing the authoritative mutation. ScryWrite exposes
`radial_edit` sectors and `ligation` source/target/preview state for inspection.

See the [validation audit](audits/vr_ligation_20260928.md) for evidence, retained
attempts and remaining headset checks.


## Nick, Undo and Redo

Choose **Nick** to replace the right controller selection sphere with scissors.
You can also equip or put them away with a **quiver gesture**: start with the right
controller in front of you, reach behind your head/shoulder with buttons released,
pointing upward/backward above that shoulder. Activation is **immediate**. A haptic pulse confirms the toggle. Bring
your hand back in front before repeating; leaving it behind does not toggle again.
A stronger pulse equips, a lighter pulse stows. The wheel's Nick sector remains
an alternative toggle.
See the [quiver gesture validation](audits/vr_quiver_gesture_20260928.md).

The gesture follows your headset's position and horizontal facing direction.
It requires an actual controller reach, not just a head turn. Lost tracking,
open menus, pressed trigger/grip/trackpad, scene manipulation and pending edits
suppress it. The left hand keeps its selection sphere and cannot nick. Its quiver
gesture independently opens or closes the [view tools panel](vr_view_tools.md).

Move the scissors onto a backbone bond: the impending cut glows amber. Squeeze
partway to close the blades gradually and brighten the bond. Crossing the normal
full-trigger click threshold creates one nick through the desktop nick API.
A held trigger does not repeat the cut; release before clicking again. An empty
click is a no-op. Choose Nick again to exit, Ligate to change mode, or a sidebar tool.

Nick candidates follow 5′→3′ strand order. Existing breaks, ambiguous core
coordinates and bonds involving synthetic residues or loop copies are excluded
because the coordinate-based nick API cannot identify those individual copies.
The same user-adjustable selection radius applies, centered at the scissors.
Menus, lost focus/tracking and scene-grip manipulation suppress cutting.

**Undo** and **Redo** apply to the current desktop design history and refresh the
native geometry after success, including edits made on desktop. They are immediate
wheel actions, not persistent modes. An empty history reports failure without an
edit. Wheel mutations share a busy guard and catalog version check, and every
request is deduplicated by the browser session. Assembly editing is excluded.

Debug → VR Tours & Tests → Tools · Authoring → **Nick with scissors, Undo and Redo**
runs an isolated demo or validates all four motion profiles. The probe checks
quiver equip/stow and no-repeat behavior, restored-sphere/scissors pixels,
partial trigger values, scissors/glow pixels, one click/one nick, held-trigger
non-repetition, empty clicks and exact history restoration.

See the [Nick/history validation audit](audits/vr_nick_history_20260928.md).
