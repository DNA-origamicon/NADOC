"""Reorder authored history through native dependency resolution and regeneration."""

from fastapi import HTTPException


def ordered_log(source, index, destination):
    """Move a whole row; preserve routing children and all authored identities."""
    log = list(source.feature_log)
    if not 0 <= index < len(log) or not 0 <= destination < len(log):
        raise HTTPException(400, detail="Feature move index out of range")
    if index == destination:
        raise HTTPException(400, detail="Feature is already at that position")
    crossed = log[min(index, destination):max(index, destination) + 1]
    initial = next((entry for entry in crossed if entry.feature_type == 'snapshot'
                    and entry.op_kind == 'bundle-create'), None)
    if initial is not None:
        # Bundle creation starts a fresh part, rather than adding to its prefix.
        # Replaying it later would silently discard already-authored geometry.
        raise HTTPException(409, detail={'code': 'history_root_order', 'feature_id': initial.id,
            'detail': 'The initial bundle must remain before its later features.'})
    log.insert(destination, log.pop(index))
    return log


def prepare_reorder(source, index, destination, *, executor, dependency_resolver):
    from backend.api.part_recipe_edit import CommandReplayError, regenerate
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_structure_gate import require_valid_structure
    from backend.core.validator import validate_design

    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail="Return to the end of history before moving a feature")
    log = ordered_log(source, index, destination)
    prefix = ReplayPrefix(source, min(index, destination))
    proof = assess_part_history(source, execute=lambda kind, current, params:
        prefix.execute(executor, kind, current, params), dependencies=dependency_resolver)
    if proof["status"] not in {"verified", "reproduced_import"}:
        raise HTTPException(409, detail={"code": "recipe_not_reproducible", "assessment": proof})
    # The impact graph is conservative, not a prohibition on authored ordering.
    # Replay resolves references at the proposed stage and validates each command.
    # A failed move never removes routing children or publishes partial geometry.
    try:
        candidate = regenerate(source, log, lambda: None, executor=executor, prefix=prefix,
                               attribute_failures=True)
    except CommandReplayError as error:
        for position, entry in enumerate(log):
            children = entry.children if entry.feature_type == 'routing-cluster' else [entry]
            failed = next((child for child in children if child.id == error.feature_id), None)
            if failed is not None:
                label = getattr(failed, 'label', None) or getattr(getattr(failed, 'op_snapshot', None), 'type', entry.feature_type)
                reason = f"F{position + 1} {label} cannot regenerate: {error.reason}"
                break
        else:
            reason = error.reason
        raise HTTPException(409, detail={**error.issue, 'detail': reason,
                                         'feature_id': error.feature_id}) from error
    require_valid_structure(candidate)
    # Reordering can expose an invalid intermediate stage even when a later
    # command repairs the final state. Certify the whole new recipe before it
    # becomes a publishable candidate, without using its recovery snapshots.
    def checked_execute(kind, current, params):
        rebuilt = executor(kind, current, params)
        require_valid_structure(rebuilt)
        return rebuilt

    proof = assess_part_history(candidate, execute=checked_execute, dependencies=dependency_resolver)
    if proof['status'] not in {'verified', 'reproduced_import'}:
        raise HTTPException(409, detail={'code': 'recipe_not_reproducible', 'assessment': proof})
    return candidate, validate_design(candidate)
