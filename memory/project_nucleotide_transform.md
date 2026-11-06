# Independent nucleotide transform — implementation scope

## Goal

Allow a user to select one nucleotide, including one crossover extra base, and rigidly
reposition that residue in the atomistic representation to test deliberate NAMD starting
arrangements. The saved `.nadoc`, atomistic viewport, structure export, and direct NAMD
seed must derive the same atom coordinates.

Checkpoint before this work: `7621cf02` (`Decouple transform activation from cluster selection`).

## Coordinate contract

- Identity uses NADOC's existing base keys: `(helix_id, bp_index, direction, copy_k)` for
  ordinary/loop nucleotides and `(__xb__, crossover_id, k)` for crossover inserts.
- A saved pose is a rigid delta `{pivot, translation, rotation}` in world nanometres.
- The delta is applied to every atom in the addressed residue as the final DNA-atom pass,
  after deformation/cluster placement and linker construction.
- Topology, coarse nucleotide geometry, cluster membership, and crossover definitions do
  not change. A strained covalent junction is allowed: testing that starting condition is
  the feature, and NAMD minimisation/declash remains responsible for physical relaxation.
- Direct NAMD builds and atomistic display consume `build_atomistic_model`, so the canonical
  transform belongs there rather than in renderer-only matrices.

## Development slices

1. **Implemented:** canonical model + pure atom transform + persistence/undo API.
2. **Implemented:** atomistic renderer residue picking and a nucleotide transform gizmo using `M`.
3. **In progress:** live preview, apply/cancel, and atomistic refetch are implemented;
   reset/delete controls and atomistic selection highlighting remain.
4. **In progress:** NAMD builder parity and save/reload tests are implemented; stale-target
   pruning/validation and an
   end-to-end crossover-extra-base gesture gate.

## Explicit non-goals

- Moving one atom independently of its nucleotide.
- Rewriting lattice or crossover topology to match the manually posed residue.
- Applying nucleotide poses to a running trajectory; they define a new starting design.

## Native history preview contract (2026-11-03)

The transform preview accepts the native boolean `residue_transformed` axis flag
already emitted by deformation and consumed by the frontend. It retains strict
axis/domain coverage and rejects nonboolean flags. Residue-projected segments
remain visible when reopening a recorded Move; this validation fix does not alter
molecular placement or topology.

## Crossover arcs during desktop residue previews (2026-11-05)

The selected-base/domain tool must refresh the separate crossover arc renderer
after the whole residue batch has moved, including identity restoration on
Reset/Cancel. Updating bead/slab instances and local cones alone leaves
cross-helix arcs stationary. `nucleotide_transform_tool.applyPreviews` now calls
the injected unfold view and crossover-extra renderer once per affected helix
set. Reported example: Gerling2018 with extra T, scaffold positions 33–34
(`gerling_p7560_ss_loop:104:FORWARD` → `h_XY_6_1:71:REVERSE`, authored forced
ligation `p7560_loop_to_bundle`). This is distinct from the cluster move path.
Read-only browser verification on that open document selected scaffold domain 0,
translated it by 5 nm and rotated it by 90° around Z through the desktop
TransformControls callbacks. Both rendered arc endpoints matched their bead
matrices exactly; the unselected endpoint stayed fixed and Escape restored the
selected endpoint exactly. Measurements: `.development-artifacts/crossover-33-34/result.json`.

## Domain drag connector cost (2026-11-05)

`applyResidueTransformMatrix` must refresh only its own slab connector. Its old
whole-design refresh repeated for every selected residue: Gerling scaffold domain
0 rewrote 33 × 15,867 = 523,611 connectors per input. The helper now accepts an
optional slab subset; other callers retain the full refresh by default.
An identical read-only browser trace measured preview-handler median/p95 falling
from 162.9/173.9 ms to 2.6/3.3 ms, with 33 connector writes and exact 33–34 arc
attachment. Headless software-raster frame intervals are not desktop FPS evidence.
Measurements: `.development-artifacts/domain0-preview-performance/{baseline,optimized}.json`.
`helix_renderer.residue_preview.test.js` checks sparse writes, rigid attachment
endpoints, unchanged unselected connectors, colors and cancellation.
