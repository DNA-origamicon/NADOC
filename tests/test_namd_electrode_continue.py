import json
import pytest
from backend.core.md_job import new_job, MdStatus, MdSegmentStatus
from backend.core.namd_electrode_continue import extend_equilibration


@pytest.fixture
def finished(tmp_path):
    job=new_job('control','electrode_equilibration_namd','system','package')
    job.status=MdStatus.failed;job.failure_kind='electrode_equilibration'
    job.segments=[MdSegmentStatus(name='rung_p100',stage='NVT',percent=100,steps=600000,status='done')]
    job.save(tmp_path)
    p=job.package_dir(tmp_path);p.mkdir();(p/'output').mkdir()
    row=dict(name='rung_p100',previous='rung_p75',stage='NVT',steps=600000,percent=100,timestep_fs=2.,scale=None)
    (p/'manifest.json').write_text(json.dumps(dict(two_electrodes={'salt_mM':300},segments=[row])))
    (p/'rung_p100.conf').write_text('tclForcesScript electrode_forces.tcl\nlangevinPiston off\ntimestep 2\nseed 42\noutputName output/rung_p100\ndcdFile output/rung_p100.dcd\nbinCoordinates output/rung_p75.coor\nbinVelocities output/rung_p75.vel\nextendedSystem output/rung_p75.xsc\nrun 600000\n')
    for ext in ('coor','vel','xsc'):(p/'output'/f'rung_p100.{ext}').write_text('saved checkpoint')
    (p/'output/rung_p100.electrode-health.json').write_text(json.dumps(dict(passed=False,confined=True,bulk_reference_validated=True)))
    return job,p


def test_extension_retains_checkpoint_and_model_and_queues_chunks(tmp_path,finished):
    old,p=finished
    before=(p/'rung_p100.conf').read_bytes()
    job=extend_equilibration(old.job_id,tmp_path,2.4)
    assert job.status==MdStatus.queued and job.current_segment_idx==1
    assert job.failure_kind is None and len(job.segments)==3
    m=json.loads((p/'manifest.json').read_text())
    assert m['two_electrodes']['salt_mM']==300
    assert m['electrode_extensions'][0]['steps']==1200000
    previous='rung_p100'
    for row in m['segments'][1:]:
        text=(p/f"{row['name']}.conf").read_text()
        assert f'binCoordinates output/{previous}.coor' in text
        assert f'binVelocities output/{previous}.vel' in text
        assert f'outputName output/{row["name"]}' in text
        assert 'tclForcesScript electrode_forces.tcl' in text
        assert 'langevinPiston off' in text and 'timestep 2' in text
        assert row['steps']==600000
        previous=row['name']
    assert m['segments'][1]['seed']!=m['segments'][2]['seed']
    assert (p/'rung_p100.conf').read_bytes()==before
    assert (p/'output/rung_p100.coor').read_text()=='saved checkpoint'
    with pytest.raises(ValueError,match='Only a finished'):
        extend_equilibration(old.job_id,tmp_path)


@pytest.mark.parametrize('problem',['density','confinement','missing_checkpoint','incomplete_run'])
def test_extension_refuses_non_convergence_failures(tmp_path,finished,problem):
    job,p=finished
    if problem in ('density','confinement'):
        report=dict(passed=False,confined=True,bulk_reference_validated=True)
        report['confined' if problem=='confinement' else 'bulk_reference_validated']=False
        (p/'output/rung_p100.electrode-health.json').write_text(json.dumps(report))
    elif problem=='missing_checkpoint':(p/'output/rung_p100.vel').unlink()
    else:job.segments[0].status='failed';job.save(tmp_path)
    with pytest.raises(ValueError):extend_equilibration(job.job_id,tmp_path)
    assert len(list(p.glob('*.conf')))==1


def test_worker_recovery_cannot_bypass_electrode_completion_gate(tmp_path,finished,monkeypatch):
    from backend.core import namd_runner, namd_electrode_health
    job,p=finished
    job.status=MdStatus.running;job.current_segment_idx=len(job.segments);job.failure_kind=None
    monkeypatch.setattr(namd_runner,'is_running',lambda _:False)
    monkeypatch.setattr(namd_runner,'_external_process_running',lambda *a:False)
    monkeypatch.setattr(namd_electrode_health,'electrode_skip_check',lambda *a:{'passed':False,'reason':'Ion profiles are drifting'})
    namd_runner.reconcile_job_status(job,tmp_path)
    assert job.status==MdStatus.failed and job.failure_kind=='electrode_equilibration'
    assert 'Ion profiles are drifting' in job.error
    job.status=MdStatus.running
    monkeypatch.setattr(namd_electrode_health,'electrode_skip_check',lambda *a:{'passed':True})
    namd_runner.reconcile_job_status(job,tmp_path)
    assert job.status==MdStatus.completed and job.error is None and job.failure_kind is None
