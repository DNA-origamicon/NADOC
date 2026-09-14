"""Source-only PEG NAMD preflight: no molecular mapper or engine subprocess."""
from copy import deepcopy
import hashlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.core.peg_seed_source import inspect_peg_checkpoint, inspect_peg_job, transformed_peg_source
from backend.core.constants import NM_TO_OXDNA
from backend.core.surface_transforms import RigidTransform


@pytest.fixture
def source_job(tmp_path):
    from scripts.create_peg_surface_review import make_review_design
    from backend.physics.oxdna_interface import write_topology, _strand_nucleotide_order
    from backend.core.oxdna_job import new_oxdna_job, OxdnaStageStatus
    design = make_review_design()
    keys = _strand_nucleotide_order(design)
    n = len(keys)
    coating = {'material': 'PEG', 'segments': 2, 'bondLengthNm': .3,
               'built': {'n_beads': 3, 'n_strands': 1, 'beads_per_chain': 3,
                         'terminal_particles': [n + 2],
                         'trap_anchors': [[n, (np.array([9.8, 0, 0]) * NM_TO_OXDNA).tolist()]]}}
    surface = {'dir': [0, 0, 1], 'position_nm': 0, 'stiff': 5}
    job = new_oxdna_job('source', [OxdnaStageStatus(name='relax', kind='equil', steps=10)],
                       run_config={'surface_strands': coating, 'surface': surface})
    job.save(tmp_path)
    root = job.job_dir(tmp_path)
    (root / 'design.json').write_text(design.to_json())
    write_topology(design, root / 'topology.top')
    lines = (root / 'topology.top').read_text().splitlines()
    count, strands = map(int, lines[0].split())
    lines[0] = f'{count + 3} {strands + 1}'
    lines += [f'{strands+1} 500 {n+1} -1', f'{strands+1} 500 {n+2} {n}',
              f'{strands+1} 500 -1 {n+1}']
    top = '\n'.join(lines) + '\n'
    (root / 'topology.top').write_text(top)
    positions = [[1, 1, 3]] * n + [[9.8, 0, 0], [.1, 0, 0], [.4, 0, 0]]
    conf = f't = 10\nb = {10*NM_TO_OXDNA} {10*NM_TO_OXDNA} {10*NM_TO_OXDNA}\nE = 0 0 0\n'
    conf += '\n'.join(' '.join(str(v*NM_TO_OXDNA) for v in p) +
                       ' 1 0 0 0 0 1 0 0 0 0 0 0' for p in positions) + '\n'
    stage = root / 'relax'
    stage.mkdir()
    (stage / 'last_conf.dat').write_text(conf)
    return job, design, keys, top, conf, coating, surface


def test_inventory_maps_every_bead_and_keeps_source_files_unchanged(source_job, tmp_path):
    job, _, keys, top, conf, _, _ = source_job
    root = job.job_dir(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
    report = inspect_peg_job(job.job_id, tmp_path, 'coarse_grained')
    assert not report['launch_ready']
    assert report['source_hashes']['checkpoint'] == hashlib.sha256(conf.encode()).hexdigest()
    assert report['source_hashes']['topology'] == hashlib.sha256(top.encode()).hexdigest()
    source = report['source']
    assert len(source['dna_particles']) == len(keys)
    assert source['chains'][0]['source_particles'] == list(range(len(keys), len(keys)+3))
    assert source['chains'][0]['target_atoms'] is None
    assert np.allclose(np.asarray(source['surface']['peg_positions_nm'])[:, 0], [9.8, 10.1, 10.4])
    moved = transformed_peg_source(source, RigidTransform(translation_nm=[-1, -1, -3]))
    assert np.allclose(moved['dna_positions_nm'], 0)
    assert np.allclose(moved['dna_a1'], [1, 0, 0])
    rotated = transformed_peg_source(source, RigidTransform([[0, -1, 0], [1, 0, 0], [0, 0, 1]]))
    assert np.allclose(rotated['dna_a1'], [0, 1, 0])
    assert np.allclose(rotated['dna_a3'], [0, 0, 1])
    assert np.allclose(moved['surface']['graft_sites_nm'], [[8.8, -1, -3]])
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize('damage', ['truncated', 'nan', 'counts', 'terminal', 'topology'])
def test_reject_corrupt_or_mismatched_sources(source_job, damage):
    _, _, keys, top, conf, coating, surface = source_job
    coating = deepcopy(coating)
    if damage == 'truncated':
        conf = '\n'.join(conf.splitlines()[:-1])
    elif damage == 'nan':
        conf = conf.replace(' 1 0 0 0 0 1 ', ' nan 0 0 0 0 1 ', 1)
    elif damage == 'counts':
        coating['built']['n_beads'] = 6
    elif damage == 'terminal':
        coating['built']['terminal_particles'] = [0]
    else:
        top = top.replace(' 500 ', ' 501 ', 1)
    with pytest.raises(ValueError):
        inspect_peg_checkpoint(top, conf, coating, surface, dna_keys=keys)


def test_reader_excludes_appended_peg_before_dna_mapping(source_job, tmp_path):
    from backend.physics.oxdna_interface import read_configuration_full_unwrapped
    job, design, keys, *_ = source_job
    result = read_configuration_full_unwrapped(job.job_dir(tmp_path) / 'relax/last_conf.dat',
                                               design, n_trailing_extra=3,
                                               copies=True, include_extra_bases=True,
                                               include_extensions=True)
    assert len(result) == len(keys)
    assert all(np.allclose(record['backbone_position'], [1, 1, 3]) for record in result.values())


def test_launch_preflight_refuses_silent_dna_only_seed(source_job, tmp_path):
    from backend.core.oxdna_runner import assert_namd_seed_available, build_namd_seed
    job, *_ = source_job
    for function in (assert_namd_seed_available, build_namd_seed):
        with pytest.raises(FileNotFoundError, match='DNA-only seeding is refused'):
            function(job.job_id, tmp_path)


def test_seed_review_api_is_read_only(source_job, tmp_path, monkeypatch):
    from backend.api.main import app
    from backend.api import routes_oxdna
    job, *_ = source_job
    monkeypatch.setattr(routes_oxdna, '_workspace', lambda: tmp_path)
    client = TestClient(app)
    response = client.post('/api/oxdna/peg/namd-seed', json={'source_job_id': job.job_id})
    assert response.status_code == 200, response.text
    assert response.json()['launch_ready'] is False
    assert {b['code'] for b in response.json()['barriers']} == {
        'target_representation', 'target_mapping', 'target_assets', 'engine_validation'}
    assert client.post('/api/oxdna/peg/namd-seed', json={'source_job_id': '../bad'}).status_code == 422
    assert len(list((tmp_path / 'oxdna_jobs').iterdir())) == 1


def test_compact_persisted_grafts_use_initial_configuration(source_job, tmp_path):
    job, _, _, _, conf, *_ = source_job
    root = job.job_dir(tmp_path)
    built = job.run_config['surface_strands']['built']
    built['trap_particles'] = [p for p, _ in built.pop('trap_anchors')]
    job.save(tmp_path)
    (root / 'conf.dat').write_text(conf)
    source = inspect_peg_job(job.job_id, tmp_path)
    assert 'initial_configuration' in source['source_hashes']
    assert np.allclose(source['source']['surface']['graft_sites_nm'], [[9.8, 0, 0]])


def test_source_rejects_same_count_but_different_dna_topology(source_job, tmp_path):
    job, *_ = source_job
    path = job.job_dir(tmp_path) / 'topology.top'
    lines = path.read_text().splitlines()
    fields = lines[1].split()
    fields[1] = 'T' if fields[1] != 'T' else 'A'
    lines[1] = ' '.join(fields)
    path.write_text('\n'.join(lines) + '\n')
    with pytest.raises(ValueError, match='DNA topology'):
        inspect_peg_job(job.job_id, tmp_path)
