"""Check the user's failed input through the managed runner in an isolated copy."""
import asyncio
from dataclasses import asdict,replace
import json
from pathlib import Path
import shutil
import subprocess
import numpy as np
from backend.core.oxdna_submodel import installation
from backend.api.headless_oxdna_build import start_relaxation,wait_for_terminal,_use_workspace
from backend.api.routes_oxdna import get_oxdna_display,get_oxdna_error_log
from backend.core.oxdna_job import OxdnaJob,OxdnaStatus
from backend.core.oxdna_runner import load_stage_specs


def run(output):
    output=Path(output).resolve();engines=installation();controls=[]
    benchmark=Path('.development-artifacts/oxdna-submodel-benchmark-20261110').resolve()
    for case in ('full_mobile','cropped'):
        before=benchmark/'adapter-check'/case/'after'
        after=output/'controls'/case;after.mkdir(parents=True)
        text=(before/'input').read_text().replace('interaction_type = DNA2','interaction_type = SubmodelDNA2')
        text+=f"\nplugin_search_path = {engines['plugins']}\n"
        (after/'input').write_text(text)
        with (after/'log').open('w') as log:subprocess.run([engines['md'],'input'],cwd=after,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=30)
        old=np.loadtxt(before/'last_conf.dat',skiprows=3);new=np.loadtxt(after/'last_conf.dat',skiprows=3)
        np.testing.assert_array_equal(old,new)
        e0=np.loadtxt(before/'energy.dat');e1=np.loadtxt(after/'energy.dat')
        delta=e0[:,1]-e1[:,1]
        assert np.ptp(delta)<2e-6,delta
        controls.append({'case':case,'particle_rows':'exactly identical','constant_energy_offset':float(np.mean(delta))})
    ws=output/'workspace';jid='52d968f5e2cc'
    shutil.copytree(Path('workspace/oxdna_jobs')/jid,ws/'oxdna_jobs'/jid)
    job=OxdnaJob.load(jid,ws);jd=job.job_dir(ws)
    specs=[replace(s,steps=10000,print_conf_interval_override=100) for s in load_stage_specs(jd)]
    job.stages=[s.to_status() for s in specs];job.status=OxdnaStatus.queued;job.error=None;job.pid=None;job.oxdna_pid=None
    job.run_config['steps']=10000;job.run_config['steps_per_frame']=100;job.save(ws)
    (jd/'stages_spec.json').write_text(json.dumps([asdict(s) for s in specs],indent=2))
    start_relaxation(jid,ws)
    final=wait_for_terminal(jid,ws,timeout=60,poll_s=.5).to_dict()
    assert final['status']=='completed',final.get('error')
    with _use_workspace(ws):
        display=asyncio.run(get_oxdna_display(jid));diagnostic=asyncio.run(get_oxdna_error_log(jid))
    assert display['ready'] and display['n_positions']==1134
    assert diagnostic['diagnostics']['oxdna_bin']==engines['md']
    result={'controls':controls,'managed_job':final,'display_positions':display['n_positions'],'diagnostics':diagnostic['diagnostics']}
    (output/'managed-results.json').write_text(json.dumps(result,indent=2));print('managed',final['status'],final['health_samples'][-1],diagnostic['diagnostics'],flush=True)

if __name__=='__main__':
    import sys
    run(sys.argv[1])
