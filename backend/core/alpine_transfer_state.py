"""Transfer-owned state, independent of stale server copies of job.json."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def state_path(job, workspace: Path) -> Path:
    return job.job_dir(workspace) / 'alpine_transfer.json'


def read_state(job, workspace: Path) -> dict:
    try:
        return json.loads(state_path(job, workspace).read_text())
    except (OSError, ValueError):
        return {}


def submission_identity(job) -> dict:
    """Bind a transfer to the allocation whose results it downloaded."""
    return {'slurm_job_id': job.slurm_job_id, 'queued_at': job.queued_at}


def matches_submission(record: dict, job, workspace: Path) -> bool:
    if 'submission' in record:
        return record['submission'] == submission_identity(job)
    # Older workers did not record an allocation. Their sidecar predates a later
    # continuation's queue timestamp. Keep legacy terminal/snapshot downloads valid.
    if job.queued_at:
        try:
            return state_path(job, workspace).stat().st_mtime >= job.queued_at
        except OSError:
            return False
    return True


def apply_transfer_state(job, workspace: Path) -> None:
    record = read_state(job, workspace)
    status = record.get('download_status')
    if not status:
        return
    current = job.download_status or {}
    if not matches_submission(record, job, workspace):
        # Also repair records previously saved after adopting the stale sidecar.
        if record.get('id') and current.get('worker_transfer_id') == record['id']:
            job.download_status = None
        return
    # Once this transfer has been adopted, backend indexing owns processing state.
    if (current.get('worker_transfer_id') == record.get('id')
            and current.get('state') in {'processing', 'verified'}):
        return
    job.download_status = status
    if record.get('done') and status.get('state') == 'verified':
        job.live_frame = None


async def recover_downloads(workspace: Path, conn, *, reconnect: bool = False) -> None:
    """Reattach unfinished transfers, including stopped and preserved jobs."""
    from backend.core.md_job import MdJob
    from backend.core.md_executor import fetch_outputs
    import logging

    for job in MdJob.list_jobs(workspace):
        if job.execution_target != 'alpine':
            continue
        state = (job.download_status or {}).get('state')
        if state != 'downloading' and not (reconnect and state == 'interrupted'):
            continue
        # Legacy scheduler downloads retain their existing reconciliation path.
        record = read_state(job, workspace)
        if not record or not matches_submission(record, job, workspace):
            continue
        try:
            await fetch_outputs(job, workspace, conn=conn)
        except Exception:
            logging.getLogger(__name__).exception('[%s] transfer recovery failed', job.job_id)
