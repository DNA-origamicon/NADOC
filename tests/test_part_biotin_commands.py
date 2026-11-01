"""Pinned input and deterministic ownership preserve the native pocket search."""
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.api import part_biotin_commands as commands
from backend.api.part_biotin_append import prepare_command
from backend.api.part_proof_commands import execute, execute_long, dependencies
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_input_sources import EmbeddedInput, SourceContractError, command_sources
from backend.core.models import Nanoparticle
from backend.core.streptavidin import build_streptavidin_coating
from backend.core.gold_strep_dna import build_dna_set
from backend.core.biotin_extensions import ensure_biotin_extensions
from backend.core.part_history_contract import create_empty_part
from tests.test_part_streptavidin_commands import sources as sources


def initial(sources, mode='adsorption', count=1):
    return create_empty_part('Biotin', 'HONEYCOMB').copy_with(input_sources=sources['table'], nanoparticles=[
        Nanoparticle(id='gold', diameter_nm=10., coating=build_streptavidin_coating(10., mode=mode, count_override=count))])


def inputs(design, **changes):
    return prepare_command(design, {'action': 'create', 'nanoparticle_id': 'gold',
        'sequence': 'ACGTACGT', 'linker_nm': 2., **changes}, history_seed=str(uuid4()))


def authored(design):
    return design.model_dump(mode='json', include=AUTHORING_FIELDS)


@pytest.mark.parametrize('mode,count,occupancy', [('adsorption', 1, 4), ('biotin_tether', 1, 3), ('adsorption', 3, 2)])
def test_exact_native_full_authoring_and_ids_without_hidden_source(sources, monkeypatch, mode, count, occupancy):
    design = initial(sources, mode, count)
    params = inputs(design, dna_per_strep=occupancy)
    expected = deepcopy(design)
    particle = expected.nanoparticles[0]
    placed = build_dna_set(particle, 'ACGTACGT', linker_nm=2., dna_per_strep=occupancy, design=expected)
    command = commands.parse_command(commands.KIND, params)
    for record, helix, strand in placed:
        helix.id = commands.output_id(command, 'helix', record.tetramer_index, record.chain)
        strand.id = commands.output_id(command, 'strand', record.tetramer_index, record.chain)
        strand.domains[0].helix_id = helix.id
        record.helix_id, record.strand_id = helix.id, strand.id
    particle.biotin_dna = [r for r, _, _ in placed]
    expected.helices, expected.strands = [h for _, h, _ in placed], [s for _, _, s in placed]
    ensure_biotin_extensions(expected)
    from backend.core import gold_strep_dna
    monkeypatch.setattr(gold_strep_dna, 'streptavidin_asset', lambda *_a, **_k: pytest.fail('Implicit bundle lookup'))
    before = design.model_dump_json()
    candidate = execute_long(commands.KIND, design, params)
    assert authored(candidate) == authored(expected)
    assert authored(execute_long(commands.KIND, design, params)) == authored(candidate)
    assert design.model_dump_json() == before
    assert command_sources(commands.KIND, params) == (command.tether_source, command.coating_source)
    assert dependencies(commands.KIND, params).known
    remove = prepare_command(candidate, {'action': 'remove', 'nanoparticle_id': 'gold'}, history_seed=str(uuid4()))
    assert authored(execute_long(commands.KIND, candidate, remove)) == authored(design)


@pytest.mark.parametrize('damage', ['source', 'pin', 'runtime', 'sites', 'coating', 'foreign'])
def test_invalid_input_fails_before_publication(sources, damage):
    design = initial(sources)
    params = inputs(design)
    if damage == 'source':
        design.input_sources = {**design.input_sources, params['tether_source']['sha256']: EmbeddedInput(data_b64='AAAA')}
    elif damage == 'pin':
        params['engine']['implementation_sha256'] = '0' * 64
    elif damage == 'runtime':
        params['engine']['runtime_sha256'] = '0' * 64
    elif damage == 'sites':
        params['site_count'] = 2
    elif damage == 'coating':
        design.nanoparticles[0].coating.protein.atoms[0].x += 1
    else:
        from backend.core.models import Helix, Vec3
        design.helices = [Helix(axis_start=Vec3(x=0., y=0., z=0.),
                               axis_end=Vec3(x=0., y=0., z=1.), length_bp=4)]
    before = design.model_dump_json()
    with pytest.raises((CommandContractError, SourceContractError)):
        execute_long(commands.KIND, design, params)
    assert design.model_dump_json() == before


def test_job_required_and_owned_delete_rejects_changed_or_foreign_dna(sources):
    design = initial(sources)
    params = inputs(design)
    with pytest.raises(CommandContractError) as error:
        execute(commands.KIND, design, params)
    assert error.value.code == 'long_job_required'
    candidate = execute_long(commands.KIND, design, params)
    remove = prepare_command(candidate, {'action': 'remove', 'nanoparticle_id': 'gold'}, history_seed=str(uuid4()))
    candidate.nanoparticles[0].biotin_dna[0].chain = 'D' if candidate.nanoparticles[0].biotin_dna[0].chain != 'D' else 'B'
    with pytest.raises(CommandContractError):
        execute_long(commands.KIND, candidate, remove)


def test_public_choices_cannot_supply_source_pin_or_output(sources):
    design = initial(sources)
    for key, value in [('engine', {}), ('history_seed', str(uuid4())), ('owned', []), ('pose', [1.] * 16)]:
        with pytest.raises(ValueError):
            inputs(design, **{key: value})
