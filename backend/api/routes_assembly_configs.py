"""
API layer — assembly configuration + camera-pose route handlers (extracted from assembly.py).

This module hosts two cohesive clusters of *saved assembly view/state presets*:
the four ``/assembly/configurations`` endpoints (named snapshots of every
instance / joint / gear-relation state) and the four ``/assembly/camera-poses``
endpoints (saved camera viewpoints). Both persist preset lists on the
``Assembly`` model and return ``_assembly_response``. They were factored out of
``assembly.py`` following the same template as the crud.py sub-router lifts
(``routes_camera_poses.py``, ``routes_animations.py``) and the assembly-side
``routes_assembly_animations.py``.

Routes
------
  POST   /assembly/configurations                      — capture current state as a named config
  POST   /assembly/configurations/{config_id}/restore  — restore a saved config (silent — no undo push)
  PATCH  /assembly/configurations/{config_id}          — rename / overwrite a config (silent)
  DELETE /assembly/configurations/{config_id}          — remove a config
  POST   /assembly/camera-poses                        — add camera pose
  PATCH  /assembly/camera-poses/{pose_id}              — update camera pose (silent)
  DELETE /assembly/camera-poses/{pose_id}              — remove camera pose
  PUT    /assembly/camera-poses/reorder                — reorder camera poses

URLs are unchanged from their previous home in assembly.py. Mounting is done
in ``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
# _assembly_response is the shared assembly response helper (the assembly-side
# twin of crud.py's _design_response). It stays in assembly.py — used by
# every assembly route there — and is imported back here. Same convention as
# routes_assembly_animations.py.
from backend.api.assembly import _assembly_response
from backend.core.models import (
    Assembly,
    AssemblyConfigurationSnapshot,
    AssemblyGearRelationConfigState,
    AssemblyInstanceConfigState,
    AssemblyJointConfigState,
    CameraPose,
)

router = APIRouter()


# ── Request bodies ────────────────────────────────────────────────────────────

class CreateAssemblyConfigurationBody(BaseModel):
    name: Optional[str] = None


class PatchAssemblyConfigurationBody(BaseModel):
    name: Optional[str] = None
    overwrite_current: Optional[bool] = None


class CreateAssemblyCameraPoseBody(BaseModel):
    name: str = "Camera Pose"
    position: list[float]
    target: list[float]
    up: list[float]
    fov: float = 55.0
    orbit_mode: str = "trackball"


class PatchAssemblyCameraPoseBody(BaseModel):
    name: Optional[str] = None
    position: Optional[list[float]] = None
    target: Optional[list[float]] = None
    up: Optional[list[float]] = None
    fov: Optional[float] = None
    orbit_mode: Optional[str] = None


class ReorderAssemblyCameraPosesBody(BaseModel):
    ordered_ids: list[str]


# ── Assembly configurations ──────────────────────────────────────────────────

def _capture_assembly_configuration(assembly: Assembly, name: str) -> AssemblyConfigurationSnapshot:
    return AssemblyConfigurationSnapshot(
        name=name,
        instance_states=[
            AssemblyInstanceConfigState(
                instance_id=inst.id,
                name=inst.name,
                transform=inst.transform,
                base_transform=inst.base_transform,
                joint_states=dict(inst.joint_states),
                cluster_transform_overrides=list(inst.cluster_transform_overrides),
            )
            for inst in assembly.instances
        ],
        joint_states=[
            AssemblyJointConfigState(
                joint_id=j.id,
                current_value=j.current_value,
                axis_origin=list(j.axis_origin),
                axis_direction=list(j.axis_direction),
                angular_velocity_rpm=j.angular_velocity_rpm,
                spin_paused=j.spin_paused,
            )
            for j in assembly.joints
        ],
        gear_relation_states=[
            AssemblyGearRelationConfigState(
                relation_id=g.id,
                ratio=g.ratio,
                invert=g.invert,
                joint_a_anchor=g.joint_a_anchor,
                joint_b_anchor=g.joint_b_anchor,
                endpoint_a_instance_id=g.endpoint_a_instance_id,
                endpoint_b_instance_id=g.endpoint_b_instance_id,
                endpoint_a_side=g.endpoint_a_side,
                endpoint_b_side=g.endpoint_b_side,
            )
            for g in assembly.gear_relations
        ],
    )


@router.post("/assembly/configurations", status_code=200)
def create_assembly_configuration(body: CreateAssemblyConfigurationBody = None) -> dict:
    """Capture current assembly instance/joint state as a named configuration."""
    assembly = assembly_state.get_or_create()
    idx = len(assembly.configurations) + 1
    cfg = _capture_assembly_configuration(assembly, (body.name if body and body.name else f"Config {idx}"))
    updated = assembly.model_copy(
        update={
            "configurations": [*assembly.configurations, cfg],
            "configuration_cursor": cfg.id,
        },
        deep=True,
    )
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.post("/assembly/configurations/{config_id}/restore", status_code=200)
def restore_assembly_configuration(config_id: str) -> dict:
    """Restore saved positions for instances present in the configuration.

    Instances and joints added after the configuration was captured are left as-is.
    """
    assembly = assembly_state.get_or_404()
    cfg = next((c for c in assembly.configurations if c.id == config_id), None)
    if cfg is None:
        raise HTTPException(404, detail=f"Configuration {config_id!r} not found.")

    state_by_id = {s.instance_id: s for s in cfg.instance_states}
    joint_by_id = {s.joint_id: s for s in cfg.joint_states}

    new_instances = []
    for inst in assembly.instances:
        state = state_by_id.get(inst.id)
        if state is None:
            new_instances.append(inst)
            continue
        new_instances.append(inst.model_copy(update={
            "transform": state.transform,
            "base_transform": state.base_transform,
            "joint_states": dict(state.joint_states),
            "cluster_transform_overrides": list(state.cluster_transform_overrides),
        }, deep=True))

    new_joints = []
    for joint in assembly.joints:
        state = joint_by_id.get(joint.id)
        if state is None:
            new_joints.append(joint)
            continue
        new_joints.append(joint.model_copy(update={
            "current_value": state.current_value,
            "axis_origin": list(state.axis_origin),
            "axis_direction": list(state.axis_direction),
            "angular_velocity_rpm": state.angular_velocity_rpm,
            "spin_paused": state.spin_paused,
        }, deep=True))

    gear_state_by_id = {s.relation_id: s for s in cfg.gear_relation_states}
    new_gears = []
    for rel in assembly.gear_relations:
        gs = gear_state_by_id.get(rel.id)
        if gs is None:
            new_gears.append(rel)
            continue
        new_gears.append(rel.model_copy(update={
            "ratio": gs.ratio,
            "invert": gs.invert,
            "joint_a_anchor": gs.joint_a_anchor,
            "joint_b_anchor": gs.joint_b_anchor,
            "endpoint_a_instance_id": gs.endpoint_a_instance_id,
            "endpoint_b_instance_id": gs.endpoint_b_instance_id,
            "endpoint_a_side": gs.endpoint_a_side,
            "endpoint_b_side": gs.endpoint_b_side,
        }, deep=True))

    updated = assembly.model_copy(update={
        "instances": new_instances,
        "joints": new_joints,
        "gear_relations": new_gears,
        "configuration_cursor": cfg.id,
    }, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.patch("/assembly/configurations/{config_id}", status_code=200)
def update_assembly_configuration(config_id: str, body: PatchAssemblyConfigurationBody) -> dict:
    """Rename a configuration or overwrite it with the current assembly state."""
    assembly = assembly_state.get_or_404()
    configs = list(assembly.configurations)
    idx = next((i for i, c in enumerate(configs) if c.id == config_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Configuration {config_id!r} not found.")

    current = configs[idx]
    if body.overwrite_current:
        replacement = _capture_assembly_configuration(assembly, body.name or current.name)
        replacement = replacement.model_copy(update={"id": current.id})
    else:
        patch = {}
        if body.name is not None:
            patch["name"] = body.name
        replacement = current.model_copy(update=patch)
    configs[idx] = replacement

    updated = assembly.model_copy(update={
        "configurations": configs,
        "configuration_cursor": replacement.id if body.overwrite_current else assembly.configuration_cursor,
    }, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.delete("/assembly/configurations/{config_id}", status_code=200)
def delete_assembly_configuration(config_id: str) -> dict:
    assembly = assembly_state.get_or_404()
    configs = [c for c in assembly.configurations if c.id != config_id]
    if len(configs) == len(assembly.configurations):
        raise HTTPException(404, detail=f"Configuration {config_id!r} not found.")
    cursor = assembly.configuration_cursor
    if cursor == config_id:
        cursor = configs[-1].id if configs else None
    updated = assembly.model_copy(update={
        "configurations": configs,
        "configuration_cursor": cursor,
    }, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


# ── Assembly camera poses ────────────────────────────────────────────────────

@router.post("/assembly/camera-poses", status_code=200)
def create_assembly_camera_pose(body: CreateAssemblyCameraPoseBody) -> dict:
    assembly = assembly_state.get_or_create()
    pose = CameraPose(
        name=body.name,
        position=body.position,
        target=body.target,
        up=body.up,
        fov=body.fov,
        orbit_mode=body.orbit_mode,
    )
    updated = assembly.model_copy(update={"camera_poses": [*assembly.camera_poses, pose]}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.patch("/assembly/camera-poses/{pose_id}", status_code=200)
def update_assembly_camera_pose(pose_id: str, body: PatchAssemblyCameraPoseBody) -> dict:
    assembly = assembly_state.get_or_create()
    poses = list(assembly.camera_poses)
    idx = next((i for i, p in enumerate(poses) if p.id == pose_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")
    poses[idx] = poses[idx].model_copy(update=body.model_dump(exclude_none=True))
    updated = assembly.model_copy(update={"camera_poses": poses}, deep=True)
    assembly_state.set_assembly_silent(updated)
    return _assembly_response(updated)


@router.delete("/assembly/camera-poses/{pose_id}", status_code=200)
def delete_assembly_camera_pose(pose_id: str) -> dict:
    assembly = assembly_state.get_or_create()
    poses = [p for p in assembly.camera_poses if p.id != pose_id]
    if len(poses) == len(assembly.camera_poses):
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")
    updated = assembly.model_copy(update={"camera_poses": poses}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)


@router.put("/assembly/camera-poses/reorder", status_code=200)
def reorder_assembly_camera_poses(body: ReorderAssemblyCameraPosesBody) -> dict:
    assembly = assembly_state.get_or_create()
    pose_map = {p.id: p for p in assembly.camera_poses}
    missing = [pid for pid in body.ordered_ids if pid not in pose_map]
    if missing:
        raise HTTPException(400, detail=f"Unknown pose IDs: {missing}")
    listed = set(body.ordered_ids)
    poses = [pose_map[pid] for pid in body.ordered_ids]
    poses += [p for p in assembly.camera_poses if p.id not in listed]
    updated = assembly.model_copy(update={"camera_poses": poses}, deep=True)
    assembly_state.set_assembly(updated)
    return _assembly_response(updated)
