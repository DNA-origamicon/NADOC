"""Relax-linker optimization.

Given an OverhangConnection, find joint angle(s) that bring the chord between
the two overhang anchors to the duplex's "fully bound" length so the connector
arcs vanish. Updates each joint's owning cluster_transform and appends one
ClusterOpLogEntry per moved cluster to feature_log.

v2 scope:
  • dsDNA only (ssDNA target length will require physics later).
  • 1-DOF: exactly one joint between the two overhang clusters (auto-pick).
  • N-DOF: caller passes joint_ids; multivariable optimization over angles.
  • Joint range is currently unconstrained: sweep θ ∈ [-π, π] and pick the
    global minimizer per axis. (Per-joint range was lost in past updates —
    see `project_overhang_connections.md` tech-debt note.)
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize, minimize_scalar

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import ClusterOpLogEntry, Design


# ── Length unit helper (mirrors the frontend `linkerLengthToBases`) ──────────
def _linker_bp(conn) -> int:
    v = float(conn.length_value)
    if v <= 0:
        return 1
    if conn.length_unit == "nm":
        return max(1, round(v / BDNA_RISE_PER_BP))
    return max(1, round(v))


def _ds_target_length_nm(conn) -> float:
    """Distance between anchors at which both connector arcs collapse to zero
    length — equal to the duplex's visualLength in `_makeDsLinkerMeshes`."""
    return max(1, _linker_bp(conn) - 1) * BDNA_RISE_PER_BP


# ── Cluster ownership ────────────────────────────────────────────────────────
def _overhang_helix_id(design: Design, ovhg_id: str) -> str | None:
    """Return the helix the overhang's tagged domain lives on."""
    for s in design.strands:
        for d in s.domains:
            if d.overhang_id == ovhg_id:
                return d.helix_id
    return None


def _overhang_owning_cluster_id(design: Design, ovhg_id: str) -> str | None:
    """Cluster whose transform applies rigidly to the overhang's helix.

    A helix is "owned" by a cluster when:
      • cluster has no domain_ids (helix-level cluster), OR
      • every strand domain on the helix is listed in cluster.domain_ids — i.e.
        the helix is fully covered, no partial-overlap "bridge" semantics.

    When MULTIPLE clusters own the helix (common after caDNAno import: an
    auto-generated "all-scaffold" cluster spans every scaffold helix AND the
    user has finer-grained geometry sub-clusters that ALSO claim it), the
    SMALLEST cluster (by helix count) wins. The big convenience cluster is
    intended for "transform all scaffolds together" and should NOT shadow
    the smaller rigid sub-bodies that joints actually connect. Tiebreak:
    later position in cluster_transforms (user-defined clusters typically
    appear after auto-imported ones).

    A helix is a "bridge" only when SOME of its strand domains are in
    domain_ids and others aren't.
    """
    helix_id = _overhang_helix_id(design, ovhg_id)
    if helix_id is None:
        return None
    candidates: list[tuple[int, int, str]] = []  # (helix_count, neg_index_for_tiebreak, id)
    for idx, cluster in enumerate(design.cluster_transforms):
        if helix_id not in (cluster.helix_ids or []):
            continue
        if cluster.domain_ids:
            domain_keys = {(dr.strand_id, dr.domain_index) for dr in cluster.domain_ids}
            any_unmatched = False
            for s in design.strands:
                for di, dom in enumerate(s.domains):
                    if dom.helix_id != helix_id:
                        continue
                    if (s.id, di) not in domain_keys:
                        any_unmatched = True
                        break
                if any_unmatched:
                    break
            if any_unmatched:
                continue
        # Smallest helix_count first; tiebreak by later index (negative so smaller sorts first).
        candidates.append((len(cluster.helix_ids or []), -idx, cluster.id))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


# ── DOF topology ─────────────────────────────────────────────────────────────
def dof_topology(design: Design, conn) -> dict[str, Any]:
    """Describe the joint topology between the two overhangs.

    Returns:
      {
        cluster_a, cluster_b: cluster ids (or None),
        joints_a, joints_b:  ClusterJoint ids whose `cluster_id` matches each side,
        n_dof:               len(joints_a) + len(joints_b) — except 0 when the
                             two overhangs share a cluster (no axis separates them),
        status:              'ok'|'no_joints'|'shared_cluster'|'multi_dof'|'no_cluster',
        reason:              short user-readable string for display,
      }
    """
    ca = _overhang_owning_cluster_id(design, conn.overhang_a_id)
    cb = _overhang_owning_cluster_id(design, conn.overhang_b_id)
    if ca is None and cb is None:
        return _topology_dict(ca, cb, [], [], 0, "no_cluster",
                              "Neither overhang's helix is in a cluster.")
    if ca == cb and ca is not None:
        return _topology_dict(ca, cb, [], [], 0, "shared_cluster",
                              "Both overhangs are on the same cluster — no joint separates them.")
    joints_a = [j.id for j in design.cluster_joints if ca is not None and j.cluster_id == ca]
    joints_b = [j.id for j in design.cluster_joints if cb is not None and j.cluster_id == cb]
    n = len(joints_a) + len(joints_b)
    if n == 0:
        return _topology_dict(ca, cb, joints_a, joints_b, 0, "no_joints",
                              "No joints on either overhang's cluster.")
    if n == 1:
        return _topology_dict(ca, cb, joints_a, joints_b, 1, "ok", "")
    return _topology_dict(ca, cb, joints_a, joints_b, n, "multi_dof",
                          f"Relax requires exactly 1 DOF; this linker has {n}.")


def _topology_dict(ca, cb, ja, jb, n, status, reason):
    return {
        "cluster_a": ca, "cluster_b": cb,
        "joints_a": ja, "joints_b": jb,
        "n_dof": n, "status": status, "reason": reason,
    }


# ── Quaternion helpers (avoid scipy.spatial.transform dep) ──────────────────
def _quat_axis_angle(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """[qx, qy, qz, qw] for rotation by *angle_rad* around unit *axis*."""
    half = 0.5 * angle_rad
    s = np.sin(half)
    return np.array([axis[0] * s, axis[1] * s, axis[2] * s, np.cos(half)])


def _quat_mul(q1: np.ndarray, q2: np.ndarray) -> np.ndarray:
    """Hamilton product q1 ⊗ q2 with [x,y,z,w] convention."""
    x1, y1, z1, w1 = q1
    x2, y2, z2, w2 = q2
    return np.array([
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
    ])


def _rot_axis_angle(axis: np.ndarray, angle_rad: float) -> np.ndarray:
    """Rodrigues 3×3 rotation matrix around unit *axis*."""
    a = axis / max(1e-12, np.linalg.norm(axis))
    K = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + np.sin(angle_rad) * K + (1 - np.cos(angle_rad)) * (K @ K)


# ── Optimization ─────────────────────────────────────────────────────────────
def _moving_anchor_at(theta: float, base_anchor: np.ndarray,
                       axis_origin: np.ndarray, axis_dir: np.ndarray) -> np.ndarray:
    """Where the moving anchor lands when its cluster is rotated by *theta*
    around (axis_origin, axis_dir). The base_anchor is the anchor's CURRENT
    world position (already includes any prior cluster transform); we pivot
    it by `theta` around the joint axis."""
    R = _rot_axis_angle(axis_dir, theta)
    return R @ (base_anchor - axis_origin) + axis_origin


def _optimize_angle(moving_anchor: np.ndarray, fixed_anchor: np.ndarray,
                    axis_origin: np.ndarray, axis_dir: np.ndarray,
                    target_len: float) -> float:
    """Brent-bounded search for θ ∈ [-π, π] minimizing
    (|p_moving(θ) − p_fixed| − target_len)²."""
    def loss(theta: float) -> float:
        p = _moving_anchor_at(theta, moving_anchor, axis_origin, axis_dir)
        return (np.linalg.norm(p - fixed_anchor) - target_len) ** 2

    # Brent on a symmetric interval can land in a local min when the function
    # has multiple basins (it does — circular motion has period 2π). Sweep a
    # coarse grid first, then refine around the best bucket.
    grid = np.linspace(-np.pi, np.pi, 73)   # every 5°
    losses = [loss(t) for t in grid]
    i = int(np.argmin(losses))
    lo = grid[max(0, i - 2)]
    hi = grid[min(len(grid) - 1, i + 2)]
    res = minimize_scalar(loss, bounds=(lo, hi), method="bounded",
                          options={"xatol": 1e-5})
    return float(res.x)


# ── Cluster transform composition ────────────────────────────────────────────
def _composed_transform(cluster, axis_origin: np.ndarray, axis_dir: np.ndarray,
                        theta: float) -> tuple[list[float], list[float]]:
    """Return (rotation_quat, translation) for the cluster after composing an
    additional rotation by *theta* around (axis_origin, axis_dir).

    Pivot is unchanged. Derivation:
      Existing transform: p' = R(p − pivot) + pivot + t
      Joint rotation:     p'' = R_j(p' − O) + O
      ⇒ p'' = (R_j R)(p − pivot) + R_j(pivot + t − O) + O
           = R_new (p − pivot) + pivot + t_new
      where R_new = R_j R, t_new = R_j(pivot + t − O) + O − pivot.
    """
    pivot = np.asarray(cluster.pivot, dtype=float)
    trans = np.asarray(cluster.translation, dtype=float)
    q_existing = np.asarray(cluster.rotation, dtype=float)
    q_joint = _quat_axis_angle(axis_dir, theta)
    q_new = _quat_mul(q_joint, q_existing)
    R_j = _rot_axis_angle(axis_dir, theta)
    t_new = R_j @ (pivot + trans - axis_origin) + axis_origin - pivot
    return q_new.tolist(), t_new.tolist()


# ── Public entry point ───────────────────────────────────────────────────────
def relax_linker(
    design: Design, conn, joint_ids: list[str] | None = None,
) -> tuple[Design, dict[str, Any]]:
    """Apply the relax operation to *design* for *conn*.

    joint_ids:
      None       — auto-pick: requires the 1-DOF case (uses dof_topology).
      [single]   — same single-axis path as 1-DOF.
      [j1, j2…]  — multi-DOF: optimize all angles jointly so the chord lands
                   on the duplex target length. Each joint rotates ITS OWN
                   cluster (joint.cluster_id) around its axis.

    Returns (updated_design, info_dict). info_dict carries per-joint angles,
    final chord length, and target length, for logging / debug.
    """
    topo = dof_topology(design, conn)

    if joint_ids is None:
        if topo["status"] != "ok" or topo["n_dof"] != 1:
            raise ValueError(f"relax_linker: not a 1-DOF case ({topo['status']})")
        # Auto-pick the single joint.
        joint_ids = topo["joints_a"] or topo["joints_b"]

    if not joint_ids:
        raise ValueError("relax_linker: no joints to relax over.")

    # Resolve joint records and validate axes.
    joints_by_id = {j.id: j for j in design.cluster_joints}
    selected: list[tuple[str, np.ndarray, np.ndarray, str]] = []   # (joint_id, origin, axis, cluster_id)
    for jid in joint_ids:
        j = joints_by_id.get(jid)
        if j is None:
            raise ValueError(f"relax_linker: joint id {jid!r} not found.")
        axis = np.asarray(j.axis_direction, dtype=float)
        n = np.linalg.norm(axis)
        if n < 1e-9:
            raise ValueError(f"relax_linker: joint {jid!r} axis_direction is degenerate.")
        selected.append((j.id, np.asarray(j.axis_origin, dtype=float), axis / n, j.cluster_id))

    # Resolve anchor positions in the live geometry frame (cluster transforms
    # already applied).
    from backend.api.crud import _geometry_for_design   # local import to avoid cycles
    nucs = _geometry_for_design(design)
    anchor_a = _anchor_position(nucs, conn.id, conn.overhang_a_id, True)
    anchor_b = _anchor_position(nucs, conn.id, conn.overhang_b_id, False)
    if anchor_a is None or anchor_b is None:
        raise ValueError("relax_linker: could not resolve anchor positions from geometry.")

    # Map anchor → cluster ownership so we know whether each joint rotates
    # anchor_a, anchor_b, both, or neither.
    cluster_of_a = topo["cluster_a"]
    cluster_of_b = topo["cluster_b"]
    target = _ds_target_length_nm(conn)

    def _apply(thetas: np.ndarray, p_a: np.ndarray, p_b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Apply the proposed joint angles to the two anchor positions. Each
        joint rotates only the anchor whose cluster matches the joint's
        cluster_id; other anchors are unaffected. Joints are applied in the
        order given (matters when multiple joints share a cluster — composition
        order changes the result)."""
        for (_jid, origin, axis, cluster_id), theta in zip(selected, thetas):
            R = _rot_axis_angle(axis, theta)
            if cluster_id == cluster_of_a:
                p_a = R @ (p_a - origin) + origin
            if cluster_id == cluster_of_b:
                p_b = R @ (p_b - origin) + origin
        return p_a, p_b

    # ── Optimize ─────────────────────────────────────────────────────────────
    if len(selected) == 1:
        # Use the existing scalar Brent path — slightly more robust on a single
        # variable than the multivariable optimizer.
        _jid, origin, axis, cluster_id = selected[0]
        moving = anchor_a if cluster_id == cluster_of_a else anchor_b
        fixed  = anchor_b if cluster_id == cluster_of_a else anchor_a
        theta = _optimize_angle(moving, fixed, origin, axis, target)
        thetas = np.array([theta])
    else:
        def loss(thetas: np.ndarray) -> float:
            p_a, p_b = _apply(thetas, anchor_a.copy(), anchor_b.copy())
            return (np.linalg.norm(p_a - p_b) - target) ** 2
        x0 = np.zeros(len(selected))
        res = minimize(loss, x0, method="Powell",
                       options={"xtol": 1e-5, "ftol": 1e-8, "maxiter": 500})
        thetas = np.asarray(res.x, dtype=float)

    final_a, final_b = _apply(thetas, anchor_a.copy(), anchor_b.copy())
    final_chord = float(np.linalg.norm(final_a - final_b))

    # Apply each joint's rotation to its owning cluster transform. Multiple
    # joints can share a cluster (rare but supported); compose them in order.
    cluster_updates: dict[str, tuple[list[float], list[float]]] = {}   # cluster_id → (rot, trans)
    for (_jid, origin, axis, cluster_id), theta in zip(selected, thetas):
        cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
        if cluster is None:
            continue
        # Use the latest pending update if this cluster has already been touched;
        # otherwise start from the cluster's stored transform.
        if cluster_id in cluster_updates:
            q_prev, t_prev = cluster_updates[cluster_id]
            staged = cluster.model_copy(update={"rotation": q_prev, "translation": t_prev})
        else:
            staged = cluster
        cluster_updates[cluster_id] = _composed_transform(staged, origin, axis, float(theta))

    new_clusters = []
    for c in design.cluster_transforms:
        if c.id in cluster_updates:
            q_new, t_new = cluster_updates[c.id]
            new_clusters.append(c.model_copy(update={"rotation": q_new, "translation": t_new}))
        else:
            new_clusters.append(c)

    # Append one ClusterOpLogEntry per touched cluster. Truncate any redo tail.
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[:design.feature_log_cursor + 1]
    for c in new_clusters:
        if c.id in cluster_updates:
            log.append(ClusterOpLogEntry(
                cluster_id=c.id,
                translation=list(c.translation),
                rotation=list(c.rotation),
                pivot=list(c.pivot),
            ))

    updated = design.copy_with(
        cluster_transforms=new_clusters,
        feature_log=log,
        feature_log_cursor=-1,
    )
    return updated, {
        "joint_ids": [jid for (jid, *_rest) in selected],
        "thetas_rad": [float(t) for t in thetas],
        "moved_cluster_ids": list(cluster_updates.keys()),
        "final_chord_nm": final_chord,
        "target_length_nm": target,
    }


# ── Anchor lookup (mirrors frontend `_linkerAttachAnchor`) ────────────────────
def _is_a_side(conn, ovhg_id: str) -> bool:
    return ovhg_id == conn.overhang_a_id


def _anchor_position(nucs: list[dict], conn_id: str, ovhg_id: str, is_a_side: bool):
    """Position of the linker complement bead at the OH attach end, falling back
    to the OH bead itself when the linker complement isn't in geometry. Mirrors
    `_linkerAttachAnchor` in overhang_link_arcs.js so the optimization sees the
    same point the renderer draws."""
    side = "a" if is_a_side else "b"
    linker_strand_id = f"__lnk__{conn_id}__{side}"
    oh_nucs = [n for n in nucs if n.get("overhang_id") == ovhg_id]
    if not oh_nucs:
        return None
    tip = next((n for n in oh_nucs if n.get("is_five_prime") or n.get("is_three_prime")), oh_nucs[0])
    # The frontend treats `attach == 'root'` as the OH nuc farthest from the tip
    # in bp space; for relax purposes we always anchor at the tip (the bead that
    # the linker complement actually sits on), since cluster rotation moves the
    # whole strand rigidly and the chord-vs-target heuristic doesn't care which
    # bp index we anchor on.
    target_nuc = tip
    partner = next((n for n in nucs if n.get("strand_id") == linker_strand_id
                    and n.get("helix_id") == target_nuc.get("helix_id")
                    and n.get("bp_index") == target_nuc.get("bp_index")), None)
    nuc = partner if partner is not None else target_nuc
    pos = nuc.get("backbone_position") or nuc.get("base_position")
    return np.asarray(pos, dtype=float) if pos is not None else None
