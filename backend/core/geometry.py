"""
Geometric layer — nucleotide position calculations.

This module derives 3D nucleotide positions and orientation frames from the
topological Helix model.  It operates purely on Helix objects and returns
NucleotidePosition records; it never modifies Design or any topology model.

Coordinate convention
─────────────────────
The helix axis runs from helix.axis_start to helix.axis_end.

FORWARD strand backbone at bp i:
    backbone = axis_point + HELIX_RADIUS × radial(twist_angle)

REVERSE strand backbone at bp i:
    backbone = axis_point + HELIX_RADIUS × radial(twist_angle + MINOR_GROOVE_ANGLE)

where twist_angle = phase_offset + i × BDNA_TWIST_PER_BP_RAD.

MINOR_GROOVE_ANGLE = 120°.  The REVERSE strand is NOT antipodal to FORWARD.
The 120° offset produces the minor groove (120°) and major groove (240°),
consistent with B-DNA crystallographic structure.

Base normals are cross-strand vectors, NOT inward radials:
    FORWARD base_normal = normalize(REVERSE_backbone − FORWARD_backbone)
    REVERSE base_normal = −FORWARD_base_normal

Base bead is displaced from the backbone along the base_normal:
    base_position = backbone + BASE_DISPLACEMENT × base_normal

B-DNA parameters (all from constants.py, never hardcoded here):
  rise              = 0.334 nm/bp
  twist             = 34.3 deg/bp
  helix radius      = 1.0 nm
  minor groove      = 120°
  base displacement = 0.3 nm
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List

import numpy as np

from backend.core.constants import (
    BASE_DISPLACEMENT,
    BDNA_MINOR_GROOVE_ANGLE_RAD,
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_RAD,
    HELIX_RADIUS,
)
from backend.core.models import Direction, Helix


@dataclass(frozen=True)
class NucleotidePosition:
    """
    Position and orientation frame for a single nucleotide.

    Attributes
    ----------
    helix_id : str
    bp_index : int  (0-based)
    direction : Direction
    position : np.ndarray shape (3,)
        Backbone (sugar-phosphate) bead, in nm, world frame.
        Sits at HELIX_RADIUS from the helix axis.
    base_position : np.ndarray shape (3,)
        Base bead, in nm.  Displaced from backbone by BASE_DISPLACEMENT
        along base_normal (the cross-strand direction).
    base_normal : np.ndarray shape (3,)
        Unit vector pointing from this backbone toward the paired strand's
        backbone at the same bp index (cross-strand, NOT inward radial).
        FORWARD: normalize(REVERSE_backbone − FORWARD_backbone).
        REVERSE: −FORWARD_base_normal.
    axis_tangent : np.ndarray shape (3,)
        Unit vector along the helix axis (axis_start → axis_end).
    """
    helix_id: str
    bp_index: int
    direction: Direction
    position: np.ndarray       # backbone bead
    base_position: np.ndarray  # base bead
    base_normal: np.ndarray    # cross-strand unit vector
    axis_tangent: np.ndarray


def _frame_from_helix_axis(axis_vec: np.ndarray) -> np.ndarray:
    """
    Right-handed orthonormal frame whose z-column aligns with axis_vec.
    Returns 3×3 matrix with columns [x_hat, y_hat, z_hat].
    """
    z_hat = axis_vec / np.linalg.norm(axis_vec)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(z_hat, ref)) > 0.9:
        ref = np.array([1.0, 0.0, 0.0])
    x_hat = np.cross(ref, z_hat)
    x_hat /= np.linalg.norm(x_hat)
    y_hat = np.cross(z_hat, x_hat)
    return np.column_stack([x_hat, y_hat, z_hat])


def nucleotide_positions(helix: Helix) -> List[NucleotidePosition]:
    """
    Compute 3D positions for every nucleotide on both strands of *helix*.

    Returns 2 × helix.length_bp NucleotidePosition objects, ordered by
    bp_index (0 … length_bp-1), FORWARD first at each index.
    """
    start    = helix.axis_start.to_array()
    end      = helix.axis_end.to_array()
    axis_vec = end - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")

    axis_hat = axis_vec / length
    frame    = _frame_from_helix_axis(axis_hat)

    results: List[NucleotidePosition] = []

    for bp in range(helix.length_bp):
        axis_point = start + axis_hat * (bp * BDNA_RISE_PER_BP)
        fwd_angle  = helix.phase_offset + bp * BDNA_TWIST_PER_BP_RAD
        rev_angle  = fwd_angle + BDNA_MINOR_GROOVE_ANGLE_RAD

        # Radial unit vectors in the helix's local XY plane.
        fwd_radial = (math.cos(fwd_angle) * frame[:, 0]
                      + math.sin(fwd_angle) * frame[:, 1])
        rev_radial = (math.cos(rev_angle) * frame[:, 0]
                      + math.sin(rev_angle) * frame[:, 1])

        # Backbone positions — both strands at HELIX_RADIUS from axis.
        fwd_backbone = axis_point + HELIX_RADIUS * fwd_radial
        rev_backbone = axis_point + HELIX_RADIUS * rev_radial

        # Cross-strand base normal: FORWARD points toward REVERSE backbone.
        base_pair_vec = rev_backbone - fwd_backbone
        base_pair_hat = base_pair_vec / np.linalg.norm(base_pair_vec)

        fwd_base_normal = base_pair_hat
        rev_base_normal = -base_pair_hat

        # Base beads displaced from backbone along the cross-strand direction.
        fwd_base = fwd_backbone + BASE_DISPLACEMENT * fwd_base_normal
        rev_base = rev_backbone + BASE_DISPLACEMENT * rev_base_normal

        results.append(NucleotidePosition(
            helix_id=helix.id,
            bp_index=bp,
            direction=Direction.FORWARD,
            position=fwd_backbone,
            base_position=fwd_base,
            base_normal=fwd_base_normal,
            axis_tangent=axis_hat,
        ))
        results.append(NucleotidePosition(
            helix_id=helix.id,
            bp_index=bp,
            direction=Direction.REVERSE,
            position=rev_backbone,
            base_position=rev_base,
            base_normal=rev_base_normal,
            axis_tangent=axis_hat,
        ))

    return results


def helix_axis_point(helix: Helix, bp_index: int) -> np.ndarray:
    """Return the world-space position of the helix axis at *bp_index*."""
    start    = helix.axis_start.to_array()
    end      = helix.axis_end.to_array()
    axis_vec = end - start
    length   = np.linalg.norm(axis_vec)
    if length == 0.0:
        raise ValueError(f"Helix {helix.id!r} has zero-length axis.")
    return start + (axis_vec / length) * (bp_index * BDNA_RISE_PER_BP)
