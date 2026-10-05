"""Circular pattern placements and shared pattern history overlays."""

import math

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.pattern_copy import copy_pattern_instances


def pattern_angles(instances, total_angle):
    if type(instances) is not int or not 1 <= instances <= 128:
        raise ValueError("Instances must be an integer from 1 to 128")
    if not math.isfinite(total_angle) or not 0 < total_angle <= 360:
        raise ValueError("Total angle must be greater than 0 and at most 360 degrees")
    divisor = instances if total_angle == 360 else max(1, instances - 1)
    return [math.radians(total_angle) * i / divisor for i in range(instances)]


def create_circular_pattern(
    design,
    cluster_id,
    instances,
    total_angle,
    axis_point,
    axis_direction,
    *,
    id_seed=None,
):
    angles = pattern_angles(instances, total_angle)
    point, direction = (
        np.asarray(axis_point, dtype=float),
        np.asarray(axis_direction, dtype=float),
    )
    if (
        point.shape != (3,)
        or direction.shape != (3,)
        or not np.isfinite([point, direction]).all()
        or not math.isfinite(float(np.linalg.norm(direction)))
        or np.linalg.norm(direction) < 1e-8
    ):
        raise ValueError("A finite axis point and nonzero direction are required")
    direction = direction / np.linalg.norm(direction)
    placements = []
    for i, angle in enumerate(angles[1:], 1):
        rotation = Rotation.from_rotvec(direction * angle).as_matrix()
        turn = np.eye(4)
        turn[:3, :3] = rotation
        turn[:3, 3] = point - rotation @ point
        placements.append((str(i), turn))
    return copy_pattern_instances(design, cluster_id, placements, id_seed=id_seed)


def pattern_history_overlays(design, decode_snapshot):
    """Restore copy-owned overlays after topology seek, preserving later pose edits."""
    clusters, deformations = {}, {}
    for entry in design.feature_log:
        if (
            getattr(entry, "op_kind", None)
            not in {"circular-pattern", "linear-pattern"}
            or entry.evicted
            or not entry.post_state_gz_b64
            or not entry.design_snapshot_gz_b64
        ):
            continue
        before = decode_snapshot(entry.design_snapshot_gz_b64)
        after = decode_snapshot(entry.post_state_gz_b64)
        old_clusters = {c.id for c in before.cluster_transforms}
        old_ops = {op.id for op in before.deformations}
        clusters.update(
            {c.id: c for c in after.cluster_transforms if c.id not in old_clusters}
        )
        deformations.update(
            {op.id: op for op in after.deformations if op.id not in old_ops}
        )
    visible = {h.id for h in design.helices}
    current = {c.id: c for c in design.cluster_transforms}
    surviving = {
        cid: current.get(cid, c)
        for cid, c in clusters.items()
        if c.helix_ids and set(c.helix_ids) <= visible
    }
    result = [c for c in design.cluster_transforms if c.id not in clusters]
    result.extend(surviving.values())
    ops = [
        op
        for op in deformations.values()
        if op.affected_helix_ids and set(op.affected_helix_ids) <= visible
    ]
    return result, ops, clusters
