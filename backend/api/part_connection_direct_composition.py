"""Closed first-time direct Connect: definition plus materialization, one feature."""

from typing import Annotated, Literal

from pydantic import Field, StrictInt, model_validator

from backend.api import part_connection_direct_commands as direct
from backend.api import part_connection_version_commands as pending
from backend.core.part_operation_input import validate_operation_input

ACTION = 'connection-version-connect-direct'


class ConnectRequest(pending.CreateRequest, direct.DirectSelection):
    action: Literal['connection-version-connect-direct']
    direct_composition_version: Annotated[StrictInt, Field(ge=1, le=1)]
    connection_type: Literal['root-to-root', 'end-to-root']

    @model_validator(mode='after')
    def old_conflicts_only(self):
        if self.version_id in self.conflict_version_ids:
            raise ValueError('A new direct version cannot be an old conflict')
        if len(self.conflict_version_ids) >= direct.linker.MAX_CONFLICTS:
            raise ValueError('Direct Connect conflicts exceed the Apply allowance')
        return self


def parse_command(params):
    validate_operation_input(params)
    return ConnectRequest.model_validate(params)


def _apply_body(body):
    values = body.model_dump(by_alias=True)
    values.update(action=direct.ACTION, direct_application_version=1,
                  conflict_version_ids=[*body.conflict_version_ids, body.version_id])
    fields = {'_proof_version' if field == 'proof_version' else field for field in direct.ApplyRequest.model_fields}
    return direct.parse_command({field: values[field] for field in fields})


def dependency_contract(params, *, topology):
    from backend.core.part_dependencies import Dependencies, Resource

    try:
        body = parse_command(params)
    except ValueError:
        return Dependencies(known=False)
    contract = direct.dependency_contract(_apply_body(body).model_dump(by_alias=True), topology=topology)
    return Dependencies(contract.reads - {Resource('connection_version', body.version_id)},
                        contract.writes, barrier=True)


def prepare(design, body):
    from backend.api.part_connection_direct_ownership import prepare as prepare_apply

    values = body.model_dump(by_alias=True)
    fields = {'_proof_version' if field == 'proof_version' else field for field in pending.CreateRequest.model_fields}
    definition = {field: values[field] for field in fields}
    definition['action'] = pending.CREATE
    staged = pending.build(design, definition)
    request = _apply_body(body)
    restored, version = prepare_apply(staged, request)
    return restored, request, version


def materialize(prepared):
    return direct.materialize(*prepared)


def build(design, params):
    return materialize(prepare(design, parse_command(params)))
