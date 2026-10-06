# VR Bend

Selections use the shared green geometry tint in Bend, Move / Rotate and Twist;
the corner-only bounding boxes have been removed. Those boxes were aligned to
the desktop export basis, rather than authored or room axes, and were only a
rendering decoration, not the deformation or movement frame.

Bend's reference direction, Twist's radial handle and deformation-plane squares
now use the exported authored axes. Plane drawing and picking share the same
frame. Changing the desktop camera therefore does not change those directions.
Regression checks cover rotated export bases, Bend endpoints and tangents,
plane hits, Twist handle angles, and Move's world-space rigid delta. The native
`nadoc-vr-selection-render` test retains selected/unselected images under
`native/vr_viewer/build/selection-evidence/` and checks that tint adds no outline
pixels. These are synthetic renderer checks, not through-headset validation.

Choose **Tools → Bend**. It replaces the tool list with the Bend panel, following
Extrude's pinned Return / Confirm / Cancel layout. All Bend controls stay visible on one page. Touchpad directions move
between controls, including the paired step buttons. Grips move the scene; triggers edit the bend.

1. Opening Bend retains the current selection, including multiple clusters,
   strands, domains, or a mixed set. **Change selection** enables the existing
   controller selection volume and Cluster / Strand / Domain filters. Fixed-level
   clicks accumulate; an empty click or **Clear selection** clears the set.
   **Use selection / Pick planes** freezes the current scope for the draft.
2. Both planes start at the selection's lowest and highest occupied bp indices.
   **Plane 1 / Plane 2** are readouts. Hold a trigger on a plane to slide it along
   selected contours. Picking rounds to integer bp, excludes gaps between selected
   domains, and keeps Plane 1 below Plane 2.
3. Enable **Manual bend** to grab either plane and move the bend endpoint without
   changing either bp index. Both nearby grabs and remote ray grabs work. Only one
   plane can be held at once. The other endpoint remains fixed, with its tangent
   locked to its starting plane normal. Switching ends resets the previous bend;
   regrabbing the same end continues it. Contour length remains
   `(Plane 2 − Plane 1) × 0.334 nm`. For strand/domain/group targets, **Shape
   handle** adjusts shared curvature/direction from Plane 2 with Plane 1 fixed;
   it does not impose a single world-space endpoint pose on disconnected arms.
4. Trigger-drag the inset, solid-ridged 3D thumbwheels to the **left** of the readouts. Angle
   and Curvature R (radius in nm) share a row; Direction has its own wheel below.
   The wheels use the Extrude wheel's ray-contact travel, degree detents, and
   damped flick inertia. Increasing radius reduces angle. Number fields do not
   initiate drags. Confirm becomes available after the wheels settle.
5. **Confirm** writes a normal desktop Bend deformation and one feature-log entry,
   then refreshes the native scene. **Undo** targets that exact entry and refuses
   to undo an intervening desktop edit. **Cancel** clears the bend and restores
   the selection's default planes.

Plane picking projects onto the scoped helix axes, including coarse scene
representations. Handle editing uses natural geometry; alternate
inspection layouts retain navigation but do not accept bend-handle grabs.

VR and desktop share exact target resolution and frozen nucleotide membership.
Overlapping selected refs do not apply a deformation twice; selecting a domain
never expands to its partner strand or containing cluster. A changed selection
invalidates the entire queued draft, including changes outside the primary ref.
The native centerline is a shape guide; backend feasibility runs before Confirm.
Polymer-circle automation remains a desktop control.

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

`tools/vr_workflows/bend_probe.py` uses production menu clicks, default planes and trigger-held plane
sliding with bp movement, both endpoint handles, exclusive grab ownership, contour
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

## Multi-selection regression

**Debug → VR Tours & Tests… → Authoring → Bend / Twist · multi-selection regression**
(or `uv run python -m tools.vr_workflows.deformation_selection_check --validate`)
exercises the real browser VR event handlers and backend for multiple clusters,
strands, domains, and mixed selections, including plane bounds, exact stationary
neighbors, stale-target refusal, save/reopen, and Undo. This check uses simulated
headset transport; it requires no headset. Native panel/viewer tests cover the
controller control path separately. Physical headset interaction remains a
separate validation gate.
