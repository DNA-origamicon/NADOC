"""
Geometric deformation layer — bend and twist transforms.

Applies the ordered list of DeformationOps stored in Design.deformations to
nucleotide positions, producing curved / twisted geometry without touching the
topological layer (strands, domains, crossovers).

Math overview
─────────────
An "accumulated world frame" (spine position + 3×3 rotation R) is propagated
forward from bp=0 to any target bp, processing each DeformationOp in plane_a_bp
order.  Between ops, the spine advances straight along the current tangent.

For each nucleotide at helix h, bp index p, direction d:
  1. (spine_p, R_p, _) = _frame_at_bp(design, p, arm_helices)
  2. axis_p = spine_p + R_p @ cross_section_offset(h)
  3. pos_d  = axis_p  + R_p @ (original_pos − original_axis_at_p)
  4. base_normal and axis_tangent are also rotated by R_p

Twist segment [p1, p2], total angle α_total (radians):
  Spine advances straight; R rotates around current tangent by α_total*(p−p1)/(p2−p1).

Bend segment [p1, p2], radius R_b (nm), direction φ (degrees, 0=+X in cross-section):
  world_dir = R_p1 @ (cos φ, sin φ, 0)   (unit vector perpendicular to tangent)
  Arc angle at bp p: θ(p) = (p−p1)*RISE / R_b
  spine(p) = spine_p1 + R_b*(1−cos θ)*world_dir + R_b*sin(θ)*tangent_p1
  Rotation: _rot_around_axis(cross(tangent, world_dir), θ)

Multi-arm designs (W-shape etc.)
─────────────────────────────────
Each arm is a group of helices whose axis directions are within ~20° of each
other.  _arm_helices_for(design, ref_helix_id) returns the arm containing the
reference helix.  Deformation ops are filtered to those that affect at least
one helix in the arm before propagation.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from backend.core.constants import BASE_DISPLACEMENT, BDNA_RISE_PER_BP
from backend.core.geometry import NucleotidePosition, nucleotide_positions
from backend.core.models import BendParams, TwistParams

if TYPE_CHECKING:
    from backend.core.models import Design, Helix


# ── Rodrigues rotation ─────────────────────────────────────────────────────────


def _rot_around_axis(axis: np.ndarray, angle: float) -> np.ndarray:
    """Return 3×3 rotation matrix for *angle* radians around unit vector *axis*."""
    c, s = math.cos(angle), math.sin(angle)
    t = 1.0 - c
    x, y, z = axis
    return np.array([
        [c + x*x*t,   x*y*t - z*s, x*z*t + y*s],
        [y*x*t + z*s, c + y*y*t,   y*z*t - x*s],
        [z*x*t - y*s, z*y*t + x*s, c + z*z*t  ],
    ], dtype=float)


# ── Bundle centroid and initial tangent ────────────────────────────────────────


def _bundle_centroid_and_tangent(helices: list["Helix"]) -> tuple[np.ndarray, np.ndarray]:
    """Return (centroid_at_bp0, unit_tangent) for the given helix list."""
    if not helices:
        return np.zeros(3), np.array([0.0, 0.0, 1.0])
    starts = np.array([h.axis_start.to_array() for h in helices])
    centroid = starts.mean(axis=0)
    h0 = helices[0]
    axis = h0.axis_end.to_array() - h0.axis_start.to_array()
    norm = np.linalg.norm(axis)
    tangent = axis / norm if norm > 1e-12 else np.array([0.0, 0.0, 1.0])
    return centroid, tangent


def _arm_helices_for(design: "Design", ref_helix_id: str) -> list["Helix"]:
    """
    Return helices whose axis direction is within ~20° of the reference helix.

    Uses dot-product threshold 0.94 (≈ cos 20°).  Falls back to all helices
    when the reference helix is not found.
    """
    ref = next((h for h in design.helices if h.id == ref_helix_id), None)
    if ref is None:
        return list(design.helices)
    ref_axis = ref.axis_end.to_array() - ref.axis_start.to_array()
    ref_norm = np.linalg.norm(ref_axis)
    if ref_norm < 1e-12:
        return list(design.helices)
    ref_dir = ref_axis / ref_norm
    result = []
    for h in design.helices:
        ax = h.axis_end.to_array() - h.axis_start.to_array()
        n = np.linalg.norm(ax)
        if n < 1e-12:
            continue
        d = abs(np.dot(ax / n, ref_dir))
        if d >= 0.94:
            result.append(h)
    return result if result else list(design.helices)


# ── Initial cross-section frame ────────────────────────────────────────────────


def _initial_cross_section_frame(
    tangent_0: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (initial_right, initial_up) for the undeformed cross-section.

    Determined by the dominant axis of tangent_0:
      XY plane (tangent ≈ ±Z): lx → world X, ly → world Y
      XZ plane (tangent ≈ ±Y): lx → world X, ly → world Z
      YZ plane (tangent ≈ ±X): lx → world Y, ly → world Z
    """
    ax = int(np.argmax(np.abs(tangent_0)))
    if ax == 2:    # Z-dominant → XY plane bundle
        return np.array([1., 0., 0.]), np.array([0., 1., 0.])
    elif ax == 1:  # Y-dominant → XZ plane bundle
        return np.array([1., 0., 0.]), np.array([0., 0., 1.])
    else:          # X-dominant → YZ plane bundle
        return np.array([0., 1., 0.]), np.array([0., 0., 1.])


# ── Resolve TwistParams to radians ────────────────────────────────────────────


def _resolve_twist_rad(params: TwistParams, p1: int, p2: int) -> float:
    if params.total_degrees is not None:
        return math.radians(params.total_degrees)
    if params.degrees_per_nm is not None:
        length_nm = (p2 - p1) * BDNA_RISE_PER_BP
        return math.radians(params.degrees_per_nm * length_nm)
    return 0.0


# ── Core frame propagation ────────────────────────────────────────────────────


def _frame_at_bp(
    design: "Design",
    target_bp: int,
    arm_helices: list["Helix"] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Return (spine_position, R_matrix, tangent) at *target_bp*.

    spine_position : world 3D position of the bundle centroid at this bp.
    R_matrix       : 3×3 rotation — original cross-section frame → world frame.
    tangent        : current spine tangent unit vector.

    arm_helices    : subset of helices to use for centroid/tangent and for
                     filtering ops.  Defaults to all design helices.
    """
    helices = arm_helices if arm_helices is not None else list(design.helices)
    centroid_0, tangent_0 = _bundle_centroid_and_tangent(helices)

    # Only apply ops that affect at least one helix in this arm.
    arm_ids = {h.id for h in helices}
    relevant_ops = [
        op for op in design.deformations
        if not op.affected_helix_ids or bool(arm_ids & set(op.affected_helix_ids))
    ]

    spine   = centroid_0.copy()
    tangent = tangent_0.copy()
    R       = np.eye(3)
    current_bp = 0

    ops = sorted(relevant_ops, key=lambda op: op.plane_a_bp)

    for op in ops:
        if target_bp <= op.plane_a_bp:
            break

        # Advance straight to op.plane_a_bp
        if current_bp < op.plane_a_bp:
            spine = spine + tangent * (op.plane_a_bp - current_bp) * BDNA_RISE_PER_BP
            current_bp = op.plane_a_bp

        seg_len = op.plane_b_bp - op.plane_a_bp
        if seg_len <= 0:
            continue

        arc_bp = min(target_bp, op.plane_b_bp) - op.plane_a_bp

        if isinstance(op.params, TwistParams):
            total_rad = _resolve_twist_rad(op.params, op.plane_a_bp, op.plane_b_bp)
            spine = spine + tangent * arc_bp * BDNA_RISE_PER_BP
            alpha = total_rad * arc_bp / seg_len
            if abs(alpha) > 1e-12:
                R_twist = _rot_around_axis(tangent, alpha)
                R       = R_twist @ R
                # tangent direction unchanged by twist

        elif isinstance(op.params, BendParams):
            angle_rad = math.radians(op.params.angle_deg)
            phi       = math.radians(op.params.direction_deg)

            # Zero angle → straight advance (no bending)
            if abs(angle_rad) < 1e-9:
                spine      = spine + tangent * arc_bp * BDNA_RISE_PER_BP
                current_bp = min(target_bp, op.plane_b_bp)
                if target_bp <= op.plane_b_bp:
                    break
                continue

            # radius derived from total arc angle and segment length
            radius = seg_len * BDNA_RISE_PER_BP / angle_rad

            # Bend direction in world space (perpendicular to current tangent)
            local_dir = np.array([math.cos(phi), math.sin(phi), 0.0])
            world_dir = R @ local_dir
            world_dir = world_dir - np.dot(world_dir, tangent) * tangent
            wd_norm   = np.linalg.norm(world_dir)
            if wd_norm < 1e-9:
                spine = spine + tangent * arc_bp * BDNA_RISE_PER_BP
            else:
                world_dir /= wd_norm
                # theta scales proportionally with arc length
                theta = arc_bp * angle_rad / seg_len

                # Arc position: spine_p1 + R_b*(1-cosθ)*world_dir + R_b*sinθ*tangent
                spine = (spine
                         + radius * (1.0 - math.cos(theta)) * world_dir
                         + radius * math.sin(theta) * tangent)

                # Rotate frame around binormal = cross(tangent, world_dir)
                binormal = np.cross(tangent, world_dir)
                bn_norm  = np.linalg.norm(binormal)
                if bn_norm > 1e-9:
                    binormal /= bn_norm
                    R_bend  = _rot_around_axis(binormal, theta)
                    R       = R_bend @ R
                    tangent = R_bend @ tangent
                    tangent /= np.linalg.norm(tangent)

        current_bp = min(target_bp, op.plane_b_bp)
        if target_bp <= op.plane_b_bp:
            break

    # Advance straight to target_bp
    if current_bp < target_bp:
        spine = spine + tangent * (target_bp - current_bp) * BDNA_RISE_PER_BP

    return spine, R, tangent


# ── Public API ────────────────────────────────────────────────────────────────


def deformed_nucleotide_positions(
    helix: "Helix",
    design: "Design",
) -> list[NucleotidePosition]:
    """
    Return nucleotide positions for *helix* with all deformation ops applied.

    Falls back to ``nucleotide_positions(helix)`` unchanged when
    ``design.deformations`` is empty.
    """
    if not design.deformations:
        return nucleotide_positions(helix)

    arm_helices = _arm_helices_for(design, helix.id)
    centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

    # Helix cross-section offset (perpendicular component of axis_start − centroid)
    h_start   = helix.axis_start.to_array()
    cs_raw    = h_start - centroid_0
    cs_offset = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0

    orig_nucs = nucleotide_positions(helix)
    result: list[NucleotidePosition] = []

    for nuc in orig_nucs:
        p = nuc.bp_index

        # Original helix axis point at this bp (straight)
        axis_orig = h_start + tangent_0 * p * BDNA_RISE_PER_BP

        # Nucleotide offset from its helix axis (radial direction in helix XY-plane)
        nuc_local = nuc.position - axis_orig

        # World frame at this bp
        spine_p, R_p, _ = _frame_at_bp(design, p, arm_helices)

        # Deformed positions
        axis_deformed    = spine_p + R_p @ cs_offset
        pos_d            = axis_deformed + R_p @ nuc_local
        base_normal_d    = R_p @ nuc.base_normal
        base_pos_d       = pos_d + BASE_DISPLACEMENT * base_normal_d
        axis_tangent_d   = R_p @ nuc.axis_tangent

        result.append(NucleotidePosition(
            helix_id     = nuc.helix_id,
            bp_index     = nuc.bp_index,
            direction    = nuc.direction,
            position     = pos_d,
            base_position= base_pos_d,
            base_normal  = base_normal_d,
            axis_tangent = axis_tangent_d,
        ))

    return result


_AXIS_SAMPLE_STEP = 7  # one sample per full twist period


def deformed_helix_axes(design: "Design") -> list[dict]:
    """
    Return deformed axis positions for each helix.

    Each element:
      { helix_id: str, start: [x,y,z], end: [x,y,z],
        samples: [[x,y,z], ...] }

    ``samples`` traces the helix centre-line at bp 0, STEP, 2*STEP, …, length_bp−1.
    For an undeformed design, samples=[start, end] (straight line).
    """
    if not design.deformations:
        return [
            {
                "helix_id": h.id,
                "start":    h.axis_start.to_array().tolist(),
                "end":      h.axis_end.to_array().tolist(),
                "samples":  [
                    h.axis_start.to_array().tolist(),
                    h.axis_end.to_array().tolist(),
                ],
            }
            for h in design.helices
        ]

    result: list[dict] = []

    for h in design.helices:
        arm_helices = _arm_helices_for(design, h.id)
        centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

        h_start   = h.axis_start.to_array()
        cs_raw    = h_start - centroid_0
        cs_offset = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0

        # Collect sample bps: 0, step, 2*step, …, length_bp−1
        sample_bps: list[int] = list(range(0, h.length_bp, _AXIS_SAMPLE_STEP))
        last_bp = max(0, h.length_bp - 1)
        if not sample_bps or sample_bps[-1] != last_bp:
            sample_bps.append(last_bp)

        samples: list[list[float]] = []
        for bp in sample_bps:
            spine_p, R_p, _ = _frame_at_bp(design, bp, arm_helices)
            samples.append((spine_p + R_p @ cs_offset).tolist())

        result.append({
            "helix_id": h.id,
            "start":    samples[0],
            "end":      samples[-1],
            "samples":  samples,
        })

    return result


def deformed_frame_at_bp(
    design: "Design",
    source_bp: int,
    ref_helix_id: str | None = None,
) -> dict:
    """
    Return the deformed cross-section frame at *source_bp*.

    When *ref_helix_id* is given the arm containing that helix is used;
    otherwise all helices are used.

    Returns a dict with:
      grid_origin  : [x,y,z] — world position of honeycomb (lx=0, ly=0)
      axis_dir     : [x,y,z] — unit tangent at source_bp
      frame_right  : [x,y,z] — unit vector for +lx (col direction)
      frame_up     : [x,y,z] — unit vector for +ly (row direction)

    To place a honeycomb cell at lattice coordinates (lx, ly):
      world_pos = grid_origin
                  + frame_right * (lx * HONEYCOMB_COL_PITCH)
                  + frame_up    * (ly * HONEYCOMB_ROW_PITCH)
    """
    arm = _arm_helices_for(design, ref_helix_id) if ref_helix_id else list(design.helices)
    centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm)

    spine_p, R_p, tangent = _frame_at_bp(design, source_bp, arm)

    # The grid origin is the world point corresponding to honeycomb (lx=0, ly=0).
    # In the undeformed frame: (lx=0, ly=0) → world position = centroid_0.
    # The cross-section offset from centroid to (0,0) is:
    #   cs_raw_00    = -centroid_0   (if helix axes originate from world origin; but
    #                                  generally it's 0 − centroid = -centroid_0 for
    #                                  the "zero-lattice-cell" helix)
    # We need the component perpendicular to the original tangent:
    #   cs_offset_00 = cs_raw_00 − dot(cs_raw_00, tangent_0) * tangent_0
    # Then the deformed grid origin is:
    #   grid_origin  = spine_p + R_p @ cs_offset_00
    #
    # For the common case where the bundle centroid IS the (0,0) honeycomb point
    # (no offset), cs_offset_00 = 0, grid_origin = spine_p.  In practice the
    # centroid will differ from (0,0) only when lattice cells are not symmetric
    # around the origin; both cases are handled correctly here.
    cs_raw_00    = np.zeros(3) - centroid_0
    cs_offset_00 = cs_raw_00 - np.dot(cs_raw_00, tangent_0) * tangent_0
    grid_origin  = spine_p + R_p @ cs_offset_00

    initial_right, initial_up = _initial_cross_section_frame(tangent_0)

    return {
        "grid_origin":  grid_origin.tolist(),
        "axis_dir":     tangent.tolist(),
        "frame_right":  (R_p @ initial_right).tolist(),
        "frame_up":     (R_p @ initial_up).tolist(),
    }


def helices_crossing_planes(design: "Design", plane_a_bp: int, plane_b_bp: int) -> list[str]:
    """Return IDs of helices whose bp range covers both plane_a_bp and plane_b_bp."""
    lo, hi = min(plane_a_bp, plane_b_bp), max(plane_a_bp, plane_b_bp)
    return [
        h.id for h in design.helices
        if h.length_bp > hi  # bp index hi must be within the helix
    ]
