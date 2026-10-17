"""Source-owned direct and linker-v3 recording; one native build and undo."""

from time import time
from uuid import uuid4

from fastapi import HTTPException

from backend.api import part_connection_application_commands as common
from backend.api import part_connection_direct_commands as command
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_NODES


def conflict_values(source, a_id, b_id, *, pair_only=False):
    from backend.api.connection_version_teardown import matches_endpoints
    fields = [('conflict_connection_ids', 'overhang_connections'),
              ('conflict_binding_ids', 'overhang_bindings'),
              ('conflict_duplex_ids', 'duplexes'),
              ('conflict_version_ids', 'connection_versions')]
    if sum(len(getattr(source, collection)) for _, collection in fields) > MAX_OPERATION_NODES:
        common._unsupported('Direct application exceeds its conflict table allowance')
    pair = {a_id, b_id}
    return {field: [item.id for item in getattr(source, collection)
                   if matches_endpoints(item, pair, pair_only=pair_only)] for field, collection in fields}


def try_record(version_id, *, linker_version=None, owner_selection=False):
    from backend.api import state
    from backend.api.feature_recording import record_feature
    from backend.api.part_connection_direct_ownership import prepare
    from backend.api.part_source_bound_route import require_current

    if linker_version is not None and (type(linker_version) is not int or linker_version not in (3, 4)):
        raise ValueError('Only linker v3/v4 uses native restoration recording')
    owner_selection = owner_selection or linker_version == 4
    allowed = common.supported_types(linker_version) if linker_version else {'root-to-root', 'end-to-root'}
    try:
        with state._lock:
            require_current()
            state._require_compatibility_write('finite_connection_apply')
            session = state._session()
            source = session.design
            if source is None:
                raise HTTPException(404, detail='No active design.')
            try:
                version = common._route_version(source, version_id)
                if version.connection_type not in allowed:
                    return None
                state._assert_active_loadout_editable(source)
                if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
                    raise HTTPException(409, detail='Return to the latest feature before Apply.')
                values = {'_proof_version': 1, 'direct_application_version': 2 if owner_selection else 1, 'action': command.ACTION,
                    'version_id': version.id, 'overhang_a_id': version.overhang_a_id,
                    'overhang_b_id': version.overhang_b_id, 'connection_type': version.connection_type,
                    'history_seed': str(uuid4()), 'created_at': time(),
                    **conflict_values(source, version.overhang_a_id, version.overhang_b_id)}
                if owner_selection:
                    from backend.api.part_connection_owner_selection import capture_selection
                    values.update(capture_selection(source, values))
                if linker_version:
                    from backend.api.part_connection_linker_replacement import prepare as prepare_linker
                    values.pop('history_seed')
                    values.pop('created_at')
                    values.pop('direct_application_version')
                    values.update(action=common.ACTION, connection_application_version=linker_version, connection_id=str(uuid4()))
                    body = common.parse_command(values)
                    prepared = prepare_linker(source, body)
                    materialize = common._materialize
                else:
                    body = command.parse_command(values)
                    restored, selected = prepare(source, body)
                    prepared = restored, body, selected
                    materialize = command.materialize
            except CommandContractError as error:
                if error.code == 'unsupported_connection_application_source':
                    return None
                raise

            def native(design):
                require_current()
                if design is not source or session.design is not source:
                    raise HTTPException(409, detail='Direct application source changed before recording.')
                result, report = materialize(*prepared)
                return result.copy_with(feature_log=list(design.feature_log)), report

            updated, report, entry = record_feature(session, 'overhang-bulk',
                f'Apply version {version.name or version.id[:8]}', values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == 'missing_reference' else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error


def try_record_connect(choices, *, linker_version=None, owner_selection=False):
    from backend.api import state, part_connection_version_commands as pending
    from backend.api import part_connection_direct_composition as composition
    from backend.api.feature_recording import record_feature
    from backend.api.part_source_bound_route import require_current

    if linker_version is not None and (type(linker_version) is not int or linker_version not in (3, 4)):
        raise ValueError('Only linker v3/v4 uses native restoration recording')
    if linker_version:
        from backend.api import part_connection_composition_commands as composition
    owner_selection = owner_selection or linker_version == 4
    allowed = common.supported_types(linker_version) if linker_version else {'root-to-root', 'end-to-root'}
    if choices.get('connection_type') not in allowed:
        return None
    try:
        with state._lock:
            require_current()
            state._require_compatibility_write('finite_connection_apply')
            session = state._session()
            source = session.design
            if source is None:
                raise HTTPException(404, detail='No active design.')
            state._assert_active_loadout_editable(source)
            if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
                raise HTTPException(409, detail='Return to the latest feature before Connect.')
            inventory = pending._inventory(source)
            provisional = pending.parse_command({
                '_proof_version': 1, 'connection_version_contract': 1, 'action': pending.CREATE,
                'version_id': 'pending', 'created_at': 0.0, 'name': (choices.get('name') or '').strip(),
                'overhang_a_id': choices.get('overhang_a_id'), 'overhang_b_id': choices.get('overhang_b_id'),
                'connection_type': choices.get('connection_type'),
                'overhang_a_seq': choices.get('overhang_a_seq'), 'overhang_b_seq': choices.get('overhang_b_seq'),
                'bridge_seq': choices.get('bridge_seq'),
                'bridge_length': max(0, int(choices.get('bridge_length') or 0)), 'applied': False,
            })
            pending._select(source, provisional, inventory)
            try:
                values = {**provisional.model_dump(by_alias=True),
                    'action': composition.ACTION, 'direct_composition_version': 2 if owner_selection else 1,
                    'version_id': str(uuid4()), 'history_seed': str(uuid4()), 'created_at': time(),
                    **conflict_values(source, provisional.overhang_a_id, provisional.overhang_b_id)}
                if owner_selection:
                    from backend.api.part_connection_owner_selection import capture_selection
                    values.update(capture_selection(source, values))
                if linker_version:
                    values.pop('history_seed')
                    values.pop('direct_composition_version')
                    values.update(connection_composition_version=linker_version, connection_id=str(uuid4()))
                prepared = composition.prepare(source, composition.parse_command(values))
            except CommandContractError as error:
                if error.code == 'unsupported_connection_application_source':
                    return None
                raise

            def native(design):
                require_current()
                if design is not source or session.design is not source:
                    raise HTTPException(409, detail='Direct Connect source changed before recording.')
                result, report = composition.materialize(prepared)
                return result.copy_with(feature_log=list(design.feature_log)), report

            updated, report, entry = record_feature(session, 'overhang-bulk',
                'Create and connect version', values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == 'missing_reference' else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
