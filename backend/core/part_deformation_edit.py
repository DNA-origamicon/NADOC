"""Resolve an explicit historical group edit from its owned native prefix.

This is an authoring operation, not a replay rule. Existing v1 operations keep
their exact stored membership. Even when a popup resubmits the same groups,
plane/parameter edits must not reinterpret historical custom affected IDs.
Only an actual group-selection change uses the existing creation selectors.
"""

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


def can_edit_groups(operation):
    """Explicit strand/domain selections keep their authored frozen scope."""
    return operation.targets is None and operation.target_ranges is None


def can_edit_named_groups(operation):
    """Schema-only eligibility; missing named identities remain repairable.

    Membership and the numerical placement context are deliberately not read.
    The source-owned edit/replay boundary resolves these inputs on its prefix.
    """
    from backend.core.part_group_selection import target_references
    from backend.core.part_operation_input import MAX_OPERATION_NODES

    targets = operation.targets
    if type(targets) is not list or not 0 < len(targets) <= MAX_OPERATION_NODES:
        return False
    try:
        target_references(targets)
    except CommandContractError:
        return False
    return all(target["kind"] == "part_group" for target in targets)


def _named_edit(prefix, original, proposed):
    if not can_edit_named_groups(original) or not can_edit_named_groups(proposed):
        raise CommandContractError("Only existing pure named-group selections can be retargeted",
                                   code="protected_deformation_selection")
    if proposed.cluster_ids != original.cluster_ids:
        raise CommandContractError("Named selection cannot change numerical placement context",
                                   code="protected_deformation_selection")
    if prefix is None:
        raise CommandContractError("Changing named groups requires the owned feature-stage prefix",
                                   code="missing_deformation_prefix")
    from backend.core.part_group_selection import resolve_deformation_targets

    ranges = resolve_deformation_targets(prefix, proposed.targets)
    return proposed.model_copy(update={"target_ranges": ranges,
                                       "affected_helix_ids": sorted({item.helix_id for item in ranges})})


def resolve_group_edit(prefix, original, proposed, patch):
    if "targets" in patch:
        proposed = _named_edit(prefix, original, proposed)
    if "cluster_ids" not in patch:
        return proposed
    identities = patch["cluster_ids"]
    if type(identities) is not list or any(type(identity) is not str for identity in identities):
        raise CommandContractError("Group selection must contain native identities",
                                   code="invalid_deformation_selection")
    references = [{"kind": "cluster", "identity": identity,
                   "parameter_path": ["cluster_ids", index]}
                  for index, identity in enumerate(identities)]
    if len(identities) != len(set(identities)):
        raise ReferenceResolutionError("Group selection contains duplicate identities",
                                       references=references, code="invalid_selection")
    # Order is not membership: the native selector takes the union of groups.
    if set(identities) == set(original.cluster_ids):
        return proposed
    if not can_edit_groups(original):
        raise CommandContractError("Explicit deformation targets cannot be changed through group selection",
                                   code="protected_deformation_selection")
    if prefix is None:
        raise CommandContractError("Changing groups requires the owned feature-stage prefix",
                                   code="missing_deformation_prefix")
    existing = {cluster.id for cluster in prefix.cluster_transforms}
    missing = [reference for reference in references if reference["identity"] not in existing]
    if missing:
        raise ReferenceResolutionError("Selected groups do not exist before this feature",
                                       references=missing)
    from backend.core.deformation import helices_crossing_planes, resolve_cluster_scope

    resolved = resolve_cluster_scope(prefix, identities, helices_crossing_planes(
        prefix, proposed.plane_a_bp, proposed.plane_b_bp))
    if not resolved["helix_ids"]:
        # The native evaluator treats an empty affected list as all helices.
        # An empty group/window intersection must never broaden the selection.
        raise ReferenceResolutionError("Selected groups do not intersect the deformation window",
                                       references=references, code="invalid_selection")
    return proposed.model_copy(update={"cluster_ids": resolved["cluster_ids"],
                                       "affected_helix_ids": resolved["helix_ids"]})
