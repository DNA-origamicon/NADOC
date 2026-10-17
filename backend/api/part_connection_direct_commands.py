"""Versioned direct Apply recipes over the shared native materializer.

No recovered geometry or restoration snapshot is accepted as a command input.
Restoration state belongs to an independently rebuilt producer prefix.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator

from backend.api import part_connection_application_commands as linker
from backend.core.feature_identity import identity_factory
from backend.core.part_operation_input import validate_operation_input

from backend.api.part_connection_owner_selection import OwnerSelection, dependency_reads

ACTION = 'connection-version-apply-direct'
_Id = linker._Id


class DirectSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    history_seed: _Id
    created_at: float = Field(ge=0, allow_inf_nan=False)
    conflict_connection_ids: list[_Id] = Field(max_length=linker.MAX_CONFLICTS)
    conflict_binding_ids: list[_Id] = Field(max_length=linker.MAX_CONFLICTS)
    conflict_duplex_ids: list[_Id] = Field(max_length=linker.MAX_CONFLICTS)
    conflict_version_ids: list[_Id] = Field(max_length=linker.MAX_CONFLICTS)

    @field_validator('history_seed')
    @classmethod
    def uuid_namespace(cls, value):
        UUID(value)
        return value

    @field_validator('conflict_connection_ids', 'conflict_binding_ids', 'conflict_duplex_ids', 'conflict_version_ids')
    @classmethod
    def unique(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Direct conflict selections must be unique')
        return value


class ApplyRequest(DirectSelection):
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias='_proof_version')
    direct_application_version: Annotated[StrictInt, Field(ge=1, le=1)]
    action: Literal['connection-version-apply-direct']
    version_id: _Id
    overhang_a_id: _Id
    overhang_b_id: _Id
    connection_type: Literal['root-to-root', 'end-to-root']

class ApplyRequestV2(ApplyRequest, OwnerSelection):
    direct_application_version: Annotated[StrictInt, Field(ge=2, le=2)]


def parse_command(params):
    validate_operation_input(params)
    marker = params.get("direct_application_version") if type(params) is dict else None
    model = ApplyRequestV2 if type(marker) is int and marker == 2 else ApplyRequest
    return model.model_validate(params)


def output_slots(body):
    identifier = identity_factory(body.history_seed)
    duplex = identifier('connection-duplex', [])
    return {('duplex', duplex), ('overhang_binding', identifier('connection-binding', [])),
            ('cluster', identifier('duplex-cluster', [duplex])),
            ('forced_ligation', identifier('duplex-ligation', [duplex]))}


def dependency_contract(params, *, topology):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        body = parse_command(params)
    except ValueError:
        return Dependencies(known=False)
    reads = {topology, Resource('connection_version', body.version_id),
             Resource('overhang', body.overhang_a_id), Resource('overhang', body.overhang_b_id)}
    for kind, field in [('overhang_connection', 'conflict_connection_ids'),
                        ('overhang_binding', 'conflict_binding_ids'), ('duplex', 'conflict_duplex_ids'),
                        ('connection_version', 'conflict_version_ids')]:
        reads.update(Resource(kind, identity) for identity in getattr(body, field))
    reads.update(dependency_reads(body))
    # Reserve conditional binding/ligation slots as potential writes: upstream
    # length edits may switch branches. The whole-topology barrier covers native
    # relocation/restoration, whose exact footprint depends on the rebuilt prefix.
    writes = {topology, *(Resource(kind, identity) for kind, identity in output_slots(body)),
              *(Resource('connection_version', identity) for identity in body.conflict_version_ids),
              Resource('overhang', body.overhang_a_id), Resource('overhang', body.overhang_b_id)}
    return Dependencies(frozenset(reads), frozenset(writes), barrier=True)


def build(design, params):
    from backend.api.part_connection_direct_ownership import prepare

    body = parse_command(params)
    restored, version = prepare(design, body)
    return materialize(restored, body, version)


def materialize(restored, body, version):
    from backend.api.connection_version_direct import materialize_direct
    from backend.api.part_connection_organization import observe_direct
    from backend.api.overhang_patch import OverhangPatchRequest, _build_overhang_patch
    from backend.api.routes_connection_versions import _cv_attach_pair, _cv_sequence_for_live_overhang
    from backend.core.sequences import overhang_dependent_strand_ids, reassign_strands

    a_id, b_id = body.overhang_a_id, body.overhang_b_id
    sequences = [_cv_sequence_for_live_overhang(restored, identity, sequence)
                 for identity, sequence in [(a_id, version.overhang_a_seq), (b_id, version.overhang_b_seq)]]
    for identity, sequence in zip((a_id, b_id), sequences, strict=True):
        if sequence:
            restored = _build_overhang_patch(restored, identity, OverhangPatchRequest(sequence=sequence))[0]
    attach_a, attach_b = _cv_attach_pair(body.connection_type)
    result = materialize_direct(restored, a_id, b_id, attach_a, attach_b, body.connection_type,
                                history_seed=body.history_seed, created_at=body.created_at)
    observe_direct(restored, result, output_slots(body))
    required = {slot for slot in output_slots(body) if slot[0] in {'duplex', 'cluster'}}
    present = {('duplex', item.id) for item in result.duplexes} | {
        ('cluster', item.id) for item in result.cluster_transforms}
    if not required <= present:
        linker._unsupported('Native direct construction could not resolve its complete placement owner')
    result = reassign_strands(result, overhang_dependent_strand_ids(result, [a_id, b_id]))
    selected = set(body.conflict_version_ids)
    result = result.copy_with(connection_versions=[item.model_copy(update={
        'applied': item.id == body.version_id,
        **({'overhang_a_seq': sequences[0]} if item.id == body.version_id and sequences[0] else {}),
        **({'overhang_b_seq': sequences[1]} if item.id == body.version_id and sequences[1] else {}),
    }) if item.id in selected else item for item in result.connection_versions])
    return result, None
