"""Bind ordinary biotin choices inside the existing explicit evaluation job."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.api import part_biotin_commands as commands
from backend.api.part_streptavidin_commands import PDB_SHA256, PDB_SIZE
from backend.core.part_biotin_contract import contract_defaults
from backend.core.part_input_sources import InputSource, EmbeddedResolver


class _Public(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    nanoparticle_id: commands.Id


class CreateRequest(_Public):
    action: Literal['create']
    sequence: str = Field(min_length=2, max_length=commands.MAX_SEQUENCE, pattern='^[ACGT]+$')
    dna_per_strep: StrictInt = Field(default=1, ge=1, le=4)
    pocket: Literal['auto', 'A', 'B', 'C', 'D'] = 'auto'
    linker_nm: commands.Number = Field(default=1.8, ge=1, le=10)


class RemoveRequest(_Public):
    action: Literal['remove']


def parse_request(params):
    model = {'create': CreateRequest, 'remove': RemoveRequest}.get(params.get('action'))
    if model is None:
        raise ValueError('Biotin append requires create or remove')
    return model.model_validate(params)


def prepare_command(design, params, *, history_seed):
    body = parse_request(params)
    particles = [p for p in design.nanoparticles if p.id == body.nanoparticle_id]
    if len(particles) != 1:
        commands._reference(body.nanoparticle_id, 'Selected coated particle is missing or ambiguous', ['nanoparticle_id'])
    particle = particles[0]
    inputs = {**body.model_dump(mode='json'), '_proof_version': 1, 'biotin_version': 1}
    if isinstance(body, CreateRequest):
        descriptor = InputSource(sha256=PDB_SHA256, size_bytes=PDB_SIZE, format='pdb', media_type='chemical/x-pdb')
        inputs.update(history_seed=history_seed, site_count=len(particle.coating.poses) if particle.coating else 0,
            tether_source=descriptor.model_dump(mode='json'), coating_source=descriptor.model_dump(mode='json'),
            **contract_defaults())
    else:
        inputs['owned'] = commands.owned_records(particle)
    commands.validate_inputs(commands.KIND, design, inputs, resolver=EmbeddedResolver(design.input_sources))
    return inputs


def capture_basis(design):
    """Validate exact owned DNA before reusing the existing coating envelope."""
    if len(design.nanoparticles) != 1:
        commands._unsupported('Biotin capture requires one coated particle')
    particle = design.nanoparticles[0]
    if not particle.biotin_dna:
        return design
    commands.validate_inputs(commands.KIND, design, {'_proof_version': 1, 'biotin_version': 1,
        'action': 'remove', 'nanoparticle_id': particle.id, 'owned': commands.owned_records(particle)})
    return design.copy_with(helices=[], strands=[], extensions=[], nanoparticles=[
        particle.model_copy(update={'biotin_dna': []})])
