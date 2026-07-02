"""Overhang-DUPLEX cluster — Phase 1 of the [[overhang-duplex-cluster]] plan.

Promotes the per-overhang duplex POSE (historically an ``OverhangSpec.rotation`` /
``OverhangSpec.translation`` overlay applied in the WORLD frame AFTER the driver part's
cluster, by ``deformation.apply_overhang_rotation_if_needed``) into a first-class CHILD
``ClusterRigidTransform`` whose local pose is stored in the driver part's REST frame and
composed INSIDE the parent (``T_parent(T_child(p_rest))`` — see
``_apply_cluster_transforms_domain_aware``). This makes the duplex a sidebar-listed,
gizmo-movable cluster AND removes the world-frame drift the overlay had when the driver
part was rotated after the pose was set.

The overlay→child conversion is a frame conjugation::

    T_child = T_parent^{-1} ∘ T_overlay_world ∘ T_parent

where ``T_overlay_world`` is the driver's stored quaternion/translation applied about the
POSED junction bead. Materializing at Apply time uses the same conversion (the placement
`direct_relax.duplex_midpoint_placement` produces is a world overlay).

DELETE-ON-COMPLETION: once this plan lands, the ``OverhangSpec.rotation``/``translation``
overlay path in ``apply_overhang_rotation_if_needed`` + ``_apply_ovhg_rotations_to_axes``
and the standalone orientation panel are retired (see `memory/project_tech_debt.md`).
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from backend.core.models import (
    ClusterRigidTransform, Design, DomainRef, _local_to_world_joint,  # noqa: F401
)

_IDENTITY_QUAT = [0.0, 0.0, 0.0, 1.0]


# ── quaternion <-> matrix (avoid a scipy dep cycle; match Three.js [x,y,z,w]) ──
def _quat_to_R(q) -> np.ndarray:
    x, y, z, w = np.asarray(q, dtype=float) / max(1e-12, float(np.linalg.norm(q)))
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
    ])


def _R_to_quat(R: np.ndarray) -> list[float]:
    """Rotation matrix → unit quaternion [x, y, z, w] (Shepperd's method)."""
    m = np.asarray(R, dtype=float)
    t = float(np.trace(m))
    if t > 0.0:
        s = np.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2, 1] - m[1, 2]) / s
        y = (m[0, 2] - m[2, 0]) / s
        z = (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        w = (m[2, 1] - m[1, 2]) / s
        x = 0.25 * s
        y = (m[0, 1] + m[1, 0]) / s
        z = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        w = (m[0, 2] - m[2, 0]) / s
        x = (m[0, 1] + m[1, 0]) / s
        y = 0.25 * s
        z = (m[1, 2] + m[2, 1]) / s
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        w = (m[1, 0] - m[0, 1]) / s
        x = (m[0, 2] + m[2, 0]) / s
        y = (m[1, 2] + m[2, 1]) / s
        z = 0.25 * s
    q = np.array([x, y, z, w], dtype=float)
    q = q / max(1e-12, float(np.linalg.norm(q)))
    return [float(q[0]), float(q[1]), float(q[2]), float(q[3])]


def conjugate_world_pose_into_parent_rest(
    r_world_quat, pivot_world, t_world, parent: Optional[ClusterRigidTransform],
) -> tuple[list[float], list[float], list[float]]:
    """Convert a WORLD-frame overlay (rotation ``r_world_quat`` about ``pivot_world`` +
    translation ``t_world``, applied AFTER the parent) into the equivalent CHILD transform
    in the parent's REST frame (applied BEFORE the parent). Returns
    ``(rotation_quat, pivot, translation)`` for the child cluster.

    Derivation (T_C = T_P^{-1} ∘ T_W ∘ T_P), with a = parent.pivot, b = parent.translation,
    R_P = parent rotation, c = pivot_world, d = t_world, R_W = r_world_quat:
        pivot   = a
        R_child = R_P^{-1} · R_W · R_P
        trans   = R_P^{-1} · ( R_W·(a + b − c) + c + d − a − b )
    With no parent (identity) this collapses to (R_W, 0, world-translation about pivot_world),
    i.e. the overlay unchanged.
    """
    R_W = _quat_to_R(r_world_quat)
    c = np.asarray(pivot_world, dtype=float)
    d = np.asarray(t_world, dtype=float)
    if parent is None:
        R_C = R_W
        a = np.zeros(3)
        # T_C(x) = R_W(x − c) + c + d = R_W x + (c − R_W c + d); pivot = 0.
        trans = (c - R_W @ c + d)
        return _R_to_quat(R_C), [0.0, 0.0, 0.0], [float(trans[0]), float(trans[1]), float(trans[2])]
    R_P = _quat_to_R(parent.rotation)
    a = np.asarray(parent.pivot, dtype=float)
    b = np.asarray(parent.translation, dtype=float)
    R_Pinv = R_P.T
    R_C = R_Pinv @ R_W @ R_P
    trans = R_Pinv @ (R_W @ (a + b - c) + c + d - a - b)
    return (_R_to_quat(R_C), [float(a[0]), float(a[1]), float(a[2])],
            [float(trans[0]), float(trans[1]), float(trans[2])])


# ── Duplex-cluster construction ──────────────────────────────────────────────
def _duplex_domain_refs(design: Design, driver_oh_id: str):
    """Domain refs that make up the duplex on the driver helix: the driver overhang
    domain PLUS every co-moving partner (relocated driven tip, LINKER complements,
    OH_BINDER / end-to-root binders) — exactly the set the overlay co-rotates."""
    from backend.core.deformation import _overhang_binding_partner_refs
    for s in design.strands:
        for di, d in enumerate(s.domains):
            if d.overhang_id == driver_oh_id:
                partners = _overhang_binding_partner_refs(design, d.helix_id, d)
                return d.helix_id, [DomainRef(strand_id=s.id, domain_index=di), *partners]
    return None, []


def _owning_parent_cluster(design: Design, helix_id: str) -> Optional[ClusterRigidTransform]:
    """The cluster that should be the duplex's PARENT: the smallest helix-level cluster
    covering the driver helix (the driver part's rigid body). None if none covers it.
    A duplex cluster itself is never a parent candidate."""
    candidates = [c for c in design.cluster_transforms
                  if not c.domain_ids and c.overhang_duplex_driver_id is None
                  and helix_id in (c.helix_ids or [])]
    if not candidates:
        return None
    # Smallest helix_count wins (mirror _overhang_owning_cluster_id's specificity rule).
    return min(candidates, key=lambda c: len(c.helix_ids or []))


def duplex_cluster_for(design: Design, driver_oh_id: str) -> Optional[ClusterRigidTransform]:
    """The auto-created duplex cluster whose driver is *driver_oh_id* (or None)."""
    return next((c for c in design.cluster_transforms
                 if c.overhang_duplex_driver_id == driver_oh_id), None)


def _next_duplex_cluster_name(design: Design) -> str:
    used = {c.name for c in design.cluster_transforms}
    n = 1
    while f"Duplex {n}" in used:
        n += 1
    return f"Duplex {n}"


def materialize_duplex_cluster(
    design: Design, driver_oh_id: str, *, name: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> tuple[Design, Optional[str]]:
    """Move the driver overhang's WORLD-frame pose (``OverhangSpec.rotation``/``translation``)
    onto a new CHILD ``ClusterRigidTransform`` (rest frame, `parent_cluster_id` = the driver
    part's cluster) covering the whole duplex (driver overhang + co-moving partners), and
    CLEAR the OverhangSpec pose. Geometry-neutral (proven by
    ``test_duplex_cluster_parity``). Idempotent: returns the existing cluster id if one is
    already materialized for this driver. Returns ``(design, cluster_id | None)``; ``None``
    when the driver overhang / its domain can't be resolved."""
    from backend.api.crud import _geometry_for_design
    from backend.core.direct_relax import _overhang_root_pivot

    existing = duplex_cluster_for(design, driver_oh_id)
    if existing is not None:
        return design, existing.id

    spec = next((o for o in design.overhangs if o.id == driver_oh_id), None)
    if spec is None:
        return design, None
    helix_id, refs = _duplex_domain_refs(design, driver_oh_id)
    if helix_id is None:
        return design, None

    r_w = list(spec.rotation)
    t_w = list(spec.translation)
    parent = _owning_parent_cluster(design, helix_id)

    # pivot_world = the junction bead in the parent-POSED, PRE-overlay frame. Read it off a
    # copy with the driver pose CLEARED so the overlay's own translation doesn't shift it.
    cleared_specs = [
        o.model_copy(update={"rotation": _IDENTITY_QUAT, "translation": [0.0, 0.0, 0.0]})
        if o.id == driver_oh_id else o
        for o in design.overhangs
    ]
    cleared = design.model_copy(update={"overhangs": cleared_specs})
    pivot_world = _overhang_root_pivot(cleared, _geometry_for_design(cleared), driver_oh_id)
    if pivot_world is None:
        return design, None

    q_c, piv_c, t_c = conjugate_world_pose_into_parent_rest(
        r_w, list(pivot_world), t_w, parent)
    kw = {"id": cluster_id} if cluster_id else {}
    cluster = ClusterRigidTransform(
        name=name or _next_duplex_cluster_name(design),
        helix_ids=[helix_id], domain_ids=refs,
        parent_cluster_id=(parent.id if parent is not None else None),
        rotation=q_c, pivot=piv_c, translation=t_c,
        overhang_duplex_driver_id=driver_oh_id, **kw,
    )
    out = cleared.model_copy(update={
        "cluster_transforms": [*design.cluster_transforms, cluster]})
    return out, cluster.id


def _duplex_driven_overhang(design: Design, cluster: ClusterRigidTransform) -> Optional[str]:
    """The DRIVEN overhang id of a duplex *cluster* — the non-driver overhang whose domain
    is in the cluster's domain_ids."""
    driver = cluster.overhang_duplex_driver_id
    strand_by_id = {s.id: s for s in design.strands}
    for dr in (cluster.domain_ids or []):
        s = strand_by_id.get(dr.strand_id)
        if s is None or dr.domain_index >= len(s.domains):
            continue
        oid = s.domains[dr.domain_index].overhang_id
        if oid is not None and oid != driver:
            return oid
    return None


def duplex_cluster_rotation_points(design: Design, cluster: ClusterRigidTransform) -> list[dict]:
    """Candidate rotation POINTS for a duplex cluster's gizmo, in the REST frame the child
    transform applies in: each participating overhang's ROOT bead + the duplex CENTROID
    (user decision 4). Returns ``[{kind, overhang_id?, label, point}]``; empty if unresolved."""
    from backend.api.crud import _geometry_for_design
    from backend.core.direct_relax import _root_anchors

    driver = cluster.overhang_duplex_driver_id
    driven = _duplex_driven_overhang(design, cluster)
    if driver is None or driven is None:
        return []
    label = {o.id: (o.label or o.id[:8]) for o in design.overhangs}
    rest = design.model_copy(update={"cluster_transforms": []})
    nucs = _geometry_for_design(rest)
    p_a, _c_a, p_b, _c_b = _root_anchors(rest, nucs, driver, driven)
    out: list[dict] = []
    for oid, p in ((driver, p_a), (driven, p_b)):
        if p is not None:
            out.append({"kind": "overhang_root", "overhang_id": oid,
                        "label": f"{label.get(oid, oid[:8])} root",
                        "point": [float(p[0]), float(p[1]), float(p[2])]})
    dup = [np.asarray(n.get("backbone_position") or n.get("base_position"), dtype=float)
           for n in nucs if n.get("overhang_id") in (driver, driven)]
    if dup:
        c = np.mean(dup, axis=0)
        out.append({"kind": "centroid", "overhang_id": None, "label": "Centroid",
                    "point": [float(c[0]), float(c[1]), float(c[2])]})
    return out


def duplex_cluster_tethers(design: Design, cluster: ClusterRigidTransform) -> list[dict]:
    """Constraint tethers for a duplex cluster's free-until-taut ("wobble-until-taut") drag
    ([[overhang-duplex-cluster]] P3). Each participating overhang's applied connection is one
    backbone bond: the MOVING end is the duplex connecting bead ``c`` (on the duplex helix →
    it rides the child cluster), the FIXED end is that overhang's embedded-staple ROOT bead
    ``P`` (on the parent part → held while the duplex drags). ``contour_nm`` is one backbone
    bond (~0.67 nm), so the taut model pulls each ``c`` to within a bond of its ``P``.

    Returns ``[{moving:{helix_id,bp,direction}, fixed:{helix_id,bp,direction}, contour_nm}]``
    — the same {movingKey,fixedKey,contour} shape the gizmo's ssDNA projector consumes, once
    the client renders each anchor as a ``helix:bp:direction`` key. A standalone single-domain
    overhang (no embedded root) contributes no tether. Multivalency (an overhang in several
    Duplex edges) naturally yields more tethers as those become participating overhangs."""
    from fastapi import HTTPException

    from backend.core.direct_relax import _DEFAULT_TARGET_NM, _find_driven_tip_and_root

    driver = cluster.overhang_duplex_driver_id
    driven = _duplex_driven_overhang(design, cluster)
    out: list[dict] = []
    for oh_id in (driver, driven):
        if not oh_id:
            continue
        try:
            _s, _idx, tip_dom, root_dom, c_bp, p_bp = _find_driven_tip_and_root(design, oh_id)
        except HTTPException:
            continue   # standalone / never-applied → no embedded root bond
        out.append({
            "moving": {"helix_id": tip_dom.helix_id, "bp": int(c_bp),
                       "direction": getattr(tip_dom.direction, "value", tip_dom.direction)},
            "fixed":  {"helix_id": root_dom.helix_id, "bp": int(p_bp),
                       "direction": getattr(root_dom.direction, "value", root_dom.direction)},
            "contour_nm": float(_DEFAULT_TARGET_NM),
        })
    return out


def set_duplex_cluster_pivot(design: Design, cluster_id: str, new_pivot) -> Design:
    """Move a cluster's rotation PIVOT to *new_pivot*, rebasing the translation so the
    geometry is unchanged: ``t' = t + (R − I)·(new_pivot − old_pivot)``. Pure."""
    cl = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cl is None:
        return design
    R = _quat_to_R(cl.rotation)
    old = np.asarray(cl.pivot, dtype=float)
    newp = np.asarray(new_pivot, dtype=float)
    t = np.asarray(cl.translation, dtype=float)
    t_new = t + (R - np.eye(3)) @ (newp - old)
    new_cl = cl.model_copy(update={"pivot": [float(newp[0]), float(newp[1]), float(newp[2])],
                                   "translation": [float(t_new[0]), float(t_new[1]), float(t_new[2])]})
    return design.model_copy(update={"cluster_transforms": [
        new_cl if c.id == cluster_id else c for c in design.cluster_transforms]})


def dematerialize_duplex_cluster(design: Design, driver_oh_id: str) -> Design:
    """Inverse of :func:`materialize_duplex_cluster`: fold the duplex cluster's pose back
    onto the driver ``OverhangSpec`` (world frame) and drop the cluster. Used on unbind /
    connection teardown. No-op when no duplex cluster exists for the driver."""
    from backend.api.crud import _geometry_for_design
    from backend.core.direct_relax import _overhang_root_pivot

    cluster = duplex_cluster_for(design, driver_oh_id)
    if cluster is None:
        return design
    parent = next((c for c in design.cluster_transforms if c.id == cluster.parent_cluster_id),
                  None) if cluster.parent_cluster_id else None

    # Recover the world overlay from the child (inverse conjugation): apply the child in the
    # parent's rest frame, read the resulting world pose about the pre-overlay junction. We
    # invert numerically via the same helper run "backwards": T_world = T_P ∘ T_child ∘ T_P^{-1}.
    r_w, _piv, t_w = _child_local_pose_to_world(design, driver_oh_id, cluster, parent,
                                                _geometry_for_design, _overhang_root_pivot)
    new_clusters = [c for c in design.cluster_transforms if c.id != cluster.id]
    new_overhangs = [
        o.model_copy(update={"rotation": r_w, "translation": t_w})
        if o.id == driver_oh_id else o
        for o in design.overhangs
    ]
    return design.model_copy(update={
        "cluster_transforms": new_clusters, "overhangs": new_overhangs})


def _child_local_pose_to_world(design, driver_oh_id, child, parent,
                               geom_fn, pivot_fn) -> tuple[list[float], list[float], list[float]]:
    """Inverse of the conjugation: given the child's rest-frame pose, return the equivalent
    WORLD overlay ``(rotation, pivot_world, translation)`` about the pre-overlay junction —
    so ``apply_overhang_rotation_if_needed`` reproduces the same geometry after unbind."""
    # Geometry with the child cluster REMOVED and the driver pose cleared = parent-posed,
    # pre-overlay frame → the junction bead there is pivot_world (c).
    others = [c for c in design.cluster_transforms if c.id != child.id]
    cleared_specs = [
        o.model_copy(update={"rotation": _IDENTITY_QUAT, "translation": [0.0, 0.0, 0.0]})
        if o.id == driver_oh_id else o for o in design.overhangs
    ]
    cleared = design.model_copy(update={"cluster_transforms": others, "overhangs": cleared_specs})
    c = np.asarray(pivot_fn(cleared, geom_fn(cleared), driver_oh_id), dtype=float)

    # Build T_child (rest) and T_parent, compose T_world = T_P ∘ T_C ∘ T_P^{-1}.
    R_C = _quat_to_R(child.rotation)
    p_c = np.asarray(child.pivot, dtype=float)
    t_c = np.asarray(child.translation, dtype=float)
    if parent is None:
        R_W = R_C
        # T_C(x) = R_C(x−p_c)+p_c+t_c ; express as world overlay about c:
        # T_W(x)=R_W(x−c)+c+d ⇒ d = T_C(c) − R_W(0) ... solve d so T_W(c)=T_C(c).
        Tc_c = R_C @ (c - p_c) + p_c + t_c
        d = Tc_c - c
        return _R_to_quat(R_W), [float(c[0]), float(c[1]), float(c[2])], [float(d[0]), float(d[1]), float(d[2])]
    R_P = _quat_to_R(parent.rotation)
    a = np.asarray(parent.pivot, dtype=float)
    b = np.asarray(parent.translation, dtype=float)
    R_W = R_P @ R_C @ R_P.T

    def T_P(x):
        return R_P @ (x - a) + a + b

    def T_Pinv(y):
        return R_P.T @ (y - a - b) + a

    def T_C(x):
        return R_C @ (x - p_c) + p_c + t_c
    Tw_c = T_P(T_C(T_Pinv(c)))     # world image of the junction under the overlay
    d = Tw_c - (R_W @ (c - c) + c)  # T_W(x)=R_W(x−c)+c+d ⇒ d = Tw_c − c
    return _R_to_quat(R_W), [float(c[0]), float(c[1]), float(c[2])], [float(d[0]), float(d[1]), float(d[2])]
