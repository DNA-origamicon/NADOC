"""Explicit intent and ownership around the existing nanoparticle numerical kernels.

No optimized pose, sampled atoms or fit diagnostics are accepted as inputs.
V1 admits one source-free particle, one graft layer and at most four anchors.
"""
from math import isfinite
from typing import Annotated
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from backend.api import part_np_application_commands as application
from backend.api import part_nanoparticle_connection_commands as pending
from backend.api.part_nanoparticle_commands import GizmoMove
from backend.core.part_np_fitting_contract import EnginePin, FittingContractError, contract_defaults, validate_environment
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_scope_references import identity_index

KINDS = frozenset({'nanoparticle-attach-overhang', 'nanoparticle-bound-move', 'nanoparticle-connection-relax'})
MAX_ANCHORS = 4
Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
Time = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class _Public(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    nanoparticle_id: Id


class FitInputs(_Public):
    overhang_id: Id
    strand_id: Id
    fixed_center: StrictBool = False


class MoveInputs(_Public):
    gizmo_move: GizmoMove


class RelaxInputs(_Public):
    pass


class _Pinned(BaseModel):
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias='_proof_version')
    np_fitting_version: StrictInt = Field(ge=1, le=1)
    engine: EnginePin
    conjugation_id: Id
    applied_version_ids: list[Id] = Field(max_length=MAX_ANCHORS)
    applied_duplex_ids: list[Id] = Field(max_length=MAX_ANCHORS)

    @model_validator(mode='after')
    def unique_anchors(self):
        if (len(set(self.applied_version_ids)) != len(self.applied_version_ids)
                or len(set(self.applied_duplex_ids)) != len(self.applied_duplex_ids)
                or len(self.applied_version_ids) != len(self.applied_duplex_ids)):
            raise ValueError('Fitting anchors require unique aligned version/duplex identities')
        return self


class FitRequest(FitInputs, _Pinned):
    history_seed: Id
    version_id: Id
    duplex_id: Id
    created_at: Time

    @model_validator(mode='after')
    def canonical_seed(self):
        if str(UUID(self.history_seed)) != self.history_seed:
            raise ValueError('Fitting seed must be a canonical UUID')
        return self


class MoveRequest(MoveInputs, _Pinned):
    pass


class RelaxRequest(RelaxInputs, _Pinned):
    pass


def parse_inputs(kind, params):
    return {'nanoparticle-attach-overhang': FitInputs, 'nanoparticle-bound-move': MoveInputs,
            'nanoparticle-connection-relax': RelaxInputs}[kind].model_validate(params)


def parse_command(kind, params):
    kind = 'nanoparticle-bound-move' if kind == 'nanoparticle-patch' else kind
    return {'nanoparticle-attach-overhang': FitRequest, 'nanoparticle-bound-move': MoveRequest,
            'nanoparticle-connection-relax': RelaxRequest}[kind].model_validate(params)


def _unsupported(detail):
    raise FittingContractError(detail, code='unsupported_np_fitting_source')


def _reference(identity, detail, path, kind='nanoparticle'):
    raise ReferenceResolutionError(detail, code='invalid_selection', references=[{
        'kind': kind, 'identity': identity, 'parameter_path': path}])


def _source(design, nanoparticle_id):
    prepared = application._prepare_source(design)
    if len(design.nanoparticles) != 1 or design.nanoparticles[0].id != nanoparticle_id:
        _unsupported('Fitting v1 requires exactly the selected uncoated gold particle')
    if len(design.nanoparticle_conjugations) != 1:
        _unsupported('Fitting v1 requires one graft layer')
    owner = design.nanoparticle_conjugations[0]
    if owner.nanoparticle_id != nanoparticle_id or not 1 <= len(owner.surface_strands) <= 16:
        _unsupported('Fitting graft ownership exceeds the admitted scope')
    if (owner.requested_count != len(owner.surface_strands)
            or not isfinite(owner.spacer_nm) or not 0 <= owner.spacer_nm <= 1000
            or any(len({getattr(r, field) for r in owner.surface_strands}) != len(owner.surface_strands)
                   for field in ('strand_id', 'overhang_id'))):
        _unsupported('Fitting graft records require exact count and unique ownership')
    versions = sorted([v for v in design.nanoparticle_connection_versions if v.applied], key=lambda v: v.id)
    if len(versions) > MAX_ANCHORS or len(design.nanoparticle_connection_versions) > application.MAX_VERSIONS:
        _unsupported('Fitting v1 admits at most four applied anchors and 128 versions')
    if {v.duplex_id for v in versions} != {d.id for d in design.duplexes}:
        _unsupported('Fitting source has an unrelated or unowned duplex')
    if len({v.strand_id for v in versions}) != len(versions) or len({v.overhang_id for v in versions}) != len(versions):
        _unsupported('Fitting anchors have duplicate handle or target ownership')
    by_strand = {v.strand_id: v for v in versions}
    for version in versions:
        if version.nanoparticle_id != nanoparticle_id:
            _unsupported('Fitting anchor belongs to another particle')
        if version.residual_nm is not None and (not isfinite(version.residual_nm) or version.residual_nm < 0):
            _unsupported('Fitting source residual is invalid')
        # Reuse the exact structural restoration check. Relaxed status is an
        # admitted numerical result here; only those two status slots differ.
        application._restoration(design, prepared.index, owner,
            version.model_copy(update={'relaxed': False, 'residual_nm': None}))
    for record in owner.surface_strands:
        strand = pending._resolve(prepared.index, 'strand', record.strand_id, 'strand_id')
        endpoint = pending._resolve(prepared.index, 'overhang', record.overhang_id, 'strand_id')
        if (len(strand.domains) != 1 or strand.domains[0].helix_id != record.helix_id
                or endpoint.helix_id != record.helix_id or endpoint.strand_id != record.strand_id
                or not endpoint.auxiliary_endpoint or strand.domains[0].overhang_id != endpoint.id
                or endpoint.parent_overhang_id is not None or strand.domains[0].binds_overhang_id):
            _unsupported('Fitting surface strand/endpoint ownership is inconsistent')
        for vector in (record.site_local, record.sulfur_local_nm, record.backbone_attachment_local_nm):
            if vector is not None and (len(vector) != 3 or any(not isfinite(v) or abs(v) > 10000 for v in vector)):
                _unsupported('Fitting surface attachment coordinates exceed the finite work envelope')
        if record.bound_overhang_id is None:
            if record.strand_id in by_strand or not record.helix_id.startswith('__np__'):
                _unsupported('Fitting free carrier disagrees with its anchor ownership')
            helix = pending._resolve(prepared.index, 'helix', record.helix_id, 'strand_id')
            domain = strand.domains[0]
            if sorted((domain.start_bp, domain.end_bp)) != [helix.bp_start, helix.bp_start + helix.length_bp - 1]:
                _unsupported('Fitting free handle must own its complete radial carrier')
            if sum(r.helix_id == record.helix_id for r in owner.surface_strands) != 1:
                _unsupported('Fitting free carrier is shared by another handle')
        elif record.strand_id not in by_strand or by_strand[record.strand_id].overhang_id != record.bound_overhang_id:
            _unsupported('Fitting source contains an unowned legacy direct binding')
    return owner, versions


def prepare_command(kind, design, params, *, history_seed, created_at):
    body = parse_inputs(kind, params)
    owner, versions = _source(design, body.nanoparticle_id)
    inputs = {**body.model_dump(mode='json'), **contract_defaults(), 'conjugation_id': owner.id,
        'applied_version_ids': [v.id for v in versions], 'applied_duplex_ids': [v.duplex_id for v in versions]}
    if kind == 'nanoparticle-attach-overhang':
        inputs.update(history_seed=history_seed, version_id=str(uuid5(UUID(history_seed), 'version')),
            duplex_id=str(uuid5(UUID(history_seed), 'duplex')), created_at=created_at)
    validate_inputs(kind, design, inputs)
    return inputs


def validate_inputs(kind, design, params):
    command = parse_command(kind, params)
    owner, versions = _source(design, command.nanoparticle_id)
    if (owner.id != command.conjugation_id or [v.id for v in versions] != command.applied_version_ids
            or [v.duplex_id for v in versions] != command.applied_duplex_ids):
        _reference(command.nanoparticle_id, 'Fitting anchor or graft selection changed', ['applied_version_ids'])
    if isinstance(command, FitRequest):
        if len(versions) >= MAX_ANCHORS or len(design.nanoparticle_connection_versions) >= application.MAX_VERSIONS:
            _unsupported('Fitting requires room for one additional anchor')
        selected = [r for r in owner.surface_strands if r.strand_id == command.strand_id]
        if len(selected) != 1 or selected[0].bound_overhang_id is not None:
            _reference(command.strand_id, 'Fit requires an exact free graft handle', ['strand_id'], 'strand')
        targets = [o for o in design.overhangs if o.id == command.overhang_id and not o.auxiliary_endpoint]
        if len(targets) != 1:
            _reference(command.overhang_id, 'Fit requires an ordinary overhang', ['overhang_id'], 'overhang')
        index, _ = identity_index(design)
        if any(identity in {key[1] for key in index} for identity in (command.version_id, command.duplex_id)):
            _unsupported('Fitting output identity already exists')
    elif not versions or (isinstance(command, MoveRequest) and len(versions) != 1):
        _unsupported('Bound motion requires one anchor; collective relaxation requires at least one')
    return command


def evaluate(kind, design, params):
    command = validate_inputs(kind, design, params)
    validate_environment(command.engine)
    if isinstance(command, FitRequest):
        from backend.api.nanoparticle_attachment import attach_nanoparticle
        candidate, diagnostics = attach_nanoparticle(design, command.nanoparticle_id, command.overhang_id,
            strand_id=command.strand_id, fixed_center=command.fixed_center,
            identity_inputs={key: getattr(command, key) for key in ('version_id', 'duplex_id', 'created_at', 'history_seed')})
    elif isinstance(command, MoveRequest):
        from backend.core.nanoparticle import constrained_nanoparticle_move
        from backend.core.design_geometry import fitting_geometry
        version = next(v for v in design.nanoparticle_connection_versions if v.id == command.applied_version_ids[0])
        candidate, diagnostics = constrained_nanoparticle_move(design, command.nanoparticle_id, version,
            fitting_geometry(design), **command.gizmo_move.model_dump())
    else:
        from backend.core.nanoparticle_kinematics import solve_nanoparticle_anchors
        candidate, diagnostics = solve_nanoparticle_anchors(design, command.nanoparticle_id)
        if diagnostics['version_ids'] != command.applied_version_ids:
            _unsupported('The anchor solver did not resolve every selected version')
        residuals = diagnostics['per_anchor_residual_nm']
        candidate = candidate.copy_with(nanoparticle_connection_versions=[
            v.model_copy(update={'relaxed': True, 'residual_nm': residuals[v.id]}) if v.id in residuals else v
            for v in candidate.nanoparticle_connection_versions])
    validate_environment(command.engine)
    return candidate, diagnostics


def build(kind, design, params):
    return evaluate(kind, design, params)[0]


def dependencies(kind, params):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        command = parse_command(kind, params)
    except (ValueError, KeyError):
        return Dependencies(known=False)
    refs = {Resource('part', 'topology'), Resource('nanoparticle', command.nanoparticle_id),
            Resource('nanoparticle_conjugation', command.conjugation_id)}
    refs.update(Resource('nanoparticle_connection_version', x) for x in command.applied_version_ids)
    refs.update(Resource('duplex', x) for x in command.applied_duplex_ids)
    writes = set(refs)
    if isinstance(command, FitRequest):
        refs |= {Resource('strand', command.strand_id), Resource('overhang', command.overhang_id)}
        writes |= {Resource('nanoparticle_connection_version', command.version_id), Resource('duplex', command.duplex_id)}
    return Dependencies(frozenset(refs), frozenset(writes), barrier=True)
