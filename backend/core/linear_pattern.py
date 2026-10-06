"""One- or two-axis linear copies in part coordinates, including the source once."""

import math

import numpy as np

from backend.core.pattern_copy import copy_pattern_instances


def linear_direction(direction, vector=None):
    if direction in ("X", "Y", "Z"):
        return np.eye(3)[("X", "Y", "Z").index(direction)]
    if direction != "Custom":
        raise ValueError("Direction must be X, Y, Z, or Custom")
    axis = np.asarray(vector, dtype=float)
    if axis.shape != (3,) or not np.isfinite(axis).all():
        raise ValueError("Custom direction requires three finite XYZ components")
    length = math.hypot(*axis)
    if not math.isfinite(length) or length < 1e-8:
        raise ValueError("Custom direction must be a nonzero vector")
    return axis / length


def linear_offsets(
    instances,
    spacing,
    direction,
    *,
    two_dimensional=False,
    instances2=2,
    spacing2=10,
    direction2="Y",
    vector=None,
    vector2=None,
):
    def validate(count, distance):
        if type(count) is not int or not 1 <= count <= 128:
            raise ValueError("Instances must be an integer from 1 to 128")
        if not math.isfinite(distance) or distance == 0:
            raise ValueError("Spacing must be finite and nonzero (nm)")

    validate(instances, spacing)
    first = linear_direction(direction, vector)
    second = np.zeros(3)
    if two_dimensional:
        validate(instances2, spacing2)
        second = linear_direction(direction2, vector2)
        if np.linalg.norm(np.cross(first, second)) < 1e-8:
            raise ValueError("Choose nonparallel directions for a 2D pattern")
    else:
        instances2 = 1
    if instances * instances2 > 128:
        raise ValueError(
            "A pattern may contain at most 128 instances including the original"
        )
    offsets = []
    for j in range(instances2):
        for i in range(instances):
            offset = first * (i * spacing)
            if two_dimensional:
                offset += second * (j * spacing2)
            if not np.isfinite(offset).all():
                raise ValueError("Pattern offsets must be finite")
            offsets.append((f"{i},{j}", offset))
    return offsets


def create_linear_pattern(
    design,
    cluster_ids,
    instances,
    spacing,
    direction,
    *,
    two_dimensional=False,
    instances2=2,
    spacing2=10,
    direction2="Y",
    vector=None,
    vector2=None,
    id_seed=None,
):
    offsets = linear_offsets(
        instances,
        spacing,
        direction,
        two_dimensional=two_dimensional,
        instances2=instances2,
        spacing2=spacing2,
        direction2=direction2,
        vector=vector,
        vector2=vector2,
    )
    if not cluster_ids or len(set(cluster_ids)) != len(cluster_ids):
        raise ValueError("Select one or more distinct clusters")
    members = set()
    for cid in cluster_ids:
        cluster = next((c for c in design.cluster_transforms if c.id == cid), None)
        if cluster is None:
            raise ValueError("Source cluster no longer exists")
        ids = set(cluster.helix_ids) - design.reference_helix_ids()
        if members & ids:
            raise ValueError("Selected clusters overlap; select each helix only once")
        members |= ids
    placements = []
    for key, offset in offsets[1:]:
        pose = np.eye(4)
        pose[:3, 3] = offset
        placements.append((key, pose))
    result, ids, report = copy_pattern_instances(
        design, cluster_ids, placements, id_seed=id_seed
    )
    return result, ids, [report]
