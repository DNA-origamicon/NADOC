"""Dependency closure for assembly deletion, shared by commands and replay.

Configurations and animation keyframes are historical snapshots/selections and
remain intact. Removing a constraint detaches its followers; surviving parts
keep their current pose and their source histories.
"""

from backend.core.assembly_groups import (
    filter_groups_after_group_removal, filter_groups_after_instance_removal,
)
from backend.core.assembly_linker import remove_assembly_linker_topology
from backend.core.models import Assembly


def remove_members(assembly: Assembly, *, instance_ids=(), group_ids=(), joint_ids=(), connection_ids=()) -> Assembly:
    instances = set(instance_ids)
    joints = set(joint_ids) | {
        j.id for j in assembly.joints
        if j.instance_a_id in instances or j.instance_b_id in instances
    }
    connections = set(connection_ids) | {
        c.id for c in assembly.overhang_connections
        if c.instance_a_id in instances or c.instance_b_id in instances
    }
    belts = {
        b.id for b in assembly.belt_paths
        if any(p.joint_id in joints or p.instance_id in instances for p in (b.pulley_a, b.pulley_b))
    }
    helices, strands = list(assembly.assembly_helices), list(assembly.assembly_strands)
    for connection_id in sorted(connections):
        helices, strands = remove_assembly_linker_topology(helices, strands, connection_id)
    groups = filter_groups_after_group_removal(list(assembly.groups), set(group_ids))
    groups = filter_groups_after_instance_removal(groups, instances)
    return assembly.model_copy(update={
        "instances": [i for i in assembly.instances if i.id not in instances],
        "groups": groups,
        "joints": [j for j in assembly.joints if j.id not in joints],
        "gear_relations": [g for g in assembly.gear_relations
                           if g.joint_a_id not in joints and g.joint_b_id not in joints
                           and g.endpoint_a_instance_id not in instances and g.endpoint_b_instance_id not in instances],
        "belt_paths": [b for b in assembly.belt_paths if b.id not in belts],
        "belt_riders": [r for r in assembly.belt_riders if r.belt_path_id not in belts and r.instance_id not in instances],
        "overhang_bindings": [b for b in assembly.overhang_bindings
                              if b.instance_a_id not in instances and b.instance_b_id not in instances],
        "overhang_connections": [c for c in assembly.overhang_connections if c.id not in connections],
        "duplexes": [d for d in assembly.duplexes
                     if d.left.instance_id not in instances and d.right.instance_id not in instances
                     and d.connection_id not in connections],
        "assembly_helices": helices,
        "assembly_strands": strands,
        "protein_attachments": [p for p in assembly.protein_attachments
                                if getattr(p.target, "instance_id", None) not in instances],
    })
