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


def apply_transfer_state(job, workspace: Path) -> None:
    record = read_state(job, workspace)
    status = record.get('download_status')
    if not status:
        return
    current = job.download_status or {}
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
        if not read_state(job, workspace):
            continue
        try:
            await fetch_outputs(job, workspace, conn=conn)
        except Exception:
            logging.getLogger(__name__).exception('[%s] transfer recovery failed', job.job_id)
