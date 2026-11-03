"""Durable remote deletion receipts, independent of disposable job folders."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path, PurePosixPath
from shlex import quote
from types import SimpleNamespace

from backend.core.alpine_cancel import SchedulerCancellationError, cancel_job

logger = logging.getLogger(__name__)
_locks = {}


def record(workspace, job, conn):
    folder = Path(workspace) / 'alpine_deletions'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f'{job.job_id}.json'
    if path.exists():
        return path
    data = {key: getattr(job, key, None) for key in (
        'job_id', 'slurm_job_id', 'remote_scratch_dir', 'remote_project_dir',
        'cluster_name',
    )}
    user = getattr(conn, 'user', '')
    scratch = PurePosixPath(data.get('remote_scratch_dir') or '')
    if not user and scratch.parts[:3] == ('/', 'scratch', 'alpine') and len(scratch.parts) > 3:
        user = scratch.parts[3]
    data.update(host=getattr(conn, 'host', ''), user=user, cancelled=False)
    _save(path, data)
    return path


def _save(path, data):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


async def process(path, conn):
    lock = _locks.setdefault(str(path.resolve()), asyncio.Lock())
    async with lock:
        if not path.exists():
            return
        data = json.loads(path.read_text())
        for key in ('host', 'user'):
            if data.get(key) and data[key] != getattr(conn, key, ''):
                raise RuntimeError('Reconnect to the original Alpine account to finish deleting this job')
        paths = []
        for key in ('remote_scratch_dir', 'remote_project_dir'):
            raw = data.get(key)
            if not raw:
                continue
            p = PurePosixPath(raw)
            if not p.is_absolute() or '..' in p.parts or p.name != data['job_id'] or len(p.parts) < 4:
                raise RuntimeError('Refusing remote cleanup outside a job-specific directory')
            paths.append(str(p))
        if not data['cancelled']:
            job = SimpleNamespace(**data, slurm_diagnostics=None, slurm_state=None)
            try:
                await cancel_job(job, conn=conn)
            except SchedulerCancellationError:
                # A completed allocation may have aged out of scancel's view.
                result = await conn.run(
                    f"sacct -j {quote(str(job.slurm_job_id))} --format=JobIDRaw,State --parsable2 --noheader",
                    timeout=10,
                )
                states = [row.split('|')[1].split()[0] for row in result.stdout.splitlines()
                          if row.startswith(str(job.slurm_job_id) + '|') and row.split('|')[1].strip()]
                terminal = {'COMPLETED', 'CANCELLED', 'FAILED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'PREEMPTED', 'BOOT_FAIL', 'DEADLINE', 'REVOKED'}
                if result.rc or len(states) != 1 or states[0] not in terminal:
                    raise
            data['cancelled'] = True
            _save(path, data)
        if paths:
            result = await conn.run('rm -rf -- ' + ' '.join(map(quote, paths)), timeout=60)
            if result.rc:
                raise RuntimeError(f'Alpine file deletion failed: {result.stderr}')
        path.unlink()


async def drain(workspace, conn):
    if not conn.is_connected():
        return
    for path in (Path(workspace) / 'alpine_deletions').glob('*.json'):
        try:
            await process(path, conn)
        except Exception:
            logger.exception('Deferred Alpine deletion failed; retained for retry: %s', path.name)


async def prepare(workspace, job, conn):
    """Persist intent before removing local files; online deletion must cancel first."""
    if job.execution_target != 'alpine' or not (job.slurm_job_id or job.remote_scratch_dir):
        return
    path = record(workspace, job, conn)
    if conn.is_connected():
        await process(path, conn)
