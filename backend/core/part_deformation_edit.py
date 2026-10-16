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


def resolve_group_edit(prefix, original, proposed, patch):
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
