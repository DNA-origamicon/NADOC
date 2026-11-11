"""Exercise real queued -> detached relaxation -> production child -> display APIs."""
import asyncio
import json
from pathlib import Path
import shutil

from backend.api.headless_oxdna_build import create_job, start_relaxation, wait_for_terminal, _use_workspace, _scratch_job_design
from backend.api.routes_oxdna import put_oxdna_submodel, get_oxdna_display, append_oxdna_run, RunRequest
from backend.api.simulation_submodel import SubmodelSelection
from backend.core.models import Design
from backend.core.oxdna_job import OxdnaJob
from scripts.agent_structure_guard import audit


def run(output):
    output=Path(output).resolve();output.mkdir(exist_ok=False,parents=True)
    ws=output/'workspace';ws.mkdir()
    source=Path('workspace/duplex.nadoc').resolve()
    design=Design.from_json(source.read_text());proof=audit(design)
    # Keep the known full-relaxation parent for the second, independent continuation test.
    parent=Path('workspace/oxdna_jobs/c49058f52282')
    shutil.copytree(parent,ws/'oxdna_jobs'/parent.name)
    selection=SubmodelSelection.model_validate_json((parent/'submodel_selection.json').read_text())
    fresh=create_job(design,ws,mc_steps=1000,md_relax_steps=1000000,equil_steps=100000,
                     min_bp_retained=.5,max_relax_retries=0,design_source_path=str(source))
    jid=fresh['job_id']
    # Select the middle 14 bp in this fresh job's actual displayed coordinates.
    # A box fitted to a bent relaxed parent is not the same region on this seed.
    import numpy as np
    from experiments.oxdna_submodel.production import duplex_box
    with _use_workspace(ws):
        initial=asyncio.run(get_oxdna_display(jid))
    selection=duplex_box(np.array([p['backbone_position'] for p in initial['positions']]),
                        np.array([p['bp_index'] for p in initial['positions']]))
    with _use_workspace(ws):
        asyncio.run(put_oxdna_submodel(jid,selection))
    manifest={'source':str(source),'source_audit':proof,'job_id':jid,'selection':selection.model_dump(mode='json')}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    start_relaxation(jid,ws)
    relaxed=wait_for_terminal(jid,ws,timeout=180,poll_s=.5).to_dict()
    print('relaxation',relaxed['status'],relaxed.get('error'),flush=True)
    if relaxed['status']!='completed':raise RuntimeError(relaxed.get('error'))
    with _use_workspace(ws),_scratch_job_design(jid,ws):
        child=asyncio.run(append_oxdna_run(jid,RunRequest(steps=10000,steps_per_frame=100,submodel=selection)))
    start_relaxation(child['job_id'],ws)
    produced=wait_for_terminal(child['job_id'],ws,timeout=180,poll_s=.5).to_dict()
    print('production',produced['status'],produced.get('error'),flush=True)
    if produced['status']!='completed':raise RuntimeError(produced.get('error'))
    with _use_workspace(ws):
        display=asyncio.run(get_oxdna_display(child['job_id']))
    assert display['ready'] and display['n_positions']==84
    manifest.update(production_job_id=child['job_id'],display_positions=display['n_positions'],
                    relaxation=OxdnaJob.load(jid,ws).to_dict(),production=OxdnaJob.load(child['job_id'],ws).to_dict())
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print('full-context display',display['n_positions'],flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output');run(p.parse_args().output)
