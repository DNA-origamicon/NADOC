# VR Bend

Choose **Tools → Bend**. It replaces the tool list with the Bend panel, following
Extrude's pinned Return / Confirm / Cancel layout. All Bend controls stay visible on one page. Touchpad directions move
between controls, including the paired step buttons. Grips move the scene; triggers edit the bend.

1. Choose **Plane 1**, then hold a trigger near a cluster. The nearest scoped
   contour determines an integer bp index. Moving while holding changes the bp;
   crossing to another cluster changes the target and clears the old planes.
   **Targets: element ends** also allows choosing an element through its end;
   unclustered elements are scoped to their helix.
2. Choose **Plane 2** and repeat. Both bp indices must be valid, with Plane 1 below
   Plane 2. The desktop fields use the same names and accept signed bp indices.
3. Grab either cyan end just outside a plane. Only one end can be held at once.
   The other endpoint stays fixed at its starting plane, with its tangent locked to
   that plane’s original normal. The moved plane follows the endpoint and stays
   perpendicular to the curve. Switching ends resets
   the previous bend first; regrabbing the same end continues it. The centerline preserves the
   contour length, limiting endpoint separation to `(Plane 2 − Plane 1) × 0.334 nm`.
4. Trigger-drag the Angle, Direction or Radius thumbwheel. Angle and Direction
   snap to 1°. Radius is shown in nm and changes through 1° arc-angle detents;
   increasing radius reduces angle. Release before confirming.
5. **Confirm** writes a normal desktop Bend deformation and one feature-log entry,
   then refreshes the native scene. **Undo** targets that exact entry and refuses
   to undo an intervening desktop edit. **Cancel** clears the draft.

Plane picking projects onto the scoped helix axes, including coarse scene
representations. Handle editing uses natural geometry; alternate
inspection layouts retain navigation but do not accept bend-handle grabs.

The desktop controls were reviewed: plane bp/nm readouts, cluster scope with
All/None, bend direction/compass, linked angle/radius, polymer-circle count,
live preview, feasibility, Apply and Cancel. Polymer-circle automation and
multi-cluster checkbox editing remain desktop controls. VR uses one proximity
selected target, a live centerline preview, and backend feasibility on Confirm.

Implementation uses canonical curvature (degrees per bp), with optional world
endpoint and midpoint constraints recording the controller pose. Both scalar and
batched desktop deformation frames apply the same rigid pose, including inverse
cluster transforms; no stretch is introduced. Files and feature replay retain
these parameters. A conflicting overlapping deformation that cannot reproduce the
requested circular endpoints is rejected before mutation. The browser owns mutation and guards design ID and revision.

Validation entry points:

- `pytest tests/test_vr_bend.py tests/test_deformation_clusters.py`
- `cd frontend && npx vitest run src/scene/vr_bend.test.js`
- `cd frontend && npx playwright test --config playwright.scrywrite-browser.config.js --grep 'VR bend'`
- Native CTest: `nadoc-vr-bend-panel`, `nadoc-vr-bend-viewer`. The latter exercises
  production trigger/wheel methods and GL pixels without an OpenXR runtime.
  An optional `motion.txt` in its output directory supplies xyz samples from
  `tools.vr_motion.model` for the four existing motion presets.

A rendered GL capture is not evidence of physical headset fit or comfort.

## ScryWrite test and guided VR tour

Use **Debug → VR Tours & Tests → Tools · Authoring → Bend between two planes**.
Demo pauses at the menus, plane handles, both endpoint previews, wheels, committed
bend, and Undo. It creates an isolated temporary part and closes its own viewer.
The terminal equivalents are:

```sh
just vr-bend-demo
just vr-bend-test
```

The test runs `steady_fast`, `steady_deliberate`, `variable_fast`, and
`variable_deliberate` in the same physical-runtime viewer, restoring the original
part with Undo between profiles. SteamVR must have a tracked, focused headset;
close any existing NADOC viewer before launching. This is synthetic controller
input through ScryWrite, not a claim of through-lens comfort or legibility.

`tools/vr_workflows/bend_probe.py` uses production menu clicks, trigger-held plane
picking with bp movement, both endpoint handles, exclusive grab ownership, contour
length and fixed-end checks, touchpad navigation, and angle/direction/radius wheels.
It never writes tool configuration directly. Stereo handle checks project the
observed world locations into both captured eyes and require actual colored
pixels; an offscreen negative must fail. `frontend/e2e/vr_bend.spec.js` checks
that Confirm changes desktop geometry, creates exactly one matching feature-log
entry, saves endpoint constraints, reloads them, and that VR Undo restores geometry
and history. Public desktop APIs are used only to generate the initial part and
save/reopen the result.

Evidence is retained under `.development-artifacts/vr-bend-tour/<run>/`: noisy
requested/applied controller samples, native state, stereo captures, desktop
screenshots, saved `.nadoc` files, and the run verdict. Failed attempts retain their
state and log. Pass `--output <new-directory>` to either command to choose a location.
The separate `frontend/scrywrite/browser_transaction.spec.js` bend case can run
without SteamVR and checks the browser transaction/desktop path; it does not replace
the physical-runtime controller test.

### Fixed starting plane during adjustment

A bend moves only one end away from its starting plane. Regrabbing that same end
continues the preview. Grabbing the other end resets both endpoints and the bend
angle first, so the previously moved end becomes fixed at its original plane.
Angle, direction, and radius readouts update while dragging. The free controller
can also operate the angle/radius and direction wheels while the other controller
holds an endpoint; wheel changes preserve the fixed starting-plane anchor.
Controller motion projects onto the nearest circular arc permitted by the fixed
surface normal and contour length. It cannot tilt the anchored surface. The
ScryWrite tour verifies the reset, live readouts, and fixed position and normal.
Desktop frame tests verify endpoint positions and tangents for bends from either
end, including bends beyond 180°.

The Bend panel remains open until **Return to tools**; trigger drags do not hide
it or require re-entering menu mode. The two-column **−5° / +5°** direction buttons
and **−10 nm / +10 nm** radius buttons provide coarse adjustments alongside the
wheels. Radius steps require a finite bend radius, and decreasing radius stops at
the 359° bend limit. The tour moves the model beside the open panel and verifies
separation in both eye views before bending.
