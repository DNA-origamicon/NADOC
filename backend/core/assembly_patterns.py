"""Replayable whole-part patterns. Source designs and their histories stay intact."""

import uuid

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.circular_pattern import pattern_angles
from backend.core.linear_pattern import linear_offsets
from backend.core.models import Mat4x4


def pattern_assembly(assembly, kind, params):
    ids = params["instance_ids"]
    sources = {i.id: i for i in assembly.instances}
    if not ids or len(set(ids)) != len(ids) or any(i not in sources for i in ids):
        raise ValueError("Select distinct existing origami instances")
    placements = []
    if kind == "assembly-linear-pattern":
        keys = (
            "instances",
            "spacing",
            "direction",
            "vector",
            "two_dimensional",
            "instances2",
            "spacing2",
            "direction2",
            "vector2",
        )
        for key, offset in linear_offsets(
            **{k: params[k] for k in keys if k in params}
        )[1:]:
            pose = np.eye(4)
            pose[:3, 3] = offset
            placements.append((key, pose))
    elif kind == "assembly-circular-pattern":
        point = np.asarray(params["axis_point"], dtype=float)
        axis = np.asarray(params["axis_direction"], dtype=float)
        if (
            point.shape != (3,)
            or axis.shape != (3,)
            or not np.isfinite([point, axis]).all()
            or not np.isfinite(np.linalg.norm(axis))
            or np.linalg.norm(axis) < 1e-8
        ):
            raise ValueError("A finite axis point and nonzero direction are required")
        for index, angle in enumerate(
            pattern_angles(params["instances"], params["total_angle"])[1:], 1
        ):
            rotation = Rotation.from_rotvec(
                axis / np.linalg.norm(axis) * angle
            ).as_matrix()
            pose = np.eye(4)
            pose[:3, :3] = rotation
            pose[:3, 3] = point - rotation @ point
            placements.append((str(index), pose))
    else:
        raise ValueError("Unknown assembly pattern")
    copies = []
    for key, pose in placements:
        for source_id in ids:
            source = sources[source_id]
            copy_id = str(
                uuid.uuid5(uuid.NAMESPACE_URL, f"{params['id_seed']}:{key}:{source_id}")
            )
            if copy_id in sources:
                raise ValueError("Pattern copy identity already exists")
            copies.append(
                source.model_copy(
                    deep=True,
                    update={
                        "id": copy_id,
                        "name": f"{source.name} ({key})",
                        "transform": Mat4x4.from_array(
                            pose @ source.transform.to_array()
                        ),
                        "base_transform": None,
                    }
                )
            )
    return assembly.model_copy(update={"instances": list(assembly.instances) + copies})
