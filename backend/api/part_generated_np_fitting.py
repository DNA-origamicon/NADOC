"""Explicit fitting intent for the bounded generated multi-particle graph.

V2 retains the complete generated input scope for obstacle evaluation. It uses
the ordinary native fit kernel; neither fitted poses nor diagnostic results are
command inputs. V1's smaller ordinary-edit contract is unchanged.
"""
from math import isfinite
from typing import Annotated, Literal
from uuid import uuid4, uuid5, UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from backend.api import part_np_application_commands as application
from backend.api import part_nanoparticle_connection_commands as pending
from backend.api.part_np_fitting_commands import Id, FitRequest, _unsupported, _reference
from backend.core.part_np_fitting_contract import contract_defaults, validate_environment
from backend.core.part_scope_references import COLLECTIONS, identity_index, referenced_resources


class PendingFit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    nanoparticle_id: Id
    strand_id: Id
    overhang_id: Id


class GeneratedFit(FitRequest):
    np_fitting_version: Literal[2]
    alignment_rotation: list[Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(min_length=4, max_length=4)
    place_new_graft: StrictBool
    pending_connections: list[PendingFit] = Field(max_length=11)
    applied_version_ids: list[Id] = Field(max_length=12)
    applied_duplex_ids: list[Id] = Field(max_length=12)


def source(design):
    from backend.core.part_verification_capture import admit

    admit(design, preserve_entry_types=True)  # Existing private 30k-node/2MB envelope.
    if not 2 <= len(design.nanoparticles) <= 4 or not 1 <= len(design.nanoparticle_conjugations) <= 12:
        _unsupported('Generated fitting requires two to four particles and at most twelve graft layers')
    if any(not pending._source_free(p) for p in design.nanoparticles):
        _unsupported('Generated fitting requires source-free uncoated gold')
    if any(getattr(design, name) for name in ('protein_assets', 'protein_attachments',
            'photoproduct_junctions', 'nucleotide_transforms', 'flexible_connections')):
        _unsupported('Generated fitting source contains unsupported molecular ownership')
    if any(h.native_residues or h.native_source for h in design.helices):
        _unsupported('Generated fitting does not admit imported residue geometry')
    if sum(abs(d.end_bp-d.start_bp)+1 for s in design.strands for d in s.domains) > 50_000:
        _unsupported('Generated fitting exceeds the existing proof nucleotide allowance')
    index, _ = identity_index(design)
    for field in COLLECTIONS:
        for item in getattr(design, field):
            referenced_resources(item)
    versions = sorted((v for v in design.nanoparticle_connection_versions if v.applied), key=lambda v: v.id)
    if len(versions) > 12 or len(design.nanoparticle_connection_versions) > application.MAX_VERSIONS:
        _unsupported('Generated fitting exceeds twelve active anchors or 128 versions')
    if {v.duplex_id for v in versions} != {d.id for d in design.duplexes}:
        _unsupported('Generated fitting source contains an unrelated duplex')
    owners = {r.strand_id: c for c in design.nanoparticle_conjugations for r in c.surface_strands}
    records = [r for c in design.nanoparticle_conjugations for r in c.surface_strands]
    if (len(records) > 128 or len(owners) != len(records)
            or len({r.overhang_id for r in records}) != len(records)
            or len({v.strand_id for v in versions}) != len(versions)
            or len({v.overhang_id for v in versions}) != len(versions)):
        _unsupported('Generated graft handles and anchors must have unique bounded ownership')
    by_strand = {v.strand_id: v for v in versions}
    for owner in design.nanoparticle_conjugations:
        pending._resolve(index, 'nanoparticle', owner.nanoparticle_id, 'nanoparticle_id')
        if owner.requested_count != len(owner.surface_strands) or not isfinite(owner.spacer_nm):
            _unsupported('Generated graft count or spacer is invalid')
        for record in owner.surface_strands:
            strand = pending._resolve(index, 'strand', record.strand_id, 'strand_id')
            endpoint = pending._resolve(index, 'overhang', record.overhang_id, 'strand_id')
            if (len(strand.domains) != 1 or strand.is_reference
                    or strand.domains[0].helix_id != record.helix_id
                    or strand.domains[0].overhang_id != endpoint.id
                    or endpoint.helix_id != record.helix_id or endpoint.strand_id != strand.id
                    or not endpoint.auxiliary_endpoint or endpoint.parent_overhang_id is not None):
                _unsupported('Generated graft handle ownership is inconsistent')
            version = by_strand.get(strand.id)
            if record.bound_overhang_id is None:
                helix = pending._resolve(index, 'helix', record.helix_id, 'strand_id')
                if (version is not None or not helix.id.startswith('__np__')
                        or sorted((strand.domains[0].start_bp, strand.domains[0].end_bp))
                        != [helix.bp_start, helix.bp_start + helix.length_bp - 1]):
                    _unsupported('Generated free handle does not own its radial carrier')
            elif (version is None or version.nanoparticle_id != owner.nanoparticle_id
                    or version.overhang_id != record.bound_overhang_id):
                _unsupported('Generated handle has no exact applied version')
            else:
                application._restoration(design, index, owner,
                    version.model_copy(update={'relaxed': False, 'residual_nm': None}))
    if set(by_strand) - owners.keys():
        _unsupported('Generated anchor has no graft owner')
    return index, owners, versions


def validate(design, params):
    command = GeneratedFit.model_validate(params)
    index, owners, versions = source(design)
    owner = owners.get(command.strand_id)
    if (owner is None or owner.id != command.conjugation_id or owner.nanoparticle_id != command.nanoparticle_id
            or [v.id for v in versions] != command.applied_version_ids
            or [v.duplex_id for v in versions] != command.applied_duplex_ids):
        _reference(command.strand_id, 'Generated fit source selection changed', ['strand_id'], 'strand')
    selections = [PendingFit(nanoparticle_id=command.nanoparticle_id,
        strand_id=command.strand_id, overhang_id=command.overhang_id), *command.pending_connections]
    if len({p.strand_id for p in selections}) != len(selections) or len({p.overhang_id for p in selections}) != len(selections):
        _unsupported('Generated pending attachments must select unique handles and targets')
    for selected in selections:
        graft = owners.get(selected.strand_id)
        target = pending._resolve(index, 'overhang', selected.overhang_id, 'overhang_id')
        if (graft is None or graft.nanoparticle_id != selected.nanoparticle_id or target.auxiliary_endpoint
                or any(r.bound_overhang_id is not None for r in graft.surface_strands if r.strand_id == selected.strand_id)):
            _reference(selected.strand_id, 'Generated fit requires an exact free graft and ordinary target', ['pending_connections'], 'strand')
    if abs(sum(v*v for v in command.alignment_rotation) - 1) > 1e-10:
        _unsupported('Generated fitting requires a unit authored alignment quaternion')
    if any(identity in {key[1] for key in index} for identity in (command.version_id, command.duplex_id)):
        _unsupported('Generated fitting output identity already exists')
    if len(versions) >= 12:
        _unsupported('Generated fitting requires room for the new anchor')
    return command


def prepare(design, item, *, alignment_rotation, place_new_graft, pending_connections):
    _, owners, versions = source(design)
    seed = str(uuid4())
    params = {**contract_defaults(), 'np_fitting_version': 2,
        'nanoparticle_id': item['particle_id'], 'strand_id': item['strand_id'], 'overhang_id': item['overhang_id'],
        'fixed_center': True, 'conjugation_id': owners[item['strand_id']].id,
        'applied_version_ids': [v.id for v in versions], 'applied_duplex_ids': [v.duplex_id for v in versions],
        'alignment_rotation': alignment_rotation, 'place_new_graft': place_new_graft,
        'pending_connections': [{'nanoparticle_id': p['particle_id'], 'strand_id': p['strand_id'],
                                 'overhang_id': p['overhang_id']} for p in pending_connections],
        'history_seed': seed, 'version_id': str(uuid5(UUID(seed), 'version')),
        'duplex_id': str(uuid5(UUID(seed), 'duplex')), 'created_at': 0.0}
    validate(design, params)
    return params


def evaluate(design, params):
    from scipy.spatial.transform import Rotation
    from backend.api.nanoparticle_attachment import attach_nanoparticle

    command = validate(design, params)
    validate_environment(command.engine)
    result = attach_nanoparticle(design, command.nanoparticle_id, command.overhang_id,
        strand_id=command.strand_id, fixed_center=command.fixed_center,
        frame=Rotation.from_quat(command.alignment_rotation).as_matrix(), place_new_graft=command.place_new_graft,
        pending_connections=[p.model_dump() for p in command.pending_connections],
        identity_inputs={key: getattr(command, key) for key in ('version_id', 'duplex_id', 'created_at', 'history_seed')})
    validate_environment(command.engine)
    return result


def teardown_inputs(design, identity):
    index, owners, _ = source(design)
    version = pending._resolve(index, 'nanoparticle_connection_version', identity, 'version_id')
    owner = owners[version.strand_id]
    record = next(r for r in owner.surface_strands if r.strand_id == version.strand_id)
    return {'_proof_version': 1, 'nanoparticle_connection_version': 1,
        'nanoparticle_application_version': 3, 'history_seed': str(uuid4()),
        'nanoparticle_id': version.nanoparticle_id, 'conjugation_id': owner.id,
        'strand_id': version.strand_id, 'overhang_id': version.overhang_id,
        'handle_overhang_id': record.overhang_id, 'version_id': version.id,
        'prior_duplex_id': version.duplex_id, 'conflict_version_ids': [v.id for v in design.nanoparticle_connection_versions
            if v.id != identity and (v.strand_id == version.strand_id or v.overhang_id == version.overhang_id)],
        'applied': False}
