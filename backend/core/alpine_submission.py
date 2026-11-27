"""Durable allocation identity across stale polls, downloads and server reloads."""
from __future__ import annotations

import json
import re
import shlex
import time

from backend.core.alpine_transfer_state import atomic_json

_FIELDS = (
    'slurm_job_id', 'slurm_state', 'queued_at', 'slurm_started_at', 'resources',
    'resubmit_count', 'resumable', 'error', 'failure_kind', 'live_metrics',
    'live_frame', 'download_status', 'fetch_attempts', 'user_stopped',
    'slurm_diagnostics',
)


def read(job, workspace):
    try:
        return json.loads((job.job_dir(workspace) / 'alpine_submission.json').read_text())
    except FileNotFoundError:
        return {}


def newer(record, job):
    return bool(record and record['fields']['queued_at'] > (job.queued_at or 0))


def record_submission(job, workspace, *, recovery=None):
    atomic_json(job.job_dir(workspace) / 'alpine_submission.json', {
        'recorded_at': time.time(), 'status': job.status.value,
        'fields': {key: getattr(job, key) for key in _FIELDS},
        'recovery': recovery,
    })


def apply_submission(job, workspace):
    record = read(job, workspace)
    if newer(record, job):
        from backend.core.md_job import MdStatus
        for key, value in record['fields'].items():
            setattr(job, key, value)
        job.status = MdStatus(record['status'])


async def recover_active_submission(job, workspace, conn):
    """Resume also recovers a submission accepted by Slurm but lost by the app.

    Never launch a second writer in the same scratch directory. Only allocations
    owned by the connected user, with this exact work directory, can be adopted.
    """
    result = await conn.run("squeue --me --noheader --format='%i|%Z|%T'")
    if result.rc:
        raise RuntimeError('Cannot check for an existing Alpine allocation')
    matches = [line.split('|') for line in result.stdout.splitlines()
               if len(line.split('|')) == 3 and line.split('|')[1] == job.remote_scratch_dir]
    if not matches:
        return False
    if len(matches) != 1:
        raise RuntimeError('Multiple active allocations share this job directory; resolve them before resuming')
    slurm_id, _, state = matches[0]
    if not slurm_id.isdigit():
        raise ValueError('Unsupported active Slurm allocation identifier')
    result = await conn.run(f'scontrol show job -o {slurm_id}')
    fields = dict(re.findall(r'(\w+)=([^\s]+)', result.stdout))
    if result.rc or fields.get('WorkDir') != job.remote_scratch_dir:
        raise RuntimeError('Could not verify the existing allocation work directory')
    stamp = await conn.run(f"date -d {shlex.quote(fields['SubmitTime'])} +%s")
    if stamp.rc:
        raise RuntimeError('Could not read the existing allocation submission time')
    resources = dict(job.resources or {})
    resources.update(partition=fields['Partition'], qos=fields['QOS'],
                     cores=int(fields['NumCPUs']), walltime=fields['TimeLimit'])
    days, _, clock = fields['TimeLimit'].rpartition('-')
    hours, minutes, seconds = map(int, clock.split(':'))
    resources['walltime_h'] = int(days or 0) * 24 + hours + minutes / 60 + seconds / 3600
    memory = re.search(r'(?:^|,)mem=([\d.]+)([MGT])', fields.get('ReqTRES', ''))
    if memory:
        resources['mem_gb'] = float(memory[1]) * {'M': 1/1024, 'G': 1, 'T': 1024}[memory[2]]
    gpu = re.search(r'gres/gpu:([^,:]+):(\d+)', fields.get('TresPerNode', ''))
    if gpu:
        resources.update(gres_type=gpu[1], gpus=int(gpu[2]))
    from backend.core.md_job import MdStatus
    if job.slurm_job_id and job.slurm_job_id != slurm_id:
        job.resubmit_count = (job.resubmit_count or 0) + 1
    job.slurm_job_id = slurm_id
    job.slurm_state = state
    job.queued_at = float(stamp.stdout.strip())
    job.resources = resources
    job.status = MdStatus.running if state == 'RUNNING' else MdStatus.queued
    job.resumable = False
    job.error = job.failure_kind = job.download_status = job.live_metrics = job.live_frame = None
    job.slurm_diagnostics = None
    job.fetch_attempts = 0
    job.user_stopped = False
    record_submission(job, workspace, recovery=fields)
    job.save(workspace)
    return True
