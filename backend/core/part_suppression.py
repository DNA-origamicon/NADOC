"""Suppressed definitions remain fingerprinted recipe steps with no execution."""

KIND = 'suppressed-feature'


def replay_input(entry, *, parent_suppressed=False):
    from backend.core.part_overlay_commands import command_input
    kind, params = command_input(entry)
    if parent_suppressed or entry.suppressed:
        return KIND, {'kind': kind, 'params': params, '_proof_version': 1}
    return kind, params


def valid_definition(params, resolver):
    return (type(params) is dict and set(params) == {'kind', 'params', '_proof_version'}
            and type(params['_proof_version']) is int and params['_proof_version'] == 1
            and type(params['kind']) is str and params['kind'] != KIND
            and type(params['params']) is dict
            and resolver(params['kind'], params['params']).known)


def has_suppression(log):
    return any(entry.suppressed or any(child.suppressed for child in getattr(entry, 'children', []))
               for entry in log)
