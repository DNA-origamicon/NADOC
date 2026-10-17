"""Source-owned ordinary direct Apply; one native build and recording pass."""

from time import time
from uuid import uuid4

from fastapi import HTTPException

from backend.api import part_connection_application_commands as common
from backend.api import part_connection_direct_commands as command
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import MAX_OPERATION_NODES


def conflict_values(source, a_id, b_id):
    fields = [('conflict_connection_ids', 'overhang_connections'),
              ('conflict_binding_ids', 'overhang_bindings'),
              ('conflict_duplex_ids', 'duplexes'),
              ('conflict_version_ids', 'connection_versions')]
    if sum(len(getattr(source, collection)) for _, collection in fields) > MAX_OPERATION_NODES:
        common._unsupported('Direct application exceeds its conflict table allowance')
    pair = {a_id, b_id}
    return {field: [item.id for item in getattr(source, collection) if pair.intersection(
        (item.left.overhang_id, item.right.overhang_id) if collection == 'duplexes'
        else (item.overhang_a_id, item.overhang_b_id))] for field, collection in fields}


def try_record(version_id):
    from backend.api import state
    from backend.api.feature_recording import record_feature
    from backend.api.part_connection_direct_ownership import prepare
    from backend.api.part_source_bound_route import require_current

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
                if version.connection_type not in {'root-to-root', 'end-to-root'}:
                    return None
                state._assert_active_loadout_editable(source)
                if source.feature_log_cursor != -1 or source.feature_log_sub_cursor is not None:
                    raise HTTPException(409, detail='Return to the latest feature before Apply.')
                values = {'_proof_version': 1, 'direct_application_version': 1, 'action': command.ACTION,
                    'version_id': version.id, 'overhang_a_id': version.overhang_a_id,
                    'overhang_b_id': version.overhang_b_id, 'connection_type': version.connection_type,
                    'history_seed': str(uuid4()), 'created_at': time(),
                    **conflict_values(source, version.overhang_a_id, version.overhang_b_id)}
                body = command.parse_command(values)
                restored, selected = prepare(source, body)
            except CommandContractError as error:
                if error.code == 'unsupported_connection_application_source':
                    return None
                raise

            def native(design):
                require_current()
                if design is not source or session.design is not source:
                    raise HTTPException(409, detail='Direct application source changed before recording.')
                result, report = command.materialize(restored, body, selected)
                return result.copy_with(feature_log=list(design.feature_log)), report

            updated, report, entry = record_feature(session, 'overhang-bulk',
                f'Apply direct version {version.name or version.id[:8]}', values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == 'missing_reference' else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error


def try_record_connect(choices):
    from backend.api import state, part_connection_version_commands as pending
    from backend.api import part_connection_direct_composition as composition
    from backend.api.feature_recording import record_feature
    from backend.api.part_source_bound_route import require_current

    if choices.get('connection_type') not in {'root-to-root', 'end-to-root'}:
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
                    'action': composition.ACTION, 'direct_composition_version': 1,
                    'version_id': str(uuid4()), 'history_seed': str(uuid4()), 'created_at': time(),
                    **conflict_values(source, provisional.overhang_a_id, provisional.overhang_b_id)}
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
                'Create and connect direct version', values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == 'missing_reference' else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
