# Protein conjugation and constrained movement

This document describes the performance and interaction contract for proteins
attached through a conjugate oligo to a design overhang.

## Conjugation-site availability

The conjugation manager evaluates solvent-accessible candidate atoms with a
Shrake–Rupley surface estimate. Candidate discovery does not calculate the full
protein surface: it first selects chemically eligible Lys, Cys, and N-terminal
atoms, uses a `scipy.spatial.cKDTree` to find local occluders, and evaluates the
fixed surface samples for only those candidates with vectorized NumPy distance
tests. Full per-atom SASA remains available for callers that explicitly need it.

`tests/test_conjugation_8scp_performance.py` uses PDB 8SCP as the representative
protein and guards the initial candidate-mapping latency. Run it with:

```bash
uv run pytest tests/test_conjugation_8scp_performance.py
```

The candidate cache remains bounded and thread-safe. Cache keys include protein
geometry and mapping options, so repeated manager visits avoid recomputation
without returning results for stale geometry.

## Conjugated-protein kinematics

Selecting a protein opens the Properties sidebar and activates the standard
Move / Rotate panel. The gizmo is anchored at the rendered protein centroid.
Translation and rotation values are mirrored into the sidebar, and `Tab`
switches between the translate and rotate gizmos while the protein is selected.
The global drill shortcut yields to this protein session.

An overhang-bound conjugate behaves as a two-ball-joint linkage:

1. the overhang anchor is the fixed joint;
2. the conjugate/protein interface is the moving joint;
3. the oligo reach is clamped to the current overhang/conjugate geometry; and
4. the protein remains rigid and can rotate through its full range about its
   centroid while its joint position is projected onto the allowed reach.

Unequal strand lengths caused by resizing are supported. The effective linkage
radius comes from the current attachment geometry rather than assuming both
strands retain their native or equal length.

The attached overhang geometry moves in its domain basis. Captures and live
transforms are filtered by domain IDs, so sibling overhangs and helical-axis
segments on the same stub helix do not move. Beads, slabs, connectors, and axis
segments use the same captured native basis, preserving their NADOC-native
relative positions throughout preview and commit.

## Preview, Apply, Reset, and Cancel

Protein manipulation is transactional:

- Dragging the gizmo or editing sidebar values updates the protein and attached
  DNA live without writing to the design.
- **Apply** sends the exact world-space transform used by the preview. On a
  successful response it creates one `Move protein` Feature Log entry, shows a
  success toast, refreshes authoritative geometry, and preserves the previewed
  bead/slab positions.
- **Reset** restores the pre-move preview and makes Apply a no-op until another
  transform is made.
- **Cancel**, `Escape`, changing selection, or clicking away restores the
  pre-move state without creating a feature.
- Undo and redo replay the saved transform without triggering the expensive
  initial protein-geometry loading path.

The Feature Log follows its newest row on initial display and as entries are
added. If the user scrolls upward, following pauses until they return to the
bottom. Updates received while another left-sidebar tab is visible do not move
that tab's scroll position.

## Regression coverage

The backend tests cover attachment pose composition, unequal-length flexible
segments, constrained endpoints, feature-log creation, and undo/redo. Frontend
unit tests cover the shared preview/commit matrix, centroid pivot, two-joint
limits, sidebar integration, domain-filtered geometry, Apply/Reset/Cancel, toast
notification, and Feature Log bottom-following. The Playwright test verifies
that selecting a protein and pressing `Tab` changes the active gizmo in a real
browser.

```bash
uv run pytest tests/test_conjugation.py tests/test_flexible_segments.py \
  tests/test_protein.py tests/test_conjugation_8scp_performance.py

cd frontend
npm test -- --run src/scene/protein_gizmo.test.js \
  src/scene/protein_subsystem.test.js src/scene/translate_rotate_tool.test.js \
  src/ui/feature_log_panel_scroll.test.js src/ui/keyboard_shortcuts.test.js
npx playwright test e2e/protein_gizmo_tab.spec.js
```
