"""Single-body PBD drag solver and adapter to the joint flexible network solve.

The legacy single-body math is retained for drag parity tests. Relax commands use
flexible_network.solve_design_network, shared by the app and headless authoring.
All results are rigid poses; topology and flexible marks remain unchanged.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Design, FlexibleAnchor

# Solver constants — IDENTICAL to cluster_gizmo.js (_SS_GAIN, _SS_ITERS,
# _SS_RELAX_OUTER, _SS_RELAX_EPS). Network closure has its own tolerance.
_SS_GAIN = 0.6
_SS_ITERS = 6
_SS_RELAX_OUTER = 80
_SS_RELAX_EPS = 1e-3  # nm — converged when max violation below this


# ── Pure PBD solver (port of relaxSsdna + _projectSsdnaConstraints) ─────────────


def relax_cluster_pose(
    pivot,
    translation,
    rotation,
    tethers,
    *,
    translate_only: bool = False,
):
    """Solve one moving cluster's relaxed pose.

    ``pivot`` / ``translation`` (nm) / ``rotation`` (quaternion ``[x,y,z,w]``)
    are the cluster's CURRENT transform.  ``tethers`` is a list of
    ``(moving_anchor_world_pos, fixed_anchor_world_pos, contour_nm)`` — the
    moving anchor is the tether end ON this cluster (it rides the pose), the
    fixed anchor is the other cluster's end (held still), both already at their
    current posed world positions.  ``translate_only`` slides without rotating
    (a lone tether has no rotation basis).

    Returns ``(new_translation, new_rotation, residual_nm, moved)`` — the absolute
    new transform (pivot unchanged), the largest remaining overstretch, and
    whether the cluster moved at all (False when nothing was overstretched).
    """
    pivot = np.asarray(pivot, dtype=float)
    dummy_pos = pivot + np.asarray(translation, dtype=float)
    start_pos = dummy_pos.copy()
    dummy_rot = Rotation.from_quat(rotation)
    start_rot = dummy_rot
    incr_rot = Rotation.identity()

    teth = [
        (np.asarray(m, dtype=float), np.asarray(f, dtype=float), float(c))
        for (m, f, c) in tethers
    ]

    def candidate(pM0):
        # world = incrQuat·(pM0 − startDummyPos) + dummyPos  (cluster_gizmo.js:825)
        return incr_rot.apply(pM0 - start_pos) + dummy_pos

    def max_violation():
        m = 0.0
        for pM0, pF, contour in teth:
            d = float(np.linalg.norm(candidate(pM0) - pF)) - contour
            if d > m:
                m = d
        return m

    if not teth or max_violation() <= _SS_RELAX_EPS:
        return list(translation), list(rotation), max_violation(), False

    for _ in range(_SS_RELAX_OUTER):
        if max_violation() <= _SS_RELAX_EPS:
            break
        # ── _projectSsdnaConstraints: _SS_ITERS internal iterations ────────────
        for _it in range(_SS_ITERS):
            # Rotation pass: accumulate torque about the pivot from violations.
            torque = np.zeros(3)
            sum_r2 = 0.0
            n_viol = 0
            for pM0, pF, contour in teth:
                pM = candidate(pM0)
                dist = float(np.linalg.norm(pM - pF))
                if dist <= contour or dist < 1e-9:
                    continue
                target = pF + (pM - pF) * (contour / dist)
                delta = target - pM
                r = pM - pivot
                torque = torque + np.cross(r, delta)
                sum_r2 += float(np.dot(r, r))
                n_viol += 1
            if n_viol == 0:
                break
            if not translate_only and sum_r2 > 1e-6:
                rv = torque * (_SS_GAIN / sum_r2)
                angle = float(np.linalg.norm(rv))
                if angle > 1e-9:
                    if angle > 0.25:
                        angle = 0.25  # clamp per-iter rotation for stability
                    axis = rv / float(np.linalg.norm(rv))
                    q = Rotation.from_rotvec(axis * angle)
                    dummy_pos = q.apply(dummy_pos - pivot) + pivot
                    dummy_rot = q * dummy_rot  # premultiply
                    incr_rot = dummy_rot * start_rot.inv()
            # Translation pass: residual after rotation.
            d_t = np.zeros(3)
            n_t = 0
            for pM0, pF, contour in teth:
                pM = candidate(pM0)
                dist = float(np.linalg.norm(pM - pF))
                if dist <= contour or dist < 1e-9:
                    continue
                target = pF + (pM - pF) * (contour / dist)
                d_t = d_t + (target - pM)
                n_t += 1
            if n_t > 0:
                dummy_pos = dummy_pos + d_t * (_SS_GAIN / n_t)

    residual = max_violation()
    new_translation = (dummy_pos - pivot).tolist()
    new_rotation = dummy_rot.as_quat().tolist()
    return new_translation, new_rotation, residual, True


# ── Geometry resolution and compatibility adapter ────────────────────────────


def _geom_index(design: Design) -> dict:
    """(helix_id, bp_index, direction-string) → posed backbone position (np)."""
    out = {}
    for n in _geometry_for_design(design):
        out[(n["helix_id"], n["bp_index"], n["direction"])] = np.asarray(
            n["backbone_position"], dtype=float
        )
    return out


def _anchor_world_pos(
    geom_index: dict, design: Design, anchor: FlexibleAnchor
) -> Optional[np.ndarray]:
    """Resolve a flexible anchor → its posed backbone world position.

    Mirrors ``flexAnchorKey`` (design_queries.js): the anchor names a strand +
    domain index + bp + direction; the domain supplies the helix.
    """
    strand = next((s for s in design.strands if s.id == anchor.strand_id), None)
    if strand is None or anchor.domain_index >= len(strand.domains):
        return None
    helix_id = strand.domains[anchor.domain_index].helix_id
    return geom_index.get((helix_id, anchor.bp_index, anchor.direction.value))


def compute_relax_transforms(
    design: Design,
    *,
    scope: str = "all",
    conn_id: Optional[str] = None,
):
    """Compatibility wrapper for the shared joint network solver."""
    from backend.core.flexible_network import solve_design_network

    result = solve_design_network(design, scope=scope, conn_id=conn_id)
    return result["transforms"], not result["converged"]
