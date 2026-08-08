"""
API layer — cluster joint route handlers (extracted from crud.py).

This module hosts the ``/design/cluster/{id}/joint`` + ``/design/joint/{id}``
CRUD endpoints: place a revolute joint on a cluster, update it, delete it. A
cluster carries at most one joint; its axis is stored in the cluster's LOCAL
frame so it stays drift-free under subsequent cluster transforms (world-space
inputs are converted at the endpoint via ``_world_to_local_joint``). Each op is
recorded as a minor feature-log op (``joint-place`` / ``joint-update`` /
``joint-delete``) under the open Fine Routing cluster.

This is the SIBLING of the cluster rigid-transform router (``routes_clusters.py``)
but a genuinely separate resource — ``cluster_joints`` are the ds-linker / Plan-B
joint records, a different reason to change than the cluster pose CRUD — so it
gets its own module. The three pure builders (``_build_add_joint`` /
``_build_update_joint`` / ``_build_delete_joint``) live here and are imported
back **function-locally** by crud.py's ``_replay_minor_op`` dispatcher (a
top-level import would be circular, since this module imports ``_design_response``
back from crud.py — same resolution as the assembly polymerize/overhang routers).

Factored out of ``crud.py`` following the same template as ``routes_clusters.py``
(the cluster-transform sibling) and the camera-poses / loop-skip exemplars.

Routes
------
  POST   /design/cluster/{cluster_id}/joint  — place a revolute joint (minor-logged)
  PATCH  /design/joint/{joint_id}            — update joint props (minor-logged)
  DELETE /design/joint/{joint_id}            — remove a joint (minor-logged)

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state

# _design_response is the shared response helper used by 100+ crud.py routes; it
# stays in crud.py and is imported back here (same convention as
# routes_clusters.py / routes_camera_poses.py).
from backend.api.crud import _design_response
from backend.core.models import ClusterJoint, Design

router = APIRouter()


class AddJointBody(BaseModel):
    axis_origin: List[float]  # [x, y, z] nm world-space
    axis_direction: List[float]  # unit vector (normalised by backend)
    surface_detail: int = 6  # lateral face count used in surface approximation
    name: str = "Joint"
    min_angle_deg: float = -180.0  # mechanical lower limit (degrees)
    max_angle_deg: float = 180.0  # mechanical upper limit (degrees)


class PatchJointBody(BaseModel):
    axis_origin: Optional[List[float]] = None
    axis_direction: Optional[List[float]] = None
    surface_detail: Optional[int] = None
    name: Optional[str] = None
    min_angle_deg: Optional[float] = None
    max_angle_deg: Optional[float] = None


def _build_add_joint(design: Design, params: dict) -> Design:
    """Pure builder for the joint-place op.

    *params* keys: cluster_id, joint_id, name, surface_detail,
    local_axis_origin, local_axis_direction.

    Stored axis is already in the cluster's local frame; world-space inputs
    are converted at the endpoint before this builder is called so the
    feature-log params are deterministic across replays (the local-frame
    axis is invariant under subsequent cluster transforms).
    """
    cluster_id = params["cluster_id"]
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cluster is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")
    joint = ClusterJoint(
        id=params["joint_id"],
        cluster_id=cluster_id,
        name=params.get("name", "Joint"),
        local_axis_origin=list(params["local_axis_origin"]),
        local_axis_direction=list(params["local_axis_direction"]),
        surface_detail=int(params.get("surface_detail", 6)),
        min_angle_deg=float(params.get("min_angle_deg", -180.0)),
        max_angle_deg=float(params.get("max_angle_deg", 180.0)),
    )
    # Each cluster has at most one joint — replace any existing one.
    existing = [j for j in design.cluster_joints if j.cluster_id != cluster_id]
    return design.copy_with(cluster_joints=existing + [joint])


def _build_update_joint(design: Design, params: dict) -> Design:
    """Pure builder for the joint-update op.

    *params* keys: joint_id and any subset of name, surface_detail,
    local_axis_origin, local_axis_direction. The endpoint resolves
    world→local and stores the local-frame fields directly, so replay is
    deterministic regardless of intervening cluster transforms.
    """
    joint_id = params["joint_id"]
    joints = list(design.cluster_joints)
    idx = next((i for i, j in enumerate(joints) if j.id == joint_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")
    fields: dict = {}
    if "name" in params:
        fields["name"] = params["name"]
    if "surface_detail" in params:
        fields["surface_detail"] = int(params["surface_detail"])
    if "local_axis_origin" in params:
        fields["local_axis_origin"] = list(params["local_axis_origin"])
    if "local_axis_direction" in params:
        fields["local_axis_direction"] = list(params["local_axis_direction"])
    if "min_angle_deg" in params:
        fields["min_angle_deg"] = float(params["min_angle_deg"])
    if "max_angle_deg" in params:
        fields["max_angle_deg"] = float(params["max_angle_deg"])
    # Pydantic re-runs the model validator on `model_copy(update=…)`, so an
    # update that would invert min/max is caught here rather than silently
    # accepted.
    cur = joints[idx]
    new_min = fields.get("min_angle_deg", cur.min_angle_deg)
    new_max = fields.get("max_angle_deg", cur.max_angle_deg)
    if new_max < new_min:
        raise HTTPException(
            400,
            detail=f"max_angle_deg ({new_max}) must be >= min_angle_deg ({new_min}).",
        )
    joints[idx] = joints[idx].model_copy(update=fields)
    return design.copy_with(cluster_joints=joints)


def _build_delete_joint(design: Design, params: dict) -> Design:
    """Pure builder for the joint-delete op."""
    joint_id = params["joint_id"]
    joints = [j for j in design.cluster_joints if j.id != joint_id]
    if len(joints) == len(design.cluster_joints):
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")
    return design.copy_with(cluster_joints=joints)


@router.post("/design/cluster/{cluster_id}/joint", status_code=200)
def add_joint(cluster_id: str, body: AddJointBody) -> dict:
    """Create a revolute joint on a cluster.

    The frontend computes the axis as the face-normal of the cluster's
    hull approximation in WORLD space (where the user clicked) and sends
    it here. The backend normalises the direction and converts to the
    cluster's LOCAL frame for storage so the axis stays drift-free under
    subsequent cluster transforms. Logged as a 'joint-place' minor op
    under the open Fine Routing cluster (or opens a new one).
    """
    import math as _math
    import uuid as _uuid
    from backend.core.models import _world_to_local_joint

    design = design_state.get_or_404()
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cluster is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    dx, dy, dz = body.axis_direction[0], body.axis_direction[1], body.axis_direction[2]
    length = _math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-9:
        raise HTTPException(400, detail="axis_direction must be a non-zero vector.")
    world_direction = [dx / length, dy / length, dz / length]

    ct_dict = {
        "rotation": list(cluster.rotation),
        "translation": list(cluster.translation),
        "pivot": list(cluster.pivot),
    }
    local_origin, local_dir = _world_to_local_joint(
        list(body.axis_origin),
        world_direction,
        ct_dict,
    )

    if body.max_angle_deg < body.min_angle_deg:
        raise HTTPException(
            400,
            detail=f"max_angle_deg ({body.max_angle_deg}) must be >= "
            f"min_angle_deg ({body.min_angle_deg}).",
        )
    params = {
        "cluster_id": cluster_id,
        "joint_id": str(_uuid.uuid4()),
        "name": body.name,
        "surface_detail": body.surface_detail,
        "local_axis_origin": local_origin,
        "local_axis_direction": local_dir,
        "min_angle_deg": body.min_angle_deg,
        "max_angle_deg": body.max_angle_deg,
    }
    label = f"Place joint {body.name!r} on cluster {cluster_id}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="joint-place",
        label=label,
        params=params,
        fn=lambda d: _build_add_joint(d, params),
    )
    return _design_response(updated, report)


@router.patch("/design/joint/{joint_id}", status_code=200)
def update_joint(joint_id: str, body: PatchJointBody) -> dict:
    """Update joint properties.

    Body's axis_origin / axis_direction are interpreted as WORLD-space
    (matching the create endpoint's input convention). They're converted
    to the cluster's local frame before storage. Logged as a 'joint-update'
    minor op.
    """
    import math as _math
    from backend.core.models import _world_to_local_joint, _local_to_world_joint

    design = design_state.get_or_404()
    joint = next((j for j in design.cluster_joints if j.id == joint_id), None)
    if joint is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")
    cluster = next(
        (c for c in design.cluster_transforms if c.id == joint.cluster_id), None
    )
    ct_dict = (
        None
        if cluster is None
        else {
            "rotation": list(cluster.rotation),
            "translation": list(cluster.translation),
            "pivot": list(cluster.pivot),
        }
    )

    params: dict = {"joint_id": joint_id}
    if body.name is not None:
        params["name"] = body.name
    if body.surface_detail is not None:
        params["surface_detail"] = int(body.surface_detail)
    if body.axis_origin is not None or body.axis_direction is not None:
        cur_world_origin, cur_world_dir = _local_to_world_joint(
            joint.local_axis_origin,
            joint.local_axis_direction,
            cluster,
        )
        new_world_origin = (
            list(body.axis_origin) if body.axis_origin is not None else cur_world_origin
        )
        if body.axis_direction is not None:
            dx, dy, dz = (
                body.axis_direction[0],
                body.axis_direction[1],
                body.axis_direction[2],
            )
            length = _math.sqrt(dx * dx + dy * dy + dz * dz)
            if length < 1e-9:
                raise HTTPException(
                    400, detail="axis_direction must be a non-zero vector."
                )
            new_world_dir = [dx / length, dy / length, dz / length]
        else:
            new_world_dir = cur_world_dir
        local_origin, local_dir = _world_to_local_joint(
            new_world_origin, new_world_dir, ct_dict
        )
        params["local_axis_origin"] = local_origin
        params["local_axis_direction"] = local_dir
    if body.min_angle_deg is not None:
        params["min_angle_deg"] = float(body.min_angle_deg)
    if body.max_angle_deg is not None:
        params["max_angle_deg"] = float(body.max_angle_deg)
    new_min = params.get("min_angle_deg", joint.min_angle_deg)
    new_max = params.get("max_angle_deg", joint.max_angle_deg)
    if new_max < new_min:
        raise HTTPException(
            400,
            detail=f"max_angle_deg ({new_max}) must be >= min_angle_deg ({new_min}).",
        )

    label = f"Update joint {joint.name!r}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="joint-update",
        label=label,
        params=params,
        fn=lambda d: _build_update_joint(d, params),
    )
    return _design_response(updated, report)


@router.delete("/design/joint/{joint_id}", status_code=200)
def delete_joint(joint_id: str) -> dict:
    """Delete a joint. Logged as a 'joint-delete' minor op."""
    design = design_state.get_or_404()
    joint = next((j for j in design.cluster_joints if j.id == joint_id), None)
    if joint is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")

    params = {"joint_id": joint_id}
    label = f"Delete joint {joint.name!r}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="joint-delete",
        label=label,
        params=params,
        fn=lambda d: _build_delete_joint(d, params),
    )
    return _design_response(updated, report)
