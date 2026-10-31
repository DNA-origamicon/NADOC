"""Parent kinematics followed by exact covalent-root duplex placement."""

import numpy as np
from fastapi import HTTPException
from scipy.optimize import minimize

from backend.core.direct_root_placement import capture_root_lengths, place_direct_roots
from backend.core.overhang_root_constraints import overhang_root_bond


def _targets(design, driver, driven):
    from backend.core.binding_relax import revert_bind_topology

    pair = {driver, driven}
    snapshots = [b.prior_driven_topology for b in design.overhang_bindings
                 if {b.overhang_a_id, b.overhang_b_id} == pair and b.prior_driven_topology]
    snapshots += [d.prior_driven_topology for d in design.duplexes
                  if {d.left.overhang_id, d.right.overhang_id} == pair and d.prior_driven_topology]
    if not snapshots:
        raise HTTPException(422, detail="Relax requires the connection's original root geometry.")
    snapshot = snapshots[0]
    if "root_bond_lengths_nm" in snapshot:
        return snapshot["root_bond_lengths_nm"]
    # Existing bound records already retain the unbound topology. Measure its
    # native lengths rather than treating a manually stretched pose as the target.
    return capture_root_lengths(revert_bind_topology(design, snapshot), [driver, driven])


def relax_direct_roots(design, driver, driven, *, joint_ids=None):
    from backend.core.direct_relax import _find_driven_tip_and_root, _relax_joint_selection
    from backend.core.duplex_cluster import dematerialize_duplex_cluster, duplex_cluster_for
    from backend.core.linker_relax import _composed_transform, _optimize_chord_angle, _rot_axis_angle

    original = design
    child = duplex_cluster_for(design, driver)
    working = dematerialize_duplex_cluster(design, driver)
    _, _, tip, root, _, _ = _find_driven_tip_and_root(working, driven)
    ca, cb, same, clusters, selected = _relax_joint_selection(working, driver, tip.helix_id, root.helix_id, joint_ids)
    targets = _targets(original, driver, driven)
    roots = {oid: overhang_root_bond(working, oid) for oid in targets}
    thetas = np.zeros(len(selected))
    moved = set()
    target_chord = None
    try:
        # Preserve parent poses when swinging/translating the duplex can close
        # both roots. This also makes a settled result exactly idempotent.
        placed = place_direct_roots(original, driver, targets)
    except HTTPException as failure:
        if failure.status_code != 422 or same or driver not in roots or driven not in roots:
            raise
        a, b = roots[driver], roots[driven]
        span = float(np.linalg.norm(b.moving - a.moving))
        la, lb = targets[driver]["viewer"], targets[driven]["viewer"]
        lower = max(0., span - la - lb, la - span - lb, lb - span - la)
        upper = span + la + lb
        gap = float(np.linalg.norm(b.fixed - a.fixed))
        # Start just inside the reachable interval to avoid a singular fully
        # extended chain. Exact root lengths remain independently enforced.
        inset = min(1e-5, (upper - lower) / 4)
        target_chord = float(np.clip(gap, lower + inset, upper - inset))

        def anchors(angles):
            pa, pb = a.fixed.copy(), b.fixed.copy()
            for (_, origin, axis, cid, _, _), angle in zip(selected, angles):
                rotation = _rot_axis_angle(axis, angle)
                if cid == ca:
                    pa = rotation @ (pa - origin) + origin
                if cid == cb:
                    pb = rotation @ (pb - origin) + origin
            return pa, pb

        if len(selected) == 1:
            _, origin, axis, cid, lo, hi = selected[0]
            mobile, fixed = (a.fixed, b.fixed) if cid == ca else (b.fixed, a.fixed)
            thetas[0] = _optimize_chord_angle(mobile, fixed, origin, axis, target_chord, lo, hi)
        elif selected:
            def loss(angles):
                pa, pb = anchors(angles)
                return (np.linalg.norm(pb - pa) - target_chord) ** 2
            solved = minimize(loss, thetas, method="Powell", bounds=[(lo, hi) for *_, lo, hi in selected],
                              options={"xtol": 1e-7, "ftol": 1e-12, "maxiter": 800})
            thetas = solved.x
        elif cb is None:
            raise failure

        updated = dict(clusters)
        for (_, origin, axis, cid, _, _), angle in zip(selected, thetas):
            q, t = _composed_transform(updated[cid], origin, axis, float(angle))
            updated[cid] = updated[cid].model_copy(update={"rotation": q, "translation": t})
            if abs(angle) > 1e-12:
                moved.add(cid)
        if not selected:
            direction = b.fixed - a.fixed
            if gap <= 1e-9:
                direction = b.moving - a.moving
            direction /= np.linalg.norm(direction)
            delta = (target_chord - gap) * direction
            updated[cb] = updated[cb].model_copy(update={
                "translation": (np.asarray(updated[cb].translation) + delta).tolist()})
            moved.add(cb)
        parent_motion = original.copy_with(cluster_transforms=[updated.get(c.id, c) for c in original.cluster_transforms])
        placed = place_direct_roots(parent_motion, driver, targets)

    from backend.core.models import ClusterOpLogEntry, OverhangRotationLogEntry

    log = list(original.feature_log)
    if original.feature_log_cursor == -2:
        log = []
    elif original.feature_log_cursor >= 0:
        log = log[:original.feature_log_cursor + 1]
    for c in placed.cluster_transforms:
        if c.id in moved or (child is not None and c.id == child.id):
            log.append(ClusterOpLogEntry(cluster_id=c.id, translation=list(c.translation),
                rotation=list(c.rotation), pivot=list(c.pivot),
                source="relax:duplex-cluster" if child is not None and c.id == child.id else "relax:direct-binding"))
    if child is None:
        spec = next(o for o in placed.overhangs if o.id == driver)
        log.append(OverhangRotationLogEntry(overhang_ids=[driver], rotations=[list(spec.rotation)], labels=[spec.label]))
    placed = placed.copy_with(feature_log=log, feature_log_cursor=-1)
    measured = capture_root_lengths(placed, targets)
    final_a = overhang_root_bond(placed, driver)
    final_b = overhang_root_bond(placed, driven)
    root_chord = float(np.linalg.norm(final_b.fixed - final_a.fixed)) if final_a is not None else 0.
    return placed, {"mode": "same_body" if same else "joints" if selected else "translate",
        "final_chord_nm": measured[driven]["viewer"], "target_nm": targets[driven]["viewer"],
        "final_root_chord_nm": root_chord,
        "target_root_chord_nm": target_chord if target_chord is not None else root_chord,
        "duplex_span_nm": float(np.linalg.norm(final_b.moving - final_a.moving)) if final_a is not None else 0.,
        "thetas_deg": np.rad2deg(thetas).tolist(), "joint_ids": [j.id for j, *_ in selected],
        "moved_cluster_ids": sorted(moved), "same_body": same, "clash_spin_deg": 0.,
        "root_bond_lengths_nm": measured, "root_targets_nm": targets}
