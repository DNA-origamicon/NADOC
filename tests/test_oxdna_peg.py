"""PEG model semantics and actual CPU/CUDA force checks (isolated engine optional)."""
import subprocess
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from backend.physics.oxdna_peg import PegParameters, configure_peg_stages, find_peg_oxdna, peg_terminal_field_text
from backend.physics.oxdna_surface_strands import CaptureSpec, build_capture_strands
from backend.core.oxdna_protocol import OxdnaStageSpec, render_stage_input
from scripts.create_peg_surface_review import make_review_design


def test_review_roundtrip_and_build():
    design = make_review_design()
    loaded = type(design).model_validate_json(design.model_dump_json())
    setup = loaded.metadata.peg_surface
    spec = CaptureSpec.from_payload(setup['surface_strands'])
    kwargs = dict(origami_cm_oxdna=np.array([[0,0,0],[1,0,0]]),
                  n_particles_origami=2, n_strands_origami=1, surface=setup['surface'])
    a, b = build_capture_strands(spec, **kwargs), build_capture_strands(spec, **kwargs)
    assert a.conf_lines == b.conf_lines
    assert a.n_strands == 4 and a.n_beads == 36
    assert {row[1] for row in a.topology_rows} == {'500'}
    assert [p for p, _ in a.trap_anchors] == [2,11,20,29]
    xyz = np.array([[float(v) for v in line.split()[:3]] for line in a.conf_lines]).reshape(4,9,3)
    assert np.allclose(np.linalg.norm(np.diff(xyz, axis=1),axis=2), PegParameters().engine_parameters()['peg_bond_length'])
    assert np.allclose(xyz[:,0,1], -7/.8518)


def test_parameters_and_field():
    for invalid in ({'segments':1}, {'bondLengthNm':float('nan')}, {'terminalChargeE':3}):
        with pytest.raises(ValidationError):
            PegParameters(**invalid)
    spec = {**make_review_design().metadata.peg_surface['surface_strands'],
            'built':{'terminal_particles':[8,17]}}
    field = {'field_V_per_m':1e7, 'dir':[0,1,0]}
    assert peg_terminal_field_text(spec,field) == ''
    charged = {**spec,'terminalChargeE':1}
    text = peg_terminal_field_text(charged,field)
    assert 'particle = 8\n' in text and 'particle = 17\n' in text
    assert text.count('type = string') == 2
    assert peg_terminal_field_text(charged, {'force_pn':1}) == ''
    stage = OxdnaStageSpec('test','production','MD',1,'CUDA',dt=.003)
    configure_peg_stages([stage],spec)
    assert stage.dt == .001 and stage.interaction == 'DNA2PEG'
    assert 'peg_sigma =' in render_stage_input(stage,'top','conf')


@pytest.mark.parametrize('backend,edge', [('CPU',False),('CUDA',False),('CUDA',True)])
@pytest.mark.parametrize('pair', ['spring','peg_wca','mixed_wca'])
def test_engine_pair_forces(tmp_path, backend, edge, pair):
    binary = find_peg_oxdna()
    if not binary:
        pytest.skip('Build isolated DNA2PEG engine to validate CPU/CUDA forces')
    if backend == 'CUDA' and subprocess.run(['nvidia-smi','-L'],capture_output=True).returncode:
        pytest.skip('CUDA device unavailable')
    params = PegParameters().engine_parameters()
    if pair == 'spring':
        r = params['peg_bond_length'] + .05
        expected = 5.
        topology = '2 1\n1 500 1 -1\n1 500 -1 0\n'
    else:
        sigma = params['peg_sigma' if pair == 'peg_wca' else 'peg_dna_sigma']
        r = sigma * 1.05
        s6 = (sigma/r)**6
        expected = 24*params['peg_epsilon']*(s6-2*s6*s6)/r
        topology = f"2 2\n1 500 -1 -1\n2 {'500' if pair == 'peg_wca' else 'A'} -1 -1\n"
    (tmp_path/'topology.top').write_text(topology)
    (tmp_path/'conf.dat').write_text('t = 0\nb = 20 20 20\nE = 0 0 0\n' +
        ''.join(f'{x:.12g} 2 2 1 0 0 0 0 1 0 0 0 0 0 1e-6\n' for x in (2,2+r)))
    dt = 1e-5
    stage = OxdnaStageSpec('test','production','MD',1,backend,dt=dt,
        thermostat='no',interaction='DNA2PEG',peg_parameters=params,seed=123)
    inp = render_stage_input(stage,'topology.top','conf.dat').replace('refresh_vel = true','refresh_vel = false')
    inp = inp.replace('use_edge = true', f'use_edge = {str(edge).lower()}')
    (tmp_path/'input').write_text(inp)
    result = subprocess.run([binary,'input'],cwd=tmp_path,capture_output=True,text=True,timeout=30)
    assert result.returncode == 0, result.stderr[-5000:]
    final = np.loadtxt(tmp_path/'last_conf.dat',skiprows=3)
    # Velocity Verlet with initially zero velocity: v/dt = initial force to O(dt²).
    forces = final[:,9:12] / dt
    assert np.allclose(forces[:,0], [expected,-expected], rtol=2e-4,atol=2e-4), forces
    assert np.max(np.abs(forces[:,1:])) < 1e-5
    assert np.max(np.abs(final[:,12:15] - [0,0,1e-6])) < 1e-8  # isotropic CM forces exert no torque


@pytest.mark.parametrize('backend', ['CPU', 'CUDA'])
def test_dna_only_unchanged_by_opt_in_model(tmp_path, backend):
    binary = find_peg_oxdna()
    if not binary:
        pytest.skip('Build isolated DNA2PEG engine')
    from backend.api.crud import _geometry_for_design
    from backend.core.oxdna_job import new_oxdna_job
    from backend.core.oxdna_runner import prepare_oxdna_job
    design = make_review_design()
    stage = OxdnaStageSpec('control','production','MD',1,backend,dt=1e-6,seed=123)
    job = new_oxdna_job('control',[stage.to_status()])
    prepare_oxdna_job(design,_geometry_for_design(design),job,tmp_path,[stage])
    jd = job.job_dir(tmp_path)
    results = []
    for interaction in ['DNA2','DNA2PEG']:
        stage.interaction = interaction
        stage.peg_parameters = PegParameters().engine_parameters() if interaction == 'DNA2PEG' else None
        (jd/'input').write_text(render_stage_input(stage,'topology.top','conf.dat'))
        proc = subprocess.run([binary,'input'],cwd=jd,capture_output=True,text=True,timeout=30)
        assert proc.returncode == 0, proc.stderr[-3000:]
        results.append(np.loadtxt(jd/'last_conf.dat',skiprows=3))
    assert np.allclose(*results,atol=1e-8,rtol=1e-8)


@pytest.mark.parametrize('charge', [0,1])
def test_production_inherits_peg_wall_and_terminal_only_field(tmp_path, monkeypatch, charge):
    import asyncio
    import json
    import re
    from backend.api import routes_oxdna as routes
    from backend.core.oxdna_job import OxdnaStatus
    from scripts.create_peg_surface_review import create_review
    if not find_peg_oxdna():
        pytest.skip('Build isolated DNA2PEG engine')
    _, parent = create_review(tmp_path)
    parent.status = OxdnaStatus.completed
    parent.run_config['surface_strands']['terminalChargeE'] = charge
    parent.save(tmp_path)
    monkeypatch.setattr(routes,'_workspace',lambda:tmp_path)
    monkeypatch.setattr(routes,'_assert_job_current',lambda job:None)
    monkeypatch.setattr(routes,'find_oxdna',find_peg_oxdna)
    monkeypatch.setattr(routes,'_latest_relaxed_conf',lambda job, ws:(job.job_dir(ws)/'conf.dat',None))
    monkeypatch.setattr(routes,'start_job',lambda *args:None)
    result = asyncio.run(routes.append_oxdna_run(parent.job_id, routes.RunRequest(
        steps=1000,field=routes.FieldElement(field_V_per_m=1e7,dir=[0,1,0]),
        surface_strands={'enabled':True,'subjectToField':True})))
    child = tmp_path/'oxdna_jobs'/result['job_id']
    stage = json.loads((child/'stages_spec.json').read_text())[0]
    assert stage['interaction'] == 'DNA2PEG' and stage['absolute_forces']
    assert result['run_config']['surface'] == parent.run_config['surface']
    assert result['run_config']['surface_strands']['subjectToField'] is False
    forces = (child/'run_forces.txt').read_text()
    assert 'type = repulsion_plane' in forces
    string_particles = []
    for block in re.findall(r'\{([^{}]*)\}', forces):
        if re.search(r'type\s*=\s*string\b',block):
            string_particles.append(int(re.search(r'particle\s*=\s*(\d+)',block)[1]))
    assert set(p for p in string_particles if p >= 32) == ({40,49,58,67} if charge else set())
    assert 'particle = 32\n' in forces  # first root trap retained
