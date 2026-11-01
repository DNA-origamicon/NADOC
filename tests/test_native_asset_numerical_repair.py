"""New numerical families retain authored pins until an explicit upgrade."""
from copy import deepcopy
from uuid import uuid4

import pytest
from backend.api import part_recipe_repair as repair
from backend.core.part_command_errors import CommandContractError
from backend.core.part_repair_inputs import UpgradeNumericalContract


def definition(kind):
    if kind == 'nanoparticle-biotin-dna':
        from backend.core.part_biotin_contract import contract_defaults
        from backend.api.part_streptavidin_commands import PDB_SHA256, PDB_SIZE
        source = {'sha256': PDB_SHA256, 'size_bytes': PDB_SIZE, 'format': 'pdb', 'media_type': 'chemical/x-pdb'}
        params = {**contract_defaults(), 'action': 'create', 'nanoparticle_id': 'gold',
            'history_seed': str(uuid4()), 'tether_source': source, 'coating_source': source,
            'site_count': 1, 'sequence': 'ACGT', 'dna_per_strep': 1, 'pocket': 'auto', 'linker_nm': 2.}
    else:
        from backend.core.part_np_fitting_contract import contract_defaults
        params = {**contract_defaults(), 'nanoparticle_id': 'gold', 'conjugation_id': 'graft',
            'applied_version_ids': [], 'applied_duplex_ids': []}
        if kind == 'nanoparticle-attach-overhang':
            params.update(history_seed=str(uuid4()), version_id='version', duplex_id='duplex', created_at=1.,
                overhang_id='target', strand_id='strand', fixed_center=False)
        elif kind == 'nanoparticle-patch':
            params['gizmo_move'] = {'pivot': [0., 0., 0.], 'translation': [0., 0., 0.], 'rotation': [0., 0., 0., 1.]}
    params['engine']['implementation_sha256'] = '0' * 64
    return params


@pytest.mark.parametrize('kind', ['nanoparticle-biotin-dna', 'nanoparticle-attach-overhang',
                                  'nanoparticle-patch', 'nanoparticle-connection-relax'])
def test_explicit_upgrade_preserves_every_nonpin_input_and_rejects_stale_expectation(kind):
    params = definition(kind)
    before = deepcopy(params)
    action = UpgradeNumericalContract(action='upgrade_numerical_contract', feature_id='numerical',
        expected_engine=deepcopy(params['engine']))
    changed, report = repair._upgrade(kind, params, action, repair._current_numerical_pins)
    assert report['changed'] and changed['engine'] != params['engine']
    assert {k: v for k, v in changed.items() if k != 'engine'} == {k: v for k, v in params.items() if k != 'engine'}
    assert params == before
    action.expected_engine['implementation_sha256'] = '1' * 64
    with pytest.raises(CommandContractError):
        repair._upgrade(kind, params, action, repair._current_numerical_pins)


def test_biotin_removal_has_no_numerical_upgrade():
    params = {'_proof_version': 1, 'biotin_version': 1, 'action': 'remove', 'nanoparticle_id': 'gold',
        'owned': [{'strand_id': 'strand', 'helix_id': 'helix', 'tetramer_index': 0, 'chain': 'A'}]}
    action = UpgradeNumericalContract(action='upgrade_numerical_contract', feature_id='numerical', expected_engine={})
    with pytest.raises(CommandContractError, match='Only biotin creation'):
        repair._upgrade('nanoparticle-biotin-dna', params, action, repair._current_numerical_pins)


@pytest.mark.parametrize('parameter', ['tether_source', 'coating_source'])
def test_biotin_source_repair_restores_only_the_recorded_assembly(parameter):
    from backend.api.part_repair_source_policy import admit_descriptor
    from backend.core.part_input_sources import InputSource
    params = definition('nanoparticle-biotin-dna')
    source = InputSource.model_validate(params[parameter])
    admitted = admit_descriptor('nanoparticle-biotin-dna', params, parameter, source)
    assert admitted['max_size_bytes'] >= source.size_bytes and not admitted['replacement_supported']
    with pytest.raises(CommandContractError):
        admit_descriptor('nanoparticle-biotin-dna', params, parameter, source.model_copy(update={'sha256': '0' * 64}))
