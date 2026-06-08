"""
API layer — assembly gear-relation route handlers (extracted from assembly.py).

A GearRelation couples two existing revolute AssemblyJoints with a constant
ratio: ``θ_b = anchor_b + sign * (θ_a - anchor_a) * ratio`` (sign = -1 if invert).
It is rendered as a row in the Mates list (no separate panel section) and is
applied each frame by the frontend kinematics ticker — the backend stores +
validates state but does not propagate gear coupling itself.

This module hosts the cohesive cluster of gear-relation CRUD + resolve endpoints,
factored out of ``assembly.py`` following the same template as the other
assembly-side sub-routers (``routes_assembly_connectors.py``,
``routes_assembly_configs.py``, ``routes_assembly_linkers.py``).

Routes
------
  POST   /assembly/gear-relations               — create a gear relation
  PATCH  /assembly/gear-relations/{rel_id}       — patch name/ratio/invert/anchors
  DELETE /assembly/gear-relations/{rel_id}       — remove a gear relation
  POST   /assembly/gear-relations/{rel_id}/resolve — drive joint_b to satisfy now

Back-imports (B=3): ``_assembly_response`` (shared kernel, the assembly-side twin
of crud.py's ``_design_response``), ``_apply_assembly_mutation_with_feature_log``
(the assembly mutate + feature-log wrapper), and ``_resolve_gear_endpoint`` (an
HTTPException-raising endpoint resolver that is shared cross-region with the Belt
paths handlers, so it stays in assembly.py as shared infrastructure — L13). The
drive math (``_build_inst_by_id``, ``_gear_endpoint_side``,
``_apply_revolute_value_to_gear_endpoint``) lives in ``backend/core`` and is
imported from there directly, not back from the god-file.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

import math
from typing import Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
    _resolve_gear_endpoint,
)
from backend.core.assembly_fk import _build_inst_by_id
from backend.core.assembly_kinematics import (
    _apply_revolute_value_to_gear_endpoint,
    _gear_endpoint_side,
)
from backend.core.models import Assembly, GearRelation

router = APIRouter()


# ── Gear relations ────────────────────────────────────────────────────────────

class CreateGearRelationRequest(BaseModel):
    name: str = "Gear"
    joint_a_id: str
    joint_b_id: str
    endpoint_a_instance_id: Optional[str] = None
    endpoint_b_instance_id: Optional[str] = None
    endpoint_a_side: Optional[Literal["a", "b"]] = None
    endpoint_b_side: Optional[Literal["a", "b"]] = None
    ratio: float = 1.0
    invert: bool = False
    capture_anchors_from_current: bool = True


class PatchGearRelationRequest(BaseModel):
    name: Optional[str] = None
    ratio: Optional[float] = None
    invert: Optional[bool] = None
    joint_a_anchor: Optional[float] = None
    joint_b_anchor: Optional[float] = None


def _find_gear_relation(assembly: Assembly, rel_id: str):
    rel = next((g for g in assembly.gear_relations if g.id == rel_id), None)
    if rel is None:
        raise HTTPException(404, detail=f"GearRelation {rel_id!r} not found.")
    return rel


@router.post("/assembly/gear-relations", status_code=201)
def create_gear_relation(body: CreateGearRelationRequest) -> dict:
    assembly = assembly_state.get_or_create()
    joint_a = next((j for j in assembly.joints if j.id == body.joint_a_id), None)
    joint_b = next((j for j in assembly.joints if j.id == body.joint_b_id), None)
    if joint_a is None or joint_b is None:
        raise HTTPException(404, detail="One or both referenced joints do not exist.")
    if joint_a.joint_type != "revolute" or joint_b.joint_type != "revolute":
        raise HTTPException(400, detail="Gear relation requires two revolute joints.")
    if body.joint_a_id == body.joint_b_id:
        raise HTTPException(400, detail="joint_a_id and joint_b_id must differ.")
    if not math.isfinite(body.ratio) or abs(body.ratio) < 1e-9:
        raise HTTPException(400, detail=f"ratio must be finite and nonzero, got {body.ratio}.")
    endpoint_a_id, endpoint_a_side = _resolve_gear_endpoint(
        joint_a, body.endpoint_a_instance_id, body.endpoint_a_side, "endpoint_a",
    )
    endpoint_b_id, endpoint_b_side = _resolve_gear_endpoint(
        joint_b, body.endpoint_b_instance_id, body.endpoint_b_side, "endpoint_b",
    )
    inst_by_id = _build_inst_by_id(assembly)
    explicit_a = body.endpoint_a_instance_id is not None or body.endpoint_a_side is not None
    explicit_b = body.endpoint_b_instance_id is not None or body.endpoint_b_side is not None
    for label, iid, explicit in (("endpoint_a", endpoint_a_id, explicit_a), ("endpoint_b", endpoint_b_id, explicit_b)):
        inst = inst_by_id.get(iid) if iid else None
        if inst is None:
            raise HTTPException(400, detail=f"{label} must reference an assembly part.")
        if explicit and inst.fixed:
            raise HTTPException(400, detail=f"{label} cannot reference a fixed part.")

    anchor_a = joint_a.current_value if body.capture_anchors_from_current else 0.0
    anchor_b = joint_b.current_value if body.capture_anchors_from_current else 0.0
    relation = GearRelation(
        name=body.name,
        joint_a_id=body.joint_a_id,
        joint_b_id=body.joint_b_id,
        endpoint_a_instance_id=endpoint_a_id if explicit_a else None,
        endpoint_b_instance_id=endpoint_b_id if explicit_b else None,
        endpoint_a_side=endpoint_a_side if explicit_a else None,
        endpoint_b_side=endpoint_b_side if explicit_b else None,
        ratio=body.ratio,
        invert=body.invert,
        joint_a_anchor=anchor_a,
        joint_b_anchor=anchor_b,
    )
    new_gears = [*assembly.gear_relations, relation]
    mutated = assembly.model_copy(update={"gear_relations": new_gears})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-create-gear",
        label=f"Add gear relation: {relation.name}",
        params={"relation_id": relation.id, "name": relation.name},
    )
    return _assembly_response(assembly_state.get_or_404())


@router.patch("/assembly/gear-relations/{rel_id}", status_code=200)
def patch_gear_relation(rel_id: str, body: PatchGearRelationRequest) -> dict:
    assembly = assembly_state.get_or_404()
    rel      = _find_gear_relation(assembly, rel_id)
    updates: dict = {}
    if body.name is not None:           updates["name"]           = body.name
    if body.ratio is not None:
        if not math.isfinite(body.ratio) or abs(body.ratio) < 1e-9:
            raise HTTPException(400, detail=f"ratio must be finite and nonzero, got {body.ratio}.")
        updates["ratio"] = float(body.ratio)
    if body.invert is not None:         updates["invert"]         = bool(body.invert)
    if body.joint_a_anchor is not None: updates["joint_a_anchor"] = float(body.joint_a_anchor)
    if body.joint_b_anchor is not None: updates["joint_b_anchor"] = float(body.joint_b_anchor)

    new_rel = rel.model_copy(update=updates)
    new_gears = [new_rel if g.id == rel_id else g for g in assembly.gear_relations]
    mutated = assembly.model_copy(update={"gear_relations": new_gears})
    assembly_state.set_assembly_silent(mutated)
    return _assembly_response(mutated)


@router.delete("/assembly/gear-relations/{rel_id}", status_code=200)
def delete_gear_relation(rel_id: str) -> dict:
    assembly = assembly_state.get_or_404()
    rel      = _find_gear_relation(assembly, rel_id)
    new_gears = [g for g in assembly.gear_relations if g.id != rel_id]
    mutated   = assembly.model_copy(update={"gear_relations": new_gears})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-gear",
        label=f"Delete gear relation: {rel.name}",
        params={"relation_id": rel_id, "name": rel.name},
    )
    return _assembly_response(assembly_state.get_or_404())


@router.post("/assembly/gear-relations/{rel_id}/resolve", status_code=200)
def resolve_gear_relation(rel_id: str) -> dict:
    """Drive joint_b to the value implied by joint_a + ratio + anchors RIGHT NOW.

    Used by the frontend on configuration restore + when the user explicitly
    asks the relation to be re-satisfied at the current pose.
    """
    assembly = assembly_state.get_or_404()
    rel      = _find_gear_relation(assembly, rel_id)
    joint_a = next((j for j in assembly.joints if j.id == rel.joint_a_id), None)
    joint_b = next((j for j in assembly.joints if j.id == rel.joint_b_id), None)
    if joint_a is None or joint_b is None:
        raise HTTPException(404, detail="Referenced joint missing.")
    sign      = -1.0 if rel.invert else 1.0
    new_value = rel.joint_b_anchor + sign * (joint_a.current_value - rel.joint_a_anchor) * rel.ratio
    inst_by_id = _build_inst_by_id(assembly)
    endpoint_side = _gear_endpoint_side(rel, "b", joint_b)
    if not _apply_revolute_value_to_gear_endpoint(assembly, joint_b, endpoint_side, new_value, inst_by_id):
        raise HTTPException(400, detail="Gear endpoint cannot be moved.")
    assembly_state.set_assembly_silent(assembly)
    return _assembly_response(assembly)
