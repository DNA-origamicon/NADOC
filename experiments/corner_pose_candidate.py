"""Isolated native-bead corner refinement; no normal display/export caller.

Search a small rigid pose adjustment with the existing clash + 4*stretch
objective and unchanged bond/angle limits. Topology and helix lengths stay fixed.
"""

import numpy as np
from scipy.spatial import cKDTree
from scipy.spatial.transform import Rotation
from backend.api import headless_corner_build as corner
from backend.core.clash import (
    _bead_arrays,
    DEFAULT_CLASH_THRESHOLD_NM as THR,
    DEFAULT_DESIGNED_MARGIN_NM as MARGIN,
)
from backend.core.deformation import deformed_helix_axes


def refine(design):
    spec = corner.resolve_corner_spec(design)
    bids = {corner._helix_id(c) for c in spec.b_cols}
    (cluster,) = [
        c
        for c in design.cluster_transforms
        if not c.is_default and set(c.helix_ids) == bids
    ]
    keys, points = _bead_arrays(design)
    skeys, straight = _bead_arrays(
        design.copy_with(deformations=[], cluster_transforms=[])
    )
    assert keys == skeys
    moving = np.array([k[0] in bids for k in keys])
    aa, bb = np.flatnonzero(~moving), np.flatnonzero(moving)
    tree = cKDTree(points[aa])
    excluded = {
        (i, j)
        for j, hits in enumerate(
            cKDTree(straight[aa]).query_ball_point(straight[bb], MARGIN)
        )
        for i in hits
    }
    fl_pairs = corner._fl_partner_pairs(design)
    excluded.update(
        (i, j)
        for i, ai in enumerate(aa)
        for j, bj in enumerate(bb)
        if frozenset((keys[ai][:3], keys[bj][:3])) in fl_pairs
    )
    raw = corner._bead_map(design)
    fixed_bonds, moving_bonds = [], []
    for fl in design.forced_ligations:
        a = (fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction.name)
        b = (fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction.name)
        if a[0] in bids:
            a, b = b, a
        assert a[0] not in bids and b[0] in bids
        fixed_bonds.append(raw[a])
        moving_bonds.append(raw[b])
    fixed_bonds, moving_bonds = map(np.asarray, (fixed_bonds, moving_bonds))
    pivot = moving_bonds.mean(0)
    axes = {
        a["helix_id"]: np.asarray(a["end"]) - a["start"]
        for a in deformed_helix_axes(design)
    }
    axis_a = np.mean(
        [
            axes[corner._helix_id(c)] / np.linalg.norm(axes[corner._helix_id(c)])
            for c in spec.a_cols
        ],
        axis=0,
    )
    axis_b = np.mean(
        [
            axes[corner._helix_id(c)] / np.linalg.norm(axes[corner._helix_id(c)])
            for c in spec.b_cols
        ],
        axis=0,
    )

    def evaluate(rotation, offset):
        bonds = np.linalg.norm(
            (moving_bonds - pivot) @ rotation.T + pivot + offset - fixed_bonds, axis=1
        )
        angle = np.degrees(
            np.arccos(
                np.clip(
                    np.dot(axis_a, rotation @ axis_b)
                    / np.linalg.norm(axis_a)
                    / np.linalg.norm(axis_b),
                    -1,
                    1,
                )
            )
        )
        if bonds.max() >= 1 or abs(angle - 90) > 5:
            return None
        shifted = (points[bb] - pivot) @ rotation.T + pivot + offset
        n = sum(
            (i, j) not in excluded
            for j, hits in enumerate(tree.query_ball_point(shifted, THR))
            for i in hits
        )
        return n, float(bonds.sum()), float(bonds.max()), float(angle)

    base = evaluate(np.eye(3), np.zeros(3))
    if base is None:
        return design, {
            "unchanged": True,
            "reason": "Initial pose violates the existing feasibility bounds",
        }
    assert base[0] == corner.steric_clash_count(design), base
    best = (base, np.eye(3), np.zeros(3))
    for axis in np.eye(3):
        for degrees in np.arange(-2, 2.01, 0.5):
            rotation = Rotation.from_rotvec(axis * np.radians(degrees)).as_matrix()
            for offset in (
                np.array(np.meshgrid(*[np.arange(-0.3, 0.301, 0.1)] * 3))
                .reshape(3, -1)
                .T
            ):
                metrics = evaluate(rotation, offset)
                if (
                    metrics is not None
                    and metrics[0] + 4 * metrics[1] < best[0][0] + 4 * best[0][1] - 1e-9
                ):
                    best = (metrics, rotation, offset)
    metrics, rotation, offset = best
    p = np.asarray(cluster.pivot)
    t = np.asarray(cluster.translation)
    candidate = design.copy_with(
        cluster_transforms=[
            c.model_copy(
                update={
                    "rotation": Rotation.from_matrix(
                        rotation @ Rotation.from_quat(c.rotation).as_matrix()
                    )
                    .as_quat()
                    .tolist(),
                    "translation": (
                        rotation @ (p + t - pivot) + pivot + offset - p
                    ).tolist(),
                }
            )
            if c.id == cluster.id
            else c
            for c in design.cluster_transforms
        ]
    )
    actual = {
        "clashes": corner.steric_clash_count(candidate),
        "bonds_nm": corner.forced_ligation_stretches(candidate),
        "angle_deg": corner.corner_face_angle_deg(candidate, spec),
    }
    assert actual["clashes"] == metrics[0], (actual, metrics)
    assert candidate.strands == design.strands and candidate.helices == design.helices
    return candidate, {
        "current": base,
        "candidate": actual,
        "rotation_deg": np.degrees(Rotation.from_matrix(rotation).as_rotvec()).tolist(),
        "offset_nm": offset.tolist(),
        "production_changed": False,
    }
