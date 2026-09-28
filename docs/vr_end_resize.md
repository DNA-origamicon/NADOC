# Resize selected ends in VR

Select a terminal end, bring either controller to its cyan arrow, and hold the
trigger. Pull outward to extend or inward to shorten, then release to save.
The arrow turns yellow on acquisition/extension and orange while shortening.
All selected end arrows resize together, following the desktop behavior.

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
