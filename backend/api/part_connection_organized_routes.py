"""Server-captured ordinary connection choices for the owned organized host."""

from time import time
from uuid import uuid4

from fastapi import HTTPException

from backend.api import state
from backend.api.part_connection_recipe_recording import CONTEXT, create
from backend.api.part_connection_organization import KEY

ENABLED = False


def capture_inputs(source, action, choices, version_id=None):
    from backend.api import part_connection_version_commands as metadata
    from backend.api.part_connection_application_commands import _route_version
    from backend.api.part_connection_direct_recording import conflict_values
    from backend.api.part_connection_owner_selection import capture_selection
    version = None if action in {'create', 'connect'} else _route_version(source, version_id)
    if action in {'unapply', 'disconnect_delete'}:
        from backend.api.part_connection_disconnect import capture_inputs as disconnect
        return {**disconnect(source, version, delete_version=action == 'disconnect_delete'), KEY: dict(CONTEXT)}
    values = {'_proof_version': 1, 'connection_version_contract': 2,
        'action': f'connection-version-{action}', 'version_id': version.id if version else str(uuid4()),
        'overhang_a_id': version.overhang_a_id if version else choices.get('overhang_a_id'),
        'overhang_b_id': version.overhang_b_id if version else choices.get('overhang_b_id')}
    if action in {'create', 'connect'}:
        values.update(name=(choices.get('name') or '').strip(), created_at=time(),
            connection_type=choices.get('connection_type'), overhang_a_seq=choices.get('overhang_a_seq'),
            overhang_b_seq=choices.get('overhang_b_seq'), bridge_seq=choices.get('bridge_seq'),
            bridge_length=max(0, int(choices.get('bridge_length') or 0)),
            applied=bool(choices.get('applied')) if action == 'create' else False)
    elif action == 'patch':
        values['patch'] = dict(choices)
        if values['patch'].get('bridge_length') is not None:
            values['patch']['bridge_length'] = max(0, values['patch']['bridge_length'])
    elif action == 'apply':
        values.pop('connection_version_contract')
        values['connection_type'] = version.connection_type
    elif action != 'delete':
        raise ValueError('Unknown organized connection action')
    if action in {'create', 'patch', 'delete'}:
        values['affected_version_ids'] = metadata.affected_versions(source, values)
    else:
        direct = values['connection_type'] in {'root-to-root', 'end-to-root'}
        values['action'] = f'connection-version-{action}-' + ('direct' if direct else 'linker')
        values[('direct_' if direct else 'connection_') + ('application_version' if action == 'apply' else 'composition_version')] = 2 if direct else 4
        if action == 'connect':
            values['connection_version_contract'] = 1  # Existing closed compound schema.
        if direct:
            values.update(history_seed=str(uuid4()), created_at=values.get('created_at', time()))
        else:
            values['connection_id'] = str(uuid4())
        values.update(conflict_values(source, values['overhang_a_id'], values['overhang_b_id']))
        values.update(capture_selection(source, values))
    return {**values, KEY: dict(CONTEXT)}


def try_response(action, choices=None, *, version_id=None):
    from backend.api.part_source_bound_route import require_current
    from backend.core.part_command_errors import CommandContractError
    try:
        with state._lock:
            require_current()
            session = state._session()
            source = session.design
            if source is None or source.group_organization is None:
                return None
            if not ENABLED:
                raise HTTPException(409, detail={'code': 'organized_connections_not_enabled'})
            values = capture_inputs(source, action, choices or {}, version_id)
            revision = session.revision
        updated, report, entry, _ = create(values, expected_design_id=source.id, expected_revision=revision)
    except CommandContractError as error:
        raise HTTPException(422, detail=error.as_issue()) from error
    except ValueError as error:
        raise HTTPException(422, detail=str(error)) from error
    from backend.api.crud import _design_response, _design_response_with_geometry
    response = _design_response if action in {'create', 'patch', 'delete'} else _design_response_with_geometry
    return response(updated, report, normalize_legacy=False, full_feature_log=True,
                    preserve_feature_log_id=entry.id)


def owns_edit(design, entry):
    return (design.group_organization is not None and getattr(entry, 'op_kind', None) == 'overhang-bulk'
            and KEY in getattr(entry, 'params', {}))


def edit_response(index, body, *, sub_index=None):
    from backend.api.crud import _design_response_with_geometry
    from backend.api.part_connection_recipe_recording import edit
    if not ENABLED:
        raise HTTPException(409, detail={'code': 'organized_connections_not_enabled'})
    if sub_index is not None:
        raise HTTPException(422, detail='A connection recipe has no editable child.')
    candidate, report, entry, _ = edit(index, body.params,
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision,
        expected_feature_id=body.expected_feature_id)
    return _design_response_with_geometry(candidate, report, embed_straight=True,
        normalize_legacy=False, preserve_feature_log_id=entry.id, full_feature_log=True)
