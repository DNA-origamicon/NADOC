"""Closed versioned Connect composition: pending definition then native Apply.

A single registered feature, never an arbitrary command batch. Builders return
one candidate; the caller owns exactly one reconciliation/recording transaction.
Saved finite Apply v1 and the molecular materializer remain unchanged.
"""
from time import time
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import Field, StrictInt, model_validator

from backend.api import part_connection_version_commands as pending
from backend.api import part_connection_application_commands as application
from backend.core.part_operation_input import validate_operation_input

from backend.api.part_connection_owner_selection import OwnerSelection, dependency_reads

ACTION = 'connection-version-connect-linker'


class ConnectRequest(pending.CreateRequest):
    action: Literal['connection-version-connect-linker']
    connection_composition_version: Annotated[StrictInt, Field(ge=1, le=1)]
    connection_type: application._FiniteType
    connection_id: Annotated[str, Field(strict=True, min_length=1, max_length=246)]
    conflict_connection_ids: list[application._Id] = Field(max_length=application.MAX_CONFLICTS)
    conflict_version_ids: list[application._Id] = Field(max_length=application.MAX_CONFLICTS)

    @model_validator(mode='after')
    def old_conflicts_only(self):
        for items in (self.conflict_connection_ids, self.conflict_version_ids):
            if len(set(items)) != len(items):
                raise ValueError('Connect conflict selections must be unique')
        if self.version_id in self.conflict_version_ids:
            raise ValueError('A newly created version cannot be an old conflict')
        # Application includes this new version in the existing shared bound.
        if len(self.conflict_version_ids) >= application.MAX_CONFLICTS:
            raise ValueError('Connect version conflicts exceed the application allowance')
        return self


class ConnectRequestV2(ConnectRequest):
    connection_composition_version: Annotated[StrictInt, Field(ge=2, le=2)]
    connection_type: application._FiniteType | application._IndirectType


class ConnectRequestV3(ConnectRequestV2, application.DirectConflicts):
    connection_composition_version: Annotated[StrictInt, Field(ge=3, le=3)]


class ConnectRequestV4(ConnectRequestV3, OwnerSelection):
    connection_composition_version: Annotated[StrictInt, Field(ge=4, le=4)]


def parse_command(params):
    validate_operation_input(params)
    if type(params) is not dict:
        raise ValueError("Native connection inputs require an object")
    marker = params.get("connection_composition_version")
    model = {2: ConnectRequestV2, 3: ConnectRequestV3, 4: ConnectRequestV4}.get(marker, ConnectRequest) if type(marker) is int else ConnectRequest
    return model.model_validate(params)


def dependency_contract(params, *, topology):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        command = parse_command(params)
    except ValueError:
        return Dependencies(known=False)
    versions = {Resource('connection_version', identity) for identity in command.conflict_version_ids}
    reads = {topology, Resource('overhang', command.overhang_a_id),
             Resource('overhang', command.overhang_b_id), *versions,
             *(Resource('overhang_connection', identity) for identity in command.conflict_connection_ids)}
    if command.connection_composition_version >= 3:
        reads.update(Resource('overhang_binding', identity) for identity in command.conflict_binding_ids)
        reads.update(Resource('duplex', identity) for identity in command.conflict_duplex_ids)
    reads.update(dependency_reads(command))
    prefix = f'__lnk__{command.connection_id}'
    suffixes = ('a', 'b') if 'dsdna' in command.connection_type else ('s',)
    writes = {topology, Resource('connection_version', command.version_id), *versions,
              Resource('overhang_connection', command.connection_id),
              *(Resource('strand', f'{prefix}__{suffix}') for suffix in suffixes)}
    if command.connection_type not in application.INDIRECT_TYPES:
        writes.add(Resource('helix', prefix))
    return Dependencies(frozenset(reads), frozenset(writes), barrier=True)


def _stage(design, body):
    """Bound metadata before copying; one application source inventory."""
    values = body.model_dump(by_alias=True)
    definition = {key: values[key] for key in pending.CreateRequest.model_fields
                  if key != 'proof_version'}
    definition.update(_proof_version=1, action=pending.CREATE)
    return pending.build(design, definition)


def _bind(staged, body, index=None):
    request = application.parse_command({
        '_proof_version': 1, 'connection_application_version': body.connection_composition_version,
        'action': application.ACTION, 'version_id': body.version_id,
        'overhang_a_id': body.overhang_a_id, 'overhang_b_id': body.overhang_b_id,
        'connection_type': body.connection_type, 'connection_id': body.connection_id,
        'conflict_connection_ids': body.conflict_connection_ids,
        'conflict_version_ids': [*body.conflict_version_ids, body.version_id],
        **({'direct_owner_seeds': body.direct_owner_seeds} if body.connection_composition_version == 4 else {}),
        **({'conflict_binding_ids': body.conflict_binding_ids, 'conflict_duplex_ids': body.conflict_duplex_ids}
           if body.connection_composition_version >= 3 else {}),
    })
    if body.connection_composition_version >= 3:
        from backend.api.part_connection_linker_replacement import prepare
        return prepare(staged, request)
    selected, removed = application._select_inputs(staged, request, index)
    application._check_outputs(staged, request, index, removed)
    return staged, request, selected


def prepare(design, body):
    staged = _stage(design, body)
    return _bind(staged, body, None if body.connection_composition_version >= 3 else application._source_index(staged))


def materialize(prepared):
    return application._materialize(*prepared)


def build(design, params):
    return materialize(prepare(design, parse_command(params)))


def try_record(choices, *, contract_version=1):
    """Private ordinary adapter; unsupported scope falls back before native work.

    The public rollout stays disabled pending desktop and responsiveness
    qualification. HTTP acquisition is bound by ConnectRoute. No extra whole-design clone or proof runs on this path.
    """
    from fastapi import HTTPException
    from backend.api import state
    from backend.api.feature_recording import record_feature
    from backend.api.part_source_bound_route import require_current
    from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError

    if type(contract_version) is int and contract_version in (3, 4):
        from backend.api.part_connection_direct_recording import try_record_connect
        return try_record_connect(choices, linker_version=contract_version)
    if choices.get('connection_type') not in application.supported_types(contract_version):
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
            # Reuse bounded endpoint/metadata admission before ID/time allocation.
            inventory = pending._inventory(source)
            provisional = pending.parse_command({
                '_proof_version': 1, 'connection_version_contract': 1, 'action': pending.CREATE,
                'version_id': 'pending', 'created_at': 0.0,
                'name': (choices.get('name') or '').strip(),
                'overhang_a_id': choices.get('overhang_a_id'), 'overhang_b_id': choices.get('overhang_b_id'),
                'connection_type': choices.get('connection_type'),
                'overhang_a_seq': choices.get('overhang_a_seq'), 'overhang_b_seq': choices.get('overhang_b_seq'),
                'bridge_seq': choices.get('bridge_seq'),
                'bridge_length': max(0, int(choices.get('bridge_length') or 0)), 'applied': False,
            })
            pending._select(source, provisional, inventory)
            values = provisional.model_dump(by_alias=True)
            values.update(action=ACTION, connection_composition_version=contract_version,
                version_id=str(uuid4()), created_at=time(), connection_id=str(uuid4()),
                conflict_version_ids=[], conflict_connection_ids=[])
            try:
                staged = _stage(source, parse_command(values))
                index = application._source_index(staged)
                endpoints = {provisional.overhang_a_id, provisional.overhang_b_id}
                values.update(
                    conflict_version_ids=[v.id for v in source.connection_versions
                        if endpoints.intersection((v.overhang_a_id, v.overhang_b_id))],
                    conflict_connection_ids=[c.id for c in source.overhang_connections
                        if endpoints.intersection((c.overhang_a_id, c.overhang_b_id))])
                if (len(values['conflict_version_ids']) >= application.MAX_CONFLICTS
                        or len(values['conflict_connection_ids']) > application.MAX_CONFLICTS):
                    return None
                prepared = _bind(staged, parse_command(values), index)
            except CommandContractError as error:
                if error.code == 'unsupported_connection_application_source':
                    return None
                raise

            def native(design):
                require_current()
                if session.design is not source or design is not source:
                    raise HTTPException(409, detail='Connect source changed before recording.')
                result, report = materialize(prepared)
                return result.copy_with(feature_log=list(design.feature_log)), report

            updated, report, entry = record_feature(session, 'overhang-bulk', 'Create and connect', values, native)
            return source, updated, report, entry
    except ReferenceResolutionError as error:
        raise HTTPException(404 if error.code == 'missing_reference' else 422, detail=error.as_issue()) from error
    except (CommandContractError, ValueError) as error:
        raise HTTPException(422, detail=error.as_issue() if isinstance(error, CommandContractError) else str(error)) from error
