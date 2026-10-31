"""Direct-duplex endpoint/kinematic selection and root-preserving Relax entry.

Automatic placement uses covalent root constraints in direct_root_placement;
parent kinematics and relaxation live in direct_root_relax. Manual pose tools
retain the shared quaternion and endpoint helpers below.
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from fastapi import HTTPException

from backend.core.linker_relax import (
    _overhang_owning_cluster_id,
    _quat_mul as _quat_mul,
)
from backend.core.models import (
    Design,
    _local_to_world_joint,
)

_DEFAULT_TARGET_NM = 0.67

# ── Topology resolution ──────────────────────────────────────────────────────
def _find_driven_tip_and_root(design: Design, driven_oh_id: str):
    """Locate the DRIVEN overhang's tip domain (``overhang_id == driven_oh_id``,
    a terminal domain of a multi-domain staple — now relocated onto the driver
    helix) plus its strand-adjacent bundle-embedded (root) domain, and the two
    connecting-bp indices of the stretched backbone bond.

    Convention (mirrors the strand-adjacency the renderer bonds across):
      * tip is the LATER domain (idx == n-1) → bond joins root.end_bp (3') to
        tip.start_bp (5').
      * tip is the EARLIER domain (idx == 0) → bond joins tip.end_bp (3') to
        root.start_bp (5').

    Returns ``(strand, tip_idx, tip_dom, root_dom, connecting_tip_bp,
    connecting_root_bp)``. Raises ``HTTPException(422)`` if no such relocated tip
    is found (e.g. the version was never applied, or the overhang is a single-
    domain standalone strand with no embedded root).
    """
    for s in design.strands:
        n_dom = len(s.domains)
        if n_dom < 2:
            continue
        for di, d in enumerate(s.domains):
            if d.overhang_id != driven_oh_id or di not in (0, n_dom - 1):
                continue
            root_dom = s.domains[di - 1] if di == n_dom - 1 else s.domains[di + 1]
            if di == n_dom - 1:
                connecting_tip_bp = d.start_bp
                connecting_root_bp = root_dom.end_bp
            else:
                connecting_tip_bp = d.end_bp
                connecting_root_bp = root_dom.start_bp
            return s, di, d, root_dom, connecting_tip_bp, connecting_root_bp
    raise HTTPException(
        422,
        detail=(
            f"relax_direct_binding: no relocated tip domain found for overhang "
            f"{driven_oh_id!r}. Apply the direct connection first."
        ),
    )


def _bead_pos(
    nucs: list[dict], *, strand_id: str, helix_id: str, bp: int
) -> Optional[np.ndarray]:
    """Backbone position of the geometry bead at (strand_id, helix_id, bp)."""
    for n in nucs:
        if (
            n.get("strand_id") == strand_id
            and n.get("helix_id") == helix_id
            and n.get("bp_index") == bp
        ):
            p = n.get("backbone_position") or n.get("base_position")
            if p is not None:
                return np.asarray(p, dtype=float)
    return None


def _overhang_root_pivot(
    design: Design, nucs: list[dict], driver_oh_id: str
) -> Optional[np.ndarray]:
    """The DRIVER's root junction bead — the pivot the overhang duplex swings
    about.

    Mirrors the junction-bp choice in
    ``deformation.apply_overhang_rotation_if_needed`` (``end_bp`` when the OH
    domain is the strand's first domain, else ``start_bp``) so the solver
    pivots about the exact bead the renderer rotates around.
    """
    for s in design.strands:
        for di, d in enumerate(s.domains):
            if d.overhang_id == driver_oh_id:
                junction_bp = d.end_bp if di == 0 else d.start_bp
                return _bead_pos(
                    nucs, strand_id=s.id, helix_id=d.helix_id, bp=junction_bp
                )
    return None


def _quat_align(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Shortest-arc unit quaternion [x,y,z,w] rotating vector *u* onto *v*.
    Returns identity for degenerate (near-zero) inputs; a stable 180° about an
    arbitrary perpendicular for antiparallel inputs."""
    nu = float(np.linalg.norm(u))
    nv = float(np.linalg.norm(v))
    if nu < 1e-9 or nv < 1e-9:
        return np.array([0.0, 0.0, 0.0, 1.0])
    a = u / nu
    b = v / nv
    d = float(np.dot(a, b))
    if d > 1.0 - 1e-9:
        return np.array([0.0, 0.0, 0.0, 1.0])
    if d < -1.0 + 1e-9:
        # Antiparallel: 180° about any axis perpendicular to a.
        axis = np.cross(a, np.array([1.0, 0.0, 0.0]))
        if float(np.linalg.norm(axis)) < 1e-6:
            axis = np.cross(a, np.array([0.0, 1.0, 0.0]))
        axis = axis / max(1e-12, float(np.linalg.norm(axis)))
        return np.array([axis[0], axis[1], axis[2], 0.0])
    axis = np.cross(a, b)
    s = float(np.sqrt((1.0 + d) * 2.0))
    q = np.array([axis[0] / s, axis[1] / s, axis[2] / s, s / 2.0])
    return q / max(1e-12, float(np.linalg.norm(q)))


def _root_anchors(
    design: Design, nucs: list[dict], driver_oh_id: str, driven_oh_id: str
):
    """Return ``(P_A, c_A, P_B, c_B)`` — each side's embedded-staple root connecting
    bead ``P`` and its duplex connecting bead ``c``. ``P`` is ``None`` for a standalone
    single-domain overhang (no embedded root). The driven side always resolves (its tip
    was relocated onto the driver, so it is multi-domain)."""

    def _side(oh_id):
        try:
            strand, _bi, tip_dom, root_dom, c_bp, p_bp = _find_driven_tip_and_root(
                design, oh_id
            )
        except HTTPException:
            return None, None
        c = _bead_pos(nucs, strand_id=strand.id, helix_id=tip_dom.helix_id, bp=c_bp)
        p = _bead_pos(nucs, strand_id=strand.id, helix_id=root_dom.helix_id, bp=p_bp)
        return p, c

    p_a, c_a = _side(driver_oh_id)
    p_b, c_b = _side(driven_oh_id)
    return p_a, c_a, p_b, c_b


def _quat_to_R(quat: np.ndarray) -> np.ndarray:
    """Rotation matrix from quaternion [x,y,z,w] (about origin)."""
    x, y, z, w = quat / max(1e-12, float(np.linalg.norm(quat)))
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
            [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
            [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
        ]
    )  # ── Public entry point ───────────────────────────────────────────────────────


def _relax_joint_selection(design, driver_oh_id, tip_helix, root_helix, joint_ids=None):
    """Existing ownership/ordered-joint rule, without placement or optimization."""
    from backend.core.bond_relax import cluster_pair_for_bond_relax

    # Cluster ownership of the two root anchors.
    cb_id, cr_id = cluster_pair_for_bond_relax(design, tip_helix, root_helix)
    cluster_a = _overhang_owning_cluster_id(design, driver_oh_id) or cb_id
    cluster_b = cr_id
    same_body = cluster_a is not None and cluster_a == cluster_b

    # Joints connecting the two clusters (skip when same body).
    candidate_joints: list = []
    if not same_body:
        candidate_joints = [
            j
            for j in design.cluster_joints
            if j.cluster_id == cluster_a or j.cluster_id == cluster_b
        ]
        if joint_ids is not None:
            wanted = set(joint_ids)
            candidate_joints = [j for j in candidate_joints if j.id in wanted]

    cts_by_id = {c.id: c for c in design.cluster_transforms}
    selected: list[tuple] = []  # (joint, origin, axis, cluster_id, tmin, tmax)
    for j in candidate_joints:
        ct = cts_by_id.get(j.cluster_id)
        wo, wd = _local_to_world_joint(j.local_axis_origin, j.local_axis_direction, ct)
        axis = np.asarray(wd, dtype=float)
        nrm = float(np.linalg.norm(axis))
        if nrm < 1e-9:
            continue
        selected.append(
            (
                j,
                np.asarray(wo, dtype=float),
                axis / nrm,
                j.cluster_id,
                float(j.min_angle_deg) * np.pi / 180.0,
                float(j.max_angle_deg) * np.pi / 180.0,
            )
        )

    return cluster_a, cluster_b, same_body, cts_by_id, selected


def direct_relax_selection(design, driver_oh_id, driven_oh_id):
    """Capture exact references selected after removal of the duplex child.

    Dematerialization only changes the driver's overhang pose and removes that
    child. Neither pose participates in this ownership/axis selection, so the
    structural view avoids generating geometry just to capture references.
    """
    from backend.core.duplex_cluster import duplex_cluster_for

    child = duplex_cluster_for(design, driver_oh_id)
    context = design.copy_with(cluster_transforms=[cluster for cluster in design.cluster_transforms
        if cluster.id != child.id]) if child is not None else design
    _strand, _index, tip, root, _cb, _cr = _find_driven_tip_and_root(context, driven_oh_id)
    driver_cluster, driven_cluster, _same, _clusters, selected = _relax_joint_selection(
        context, driver_oh_id, tip.helix_id, root.helix_id)
    return {"driver_cluster_id": driver_cluster, "driven_cluster_id": driven_cluster,
            "duplex_cluster_id": child.id if child is not None else None,
            "joint_ids": [joint.id for joint, *_rest in selected]}


def relax_direct_binding(
    design: Design,
    driver_oh_id: str,
    driven_oh_id: str,
    *,
    target_nm: float = _DEFAULT_TARGET_NM,
    joint_ids: Optional[list[str]] = None,
) -> tuple[Design, dict[str, Any]]:
    """Close an applied duplex using its stored covalent root lengths.

    The legacy target_nm argument no longer changes chemical bond lengths.
    Parent joint/translation options are retained; collisions are advisory.
    Roots fixed to one rigid cluster retain their existing strain with an exemption.
    """
    if target_nm != _DEFAULT_TARGET_NM:
        raise HTTPException(422, detail="Relax preserves the original covalent root lengths; target_nm cannot override them.")
    from backend.core.direct_root_relax import relax_direct_roots

    return relax_direct_roots(design, driver_oh_id, driven_oh_id, joint_ids=joint_ids)
