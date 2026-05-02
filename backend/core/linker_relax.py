"""Relax-linker optimization.

Given an OverhangConnection, find the joint angle that brings the chord between
the two overhang anchors to the duplex's "fully bound" length so the connector
arcs vanish. Updates the joint's owning cluster_transform and appends a
ClusterOpLogEntry to feature_log.

v1 scope:
  • dsDNA only (ssDNA target length will require physics later).
  • Exactly 1-DOF — exactly one joint among the two overhang clusters.
  • Joint range is currently unconstrained: sweep θ ∈ [-π, π] and pick the
    global minimizer. (Per-joint range was lost in past updates — see project
    memory `project_overhang_connections.md` tech-debt note.)
"""

from __future__ import annotations

from typing import Any

import numpy as np
from scipy.optimize import minimize_scalar

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

    A helix is a "bridge" only when SOME of its strand domains are in domain_ids
    and others aren't; that's the case where the cluster moves part of the helix
    but not all of it. The earlier definition (any domain ⇒ bridge) wrongly
    excluded fully-covered overhang stub helices once their overhang and linker
    complement were both placed in domain_ids by autodetect / `_sync_linker_cluster_membership`.
    """
    helix_id = _overhang_helix_id(design, ovhg_id)
    if helix_id is None:
        return None
    for cluster in design.cluster_transforms:
        if helix_id not in (cluster.helix_ids or []):
            continue
        if not (cluster.domain_ids or []):
            return cluster.id
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
        if not any_unmatched:
            return cluster.id
    return None


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
def relax_linker(design: Design, conn) -> tuple[Design, dict[str, Any]]:
    """Apply the relax operation to *design* for *conn*. Caller is responsible
    for the ds-only / DOF gating; this assumes both have already been checked.

    Returns (updated_design, info_dict). info_dict carries the chosen joint id,
    optimal angle (radians), final chord length, and target length, mostly for
    logging / debug.
    """
    topo = dof_topology(design, conn)
    if topo["status"] != "ok" or topo["n_dof"] != 1:
        raise ValueError(f"relax_linker: not a 1-DOF case ({topo['status']})")

    # Identify the active joint and which side moves.
    if topo["joints_a"]:
        joint_id = topo["joints_a"][0]
        moving_cluster_id = topo["cluster_a"]
        moving_ovhg_id = conn.overhang_a_id
        fixed_ovhg_id = conn.overhang_b_id
    else:
        joint_id = topo["joints_b"][0]
        moving_cluster_id = topo["cluster_b"]
        moving_ovhg_id = conn.overhang_b_id
        fixed_ovhg_id = conn.overhang_a_id

    joint = next(j for j in design.cluster_joints if j.id == joint_id)
    cluster = next(c for c in design.cluster_transforms if c.id == moving_cluster_id)

    # Anchor positions: pull from the live geometry pipeline (cluster transforms
    # already applied), so the optimization works in the rendered world frame.
    from backend.api.crud import _geometry_for_design   # local import to avoid cycles
    nucs = _geometry_for_design(design)
    moving_anchor = _anchor_position(nucs, conn.id, moving_ovhg_id, _is_a_side(conn, moving_ovhg_id))
    fixed_anchor = _anchor_position(nucs, conn.id, fixed_ovhg_id, _is_a_side(conn, fixed_ovhg_id))
    if moving_anchor is None or fixed_anchor is None:
        raise ValueError("relax_linker: could not resolve anchor positions from geometry.")

    axis_origin = np.asarray(joint.axis_origin, dtype=float)
    axis_dir = np.asarray(joint.axis_direction, dtype=float)
    n = np.linalg.norm(axis_dir)
    if n < 1e-9:
        raise ValueError("relax_linker: joint axis_direction is degenerate.")
    axis_dir = axis_dir / n

    target = _ds_target_length_nm(conn)
    theta = _optimize_angle(moving_anchor, fixed_anchor, axis_origin, axis_dir, target)
    final_pos = _moving_anchor_at(theta, moving_anchor, axis_origin, axis_dir)
    final_chord = float(np.linalg.norm(final_pos - fixed_anchor))

    # Compose new cluster transform and write it back.
    q_new, t_new = _composed_transform(cluster, axis_origin, axis_dir, theta)
    new_cluster = cluster.model_copy(update={"rotation": q_new, "translation": t_new})
    new_clusters = [new_cluster if c.id == cluster.id else c for c in design.cluster_transforms]

    # Append a ClusterOpLogEntry. Truncate any redo tail (mirrors patch_overhang_connection).
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[:design.feature_log_cursor + 1]
    log.append(ClusterOpLogEntry(
        cluster_id=cluster.id,
        translation=t_new,
        rotation=q_new,
        pivot=list(cluster.pivot),
    ))

    updated = design.copy_with(
        cluster_transforms=new_clusters,
        feature_log=log,
        feature_log_cursor=-1,
    )
    return updated, {
        "joint_id": joint_id,
        "moving_cluster_id": moving_cluster_id,
        "theta_rad": theta,
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
