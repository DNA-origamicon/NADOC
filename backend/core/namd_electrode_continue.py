"""Append fixed-cell equilibration checkpoints without rebuilding the physical system."""
import copy
import json
import math
import re
import threading
import time
from pathlib import Path

from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus

_LOCK = threading.RLock()


def can_extend(report):
    return bool(not report.get('passed') and report.get('confined')
                and report.get('bulk_reference_validated')
                and (not report.get('reason') or report.get('sampling_sufficient') is False))


def extend_equilibration(job_id, workspace, duration_ns=2.4):
    """Queue <=1.2 ns chunks, retaining all old outputs and convergence evidence."""
    if not math.isfinite(duration_ns) or not 0 < duration_ns <= 100:
        raise ValueError('Extension duration must be between 0 and 100 ns.')
    with _LOCK:
        job=MdJob.load(job_id,Path(workspace))
        if job.status != MdStatus.failed or job.failure_kind != 'electrode_equilibration':
            raise ValueError('Only a finished electrode run with unmet equilibration checks can be extended.')
        package=job.package_dir(Path(workspace)); path=package/'manifest.json'
        manifest=json.loads(path.read_text())
        rows=manifest.get('segments',[])
        if not manifest.get('two_electrodes') or not rows or not all(s.status=='done' for s in job.segments):
            raise ValueError('Finish all planned electrode chunks before extending equilibration.')
        last=rows[-1]; old_name=last['name']; output=package/'output'
        report=json.loads((output/f'{old_name}.electrode-health.json').read_text())
        if not can_extend(report):
            raise ValueError('Correct confinement, missing evidence or solvent loading before extending equilibration.')
        if not all((output/f'{old_name}.{ext}').is_file() and (output/f'{old_name}.{ext}').stat().st_size for ext in ('coor','vel','xsc')):
            raise ValueError('The final checkpoint is incomplete.')
        template=(package/f'{old_name}.conf').read_text()
        if len(re.findall(r'(?m)^run\s+\d+\s*$',template)) != 1:
            raise ValueError('Continuation requires a single-run checkpoint configuration.')
        dt=float(last.get('timestep_fs',2.))
        if not math.isfinite(dt) or dt<=0:raise ValueError('Invalid checkpoint timestep.')
        total=int(math.ceil(duration_ns*1e6/dt/20))*20
        chunk=max(20,int(1.2e6/dt/20)*20)
        previous=old_name; remaining=total; prepared=[]
        count=len(manifest.get('electrode_extensions',[]))+1
        while remaining:
            steps=min(chunk,remaining); number=len(prepared)+1
            name=f"{old_name.rsplit('_p',1)[0]}_p100_extra{count}_{number}"
            if (package/f'{name}.conf').exists():raise ValueError('Extension configuration already exists.')
            row=copy.deepcopy(last);row.update(name=name,previous=previous,steps=steps,percent=100,reinit=False)
            # Replace identifiers simultaneously: the new restart input must not
            # be mistaken for the new output name on a second replacement pass.
            replacements={old_name:name,last['previous']:previous}
            text=re.sub('|'.join(re.escape(k) for k in sorted(replacements,key=len,reverse=True)),
                        lambda match:replacements[match.group()],template)
            text=re.sub(r'(?m)^run\s+\d+\s*$',f'run {steps}\n',text)
            seed_match=re.search(r'(?m)^seed\s+(\d+)',template)
            seed=((int(seed_match.group(1)) if seed_match else 5489)+1000*count+number) % 2147483646 + 1
            text=re.sub(r'(?m)^seed\s+\d+',f'seed {seed}',text) if seed_match else f'seed {seed}\n'+text
            row['seed']=seed
            prepared.append((row,text));previous=name;remaining-=steps
        for row,text in prepared:
            (package/f"{row['name']}.conf").write_text(text)
            rows.append(row)
            job.segments.append(MdSegmentStatus(name=row['name'],stage=row['stage'],percent=100,steps=row['steps']))
        manifest.setdefault('electrode_extensions',[]).append(dict(created_at=time.time(),
            requested_ns=duration_ns,steps=total,timestep_fs=dt,checkpoint=old_name,
            prior_validation=report,segments=[row['name'] for row,_ in prepared]))
        for target in (path,package/'nadoc_md_run.json'):
            temp=target.with_suffix('.json.extension.tmp');temp.write_text(json.dumps(manifest,indent=2)+'\n');temp.replace(target)
        job.status=MdStatus.queued;job.error=None;job.failure_kind=None;job.decision=None
        job.current_segment_idx=len(job.segments)-len(prepared)
        job.save(Path(workspace))
        return job
