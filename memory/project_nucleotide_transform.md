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
