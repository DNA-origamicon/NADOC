"""Pure, representation-specific projections shared by the native VR snapshot.

Topology and residue placement remain owned by the regular NADOC model and geometry
modules. This module only converts those authoritative records into Full-view primitive
poses; keeping that conversion pure makes numeric desktop/VR parity testable without an
OpenXR runtime.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.core.atomistic_helpers import crossover_extra_base_placements


@dataclass(frozen=True, slots=True)
class CrossoverExtraBaseFullProjection:
    """One crossover-insert bead, slab, and bead-to-slab attachment pose."""

    geometric_index: int
    sim_k: int
    base: str
    bead_center: np.ndarray
    slab_center: np.ndarray
    slab_axis_x: np.ndarray
    slab_axis_y: np.ndarray
    slab_axis_z: np.ndarray
    slab_corner: np.ndarray


def _base_centroid(base: str) -> np.ndarray:
    """Mean heavy-atom base-ring site from the atom template of record."""
    # Import lazily: atomistic imports atomistic_helpers, so a module-level import
    # would create a cycle. Reading the template here avoids a second copied centroid
    # table drifting away from both the atomistic model and the desktop Full renderer.
    from backend.core.atomistic import BASE_TEMPLATES, _BASE_CHAR_TO_RESIDUE

    residue = _BASE_CHAR_TO_RESIDUE.get(base.upper(), "DT")
    atom_defs, _ = BASE_TEMPLATES[residue]
    return np.mean(
        np.asarray([[atom[2], atom[3], atom[4]] for atom in atom_defs], dtype=float),
        axis=0,
    )


def crossover_extra_base_full_projections(
    first_nucleotide: dict,
    second_nucleotide: dict,
    sequence: str,
    *,
    sim_reversed: bool,
    local_frame_reversed: bool,
) -> list[CrossoverExtraBaseFullProjection]:
    """Project canonical crossover residue frames into desktop-Full slab geometry.

    Slab local axes exactly mirror ``crossoverExtraSlabQuaternion`` in
    ``crossover_extra_placement.js``: box X follows residue-frame Y, box Y follows
    residue-frame Z, and box Z follows residue-frame X. The attachment point is the
    canonical +X / backbone-facing-Z corner used by ``slabConnectionCorner``.
    """
    if not sequence:
        return []
    placements = crossover_extra_base_placements(
        np.asarray(first_nucleotide["backbone_position"], dtype=float),
        np.asarray(second_nucleotide["backbone_position"], dtype=float),
        np.asarray(first_nucleotide["axis_tangent"], dtype=float),
        np.asarray(second_nucleotide["axis_tangent"], dtype=float),
        len(sequence),
        sim_reversed=sim_reversed,
        local_frame_reversed=local_frame_reversed,
    )
    result = []
    for placement in placements:
        frame = np.asarray(placement["frame_rotation"], dtype=float)
        bead_center = np.asarray(placement["center"], dtype=float)
        base = sequence[int(placement["sim_k"])].upper()
        slab_center = bead_center + frame @ _base_centroid(base)
        axis_x = frame[:, 1] * 0.30
        axis_y = frame[:, 2] * 0.06
        axis_z = frame[:, 0] * 0.70
        z_sign = (
            -1.0 if float(np.dot(bead_center - slab_center, frame[:, 0])) < 0 else 1.0
        )
        slab_corner = slab_center + frame[:, 1] * 0.15 + frame[:, 0] * (z_sign * 0.35)
        result.append(
            CrossoverExtraBaseFullProjection(
                geometric_index=int(placement["geometric_index"]),
                sim_k=int(placement["sim_k"]),
                base=base,
                bead_center=bead_center,
                slab_center=slab_center,
                slab_axis_x=axis_x,
                slab_axis_y=axis_y,
                slab_axis_z=axis_z,
                slab_corner=slab_corner,
            )
        )
    return result
