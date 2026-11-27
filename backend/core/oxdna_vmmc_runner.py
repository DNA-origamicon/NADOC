"""Detached CPU VMMC controller; fixed production weights, independent replica seeds."""
import json
import shutil
import time

import numpy as np

from backend.core.oxdna_job import OxdnaStatus
from backend.core.oxdna_vmmc import VmmcMelting, write_order_parameters, render_input, histogram, tune_weights, analyse, VMMC_ENGINE_REVISION, VMMC_ENGINE_SIGNATURE


def save_weights(path, weights):
    path.write_text(''.join(f'{i} {weight:.16g}\n' for i,weight in enumerate(weights)))


async def run(job, workspace, specs):
    from backend.core import oxdna_runner as runner
    root=job.job_dir(workspace)
    cfg=VmmcMelting.model_validate(job.run_config['vmmc_melting'])
    binary=runner.find_oxdna()
    if not binary:
        raise ValueError('CPU oxDNA executable is unavailable.')
    if not runner._oxdna_contains_signature(binary, VMMC_ENGINE_SIGNATURE):
        raise ValueError('VMMC requires the periodic-image-safe oxDNA backend. Rebuild with scripts/build-oxdna.sh.')
    # A completed stage from an older sampler cannot certify this protocol.
    # Rewind its entire suffix, preserving every previous attempt in stage archives.
    for index,spec in enumerate(specs):
        if job.stages[index].status != 'done': continue
        try:
            receipt=json.loads((root/spec.name/'vmmc_complete.json').read_text())
        except (OSError,ValueError):
            receipt={}
        if receipt.get('engine_revision') != VMMC_ENGINE_REVISION or receipt.get('steps') != spec.steps or receipt.get('seed') != spec.seed:
            for stage in job.stages[index:]:
                stage.status='pending';stage.completed_steps=0
            job.run_config.pop('vmmc_result',None)
            previous_results=[root/name for name in ('vmmc_result.json','vmmc_melting.csv') if (root/name).exists()]
            if previous_results:
                archive=root/f'interrupted_analysis_{time.time_ns()}';archive.mkdir()
                for path in previous_results: path.rename(archive/path.name)
            job.run_config.setdefault('vmmc_restarts',[]).append({
                'time':time.time(),'from_stage':spec.name,
                'reason':'Completed stage lacks a matching periodic-image-safe engine receipt.'})
            break
    job.run_config['vmmc_engine_revision']=VMMC_ENGINE_REVISION
    n_pairs=write_order_parameters(root)
    job.backend='CPU';job.status=OxdnaStatus.running;job.error=None
    job.save(workspace)
    try:
        for index,spec in enumerate(specs):
            if job.stages[index].status == 'done': continue
            directory=root/spec.name;directory.mkdir(exist_ok=True)
            # Whole-stage replay avoids mixing stale histograms with checkpoints after interruption.
            # Completed stages and all original user inputs remain intact.
            if (directory/'input.txt').exists():
                archive=directory/f'interrupted_{time.time_ns()}';archive.mkdir()
                for path in list(directory.iterdir()):
                    if path.is_file(): path.rename(archive/path.name)
            tuning='_tune_' in spec.name
            if tuning:
                if index:
                    weights=np.loadtxt(root/specs[index-1].name/'next_weights.txt',ndmin=2)[:,1]
                    conf=root/specs[index-1].name/'last_conf.dat'
                else:
                    weights=np.ones(n_pairs+1);conf=root/'conf.dat'
            else:
                weights=np.loadtxt(root/'vmmc_frozen_weights.txt',ndmin=2)[:,1]
                conf=root/specs[cfg.tuning_rounds-1].name/'last_conf.dat' if '_equil_' in spec.name else root/specs[index-1].name/'last_conf.dat'
            save_weights(directory/'weights.txt',weights)
            (directory/'input.txt').write_text(render_input(root,directory,spec,cfg,conf))
            stage=job.stages[index];stage.status='running';stage.started_at=time.time();stage.completed_steps=0
            job.current_stage_idx=index;job.save(workspace)
            def pid(value):
                job.oxdna_pid=value;job.save(workspace)
            rc,_=await runner._run_oxdna_async(binary,directory/'input.txt',directory,directory/'oxdna.log',job.job_id,on_spawn=pid)
            if (root/runner._STOP_MARKER).exists():
                (root/runner._STOP_MARKER).unlink(missing_ok=True)
                stage.status='stopped';job.status=OxdnaStatus.stopped;job.save(workspace);return
            if rc:
                log_path=directory/'oxdna.log'
                # Surface the native reason in the job card, not only a generic exit code.
                errors=[]
                if log_path.exists():
                    with log_path.open() as log:
                        log.seek(max(0, log_path.stat().st_size-8192))
                        errors=[line.strip() for line in log if line.startswith('ERROR:')]
                detail=errors[-1] if errors else 'See its oxDNA log.'
                raise ValueError(f'VMMC failed in {spec.name} (exit {rc}): {detail}')
            if not runner.conf_is_restartable(directory/'last_conf.dat',job.n_nucleotides):
                raise ValueError(f'Invalid VMMC checkpoint in {spec.name}.')
            data=histogram(directory/'last_hist.dat',n_pairs,len(cfg.temperatures()))
            if tuning:
                save_weights(directory/'next_weights.txt',tune_weights(weights,data[:,1]))
                if index == cfg.tuning_rounds-1:
                    shutil.copy2(directory/'next_weights.txt',root/'vmmc_frozen_weights.txt')
            (directory/'vmmc_complete.json').write_text(json.dumps({'steps':spec.steps,'seed':spec.seed,'role':spec.name.split('_')[2],'engine_revision':VMMC_ENGINE_REVISION}))
            stage.status='done';job.current_stage_idx=index+1;job.save(workspace)
        job.run_config['vmmc_result']=analyse(root,specs,cfg,n_pairs)
        job.status=OxdnaStatus.completed;job.current_stage_idx=len(specs);job.error=None;job.save(workspace)
    except Exception as error:
        if job.current_stage_idx < len(job.stages): job.stages[job.current_stage_idx].status='failed'
        job.status=OxdnaStatus.failed;job.error=str(error);job.save(workspace)
        raise
