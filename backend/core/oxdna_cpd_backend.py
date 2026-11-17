"""Recorded backend changes for idle CPD jobs; preserve checkpoints and gate state."""
from dataclasses import asdict, replace
import json
import time
from typing import Literal

from pydantic import BaseModel


class CpdBackendRequest(BaseModel):
    backend: Literal['CPU', 'CUDA']


def change_backend(job, workspace, backend):
    from backend.core.oxdna_runner import load_stage_specs
    from backend.physics.oxdna_cpd import verify, plugin_directory
    from backend.physics.oxdna_cpd_cuda import add_cuda
    if job.status not in {'queued', 'stopped', 'failed'}:
        raise ValueError('Stop the CPD job before changing its execution backend.')
    jd = job.job_dir(workspace)
    if not (jd / 'cpd_manifest.json').is_file():
        raise ValueError('This backend-change operation is for CPD jobs only.')
    manifest = verify(jd)
    specs = load_stage_specs(jd)
    remaining = specs[job.current_stage_idx:]
    if not remaining or any(s.sim_type == 'MD' and s.interaction != 'CpdDNA2' for s in remaining):
        raise ValueError('The remaining CPD protocol is missing or inconsistent.')
    if job.backend == backend and all(s.backend == backend for s in remaining if s.sim_type == 'MD'):
        return job
    if backend == 'CUDA' and not manifest.get('cuda_plugin_sha256'):
        add_cuda(jd, manifest, plugin_directory())
        manifest_path = jd / 'cpd_manifest.json'
        temporary = jd / 'cpd_manifest.backend.tmp'
        temporary.write_text(json.dumps(manifest, indent=2)+'\n')
        temporary.replace(manifest_path)
    changes = list((job.run_config or {}).get('backend_changes', []))
    change = {'time': time.time(), 'from': job.backend, 'to': backend,
              'stage_index': job.current_stage_idx,
              'completed_steps': job.stages[job.current_stage_idx].completed_steps,
              'previous_specs': [asdict(s) for s in specs]}
    changes.append(change)
    specs = [replace(s, backend=backend) if i >= job.current_stage_idx and s.sim_type == 'MD' else s
             for i, s in enumerate(specs)]
    temporary = jd / 'stages_spec.backend.tmp'
    temporary.write_text(json.dumps([asdict(s) for s in specs], indent=2)+'\n')
    temporary.replace(jd / 'stages_spec.json')
    job.backend = backend
    job.run_config = {**(job.run_config or {}), 'backend': backend, 'backend_changes': changes}
    job.save(workspace)
    return job
