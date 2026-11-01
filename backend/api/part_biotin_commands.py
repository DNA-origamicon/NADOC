"""Bounded source-pinned biotin create/remove; existing geometry stays authoritative."""
from copy import deepcopy
from typing import Annotated, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from backend.api.part_streptavidin_commands import PDB_SHA256, PDB_SIZE, MAX_ASSET_ATOMS, MAX_ASSET_BONDS
from backend.core.part_biotin_contract import EnginePin, BiotinContractError, validate_environment
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import InputSource, EmbeddedResolver, verify

KIND = 'nanoparticle-biotin-dna'
MAX_SITES = 4
MAX_SEQUENCE = 32
Id = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]


class _Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    proof_version: Annotated[StrictInt, Field(ge=1, le=1)] = Field(alias='_proof_version')
    biotin_version: StrictInt = Field(ge=1, le=1)
    nanoparticle_id: Id


class CreateRequest(_Input):
    action: Literal['create']
    engine: EnginePin
    history_seed: Id
    tether_source: InputSource
    coating_source: InputSource
    site_count: StrictInt = Field(ge=1, le=MAX_SITES)
    sequence: str = Field(min_length=2, max_length=MAX_SEQUENCE, pattern='^[ACGT]+$')
    dna_per_strep: StrictInt = Field(ge=1, le=4)
    pocket: Literal['auto', 'A', 'B', 'C', 'D']
    linker_nm: Annotated[Number, Field(ge=1, le=10)]

    @model_validator(mode='after')
    def canonical_seed(self):
        if str(UUID(self.history_seed)) != self.history_seed:
            raise ValueError('Biotin identity seed must be a canonical UUID')
        return self


class OwnedRecord(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    strand_id: Id
    helix_id: Id
    tetramer_index: StrictInt = Field(ge=0, lt=MAX_SITES)
    chain: Literal['A', 'B', 'C', 'D']


class RemoveRequest(_Input):
    action: Literal['remove']
    owned: list[OwnedRecord] = Field(min_length=1, max_length=MAX_SITES * 4)


def parse_command(kind, params):
    if kind != KIND:
        raise ValueError('Unsupported biotin command')
    model = {'create': CreateRequest, 'remove': RemoveRequest}.get(params.get('action'))
    if model is None:
        raise ValueError('Biotin action must be create or remove')
    return model.model_validate(params)


def _unsupported(detail, code='unsupported_biotin_scope'):
    raise BiotinContractError(detail, code=code)


def _reference(identity, detail, path):
    raise ReferenceResolutionError(detail, code='invalid_selection', references=[{
        'kind': 'nanoparticle', 'identity': identity, 'parameter_path': path}])


def output_id(command, role, index, site):
    identity = str(uuid5(UUID(command.history_seed), f'{role}:{index}:{site}'))
    return '__strep_dna__' + identity if role == 'helix' else identity


def owned_records(particle):
    return [OwnedRecord.model_validate(record.model_dump(include={
        'strand_id', 'helix_id', 'tetramer_index', 'chain'})).model_dump() for record in particle.biotin_dna]


def _bounded_pose(pose, max_translation=10000):
    # Admission only: no normalization or geometry correction. This bounds the
    # physical segment sampling work of the unchanged native pocket search.
    import numpy as np
    matrix = pose.to_array()
    return (np.isfinite(matrix).all() and np.max(np.abs(matrix[:3, 3])) <= max_translation
        and np.allclose(matrix[3], [0., 0., 0., 1.], rtol=0., atol=1e-9)
        and np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), rtol=0., atol=1e-6)
        and abs(np.linalg.det(matrix[:3, :3]) - 1.) <= 1e-6)


def validate_inputs(kind, design, params, *, resolver=None):
    command = parse_command(kind, params)
    if len(design.nanoparticles) != 1 or design.nanoparticles[0].id != command.nanoparticle_id:
        _reference(command.nanoparticle_id, 'Biotin v1 requires exactly its selected coated particle', ['nanoparticle_id'])
    particle = design.nanoparticles[0]
    coating = particle.coating
    if particle.kind != 'gold_nanosphere' or particle.quantum_dot is not None or coating is None:
        _unsupported('Biotin v1 requires coated source-free gold')
    if not 5 <= particle.diameter_nm <= 100 or not _bounded_pose(particle.pose):
        _unsupported('Biotin particle diameter/pose exceeds its admitted range')
    if not 1 <= len(coating.poses) <= MAX_SITES:
        _unsupported('Biotin v1 admits one to four coating sites', 'source_limit')
    if len(coating.protein.atoms) > MAX_ASSET_ATOMS or len(coating.protein.bonds) > MAX_ASSET_BONDS:
        _unsupported('Biotin coating exceeds its atom/bond allowance', 'source_limit')
    if any(not _bounded_pose(pose, 100) for pose in coating.poses):
        _unsupported('Biotin coating poses must be bounded rigid transforms')
    from backend.core.models import Design
    baseline = Design()
    allowed = {'nanoparticles', 'metadata', 'lattice_type', 'dimensions'}
    if isinstance(command, RemoveRequest):
        allowed |= {'helices', 'strands', 'extensions'}
    if any(getattr(design, name) != getattr(baseline, name) for name in AUTHORING_FIELDS - allowed):
        _unsupported('Biotin v1 excludes other DNA, particles and coupled consumers')
    if isinstance(command, RemoveRequest):
        expected = [row.model_dump() for row in command.owned]
        if owned_records(particle) != expected:
            _reference(particle.id, 'Selected biotin ownership changed', ['owned'])
        sids, hids = {r.strand_id for r in command.owned}, {r.helix_id for r in command.owned}
        if len(sids) != len(expected) or len(hids) != len(expected):
            _unsupported('Biotin ownership is ambiguous')
        if {s.id for s in design.strands} != sids or {h.id for h in design.helices} != hids:
            _unsupported('Biotin deletion requires exact owned strands and carriers')
        if len(design.strands) != len(sids) or len(design.helices) != len(hids):
            _unsupported('Biotin owned identities repeat')
        for record in command.owned:
            strand = design.find_strand(record.strand_id)
            if len(strand.domains) != 1 or strand.domains[0].helix_id != record.helix_id:
                _unsupported('Biotin owned strand topology has changed')
        if len({e.id for e in design.extensions}) != len(design.extensions) or any(
               e.strand_id not in sids or e.id != '__biotin_teg__' + e.strand_id
               or e.modification != 'biotin' or e.end != 'five_prime' for e in design.extensions):
            _unsupported('Biotin deletion has foreign extension ownership')
        return command, particle, None
    if particle.biotin_dna or len(coating.poses) != command.site_count:
        _reference(particle.id, 'Biotin sites changed or already contain attached DNA', ['site_count'])
    for source in (command.tether_source, command.coating_source):
        if (source.sha256 != PDB_SHA256 or source.size_bytes != PDB_SIZE
                or source.format != 'pdb' or source.media_type != 'chemical/x-pdb'):
            _unsupported('Biotin v1 requires the complete pinned 1STP assembly source')
    resolve = resolver if resolver is not None else EmbeddedResolver({})
    raw = verify(command.tether_source, resolve(command.tether_source))
    verify(command.coating_source, resolve(command.coating_source))
    return command, particle, raw.decode('utf-8')


def build(kind, design, params, *, resolver=None):
    command, particle, text = validate_inputs(kind, design, params, resolver=resolver)
    result = deepcopy(design)
    selected = result.nanoparticles[0]
    if isinstance(command, RemoveRequest):
        result.helices, result.strands, result.extensions = [], [], []
        selected.biotin_dna, selected.oxdna_fixed_core = [], False
        return result
    validate_environment(command.engine)
    from backend.core.streptavidin import streptavidin_asset_from_text
    from backend.core.gold_strep_dna import build_dna_set
    from backend.core.biotin_extensions import ensure_biotin_extensions
    expected = streptavidin_asset_from_text(text, particle.coating.mode)
    if expected != particle.coating.protein:
        _unsupported('Applied coating atoms differ from their pinned original input')
    template = streptavidin_asset_from_text(text, 'biotin_tether')
    placed = build_dna_set(selected, command.sequence, command.pocket, command.linker_nm,
        command.dna_per_strep, result, template=template,
        identity_factory=lambda role, index, site: output_id(command, role, index, site))
    selected.biotin_dna = [r for r, _, _ in placed]
    selected.oxdna_fixed_core = False
    result.helices.extend(h for _, h, _ in placed)
    result.strands.extend(s for _, _, s in placed)
    ensure_biotin_extensions(result)
    validate_environment(command.engine)
    return result


def dependencies(kind, params):
    from backend.core.part_dependencies import Dependencies, Resource
    try:
        command = parse_command(kind, params)
    except ValueError:
        return Dependencies(known=False)
    topology, particle = Resource('part', 'topology'), Resource('nanoparticle', command.nanoparticle_id)
    reads, writes, sources = {topology, particle}, {topology, particle}, set()
    if isinstance(command, CreateRequest):
        sources = {Resource('input_source', source.sha256) for source in (command.tether_source, command.coating_source)}
        reads |= sources
        for index in range(command.site_count):
            for site in 'ABCD':
                for role in ('helix', 'strand'):
                    writes.add(Resource(role, output_id(command, role, index, site)))
    else:
        for record in command.owned:
            for role in ('helix', 'strand'):
                resource = Resource(role, getattr(record, role + '_id'))
                reads.add(resource)
                writes.add(resource)
    return Dependencies(frozenset(reads), frozenset(writes), barrier=True, imported_sources=frozenset(sources))
