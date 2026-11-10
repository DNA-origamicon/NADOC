"""Bounded native stop/resume check using a completed managed submodel parent."""
import asyncio
import json
from pathlib import Path
import time
from backend.api import routes_oxdna as api
from backend.api.headless_oxdna_build import _use_workspace, _scratch_job_design, start_relaxation, wait_for_terminal
from backend.core.oxdna_job import OxdnaJob


def run(output):
    output=Path(output).resolve();ws=output/'workspace'
    parent=json.loads((output/'manifest.json').read_text())['job_id']
    with _use_workspace(ws),_scratch_job_design(parent,ws):
        child=asyncio.run(api.append_oxdna_run(parent,api.RunRequest(steps=200000,steps_per_frame=1000)))
    jid=child['job_id'];start_relaxation(jid,ws)
    deadline=time.monotonic()+30
    jd=OxdnaJob.load(jid,ws).job_dir(ws);native=jd/'1_production/submodel'
    while not (native/'trajectory.dat').exists() or (native/'trajectory.dat').stat().st_size<1000:
        if time.monotonic()>deadline:raise TimeoutError('No native trajectory')
        time.sleep(.1)
    with _use_workspace(ws):asyncio.run(api.stop_oxdna_job(jid))
    stopped=wait_for_terminal(jid,ws,timeout=30,poll_s=.2).to_dict()
    assert stopped['status']=='stopped',stopped
    before=json.loads((native/'extraction.json').read_text())
    start_relaxation(jid,ws)
    final=wait_for_terminal(jid,ws,timeout=90,poll_s=.5).to_dict()
    assert final['status']=='completed',final.get('error')
    assert final['stages'][0]['resumed']
    assert final['stages'][0]['completed_steps']>0
    assert json.loads((native/'extraction.json').read_text())==before
    execution=json.loads((native/'execution.json').read_text())
    assert execution['steps']+final['stages'][0]['completed_steps']==200000
    assert list(native.glob('trajectory.r*.dat')),list(native.iterdir())
    (output/'resume-check.json').write_text(json.dumps({'stopped':stopped,'completed':final,'execution':execution},indent=2))
    print(jid,'resumed',final['stages'][0]['completed_steps'],'remaining',execution['steps'],flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
