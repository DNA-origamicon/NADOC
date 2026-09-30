"""Scheduler cancellation with a verified, single-node process-stop fallback."""
from __future__ import annotations

import json
from pathlib import Path
import re
from shlex import quote

from backend.core.cluster_ssh import ClusterSSHError


class SchedulerCancellationError(RuntimeError):
    """Neither the scheduler nor compute-node verification confirmed a stop."""


async def _stop_on_node(job, conn):
    if not str(job.slurm_job_id).isdigit() or not job.remote_scratch_dir:
        raise RuntimeError('Missing job ID or scratch directory for node verification')
    result = await conn.run(
        f'sacct -j {job.slurm_job_id} --format=JobIDRaw,State,NodeList --parsable2 --noheader',
        timeout=10,
    )
    rows = [line.split('|') for line in result.stdout.splitlines()]
    rows = [r for r in rows if len(r) >= 3 and r[0] == str(job.slurm_job_id)]
    if result.rc or len(rows) != 1 or rows[0][1] not in {'RUNNING', 'COMPLETING'}:
        raise RuntimeError('Accounting did not identify one active allocation')
    node = rows[0][2]
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', node) or node in {'None', 'Unknown'}:
        raise RuntimeError('No single compute hostname available')
    source = Path(__file__).with_name('alpine_node_stop.py').read_text()
    remote = 'python3 -c ' + quote(source) + ' ' + quote(str(job.slurm_job_id)) + ' ' + quote(job.remote_scratch_dir)
    # Dedicated known-hosts file: pin first contact; never accept a changed key.
    known_hosts = f'{job.remote_scratch_dir}/.nadoc-node-known-hosts'
    command = (
        'timeout --kill-after=2s 15s ssh -o BatchMode=yes -o ConnectTimeout=5 '
        '-o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=' + quote(known_hosts)
        + ' ' + quote(node) + ' ' + quote(remote)
    )
    result = await conn.run(command, timeout=20)
    if result.rc:
        raise RuntimeError(f'Compute-node stop failed (exit {result.rc}): {result.stderr[-500:]}')
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    if evidence.get('job_id') != str(job.slurm_job_id) or evidence.get('processes_stopped') is not True:
        raise RuntimeError('Compute node did not confirm the requested process stop')
    evidence['node'] = node
    evidence['last_accounting_state'] = rows[0][1]
    job.slurm_diagnostics = {**(job.slurm_diagnostics or {}), 'direct_stop': evidence}
    # Retain the stale accounting report in evidence, not as a live RUNNING badge.
    # The allocation's current scheduler state is unknown until control recovers.
    job.slurm_state = None


async def cancel_job(job, *, conn):
    if not job.slurm_job_id:
        return False
    try:
        result = await conn.run(
            f'timeout --kill-after=2s 20s scancel --ctld --quiet {quote(str(job.slurm_job_id))}',
            timeout=30,
        )
        if result.rc == 0:
            return True
        reason = f'scancel exited {result.rc}: {result.stderr.strip()[:500]}'
    except ClusterSSHError as exc:
        if exc.kind != 'timeout':
            raise
        reason = str(exc)
    try:
        await _stop_on_node(job, conn)
        return True
    except (RuntimeError, ClusterSSHError, OSError, ValueError, IndexError) as exc:
        raise SchedulerCancellationError(
            f'Alpine did not confirm termination of SLURM job {job.slurm_job_id}. '
            f'It may still be running; download has not started. Scheduler: {reason}. '
            f'Node verification: {exc}'
        ) from exc
