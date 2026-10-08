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
