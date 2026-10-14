import json
from pathlib import Path

import numpy as np
import pytest

from experiments.cpd_isomer_formation.geometry import catalog, features
from experiments.cpd_isomer_formation.reanalyze import reanalyze
from experiments.cpd_isomer_formation.run import pin
from backend.core.photoproduct_chemistry import load_chemical_definition, load_patch_charge_scope
from backend.core.photoproduct_registry import photoproduct_registry


def cached_input(tmp_path):
    source = tmp_path / 'original'
    source.mkdir()
    base = np.array([[-.7,1.2,0], [0,0,0], [1.4,0,0],
                     [-.7,-1.2,0], [2.1,-.8,0], [2.1,1.2,0]])
    second = (base*[1,-1,-1] - [.7,0,0])*[-1,-1,1]+[.7,0,3.4]
    close = np.concatenate([base,second])
    far = close.copy(); far[6:,2] += 8
    x = np.stack([close,far])[:,None,:,:]
    products = catalog()
    np.savez_compressed(source/'geometry.npz', coordinates_ang=x,
                        time_weights_ps=np.array([2.,1.]), **features(x, products))
    plan = {'job_id':'test', 'distance_cutoffs_ang':[4.],
            'twist_cutoffs_deg':[45.], 'face_margin_cutoffs':[.25]}
    (source/'plan.json').write_text(json.dumps(plan))
    summary = {'plan':pin(source/'plan.json'), 'cached_geometry':pin(source/'geometry.npz'),
               'isomer_ids':[p['id'] for p in products], 'sample_count':2, 'pair_ids':['pair'],
               'pairs':[{'id':'pair','class':'intended_weld'}]}
    (source/'summary.json').write_text(json.dumps(summary))
    return source


def test_replay_uses_weights_preserves_inputs_and_detects_anti(tmp_path):
    source = cached_input(tmp_path)
    before = {p.name:p.read_bytes() for p in source.iterdir()}
    result = reanalyze(source, tmp_path/'replay')
    assert result['stereochemical_detection_passed']
    assert not result['formation_ranking_qualified']
    k = result['isomer_ids'].index('tt-cpd-cis-anti-i')
    grid = result['grids'][0]
    assert grid['compatible_fraction_by_pair_isomer'][0][k] == pytest.approx(2/3)
    assert grid['compatible_sample_counts_by_isomer'][k] == 1
    assert before == {p.name:p.read_bytes() for p in source.iterdir()}
    with pytest.raises(FileExistsError):
        reanalyze(source, tmp_path/'replay')


def test_replay_refuses_changed_cached_coordinates(tmp_path):
    source = cached_input(tmp_path)
    with (source/'geometry.npz').open('ab') as stream:
        stream.write(b'changed')
    with pytest.raises(ValueError, match='Changed cached input'):
        reanalyze(source, tmp_path/'replay')
    assert not (tmp_path/'replay').exists()


def test_corrected_anti_definitions_do_not_inherit_old_minimum_or_review():
    for entry in photoproduct_registry()['products']:
        if entry['structural_class']['double_bond_orientation'] != 'anti':
            continue
        definition = load_chemical_definition(entry['product'], entry['stereochemistry'])
        scope = load_patch_charge_scope(entry['product'], entry['stereochemistry'])
        assert len(scope['atoms_with_charges_replaced']) == 28
        assert 'minimum_geometry_evidence' not in definition
        assert definition['superseded_minimum_geometry_evidence']['evidence']
        assert not definition['stereochemistry_correction']['minimum_certified']
        assert entry['gates']['chemical_definition']['status'] == 'pending'
        assert entry['assets']['chemical_definition']['sha256'] != definition[
            'stereochemistry_correction']['previous_definition']['sha256']
