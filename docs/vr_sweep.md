# Sweep in VR

Open the right hand **Tools → Sweep** panel. As in desktop Sweep, paint the
lattice footprint first, then choose **Next**. The second step starts with an
origin and a second spline point, and displays a lightweight point-cloud preview.
**Back** returns to the footprint without discarding the edited path.

Select a point in the scrollable list or point at its sphere and click Trigger.
A pointer line identifies the hovered point. Hold Trigger and move to drag it;
the XYZ fields and their arrows edit coordinates in nanometres relative to the
fixed origin. The right touchpad menu offers **Add Point** on the right and
**Delete Last** on the left. Deletion removes the last added point (the last point
in the list), regardless of the selection. The panel's **Delete Selected** button
removes the selected point. The origin remains fixed.

**Free draw** clears the path and arms one continuous stroke. Hold the right-hand Trigger and
sketch in three dimensions; a glowing green line follows the captured stroke.
Releasing Trigger replaces it with a smoothed, editable point list. The sketch
starts at the sweep origin; its shape follows controller-tip displacement.
Confirm creates the same editable Sweep feature as desktop authoring, with
ordinary history, undo and redo.

In the desktop **Feature Log**, choose the Sweep feature's **Edit** action. Its
painted footprint and fitted control points reopen in the desktop Sweep editor;
change a point's coordinates and confirm to update that feature. Undo and Redo
restore the feature edit separately from the original Sweep creation.

The smoothing control is adjustable. Default physical distances are a 36 mm
smoothing radius, 15 mm simplification tolerance and 1.5 mm sample spacing,
converted to model nanometres using the scene scale frozen when drawing starts.
These are provisional stress-tested settings, not a measured model of human
accuracy. Small features below the tolerance may be removed. The first version
captures one stroke per Free draw activation.

## Direction, twist and bend warnings

Both the desktop and VR editors support optional orientation at every path
point. Green arrows show the forward direction; amber arrows show the
cross-section's right axis, making twist visible. Automatic points retain the
original natural-spline behavior. Controlled points steer a cubic Hermite path;
roll interpolates between the authored frames. Disabling all controls restores
the original natural spline.

On desktop, select a point and enable **Control direction and twist**, then edit
**Tilt X**, **Tilt Y**, and **Twist** with arbitrary angles. With a point selected
and focus on the canvas or point entry, **Tab** switches between translation and
free-angle rotation gizmos; entering rotation enables direction control. Tab in
form fields retains normal focus navigation. XYZ fields and the translation gizmo
control position independently. Displayed positions truncate to two decimals,
without reducing stored precision. Point labels match the XYZ field font; usage
help is available as hover tooltips.

Both editors show the lattice envelope and helix circles at each point in its
oriented plane, emphasizing the selected section. **New BP** below the path
controls reports the total new base-pair sites across all selected helices from
the current server preview, excluding existing source bases in continuations.

In VR, point at a point and hold **Grip** to enable orientation and rotate it by
turning the controller. Position stays fixed; crossing a 15° increment gives a
small haptic pulse. Trigger still drags position. An unclaimed grip moves the
scene, so aim away from points when repositioning the model. **DIR ON/OFF** in
each point's row toggles orientation; with DIR ON, the row's arrows edit RX/RY/RZ
in 15° steps instead of XYZ in nanometres. RZ is cross-section twist.

Angles reference the starting plane, even after moving or rotating the model.
The convention is a right-handed local frame: right is +X for XY/XZ and +Y for
YZ; up is normal × right. Orientation is `Ry(tilt Y) Rx(tilt X) Rz(twist)`.
The new-bundle origin can rotate but cannot move. An attached origin retains its
source end's complete orientation so that the connection remains continuous.
Full point orientations survive feature editing, persistence, Undo and Redo.

Orange-red path segments and a warning identify bending demand above the existing
loop/skip density limit: **three insertions or deletions per seven-bp cell**.
The calculation uses the painted helix offsets in their transported, twisted
frame, including opposite bend directions separately. It shares the signed
bending calculation used by loop/skip generation. **Warnings allow Confirm**.
They do not certify experimental stability, torsional feasibility, helix
collisions, or the availability of crossover-safe modification sites. Amber warning
icons mark affected regions. Desktop hover or a VR trigger click displays
**Loop/skip limit is exceeded**. Icons remain on created geometry, persist through
save/load and history, and track the corresponding helix positions.

Confirm automatically applies safe loop/skip corrections to the new sweep's
helices only, including square-lattice periodic compensation. Original source
helices retain their marks. Excess demand is capped at the existing cell limit,
strand ends and crossover margins stay protected, and creation succeeds with
warnings for uncorrected strain. Running **Add skips/loops** again recomputes the
same corrections without stacking them. Legacy sweeps keep their previous strict
menu behavior. Native VR Confirm is green; during generation a spinning circle
appears over its label and repeat submissions are disabled.

Native VR receives bounded preview geometry and warning segments from the same
backend evaluator used by desktop. While an oriented draft is being evaluated,
the native line shows its current steering and the old helix cloud is hidden.
The new cloud appears when feedback for that exact configuration arrives.

## Calibration and regression

The calibration harness calls the production C++ smoother and natural spline
sampler, using all four existing controller presets, independent seeds and
straight, S-shaped and nonplanar arc strokes. Position and rotation noise both
affect the same 12 cm controller-tip offset used by the native viewer. It reports
point count, arc-length inflation, spatial error and missing intended curvature.
Default scale tests use 50, 100 and 200 model nanometres per tracking metre.

```bash
uv run python -m tools.vr_motion.sweep_calibration --output /tmp/sweep-calibration.json
just test-focused tests/test_vr_sweep_calibration.py
```

Seeds 0–3 were used to choose the provisional defaults; the regression uses
held-out seeds. The `variable_fast` and `variable_deliberate` presets both use
12 mm per-axis positional deviation, 2° angular deviation and 15% overshoot.
They are illustrative stress profiles and do not establish physical user
performance. The calibration output distinguishes the original noisy path from
the intended motion; a small point count alone is not a passing criterion.

## Tour and physical validation

In **Debug → VR Tours & Tests → Tools · Authoring**, choose **Sweep an S shape · Free
Draw and point editing**. Demo draws with `steady_fast` and pauses at the glowing
stroke, fitted S, trigger-dragged point and before/after XYZ controls. The command
line exposes the same demo and four-profile validation:

```bash
uv run python -m tools.vr_workflows.sweep_tour --output /tmp/sweep-tour
uv run python -m tools.vr_workflows.sweep_tour --validate --output /tmp/sweep-validation
```

Both modes use a temporary document, workspace, backend and frontend, then drive
normal controller handlers through ScryWrite transactions. The tour paints two
lattice cells, checks radial **Delete Last** with a different point selected,
and draws an upright S in front of the tracked eye. An ordinary model-grip
translation places the draft for review without changing the canonical points
or configuration. The drawing frame is recorded, and profile timing and noise
remain unchanged. Both S lobes must survive smoothing; a straight or single-bend
curve cannot pass the shape check.

After each Free Draw release, the probe ray-selects and trigger-drags a fitted
interior point, verifies other points remain unchanged, then edits its Y field
through the list's arrow. Submitted stereo images retain the stroke, pointer,
fitted curve and point-edit states. The browser then confirms the feature,
opens **Edit** in the desktop feature log, changes an interior point, and checks
Undo and Redo for both that edit and the original creation.

These commands require the workstation's working OpenXR runtime and headset
tracking. They must start with no active native viewer. A headed browser and
visible pauses are used for Demo; validation runs all four profiles without
review pauses. `NADOC_VR_DEMO_HOLD` changes only the pauses outside measured
motion, in seconds (default 3).

```bash
cd frontend
NADOC_PHYSICAL_VR_TEST=1 npm exec playwright test -- --config playwright.vr-sweep.config.js
```

The tour keeps `sweep-evidence/tour-report.json`, per-profile shape and input
reports, point-edit stereo captures and desktop history evidence under `--output`.
The direct Playwright command keeps evidence in its isolated
`/tmp/nadoc-scry-browser-*` directory. These are application-submitted stereo
images, not compositor presentation measurements. Offscreen native rendering
checks and headless geometry tests remain separate from physical-headset proof.

The 2026-10-08 S-shape Demo passed in about 1.5 minutes, including visible review
pauses, post-Free Draw point dragging and XYZ edits, desktop feature-log editing,
and Undo/Redo of editing and creation. Retained evidence is at
`/tmp/nadoc-sweep-tour-edit-demo-20261008/sweep-evidence/`. Compare
`smoothed-s-shape-steady_fast/left.png` with
`fitted-point-dragged-steady_fast/left.png` to see the edited lower lobe;
`fitted-xyz-before-steady_fast/` and `fitted-xyz-after-steady_fast/` show the point
list. The browser's desktop history evidence retains the canonical before/after
states. The separate 288-case synthetic calibration report remains
`/tmp/nadoc-sweep-tip-calibration.json`.

The expanded four-profile validation also passed on 2026-10-08 in about 1.3
minutes. Its evidence is at
`/tmp/nadoc-sweep-tour-edit-validation-20261008/sweep-evidence/`.
`tour-report.json` records both preserved S lobes and the post-fit trigger drag
and XYZ change for every profile. `desktop-edit-preview.png` shows the full
S-shaped design beside its desktop Sweep editor; `desktop-history.json` records
the feature-log edit and exact geometry restoration through Undo and Redo.
These passes cover the new tour and desktop feature edit, beyond the earlier
creation-only history check.

The lattice painter displays occupied source cells for both Sweep and Extrude.
Occupied cells cannot be painted, and preview/commit reject conflicting new
footprints on the selected XY, XZ or YZ plane. Occupancy survives bends and
sweeps and remains available when several source frames make placement
ambiguous. End continuation keeps its existing source-attachment behavior.
The tour reopens both painters after committing, checks the occupied footprint,
and attempts to paint it with each validation controller profile.

VR helical axes now follow the desktop's centripetal Catmull–Rom curves and
arc-length sampling, including separate paths across domain gaps. Regression
tests compare Bend and Sweep exports directly with the desktop renderer's
Three.js tube centerlines.

The occupied-cell extension passed all four controller profiles on 2026-10-08:
`/tmp/nadoc-sweep-occupied-axis-final-20261008/sweep-evidence/` retains eight
occupied-cell trials, post-fit edits, and the desktop history sequence.
`occupied-sweep-steady_fast/left.png` shows the two existing cells and disabled
Next button. For observation, an ordinary scene grip moved the molecule aside
after the committed-design review; this left document geometry unchanged.
The initial demo timed out reopening the desktop Edit menu; the tour now
targets its top-level button explicitly before each history action.

An additional Bend demo retained at `/tmp/nadoc-bend-axis-review-20261008/`
reached the endpoint and curvature controls but was refused at commit with
`stale_target`. It is not a visual validation pass. Bend axis correctness is
covered by the direct desktop-renderer/export comparison (with and without
domain gaps). The Bend probe now waits for startup and menu readiness; its
initial startup failure remains at `/tmp/nadoc-bend-axis-demo-20261008/`.

The direction/twist extension passed the physical-runtime `steady_fast` demo on
2026-10-08 at `/tmp/nadoc-sweep-orientation-demo3-20261008/`, followed by all four
controller presets at `/tmp/nadoc-sweep-orientation-validation-20261008/`.
Each profile grips a fitted interior point, rotates it through the ordinary
controller handlers, checks 15° snapping and unchanged XYZ/scene placement,
and retains `fitted-point-orientation-<preset>/left.png` and `right.png`.
`tour-report.json` records the before/after angles and profile motion evidence;
`desktop-history.json` covers subsequent editing and undo/redo. These are
submitted stereo images, not through-lens measurements.

Retained failed attempts explain the setup changes: `demo-20261008` gripped the
origin to reposition the scene, which now correctly activates point orientation.
The tour now grips empty space for scene framing. `demo2-20261008` passed point
rotation but its preflight was displaced by a concurrently running desktop
browser test using the shared VR session. Final desktop and VR browser runs
were serialized. No input tolerances or controller profiles were relaxed.

Desktop warning/control evidence is
`.development-artifacts/sweep-orientation-warning.png`. Reproduce the isolated
desktop creation/edit/history check with
`cd frontend && npm exec playwright test -- --config playwright.sweep.config.js sweep_orientation.spec.js`.
Native input and rendered warning evidence is covered by
`nadoc-vr-sweep-viewer-test`, with images under
`native/vr_viewer/build/sweep-evidence/`.

The desktop refinement check is `sweep_orientation.spec.js`'s “Tab rotates”
case. It uses a real mouse drag on the rotation gizmo, verifies arbitrary angles
and unchanged XYZ, compares displayed fonts, and checks that a coordinate such
as `1.239876` displays as `1.23` while retaining full precision after creation.
`.development-artifacts/sweep-refined-controls.png` shows the resulting controls,
section outlines and BP count. Backend tests compare the count with actual added
helix sites for new bundles and continuations, and check section placement in all
three starting planes. Native layout tests ensure two-decimal coordinates remain
intact on one line and the BP box clears the footer.

Refinement validation notes (2026-10-08): the first VR attempt did not launch
because the test could not reach Help → View in VR. The tour now uses an explicit
Help-button click and a 1600×1000 browser viewport. The second attempt completed
steady_fast controller/creation trials, with stereo evidence under
`/tmp/nadoc-sweep-refinement-demo2-20261008/sweep-evidence/`, before the desktop
check encountered its obsolete three-decimal display expectation; that assertion
now checks two-decimal truncation. Its eye images also exposed wrapped coordinate
digits, corrected by fitting the number within the native field width.

A broader browser run was interrupted after development-time reloads invalidated
its scaffold-routing page; retained trace: `/tmp/nadoc-scry-browser-gTimy9/`.
The orientation/history case has passed but also intermittently encountered
`Design changed while the feature operations were being prepared` during an edit
(`/tmp/nadoc-scry-browser-IzIpi2/`). This revision-conflict check remains active.
The independent Tab/precision/BP creation case passed. Rendered stereo evidence
establishes eye-buffer output, not through-lens headset legibility or comfort.

Final refinement validation passed all four motion profiles plus creation,
desktop feature editing, Undo and Redo in
`/tmp/nadoc-sweep-refinement-validation-20261008/` (2.3 minutes).
`fitted-xyz-after-variable_deliberate/left.png` under its `sweep-evidence/`
directory shows intact coordinates, oriented sections and **NEW BP: 612**;
`desktop-edit-preview.png` shows the corresponding desktop editor. The tour's
owned viewer and temporary document were closed on completion.
The final isolated desktop run also passed all four cases in
`sweep_orientation.spec.js` and `sweep.spec.js`, including end continuation
(43.5 seconds); no application changes or reloads ran concurrently with it.

Automatic correction and persistent-warning regression evidence (2026-10-08):
80 backend Sweep tests pass both in the working tree and in an isolated checkout
containing only the staged Sweep patch. Forty focused frontend tests and all
three native Sweep tests pass; the production frontend build also passes.
Native GL evidence in `native/vr_viewer/build/sweep-evidence/` includes
`sweep-generating-a.ppm`, `sweep-generating-b.ppm` and
`sweep-curvature-warning.ppm`. The two pending frames use distinct clock phases
and assert green button pixels and a changing spinner; success/failure feedback
stops the spinner. Desktop tests exercise hover before and after creation, while
native tests trigger the warning on both draft and loaded scene metadata.

The pending-generation demo passed at
`/tmp/nadoc-sweep-generation-demo2-20261008/sweep-evidence/`, including submitted
stereo frames `generating-sweep-a/` and `generating-sweep-b/`. The test holds the
real creation request for ten seconds outside measured motion to make the
pending state reviewable. Its first attempt (`demo-20261008`) exposed an end-on
point-pointer ray hidden by the point glyph. The probe now offsets that inspection
ray sideways by 8 cm, retaining the input profiles and pixel thresholds. The
first final-validation attempt (`validation-20261008`) failed before controller
testing when SteamVR's server aborted on a Web-thread watchdog timeout. The
runtime was restarted through its normal startup script for the headed retry.
These captures establish rendered behavior, not physical through-lens legibility.

The headed retry passed all four profiles and desktop creation/edit/undo/redo
in 2.7 minutes at `/tmp/nadoc-sweep-generation-validation2-20261008/`.
The desktop warning screenshot after creation is retained at
`.development-artifacts/sweep-created-warning.png`; the draft warning and free
rotation views are beside it as `sweep-orientation-warning.png` and
`sweep-refined-controls.png`.

The final desktop run exposed a continuation-test setup race: autosaving its
fresh source bundle invalidated preflight during the Next button click. The
instrumented diagnostic passed once that save settled. The continuation fixture
now waits for the normal saved badge before exercising authoring; production
input handlers and validation thresholds are unchanged. Failed traces remain in
`/tmp/nadoc-scry-browser-tzzH7P/` and `/tmp/nadoc-scry-browser-KcfG4T/`.
The final desktop rerun passed all four tests in 44.9 seconds.
