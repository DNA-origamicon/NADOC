"""Verify continuation and visualization contracts against actual completed jobs."""
import asyncio
import json
from pathlib import Path
from starlette.requests import Request
from backend.api import routes_oxdna as api
from backend.api.headless_oxdna_build import _use_workspace, _scratch_job_design, start_relaxation, wait_for_terminal
from backend.core.oxdna_job import OxdnaJob


def run(output):
    output=Path(output).resolve();ws=output/'workspace'
    manifest=json.loads((output/'manifest.json').read_text())
    results=[]
    for parent in (manifest['job_id'],'c49058f52282'):
        with _use_workspace(ws),_scratch_job_design(parent,ws):
            child=asyncio.run(api.append_oxdna_run(parent,api.RunRequest(steps=10000,steps_per_frame=100)))
        jid=child['job_id'];start_relaxation(jid,ws)
        result=wait_for_terminal(jid,ws,timeout=120,poll_s=.5).to_dict()
        assert result['status']=='completed',result.get('error')
        assert result['submodel'], 'Production must not silently run the full model'
        jd=OxdnaJob.load(jid,ws).job_dir(ws)
        native=int((jd/'1_production/submodel/topology.top').read_text().split()[0])
        assert native==result['submodel']['simulated_nucleotides']<84
        if parent==manifest['job_id']:
            pjd=OxdnaJob.load(parent,ws).job_dir(ws)
            assert json.loads((jd/'submodel_plan.json').read_text())['mobile_source_indices']==json.loads((pjd/'submodel_plan.json').read_text())['mobile_source_indices']
        async def receive():
            await asyncio.sleep(3600)
        request=Request({'type':'http','method':'GET','path':'/','headers':[]},receive)
        async def visuals():
            calls={
                'display': lambda:api.get_oxdna_display(jid),
                'flex':lambda:api.get_oxdna_rmsf(jid),
                'deviation':lambda:api.get_oxdna_deviation(jid),
                'strain':lambda:api.get_oxdna_strain(jid),
                'trajectory':lambda:api.get_oxdna_trajectory(jid,request,scope='job'),
                'occupancy':lambda:api.get_oxdna_occupancy(jid,request,scope='job',max_frames=100),
                'atomistic':lambda:api.get_oxdna_display_atomistic(jid),
            }
            summary={}
            for name,call in calls.items():
                data=await call();assert data.get('ready',True),(name,data)
                summary[name]={k:v for k,v in data.items() if k in ('ready','n_frames','n_positions','n_atoms','n_clusters','reason')}
                print(jid,name,summary[name],flush=True)
            return summary
        with _use_workspace(ws):summary=asyncio.run(visuals())
        results.append({'parent':parent,'job':result,'native_particles':native,'visualizations':summary})
    (output/'continuation-checks.json').write_text(json.dumps(results,indent=2))
    manifest.update(job_id=results[0]['job']['job_id'],display_relaxed=True,inspect_visualizations=True)
    (output/'visual-manifest.json').write_text(json.dumps(manifest,indent=2))

if __name__=='__main__':
    import sys
    run(sys.argv[1])
