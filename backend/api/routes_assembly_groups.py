"""
API layer — assembly PartGroup route handlers (extracted from assembly.py).

A PartGroup bundles PartInstances (and nested subgroups) into a single
PowerPoint-style entity that the user can move / duplicate / delete / re-style
as one unit. Groups may nest; the partition invariant (a member belongs to at
most one parent group) is enforced here on create and by the model validator.

This module hosts the cohesive cluster of group CRUD + duplicate + cascade-delete
+ rigid-transform endpoints, factored out of ``assembly.py`` following the same
template as the other assembly-side sub-routers (``routes_assembly_belts.py``,
``routes_assembly_gears.py``, ``routes_assembly_connectors.py``).

The pure grouping logic (transitive closure, clone-subtree, translation /
transform application, membership collection, post-removal filtering) already
lives in ``backend/core/assembly_groups.py`` (imported as ``_ag``), and the
revolute/gear drive math lives in ``backend/core/assembly_kinematics.py``; this
router is a thin parse → delegate → respond shell over both.

Back-imports (B=3 — all shared kernel/infrastructure, zero bespoke):
``_assembly_response`` (shared kernel, the assembly-side twin of crud.py's
``_design_response``), ``_apply_assembly_mutation_with_feature_log`` (the
assembly mutate + feature-log wrapper), and ``resolve_assembly`` (the kernel
joint-solver route, called after a group transform to re-snap externally-mated
partners — shared infrastructure, stays in assembly.py). The two group-only
helpers (``_find_group``, ``_autogen_group_name``) and all four request models
moved IN with the router.

URLs are unchanged from their previous home in assembly.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api import assembly_state
from backend.api.assembly import (
    _apply_assembly_mutation_with_feature_log,
    _assembly_response,
    resolve_assembly,
)
from backend.core import assembly_groups as _ag
from backend.core.assembly_kinematics import (
    _propagate_gear_relations_from,
    _sync_revolute_values_for_instances,
    _sync_revolute_values_for_parent_moves,
)
from backend.core.models import Assembly, PartGroup

router = APIRouter()


# ── PartGroup routes (PowerPoint-style grouping) ──────────────────────────────


def _find_group(assembly: Assembly, group_id: str) -> PartGroup:
    for g in assembly.groups:
        if g.id == group_id:
            return g
    raise HTTPException(404, detail=f"Group {group_id!r} not found.")


def _autogen_group_name(assembly: Assembly) -> str:
    """Pick the next sequential 'Group N' name."""
    used = {g.name for g in assembly.groups if g.name}
    n = 1
    while f"Group {n}" in used:
        n += 1
    return f"Group {n}"


class CreateGroupRequest(BaseModel):
    """Body for ``POST /assembly/groups``.

    Members may be a mix of top-level PartInstances and existing
    PartGroups; the partition invariant (a member can only belong to one
    parent group) is enforced.
    """
    instance_ids: list[str] = Field(default_factory=list)
    subgroup_ids: list[str] = Field(default_factory=list)
    name: Optional[str] = None


@router.post("/assembly/groups", status_code=200)
def create_group(body: CreateGroupRequest) -> dict:
    assembly = assembly_state.get_or_404()
    if not body.instance_ids and not body.subgroup_ids:
        raise HTTPException(400, detail="Group needs at least one member.")
    # Validate referenced ids exist + no double-parenting.
    instance_ids_set = {i.id for i in assembly.instances}
    group_ids_set    = {g.id for g in assembly.groups}
    for iid in body.instance_ids:
        if iid not in instance_ids_set:
            raise HTTPException(404, detail=f"Instance {iid!r} not found.")
    for sgid in body.subgroup_ids:
        if sgid not in group_ids_set:
            raise HTTPException(404, detail=f"Subgroup {sgid!r} not found.")
    for g in assembly.groups:
        for iid in body.instance_ids:
            if iid in g.instance_ids:
                raise HTTPException(
                    400,
                    detail=f"Instance {iid!r} already belongs to group {g.id!r}.",
                )
        for sgid in body.subgroup_ids:
            if sgid in g.subgroup_ids:
                raise HTTPException(
                    400,
                    detail=f"Subgroup {sgid!r} already belongs to group {g.id!r}.",
                )

    new_group = PartGroup(
        name=body.name or _autogen_group_name(assembly),
        instance_ids=list(body.instance_ids),
        subgroup_ids=list(body.subgroup_ids),
    )
    new_groups = list(assembly.groups) + [new_group]
    mutated = assembly.model_copy(update={"groups": new_groups})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-create-group",
        label=f"Group: {new_group.name}",
        params={
            "group_id":     new_group.id,
            "name":         new_group.name,
            "instance_ids": list(body.instance_ids),
            "subgroup_ids": list(body.subgroup_ids),
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/groups/{group_id}", status_code=200)
def ungroup(group_id: str) -> dict:
    """Remove the group itself; members re-enter the top level.

    Cascade-removes ``group_id`` from any parent group's ``subgroup_ids``.
    Instance ids and subgroup ids inside the removed group are unaffected —
    subgroups become top-level groups, instances become top-level instances.
    """
    assembly = assembly_state.get_or_404()
    target = _find_group(assembly, group_id)
    new_groups = _ag.filter_groups_after_group_removal(
        list(assembly.groups), {group_id}
    )
    mutated = assembly.model_copy(update={"groups": new_groups})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-ungroup",
        label=f"Ungroup: {target.name or group_id}",
        params={"group_id": group_id, "name": target.name},
    )
    return _assembly_response(assembly_state.get_or_404())


class PatchGroupRequest(BaseModel):
    name:           Optional[str] = None
    visible:        Optional[bool] = None
    representation: Optional[Literal[
        "full", "beads", "cylinders", "vdw", "ballstick", "hull-prism", "surface"
    ]] = None
    # null/empty string is treated as "clear the override → respect member reps"
    clear_representation: bool = False
    expanded:       Optional[bool] = None


@router.patch("/assembly/groups/{group_id}", status_code=200)
def patch_group(group_id: str, body: PatchGroupRequest) -> dict:
    """Update overlay fields on a group. Never mutates member instances."""
    assembly = assembly_state.get_or_404()
    target = _find_group(assembly, group_id)
    updates: dict = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.visible is not None:
        updates["visible"] = body.visible
    if body.clear_representation:
        updates["representation"] = None
    elif body.representation is not None:
        updates["representation"] = body.representation
    if body.expanded is not None:
        updates["expanded"] = body.expanded
    if not updates:
        return _assembly_response(assembly)
    new_target = target.model_copy(update=updates)
    new_groups = [new_target if g.id == group_id else g for g in assembly.groups]
    mutated = assembly.model_copy(update={"groups": new_groups})
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-patch-group",
        label=f"Update group: {new_target.name or group_id}",
        params={"group_id": group_id, "updates": updates},
    )
    return _assembly_response(assembly_state.get_or_404())


class DuplicateGroupRequest(BaseModel):
    offset: list[float] = [5.0, 0.0, 0.0]
    name:   Optional[str] = None


@router.post("/assembly/groups/{group_id}/duplicate", status_code=200)
def duplicate_group(group_id: str, body: DuplicateGroupRequest = DuplicateGroupRequest()) -> dict:
    """Deep-copy a group: clone all transitive members + nested subgroups +
    internal joints + internal bindings. External joints/bindings are dropped.
    """
    assembly = assembly_state.get_or_404()
    _find_group(assembly, group_id)   # 404 if missing
    offset = (
        float(body.offset[0]) if len(body.offset) > 0 else 5.0,
        float(body.offset[1]) if len(body.offset) > 1 else 0.0,
        float(body.offset[2]) if len(body.offset) > 2 else 0.0,
    )
    new_insts, new_joints, new_bindings, new_groups, root_id = _ag.clone_group_subtree(
        assembly, group_id, offset=offset,
    )
    if body.name is not None:
        new_groups = [
            g.model_copy(update={"name": body.name}) if g.id == root_id else g
            for g in new_groups
        ]

    mutated = assembly.model_copy(update={
        "instances":         list(assembly.instances) + new_insts,
        "joints":            list(assembly.joints) + new_joints,
        "overhang_bindings": list(assembly.overhang_bindings) + new_bindings,
        "groups":            list(assembly.groups) + new_groups,
    })
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-duplicate-group",
        label="Duplicate group",
        params={
            "source_group_id": group_id,
            "new_group_id":    root_id,
            "offset":          list(body.offset),
            "n_instances":     len(new_insts),
        },
    )
    return _assembly_response(assembly_state.get_or_404())


@router.delete("/assembly/groups/{group_id}/cascade", status_code=200)
def cascade_delete_group(group_id: str) -> dict:
    """Delete a group and all its transitive members (instances + subgroups).
    Cascade-removes joints + overhang bindings referencing deleted instances.
    """
    assembly = assembly_state.get_or_404()
    target = _find_group(assembly, group_id)
    inst_ids, group_ids = _ag.collect_group_member_ids(assembly, group_id)

    new_instances = [i for i in assembly.instances if i.id not in inst_ids]
    new_joints    = [j for j in assembly.joints
                     if j.instance_a_id not in inst_ids and j.instance_b_id not in inst_ids]
    new_bindings  = [b for b in assembly.overhang_bindings
                     if b.instance_a_id not in inst_ids and b.instance_b_id not in inst_ids]
    new_groups    = _ag.filter_groups_after_group_removal(list(assembly.groups), group_ids)

    mutated = assembly.model_copy(update={
        "instances":         new_instances,
        "joints":            new_joints,
        "overhang_bindings": new_bindings,
        "groups":            new_groups,
    })
    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-delete-group",
        label=f"Delete group: {target.name or group_id}",
        params={
            "group_id":         group_id,
            "name":             target.name,
            "deleted_instance_ids": sorted(inst_ids),
            "deleted_group_ids":    sorted(group_ids),
        },
    )
    for iid in inst_ids:
        assembly_state.forget_instance_display(iid)
    return _assembly_response(assembly_state.get_or_404())


class TransformGroupRequest(BaseModel):
    """Body for ``POST /assembly/groups/{id}/transform``.

    Either ``translation`` (3 floats, world-space) OR ``matrix`` (16 floats,
    row-major 4×4 that is left-multiplied into each affected instance's
    transform). Translation is the common case for the drag-handle gizmo;
    matrix covers translate+rotate group moves.
    """
    translation: Optional[list[float]] = None
    matrix:      Optional[list[float]] = None


@router.post("/assembly/groups/{group_id}/transform", status_code=200)
def transform_group(group_id: str, body: TransformGroupRequest) -> dict:
    """Apply a rigid transform to a group; rigidly-mated external partners
    follow via the joint/binding transitive closure."""
    assembly = assembly_state.get_or_404()
    target = _find_group(assembly, group_id)
    # Snapshot pre-move base_transforms — apply_group_transform clears them
    # on every moved instance, and gear-sync below needs the originals to
    # derive each revolute joint's implied new angle.
    pre_move_bases = {
        i.id: i.base_transform for i in assembly.instances if i.base_transform is not None
    }
    if body.translation is not None:
        if len(body.translation) != 3:
            raise HTTPException(400, detail="translation must have 3 floats.")
        mutated = _ag.apply_group_translation(
            assembly, group_id,
            (float(body.translation[0]), float(body.translation[1]), float(body.translation[2])),
        )
        op_params = {"group_id": group_id, "translation": list(body.translation)}
    elif body.matrix is not None:
        if len(body.matrix) != 16:
            raise HTTPException(400, detail="matrix must have 16 floats (row-major 4×4).")
        M = np.asarray(body.matrix, dtype=float).reshape(4, 4)
        mutated = _ag.apply_group_transform(assembly, group_id, M)
        op_params = {"group_id": group_id, "matrix": list(body.matrix)}
    else:
        raise HTTPException(400, detail="One of translation or matrix is required.")

    _apply_assembly_mutation_with_feature_log(
        mutated,
        op_kind="assembly-transform-group",
        label=f"Move group: {target.name or group_id}",
        params=op_params,
    )
    # After the bulk transform, every mated joint touching a moved instance
    # may be out of sync (revolute/prismatic axes are stored in world space;
    # rigid/spherical mates are connector-coincident in world space). Run the
    # joint solver in-place so externally-mated partners that the rigid
    # transitive closure left behind get re-snapped, axis origins re-derived
    # from connector positions, and the post-move state matches what the
    # Resolve button would produce. Mirrors the same pattern used after part
    # geometry edits at L2101. resolve_assembly() writes back via
    # set_assembly_silent so the entire group move (transform + resolve)
    # stays one undo step.
    solve_status = None
    if mutated.joints:
        resolve_resp = resolve_assembly()
        solve_status = resolve_resp.get("solve_status")

    # Re-sync revolute joint values for any joint whose child is in the moved
    # group, then propagate gear relations. Without this step, dragging a
    # group via the group gizmo (which only updates instance transforms, never
    # joint.current_value) would not drive a gear-coupled counterpart.
    latest = assembly_state.get_or_404()
    member_instance_ids, _gids = _ag.collect_group_member_ids(latest, group_id)
    updated_joint_ids = _sync_revolute_values_for_instances(
        latest, member_instance_ids, base_transforms_override=pre_move_bases,
    )
    # Parent-side sync: joints where the moved group is the PARENT (instance_a)
    # and the child (instance_b) stayed put (e.g. fixed axle). The child's
    # angle relative to the parent goes down by Δ (the parent's rotation
    # about the joint axis), so the gear-coupled side fires on inverse.
    if body.matrix is not None:
        M = np.asarray(body.matrix, dtype=float).reshape(4, 4)
        parent_updates = _sync_revolute_values_for_parent_moves(
            latest, member_instance_ids, M,
        )
        updated_joint_ids = [*updated_joint_ids, *parent_updates]
    for jid in updated_joint_ids:
        _propagate_gear_relations_from(latest, jid)
    if updated_joint_ids:
        assembly_state.set_assembly_silent(latest)

    response = _assembly_response(assembly_state.get_or_404())
    if solve_status is not None:
        response["solve_status"] = solve_status
    return response
