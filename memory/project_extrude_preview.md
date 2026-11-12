---
name: project_extrude_preview
description: "Sidebar \"Extrude\" toggle showing translucent ghost cylinders for the extrude tool (slice-plane + overhang)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 9242672e-6640-4491-bdd3-c5b7f01e77e6
---

# Extrude and Sweep previews

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

## Shared desktop cross-section workflow (2026-11-11)

Extrude now opens Step 1 with the source plane normal to the camera and orbit
locked. Next requires selected cells and opens Step 2 with a fitted oblique view,
length/direction/recommendations, and a non-pickable cross-section. Previous keeps
the footprint and length; the close button/Escape cancels the whole draft.
Source and strand/ligation choices live in Step 1. History edits use the same
steps and retain their existing Apply/Cancel/replay contract.
`ui/cross_section_workflow.js` is shared with Sweep for normal source alignment,
orbit gating, and view fitting. Source switches, Next/Previous, and length refits
use cancellable 500 ms eased camera transitions (`cross_section_transition.js`).
New requests replace the pending transition; canvas input and close cancel it.
Existing design materials are multiplied by 0.15 opacity while either tool is
active (`scene/authoring_display.js`), with depth writing disabled. This includes
the separate crossover arc group owned by Unfold View, including rebuilt arcs;
existing per-cluster arc alpha continues to multiply the temporary tool fade. Preview and
picker materials are separate. The scoped multiplier follows renderer rebuilds,
preserves concurrent representation/cross-fade opacity changes, and restores
those values when the last tool closes. It does not change saved design fields. `scene/lattice_authoring_stage.js` separates
picker visibility/input from the retained selection and ghost length preview.
Source changes (including deformed frames) notify the controller after the
picker is built. Camera bounds include selected cells, extrusion ends and existing
helix axes, with room beside the tool popup. Molecular authoring commands and
lattice geometry are unchanged. Guide capture exercises the actual UI and is
being updated to reflect this workflow; visual ergonomics remain reviewable.

## Guide representation convention (2026-11-12)

All guide screenshots use Full, except the representations lesson itself.
The shared capture helper checks the global mode and rejects regional overrides,
and records each screenshot's mode in steps.json. Extrude no longer switches to
Cylinders. Tool-specific previews remain the actual application previews.

## Guide capture and startup hints (2026-11-11)

The automatic “Selection: D = dimensions…” startup toast has been removed.
Its delayed localStorage-gated boot timer reappeared in fresh browser contexts
and cluttered guide screenshots. Help → Keyboard Shortcuts remains the on-demand
reference. Smoke checks cover fresh startup and reload with the old flag absent;
guide capture refuses a screenshot containing that hint instead of hiding it.

## Desktop spline Sweep (2026-10-08)

Tools → Sweep uses the shared `tool_popup` shell and slice-plane lattice picker.
`sweep_panel.js` owns the independent popup, ordered point editor, and preview
lifecycle. Step 1/2 exposes source/plane, strands, and lattice selection with
Cancel/Next. Step 2/2 hides and disables the lattice, previews the swept helix
tubes, and exposes Previous/Confirm plus the jobs-style scrollable point box.
Points can be selected in the list or by scene raycast; selected non-origin points
have world-axis translation handles. Dragging updates XYZ fields and debounces the
server preview; leaving the tool detaches controls and restores camera input.
Blunt-end right-click → Sweep seeds the source end and opens step 1.
Coordinates are world XYZ offsets in nm from the footprint centroid;
the first point is fixed. Point spinners step by 1 nm. New paths use an
interpolating cubic spline; continuation clamps its initial tangent to the source
end. The server supplies the preview, arc length, and derived bp count. Frames
use rotation-minimizing transport; no bend-chain approximation is stored.

`POST /api/design/sweep/preview` is read-only. `POST /api/design/sweep` and
`backend.api.headless_build.sweep(...)` share `core/sweep.py`. A single `sweep`
snapshot owns the canonical lattice topology and `SweepParams` deformation.
Feature edit/revert, undo/redo, save/load, and history seek preserve that geometry;
a stable `sweep_id` retains helix identities on edit. Continuation selects a
source helix and start/end, supports coplanar ends plus vacant cells, preserves strand
traversal and assigned sequence (new bases are N), and inherits rigid ownership.
Upstream bend edits replay the continuation's source frame. Edit previews and
gizmo coordinates account for later rigid moves. Preview-only helix paths use
the same transported frames as committed geometry and do not mutate topology.

Assembly launch opens the selected instance's existing part editor, where the
part owns the new topology and the ordinary save-back workflow applies. Curvature
constraints during sweep authoring remain deferred.

Add Loops/Skips now realizes sweeps through `core/sweep_loop_skips.py`: integrate
signed curvature against the transported footprint, quantize each contiguous
signed duplex region separately, and place inside that region away from crossovers,
domain endpoints and end margins. S-bend lobes do not cancel. Existing SQ periodic
and bend/twist marks reserve sites, so sweep marks do not overwrite them. The
existing per-cell density limit and safe-site capacity are enforced at realization;
failure is atomic. Recompute replaces old active marks, preserves ignored geometry,
and commits with a revision guard through the existing undoable feature-log route.
Tests: `tests/test_sweep_loop_skips.py` and `frontend/e2e/sweep_loop_skips.spec.js`.
Tests: `tests/test_sweep.py`, `sweep_panel.test.js`, `sweep_points.test.js`, and
`sweep_preview.test.js`; `frontend/e2e/sweep.spec.js` drives actual point raycasts,
translation handles and the blunt-end context-menu entry as well as history/reload.

<a id="mixed-frame-compatibility-2026-10-06"></a>
- [Mixed-frame compatibility (2026-10-06)](details/project_extrude_preview/01-mixed-frame-compatibility-2026-10-06.md#mixed-frame-compatibility-2026-10-06)

<a id="native-vr-painter-and-length-controls-2026-10-05"></a>
- [Native VR painter and length controls (2026-10-05)](details/project_extrude_preview/01-mixed-frame-compatibility-2026-10-06.md#native-vr-painter-and-length-controls-2026-10-05)

<a id="lattice-cells-colour-coded-forwardreverse--polarity-legend-2026-07-10"></a>
- [Lattice cells colour-coded FORWARD/REVERSE + polarity legend (2026-07-10)](details/project_extrude_preview/01-mixed-frame-compatibility-2026-10-06.md#lattice-cells-colour-coded-forwardreverse--polarity-legend-2026-07-10)

<a id="extrude-entry-rework--sidebar-panel--plane-dropdown--origin-axes-2026-06-11"></a>
- [Extrude-entry rework — sidebar panel + plane dropdown + origin axes (2026-06-11)](details/project_extrude_preview/01-mixed-frame-compatibility-2026-10-06.md#extrude-entry-rework--sidebar-panel--plane-dropdown--origin-axes-2026-06-11)

<a id="length-field-steps-by-the-lattice-crossover-period-2026-06-20"></a>
- [Length field steps by the lattice crossover period (2026-06-20)](details/project_extrude_preview/02-length-field-steps-by-the-lattice-crossover-period-2026-06-20.md#length-field-steps-by-the-lattice-crossover-period-2026-06-20)

<a id="near-end-blunt-continuation--collision-guard-2026-05-25"></a>
- [Near-end blunt continuation + collision guard (2026-05-25)](details/project_extrude_preview/02-length-field-steps-by-the-lattice-crossover-period-2026-06-20.md#near-end-blunt-continuation--collision-guard-2026-05-25)

<a id="ligated-extrudes-adopt-the-connected-strands-colour-2026-05-25"></a>
- [Ligated extrudes adopt the connected strand's colour (2026-05-25)](details/project_extrude_preview/02-length-field-steps-by-the-lattice-crossover-period-2026-06-20.md#ligated-extrudes-adopt-the-connected-strands-colour-2026-05-25)

<a id="continuation-on-gapped-helices--extend-only-the-terminus-interval-2026-05-25"></a>
- [Continuation on GAPPED helices — extend only the terminus interval (2026-05-25)](details/project_extrude_preview/02-length-field-steps-by-the-lattice-crossover-period-2026-06-20.md#continuation-on-gapped-helices--extend-only-the-terminus-interval-2026-05-25)

<a id="reopen-empty-part--empty-space-extrude-menu-2026-05-26"></a>
- [Reopen-empty-part + empty-space "Extrude" menu (2026-05-26)](details/project_extrude_preview/03-reopen-empty-part--empty-space-extrude-menu-2026-05-26.md#reopen-empty-part--empty-space-extrude-menu-2026-05-26)

<a id="minus-extrude-backend-bug-fixed-2026-05-25"></a>
- [Minus-extrude backend bug (fixed 2026-05-25)](details/project_extrude_preview/03-reopen-empty-part--empty-space-extrude-menu-2026-05-26.md#minus-extrude-backend-bug-fixed-2026-05-25)
