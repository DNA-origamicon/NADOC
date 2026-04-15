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
from backend.core.geometry import (
    NucleotidePosition,
    nucleotide_positions,
    nucleotide_positions_arrays,
)
from backend.core.models import BendParams, ClusterRigidTransform, Direction, TwistParams

if TYPE_CHECKING:
    from backend.core.models import Design, Helix, LatticeType


# ── Grid normalisation ────────────────────────────────────────────────────────


def _normalize_helix_for_grid(
    helix: "Helix",
    lattice_type: "LatticeType",
) -> "Helix":
    """Return a copy of *helix* with axis and phase derived from grid_pos.

    If helix.grid_pos is None, returns the original helix unchanged.

    The returned copy has:
      axis_start       = (x, y, bp_start * RISE)
      axis_end         = (x, y, (bp_start + length_bp) * RISE)
      phase_offset     = base_phase + bp_start * twist  (local-bp=0 convention)
      twist_per_bp_rad = lattice twist
      direction        = FORWARD/REVERSE from lattice parity rule

    This ensures backbone bead positions are always derived from the canonical
    cadnano2 lattice grid, regardless of the stored axis_start/axis_end values.
    """
    if helix.grid_pos is None:
        return helix
    from backend.core.lattice import helix_canonical_axis
    from backend.core.models import Vec3
    x, y, base_phase, twist = helix_canonical_axis(helix, lattice_type)
    # Bake bp_start into the phase so geometry.py's local_bp=0 corresponds
    # to the correct angle at global bp index bp_start.
    phase     = base_phase + helix.bp_start * twist
    z_start   = helix.bp_start * BDNA_RISE_PER_BP
    z_end     = (helix.bp_start + helix.length_bp) * BDNA_RISE_PER_BP
    row, col  = helix.grid_pos
    direction = Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE
    return helix.model_copy(update={
        "axis_start":       Vec3(x=x, y=y, z=z_start),
        "axis_end":         Vec3(x=x, y=y, z=z_end),
        "phase_offset":     phase,
        "twist_per_bp_rad": twist,
        "direction":        direction,
    })


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


def _rot_around_axis_batched(axis: np.ndarray, angles: np.ndarray) -> np.ndarray:
    """
    Vectorised Rodrigues rotation for a fixed *axis* and multiple *angles*.

    axis   : (3,) unit vector
    angles : (K,) float array of angles in radians
    Returns: (K, 3, 3) rotation matrices
    """
    cos_a = np.cos(angles)   # (K,)
    sin_a = np.sin(angles)   # (K,)
    x, y, z = axis
    # Skew-symmetric cross-product matrix of axis
    K_mat = np.array([[ 0, -z,  y],
                       [ z,  0, -x],
                       [-y,  x,  0]], dtype=float)
    outer = np.outer(axis, axis)   # (3, 3)
    I3    = np.eye(3)
    # Rodrigues: R[k] = cos[k]*I + sin[k]*K + (1−cos[k])*outer(axis,axis)
    return (cos_a[:, None, None] * I3
            + sin_a[:, None, None] * K_mat
            + (1.0 - cos_a)[:, None, None] * outer)  # (K, 3, 3)


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

    Overhang helices are excluded: their axis_start.z is non-zero (positioned at
    the nick Z) which shifts the bundle centroid and displaces overhang nucleotide
    positions when deformations are applied.
    """
    overhang_helix_ids = {o.helix_id for o in design.overhangs}
    ref = next((h for h in design.helices if h.id == ref_helix_id), None)
    if ref is None:
        return [h for h in design.helices if h.id not in overhang_helix_ids]
    ref_axis = ref.axis_end.to_array() - ref.axis_start.to_array()
    ref_norm = np.linalg.norm(ref_axis)
    if ref_norm < 1e-12:
        return [h for h in design.helices if h.id not in overhang_helix_ids]
    ref_dir = ref_axis / ref_norm
    result = []
    for h in design.helices:
        if h.id in overhang_helix_ids:
            continue
        ax = h.axis_end.to_array() - h.axis_start.to_array()
        n = np.linalg.norm(ax)
        if n < 1e-12:
            continue
        d = abs(np.dot(ax / n, ref_dir))
        if d >= 0.94:
            result.append(h)
    return result if result else [h for h in design.helices if h.id not in overhang_helix_ids]


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

    target_bp      : arm-local bp index (0 = axis_start of the arm).
    arm_helices    : subset of helices to use for centroid/tangent and for
                     filtering ops.  Defaults to all design helices.

    DeformationOp.plane_a_bp / plane_b_bp store GLOBAL bp indices.
    This function converts them to arm-local by subtracting arm_bp_start so
    that the planes stay anchored to the correct physical position even when
    the helix is later extended backward (which shifts axis_start and therefore
    the arm-local coordinate origin).
    """
    helices = arm_helices if arm_helices is not None else list(design.helices)
    centroid_0, tangent_0 = _bundle_centroid_and_tangent(helices)

    # Global bp of this arm's axis_start.  Used to convert stored global op
    # planes → arm-local indices for propagation arithmetic.
    arm_bp_start = helices[0].bp_start if helices else 0

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
        # Convert stored global plane indices to arm-local.
        local_a = op.plane_a_bp - arm_bp_start
        local_b = op.plane_b_bp - arm_bp_start

        if target_bp <= local_a:
            break

        # Advance straight to local_a
        if current_bp < local_a:
            spine = spine + tangent * (local_a - current_bp) * BDNA_RISE_PER_BP
            current_bp = local_a

        seg_len = local_b - local_a   # equals op.plane_b_bp − op.plane_a_bp
        if seg_len <= 0:
            continue

        arc_bp = min(target_bp, local_b) - local_a

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
                current_bp = min(target_bp, local_b)
                if target_bp <= local_b:
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

        current_bp = min(target_bp, local_b)
        if target_bp <= local_b:
            break

    # Advance straight to target_bp
    if current_bp < target_bp:
        spine = spine + tangent * (target_bp - current_bp) * BDNA_RISE_PER_BP

    return spine, R, tangent


# ── Public API ────────────────────────────────────────────────────────────────


def _rot_from_quaternion(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """Return a 3×3 rotation matrix from a unit quaternion [x, y, z, w]."""
    return np.array([
        [1 - 2*(qy*qy + qz*qz),     2*(qx*qy - qz*qw),     2*(qx*qz + qy*qw)],
        [    2*(qx*qy + qz*qw), 1 - 2*(qx*qx + qz*qz),     2*(qy*qz - qx*qw)],
        [    2*(qx*qz - qy*qw),     2*(qy*qz + qx*qw), 1 - 2*(qx*qx + qy*qy)],
    ], dtype=float)


def _apply_cluster_rigid_transform(
    positions: list[NucleotidePosition],
    cluster: ClusterRigidTransform,
) -> list[NucleotidePosition]:
    """
    Apply a rigid-body transform (rotate around pivot, then translate) to a
    list of NucleotidePosition objects.

    The transform matches the Three.js TransformControls convention:
      1. Subtract pivot (move pivot to origin).
      2. Rotate by quaternion.
      3. Add pivot back.
      4. Add translation.

    Direction-only vectors (base_normal, axis_tangent) are rotated but not
    shifted by pivot or translation.
    """
    R     = _rot_from_quaternion(*cluster.rotation)
    pivot = np.array(cluster.pivot,       dtype=float)
    trans = np.array(cluster.translation, dtype=float)

    out: list[NucleotidePosition] = []
    for nuc in positions:
        pos_d    = R @ (nuc.position     - pivot) + pivot + trans
        base_d   = R @ (nuc.base_position - pivot) + pivot + trans
        normal_d = R @ nuc.base_normal
        tang_d   = R @ nuc.axis_tangent
        out.append(NucleotidePosition(
            helix_id      = nuc.helix_id,
            bp_index      = nuc.bp_index,
            direction     = nuc.direction,
            position      = pos_d,
            base_position = base_d,
            base_normal   = normal_d,
            axis_tangent  = tang_d,
        ))
    return out


def _cluster_for_helix(design: "Design", helix_id: str) -> ClusterRigidTransform | None:
    """Return the first ClusterRigidTransform that contains *helix_id*, or None.
    Used by callers that only need one cluster (e.g. deformation arm scoping)."""
    for c in design.cluster_transforms:
        if helix_id in c.helix_ids:
            return c
    return None


def _clusters_for_helix(design: "Design", helix_id: str) -> list[ClusterRigidTransform]:
    """Return all ClusterRigidTransforms whose helix_ids include *helix_id*.
    A helix can belong to multiple domain-level clusters on shared helices."""
    return [c for c in design.cluster_transforms if helix_id in c.helix_ids]


def _apply_cluster_transforms_domain_aware(
    arrs: dict,
    clusters: list[ClusterRigidTransform],
    helix: "Helix",
    design: "Design",
) -> dict:
    """Apply cluster rigid transforms to a nucleotide-positions array dict.

    Helix-level clusters (domain_ids empty): transform is applied to all nucleotides.
    Domain-level clusters (domain_ids non-empty): transform is applied only to
    nucleotides whose (bp_index, direction) falls within one of the cluster's
    domain refs on this helix.

    Multiple domain-level clusters may coexist on shared helices (e.g. two scaffold
    clusters that both traverse helices 44-49).  Each transforms its own disjoint
    subset of nucleotides, allowing independent movement after a committed drag.
    """
    if not clusters:
        return arrs

    any_domain_level = any(c.domain_ids for c in clusters)

    if not any_domain_level:
        # Fast path: single helix-level cluster applies to all nucleotides.
        return _apply_cluster_rigid_transform_arrays(arrs, clusters[0])

    # Domain-level path: selectively overwrite per-cluster subsets.
    result = {
        k: (v.copy() if isinstance(v, np.ndarray) else v)
        for k, v in arrs.items()
    }

    strand_by_id = {s.id: s for s in design.strands}

    for cluster in clusters:
        if not cluster.domain_ids:
            # Helix-level cluster mixed with domain-level ones — skip; this
            # configuration should not arise from normal cluster creation.
            continue

        # Build boolean mask: True for nucleotides that belong to this cluster
        # on this specific helix.
        M = len(arrs['bp_indices'])
        mask = np.zeros(M, dtype=bool)

        for dr in cluster.domain_ids:
            strand = strand_by_id.get(dr.strand_id)
            if strand is None or dr.domain_index >= len(strand.domains):
                continue
            dom = strand.domains[dr.domain_index]
            if dom.helix_id != helix.id:
                continue  # domain is on a different helix
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            dir_int = 0 if dom.direction == Direction.FORWARD else 1
            mask |= (
                (arrs['bp_indices'] >= lo) &
                (arrs['bp_indices'] <= hi) &
                (arrs['directions'] == dir_int)
            )

        if not mask.any():
            continue

        # Transform all positions then copy only the masked rows into result.
        transformed = _apply_cluster_rigid_transform_arrays(arrs, cluster)
        for key in ('positions', 'base_positions', 'base_normals', 'axis_tangents'):
            result[key][mask] = transformed[key][mask]

    return result


def _apply_cluster_rigid_transform_arrays(
    arrs: dict,
    cluster: ClusterRigidTransform,
) -> dict:
    """
    Apply a rigid-body transform to a nucleotide_positions_arrays dict.

    The transform matches _apply_cluster_rigid_transform: rotate around pivot then
    translate.  Point arrays (positions, base_positions) are shifted; direction arrays
    (base_normals, axis_tangents) are only rotated.

    Uses vectorised (N, 3) @ R.T to apply the same rotation to all N nucleotides in
    one C-level call instead of N separate matrix–vector products.
    """
    R     = _rot_from_quaternion(*cluster.rotation)  # (3, 3)
    pivot = np.array(cluster.pivot,       dtype=float)
    trans = np.array(cluster.translation, dtype=float)

    def _xf_pos(pts: np.ndarray) -> np.ndarray:   # (N, 3)
        return (pts - pivot) @ R.T + pivot + trans

    def _xf_dir(vecs: np.ndarray) -> np.ndarray:  # (N, 3)
        return vecs @ R.T

    return {
        'helix_id':       arrs['helix_id'],
        'bp_indices':     arrs['bp_indices'],
        'local_bps':      arrs['local_bps'],
        'directions':     arrs['directions'],
        'positions':      _xf_pos(arrs['positions']),
        'base_positions': _xf_pos(arrs['base_positions']),
        'base_normals':   _xf_dir(arrs['base_normals']),
        'axis_tangents':  _xf_dir(arrs['axis_tangents']),
    }


def _precompute_arm_frames(
    design: "Design",
    arm_helices: list["Helix"],
    arm_min_bp: int,
    max_local_bp: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute deformation frames for all arm-local bp indices 0 … max_local_bp.

    Runs the same sequential deformation propagation as _frame_at_bp but stores
    the frame (spine, R, tangent) at every bp in one pass — O(D + M) instead of
    the O(D × M) that results from calling _frame_at_bp once per nucleotide.

    Within each op segment the arc/twist math is evaluated for all bps in that
    segment simultaneously using vectorised numpy ops.

    Returns
    -------
    spines   : (M, 3)    world spine positions
    Rs       : (M, 3, 3) rotation matrices  (cross-section → world)
    tangents : (M, 3)    world tangent unit vectors
    where M = max_local_bp + 1.
    """
    M = max_local_bp + 1
    spines_out = np.empty((M, 3),    dtype=float)
    Rs_out     = np.empty((M, 3, 3), dtype=float)
    tans_out   = np.empty((M, 3),    dtype=float)

    centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

    arm_ids = {h.id for h in arm_helices}
    relevant_ops = [
        op for op in design.deformations
        if not op.affected_helix_ids or bool(arm_ids & set(op.affected_helix_ids))
    ]
    ops = sorted(relevant_ops, key=lambda op: op.plane_a_bp)

    # Running frame state — always represents the frame at local bp `filled_up_to`.
    spine        = centroid_0.copy()
    tangent      = tangent_0.copy()
    R            = np.eye(3, dtype=float)
    filled_up_to = 0  # next array index that still needs to be written

    for op in ops:
        local_a = op.plane_a_bp - arm_min_bp
        local_b = op.plane_b_bp - arm_min_bp
        seg_len = local_b - local_a
        if seg_len <= 0:
            continue
        if local_a >= M:
            break  # op starts beyond our range

        # ── Straight segment before this op: [filled_up_to, min(local_a, M)) ──
        seg_end = min(local_a, M)
        if filled_up_to < seg_end:
            idxs  = np.arange(filled_up_to, seg_end)
            steps = (idxs - filled_up_to).astype(float)
            spines_out[filled_up_to:seg_end] = spine + tangent * steps[:, None] * BDNA_RISE_PER_BP
            Rs_out[filled_up_to:seg_end]     = R
            tans_out[filled_up_to:seg_end]   = tangent

        # Advance spine to local_a (may be a backward step if local_a < filled_up_to,
        # which can happen when an op starts before the arm's bp_start; handled correctly
        # because adv can be negative and the op's steps = bps - local_a compensate).
        spine        = spine + tangent * (local_a - filled_up_to) * BDNA_RISE_PER_BP
        filled_up_to = local_a

        # ── Op segment: [max(local_a, 0), min(local_b, M)) ──
        op_start = max(local_a, 0)
        op_end   = min(local_b, M)

        if isinstance(op.params, TwistParams):
            total_rad = _resolve_twist_rad(op.params, op.plane_a_bp, op.plane_b_bp)

            if op_start < op_end:
                bps    = np.arange(op_start, op_end)
                steps  = (bps - local_a).astype(float)
                spines_out[op_start:op_end] = spine + tangent * steps[:, None] * BDNA_RISE_PER_BP
                tans_out[op_start:op_end]   = tangent  # twist does not rotate tangent
                alphas    = total_rad * steps / seg_len
                R_twists  = _rot_around_axis_batched(tangent, alphas)  # (K, 3, 3)
                Rs_out[op_start:op_end] = R_twists @ R  # (K, 3, 3)

            # Advance state: spine moves straight, R rotates by the angle at op_end.
            spine        = spine + tangent * (op_end - local_a) * BDNA_RISE_PER_BP
            filled_up_to = op_end
            partial_steps = op_end - local_a
            alpha_at_end  = total_rad * partial_steps / seg_len
            if abs(alpha_at_end) > 1e-12:
                R = _rot_around_axis(tangent, alpha_at_end) @ R

        elif isinstance(op.params, BendParams):
            angle_rad = math.radians(op.params.angle_deg)
            phi       = math.radians(op.params.direction_deg)

            if abs(angle_rad) < 1e-9:
                # Zero bend: straight advance through op range.
                if op_start < op_end:
                    idxs  = np.arange(op_start, op_end)
                    steps = (idxs - local_a).astype(float)
                    spines_out[op_start:op_end] = spine + tangent * steps[:, None] * BDNA_RISE_PER_BP
                    Rs_out[op_start:op_end]     = R
                    tans_out[op_start:op_end]   = tangent
                spine        = spine + tangent * (op_end - local_a) * BDNA_RISE_PER_BP
                filled_up_to = op_end
                continue

            radius = seg_len * BDNA_RISE_PER_BP / angle_rad

            local_dir = np.array([math.cos(phi), math.sin(phi), 0.0])
            world_dir = R @ local_dir
            world_dir = world_dir - np.dot(world_dir, tangent) * tangent
            wd_norm   = np.linalg.norm(world_dir)

            if wd_norm < 1e-9:
                # Degenerate direction: straight advance.
                if op_start < op_end:
                    idxs  = np.arange(op_start, op_end)
                    steps = (idxs - local_a).astype(float)
                    spines_out[op_start:op_end] = spine + tangent * steps[:, None] * BDNA_RISE_PER_BP
                    Rs_out[op_start:op_end]     = R
                    tans_out[op_start:op_end]   = tangent
                spine        = spine + tangent * seg_len * BDNA_RISE_PER_BP
                filled_up_to = op_end
                continue

            world_dir /= wd_norm
            binormal = np.cross(tangent, world_dir)
            bn_norm  = np.linalg.norm(binormal)
            if bn_norm > 1e-9:
                binormal /= bn_norm

            if op_start < op_end:
                bps    = np.arange(op_start, op_end)
                steps  = (bps - local_a).astype(float)
                thetas = steps * angle_rad / seg_len
                cos_t  = np.cos(thetas)
                sin_t  = np.sin(thetas)

                spines_out[op_start:op_end] = (
                    spine
                    + radius * (1.0 - cos_t)[:, None] * world_dir
                    + radius * sin_t[:, None] * tangent
                )
                if bn_norm > 1e-9:
                    R_bends   = _rot_around_axis_batched(binormal, thetas)  # (K, 3, 3)
                    Rs_out[op_start:op_end] = R_bends @ R               # (K, 3, 3)
                    t_rot = R_bends @ tangent                            # (K, 3)
                    norms = np.linalg.norm(t_rot, axis=1, keepdims=True)
                    tans_out[op_start:op_end] = t_rot / np.where(norms > 1e-12, norms, 1.0)
                else:
                    Rs_out[op_start:op_end]   = R
                    tans_out[op_start:op_end] = tangent

            # Advance state to op_end.
            partial_steps = op_end - local_a
            theta_end     = partial_steps * angle_rad / seg_len
            cos_e, sin_e  = math.cos(theta_end), math.sin(theta_end)
            spine = (spine
                     + radius * (1.0 - cos_e) * world_dir
                     + radius * sin_e * tangent)
            filled_up_to = op_end
            if bn_norm > 1e-9:
                R_end   = _rot_around_axis(binormal, theta_end)
                R       = R_end @ R
                tangent = R_end @ tangent
                tn = np.linalg.norm(tangent)
                if tn > 1e-12:
                    tangent /= tn

        if filled_up_to >= M:
            break

    # ── Remaining straight segment after all ops ──
    if filled_up_to < M:
        idxs  = np.arange(filled_up_to, M)
        steps = (idxs - filled_up_to).astype(float)
        spines_out[filled_up_to:M] = spine + tangent * steps[:, None] * BDNA_RISE_PER_BP
        Rs_out[filled_up_to:M]     = R
        tans_out[filled_up_to:M]   = tangent

    return spines_out, Rs_out, tans_out


def deformed_nucleotide_arrays(
    helix: "Helix",
    design: "Design",
) -> dict:
    """
    Return nucleotide positions for *helix* with all deformation ops applied.

    Returns the same dict-of-arrays format as nucleotide_positions_arrays().
    This is the vectorised equivalent of deformed_nucleotide_positions() and is
    ~10–50× faster for typical helix lengths because:

      1. nucleotide_positions_arrays() replaces the per-bp scalar loop in
         nucleotide_positions() with numpy array ops.
      2. _precompute_arm_frames() computes all deformation frames in one sequential
         pass (vs one _frame_at_bp() call per nucleotide).
      3. All transforms are applied as batched matrix ops on (N, 3) arrays.

    Falls back to straight geometry (no frame computation) when the design has
    no deformations and no cluster transform for this helix.
    """
    helix    = _normalize_helix_for_grid(helix, design.lattice_type)
    clusters = _clusters_for_helix(design, helix.id)

    arrs = nucleotide_positions_arrays(helix)  # vectorised straight geometry

    if not design.deformations and not clusters:
        return arrs

    if not design.deformations:
        # Only cluster rigid transform(s) — apply domain-aware and return.
        return _apply_cluster_transforms_domain_aware(arrs, clusters, helix, design)

    # ── Has deformations ──────────────────────────────────────────────────────

    # Scope deformation arm to the first cluster's helix set (existing behaviour).
    cluster = clusters[0] if clusters else None
    arm_helices = [_normalize_helix_for_grid(h, design.lattice_type)
                   for h in _arm_helices_for(design, helix.id)]
    if cluster:
        cluster_ids = set(cluster.helix_ids)
        filtered    = [h for h in arm_helices if h.id in cluster_ids]
        if filtered:
            arm_helices = filtered

    centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

    h_start   = helix.axis_start.to_array()
    cs_raw    = h_start - centroid_0
    cs_offset = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0

    arm_min_bp = min((h.bp_start for h in arm_helices), default=0)

    # arm-local bp index for each nucleotide
    local_bps = arrs['bp_indices'] - arm_min_bp   # (M,) int

    M = len(local_bps)
    if M == 0:
        return arrs

    max_local_bp = int(local_bps.max())

    # One pass computes frames for all needed local bps.
    spines, Rs, _ = _precompute_arm_frames(design, arm_helices, arm_min_bp, max_local_bp)

    # Index frames per nucleotide using the arm-local bp as a direct array index.
    R_n     = Rs[local_bps]      # (M, 3, 3)
    spine_n = spines[local_bps]  # (M, 3)

    # Original helix axis point at each nucleotide's bp (straight geometry).
    # h_start corresponds to helix.bp_start; helix-local bp = global_bp - helix.bp_start.
    helix_local_bps = arrs['bp_indices'] - helix.bp_start            # (M,) int
    axis_origs = (h_start
                  + tangent_0 * helix_local_bps.astype(float)[:, None] * BDNA_RISE_PER_BP)  # (M, 3)

    # Per-nucleotide radial offset from its straight helix axis.
    nuc_locals = arrs['positions'] - axis_origs  # (M, 3)

    # Deformed axis point for each nucleotide: spine + R @ cs_offset
    axis_d = spine_n + (R_n @ cs_offset)  # (M, 3)  — R_n @ cs_offset broadcasts (M,3,3)@(3,)→(M,3)

    # Deformed backbone position: axis_d + R @ nuc_local  (batched)
    pos_d     = axis_d + np.einsum('mij,mj->mi', R_n, nuc_locals)   # (M, 3)
    bn_d      = np.einsum('mij,mj->mi', R_n, arrs['base_normals'])  # (M, 3)
    base_d    = pos_d + BASE_DISPLACEMENT * bn_d                     # (M, 3)
    at_d      = np.einsum('mij,mj->mi', R_n, arrs['axis_tangents']) # (M, 3)

    result = {
        'helix_id':       arrs['helix_id'],
        'bp_indices':     arrs['bp_indices'],
        'local_bps':      arrs['local_bps'],
        'directions':     arrs['directions'],
        'positions':      pos_d,
        'base_positions': base_d,
        'base_normals':   bn_d,
        'axis_tangents':  at_d,
    }

    if clusters:
        result = _apply_cluster_transforms_domain_aware(result, clusters, helix, design)

    return result


def deform_extended_arrays(
    extra_arrs: dict,
    helix: "Helix",
    design: "Design",
    edge_bp: int,
) -> dict:
    """Apply deformation / cluster transforms to nucleotides outside the helix span.

    These are the single-stranded scaffold-loop nucleotides generated by
    ``nucleotide_positions_arrays_extended`` / ``_right``.  Their straight
    geometry extrapolates the canonical helix axis; this function rotates and
    translates them so they follow the deformed axis at *edge_bp* (the first
    or last physical bp of the helix).

    *edge_bp* is a **global** bp index — typically ``helix.bp_start`` for
    left-side extensions or ``helix.bp_start + helix.length_bp - 1`` for
    right-side extensions.
    """
    helix    = _normalize_helix_for_grid(helix, design.lattice_type)
    clusters = _clusters_for_helix(design, helix.id)

    M = len(extra_arrs['bp_indices'])
    if M == 0:
        return extra_arrs

    if not design.deformations and not clusters:
        return extra_arrs

    if not design.deformations:
        # Only cluster rigid transform — apply helix-level transform to all.
        # Domain-aware filtering is not meaningful for extended bps (they don't
        # belong to any domain), so apply the first matching cluster uniformly.
        if clusters:
            return _apply_cluster_rigid_transform_arrays(extra_arrs, clusters[0])
        return extra_arrs

    # ── Has deformations ──────────────────────────────────────────────────────
    cluster = clusters[0] if clusters else None
    arm_helices = [_normalize_helix_for_grid(h, design.lattice_type)
                   for h in _arm_helices_for(design, helix.id)]
    if cluster:
        cluster_ids = set(cluster.helix_ids)
        filtered    = [h for h in arm_helices if h.id in cluster_ids]
        if filtered:
            arm_helices = filtered

    centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

    h_start   = helix.axis_start.to_array()
    cs_raw    = h_start - centroid_0
    cs_offset = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0

    arm_min_bp = min((h.bp_start for h in arm_helices), default=0)
    edge_local = edge_bp - arm_min_bp

    # Single-bp frame at the helix edge.
    spine_e, R_e, _ = _frame_at_bp(design, edge_local, arm_helices)
    axis_d_edge = spine_e + R_e @ cs_offset

    # Straight-geometry axis point at the edge bp.
    edge_helix_local = edge_bp - helix.bp_start
    axis_orig_edge = h_start + tangent_0 * float(edge_helix_local) * BDNA_RISE_PER_BP

    # Transform each extended nucleotide: rotate its offset from the
    # straight edge axis point into the deformed frame.
    offsets = extra_arrs['positions'] - axis_orig_edge          # (M, 3)
    pos_d   = axis_d_edge + offsets @ R_e.T                     # (M, 3)
    bn_d    = extra_arrs['base_normals'] @ R_e.T                # (M, 3)
    base_d  = pos_d + BASE_DISPLACEMENT * bn_d                  # (M, 3)
    at_d    = extra_arrs['axis_tangents'] @ R_e.T               # (M, 3)

    result = {
        'helix_id':       extra_arrs['helix_id'],
        'bp_indices':     extra_arrs['bp_indices'],
        'local_bps':      extra_arrs['local_bps'],
        'directions':     extra_arrs['directions'],
        'positions':      pos_d,
        'base_positions': base_d,
        'base_normals':   bn_d,
        'axis_tangents':  at_d,
    }

    if clusters:
        result = _apply_cluster_rigid_transform_arrays(result, clusters[0])

    return result


def apply_deformations_to_atoms(atoms: list, design: "Design") -> None:
    """
    Apply bend/twist deformations and cluster rigid transforms to atom positions in-place.

    Mirrors deformed_nucleotide_arrays() — uses the same arm-frame propagation and
    cluster domain-aware transform — but operates on Atom objects (from atomistic.py)
    rather than NucleotidePosition arrays.  Called from build_atomistic_model() to
    ensure the all-atom model matches the deformed 3-D view.

    Extra-base crossover atoms (aux_helix_id != "") use their helix_id / bp_index
    (the source-junction nucleotide's helix and global bp) for frame lookup.

    Atoms with empty helix_id are skipped (no frame available).
    """
    if not design.deformations and not design.cluster_transforms:
        return

    helix_map = {h.id: h for h in design.helices}

    # Group atom list-indices by helix_id.
    from collections import defaultdict
    by_helix: dict[str, list[int]] = defaultdict(list)
    for i, atom in enumerate(atoms):
        if atom.helix_id:
            by_helix[atom.helix_id].append(i)

    for helix_id, atom_indices in by_helix.items():
        helix_raw = helix_map.get(helix_id)
        if helix_raw is None:
            continue

        helix    = _normalize_helix_for_grid(helix_raw, design.lattice_type)
        clusters = _clusters_for_helix(design, helix_id)

        has_deform  = bool(design.deformations)
        has_cluster = bool(clusters)

        if not has_deform and not has_cluster:
            continue

        N = len(atom_indices)
        positions      = np.empty((N, 3), dtype=float)
        bp_indices_arr = np.empty(N,      dtype=int)
        directions_arr = np.empty(N,      dtype=int)

        for j, idx in enumerate(atom_indices):
            a = atoms[idx]
            positions[j, 0] = a.x
            positions[j, 1] = a.y
            positions[j, 2] = a.z
            bp_indices_arr[j] = a.bp_index
            directions_arr[j] = 0 if a.direction == "FORWARD" else 1

        if has_deform:
            arm_helices = [_normalize_helix_for_grid(h, design.lattice_type)
                           for h in _arm_helices_for(design, helix_id)]
            cluster = clusters[0] if clusters else None
            if cluster:
                cluster_ids = set(cluster.helix_ids)
                filtered    = [h for h in arm_helices if h.id in cluster_ids]
                if filtered:
                    arm_helices = filtered

            centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)
            h_start    = helix.axis_start.to_array()
            cs_raw     = h_start - centroid_0
            cs_offset  = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0
            arm_min_bp = min(h.bp_start for h in arm_helices)

            local_bps    = bp_indices_arr - arm_min_bp    # (N,) int
            # Clamp to valid range: atoms extended before arm start use frame 0;
            # atoms past the end use the last computed frame.
            local_bps_clamped = np.clip(local_bps, 0, None)
            max_local_bp      = int(local_bps_clamped.max()) if N > 0 else 0

            spines, Rs, _ = _precompute_arm_frames(design, arm_helices, arm_min_bp, max_local_bp)

            R_n     = Rs[local_bps_clamped]       # (N, 3, 3)
            spine_n = spines[local_bps_clamped]   # (N, 3)

            # Straight helix axis at each atom's global bp_index.
            helix_local_bps = bp_indices_arr - helix.bp_start   # (N,) int
            axis_origs = (h_start
                          + tangent_0 * helix_local_bps.astype(float)[:, None] * BDNA_RISE_PER_BP)

            nuc_locals = positions - axis_origs  # (N, 3)
            positions  = spine_n + np.einsum('mij,mj->mi', R_n, nuc_locals + cs_offset)

        if has_cluster:
            arrs = {
                'helix_id':       helix_id,
                'bp_indices':     bp_indices_arr,
                'local_bps':      bp_indices_arr - helix.bp_start,
                'directions':     directions_arr,
                'positions':      positions,
                'base_positions': positions,           # placeholder — not used by cluster path
                'base_normals':   np.zeros((N, 3)),    # placeholder
                'axis_tangents':  np.zeros((N, 3)),    # placeholder
            }
            out       = _apply_cluster_transforms_domain_aware(arrs, clusters, helix, design)
            positions = out['positions']

        # Write back
        for j, idx in enumerate(atom_indices):
            a      = atoms[idx]
            a.x    = float(positions[j, 0])
            a.y    = float(positions[j, 1])
            a.z    = float(positions[j, 2])


def deformed_nucleotide_positions(
    helix: "Helix",
    design: "Design",
) -> list[NucleotidePosition]:
    """
    Return nucleotide positions for *helix* with all deformation ops applied.

    Falls back to ``nucleotide_positions(helix)`` unchanged when
    ``design.deformations`` is empty and the helix has no cluster transform.
    """
    helix   = _normalize_helix_for_grid(helix, design.lattice_type)
    cluster = _cluster_for_helix(design, helix.id)
    if not design.deformations and cluster is None:
        return nucleotide_positions(helix)

    if not design.deformations:
        result = nucleotide_positions(helix)
        return _apply_cluster_rigid_transform(result, cluster)  # type: ignore[arg-type]

    arm_helices = [_normalize_helix_for_grid(h, design.lattice_type)
                   for h in _arm_helices_for(design, helix.id)]
    # Restrict to the helix's cluster so each cluster deforms independently.
    if cluster:
        cluster_ids = set(cluster.helix_ids)
        filtered = [h for h in arm_helices if h.id in cluster_ids]
        if filtered:
            arm_helices = filtered
    centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

    # Helix cross-section offset (perpendicular component of axis_start − centroid)
    h_start   = helix.axis_start.to_array()
    cs_raw    = h_start - centroid_0
    cs_offset = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0

    # _frame_at_bp target_bp is arm-local (0 = axis_start); nuc.bp_index is GLOBAL.
    # Subtract arm_min_bp_start once to convert to arm-local for all nucleotides.
    arm_min_bp_start = min((h.bp_start for h in arm_helices), default=0)

    orig_nucs = nucleotide_positions(helix)
    result: list[NucleotidePosition] = []

    for nuc in orig_nucs:
        p = nuc.bp_index

        # Original helix axis point at this bp (straight).
        # h_start corresponds to bp_start, so offset from there.
        axis_orig = h_start + tangent_0 * (p - helix.bp_start) * BDNA_RISE_PER_BP

        # Nucleotide offset from its helix axis (radial direction in helix XY-plane)
        nuc_local = nuc.position - axis_orig

        # World frame at this bp — _frame_at_bp expects LOCAL bp
        spine_p, R_p, _ = _frame_at_bp(design, p - arm_min_bp_start, arm_helices)

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

    if cluster is not None:
        result = _apply_cluster_rigid_transform(result, cluster)
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
    if not design.deformations and not design.cluster_transforms:
        out: list[dict] = []
        for h in design.helices:
            hn = _normalize_helix_for_grid(h, design.lattice_type)
            s  = hn.axis_start.to_array().tolist()
            e  = hn.axis_end.to_array().tolist()
            out.append({"helix_id": h.id, "start": s, "end": e, "samples": [s, e]})
        return out

    if not design.deformations:
        # Only cluster transforms — apply rigid shift to straight axis samples.
        axes: list[dict] = []
        for h in design.helices:
            hn      = _normalize_helix_for_grid(h, design.lattice_type)
            cluster = _cluster_for_helix(design, h.id)
            s = hn.axis_start.to_array().tolist()
            e = hn.axis_end.to_array().tolist()
            samples = [s, e]
            if cluster is not None:
                R     = _rot_from_quaternion(*cluster.rotation)
                pivot = np.array(cluster.pivot,       dtype=float)
                trans = np.array(cluster.translation, dtype=float)
                def _xf(p: list[float]) -> list[float]:
                    return (R @ (np.array(p) - pivot) + pivot + trans).tolist()
                samples = [_xf(pt) for pt in samples]
            axes.append({"helix_id": h.id, "start": samples[0], "end": samples[-1], "samples": samples})
        return axes

    result: list[dict] = []

    for h in design.helices:
        h           = _normalize_helix_for_grid(h, design.lattice_type)
        arm_helices = [_normalize_helix_for_grid(h2, design.lattice_type)
                       for h2 in _arm_helices_for(design, h.id)]
        cluster = _cluster_for_helix(design, h.id)
        # Restrict to the helix's cluster so each cluster deforms independently.
        if cluster:
            cluster_ids = set(cluster.helix_ids)
            filtered = [h2 for h2 in arm_helices if h2.id in cluster_ids]
            if filtered:
                arm_helices = filtered
        centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)

        h_start   = h.axis_start.to_array()
        cs_raw    = h_start - centroid_0
        cs_offset = cs_raw - np.dot(cs_raw, tangent_0) * tangent_0

        # _frame_at_bp uses LOCAL bp (0 = axis_start).  Sample the full helix
        # length in local indices (0 … length_bp−1).
        sample_local: list[int] = list(range(0, h.length_bp, _AXIS_SAMPLE_STEP))
        if not sample_local or sample_local[-1] != h.length_bp - 1:
            sample_local.append(h.length_bp - 1)

        samples: list[list[float]] = []
        for local_bp in sample_local:
            spine_p, R_p, _ = _frame_at_bp(design, local_bp, arm_helices)
            samples.append((spine_p + R_p @ cs_offset).tolist())
        if cluster is not None:
            R_c   = _rot_from_quaternion(*cluster.rotation)
            piv_c = np.array(cluster.pivot,       dtype=float)
            tr_c  = np.array(cluster.translation, dtype=float)
            samples = [
                (R_c @ (np.array(pt) - piv_c) + piv_c + tr_c).tolist()
                for pt in samples
            ]

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

    axis_dir    = tangent
    frame_right = R_p @ initial_right
    frame_up    = R_p @ initial_up

    # Apply cluster rigid transform when the reference helix belongs to a cluster.
    if ref_helix_id is not None:
        cluster = _cluster_for_helix(design, ref_helix_id)
        if cluster is not None:
            R_c   = _rot_from_quaternion(*cluster.rotation)
            piv_c = np.array(cluster.pivot,       dtype=float)
            tr_c  = np.array(cluster.translation, dtype=float)
            grid_origin = R_c @ (grid_origin - piv_c) + piv_c + tr_c
            axis_dir    = R_c @ axis_dir
            frame_right = R_c @ frame_right
            frame_up    = R_c @ frame_up

    return {
        "grid_origin":  grid_origin.tolist(),
        "axis_dir":     axis_dir.tolist(),
        "frame_right":  frame_right.tolist(),
        "frame_up":     frame_up.tolist(),
    }


def helices_crossing_planes(design: "Design", plane_a_bp: int, plane_b_bp: int) -> list[str]:
    """Return IDs of helices whose GLOBAL bp range covers both plane_a_bp and plane_b_bp.

    plane_a_bp / plane_b_bp are GLOBAL bp indices (invariant under helix extension).
    A helix covers global range [h.bp_start, h.bp_start + h.length_bp − 1].
    """
    lo, hi = min(plane_a_bp, plane_b_bp), max(plane_a_bp, plane_b_bp)
    return [
        h.id for h in design.helices
        if h.bp_start <= lo and h.bp_start + h.length_bp - 1 >= hi
    ]
