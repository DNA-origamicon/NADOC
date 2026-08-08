"""
API layer — assembly belt/pulley route handlers (extracted from assembly.py).

A BeltPath defines an open belt wrapping exactly two pulleys; each pulley is a
revolute AssemblyJoint (the rotation axis) plus a rim connector on the rotating
body (its perpendicular distance to the axis = pulley radius). This phase is
DISPLAY-ONLY: the belt is rendered as a glowing line, parts ride it as static
placements, and the polymerize route clones a seed rider around the loop. The
backend stores + validates state; geometry (radius / center / arc positions) is
computed by the frontend and cached here as advisory metadata.

This module hosts the cohesive cluster of belt-path CRUD + belt-rider CRUD +
belt polymerization endpoints, factored out of ``assembly.py`` following the same
template as the other assembly-side sub-routers (``routes_assembly_gears.py``,
``routes_assembly_connectors.py``, ``routes_assembly_configs.py``).

Routes
------
  POST   /assembly/belt-paths              — create a belt path (two pulleys)
  PATCH  /assembly/belt-paths/{belt_id}    — patch name / pulleys (re-anchored)
  DELETE /assembly/belt-paths/{belt_id}    — remove a belt path
  POST   /assembly/belt-riders             — attach a part to a belt (static)
  DELETE /assembly/belt-riders/{rider_id}  — detach a part from a belt
  POST   /assembly/polymerize-belt         — clone a seed rider around the loop

Back-imports (B=4 — all shared kernel/infrastructure, zero bespoke): ``_assembly_response``
(shared kernel, the assembly-side twin of crud.py's ``_design_response``),
``_apply_assembly_mutation_with_feature_log`` (the assembly mutate + feature-log
wrapper), ``_find_instance`` (the 54-caller shared instance lookup), and
``_resolve_gear_endpoint`` (the HTTPException-raising endpoint resolver shared
cross-region with the gear router, so it stays in assembly.py as shared
infrastructure — L13). The two belt-only helpers (``_find_belt_path``,
``_resolve_belt_pulley``) and all six request models moved IN with the router.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import math
import uuid as _uuid
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
    _find_instance,
    _resolve_gear_endpoint,
)
from backend.core.models import Assembly, BeltPath, BeltPulley, BeltRider, Mat4x4

router = APIRouter()


# ── Belt paths ────────────────────────────────────────────────────────────────
#
# A BeltPath defines an open belt wrapping exactly two pulleys. Each pulley is a
# revolute AssemblyJoint (the rotation axis) plus a rim connector on the rotating
# body (its perpendicular distance to the axis = pulley radius). This phase is
# DISPLAY-ONLY: the belt is rendered as a glowing line; no kinematic coupling and
# no part mating yet. The backend stores + validates state; geometry (radius /
# center) is computed by the frontend and cached here as advisory metadata.


class BeltPulleyRequest(BaseModel):
    joint_id: str
    side: Optional[Literal["a", "b"]] = None
    instance_id: Optional[str] = None
    connector_label: Optional[str] = None
    radius: float = 0.0
    center_world: Optional[list[float]] = None
    connector_world: Optional[list[float]] = None


class CreateBeltPathRequest(BaseModel):
    name: str = "Belt"
    pulley_a: BeltPulleyRequest
    pulley_b: BeltPulleyRequest


class PatchBeltPathRequest(BaseModel):
    name: Optional[str] = None
    pulley_a: Optional[BeltPulleyRequest] = None
    pulley_b: Optional[BeltPulleyRequest] = None


# This module uses `from __future__ import annotations`, so the nested
# BeltPulleyRequest field annotations are lazy strings. Resolve them now so
# FastAPI can build the request body validators.
CreateBeltPathRequest.model_rebuild()
PatchBeltPathRequest.model_rebuild()


def _find_belt_path(assembly: Assembly, belt_id: str):
    belt = next((b for b in assembly.belt_paths if b.id == belt_id), None)
    if belt is None:
        raise HTTPException(404, detail=f"BeltPath {belt_id!r} not found.")
    return belt


def _resolve_belt_pulley(
    assembly: Assembly, req: BeltPulleyRequest, label: str
) -> BeltPulley:
    joint = next((j for j in assembly.joints if j.id == req.joint_id), None)
    if joint is None:
        raise HTTPException(404, detail=f"{label}: joint {req.joint_id!r} not found.")
    if joint.joint_type != "revolute":
        raise HTTPException(
            400, detail=f"{label}: belt pulley requires a revolute joint."
        )
    inst_id, side = _resolve_gear_endpoint(joint, req.instance_id, req.side, label)
    if not math.isfinite(req.radius) or req.radius < 0:
        raise HTTPException(400, detail=f"{label}: radius must be finite and >= 0.")
    return BeltPulley(
        joint_id=req.joint_id,
        side=side,
        instance_id=inst_id,
        connector_label=req.connector_label,
        radius=float(req.radius),
        center_world=req.center_world,
        connector_world=req.connector_world,
    )


@router.post("/assembly/belt-paths", status_code=201)
def create_belt_path(body: CreateBeltPathRequest) -> dict:
    assembly = assembly_state.get_or_create()
    if body.pulley_a.joint_id == body.pulley_b.joint_id:
        raise HTTPException(
            400, detail="pulley_a and pulley_b must use different joints."
        )
    pulley_a = _resolve_belt_pulley(assembly, body.pulley_a, "pulley_a")
    pulley_b = _resolve_belt_pulley(assembly, body.pulley_b, "pulley_b")
    joint_by_id = {j.id: j for j in assembly.joints}
    belt = BeltPath(
        name=body.name,
        pulley_a=pulley_a,
        pulley_b=pulley_b,
        joint_a_anchor=joint_by_id[pulley_a.joint_id].current_value,
        joint_b_anchor=joint_by_id[pulley_b.joint_id].current_value,
    )
    new_belts = [*assembly.belt_paths, belt]
    mutated = assembly.model_copy(update={"belt_paths": new_belts})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-create-belt",
        label=f"Add belt path: {belt.name}",
        params={"belt_id": belt.id, "name": belt.name},
    )
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/belt-paths/{belt_id}", status_code=200)
def patch_belt_path(belt_id: str, body: PatchBeltPathRequest) -> dict:
    assembly = assembly_state.get_or_404()
    belt = _find_belt_path(assembly, belt_id)
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    joint_by_id = {j.id: j for j in assembly.joints}
    if body.pulley_a is not None:
        updates["pulley_a"] = _resolve_belt_pulley(assembly, body.pulley_a, "pulley_a")
        # Re-anchor from the current pose so the new geometry couples without a jump.
        updates["joint_a_anchor"] = joint_by_id[
            updates["pulley_a"].joint_id
        ].current_value
    if body.pulley_b is not None:
        updates["pulley_b"] = _resolve_belt_pulley(assembly, body.pulley_b, "pulley_b")
        updates["joint_b_anchor"] = joint_by_id[
            updates["pulley_b"].joint_id
        ].current_value
    new_belt = belt.model_copy(update=updates)
    if new_belt.pulley_a.joint_id == new_belt.pulley_b.joint_id:
        raise HTTPException(
            400, detail="pulley_a and pulley_b must use different joints."
        )
    new_belts = [new_belt if b.id == belt_id else b for b in assembly.belt_paths]
    mutated = assembly.model_copy(update={"belt_paths": new_belts})
    assembly_state.set_assembly_silent(mutated)
    return _assembly_response(mutated)


@router.delete("/assembly/belt-paths/{belt_id}", status_code=200)
def delete_belt_path(belt_id: str) -> dict:
    assembly = assembly_state.get_or_404()
    belt = _find_belt_path(assembly, belt_id)
    new_belts = [b for b in assembly.belt_paths if b.id != belt_id]
    mutated = assembly.model_copy(update={"belt_paths": new_belts})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-belt",
        label=f"Delete belt path: {belt.name}",
        params={"belt_id": belt_id, "name": belt.name},
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Belt riders (parts attached to a belt path) ──────────────────────────────
#
# Phase 1: static placement. The frontend computes the seating transform (the
# part's connector lands on the belt at arc_param, oriented to the belt) and
# sends it; this route applies it to the instance and records the rider so it
# lists under the belt and can later be advanced as the belt's pulley spins.


class CreateBeltRiderRequest(BaseModel):
    belt_path_id: str
    instance_id: str
    connector_label: Optional[str] = None
    arc_param: float = 0.0
    ref_angle: float = 0.0  # driver-pulley angle at attach
    local_transform: Optional[list[float]] = (
        None  # part pose relative to belt frame (row-major 16)
    )
    transform: Optional[dict] = (
        None  # Mat4x4 {"values": [16 floats]}; applied to the part
    )


@router.post("/assembly/belt-riders", status_code=201)
def create_belt_rider(body: CreateBeltRiderRequest) -> dict:
    assembly = assembly_state.get_or_404()
    belt = next((b for b in assembly.belt_paths if b.id == body.belt_path_id), None)
    if belt is None:
        raise HTTPException(404, detail=f"BeltPath {body.belt_path_id!r} not found.")
    inst = _find_instance(assembly, body.instance_id)
    new_instances = assembly.instances
    if body.transform is not None:
        vals = (
            body.transform.get("values") if isinstance(body.transform, dict) else None
        )
        if not vals or len(vals) != 16:
            raise HTTPException(
                400, detail="transform must be {'values': [16 floats]}."
            )
        # Cargo placement: set the part's transform directly (Phase 1 — no FK to
        # rigid children / joint sync; riders are free parts).
        new_inst = inst.model_copy(
            update={
                "transform": Mat4x4(values=[float(v) for v in vals]),
                "base_transform": None,
            }
        )
        new_instances = [new_inst if i.id == inst.id else i for i in assembly.instances]
    rider = BeltRider(
        belt_path_id=body.belt_path_id,
        instance_id=body.instance_id,
        connector_label=body.connector_label,
        arc_param=float(body.arc_param),
        ref_angle=float(body.ref_angle),
        local_transform=body.local_transform,
    )
    mutated = assembly.model_copy(
        update={
            "instances": new_instances,
            "belt_riders": [*assembly.belt_riders, rider],
        }
    )
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-create-belt-rider",
        label=f"Attach {inst.name} to belt: {belt.name}",
        params={"rider_id": rider.id, "belt_id": belt.id, "instance_id": inst.id},
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/belt-riders/{rider_id}", status_code=200)
def delete_belt_rider(rider_id: str) -> dict:
    assembly = assembly_state.get_or_404()
    rider = next((r for r in assembly.belt_riders if r.id == rider_id), None)
    if rider is None:
        raise HTTPException(404, detail=f"BeltRider {rider_id!r} not found.")
    mutated = assembly.model_copy(
        update={
            "belt_riders": [r for r in assembly.belt_riders if r.id != rider_id],
        }
    )
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-belt-rider",
        label="Detach part from belt",
        params={"rider_id": rider_id},
    )
    return _assembly_response(assembly_state.get_or_404())


# ── Polymerize along a belt ──────────────────────────────────────────────────
#
# Repeat an existing belt rider (the seed) around the belt loop: clone the seed
# instance N-1 times and record each as a BeltRider sharing the seed's
# local_transform (so the chain rides together) at the arc positions the frontend
# computed from the belt geometry. Geometry lives frontend-side; this route just
# clones + records, in one undo step.


class PolymerizeBeltCopy(BaseModel):
    arc_param: float
    transform: dict  # Mat4x4 {"values": [16 floats]} — world pose for this copy


class PolymerizeBeltRequest(BaseModel):
    rider_id: str  # SEED belt rider to repeat
    copies: list[PolymerizeBeltCopy]  # N-1 new copies (the seed is copy 0)


PolymerizeBeltRequest.model_rebuild()


@router.post("/assembly/polymerize-belt", status_code=201)
def polymerize_belt(body: PolymerizeBeltRequest) -> dict:
    assembly = assembly_state.get_or_404()
    seed = next((r for r in assembly.belt_riders if r.id == body.rider_id), None)
    if seed is None:
        raise HTTPException(404, detail=f"BeltRider {body.rider_id!r} not found.")
    if not body.copies:
        raise HTTPException(400, detail="copies must be non-empty.")
    seed_inst = _find_instance(assembly, seed.instance_id)

    new_instances = list(assembly.instances)
    new_riders = list(assembly.belt_riders)
    new_instance_ids: list[str] = []
    new_rider_ids: list[str] = []
    for k, copy in enumerate(body.copies, start=1):
        vals = (
            copy.transform.get("values") if isinstance(copy.transform, dict) else None
        )
        if not vals or len(vals) != 16:
            raise HTTPException(
                400, detail="each copy transform must be {'values': [16 floats]}."
            )
        new_id = str(_uuid.uuid4())
        clone = seed_inst.model_copy(
            deep=True,
            update={
                "id": new_id,
                "name": f"{seed_inst.name} +{k}",
                "transform": Mat4x4(values=[float(v) for v in vals]),
                "base_transform": None,
            },
        )
        new_instances.append(clone)
        rider = BeltRider(
            belt_path_id=seed.belt_path_id,
            instance_id=new_id,
            connector_label=seed.connector_label,
            arc_param=float(copy.arc_param),
            ref_angle=seed.ref_angle,
            local_transform=seed.local_transform,
        )
        new_riders.append(rider)
        new_instance_ids.append(new_id)
        new_rider_ids.append(rider.id)

    mutated = assembly.model_copy(
        update={"instances": new_instances, "belt_riders": new_riders}
    )
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-polymerize-belt",
        label=f"Polymerize {seed_inst.name} around belt: {len(body.copies) + 1} copies",
        params={
            "rider_id": seed.id,
            "belt_id": seed.belt_path_id,
            "new_instance_ids": new_instance_ids,
            "new_rider_ids": new_rider_ids,
        },
    )
    return _assembly_response(assembly_state.get_or_404())
