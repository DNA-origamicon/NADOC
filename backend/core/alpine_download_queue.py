"""Non-blocking completion ownership and FIFO bulk-transfer admission.

The API and detached worker each enforce admission: the API also supports workers
started before this policy existed. Queue intent is durable; tasks are process-local.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import time
from weakref import WeakKeyDictionary

from backend.core import alpine_operations
from backend.core.alpine_transfer_state import (
    submission_identity,
)

_loops = WeakKeyDictionary()
logger = logging.getLogger(__name__)


def _state():
    return _loops.setdefault(asyncio.get_running_loop(), {
        "tasks": {}, "transfers": {}, "gate": asyncio.Lock(), "owner": None,
    })


def key(job, workspace):
    return (str(job.job_dir(workspace).resolve()), job.slurm_job_id, job.queued_at)


def pending(job, workspace):
    task = _state()["tasks"].get(key(job, workspace))
    return task is not None and not task.done()


def recovery_order(job):
    status = job.download_status or {}
    return (status.get("state") != "downloading",
            status.get("enqueued_at", job.created_at), job.job_id)


def mark_queued(job, workspace):
    status = dict(job.download_status or {})
    if status.get("state") in {"queued", "downloading", "processing", "verified"}:
        return
    status.update(state="queued", enqueued_at=time.time(), current_file=None)
    job.download_status = status
    job.save(workspace)
    alpine_operations.event("download_queued", job_id=job.job_id,
                            submission=submission_identity(job))


def schedule(job, workspace, operation):
    """Own one completion/recovery task per submission, without awaiting its I/O."""
    tasks = _state()["tasks"]
    identity = key(job, workspace)
    if pending(job, workspace):
        return False
    mark_queued(job, workspace)

    async def run():
        try:
            from backend.core.md_job import MdJob
            if key(MdJob.load(job.job_id, workspace), workspace) != identity:
                return
            await operation()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] background Alpine completion failed", job.job_id)
        finally:
            tasks.pop(identity, None)

    tasks[identity] = asyncio.create_task(run())
    return True


@asynccontextmanager
async def transfer_slot(job, workspace):
    """FIFO admission; release before local indexing so polling stays responsive."""
    state = _state()
    if state["owner"] is asyncio.current_task():
        yield
        return
    mark_queued(job, workspace)
    async with state["gate"]:
        from backend.core.md_job import MdJob
        latest = MdJob.load(job.job_id, workspace)
        if key(latest, workspace) != key(job, workspace):
            raise ValueError("Alpine submission changed while waiting to download")
        # Waiting may take hours. Preserve edits made while this entry was queued.
        # A worker's instance-level save override remains installed.
        job.__dict__.update(latest.__dict__)
        started = time.time()
        queued = (job.download_status or {}).get("enqueued_at", started)
        job.download_status = {
            **(job.download_status or {}), "state": "downloading",
            "enqueued_at": queued, "transfer_started_at": started,
        }
        job.save(workspace)
        alpine_operations.event("download_dequeued", job_id=job.job_id,
                                queue_wait_seconds=max(0, started - queued))
        state["owner"] = asyncio.current_task()
        try:
            yield
        except Exception:
            job.download_status = {**(job.download_status or {}), "state": "interrupted"}
            job.save(workspace)
            raise
        finally:
            state["owner"] = None
            alpine_operations.event("download_slot_released", job_id=job.job_id,
                                    elapsed_seconds=time.time() - started)


async def terminal_fetch(job, workspace, conn):
    """Admit before optional progress I/O, preserving enqueue order."""
    from backend.core import md_executor
    async def operation():
        try:
            await md_executor.poll_remote_progress(job, conn=conn)
        except Exception as exc:
            logger.warning("[%s] terminal remote progress poll failed: %s", job.job_id, exc)
        job.save(workspace)
        return await md_executor.fetch_outputs(job, workspace, conn=conn)
    return await run_transfer(job, workspace, operation)


async def run_transfer(job, workspace, operation):
    """Single-flight transfer ownership survives cancellation of an API waiter."""
    state = _state()
    if state["owner"] is asyncio.current_task():
        return await operation()
    identity = key(job, workspace)
    task = state["transfers"].get(identity)
    duplicate = task is not None
    if task is None:
        async def run():
            try:
                async with transfer_slot(job, workspace):
                    return await operation()
            finally:
                state["transfers"].pop(identity, None)

        task = asyncio.create_task(run())
        state["transfers"][identity] = task
        task.add_done_callback(lambda done: None if done.cancelled() else done.exception())
    result = await asyncio.shield(task)
    # A duplicate caller owns a different in-memory copy. Reload before its caller
    # performs bookkeeping, so it cannot overwrite edits made during the transfer.
    from backend.core.md_job import MdJob
    if duplicate:
        latest = MdJob.load(job.job_id, workspace)
        if key(latest, workspace) == identity:
            job.__dict__.update(latest.__dict__)
    return result
