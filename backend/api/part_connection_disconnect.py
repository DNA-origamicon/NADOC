"""Explicit native pair teardown plus saved-version disposition, one transaction."""

from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import ConfigDict, Field, StrictBool, StrictInt, field_validator

from backend.api import part_connection_application_commands as common
from backend.api import part_connection_version_commands as metadata
from backend.api.part_connection_owner_selection import OwnerSelection, capture_selection, dependency_reads
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_operation_input import validate_operation_input

ACTION = 'connection-version-disconnect'
ENABLED = False


class DisconnectRequest(OwnerSelection, common.DirectConflicts):
    model_config = ConfigDict(extra='forbid', strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias='_proof_version')
    connection_disconnect_version: Annotated[StrictInt, Field(ge=1, le=1)]
    action: Literal['connection-version-disconnect']
    version_id: common._Id
    overhang_a_id: common._Id
    overhang_b_id: common._Id
    connection_type: metadata._Type
    delete_version: StrictBool
    conflict_connection_ids: list[common._Id] = Field(max_length=common.MAX_CONFLICTS)
    conflict_version_ids: list[common._Id] = Field(max_length=common.MAX_CONFLICTS)

    @field_validator('conflict_connection_ids', 'conflict_version_ids')
    @classmethod
    def unique(cls, values):
        if len(values) != len(set(values)):
            raise ValueError('Disconnect references must be unique')
        return values


def parse_command(params):
    validate_operation_input(params)
    return DisconnectRequest.model_validate(params)


def dependency_contract(params, *, topology):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        body = parse_command(params)
    except ValueError:
        return Dependencies(known=False)
    reads = {topology, Resource('overhang', body.overhang_a_id), Resource('overhang', body.overhang_b_id),
             Resource('connection_version', body.version_id), *dependency_reads(body)}
    for kind, field in [('overhang_connection', 'conflict_connection_ids'), ('overhang_binding', 'conflict_binding_ids'),
                        ('duplex', 'conflict_duplex_ids'), ('connection_version', 'conflict_version_ids')]:
        reads.update(Resource(kind, identity) for identity in getattr(body, field))
    return Dependencies(frozenset(reads), frozenset(reads), barrier=True)


def prepare(design, body):
    from backend.api.part_connection_direct_ownership import prepare_replacement
    restored, _, _, _ = prepare_replacement(design, body, slots=set(), slot_path='version_id',
                                            qualify_targets=False, pair_only=True)
    selected = set(body.conflict_version_ids)
    return restored.copy_with(connection_versions=[v.model_copy(update={'applied': False})
        if v.id in selected else v for v in restored.connection_versions
        if not (body.delete_version and v.id == body.version_id)])


def build(design, params):
    return prepare(design, parse_command(params)), None


def capture_inputs(source, version, *, delete_version):
    from backend.api.part_connection_direct_recording import conflict_values
    values = {'_proof_version': 1, 'connection_disconnect_version': 1, 'action': ACTION,
              'version_id': version.id, 'overhang_a_id': version.overhang_a_id,
              'overhang_b_id': version.overhang_b_id, 'connection_type': version.connection_type,
              'delete_version': delete_version,
              **conflict_values(source, version.overhang_a_id, version.overhang_b_id, pair_only=True)}
    values.update(capture_selection(source, values))
    return values


def record(version_id, *, delete_version=False):
    from backend.api import state
    from backend.api.feature_recording import record_feature
    from backend.api.part_source_bound_route import require_current
    if not ENABLED:
        raise HTTPException(404, detail='Native connection disconnection is not enabled.')
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
                raise HTTPException(409, detail='Return to the latest feature before disconnecting.')
            version = common._route_version(source, version_id)
            values = capture_inputs(source, version, delete_version=delete_version)
            result = prepare(source, parse_command(values))

            def native(design):
                require_current()
                if design is not source or session.design is not source:
                    raise HTTPException(409, detail='Connection source changed before disconnection.')
                return result.copy_with(feature_log=list(design.feature_log)), None

            updated, report, entry = record_feature(session, 'overhang-bulk',
                'Disconnect and delete version' if delete_version else 'Unapply connection version', values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == 'missing_reference' else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
