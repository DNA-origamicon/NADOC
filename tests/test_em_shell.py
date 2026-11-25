"""Optical shell assumptions, admission and independent Maxwell checks."""
import json
import os
import subprocess

import numpy as np
import pytest

from backend.api.routes_em_analysis import EMRequest, solver_python
from backend.physics.em_shell import shell_parameters


def test_length_proxy_and_full_coverage():
    short = shell_parameters([{}], {'model': 'ssdna_wlc', 'oligo_length_nt': 10})
    long = shell_parameters([{}, {}], {'model': 'ssdna_wlc', 'oligo_length_nt': 20})
    assert 0 < short['thickness_nm'] < long['thickness_nm'] < .59*20
    assert long['thickness_by_particle_nm'] == [long['thickness_nm']] * 2
    assert shell_parameters([{}], {'model': 'none'})['thickness_nm'] == 0
    assert shell_parameters([{}], {'model': 'manual', 'thickness_nm': 1.2})['thickness_nm'] == 1.2
    assert 'not a measured optical' in long['interpretation']


@pytest.mark.parametrize('settings', [{'model': 'unknown'}, {'refractive_index': float('nan')},
    {'persistence_length_nm': 0}, {'oligo_length_nt': 0}, {'thickness_nm': -1}])
def test_invalid_shell(settings):
    with pytest.raises(ValueError):
        shell_parameters([{}], settings)


def test_shell_request_contract():
    request = EMRequest(particles=[{'id': 'a', 'center_nm': [0, 0, 0], 'diameter_nm': 20}],
        shell={'model': 'ssdna_wlc'}, solver='multipole_reference')
    assert request.shell.oligo_length_nt == 20
    with pytest.raises(ValueError):
        EMRequest(**{**request.model_dump(), 'solver': 'dipole'})


def test_independent_coated_sphere_oracle():
    executable = solver_python()
    if not executable:
        pytest.skip('Optional EM environment missing')
    process = subprocess.run([executable, 'tests/em_shell_oracle.py'], capture_output=True,
        text=True, timeout=60, env={**os.environ, 'PYTHONPATH': '.', 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'})
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.parametrize('sampling', ['uniform', 'adaptive', 'field_adaptive'])
def test_coated_solve_and_overlap_rejection(sampling):
    executable = solver_python()
    if not executable:
        pytest.skip('Optional EM environment missing')
    particle = lambda x: {'id': str(x), 'center_nm': [x, 0, 0], 'diameter_nm': 20}
    payload = {'particles': [particle(0), particle(25)], 'resolution': 25, 'sampling': sampling,
        'shell': {'model': 'manual', 'thickness_nm': .5, 'refractive_index': 1.7}}
    def run(value):
        return subprocess.run([executable, '-m', 'backend.physics.em_analysis'], input=json.dumps(value),
            capture_output=True, text=True, timeout=60,
            env={**os.environ, 'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1'})
    process = run(payload)
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(process.stdout)
    if sampling != 'uniform':
        assert len(result['sample_positions_nm']) == len(result['intensity']) <= 5 * 25**3
        assert result['sampling']['layout'] == 'octree'
        if sampling == 'field_adaptive':
            refinement = result['sampling']['field_refinement']
            assert refinement['refined_cells'] > 0
            assert 1 <= refinement['rounds'] <= 3
    assert result['dna_shell']['thickness_nm'] == .5
    assert result['probe_relative_error'] < .01
    assert np.isfinite(result['intensity']).all()
    process = run({**payload, 'shell': {'model': 'ssdna_wlc', 'oligo_length_nt': 20}})
    assert process.returncode == 1
    error = json.loads(process.stdout)['error']
    assert 'overlap' in error
    assert '5.00 nm metal gap' in error and '13.65 nm' in error
