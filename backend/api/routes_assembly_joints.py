"""
API layer — assembly joint CRUD route handlers (extracted from assembly.py).

An ``AssemblyJoint`` is a kinematic relationship (rigid / revolute / prismatic /
spherical) between two PartInstances. This module hosts the cohesive cluster of
joint *mutator* endpoints — add / create-mate (atomic) / patch / refresh-mate /
delete — factored out of ``assembly.py`` following the same template as the
other assembly-side sub-routers (``routes_assembly_groups.py``,
``routes_assembly_belts.py``, ``routes_assembly_gears.py``,
``routes_assembly_frames.py``).

The read-only frame-inspection half of the old ``# ── Joint routes`` banner
(``GET .../connector-frames`` / ``.../debug-frames``) already moved to
``routes_assembly_frames.py`` (Refactor #19); this is the write half.

The kinematic math is all in ``backend/core``: FK graph propagation
(``assembly_fk``), connector-world/frame resolution + coincidence enforcement
(``assembly_connectors``), and revolute/gear drive (``assembly_kinematics``).
This router imports those directly from core, NOT back from the god-file.

Back-imports from ``assembly.py`` (B=11, **bespoke-B=0** — every one is shared
kernel / infrastructure, not a region helper): the shared response kernel
``_assembly_response`` + mutate-and-feature-log wrapper
``_apply_assembly_mutation_with_feature_log``; the trivial shared lookups
``_find_instance`` / ``_find_joint``; the SE3 converters ``_mat4_from_model`` /
``_mat4_to_model`` (26+ unrelated callers) and ``_apply_prismatic_joint``; the
file-IO design-load infrastructure ``_assembly_source_path`` /
``_design_with_instance_overrides`` / ``_propagate_fk_inplace``; and the
L4-blocked cross-region cluster-inference helper
``_infer_cluster_ids_for_connector_label`` (raises through the api-layer
design load). The region-local ``_compose_add_joint`` and all four request
models moved IN with the router.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import math
import os
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _apply_prismatic_joint,
    _assembly_response,
    _assembly_source_path,
    _design_with_instance_overrides,
    _find_instance,
    _find_joint,
    _infer_cluster_ids_for_connector_label,
    _mat4_from_model,
    _mat4_to_model,
    _propagate_fk_inplace,
)
from backend.core.assembly_connectors import (
    _enforce_connector_coincidence,
    _get_connector_world,
    _get_connector_world_frame,
)
from backend.core.assembly_fk import (
    _build_inst_by_id,
    _fk_expand_rigid_group,
    _fk_propagate,
)
from backend.core.assembly_kinematics import (
    _apply_revolute_joint,
    _apply_revolute_value_to_gear_endpoint,
    _propagate_gear_relations_from,
)
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    ConnectionType,
    InterfacePoint,
    Vec3,
)

router = APIRouter()


# ── Request bodies ────────────────────────────────────────────────────────────

class AddJointRequest(BaseModel):
    name: str = "Joint"
    joint_type: str = "revolute"
    instance_a_id: Optional[str] = None
    cluster_id_a: Optional[str] = None
    instance_b_id: str
    cluster_id_b: Optional[str] = None
    axis_origin: list[float] = [0.0, 0.0, 0.0]
    axis_direction: list[float] = [0.0, 0.0, 1.0]
    current_value: float = 0.0
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    connector_a_label: Optional[str] = None
    connector_b_label: Optional[str] = None


class MateConnectorSpec(BaseModel):
    """One side of a mate. ``position``/``normal`` are instance-LOCAL and used
    only to auto-register the connector as an InterfacePoint when one of the
    ``is_*`` flags is true (no-op if the label already exists).

    ``is_blunt_end``  — free helix endpoint (label ``end:<helix>:<bp>``).
    ``is_bend_center`` — derived center-of-curvature of a bend op (label
    ``bend_<i>_center``). Auto-registered the same way as blunt ends.
    """
    instance_id: str
    label: str
    position: list[float] = [0.0, 0.0, 0.0]
    normal: list[float] = [0.0, 0.0, 1.0]
    cluster_id: Optional[str] = None
    is_blunt_end: bool = False
    is_bend_center: bool = False


class CreateMateRequest(BaseModel):
    """Atomic mate creation: register blunt-end connectors + propagate FK to the
    aligned pose + add the joint, in ONE request.  Collapses the old
    4-round-trip frontend sequence (addConnector ×2 → propagate_fk → add_joint)
    into a single store update / undo step / feature-log entry."""
    child_connector: MateConnectorSpec
    parent_connector: Optional[MateConnectorSpec] = None   # None => World mate
    moved_instance_id: Optional[str] = None                # which instance FK moves (None => no move)
    transform: Optional[dict] = None                       # {"values": [16]} row-major, for moved instance
    name: str = "Joint"
    joint_type: str = "rigid"
    axis_origin: list[float] = [0.0, 0.0, 0.0]
    axis_direction: list[float] = [0.0, 0.0, 1.0]
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None


class PatchJointRequest(BaseModel):
    name: Optional[str] = None
    joint_type: Optional[str] = None  # changing type resets current_value to 0
    current_value: Optional[float] = None
    axis_origin: Optional[list[float]] = None
    axis_direction: Optional[list[float]] = None
    min_limit: Optional[float] = None
    max_limit: Optional[float] = None
    clear_limits: Optional[bool] = None
    angular_velocity_rpm: Optional[float] = None   # revolute only; 0 = static
    spin_paused: Optional[bool] = None             # per-joint freeze
    silent: Optional[bool] = None  # True during animation playback (suppress undo push)
    # Which body moves when driving current_value on a revolute joint: 'b' (child,
    # the default/legacy) or 'a' (parent). Set by the gizmo when the moving body
    # is the joint's parent (e.g. a pulley whose fixed axle is authored as the
    # child) so we rotate the pulley, not the fixed axle.
    endpoint_side: Optional[Literal["a", "b"]] = None


# ── Joint routes ──────────────────────────────────────────────────────────────

def _compose_add_joint(
    assembly: Assembly, body: AddJointRequest,
) -> tuple[Assembly, AssemblyJoint, str, dict]:
    """Build the assembly state for a new joint: derive axis_origin, snap
    instance_b to connector_a, snapshot base_transform, capture
    mate_relative_transform, and propagate the snap to non-rigid children.

    Returns ``(new_assembly, joint, feature_log_label, feature_log_params)``.
    Pure w.r.t. ``assembly_state`` — the caller persists via
    ``_apply_assembly_mutation_with_feature_log``.  Shared by ``add_joint``
    and the atomic ``create_mate`` endpoint.
    """
    _find_instance(assembly, body.instance_b_id)
    if body.instance_a_id is not None:
        _find_instance(assembly, body.instance_a_id)

    # Derive axis_origin from connector positions (safety net — frontend pre-aligns,
    # but the backend recomputes to guarantee connector coincidence at creation time).
    axis_origin = list(body.axis_origin)
    snap_delta: 'np.ndarray | None' = None

    inst_b = _find_instance(assembly, body.instance_b_id)
    cluster_id_a = body.cluster_id_a
    cluster_id_b = body.cluster_id_b
    # Snap + axis_origin go through _get_connector_world so the snap math
    # uses LIVE cluster-aware connector positions (for blunt-end labels,
    # pulled fresh from helix geometry; for manual connectors,
    # T_inst @ ip.position). Keeps add_joint, resolve, and the highlight
    # markers all on the same definition of "where the connector is."
    asm_path = _assembly_source_path(assembly)
    if body.connector_b_label:
        ip_b = next((p for p in inst_b.interface_points if p.label == body.connector_b_label), None)
        if ip_b is not None:
            if cluster_id_b is None:
                cluster_id_b = (_infer_cluster_ids_for_connector_label(inst_b, body.connector_b_label) or [ip_b.cluster_id])[0]
            design_b = _design_with_instance_overrides(inst_b, asm_path)
            cb_world = _get_connector_world(inst_b, body.connector_b_label, design_b)
            if cb_world is None:
                cb_world = np.zeros(3, dtype=float)
            if body.connector_a_label and body.instance_a_id:
                inst_a = _find_instance(assembly, body.instance_a_id)
                ip_a   = next((p for p in inst_a.interface_points
                               if p.label == body.connector_a_label), None)
                if ip_a is not None:
                    if cluster_id_a is None:
                        cluster_id_a = (_infer_cluster_ids_for_connector_label(inst_a, body.connector_a_label) or [ip_a.cluster_id])[0]
                    design_a = _design_with_instance_overrides(inst_a, asm_path)
                    ca_world = _get_connector_world(inst_a, body.connector_a_label, design_a)
                    if ca_world is None:
                        ca_world = np.zeros(3, dtype=float)
                    snap = ca_world - cb_world
                    if np.linalg.norm(snap) > 1e-6:
                        snap_delta = np.eye(4, dtype=float)
                        snap_delta[:3, 3] = snap
                    axis_origin = ca_world.tolist()
                else:
                    axis_origin = cb_world.tolist()
            else:
                axis_origin = cb_world.tolist()

    joint = AssemblyJoint(
        name=body.name,
        joint_type=body.joint_type,
        instance_a_id=body.instance_a_id,
        cluster_id_a=cluster_id_a,
        instance_b_id=body.instance_b_id,
        cluster_id_b=cluster_id_b,
        axis_origin=axis_origin,
        axis_direction=body.axis_direction,
        current_value=body.current_value,
        min_limit=body.min_limit,
        max_limit=body.max_limit,
        connector_a_label=body.connector_a_label,
        connector_b_label=body.connector_b_label,
    )

    # Apply any residual snap and snapshot base_transform (value=0 reference pose)
    T_b         = _mat4_from_model(inst_b.transform)
    snapped_T_b = snap_delta @ T_b if snap_delta is not None else T_b
    new_inst_b  = inst_b.model_copy(update={
        "transform":      _mat4_to_model(snapped_T_b),
        "base_transform": _mat4_to_model(snapped_T_b),
    })
    new_instances = [new_inst_b if i.id == inst_b.id else i for i in assembly.instances]
    new_joints    = list(assembly.joints) + [joint]
    new_assembly = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # Capture mate_relative_transform = F_a_world^-1 @ F_b_world right after the
    # creation-time snap so future resolve_assembly invocations can restore not
    # just the position coincidence but the full relative orientation between
    # the two connector frames (important when a later part edit rotates a
    # connector within its part — e.g. via a Relax Bond cluster transform).
    if joint.joint_type in ("rigid", "spherical") and body.connector_a_label and body.instance_a_id and body.connector_b_label:
        post_inst_a = _find_instance(new_assembly, body.instance_a_id)
        post_inst_b = _find_instance(new_assembly, body.instance_b_id)
        design_a = _design_with_instance_overrides(post_inst_a, _assembly_source_path(new_assembly))
        design_b = _design_with_instance_overrides(post_inst_b, _assembly_source_path(new_assembly))
        F_a = _get_connector_world_frame(post_inst_a, body.connector_a_label, design_a)
        F_b = _get_connector_world_frame(post_inst_b, body.connector_b_label, design_b)
        if F_a is not None and F_b is not None:
            try:
                M = np.linalg.inv(F_a) @ F_b
                new_joints = [
                    j.model_copy(update={"mate_relative_transform": M.flatten().tolist()})
                    if j.id == joint.id else j
                    for j in new_assembly.joints
                ]
                new_assembly = new_assembly.model_copy(update={"joints": new_joints})
                joint = next(j for j in new_assembly.joints if j.id == joint.id)
            except np.linalg.LinAlgError:
                pass

    # Propagate snap to inst_b's NON-rigid kinematic children only. Do NOT
    # call _fk_expand_rigid_group here: that helper walks rigid joints
    # bidirectionally, so for the brand-new rigid joint we just added it
    # would find instance_a as a rigid neighbour of instance_b and translate
    # instance_a by the same snap_delta — dragging the parent away from
    # where its connector was. instance_a is the snap target and must not
    # move. (Same reasoning as the rigid branch in resolve_assembly.)
    if snap_delta is not None:
        try:
            _fk_propagate(new_assembly, {body.instance_b_id}, snap_delta, {body.instance_b_id},
                          _build_inst_by_id(new_assembly))
        except np.linalg.LinAlgError:
            pass

    inst_a_name = (_find_instance(new_assembly, body.instance_a_id).name
                    if body.instance_a_id else "world")
    inst_b_name = _find_instance(new_assembly, body.instance_b_id).name
    label_str = f"Add mate: {inst_a_name} ↔ {inst_b_name}"

    params = {
        "joint_id":          joint.id,
        "name":              joint.name,
        "joint_type":        joint.joint_type,
        "instance_a_id":     joint.instance_a_id,
        "instance_b_id":     joint.instance_b_id,
        "cluster_id_a":      joint.cluster_id_a,
        "cluster_id_b":      joint.cluster_id_b,
        "axis_origin":       list(joint.axis_origin),
        "axis_direction":    list(joint.axis_direction),
        "min_limit":         joint.min_limit,
        "max_limit":         joint.max_limit,
        "connector_a_label": joint.connector_a_label,
        "connector_b_label": joint.connector_b_label,
        "mate_relative_transform": list(joint.mate_relative_transform) if joint.mate_relative_transform else None,
    }
    return new_assembly, joint, label_str, params


@router.post("/assembly/joints", status_code=201)
def add_joint(body: AddJointRequest) -> dict:
    """Add an AssemblyJoint, snap instance_b to connector_a, and snapshot base_transform."""
    assembly = assembly_state.get_or_404()
    new_assembly, _joint, label_str, params = _compose_add_joint(assembly, body)
    _apply_assembly_mutation_with_feature_log(
        new_assembly,
        op_kind="assembly-add-joint",
        label=label_str,
        params=params,
    )
    return _assembly_response(assembly_state.get_or_404())


@router.post("/assembly/joints/create-mate", status_code=201)
def create_mate(body: CreateMateRequest) -> dict:
    """Create a mate in ONE request: register blunt-end connectors, propagate FK
    to the aligned pose, and add the joint.

    Replaces the old frontend sequence of four awaited round-trips
    (addConnector × 2 → propagate_fk → add_joint), each of which replaced the
    active assembly and fired the renderer's store subscriber.  Two of those
    carried an unchanged transform and snapped any live mate preview back to
    the stored pose, producing the visible "moves three times" jank.  Doing it
    all server-side yields a single store update, a single undo step, and a
    single feature-log entry.
    """
    live = assembly_state.get_or_404()
    # Work on a deep copy so every sub-step mutates freely; the live state is
    # untouched until the single feature-log apply at the end.
    assembly = live.model_copy(deep=True)
    inst_by_id = _build_inst_by_id(assembly)

    # 1. Register blunt-end connectors as InterfacePoints (idempotent — skip if
    #    the label already exists, e.g. a previously-defined interface point).
    def _register(conn: 'MateConnectorSpec | None') -> None:
        if conn is None or not (conn.is_blunt_end or conn.is_bend_center):
            return
        inst = inst_by_id.get(conn.instance_id)
        if inst is None or any(ip.label == conn.label for ip in inst.interface_points):
            return
        inst.interface_points.append(InterfacePoint(
            label=conn.label,
            position=Vec3(x=conn.position[0], y=conn.position[1], z=conn.position[2]),
            normal=Vec3(x=conn.normal[0], y=conn.normal[1], z=conn.normal[2]),
            connection_type=ConnectionType.COVALENT,
            cluster_id=conn.cluster_id,
        ))
    _register(body.child_connector)
    _register(body.parent_connector)

    # 2. Propagate FK to the aligned pose.  Skipped for World mates / both-fixed
    #    parts, where the frontend sends no transform.
    if body.moved_instance_id and body.transform and "values" in body.transform:
        _propagate_fk_inplace(assembly, body.moved_instance_id, body.transform["values"], inst_by_id)

    # 3. Compose the joint on the connector-registered, FK-moved assembly.
    joint_body = AddJointRequest(
        name=body.name,
        joint_type=body.joint_type,
        instance_a_id=(body.parent_connector.instance_id if body.parent_connector else None),
        cluster_id_a=(body.parent_connector.cluster_id if body.parent_connector else None),
        instance_b_id=body.child_connector.instance_id,
        cluster_id_b=body.child_connector.cluster_id,
        axis_origin=body.axis_origin,
        axis_direction=body.axis_direction,
        min_limit=body.min_limit,
        max_limit=body.max_limit,
        connector_a_label=(body.parent_connector.label if body.parent_connector else None),
        connector_b_label=body.child_connector.label,
    )
    new_assembly, joint, _label, _params = _compose_add_joint(assembly, joint_body)

    # 4. Apply once: single undo step + single feature-log entry.
    inst_a_name = (_find_instance(new_assembly, joint.instance_a_id).name
                   if joint.instance_a_id else "world")
    inst_b_name = _find_instance(new_assembly, joint.instance_b_id).name
    _apply_assembly_mutation_with_feature_log(
        new_assembly,
        op_kind="assembly-create-mate",
        label=f"Create mate: {inst_a_name} ↔ {inst_b_name}",
        params={
            "joint_id":          joint.id,
            "joint_type":        joint.joint_type,
            "instance_a_id":     joint.instance_a_id,
            "instance_b_id":     joint.instance_b_id,
            "moved_instance_id": body.moved_instance_id,
            "connector_a_label": joint.connector_a_label,
            "connector_b_label": joint.connector_b_label,
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/joints/{joint_id}", status_code=200)
def patch_joint(joint_id: str, body: PatchJointRequest) -> dict:
    """
    Update joint fields.  When current_value changes on a revolute joint,
    recomputes instance_b.transform from base_transform to avoid accumulation.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)
    if os.environ.get('NADOC_GEAR_DEBUG', '1') != '0':
        print(f"[patch_joint] joint={joint_id[:8]} type={joint.joint_type} "
              f"body.current_value={body.current_value} "
              f"joint.current_value={joint.current_value}", flush=True)

    joint_updates: dict = {}
    if body.name is not None:
        joint_updates["name"] = body.name
    if body.joint_type is not None and body.joint_type != joint.joint_type:
        joint_updates["joint_type"] = body.joint_type
        joint_updates["current_value"] = 0.0   # reset value when type changes
        joint_updates["min_limit"] = None
        joint_updates["max_limit"] = None
    if body.axis_origin is not None:
        joint_updates["axis_origin"] = body.axis_origin
    if body.axis_direction is not None:
        joint_updates["axis_direction"] = body.axis_direction
    if body.clear_limits:
        joint_updates["min_limit"] = None
        joint_updates["max_limit"] = None
    fields_set = getattr(body, "model_fields_set", set())
    if "min_limit" in fields_set:
        joint_updates["min_limit"] = body.min_limit
    if "max_limit" in fields_set:
        joint_updates["max_limit"] = body.max_limit
    if body.angular_velocity_rpm is not None:
        joint_updates["angular_velocity_rpm"] = float(body.angular_velocity_rpm)
    if body.spin_paused is not None:
        joint_updates["spin_paused"] = bool(body.spin_paused)

    value_changed = body.current_value is not None and body.current_value != joint.current_value
    if body.current_value is not None:
        # Clamp to limits if set
        val = body.current_value
        active_min = joint_updates.get("min_limit", joint.min_limit)
        active_max = joint_updates.get("max_limit", joint.max_limit)
        lo  = active_min if active_min is not None else -math.inf
        hi  = active_max if active_max is not None else  math.inf
        joint_updates["current_value"] = max(lo, min(hi, val))

    # ── Endpoint-aware revolute drive ────────────────────────────────────────
    # Apply the value via the gear-endpoint helper, which rotates the correct
    # seed even when the joint is authored "backward" (moving pulley = parent,
    # fixed axle = child). The legacy path below always moves instance_b, which
    # would rotate the *fixed axle*. The gizmo passes endpoint_side explicitly;
    # for any other caller (e.g. the joint-edit form re-sending current_value
    # after a limits toggle) we INFER it: never rotate a fixed child — if
    # instance_b is anchored but the parent isn't, the moving body is the parent.
    endpoint_side = body.endpoint_side
    if endpoint_side is None and value_changed and joint.joint_type == "revolute":
        inst_a = next((i for i in assembly.instances if i.id == joint.instance_a_id), None)
        inst_b = next((i for i in assembly.instances if i.id == joint.instance_b_id), None)
        if inst_b is not None and inst_b.fixed and not (inst_a is not None and inst_a.fixed):
            endpoint_side = "a"

    if (value_changed and joint.joint_type == "revolute"
            and endpoint_side in ("a", "b")):
        target_value = joint_updates.pop("current_value")  # helper sets it from the OLD value
        new_joint = joint.model_copy(update=joint_updates)
        new_joints = [new_joint if j.id == joint_id else j for j in assembly.joints]
        silent = bool(body.silent)
        if not silent:
            assembly_state.snapshot()
        new_assembly = assembly.model_copy(update={"joints": new_joints})
        inst_by_id = _build_inst_by_id(new_assembly)
        target_joint = next(j for j in new_assembly.joints if j.id == joint_id)
        _apply_revolute_value_to_gear_endpoint(
            new_assembly, target_joint, endpoint_side, float(target_value), inst_by_id,
        )
        _propagate_gear_relations_from(new_assembly, joint_id)
        assembly_state.set_assembly_silent(new_assembly)
        return _assembly_response(assembly_state.get_or_404())

    new_joint = joint.model_copy(update=joint_updates)
    new_joints = [new_joint if j.id == joint_id else j for j in assembly.joints]

    # Recompute instance_b transform when driving a revolute or prismatic joint
    new_instances = list(assembly.instances)
    new_mat: np.ndarray | None = None
    old_inst_b_T: np.ndarray | None = None
    if value_changed and new_joint.joint_type in ("revolute", "prismatic"):
        inst_b = _find_instance(assembly, joint.instance_b_id)
        old_inst_b_T = _mat4_from_model(inst_b.transform)
        base_mat = _mat4_from_model(inst_b.base_transform or inst_b.transform)
        if new_joint.joint_type == "revolute":
            new_mat = _apply_revolute_joint(
                base_mat,
                new_joint.axis_origin,
                new_joint.axis_direction,
                new_joint.current_value,
            )
        else:
            new_mat = _apply_prismatic_joint(
                base_mat,
                new_joint.axis_direction,
                new_joint.current_value,
            )
        new_inst_b    = inst_b.model_copy(update={"transform": _mat4_to_model(new_mat)})
        new_instances = [new_inst_b if i.id == inst_b.id else i for i in assembly.instances]

    silent = body.silent  # True during animation playback
    if not silent:
        assembly_state.snapshot()

    new_assembly = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # FK propagation: propagate delta from instance_b's motion to its kinematic descendants
    if new_mat is not None and old_inst_b_T is not None:
        try:
            delta = new_mat @ np.linalg.inv(old_inst_b_T)
            visited = {new_joint.instance_b_id}
            inst_by_id = _build_inst_by_id(new_assembly)
            _fk_expand_rigid_group(new_assembly, new_joint.instance_b_id, delta, visited, [], inst_by_id)
            _fk_propagate(new_assembly, visited.copy(), delta, visited, inst_by_id)
            _enforce_connector_coincidence(new_assembly, visited, inst_by_id)
        except np.linalg.LinAlgError:
            pass  # singular old transform — skip FK propagation

    # Gear-relation propagation: if this joint is a driver of any GearRelation,
    # update each driven joint's current_value + instance_b transform + FK so
    # the gear-coupled part follows whether the user got here via ring drag,
    # the joint edit form, or any other source.
    if value_changed and new_joint.joint_type == 'revolute':
        _propagate_gear_relations_from(new_assembly, joint_id)

    assembly_state.set_assembly_silent(new_assembly)
    return _assembly_response(assembly_state.get_or_404())


@router.post("/assembly/joints/{joint_id}/refresh-mate", status_code=200)
def refresh_mate(joint_id: str) -> dict:
    """Capture the mate's current relative *rotation* and snap connectors together.

    For a rigid mate the captured invariant is: "the two connector frames are
    coincident in position with this relative rotation". So we:
      1. Compute the live world frames F_a, F_b (cluster-aware).
      2. Capture mate_relative_transform with the rotation part of
         ``F_a^-1 @ F_b`` and a ZERO translation column. Capturing the raw
         translation would lock in any current position discrepancy as the
         "intended" state — exactly what a user clicking this button on a
         misaligned mate wants to avoid.
      3. Apply the SE3 snap to instance_b so connector_b coincides with
         connector_a using the captured rotation, propagating the same snap
         to inst_b's non-rigid kinematic children. This makes the button a
         single-click fix instead of requiring a follow-up Resolve.

    Useful for legacy joints (no mate_relative_transform set) and for re-
    capturing intent after a part edit has rotated a connector inside its
    part — typical example is the Hinge dimers case where a linker-length
    change tilts the hinge's mating face.

    Only rigid / spherical joints are eligible.
    """
    assembly = assembly_state.get_or_404()
    joint = _find_joint(assembly, joint_id)
    if joint.joint_type not in ("rigid", "spherical"):
        raise HTTPException(400, detail="Only rigid / spherical mates store a relative transform.")
    if not (joint.connector_a_label and joint.instance_a_id and joint.connector_b_label):
        raise HTTPException(400, detail="Joint must reference both connectors to refresh.")
    inst_a = _find_instance(assembly, joint.instance_a_id)
    inst_b = _find_instance(assembly, joint.instance_b_id)
    design_a = _design_with_instance_overrides(inst_a, _assembly_source_path(assembly))
    design_b = _design_with_instance_overrides(inst_b, _assembly_source_path(assembly))
    F_a = _get_connector_world_frame(inst_a, joint.connector_a_label, design_a)
    F_b = _get_connector_world_frame(inst_b, joint.connector_b_label, design_b)
    if F_a is None or F_b is None:
        raise HTTPException(400, detail="Failed to compute connector frames for this mate.")
    try:
        M_full = np.linalg.inv(F_a) @ F_b
    except np.linalg.LinAlgError:
        raise HTTPException(400, detail="Singular connector frame; cannot capture mate transform.")

    # Rotation-only capture: discard any current position discrepancy.
    M = np.eye(4, dtype=float)
    M[:3, :3] = M_full[:3, :3]

    # Compute the SE3 snap that brings F_b to F_a @ M (positions coincide
    # using the captured rotation) and apply it to inst_b + non-rigid
    # children. Mirrors the rigid branch of resolve_assembly.
    F_b_target = F_a @ M
    try:
        snap_T = F_b_target @ np.linalg.inv(F_b)
    except np.linalg.LinAlgError:
        raise HTTPException(400, detail="Singular connector frame; cannot capture mate transform.")

    new_origin = F_a[:3, 3].tolist()
    # Apply the snap to inst_b's transform + base_transform.
    old_T = _mat4_from_model(inst_b.transform)
    new_T = snap_T @ old_T
    new_inst_b_updates = {"transform": _mat4_to_model(new_T)}
    if inst_b.base_transform:
        new_inst_b_updates["base_transform"] = _mat4_to_model(
            snap_T @ _mat4_from_model(inst_b.base_transform))

    new_instances = [
        i.model_copy(update=new_inst_b_updates) if i.id == inst_b.id else i
        for i in assembly.instances
    ]
    new_joints = [
        j.model_copy(update={
            "mate_relative_transform": M.flatten().tolist(),
            "axis_origin": new_origin,
        }) if j.id == joint_id else j
        for j in assembly.joints
    ]
    mutated = assembly.model_copy(update={"instances": new_instances, "joints": new_joints})

    # Propagate the snap to inst_b's non-rigid kinematic children so
    # revolute / prismatic descendants follow the mate fix.
    try:
        _fk_propagate(mutated, {inst_b.id}, snap_T, {inst_b.id},
                      _build_inst_by_id(mutated))
    except np.linalg.LinAlgError:
        pass

    assembly_state.set_assembly(mutated)
    return _assembly_response(mutated)


@router.delete("/assembly/joints/{joint_id}", status_code=200)
def delete_joint(joint_id: str) -> dict:
    """Remove an AssemblyJoint."""
    assembly = assembly_state.get_or_404()
    target   = _find_joint(assembly, joint_id)
    new_joints = [j for j in assembly.joints if j.id != joint_id]
    # Cascade-drop any gear relations that referenced this joint.
    new_gears  = [g for g in assembly.gear_relations
                  if g.joint_a_id != joint_id and g.joint_b_id != joint_id]
    mutated = assembly.model_copy(update={"joints": new_joints, "gear_relations": new_gears})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-joint",
        label=f"Delete mate: {target.name}",
        params={"joint_id": joint_id, "name": target.name},
    )
    return _assembly_response(assembly_state.get_or_404())
