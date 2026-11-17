"""Contract tests for event-driven production-ramp alerts; no native simulation."""
import json

from scripts.watch_oxdna_ramp import monitor


def fixture(directory, status, count=13):
    specs=[]; stages=[]; progress={}; health=[]
    for i in range(count):
        name=f'{i+1}_thermal'
        specs.append({'name':name,'temperature':f'{298.15+5*i}K','steps':2_000_000,
                      'backend':'CUDA','interaction':'CpdDNA2','min_bp_retained':0,
                      'thermal_ramp':{'check_pairing':False,'consecutive_passes':2}})
        stages.append({'name':name,'status':'done' if status=='completed' else 'running'})
        if status=='completed':
            d=directory/name;d.mkdir()
            (d/'input.txt').write_text('backend = CUDA\ninteraction_type = CpdDNA2\nuse_edge = true')
            (d/'oxdna.log').write_text('NADOC_CPD_CUDA_V1\nEND OF THE SIMULATION, everything went OK!')
            (d/'last_conf.dat').touch()  # Hash-only fixture, not a molecular configuration.
            progress[name]={'decision':'done','metrics':{'passed':True},'consecutive_passes':2}
            health.append({'stage':name,'passed':True,'bp_retained_fraction':0.0})
    job={'job_id':'fixture','backend':'CUDA','status':status,'stages':stages,'current_stage_idx':0,
         'run_config':{'thermal_progress':progress},'health_samples':health}
    (directory/'job.json').write_text(json.dumps(job))
    (directory/'stages_spec.json').write_text(json.dumps(specs))


def events(output):
    return [json.loads(line) for line in (output/'events.jsonl').read_text().splitlines()]


def test_completed_ramp_audits_every_stage_even_when_fully_melted(tmp_path):
    fixture(tmp_path,'completed')
    output=tmp_path/'audit'
    assert monitor(tmp_path,output)==0
    assert sum(e['event']=='stage_passed' for e in events(output))==13
    assert events(output)[-1]['status']=='completed'


def test_failure_triggers_terminal_alert(tmp_path):
    fixture(tmp_path,'failed')
    output=tmp_path/'audit'
    assert monitor(tmp_path,output)==2
    assert events(output)[-1]['status']=='failed'


def test_worker_stall_triggers_without_status_polling(tmp_path,monkeypatch):
    fixture(tmp_path,'running')
    output=tmp_path/'audit'
    calls=[]
    def timeout(*args):
        calls.append(args)
        return [],[],[]
    monkeypatch.setattr('scripts.watch_oxdna_ramp.select.select',timeout)
    assert monitor(tmp_path,output)==3
    assert len(calls)==1
    assert events(output)[-1]['event']=='stalled_worker'


def test_fixed_dwell_completion_does_not_claim_stability(tmp_path):
    fixture(tmp_path,'completed')
    job=json.loads((tmp_path/'job.json').read_text())
    specs=json.loads((tmp_path/'stages_spec.json').read_text())
    for spec in specs:
        spec['thermal_ramp']['gate']=False
        report=job['run_config']['thermal_progress'][spec['name']]
        report.update(gate_enabled=False,consecutive_passes=0,metrics={'passed':False})
    (tmp_path/'job.json').write_text(json.dumps(job))
    (tmp_path/'stages_spec.json').write_text(json.dumps(specs))
    assert monitor(tmp_path,tmp_path/'audit')==0
    assert all(not e['check']['metrics']['passed'] for e in events(tmp_path/'audit') if e['event']=='stage_passed')
