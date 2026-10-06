# Resize selected ends in VR

Use Bases (or End) selection mode to trigger-click multiple 5′ or 3′ ends.
Each click adds to the selection; clicking an already selected end keeps it
selected. Trigger-click empty space to clear the selection. Other fixed VR
selection modes also accumulate; Drill keeps its existing behavior.

Point either controller at a cyan arrow, or bring the controller close to it.
The targeted arrow highlights yellow and a pointer line joins the controller to
the arrow. Hold the trigger, pull outward to extend or inward to shorten, then
release to save. During the pull, a signed base count appears at the midpoint
of that line, facing the viewer. Arrows turn orange while shortening.
All selected ends preview and commit the same outward base count, clamped to
the shared collision/length limits. Their relocated ends remain selected for
subsequent group resizing.

Displacement snaps to whole base pairs and respects the desktop collision and
terminal-run limits (including inline overhangs and single-nucleotide ends).
Scene scaling changes the physical distance per base pair. The arrow geometry
follows native Expanded view. Grips continue to move/scale the scene; moving the
scene during an end drag cancels that drag. Tracking/focus loss, an expansion
change, or a changed selection/design also cancels or refuses the stale edit.
A release with no net base-pair change does not create an edit.

Each release uses the existing desktop strand-end-resize API and one Undo step.
Consecutive resizes appear as separate children of a Fine Routing feature-log
entry. The authoritative geometry is republished to the headset after commit.

Debug → VR Tours & Tests → Tools · Authoring → **Resize selected ends** runs a
reusable isolated demonstration. Validation exercises extension and shortening
with all four controller motion profiles, projected arrow pixels in both eyes
and the mirror, an offscreen negative control, topology, and independent Undo.
The generated part lives in a temporary workspace.

```sh
uv run python -m tools.vr_workflows.end_resize_tour --validate
```

Native `end_resize.hpp` owns acquisition, model-space projection and feedback.
The browser publishes versioned handles through `/api/vr/end-resize-handles` and
reuses `end_extrude_arrows.js` limits, mutations and reselection. Journal sequences
suppress duplicate release delivery; browser versions refuse stale targets.
ScryWrite exposes `end_resize` targets, grab state, and snapped delta for inspection.

Rendered stereo/mirror evidence and simulated controller paths do not establish
human through-lens comfort. See [validation record](audits/vr_end_resize_20260928.md).

Pointer interaction validation (2026-10-05): all four motion profiles exercised
remote hover, pointer and midpoint label pixels in both eyes and the mirror,
two selected ends extended by +12 and shortened by -6 together, retained end
selection, and independent Undo. The variable-deliberate run required a retry
after an uncommitted drag cancellation; cancellation telemetry was added and the
retry passed without changing motion profiles or input tolerances. Initial
visibility failures and observation-framing changes are retained alongside the
passing captures in `.development-artifacts/vr-end-pointer-validation-20261005.json`.
The inspector exposes `hover_hand`, `hovered_arrow`, `pointer_start`, `pointer_end`,
`label_position`, `label`, and `cancel_reason` under `end_resize`.
