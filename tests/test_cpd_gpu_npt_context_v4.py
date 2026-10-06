import json
import time
from pathlib import Path
import numpy as np
import pytest
from experiments.cpd_anti_additive import gpu_npt_context_v4 as m


def test_checkpoint_config_uses_full_xsc_without_overriding_cell():
    cp=Path('/tmp/qualified-checkpoint')
    cfg=m.config('anti',Path(str(cp)+'.coor'),530000,123,cp,True,True,5000)
    assert 'extendedSystem /tmp/qualified-checkpoint.xsc\n' in cfg
    assert not any(line.startswith(('cellBasisVector','cellOrigin')) for line in cfg.splitlines())
    for required in ['GPUresident on','vdwForceSwitching on','LangevinPiston on',
                     'PMEGridSizeX 72','PMEGridSizeY 88','PMEGridSizeZ 144',
                     'DCDfreq 5000','outputEnergies 1000','useGroupPressure yes',
                     'timestep 2','stepspercycle 10','restartfreq 50000','restartsave yes','restartname checkpoint']:
        assert required+'\n' in cfg
    assert 'run 0' not in cfg


def test_timing_excludes_initial_slow_intervals_and_reports_real_atom_count():
    log='\n'.join(f'TIMING: {i*1000} CPU: 1, 1/step Wall: 1, {s}/step, 1 ns/days'
                  for i,s in enumerate([.004,.003,.002,.002],1))+'\nWallClock: 20\n'
    p=m.performance(log,10000)
    assert p['late_median_seconds_per_step']==.002
    assert p['late_ns_per_day']==pytest.approx(86.4)
    assert p['late_nanoseconds_wall_per_atom_step']==pytest.approx(.002*1e9/70624)
    assert p['native_seconds_per_ns']==pytest.approx(1000)
    with pytest.raises(AssertionError):m.performance('WallClock: 20\n',10000)


def test_xsc_rejects_shear_nonfinite_or_missing_cell(tmp_path):
    path=tmp_path/'state.xsc'
    row=np.array([530000,60,0,0,0,80,0,0,0,120,30,40,60,.001,.002,.003])
    np.savetxt(path,row[None,:]);box,full=m.box_from_xsc(path)
    assert np.array_equal(full,row) and np.array_equal(box,[60,80,120])
    for index,value in [(2,1),(1,np.nan),(9,20)]:
        bad=row.copy();bad[index]=value;np.savetxt(path,bad[None,:])
        with pytest.raises(AssertionError):m.box_from_xsc(path)


def test_activation_respects_changed_hold_and_absolute_deadline(tmp_path,monkeypatch):
    hold=tmp_path/'hold.json';hold.write_text('{"paused": true}')
    activation=dict(authorized=True,context_max_hours=48,legacy_hold=m.source(hold),
                    scope='Six fresh matched 10 ns GPU-resident NPT validation runs only',
                    context_deadline_epoch=time.time()+100)
    path=tmp_path/'activation.json';path.write_text(json.dumps(activation));monkeypatch.setattr(m,'ROOT',tmp_path)
    assert m.authorize()['authorized']
    hold.write_text('{"paused": false}')
    with pytest.raises(ValueError):m.authorize()
    hold.write_text('{"paused": true}');activation['context_deadline_epoch']=time.time()-1
    path.write_text(json.dumps(activation))
    with pytest.raises(AssertionError):m.authorize()


def test_regular_restart_sets_require_all_components_and_correct_step(tmp_path,monkeypatch):
    from experiments.cpd_anti_additive.run_engine_v2 import binary
    monkeypatch.setattr(m,'N',2)
    for step in [50000,100000]:
        for ext in ['coor','vel']:binary(tmp_path/f'checkpoint.{step}.{ext}',np.zeros((2,3)))
        np.savetxt(tmp_path/f'checkpoint.{step}.xsc',np.array([[step,60,0,0,0,80,0,0,0,120,30,40,60,.001,.002,.003]]))
    assert [r['step'] for r in m.regular_checkpoints(tmp_path,25000,125000)]==[50000,100000]
    (tmp_path/'checkpoint.50000.vel').unlink()
    with pytest.raises(FileNotFoundError):m.regular_checkpoints(tmp_path,25000,125000)
