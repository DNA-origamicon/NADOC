"""Generic relax solver for any stretched backbone bond.

Subsumes the special-case relaxers (linker, binding) into a single
optimization core. The caller supplies two anchor positions (one per
"side") and a target chord magnitude; the solver brings the chord to
target by either:

* **0-DOF**: rigidly translating the user-chosen cluster (``side_to_move``).
* **1-DOF**: rotating the joint-side cluster about the single joint
  connecting the two clusters.
* **N-DOF**: Powell-optimizing all joints that connect the clusters
  (chord-magnitude loss + θ² regulariser to break ties).

Same-cluster bonds are refused (no relaxation is possible — both endpoints
already move rigidly together).

Public entry points:

    relax_bond(design, *, anchor_a, anchor_b, cluster_a_id, cluster_b_id,
               target_nm, side_to_move=None, joint_ids=None,
               source_tag="bond-relax") -> tuple[Design, dict]
"""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
from fastapi import HTTPException
from scipy.optimize import minimize

from backend.core.linker_relax import (
    _composed_transform,
    _optimize_angle,
    _rot_axis_angle,
    _THETA_REG_LAMBDA,
)
from backend.core.models import (
    ClusterOpLogEntry,
    Design,
    _local_to_world_joint,
)


def relax_bond(
    design: Design,
    *,
    anchor_a: np.ndarray,
    anchor_b: np.ndarray,
    cluster_a_id: str,
    cluster_b_id: str,
    target_nm: float,
    side_to_move: Optional[str] = None,
    joint_ids: Optional[list[str]] = None,
    source_tag: str = "bond-relax",
) -> tuple[Design, dict[str, Any]]:
    """Relax a bond by moving one or both of its owning clusters.

    Parameters
    ----------
    anchor_a, anchor_b : np.ndarray (3,)
        Current world-space positions of the bond's two endpoints.
    cluster_a_id, cluster_b_id : str
        Owning clusters of side A / side B. Must differ; 422 otherwise.
    target_nm : float
        Desired chord magnitude ``|anchor_a − anchor_b|`` post-relax.
    side_to_move : "a" | "b" | None
        Which cluster gets transformed in the 0-DOF case. Required when no
        joints are passed AND the topology has no joints between the two
        clusters. Ignored otherwise.
    joint_ids : list[str] | None
        Joints to optimise. If None, auto-pick: all joints whose
        ``cluster_id`` matches either side. Empty list/None with no joints
        between the clusters falls back to 0-DOF rigid translate.
    source_tag : str
        Logged on each emitted ``ClusterOpLogEntry`` so the feature-log
        panel can distinguish bond-relax events from manual cluster moves.

    Returns
    -------
    (updated_design, info)  — info carries ``mode`` ("translate" /
    "1dof" / "ndof"), final ``chord_nm``, and any joint angles applied.
    """
    if cluster_a_id == cluster_b_id:
        raise HTTPException(422, detail=(
            "relax_bond: both bond endpoints share a cluster — no relaxation "
            "is possible (the bond moves rigidly with the cluster)."
        ))

    cts_by_id = {c.id: c for c in design.cluster_transforms}
    if cluster_a_id not in cts_by_id or cluster_b_id not in cts_by_id:
        raise HTTPException(422, detail=(
            "relax_bond: one or both endpoint clusters not found."
        ))

    # Joints connecting the two clusters.
    candidate_joints = [
        j for j in design.cluster_joints
        if j.cluster_id == cluster_a_id or j.cluster_id == cluster_b_id
    ]
    if joint_ids is not None:
        # User pinned a subset; intersect.
        wanted = set(joint_ids)
        candidate_joints = [j for j in candidate_joints if j.id in wanted]
        missing = wanted - {j.id for j in candidate_joints}
        if missing:
            raise HTTPException(422, detail=(
                f"relax_bond: joint ids {sorted(missing)!r} not on either "
                f"endpoint's cluster."
            ))

    if not candidate_joints:
        return _relax_translate(
            design,
            anchor_a=anchor_a,
            anchor_b=anchor_b,
            cluster_a_id=cluster_a_id,
            cluster_b_id=cluster_b_id,
            target_nm=target_nm,
            side_to_move=side_to_move,
            source_tag=source_tag,
        )

    if len(candidate_joints) == 1:
        return _relax_one_joint(
            design,
            anchor_a=anchor_a,
            anchor_b=anchor_b,
            cluster_a_id=cluster_a_id,
            cluster_b_id=cluster_b_id,
            target_nm=target_nm,
            joint=candidate_joints[0],
            source_tag=source_tag,
        )

    return _relax_n_joints(
        design,
        anchor_a=anchor_a,
        anchor_b=anchor_b,
        cluster_a_id=cluster_a_id,
        cluster_b_id=cluster_b_id,
        target_nm=target_nm,
        joints=candidate_joints,
        source_tag=source_tag,
    )


# ── 0-DOF: rigid translate ───────────────────────────────────────────────────

def _relax_translate(
    design: Design,
    *,
    anchor_a: np.ndarray,
    anchor_b: np.ndarray,
    cluster_a_id: str,
    cluster_b_id: str,
    target_nm: float,
    side_to_move: Optional[str],
    source_tag: str,
) -> tuple[Design, dict[str, Any]]:
    if side_to_move not in ("a", "b"):
        raise HTTPException(422, detail=(
            "relax_bond: no joints between the two clusters; "
            "side_to_move (\"a\" or \"b\") must be specified to choose "
            "which cluster translates."
        ))
    chord = anchor_b - anchor_a   # vector from A to B
    chord_mag = float(np.linalg.norm(chord))
    if chord_mag < 1e-9:
        return design, {"mode": "translate", "chord_nm": chord_mag,
                        "moved_cluster": cluster_b_id if side_to_move == "b" else cluster_a_id}

    # Shrink the chord to `target_nm`. The moving anchor slides along the
    # chord toward the fixed anchor by ``chord_mag − target_nm``.
    delta_mag = chord_mag - target_nm
    unit = chord / chord_mag
    if side_to_move == "a":
        # A moves toward B → +unit (since chord points A→B)
        delta = +unit * delta_mag
        moved_cluster_id = cluster_a_id
    else:
        # B moves toward A → −unit
        delta = -unit * delta_mag
        moved_cluster_id = cluster_b_id

    new_clusters = []
    moved_ct = None
    for c in design.cluster_transforms:
        if c.id == moved_cluster_id:
            moved_ct = c.model_copy(update={
                "translation": (
                    np.asarray(c.translation, dtype=float) + delta
                ).tolist(),
            })
            new_clusters.append(moved_ct)
        else:
            new_clusters.append(c)

    nxt = _commit_clusters(design, new_clusters, [moved_cluster_id], source_tag)
    return nxt, {
        "mode": "translate",
        "moved_cluster": moved_cluster_id,
        "delta_nm": list(delta),
        "chord_nm_before": chord_mag,
        "chord_nm_after": target_nm,
    }


# ── 1-DOF: one-joint rotate ─────────────────────────────────────────────────

def _relax_one_joint(
    design: Design,
    *,
    anchor_a: np.ndarray,
    anchor_b: np.ndarray,
    cluster_a_id: str,
    cluster_b_id: str,
    target_nm: float,
    joint,
    source_tag: str,
) -> tuple[Design, dict[str, Any]]:
    cts_by_id = {c.id: c for c in design.cluster_transforms}
    ct = cts_by_id.get(joint.cluster_id)
    world_origin, world_dir = _local_to_world_joint(
        joint.local_axis_origin, joint.local_axis_direction, ct,
    )
    axis = np.asarray(world_dir, dtype=float)
    nrm = float(np.linalg.norm(axis))
    if nrm < 1e-9:
        raise HTTPException(422, detail=(
            f"Joint {joint.id} axis is degenerate."
        ))
    axis = axis / nrm
    origin = np.asarray(world_origin, dtype=float)

    moving_is_a = (joint.cluster_id == cluster_a_id)
    moving_anchor = anchor_a if moving_is_a else anchor_b
    fixed_anchor = anchor_b if moving_is_a else anchor_a

    theta_min = float(joint.min_angle_deg) * np.pi / 180.0
    theta_max = float(joint.max_angle_deg) * np.pi / 180.0

    theta_rad = _optimize_angle_chord_target(
        moving_anchor=moving_anchor,
        fixed_anchor=fixed_anchor,
        axis_origin=origin,
        axis_dir=axis,
        target_nm=target_nm,
        theta_min=theta_min,
        theta_max=theta_max,
    )

    cluster = cts_by_id[joint.cluster_id]
    q_new, t_new = _composed_transform(cluster, origin, axis, float(theta_rad))
    new_clusters = []
    for c in design.cluster_transforms:
        if c.id == joint.cluster_id:
            new_clusters.append(c.model_copy(update={
                "rotation": list(q_new),
                "translation": list(t_new),
            }))
        else:
            new_clusters.append(c)

    nxt = _commit_clusters(design, new_clusters, [joint.cluster_id], source_tag)
    return nxt, {
        "mode": "1dof",
        "joint_id": joint.id,
        "theta_deg": float(theta_rad * 180.0 / np.pi),
        "moved_cluster": joint.cluster_id,
    }


# ── N-DOF: Powell over all joints ───────────────────────────────────────────

def _relax_n_joints(
    design: Design,
    *,
    anchor_a: np.ndarray,
    anchor_b: np.ndarray,
    cluster_a_id: str,
    cluster_b_id: str,
    target_nm: float,
    joints: list,
    source_tag: str,
) -> tuple[Design, dict[str, Any]]:
    cts_by_id = {c.id: c for c in design.cluster_transforms}

    selected: list[tuple] = []
    for j in joints:
        ct = cts_by_id.get(j.cluster_id)
        wo, wd = _local_to_world_joint(
            j.local_axis_origin, j.local_axis_direction, ct,
        )
        axis = np.asarray(wd, dtype=float)
        nrm = float(np.linalg.norm(axis))
        if nrm < 1e-9:
            raise HTTPException(422, detail=(
                f"Joint {j.id} axis is degenerate."
            ))
        axis = axis / nrm
        selected.append((
            j,
            np.asarray(wo, dtype=float),
            axis,
            j.cluster_id,
            float(j.min_angle_deg) * np.pi / 180.0,
            float(j.max_angle_deg) * np.pi / 180.0,
        ))

    def _apply(thetas: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pa = anchor_a.copy()
        pb = anchor_b.copy()
        for (_j, origin, axis, cid, _tmin, _tmax), theta in zip(selected, thetas):
            R = _rot_axis_angle(axis, theta)
            if cid == cluster_a_id:
                pa = R @ (pa - origin) + origin
            if cid == cluster_b_id:
                pb = R @ (pb - origin) + origin
        return pa, pb

    def loss(thetas: np.ndarray) -> float:
        pa, pb = _apply(thetas)
        chord = float(np.linalg.norm(pa - pb))
        residual = chord - target_nm
        return (residual * residual) + _THETA_REG_LAMBDA * float(np.sum(thetas * thetas))

    bounds = [(tmin, tmax) for (*_rest, tmin, tmax) in selected]
    x0 = np.array(
        [min(max(0.0, tmin), tmax) for (tmin, tmax) in bounds],
        dtype=float,
    )
    res = minimize(
        loss, x0, method="Powell", bounds=bounds,
        options={"xtol": 1e-5, "ftol": 1e-8, "maxiter": 500},
    )
    thetas = np.asarray(res.x, dtype=float)
    for i, (tmin, tmax) in enumerate(bounds):
        thetas[i] = float(min(max(thetas[i], tmin), tmax))

    # Compose per-cluster transforms in joint order.
    staged: dict[str, tuple[list[float], list[float], list[float]]] = {}
    for (j, origin, axis, cid, _tmin, _tmax), theta in zip(selected, thetas):
        cluster = cts_by_id[cid]
        if cid in staged:
            q_prev, t_prev, _pivot = staged[cid]
            stub = cluster.model_copy(update={
                'rotation': q_prev, 'translation': t_prev,
            })
        else:
            stub = cluster
        q_new, t_new = _composed_transform(stub, origin, axis, float(theta))
        staged[cid] = (q_new, t_new, list(cluster.pivot))

    new_clusters = []
    for c in design.cluster_transforms:
        if c.id in staged:
            q_new, t_new, _pv = staged[c.id]
            new_clusters.append(c.model_copy(update={
                "rotation": q_new, "translation": t_new,
            }))
        else:
            new_clusters.append(c)

    pa_final, pb_final = _apply(thetas)
    final_chord = float(np.linalg.norm(pa_final - pb_final))

    nxt = _commit_clusters(design, new_clusters, list(staged.keys()), source_tag)
    return nxt, {
        "mode": "ndof",
        "thetas_deg": [float(t * 180.0 / np.pi) for t in thetas],
        "joint_ids": [j.id for (j, *_r) in selected],
        "chord_nm": final_chord,
        "target_nm": target_nm,
    }


# ── Shared helpers ──────────────────────────────────────────────────────────

def _optimize_angle_chord_target(
    *,
    moving_anchor: np.ndarray,
    fixed_anchor: np.ndarray,
    axis_origin: np.ndarray,
    axis_dir: np.ndarray,
    target_nm: float,
    theta_min: float,
    theta_max: float,
) -> float:
    """Bounded 1-DOF brent search for θ that brings chord magnitude to
    *target_nm*. Mirrors the structure of linker_relax._optimize_angle but
    against a free chord target instead of the bridge-arc loss."""

    def chord_loss(theta: float) -> float:
        R = _rot_axis_angle(axis_dir, theta)
        p_moving = R @ (moving_anchor - axis_origin) + axis_origin
        chord = float(np.linalg.norm(p_moving - fixed_anchor))
        residual = chord - target_nm
        return residual * residual

    if theta_max <= theta_min + 1e-9:
        return 0.5 * (theta_min + theta_max)

    # Coarse 5° grid + brent refine, identical pattern to _optimize_angle.
    step = 5.0 * np.pi / 180.0
    n_grid = max(3, int(np.ceil((theta_max - theta_min) / step)) + 1)
    grid = np.linspace(theta_min, theta_max, n_grid)
    losses = [chord_loss(t) for t in grid]
    candidate_idxs: list[int] = []
    n = len(grid)
    for i in range(n):
        if i == 0:
            if n > 1 and losses[i] < losses[i + 1]:
                candidate_idxs.append(i)
        elif i == n - 1:
            if losses[i] < losses[i - 1]:
                candidate_idxs.append(i)
        else:
            if losses[i] < losses[i - 1] and losses[i] < losses[i + 1]:
                candidate_idxs.append(i)
    if not candidate_idxs:
        candidate_idxs = [int(np.argmin(losses))]

    from scipy.optimize import minimize_scalar
    refined: list[tuple[float, float]] = []
    for i in candidate_idxs:
        lo = grid[max(0, i - 2)]
        hi = grid[min(n - 1, i + 2)]
        if hi <= lo + 1e-9:
            refined.append((float(grid[i]), float(losses[i])))
            continue
        res = minimize_scalar(
            chord_loss, bounds=(lo, hi), method="bounded",
            options={"xatol": 1e-5},
        )
        refined.append((float(res.x), float(res.fun)))

    best = min(c for _, c in refined)
    tol = 1e-6
    near = [(t, c) for t, c in refined if c <= best + tol]
    near.sort(key=lambda tc: abs(tc[0]))
    return near[0][0]


def _commit_clusters(
    design: Design,
    new_clusters: list,
    moved_cluster_ids: list[str],
    source_tag: str,
) -> Design:
    """Replace ``design.cluster_transforms`` and append a
    ``ClusterOpLogEntry`` per moved cluster. Mirrors the relax_linker tail
    block (truncate redo on cursor, reset cursor to −1)."""
    moved_set = set(moved_cluster_ids)
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[:design.feature_log_cursor + 1]
    for c in new_clusters:
        if c.id in moved_set:
            log.append(ClusterOpLogEntry(
                cluster_id=c.id,
                translation=list(c.translation),
                rotation=list(c.rotation),
                pivot=list(c.pivot),
                source=source_tag,
            ))
    return design.model_copy(update={
        "cluster_transforms": new_clusters,
        "feature_log": log,
        "feature_log_cursor": -1,
    })
