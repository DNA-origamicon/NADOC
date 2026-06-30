"""Relax solver for an *applied direct* overhang connection (root-to-root or
end-to-root).

A direct connection materializes as a single non-consuming ``OverhangBinding``
(``crud._cv_create_bound_binding`` → ``binding_relax.apply_bind_topology``): the
DRIVEN overhang B's tip domain is relocated onto the DRIVER overhang A's helix,
antiparallel at A's bp range, forming a duplex. Neither overhang is consumed; B
keeps its ``OverhangSpec``. The relocation leaves B's tip connected to its own
bundle-embedded (root) domain by a now cross-helix backbone bond — that is the
only stretched bond when A's and B's parts sit in arbitrary poses.

"Relax" closes that bond to one backbone-connection length (``target_nm`` =
0.67 nm) by solving the design's kinematic model. The degrees of freedom are:

  * **2 DOF — the overhang duplex swings about the DRIVER's root bead.** A's
    overhang + B's relocated tip form a rigid duplex hinged at A's root crossover.
    Swinging it (a ball-joint rotation about the root junction) moves the duplex's
    connecting end. This is stored as A's ``OverhangSpec.rotation`` so B's relocated
    tip co-rotates natively (``apply_overhang_rotation_if_needed`` →
    ``_overhang_binding_partner_refs`` picks up the bound driven overhang) and the
    edit is a real, undoable orientation change.
  * **cluster kinematics — the rest of the model.** If A's cluster and B's root
    cluster are connected by ClusterJoint(s) (the common 1-DOF case), those joints
    rotate to bring B's root to meet the duplex; if the two clusters differ but
    have NO joint between them, B's root cluster is rigidly translated. If both
    anchors live on the SAME rigid body no cluster motion is possible — only the
    duplex swing runs.

2-DOF swing + 1-DOF joint = 3 DOF, exactly enough to drive a 3-D gap to zero.

Public entry point:

    relax_direct_binding(design, driver_oh_id, driven_oh_id, *, target_nm=0.67,
                         joint_ids=None) -> tuple[Design, dict]
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from fastapi import HTTPException
from scipy.optimize import minimize

from backend.core.linker_relax import (
    _composed_transform,
    _overhang_owning_cluster_id,
    _quat_mul,
    _rot_axis_angle,
    _THETA_REG_LAMBDA,
)
from backend.core.models import (
    ClusterOpLogEntry,
    Design,
    OverhangRotationLogEntry,
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
    raise HTTPException(422, detail=(
        f"relax_direct_binding: no relocated tip domain found for overhang "
        f"{driven_oh_id!r}. Apply the direct connection first."
    ))


def _bead_pos(nucs: list[dict], *, strand_id: str, helix_id: str,
              bp: int) -> Optional[np.ndarray]:
    """Backbone position of the geometry bead at (strand_id, helix_id, bp)."""
    for n in nucs:
        if (n.get("strand_id") == strand_id
                and n.get("helix_id") == helix_id
                and n.get("bp_index") == bp):
            p = n.get("backbone_position") or n.get("base_position")
            if p is not None:
                return np.asarray(p, dtype=float)
    return None


def _overhang_root_pivot(design: Design, nucs: list[dict],
                         driver_oh_id: str) -> Optional[np.ndarray]:
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
                return _bead_pos(nucs, strand_id=s.id, helix_id=d.helix_id,
                                 bp=junction_bp)
    return None


# ── Swing parameterisation (2-DOF ball joint about the root pivot) ────────────
def _swing_frame(arm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two orthonormal axes perpendicular to *arm* (the root→tip vector).

    Tilting the arm about these two axes spans the 2-DOF pointing sphere; the
    third (twist about the arm) doesn't move the arm tip and is omitted.
    """
    a = arm / max(1e-9, float(np.linalg.norm(arm)))
    seed = np.array([0.0, 0.0, 1.0]) if abs(a[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    u = seed - a * float(np.dot(seed, a))
    u = u / max(1e-9, float(np.linalg.norm(u)))
    v = np.cross(a, u)
    return u, v


def _swing_quat(alpha: float, beta: float,
                u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Quaternion [x,y,z,w] for the 2-DOF swing R(v, beta) ⊗ R(u, alpha)."""
    def q(axis, ang):
        h = 0.5 * ang
        s = np.sin(h)
        return np.array([axis[0] * s, axis[1] * s, axis[2] * s, np.cos(h)])
    return _quat_mul(q(v, beta), q(u, alpha))


def _quat_to_R(quat: np.ndarray) -> np.ndarray:
    """Rotation matrix from quaternion [x,y,z,w] (about origin)."""
    x, y, z, w = quat / max(1e-12, float(np.linalg.norm(quat)))
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w),     2 * (x * z + y * w)],
        [2 * (x * y + z * w),     1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w),     2 * (y * z + x * w),     1 - 2 * (x * x + y * y)],
    ])


# ── Public entry point ───────────────────────────────────────────────────────
def relax_direct_binding(
    design: Design,
    driver_oh_id: str,
    driven_oh_id: str,
    *,
    target_nm: float = _DEFAULT_TARGET_NM,
    joint_ids: Optional[list[str]] = None,
) -> tuple[Design, dict[str, Any]]:
    """Close the driven overhang's stretched tip↔root chord by swinging the
    DRIVER's overhang duplex (persisted as the driver's ``OverhangSpec.rotation``)
    and, when the two clusters differ, rotating their connecting joint(s) or
    rigidly translating the driven side's root cluster.

    Returns ``(updated_design, info)``. ``info["mode"]`` is one of
    ``"same_body"`` / ``"swing+translate"`` / ``"swing+joints"``.
    """
    from backend.api.crud import _geometry_for_design  # local import (cycle)

    a_spec = next((o for o in design.overhangs if o.id == driver_oh_id), None)
    if a_spec is None:
        raise HTTPException(422, detail=(
            f"relax_direct_binding: driver overhang {driver_oh_id!r} not found."))

    strand, _bi, tip_dom, root_dom, cb_bp, cr_bp = _find_driven_tip_and_root(
        design, driven_oh_id)
    tip_helix = tip_dom.helix_id              # == the driver's helix
    root_helix = root_dom.helix_id

    nucs = _geometry_for_design(design)
    anchor_tip = _bead_pos(nucs, strand_id=strand.id,
                           helix_id=tip_helix, bp=cb_bp)
    anchor_root = _bead_pos(nucs, strand_id=strand.id,
                            helix_id=root_helix, bp=cr_bp)
    pivot = _overhang_root_pivot(design, nucs, driver_oh_id)
    if anchor_tip is None or anchor_root is None or pivot is None:
        raise HTTPException(422, detail=(
            "relax_direct_binding: could not resolve tip/root/pivot beads "
            "from geometry."))

    cluster_tip = _overhang_owning_cluster_id(design, driver_oh_id)
    from backend.api.crud import _cluster_pair_for_bond_relax
    cb_id, cr_id = _cluster_pair_for_bond_relax(design, tip_helix, root_helix)
    if cluster_tip is None:
        cluster_tip = cb_id

    # Joints connecting the two clusters (skip when same body).
    same_body = (cluster_tip is not None and cluster_tip == cr_id)
    candidate_joints: list = []
    if not same_body:
        candidate_joints = [
            j for j in design.cluster_joints
            if j.cluster_id == cluster_tip or j.cluster_id == cr_id
        ]
        if joint_ids is not None:
            wanted = set(joint_ids)
            candidate_joints = [j for j in candidate_joints if j.id in wanted]

    # Resolve world-space joint axes once.
    cts_by_id = {c.id: c for c in design.cluster_transforms}
    selected: list[tuple] = []   # (joint, origin, axis, cluster_id, tmin, tmax)
    for j in candidate_joints:
        ct = cts_by_id.get(j.cluster_id)
        wo, wd = _local_to_world_joint(j.local_axis_origin,
                                       j.local_axis_direction, ct)
        axis = np.asarray(wd, dtype=float)
        nrm = float(np.linalg.norm(axis))
        if nrm < 1e-9:
            continue
        selected.append((
            j, np.asarray(wo, dtype=float), axis / nrm, j.cluster_id,
            float(j.min_angle_deg) * np.pi / 180.0,
            float(j.max_angle_deg) * np.pi / 180.0,
        ))

    arm = anchor_tip - pivot
    u_axis, v_axis = _swing_frame(arm)

    def _place(params: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Return (tip_anchor, root_anchor) after applying the candidate
        joint rotations (rigid) then the duplex swing about the pivot."""
        alpha, beta = params[0], params[1]
        thetas = params[2:]
        pb = anchor_tip.copy()
        pr = anchor_root.copy()
        piv = pivot.copy()
        for (_j, origin, axis, cid, _tn, _tx), th in zip(selected, thetas):
            R = _rot_axis_angle(axis, th)
            if cid == cluster_tip:
                pb = R @ (pb - origin) + origin
                piv = R @ (piv - origin) + origin
            if cid == cr_id:
                pr = R @ (pr - origin) + origin
        # Swing the tip anchor about the (possibly moved) root pivot.
        Rs = _quat_to_R(_swing_quat(alpha, beta, u_axis, v_axis))
        pb = Rs @ (pb - piv) + piv
        return pb, pr

    def _loss(params: np.ndarray) -> float:
        pb, pr = _place(params)
        chord = float(np.linalg.norm(pb - pr))
        reg = _THETA_REG_LAMBDA * float(np.sum(params * params))
        return (chord - target_nm) ** 2 + reg

    n_theta = len(selected)
    bounds = [(-np.pi, np.pi), (-np.pi, np.pi)]
    bounds += [(tmn, tmx) for (*_r, tmn, tmx) in selected]

    # Multi-start Powell: x0=0 plus a few deterministic swing seeds so a 1-DOF
    # joint case doesn't stall in the wrong basin.
    seeds = [
        np.zeros(2 + n_theta),
        np.array([0.6, 0.0] + [0.0] * n_theta),
        np.array([-0.6, 0.0] + [0.0] * n_theta),
        np.array([0.0, 0.6] + [0.0] * n_theta),
        np.array([0.0, -0.6] + [0.0] * n_theta),
    ]
    best_x, best_f = None, float("inf")
    for x0 in seeds:
        x0 = np.array([min(max(x0[i], lo), hi)
                       for i, (lo, hi) in enumerate(bounds)], dtype=float)
        res = minimize(_loss, x0, method="Powell", bounds=bounds,
                       options={"xtol": 1e-6, "ftol": 1e-10, "maxiter": 800})
        if res.fun < best_f:
            best_f, best_x = float(res.fun), np.asarray(res.x, dtype=float)
    params = best_x
    for i, (lo, hi) in enumerate(bounds):
        params[i] = float(min(max(params[i], lo), hi))

    alpha, beta = float(params[0]), float(params[1])
    thetas = params[2:]

    # 0-DOF (different clusters, no joints): rigid-translate the driven root
    # cluster to finish closing the residual along the post-swing chord.
    translate_delta = None
    if not same_body and n_theta == 0 and cr_id is not None:
        pb, pr = _place(params)
        chord_vec = pb - pr
        chord_mag = float(np.linalg.norm(chord_vec))
        if chord_mag > 1e-9:
            translate_delta = (chord_vec / chord_mag) * (chord_mag - target_nm)

    # ── Commit ───────────────────────────────────────────────────────────────
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[:design.feature_log_cursor + 1]

    # 1) Persist the swing as the driver's overhang rotation (q_new = q_swing ⊗ q_old).
    q_old = np.asarray(a_spec.rotation, dtype=float)
    q_new = _quat_mul(_swing_quat(alpha, beta, u_axis, v_axis), q_old)
    q_new = q_new / max(1e-12, float(np.linalg.norm(q_new)))
    new_overhangs = [
        o.model_copy(update={"rotation": q_new.tolist()})
        if o.id == driver_oh_id else o
        for o in design.overhangs
    ]
    log.append(OverhangRotationLogEntry(
        overhang_ids=[driver_oh_id],
        rotations=[q_new.tolist()],
        labels=[a_spec.label],
    ))

    # 2) Cluster motion: joint rotations and/or rigid translate.
    cluster_updates: dict[str, tuple[list[float], list[float]]] = {}
    for (_j, origin, axis, cid, _tn, _tx), th in zip(selected, thetas):
        cluster = next((c for c in design.cluster_transforms if c.id == cid), None)
        if cluster is None:
            continue
        if cid in cluster_updates:
            q_prev, t_prev = cluster_updates[cid]
            staged = cluster.model_copy(update={"rotation": q_prev,
                                                "translation": t_prev})
        else:
            staged = cluster
        cluster_updates[cid] = _composed_transform(staged, origin, axis, float(th))

    new_clusters = []
    for c in design.cluster_transforms:
        if c.id in cluster_updates:
            q_c, t_c = cluster_updates[c.id]
            c = c.model_copy(update={"rotation": q_c, "translation": t_c})
        if translate_delta is not None and c.id == cr_id:
            c = c.model_copy(update={
                "translation": (np.asarray(c.translation, dtype=float)
                                + translate_delta).tolist()})
        new_clusters.append(c)

    moved_cluster_ids = list(cluster_updates.keys())
    if translate_delta is not None and cr_id is not None:
        moved_cluster_ids.append(cr_id)
    for c in new_clusters:
        if c.id in moved_cluster_ids:
            log.append(ClusterOpLogEntry(
                cluster_id=c.id,
                translation=list(c.translation),
                rotation=list(c.rotation),
                pivot=list(c.pivot),
                source="relax:direct-binding",
            ))

    updated = design.copy_with(
        overhangs=new_overhangs,
        cluster_transforms=new_clusters,
        feature_log=log,
        feature_log_cursor=-1,
    )

    pb, pr = _place(params)
    if translate_delta is not None:
        pr = pr + translate_delta
    final_chord = float(np.linalg.norm(pb - pr))
    mode = ("same_body" if same_body
            else "swing+joints" if n_theta > 0
            else "swing+translate")
    return updated, {
        "mode": mode,
        "final_chord_nm": final_chord,
        "target_nm": target_nm,
        "swing_alpha_deg": alpha * 180.0 / np.pi,
        "swing_beta_deg": beta * 180.0 / np.pi,
        "thetas_deg": [float(t * 180.0 / np.pi) for t in thetas],
        "joint_ids": [j.id for (j, *_r) in selected],
        "moved_cluster_ids": moved_cluster_ids,
        "same_body": same_body,
    }
