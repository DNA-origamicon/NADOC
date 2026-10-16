"""Bounded incoming organization references and native realization admission."""

from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


def group_targets(design, *, max_items=30_000, checkpoint=lambda: None):
    """Return (operation ID, group ID, model path), plus charged item count.

    Inspect live inputs only. Historical rows describe their own prefixes and
    are not incoming references to the current organizational wrappers.
    """
    from backend.core.part_group_selection import has_part_group_targets, target_references
    from backend.core.part_capture_graph import CaptureLimit, GraphBudget

    operations = design.deformations
    if not isinstance(operations, list):
        raise CommandContractError("Invalid deformation inventory", code="invalid_group_consumer")
    count = len(operations)
    if count > max_items:
        raise CommandContractError("Group consumer allowance exceeded", code="group_consumer_limit")
    for op in operations:
        checkpoint()
        if op.targets is not None:
            if not isinstance(op.targets, list):
                raise CommandContractError("Invalid deformation targets", code="invalid_group_consumer")
            count += len(op.targets)
            if count > max_items:
                raise CommandContractError("Group consumer allowance exceeded", code="group_consumer_limit")
    result = []
    budget = GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None, clock=lambda: 0)
    for position, op in enumerate(operations):
        checkpoint()
        if not has_part_group_targets(op.targets):
            continue  # Saved legacy selectors keep their existing native grammar.
        try:
            budget.charge(op.id)
            for target in op.targets or ():
                budget.charge(target)  # Shared containers still cost once per occurrence.
        except CaptureLimit as error:
            raise CommandContractError(str(error), code="group_consumer_limit") from error
        target_references(op.targets)  # Closed grammar before looking up any IDs.
        for index, target in enumerate(op.targets or ()):
            if target["kind"] == "part_group":
                result.append((op.id, target["id"], ["deformations", position, "targets", index, "id"]))
    return result, count


def require_no_incoming_groups(design, selected):
    targets, _ = group_targets(design)
    incoming = [{"kind": "part_group", "identity": identity, "parameter_path": path}
                for _, identity, path in targets if identity in selected]
    if incoming:
        raise ReferenceResolutionError(
            "A deformation selects this group. Repair or remove that feature before dissolving the group.",
            references=incoming, code="invalid_selection")


def require_whole_helix_realization(design):
    """Existing loop planners cannot realize a partial/directional group scope.

    Keep saved legacy realization unchanged. New named group selections must
    cover both full helix directions before the existing numerical planner runs.
    """
    if design.group_organization is None:
        return
    targets, _ = group_targets(design)
    selected = {owner for owner, _, _ in targets}
    if not selected:
        return
    from backend.core.models import Direction

    count = len(design.helices)
    for op in design.deformations:
        if op.id in selected:
            count += len(op.affected_helix_ids)
            if op.target_ranges is not None:
                count += len(op.target_ranges)
    if count > 30_000:
        raise CommandContractError("Group realization allowance exceeded", code="group_consumer_limit")
    helices = {helix.id: helix for helix in design.helices}
    from backend.core.part_capture_graph import CaptureLimit, GraphBudget
    budget = GraphBudget(max_nodes=30_000, max_bytes=2_000_000, seconds=None, clock=lambda: 0)
    for op in design.deformations:
        if op.id not in selected:
            continue
        try:
            for identity in op.affected_helix_ids:
                budget.charge(identity)
        except CaptureLimit as error:
            raise CommandContractError(str(error), code="group_consumer_limit") from error
        ranges = op.target_ranges
        allowed = bool(ranges) and len(ranges) <= 30_000
        if allowed:
            covered = {}
            for scope in ranges:
                helix = helices.get(scope.helix_id)
                if helix is None or (scope.start_bp, scope.end_bp) != (
                        helix.bp_start, helix.bp_start + helix.length_bp - 1):
                    allowed = False
                    break
                covered.setdefault(scope.helix_id, set()).add(scope.direction)
            allowed = allowed and set(covered) == set(op.affected_helix_ids) and all(
                directions == {Direction.FORWARD, Direction.REVERSE} for directions in covered.values())
        if not allowed:
            raise CommandContractError(
                "Loop/skip realization requires a whole-helix group selection in both directions.",
                code="unsupported_partial_group_realization")
