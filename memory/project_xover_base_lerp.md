---
name: Crossover extra-base placement
description: Representation-neutral residue poses shared by Full and atomistic views; 1xT uses a calibrated local default and simulated frames override it
type: project
originSessionId: 98703278-3f45-4b55-bf2c-d8e8f4a72d22
---
# Crossover extra-base placement

## Current contract

`crossover_extra_base_placements` in Python and `buildCrossoverExtraPlacements` in
JavaScript are mirrored, representation-neutral abstractions. They determine a residue
centre and rigid frame; atom templates, Full beads, slabs, and bead-to-slab connectors
project from that same pose. Do not add downstream offsets in an individual renderer.

For `extra_bases` length 1, the native pose is a junction-local translation and quaternion
calibrated from the two manually assigned residues in `workspace/2hb_1xT.nadoc` on
2026-08-09. Separate records cover direct and reversed chemical traversal. A second,
independent parity bit canonicalises the local 2HB polarity: the calibration fixture is
`FORWARD -> REVERSE`; a `REVERSE -> FORWARD` half-a/half-b junction rotates the residue
frame 180 degrees about the crossover chord (negates its frame bow). This was added after
`workspace/6hbx32_1xT.nadoc` exposed 43/40 sub-1.5 A nonlocal contacts on its two reverse-
polarity interfaces; the canonical frames leave 4/4, matching the other four interfaces.
Do not fold this bit into `sim_reversed`: both members of a reciprocal pair can share 2HB
polarity while having opposite chemical traversal. The source Bézier centre/tangent remain
diagnostic inputs, but are not the rendered 1xT location.
Runs longer than one base retain their existing Bézier/flexible-arc placement until they
receive their own calibrated abstraction.

Placement precedence is:

1. Native abstraction: calibrated local pose for 1xT; legacy arc pose for longer runs.
2. Authored per-residue transform: composes on the native pose in design views.
3. Physical trajectory pose: an oxDNA `("__xb__", crossover_id, k)` frame supplies the
   actual centre-of-mass, `a1`, and `a3`, replacing the native placement for simulated
   atomistic display and oxDNA→NAMD backmapping.

The NAMD seed and relaxed atomistic display deliberately share
`_frame_atomistic_overrides`. The seed reader must use `include_extra_bases=True`; otherwise
the synthetic particle is silently filtered and the NAMD seed falls back to the native
default. NAMD recentres the complete seed globally after reconstruction, which preserves
all relative extra-base coordinates.

## Animated endpoint updates

Extra-base beads/slabs follow crossover endpoint motion during unfold, cadnano, deformation,
and cluster-drag transitions through
`designRenderer.updateExtraBaseArc(crossoverId, posA, ctrl, posB)` followed by one
`flushExtraBaseMeshes()`. The update recomputes the canonical placement; it must not force a
1xT residue back onto the raw arc. Existing calls in `_updateArcPositions()` and
`applyCadnanoPositions()` cover current transition paths.

## Verification pins

- Python/JavaScript parity tests cover both traversal orientations and prove the 1xT pose
  differs from the raw Bézier point while Full and atomistic projections coincide.
- The oxDNA regression moves an actual `__xb__` configuration row and requires all 14 rigid
  sugar/base atoms in the NAMD backmap to match the rendered atomistic pose within
  `1e-9 nm`; linker atoms are excluded because the display uses its fast closure path.
