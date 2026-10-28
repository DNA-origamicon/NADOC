"""Make Cluster changes selection ownership without dropping prior placement.

An identity default may surrender whole helices. A posed/default arm owner or
a domain selection keeps its existing scope; the new identity cluster composes
with those visible existing owners through the ordinary native cluster pipeline.
No coordinates or replacement placement records are created here.
"""


def transfers_members(design, owner, cluster):
    if not owner.is_default or cluster.domain_ids or owner.domain_ids:
        return False
    if (owner.parent_cluster_id or owner.overhang_duplex_driver_id
            or owner.translation != [0, 0, 0] or owner.rotation != [0, 0, 0, 1]
            or owner.pivot != [0, 0, 0]):
        return False
    selected = set(cluster.helix_ids)
    # Deformation arm membership is geometric input even for an identity pose.
    return not any(not op.affected_helix_ids or selected.intersection(op.affected_helix_ids)
                   for op in design.deformations)


def creation_clusters(design, clusters, cluster):
    if (cluster.translation != [0, 0, 0] or cluster.rotation != [0, 0, 0, 1]
            or cluster.pivot != [0, 0, 0] or cluster.parent_cluster_id
            or cluster.overhang_duplex_driver_id or cluster.is_default):
        raise ValueError("Make Cluster starts at identity. Use Move/Rotate to move its members.")
    selected = set(cluster.helix_ids)
    result = [owner.model_copy(update={
        "helix_ids": [hid for hid in owner.helix_ids if hid not in selected]})
        if transfers_members(design, owner, cluster) else owner for owner in clusters] + [cluster]
    require_unchanged_arm_scope(design, result)
    return result


def require_unchanged_arm_scope(design, clusters):
    """Existing deformation arms are incoming references, not new geometry."""
    if not design.deformations:
        return
    from backend.core.deformation import _arm_filter_cluster
    from backend.core.part_command_errors import ReferenceResolutionError

    def scope(owners, hid):
        owner = _arm_filter_cluster([c for c in owners if hid in c.helix_ids])
        return frozenset(owner.helix_ids) if owner else frozenset(h.id for h in design.helices)

    changed = {h.id for h in design.helices
               if scope(design.cluster_transforms, h.id) != scope(clusters, h.id)}
    dependents = [op for op in design.deformations
                  if changed and (not op.affected_helix_ids or changed.intersection(op.affected_helix_ids))]
    if dependents:
        raise ReferenceResolutionError(
            "Cannot change cluster membership: it would change the arm used by "
            + ", ".join(f'{op.type.title()} "{op.id}"' for op in dependents[:8])
            + ". Make the cluster before these deformation features, or remove their dependency first.",
            code="invalid_selection", references=[{"kind": "deformation", "identity": op.id,
                "parameter_path": ["cluster", "helix_ids"]} for op in dependents])


def restore_creation_history(design, position):
    """Replay grouping inputs after the selected decoded topology checkpoint.

    This reconstructs metadata only. Ordinary seek still owns pose overlays,
    nucleotide-pose chronology, Join and pattern recovery and final geometry.
    """
    from backend.core.part_overlay_commands import build, command_input, pose_fields
    from backend.core.part_operation_input import validate_operation_input

    entries = design.feature_log
    if len(entries) > 2_000:
        raise ValueError("Cluster history exceeds its recovery entry limit")
    end = len(entries) - 1 if position == -1 else position
    last_payload = max((i for i, entry in enumerate(entries) if i <= end
        and entry.feature_type in {"snapshot", "routing-cluster"}
        and not entry.evicted and entry.post_state_gz_b64), default=-1)
    current = design
    for entry in entries[last_payload + 1:max(0, end + 1)]:
        if entry.feature_type == "cluster_create":
            kind, params = command_input(entry)
            validate_operation_input(params)
            current = build(kind, current, params)
        elif entry.feature_type == "cluster_op":
            fields = pose_fields(entry)
            current = current.copy_with(cluster_transforms=[
                c.model_copy(update=fields) if c.id == entry.cluster_id else c
                for c in current.cluster_transforms])
        elif entry.feature_type == "deformation" and entry.op_snapshot is not None:
            current = current.copy_with(deformations=[*current.deformations, entry.op_snapshot])
    return current
