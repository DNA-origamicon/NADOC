from types import SimpleNamespace
import asyncio

import numpy as np
import pytest
from pydantic import ValidationError
from backend.core.oxdna_vmmc import (VmmcMelting, duplex_pairs, configure, histogram,
    tune_weights, duplex_yield, melting_point, analyse, validate_request)
from backend.core.oxdna_job import new_oxdna_job, OxdnaStatus, OxdnaJob
from backend.core.oxdna_protocol import build_production_stage


def topology(root):
    path=root/'topology.top'
    path.write_text('4 2\n1 A 1 -1\n1 C -1 0\n2 G 3 -1\n2 T -1 2\n')
    return path


def test_config_and_duplex_validation(tmp_path):
    assert duplex_pairs(topology(tmp_path)) == [(0,3),(1,2)]
    for fields in [{'replicas':1},{'end_c':59},{'temperature_c':90},{'step_c':.001},{'production_steps':float('nan')}]:
        with pytest.raises(ValidationError): VmmcMelting(**fields)
    p=tmp_path/'topology.top';p.write_text(p.read_text().replace('2 T','2 C'))
    with pytest.raises(ValueError,match='reverse-complementary'):duplex_pairs(p)


def test_finite_size_correction_and_interpolation():
    assert duplex_yield(2) == pytest.approx(.5)
    assert duplex_yield(0) == 0
    assert duplex_yield(float('inf')) == 1
    assert duplex_yield(1e-15) == pytest.approx(1e-15)
    assert melting_point([60,70,80],[.7,.5,.2]) == 70
    assert melting_point([60,70],[1,.9]) is None
    weights=tune_weights([1,1,1],[0,100,10000])
    assert weights[0]>weights[1]>weights[2]>0


def test_native_histogram_shape_and_invalid_values(tmp_path):
    p=tmp_path/'hist.dat';p.write_text('0 1 1 1\n1 1 1 nan\n')
    with pytest.raises(ValueError):histogram(p,1,1)
    p.write_text('0 1 1 1\n')
    with pytest.raises(ValueError):histogram(p,1,1)


def write_samples(directory, steps):
    # Three temperatures: true bound/unbound ratios 8, 2, 0.5 imply Tm=70 C.
    (directory/'last_hist.dat').write_text('# native format\n0 100 1 1 1 1\n1 100 1 4 1 .25\n2 100 1 4 1 .25\n')
    np.savetxt(directory/'energy.dat',[[i*steps/100,-1,.2,.2,0,2*(i%2),7] for i in range(101)])
    (directory/'last_conf.dat').write_text(f't = {steps}\n')


def test_controller_freezes_weights_and_reports_only_production(tmp_path,monkeypatch):
    from backend.core import oxdna_runner as runner
    from backend.core.oxdna_vmmc_runner import run
    cfg=VmmcMelting(tuning_rounds=2,tuning_steps=1000,equil_steps=1000,production_steps=2000,replicas=3,step_c=10)
    job=new_oxdna_job('VMMC fixture',[],n_nucleotides=4);job.run_config={}
    specs=configure(job,build_production_stage(salt_concentration=.3),cfg)
    assert job.salt_concentration == .3
    assert len({s.seed for s in specs}) == len(specs)
    root=job.job_dir(tmp_path);root.mkdir(parents=True)
    topology(root);(root/'conf.dat').write_text('t = 0\nb = 10 10 10\nE = 0 0 0\n')
    monkeypatch.setattr(runner,'find_oxdna',lambda:'/fake/oxDNA')
    monkeypatch.setattr(runner,'conf_is_restartable',lambda *a:True)
    seen=[]
    async def native(binary,inp,directory,log,jid,on_spawn=None):
        seen.append(directory.name)
        assert 'sim_type = VMMC' in inp.read_text() and 'backend = CPU' in inp.read_text()
        write_samples(directory,next(s.steps for s in specs if s.name==directory.name))
        return 0,123
    monkeypatch.setattr(runner,'_run_oxdna_async',native)
    asyncio.run(run(job,tmp_path,specs))
    loaded=OxdnaJob.load(job.job_id,tmp_path)
    result=loaded.run_config['vmmc_result']
    assert loaded.status == OxdnaStatus.completed and all(s.status=='done' for s in loaded.stages)
    assert len(seen)==8 and len(result['replicas'])==3
    assert result['status']=='sampling_checks_passed' and result['tm_c']==pytest.approx(70)
    assert result['replica_tm_sem_c']==0
    weights=[(root/s.name/'weights.txt').read_text() for s in specs if '_sample_' in s.name]
    assert len(set(weights))==1
    before=len(seen);asyncio.run(run(loaded,tmp_path,specs));assert len(seen)==before
    # Recover a crash after the final stage receipt but before result publication.
    loaded.run_config.pop('vmmc_result')
    loaded.status = OxdnaStatus.stopped
    runner.reconcile_oxdna_status(loaded, tmp_path, specs)
    assert loaded.status == OxdnaStatus.completed
    assert loaded.run_config['vmmc_result']['tm_c'] == pytest.approx(70)
    # Restart replays only the unfinished stage and archives its partial histogram.
    loaded.stages[-1].status = 'stopped'
    loaded.status = OxdnaStatus.stopped
    asyncio.run(run(loaded, tmp_path, specs))
    assert len(seen) == before + 1
    assert list((root / specs[-1].name).glob('interrupted_*/last_hist.dat'))
    assert all(s.status == 'done' for s in loaded.stages)
    # Invalid native output fails this stage and does not silently advance.
    async def broken(*args, **kwargs):
        return 1, 123
    monkeypatch.setattr(runner, '_run_oxdna_async', broken)
    loaded.stages[-1].status = 'stopped'
    with pytest.raises(ValueError, match='exit 1'):
        asyncio.run(run(loaded, tmp_path, specs))
    assert loaded.status == OxdnaStatus.failed and loaded.stages[-1].status == 'failed'
    monkeypatch.setattr(runner, '_run_oxdna_async', native)
    asyncio.run(run(loaded, tmp_path, specs))
    # Completed but statistically insufficient simulations are inconclusive, not execution failures.
    for s in specs:
        if '_sample_' in s.name:np.savetxt(root/s.name/'energy.dat',[[0,-1,.2,.2,0,2,1],[2000,-1,.2,.2,0,2,1]])
    assert analyse(root,specs,cfg,2)['status']=='inconclusive'


def test_modes_and_special_systems_are_rejected_before_job_creation(tmp_path):
    topology(tmp_path)
    body=SimpleNamespace(vmmc_melting=VmmcMelting(),thermal_ramp=True,field=None,surface=None,anchors=[],surface_anchors=[],surface_strands=None,submodel=None)
    with pytest.raises(ValueError,match='either'): validate_request(body,tmp_path,SimpleNamespace(run_config={}))
    body.thermal_ramp=None
    validate_request(body,tmp_path,SimpleNamespace(run_config={}))
    (tmp_path/'cpd_manifest.json').write_text('{}')
    with pytest.raises(ValueError,match='CPD'):validate_request(body,tmp_path,SimpleNamespace(run_config={}))


def test_full_system_wizard_wrapper_is_not_an_active_submodel(tmp_path):
    from backend.api.routes_oxdna import RunRequest
    topology(tmp_path)
    parent = SimpleNamespace(run_config={})
    body = RunRequest(vmmc_melting={}, submodel={"box": None})
    validate_request(body, tmp_path, parent)
    body = RunRequest(vmmc_melting={}, submodel={"box": {
        "min_corner": [0, 0, 0], "max_corner": [10, 10, 10]}})
    with pytest.raises(ValueError, match="submodels"):
        validate_request(body, tmp_path, parent)
