"""Toggle saved feature execution through the existing recipe transaction."""
from fastapi import HTTPException


def prepare_suppression(source, index, suppressed, *, executor, dependency_resolver):
    from backend.api.part_recipe_edit import CommandReplayError, regenerate
    from backend.api.part_recipe_prefix import ReplayPrefix
    from backend.core.part_history_contract import assess_part_history
    from backend.core.part_structure_gate import require_valid_structure
    from backend.core.validator import validate_design

    if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
        raise HTTPException(409, detail='Return to the end of history before suppressing a feature')
    if type(suppressed) is not bool or not 0 <= index < len(source.feature_log):
        raise HTTPException(400, detail='Invalid feature suppression target')
    if source.feature_log[index].suppressed == suppressed:
        raise HTTPException(400, detail='Feature already has that suppression state')
    prefix = ReplayPrefix(source, index)
    proof = assess_part_history(source, execute=lambda kind, current, params:
        prefix.execute(executor, kind, current, params), dependencies=dependency_resolver)
    if proof['status'] not in {'verified', 'reproduced_import'}:
        raise HTTPException(409, detail={'code': 'recipe_not_reproducible', 'assessment': proof})
    log = list(source.feature_log)
    log[index] = log[index].model_copy(update={'suppressed': suppressed})
    try:
        candidate = regenerate(source, log, lambda: None, executor=executor, prefix=prefix,
                               attribute_failures=True)
    except CommandReplayError as error:
        label = f'Feature {error.feature_id}'
        for position, row in enumerate(log):
            entries = row.children if row.feature_type == 'routing-cluster' else [row]
            failed = next((entry for entry in entries if entry.id == error.feature_id), None)
            if failed is not None:
                name = getattr(failed, 'label', None) or getattr(getattr(failed, 'op_snapshot', None), 'type', row.feature_type)
                label = f'F{position + 1} {name}'
                break
        raise HTTPException(409, detail={**error.issue, 'feature_id': error.feature_id,
            'detail': f'{label} cannot regenerate: {error.reason}'}) from error
    require_valid_structure(candidate)

    def checked_execute(kind, current, params):
        rebuilt = executor(kind, current, params)
        require_valid_structure(rebuilt)
        return rebuilt

    proof = assess_part_history(candidate, execute=checked_execute, dependencies=dependency_resolver)
    if proof['status'] not in {'verified', 'reproduced_import'}:
        raise HTTPException(409, detail={'code': 'recipe_not_reproducible', 'assessment': proof})
    return candidate, validate_design(candidate)


def seek_suppressed_history(source, position, sub_position):
    """Replay the requested prefix, retaining every saved row and its identity."""
    from backend.api.part_recipe_edit import regenerate

    log = list(source.feature_log)
    if position < -2:
        raise HTTPException(400, detail='Invalid history position')
    count = 0 if position == -2 else len(log) if position == -1 else min(position + 1, len(log))
    active = log[:count]
    cursor = -1 if count == len(log) else position
    sub_cursor = None
    if sub_position is not None and 0 <= position < len(log):
        row = log[position]
        if row.feature_type == 'routing-cluster':
            cursor, sub_cursor = position, sub_position
            if sub_position < -1:
                active = log[:position]
            elif 0 <= sub_position < len(row.children):
                active[-1] = row.model_copy(update={'children': row.children[:sub_position + 1]})
    rebuilt = regenerate(source, active, lambda: None)
    return rebuilt.copy_with(feature_log=log, feature_log_cursor=cursor,
                             feature_log_sub_cursor=sub_cursor)
