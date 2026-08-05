"""routes_md_queue.py — the persistent NAMD run queue.

```
GET    /md/queue              the queue, in order, with each entry's live status
POST   /md/queue              {job_id} → append (idempotent)
PUT    /md/queue              {job_ids} → replace the whole order
DELETE /md/queue/{job_id}     remove one entry
```

Plus :func:`advance_md_queue`, the drain pass the MD supervisor calls once per tick:
when nothing is in flight it starts the head of the queue through the SAME
``POST /md/jobs/{id}/start`` handler a human would press, so a queued launch and a
manual one are the same code path (RunPod rental included).

The queue is server-side and persistent on purpose — a run scheduled to follow another
must survive closing the tab.  See ``backend/core/md_queue.py`` for the model.

Lives outside ``routes_md.py`` (already ~4,500 lines and an active carve-up target).
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api.assembly import _WORKSPACE_DIR
from backend.core import md_queue
from backend.core.md_job import MdJob

logger = logging.getLogger(__name__)

router = APIRouter(tags=["md"])


def _workspace() -> Path:
    return _WORKSPACE_DIR


class EnqueueRequest(BaseModel):
    job_id: str


class ReorderRequest(BaseModel):
    job_ids: list[str]


def _response(workspace: Path) -> dict:
    jobs = MdJob.list_jobs(workspace)
    running = md_queue.running_job(jobs)
    return {
        "queue": md_queue.queue_view(workspace, jobs),
        # What the Run button needs to decide between "▶ Run" and "＋ Queue": is the
        # machine busy right now, and (separately) is anything already waiting?
        "running_job_id": getattr(running, "job_id", None),
        "busy": running is not None,
    }


@router.get("/md/queue")
async def get_md_queue() -> dict:
    ws = _workspace()
    md_queue.prune(ws, MdJob.list_jobs(ws))
    return _response(ws)


@router.post("/md/queue")
async def enqueue_md_job(body: EnqueueRequest) -> dict:
    ws = _workspace()
    jobs = MdJob.list_jobs(ws)
    job = next((j for j in jobs if j.job_id == body.job_id), None)
    if job is None:
        raise HTTPException(404, f"No such MD job: {body.job_id}")
    if not md_queue.job_is_queueable(job):
        raise HTTPException(
            400,
            f"Job is {job.status.value} — only a prepared or stopped job can be queued.",
        )
    md_queue.enqueue(ws, body.job_id)
    return _response(ws)


@router.put("/md/queue")
async def reorder_md_queue(body: ReorderRequest) -> dict:
    ws = _workspace()
    md_queue.reorder(ws, body.job_ids)
    return _response(ws)


@router.delete("/md/queue/{job_id}")
async def dequeue_md_job(job_id: str) -> dict:
    ws = _workspace()
    md_queue.dequeue(ws, job_id)
    return _response(ws)


async def advance_md_queue(workspace: Path) -> list[str]:
    """Supervisor pass: start the head of the queue if the machine is idle.

    Returns the ids started (at most one — the queue is strictly serial).  Never
    raises: a launch that fails drops its entry and logs, rather than wedging the
    queue behind a job that can never start.
    """
    queued = md_queue.load_queue(workspace)
    if not queued:
        return []

    jobs = MdJob.list_jobs(workspace)
    if md_queue.running_job(jobs) is not None:
        return []   # something is in flight — the queue waits

    job_id, stale = md_queue.next_startable(queued, jobs)
    if stale:
        logger.info("md queue: dropping stale entries %s", ", ".join(stale))
        md_queue.save_queue(workspace, [j for j in queued if j not in stale])
    if not job_id:
        return []

    # Same handler the ▶ Run button hits — one launch path, one set of gates.
    from backend.api.routes_md import start_md_job

    md_queue.dequeue(workspace, job_id)   # dequeue FIRST: a start that throws must not retry forever
    try:
        await start_md_job(job_id)
    except Exception:
        logger.exception("md queue: could not start %s — dropped from the queue", job_id)
        return []
    logger.info("md queue: started %s", job_id)
    return [job_id]
