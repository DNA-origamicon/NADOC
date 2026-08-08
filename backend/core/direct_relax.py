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
    _optimize_chord_angle,
    _overhang_owning_cluster_id,
    _quat_axis_angle,
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

# The relax is UNDER-CONSTRAINED: the 2-DOF overhang swing alone can close the
# tip↔root chord at essentially any hinge angle, so the joint θ is a null-space
# (free) parameter. The reg term is too weak to pin it, so a raw Powell result
# drifts / overshoots the hinge (and the relax isn't even idempotent). We resolve
# the redundancy the way the user asked — MINIMISE TOTAL MOTION (Σ swing² + hinge²)
# — via a lexicographic post-selection: among all candidate solutions (incl. the
# do-nothing params=0) whose chord is within this band of the BEST achievable chord,
# take the one with the least Σparams². This makes the relax converge to the
# minimal-movement pose and be idempotent once the bond is already closed.
_CHORD_ACCEPT_BAND_NM = 0.02


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


def duplex_midpoint_placement(
    design: Design,
    driver_oh_id: str,
    driven_oh_id: str,
) -> Optional[tuple[list[float], list[float]]]:
    """Rigid placement (rotation + translation) that re-seats a just-relocated
    DIRECT connection's duplex like a linker bridge: **oriented along** and
    **centered on** the chord between its two embedded-staple connections
    (``bridge_axis_geometry`` orients the bridge along and centers it at
    ``(p_a + p_b)/2``).

    A direct apply relocates the DRIVEN tip onto the DRIVER's helix, leaving the
    whole tip↔root stretch on the driven side and an arbitrary duplex orientation.
    Each side of the duplex exposes two beads:

      * ``c`` — the duplex's own connecting bead (the overhang bp bonded to its root);
      * ``P`` — the embedded-staple root bead it bonds to.

    We place the rigid duplex so its connection axis ``c_A→c_B`` aligns with the
    anchor chord ``P_A→P_B`` and its midpoint lands on ``(P_A + P_B)/2``:

        T(p) = R·(p − center) + M,   center = (c_A+c_B)/2,  M = (P_A+P_B)/2,
        R aligns (c_B − c_A) → (P_B − P_A).

    Both residual root bonds then come out equal and minimal (``bond_A = −bond_B``,
    each ``(gap − span)/2`` along the chord). The geometry code applies the overhang
    transform about the junction bead ``p0`` (``= c_A``) as
    ``R·(p − p0) + p0 + translation``, so we return the ``translation`` that makes
    that form equal ``T``:

        translation = R·(p0 − center) + (M − p0).

    Returns ``(rotation_quat[x,y,z,w], translation[nm])`` in the CURRENT geometry
    frame, or ``None`` if any bead can't be resolved (e.g. a standalone single-domain
    driver with no embedded root) — caller then leaves rotation/translation identity.
    Pure read — does not mutate ``design``.
    """
    from backend.api.crud import _geometry_for_design

    nucs = _geometry_for_design(design)

    def _connection(oh_id: str) -> Optional[tuple[np.ndarray, np.ndarray]]:
        # A standalone single-domain overhang has NO embedded-staple (root)
        # connection — `_find_driven_tip_and_root` raises 422. That side simply
        # isn't anchored to a bundle, so there is no bond to balance; return None
        # and let the caller fall back to no re-seating (one-sided placement).
        try:
            strand, _bi, tip_dom, root_dom, c_bp, p_bp = _find_driven_tip_and_root(
                design, oh_id
            )
        except HTTPException:
            return None
        c = _bead_pos(nucs, strand_id=strand.id, helix_id=tip_dom.helix_id, bp=c_bp)
        p = _bead_pos(nucs, strand_id=strand.id, helix_id=root_dom.helix_id, bp=p_bp)
        return None if (c is None or p is None) else (c, p)

    driver = _connection(driver_oh_id)
    driven = _connection(driven_oh_id)
    if driver is None or driven is None:
        return None
    c_a, p_a = driver
    c_b, p_b = driven
    p0 = _overhang_root_pivot(design, nucs, driver_oh_id)  # junction bead == c_A
    if p0 is None:
        p0 = c_a

    q = _quat_align(c_b - c_a, p_b - p_a)  # align duplex axis → anchor chord
    R = _quat_to_R(q)
    center = (c_a + c_b) / 2.0
    M = (p_a + p_b) / 2.0
    translation = R @ (p0 - center) + (M - p0)
    return (
        [float(q[0]), float(q[1]), float(q[2]), float(q[3])],
        [float(translation[0]), float(translation[1]), float(translation[2])],
    )


# ── Clash-avoidance rotation of the duplex about the root→root axis ───────────
def _wrap(th: float) -> float:
    """Wrap an angle into (−π, π] (used to prefer the least-motion clash angle)."""
    return (th + np.pi) % (2.0 * np.pi) - np.pi


def _min_clash_rotation(
    nucs: list[dict],
    moving_overhang_ids: set,
    origin: np.ndarray,
    axis: np.ndarray,
    *,
    threshold_nm: float = 1.8,
    n_samples: int = 24,
) -> float:
    """Angle (rad) about (``origin``, ``axis``) applied to the DUPLEX beads (those whose
    ``overhang_id`` is in *moving_overhang_ids*) that MINIMISES steric contacts with all
    OTHER beads.

    The axis is the root→root line; after the midpoint re-seat the duplex's two connecting
    beads are collinear on it, so every angle preserves both duplex↔root bonds — only the
    duplex's paired region swings around (~a helix diameter) to dodge clashes, which is what
    makes a subsequent simulation easier to equilibrate. Returns ``0.0`` when there is
    nothing to de-clash; ties break toward the smallest |angle| (least motion)."""
    try:
        from scipy.spatial import cKDTree
    except Exception:  # pragma: no cover - SciPy always present in this project
        return 0.0
    moving, other = [], []
    for n in nucs:
        p = n.get("backbone_position") or n.get("base_position")
        if p is None:
            continue
        (moving if n.get("overhang_id") in moving_overhang_ids else other).append(p)
    if not moving or not other:
        return 0.0
    moving_arr = np.asarray(moving, dtype=float)
    other_arr = np.asarray(other, dtype=float)
    tree = cKDTree(other_arr)
    a = axis / max(1e-12, float(np.linalg.norm(axis)))
    best: Optional[tuple] = None
    for k in range(n_samples):
        th = 2.0 * np.pi * k / n_samples
        R = _rot_axis_angle(a, th)
        rot = (moving_arr - origin) @ R.T + origin
        clash = sum(len(ix) for ix in tree.query_ball_point(rot, r=threshold_nm))
        key = (clash, abs(_wrap(th)))
        if best is None or key < best[0]:
            best = (key, th)
    return best[1] if best is not None else 0.0


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


def relax_direct_binding(
    design: Design,
    driver_oh_id: str,
    driven_oh_id: str,
    *,
    target_nm: float = _DEFAULT_TARGET_NM,
    joint_ids: Optional[list[str]] = None,
) -> tuple[Design, dict[str, Any]]:
    """Settle an applied DIRECT connection the way a dsDNA linker bridge is relaxed
    (``linker_relax.relax_linker``), then de-clash the duplex.

    The duplex was already seated at the oriented midpoint on apply, so:

      1. **Arc minimization (cluster kinematics, the bridge method).** Anchors = the two
         embedded-staple root beads ``P_A`` / ``P_B``. Rotate the connecting joint(s) —
         1-DOF via ``_optimize_chord_angle`` (grid + all-minima + smallest-|θ|), N-DOF via
         Powell — to drive ``|P_A − P_B|`` → ``span + 2·target_nm`` (duplex span + one
         backbone bond per end). No joint but distinct clusters → rigid-translate the driven
         cluster. Same rigid body ⇒ no cluster motion.
      2. **Re-seat the duplex** at the new oriented midpoint (``duplex_midpoint_placement``
         → the DRIVER's ``OverhangSpec.rotation`` + ``translation``), so both bonds land at
         ``target_nm``.
      3. **Clash-avoidance rotation of the OVERHANG DUPLEX ONLY.** Rotate the duplex (driver
         overhang + driven tip, via the driver's ``OverhangSpec.rotation``) about the
         root→root axis to the least-clashing angle — NOT the driven cluster (the whole part
         must stay put). After the re-seat the duplex's two connecting beads are collinear
         on that axis, so every angle preserves both bonds while the paired region swings
         clear of neighbouring structure.

    Returns ``(updated_design, info)``. ``info["mode"]`` ∈
    ``"same_body"`` / ``"joints"`` / ``"translate"``.
    """
    from backend.api.crud import _cluster_pair_for_bond_relax, _geometry_for_design
    from backend.core.duplex_cluster import (
        dematerialize_duplex_cluster,
        duplex_cluster_for,
        materialize_duplex_cluster,
    )

    # When the duplex pose lives on a child cluster ([[overhang-duplex-cluster]]), fold it
    # back onto the OverhangSpec overlay for the duration of the (unchanged) solve, then
    # re-materialize onto the cluster at the end — so the solver's geometry reads stay
    # consistent (no double-transform) and the result lands back on the cluster.
    _dcl = duplex_cluster_for(design, driver_oh_id)
    _had_cluster = _dcl is not None
    _prev_cluster_id = _dcl.id if _dcl is not None else None
    if _had_cluster:
        design = dematerialize_duplex_cluster(design, driver_oh_id)

    a_spec = next((o for o in design.overhangs if o.id == driver_oh_id), None)
    if a_spec is None:
        raise HTTPException(
            422,
            detail=(
                f"relax_direct_binding: driver overhang {driver_oh_id!r} not found."
            ),
        )

    strand, _bi, tip_dom, root_dom, _cb, _cr = _find_driven_tip_and_root(
        design, driven_oh_id
    )
    tip_helix = tip_dom.helix_id  # == the driver's helix (relocated tip)
    root_helix = root_dom.helix_id  # driven overhang's own root helix

    nucs = _geometry_for_design(design)
    p_a, c_a, p_b, c_b = _root_anchors(design, nucs, driver_oh_id, driven_oh_id)
    if p_b is None or c_b is None or c_a is None:
        raise HTTPException(
            422,
            detail=(
                "relax_direct_binding: could not resolve the duplex / root anchor beads "
                "from geometry. Apply the direct connection first."
            ),
        )
    # A standalone single-domain driver has no root bond; anchor on its duplex end.
    n_bonds = 2 if p_a is not None else 1
    anchor_a = p_a if p_a is not None else c_a
    anchor_b = p_b
    span = float(np.linalg.norm(c_a - c_b))  # duplex length (rigid-invariant)
    target_chord = span + n_bonds * target_nm

    # Cluster ownership of the two root anchors.
    cb_id, cr_id = _cluster_pair_for_bond_relax(design, tip_helix, root_helix)
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

    # ── 1) Arc minimization: bring |P_A − P_B| → target_chord ──────────────────
    def _place(thetas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pa = anchor_a.copy()
        pb = anchor_b.copy()
        for (_j, origin, axis, cid, _tn, _tx), th in zip(selected, thetas):
            R = _rot_axis_angle(axis, th)
            if cid == cluster_a:
                pa = R @ (pa - origin) + origin
            if cid == cluster_b:
                pb = R @ (pb - origin) + origin
        return pa, pb

    thetas = np.zeros(len(selected))
    if len(selected) == 1:
        _j, origin, axis, cid, tmin, tmax = selected[0]
        moving_is_a = cid == cluster_a
        moving = anchor_a if moving_is_a else anchor_b
        fixed = anchor_b if moving_is_a else anchor_a
        thetas = np.array(
            [
                _optimize_chord_angle(
                    moving, fixed, origin, axis, target_chord, tmin, tmax
                )
            ]
        )
    elif len(selected) > 1:

        def _loss(th: np.ndarray) -> float:
            pa, pb = _place(th)
            return (
                float(np.linalg.norm(pa - pb)) - target_chord
            ) ** 2 + _THETA_REG_LAMBDA * float(np.sum(th * th))

        bounds = [(tmn, tmx) for (*_r, tmn, tmx) in selected]
        x0 = np.array([min(max(0.0, tmn), tmx) for (tmn, tmx) in bounds], dtype=float)
        res = minimize(
            _loss,
            x0,
            method="Powell",
            bounds=bounds,
            options={"xtol": 1e-6, "ftol": 1e-10, "maxiter": 800},
        )
        thetas = np.asarray(res.x, dtype=float)
        for i, (tmn, tmx) in enumerate(bounds):
            thetas[i] = float(min(max(thetas[i], tmn), tmx))

    # No joint but distinct clusters → rigid-translate the driven cluster to target.
    translate_delta = None
    if not same_body and not selected and cluster_b is not None:
        chord_vec = anchor_b - anchor_a
        chord_mag = float(np.linalg.norm(chord_vec))
        if chord_mag > 1e-9:
            u = chord_vec / chord_mag
            translate_delta = (target_chord - chord_mag) * u

    cluster_updates: dict[str, tuple[list[float], list[float]]] = {}
    for (_j, origin, axis, cid, _tn, _tx), th in zip(selected, thetas):
        cluster = cts_by_id.get(cid)
        if cluster is None:
            continue
        if cid in cluster_updates:
            q_prev, t_prev = cluster_updates[cid]
            staged = cluster.model_copy(
                update={"rotation": q_prev, "translation": t_prev}
            )
        else:
            staged = cluster
        cluster_updates[cid] = _composed_transform(staged, origin, axis, float(th))

    def _clusters_with(updates, delta):
        out = []
        for c in design.cluster_transforms:
            if c.id in updates:
                q_c, t_c = updates[c.id]
                c = c.model_copy(update={"rotation": q_c, "translation": t_c})
            if delta is not None and c.id == cluster_b:
                c = c.model_copy(
                    update={
                        "translation": (
                            np.asarray(c.translation, dtype=float) + delta
                        ).tolist()
                    }
                )
            out.append(c)
        return out

    clusters_final = _clusters_with(cluster_updates, translate_delta)

    # ── 2) Re-seat the duplex at the new oriented midpoint ─────────────────────
    zeroed_overhangs = [
        o.model_copy(
            update={"rotation": [0.0, 0.0, 0.0, 1.0], "translation": [0.0, 0.0, 0.0]}
        )
        if o.id == driver_oh_id
        else o
        for o in design.overhangs
    ]
    design_motion = design.model_copy(
        update={
            "cluster_transforms": clusters_final,
            "overhangs": zeroed_overhangs,
        }
    )
    placement = duplex_midpoint_placement(design_motion, driver_oh_id, driven_oh_id)
    if placement is not None:
        q_seat, t_seat = placement
    else:
        q_seat, t_seat = [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0]

    # ── 3) Clash-avoidance rotation of the DUPLEX ONLY (driver OverhangSpec) ───
    seated_overhangs = [
        o.model_copy(update={"rotation": q_seat, "translation": t_seat})
        if o.id == driver_oh_id
        else o
        for o in design.overhangs
    ]
    design_seated = design_motion.model_copy(update={"overhangs": seated_overhangs})
    nucs2 = _geometry_for_design(design_seated)
    pa2, _ca2, pb2, _cb2 = _root_anchors(
        design_seated, nucs2, driver_oh_id, driven_oh_id
    )
    # The geometry pipeline applies the OverhangSpec transform about the UN-SEATED
    # junction pivot (driver zeroed → the relocated position, which is OFF the root→root
    # axis), so composing the clash spin needs the full pivot-aware translation formula.
    nucs_motion = _geometry_for_design(design_motion)
    p0u = _overhang_root_pivot(design_motion, nucs_motion, driver_oh_id)

    q_final, t_final = list(q_seat), list(t_seat)
    clash_theta = 0.0
    if (
        pa2 is not None
        and pb2 is not None
        and p0u is not None
        and float(np.linalg.norm(pb2 - pa2)) > 1e-6
    ):
        axis_rr = (pb2 - pa2) / float(np.linalg.norm(pb2 - pa2))
        clash_theta = _min_clash_rotation(
            nucs2, {driver_oh_id, driven_oh_id}, pa2, axis_rr
        )
        if abs(_wrap(clash_theta)) > 1e-6:
            # Rotate the SEATED duplex about the root→root line (origin pa2): the seated
            # transform T_seat(p) = R_seat·(p−p0u)+p0u+t_seat is post-rotated, giving
            # R_final = R_clash·R_seat and t_final = R_clash·(p0u+t_seat−pa2)+pa2−p0u.
            # Both duplex connecting beads lie on the axis, so both bonds are preserved.
            q_clash = _quat_axis_angle(axis_rr, float(clash_theta))
            R_clash = _rot_axis_angle(axis_rr, float(clash_theta))
            qf = _quat_mul(q_clash, np.asarray(q_seat, dtype=float))
            qf = qf / max(1e-12, float(np.linalg.norm(qf)))
            q_final = qf.tolist()
            t_seat_arr = np.asarray(t_seat, dtype=float)
            t_final = (R_clash @ (p0u + t_seat_arr - pa2) + pa2 - p0u).tolist()

    final_overhangs = [
        o.model_copy(update={"rotation": q_final, "translation": t_final})
        if o.id == driver_oh_id
        else o
        for o in design.overhangs
    ]

    # ── Commit + feature log ───────────────────────────────────────────────────
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[: design.feature_log_cursor + 1]

    # When cluster-backed, the pose moves onto the duplex cluster below, so we log a
    # ClusterOpLogEntry for it (NOT an OverhangRotationLogEntry that would set — and on
    # feature-log SEEK, double-transform — the now-cleared OverhangSpec). The overlay
    # (legacy) path still logs the overhang rotation.
    if not _had_cluster:
        log.append(
            OverhangRotationLogEntry(
                overhang_ids=[driver_oh_id],
                rotations=[q_final],
                labels=[a_spec.label],
            )
        )

    moved_cluster_ids = set(cluster_updates.keys())
    if translate_delta is not None and cluster_b is not None:
        moved_cluster_ids.add(cluster_b)
    for c in clusters_final:
        if c.id in moved_cluster_ids:
            log.append(
                ClusterOpLogEntry(
                    cluster_id=c.id,
                    translation=list(c.translation),
                    rotation=list(c.rotation),
                    pivot=list(c.pivot),
                    source="relax:direct-binding",
                )
            )

    updated = design.copy_with(
        overhangs=final_overhangs,
        cluster_transforms=clusters_final,
        feature_log=log,
        feature_log_cursor=-1,
    )

    # Re-seat the pose onto the child duplex cluster if it was cluster-backed on entry —
    # reusing the SAME cluster id so its ClusterOpLogEntry (below) is stable across relaxes
    # and replays correctly. Feature-log SEEK now reconstructs the duplex-cluster pose from
    # that cluster_op instead of double-transforming the cleared OverhangSpec.
    if _had_cluster:
        updated, _cid = materialize_duplex_cluster(
            updated, driver_oh_id, cluster_id=_prev_cluster_id
        )
        dcl = duplex_cluster_for(updated, driver_oh_id)
        if dcl is not None:
            seek_log = list(updated.feature_log) + [
                ClusterOpLogEntry(
                    cluster_id=dcl.id,
                    translation=list(dcl.translation),
                    rotation=list(dcl.rotation),
                    pivot=list(dcl.pivot),
                    source="relax:duplex-cluster",
                )
            ]
            updated = updated.copy_with(feature_log=seek_log, feature_log_cursor=-1)

    # Final tip↔root (driven B-bond) chord — the clash spin keeps it fixed (both its
    # beads are on the spin axis), so read it off the seated geometry.
    _s, _i2, td2, rd2, cb_bp2, cr_bp2 = _find_driven_tip_and_root(
        design_seated, driven_oh_id
    )
    fb = _bead_pos(nucs2, strand_id=_s.id, helix_id=td2.helix_id, bp=cb_bp2)
    fr = _bead_pos(nucs2, strand_id=_s.id, helix_id=rd2.helix_id, bp=cr_bp2)
    final_chord = (
        float(np.linalg.norm(fb - fr))
        if (fb is not None and fr is not None)
        else float("nan")
    )
    final_root_chord = (
        float(np.linalg.norm(pb2 - pa2))
        if (pa2 is not None and pb2 is not None)
        else float("nan")
    )
    mode = "same_body" if same_body else ("joints" if selected else "translate")
    return updated, {
        "mode": mode,
        "final_chord_nm": final_chord,
        "final_root_chord_nm": final_root_chord,
        "target_root_chord_nm": target_chord,
        "target_nm": target_nm,
        "duplex_span_nm": span,
        "thetas_deg": [float(t * 180.0 / np.pi) for t in thetas],
        "clash_spin_deg": float(clash_theta * 180.0 / np.pi),
        "joint_ids": [j.id for (j, *_r) in selected],
        "moved_cluster_ids": list(moved_cluster_ids),
        "same_body": same_body,
    }
