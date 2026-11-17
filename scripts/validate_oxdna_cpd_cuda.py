"""Explicit native GPU ramp validation from existing, completed CPD jobs.

Bounded temporary workspace; retains only a compact receipt. Copies preserve the
source design history and frozen CPD model byte-for-byte. No structure authoring.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import shutil
import tempfile


def clone_parent(source, workspace):
    meta=json.loads((source/'job.json').read_text())
    assert meta['status']=='completed'
    dest=workspace/'oxdna_jobs'/meta['job_id']; dest.mkdir(parents=True)
    # Only frozen inputs and terminal checkpoints, never bulk trajectories.
    for name in ['design.json','topology.top','conf.dat','design_ref.dat','cpd.dat','cpd_model.json',
                 'cpd_manifest.json','stages_spec.json','oxDNA2_average_sequence_parameters.txt']:
        if (source/name).exists(): shutil.copy2(source/name,dest/name)
    shutil.copytree(source/'cpd_plugin',dest/'cpd_plugin')
    for stage in meta['stages']:
        old=source/stage['name'];new=dest/stage['name'];new.mkdir()
        if (old/'last_conf.dat').exists(): shutil.copy2(old/'last_conf.dat',new/'last_conf.dat')
    meta.update(archived=False,archive_path=None)
    (dest/'job.json').write_text(json.dumps(meta))
    (dest/'validation_source.json').write_text(json.dumps({'source':str(source),
        'design_sha256':hashlib.sha256((source/'design.json').read_bytes()).hexdigest()}))
    return meta['job_id']


def run(source):
    from backend.api.headless_oxdna_build import _use_workspace,_scratch_job_design,start_relaxation
    from backend.api.routes_oxdna import _prepare_run_job,RunRequest,get_oxdna_trajectory_meta
    from backend.core.oxdna_thermal_ramp import ThermalRamp
    from backend.core.oxdna_runner import stop_job
    from scripts.validate_oxdna_cpd import wait_job
    with tempfile.TemporaryDirectory(prefix='nadoc-cpd-cuda-ramp-') as td:
        workspace=Path(td); parent=clone_parent(source,workspace); child=None
        try:
            with _use_workspace(workspace),_scratch_job_design(parent,workspace):
                child=_prepare_run_job(parent,RunRequest(backend='CUDA',steps_per_frame=1000,
                    thermal_ramp=ThermalRamp(start_c=25,end_c=85,step_c=5,gate=False,block_steps=10000)))
            start_relaxation(child.job_id,workspace)
            job=wait_job(child.job_id,workspace)
            jd=job.job_dir(workspace)
            if job.status.value!='completed': raise RuntimeError(job.error)
            assert job.backend=='CUDA' and len(job.stages)==13
            for stage in job.stages:
                inp=(jd/stage.name/'input.txt').read_text();log=(jd/stage.name/'oxdna.log').read_text()
                assert 'backend = CUDA' in inp and 'interaction_type = CpdDNA2' in inp
                assert 'use_edge = true' in inp
                assert 'NADOC_CPD_CUDA_V1' in log and stage.status=='done'
            with _use_workspace(workspace):
                meta=asyncio.run(get_oxdna_trajectory_meta(job.job_id,scope='thermal'))
            result={'source':str(source),'isomers':[e.get('stereochemistry', json.loads((jd/'cpd_model.json').read_text())['stereochemistry']) for e in json.loads((jd/'cpd_manifest.json').read_text())['endpoints']],
                    'status':job.status.value,'backend':job.backend,'temperatures':13,'steps_per_temperature':10000,
                    'gate':False,'markers':len(meta['markers']),'frames':meta['n_frames'],
                    'qualification':'software workflow validation; not equilibration or Tm convergence'}
            assert result['markers']==13
            return result
        finally:
            if child:
                stop_job(child.job_id,workspace)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('parents',nargs='+',type=Path);parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args(); results=[]
    for parent in args.parents:
        result=run(parent.resolve());results.append(result);print(json.dumps(result),flush=True)
        args.receipt.parent.mkdir(parents=True,exist_ok=True)
        args.receipt.write_text(json.dumps(results,indent=2)+'\n')
