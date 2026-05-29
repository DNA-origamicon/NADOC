"""PartGroup helpers for the assembly layer.

Pure functions over ``Assembly`` (no FastAPI / I/O). Two responsibilities:

1. **transitive_rigidly_attached** — given a seed of instance ids (typically a
   group's transitive members), walk the joint + duplex-binding graph and
   return every instance that is *rigidly* attached. Used by the group
   transform endpoint so externally-mated parts follow the group as a unit
   when the connection is rigid (rigid joint, duplex overhang binding) but
   stay put when the connection is articulated (revolute / prismatic /
   toehold).

2. **clone_group_subtree** — deep-copy all transitive members + nested
   subgroups + internal joints + internal overhang bindings of a group, with
   fresh ids and a caller-supplied translational offset applied to the new
   instance transforms. External joints/bindings (those with at least one
   endpoint outside the group) are *dropped* — the new copy is unconnected to
   anything outside.

3. **collect_group_instance_ids** / **collect_group_member_ids** — transitive
   id collection helpers used by the routes above and by cascade-delete.
"""
from __future__ import annotations

from typing import Iterable
import uuid as _uuid

import numpy as np

from backend.core.models import (
    Assembly,
    AssemblyJoint,
    AssemblyOverhangBinding,
    Mat4x4,
    PartGroup,
    PartInstance,
)


# ── Group membership traversal ─────────────────────────────────────────────────


def collect_group_member_ids(assembly: Assembly, group_id: str) -> tuple[set[str], set[str]]:
    """Return ``(instance_ids, group_ids)`` reachable from ``group_id``.

    ``group_ids`` includes the seed itself. Cycles can't happen because the
    Assembly validator rejects them.
    """
    by_id = {g.id: g for g in assembly.groups}
    if group_id not in by_id:
        return set(), set()
    visited_groups: set[str] = set()
    visited_instances: set[str] = set()
    stack = [group_id]
    while stack:
        gid = stack.pop()
        if gid in visited_groups:
            continue
        visited_groups.add(gid)
        g = by_id.get(gid)
        if g is None:
            continue
        visited_instances.update(g.instance_ids)
        stack.extend(g.subgroup_ids)
    return visited_instances, visited_groups


def collect_group_instance_ids(assembly: Assembly, group_id: str) -> set[str]:
    """Convenience: transitive set of instance ids inside ``group_id``."""
    inst_ids, _ = collect_group_member_ids(assembly, group_id)
    return inst_ids


def find_owning_group(assembly: Assembly, member_id: str) -> PartGroup | None:
    """Return the PartGroup whose ``instance_ids`` or ``subgroup_ids``
    contains ``member_id``, or ``None`` if the member is at the top level."""
    for g in assembly.groups:
        if member_id in g.instance_ids or member_id in g.subgroup_ids:
            return g
    return None


# ── Rigid-attachment transitive closure ────────────────────────────────────────


def _joint_is_rigid(joint: AssemblyJoint) -> bool:
    """A joint constrains both endpoints rigidly when:

    - ``joint_type == "rigid"`` — the obvious case.
    - ``joint_type == "spherical"`` — preserves position but allows rotation;
      for *translation-only* group moves this still drags the partner with
      the seed, so we treat it as rigid.

    Revolute / prismatic joints permit one DOF and are *not* rigid — moving
    the seed past them rotates / slides the partner relative to the seed but
    the partner stays where it is in world space.
    """
    return joint.joint_type in ("rigid", "spherical")


def _binding_is_rigid(binding: AssemblyOverhangBinding) -> bool:
    """Duplex overhang bindings are physically a Watson-Crick pair — the two
    helices are coaxial and rigid for the purposes of moving the group.
    Toehold bindings are transient single-base attachments and are not
    treated as rigid."""
    mode = getattr(binding, "binding_mode", "duplex") or "duplex"
    return mode == "duplex"


def transitive_rigidly_attached(
    assembly: Assembly, seed_instance_ids: Iterable[str]
) -> set[str]:
    """BFS through joint + duplex-binding edges from the seed set, crossing
    only edges that imply rigid attachment. Returns every instance reachable
    (including the original seed)."""
    reached: set[str] = set(seed_instance_ids)
    frontier: list[str] = list(reached)

    # Build an adjacency multimap once — assemblies with thousands of
    # instances should still be cheap to walk.
    adj: dict[str, set[str]] = {}
    def _add_edge(a: str | None, b: str | None) -> None:
        if not a or not b or a == b:
            return
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    for j in assembly.joints:
        if _joint_is_rigid(j):
            _add_edge(j.instance_a_id, j.instance_b_id)
    for b in assembly.overhang_bindings:
        if _binding_is_rigid(b):
            _add_edge(b.instance_a_id, b.instance_b_id)

    while frontier:
        cur = frontier.pop()
        for neighbour in adj.get(cur, ()):
            if neighbour not in reached:
                reached.add(neighbour)
                frontier.append(neighbour)
    return reached


# ── Group duplication ──────────────────────────────────────────────────────────


def clone_group_subtree(
    assembly: Assembly,
    group_id: str,
    *,
    offset: tuple[float, float, float] = (5.0, 0.0, 0.0),
    name_suffix: str = " (copy)",
) -> tuple[
    list[PartInstance],          # new instances
    list[AssemblyJoint],          # new joints (internal only)
    list[AssemblyOverhangBinding],  # new bindings (internal only)
    list[PartGroup],              # new groups (root first)
    str,                          # id of the cloned root group
]:
    """Deep-copy a group: every transitive instance + nested subgroup gets a
    fresh id; every *internal* joint / overhang binding (both endpoints inside
    the group) is cloned with re-IDed ``instance_*_id`` references; *external*
    joints / bindings are dropped. New instance transforms are left-multiplied
    by a pure translation ``offset`` so the copy is visible next to the
    original. The clone preserves the group's nesting structure exactly."""
    by_inst = {i.id: i for i in assembly.instances}
    by_group = {g.id: g for g in assembly.groups}
    if group_id not in by_group:
        raise KeyError(f"PartGroup {group_id!r} not found")

    inst_ids_to_clone, group_ids_to_clone = collect_group_member_ids(assembly, group_id)

    # Build id_map first so internal joint/binding cloning can resolve.
    id_map: dict[str, str] = {old: str(_uuid.uuid4()) for old in inst_ids_to_clone}
    group_id_map: dict[str, str] = {old: str(_uuid.uuid4()) for old in group_ids_to_clone}

    # ── Instances ──
    new_instances: list[PartInstance] = []
    dx, dy, dz = (float(offset[0]), float(offset[1]), float(offset[2]))
    for old_id in inst_ids_to_clone:
        src = by_inst[old_id]
        T = src.transform.to_array().copy()
        T[0, 3] += dx
        T[1, 3] += dy
        T[2, 3] += dz
        new_inst = src.model_copy(deep=True, update={
            "id":             id_map[old_id],
            "name":           f"{src.name}{name_suffix}",
            "transform":      Mat4x4.from_array(T),
            "base_transform": None,
        })
        new_instances.append(new_inst)

    # ── Internal joints (both endpoints inside the group) ──
    new_joints: list[AssemblyJoint] = []
    for j in assembly.joints:
        a = j.instance_a_id
        b = j.instance_b_id
        if a in inst_ids_to_clone and b in inst_ids_to_clone:
            new_j = j.model_copy(deep=True, update={
                "id":             str(_uuid.uuid4()),
                "instance_a_id":  id_map[a],
                "instance_b_id":  id_map[b],
            })
            new_joints.append(new_j)

    # ── Internal overhang bindings ──
    new_bindings: list[AssemblyOverhangBinding] = []
    for binding in assembly.overhang_bindings:
        a = binding.instance_a_id
        b = binding.instance_b_id
        if a in inst_ids_to_clone and b in inst_ids_to_clone:
            new_b = binding.model_copy(deep=True, update={
                "id":             str(_uuid.uuid4()),
                "instance_a_id":  id_map[a],
                "instance_b_id":  id_map[b],
            })
            new_bindings.append(new_b)

    # ── Groups (preserve nesting) ──
    new_groups: list[PartGroup] = []
    for old_gid in group_ids_to_clone:
        src_g = by_group[old_gid]
        new_groups.append(src_g.model_copy(deep=True, update={
            "id":            group_id_map[old_gid],
            "name":          f"{src_g.name}{name_suffix}" if src_g.name else "",
            "instance_ids":  [id_map[i] for i in src_g.instance_ids if i in id_map],
            "subgroup_ids":  [group_id_map[s] for s in src_g.subgroup_ids if s in group_id_map],
        }))

    return new_instances, new_joints, new_bindings, new_groups, group_id_map[group_id]


# ── Cascade delete ─────────────────────────────────────────────────────────────


def apply_group_translation(
    assembly: Assembly, group_id: str, delta: tuple[float, float, float]
) -> Assembly:
    """Translate every instance reached by the transitive rigid closure of
    ``group_id`` by ``delta`` (world-space). Returns a new ``Assembly`` with
    the updated transforms; never mutates the input.

    External rigidly-mated partners follow along — see
    :func:`transitive_rigidly_attached`. Joints' ``current_value`` is *not*
    rewritten; the existing joint solver re-derives any joint's stored DOF
    on the next read from the new transforms.
    """
    seed = collect_group_instance_ids(assembly, group_id)
    if not seed:
        return assembly
    reached = transitive_rigidly_attached(assembly, seed)
    dx, dy, dz = (float(delta[0]), float(delta[1]), float(delta[2]))
    new_instances: list[PartInstance] = []
    for inst in assembly.instances:
        if inst.id in reached:
            T = inst.transform.to_array().copy()
            T[0, 3] += dx
            T[1, 3] += dy
            T[2, 3] += dz
            new_instances.append(inst.model_copy(update={
                "transform":      Mat4x4.from_array(T),
                "base_transform": None,
            }))
        else:
            new_instances.append(inst)
    return assembly.model_copy(update={"instances": new_instances})


def apply_group_transform(
    assembly: Assembly, group_id: str, transform_4x4: np.ndarray
) -> Assembly:
    """Left-multiply ``transform_4x4`` (4×4 row-major) into the world
    transform of every instance reached by the transitive rigid closure of
    ``group_id``. Use this for combined translate + rotate group moves; for
    pure translation prefer :func:`apply_group_translation`."""
    seed = collect_group_instance_ids(assembly, group_id)
    if not seed:
        return assembly
    reached = transitive_rigidly_attached(assembly, seed)
    M = np.asarray(transform_4x4, dtype=float).reshape(4, 4)
    new_instances: list[PartInstance] = []
    for inst in assembly.instances:
        if inst.id in reached:
            T = inst.transform.to_array()
            T_new = M @ T
            new_instances.append(inst.model_copy(update={
                "transform":      Mat4x4.from_array(T_new),
                "base_transform": None,
            }))
        else:
            new_instances.append(inst)
    return assembly.model_copy(update={"instances": new_instances})


def filter_groups_after_instance_removal(
    groups: list[PartGroup], removed_instance_ids: set[str]
) -> list[PartGroup]:
    """Drop removed instance ids from ``instance_ids`` of every group.

    Used by the cascade-delete handler after stripping instances. Leaves an
    empty group in place (the caller decides whether to also drop empty
    groups — for cascade-delete-group we drop the targeted group; for
    delete-instance we leave the parent group intact even if it's now
    empty)."""
    if not removed_instance_ids:
        return list(groups)
    return [
        g.model_copy(update={
            "instance_ids": [i for i in g.instance_ids if i not in removed_instance_ids],
        })
        for g in groups
    ]


def filter_groups_after_group_removal(
    groups: list[PartGroup], removed_group_ids: set[str]
) -> list[PartGroup]:
    """Drop removed group ids from ``subgroup_ids`` of every survivor and
    remove the deleted groups themselves."""
    if not removed_group_ids:
        return list(groups)
    survivors: list[PartGroup] = []
    for g in groups:
        if g.id in removed_group_ids:
            continue
        survivors.append(g.model_copy(update={
            "subgroup_ids": [s for s in g.subgroup_ids if s not in removed_group_ids],
        }))
    return survivors
