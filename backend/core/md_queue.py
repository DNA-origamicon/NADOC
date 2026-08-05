"""md_queue.py — the persistent, strictly-serial NAMD run queue.

The problem this solves: a NADOC workspace has ONE machine (one GPU, one set of
cores), but the Job Wizard lets the user create any number of prepared jobs.  Before
this module the only way to run several in sequence was the Chain Simulations panel,
which authored a *plan* of not-yet-existing stages; jobs already sitting in the list
at ``queued`` had no way to say "go after that one".

The model is deliberately small:

- The queue is an **ordered list of job ids**, persisted to ``<workspace>/md_queue.json``.
  It survives a page reload, a browser close and a server restart — the frontend is a
  view onto it, never its owner.
- It is **strictly serial**: while ANY NAMD job is in flight (locally running/preparing,
  or handed to SLURM/RunPod), nothing is started.  The moment the machine is idle the
  head of the queue starts, driven by the MD supervisor tick.
- It is **self-healing**: an entry whose job was deleted, started by hand, or has
  already finished is dropped on the next pass.  Nothing else has to remember to clean
  up after it.

Everything that decides *what happens* is a pure function over a job list, so it is
unit-testable without a workspace: :func:`running_job`, :func:`job_is_startable`,
:func:`next_startable`.  Only :func:`load_queue` / :func:`save_queue` touch disk.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Iterable, Optional, Sequence

from backend.core.md_job import MdJob, MdStatus

logger = logging.getLogger(__name__)

QUEUE_FILENAME = "md_queue.json"


# ── persistence ──────────────────────────────────────────────────────────────────

def queue_path(workspace) -> Path:
    return Path(workspace) / QUEUE_FILENAME


def load_queue(workspace) -> list[str]:
    """The persisted job-id order.  A missing or corrupt file reads as an empty queue —
    a broken queue file must never take the server down with it."""
    path = queue_path(workspace)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("md queue: unreadable %s — treating as empty", path)
        return []
    ids = data.get("job_ids") if isinstance(data, dict) else data
    if not isinstance(ids, list):
        return []
    return [str(j) for j in ids if isinstance(j, (str, int))]


def save_queue(workspace, job_ids: Sequence[str]) -> list[str]:
    path = queue_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = dedupe(job_ids)
    path.write_text(json.dumps({"job_ids": ordered}, indent=2))
    return ordered


# ── pure helpers ─────────────────────────────────────────────────────────────────

def dedupe(job_ids: Iterable[str]) -> list[str]:
    """First occurrence wins.  A job can hold exactly one place in the queue."""
    seen: set[str] = set()
    out: list[str] = []
    for jid in job_ids:
        if jid and jid not in seen:
            seen.add(jid)
            out.append(jid)
    return out


def job_is_running(job) -> bool:
    """Is this job occupying the machine (or a remote scheduler slot) right now?

    Mirrors ``mdJobIsRunning`` in ``md_jobs_panel.js`` — a remote job parked at
    ``queued`` with a scheduler id has been handed over and IS in flight, while the
    same status with no id is a prepared job waiting for a human.
    """
    if job is None:
        return False
    if job.status in (MdStatus.running, MdStatus.preparing):
        return True
    return job.status == MdStatus.queued and bool(
        getattr(job, "slurm_job_id", None) or getattr(job, "runpod_pod_id", None)
    )


def remote_awaiting_submit(job) -> bool:
    """A prepared Alpine/RunPod job that has not been handed to its scheduler.

    Mirrors ``mdRemoteAwaitingSubmit`` in ``md_jobs_panel.js``: such a job is launched
    from its review card (which is where the cluster/pod choices are made), never by
    pressing Run — and so never by the queue either.
    """
    if job is None:
        return False
    remote = getattr(job, "execution_target", "local") in ("alpine", "runpod")
    return remote and job.status == MdStatus.queued \
        and not getattr(job, "slurm_job_id", None) \
        and not getattr(job, "runpod_pod_id", None)


def job_is_startable(job) -> bool:
    """Prepared, never started, nothing pending on a remote scheduler.

    Mirrors ``mdJobIsStartable`` in ``md_jobs_panel.js``.  A ``draft`` is excluded on
    purpose: it has not been solvated, so starting it is a wizard decision, not a
    queue one.
    """
    if job is None:
        return False
    return job.status == MdStatus.queued and not getattr(job, "slurm_job_id", None) \
        and not getattr(job, "runpod_pod_id", None) and not remote_awaiting_submit(job)


def job_is_queueable(job) -> bool:
    """Can this job be parked behind the run that's going?

    Two shapes qualify, because ``POST /md/jobs/{id}/start`` handles both identically:
    a prepared job that has never run, and a ``stopped``/``failed`` one that would pick
    up from its last checkpoint.

    **The queue is local-only**, mirroring what the Run button will offer.  Excluded on
    purpose: ``draft`` (unsolvated — starting it is a wizard decision), ``paused``
    (waiting on a GPU-resident decision a human has to answer), and every remote job —
    an Alpine submit and a RunPod rental are decisions made at the review card, not
    things to trigger unattended hours later.
    """
    if job is None:
        return False
    if getattr(job, "execution_target", "local") != "local":
        return False
    return job_is_startable(job) or job.status in (MdStatus.stopped, MdStatus.failed)


def running_job(jobs: Iterable) -> Optional[object]:
    """The job blocking the queue, or None when the machine is idle."""
    for job in jobs:
        if job_is_running(job):
            return job
    return None


def next_startable(job_ids: Sequence[str], jobs: Iterable) -> tuple[Optional[str], list[str]]:
    """Decide the next launch from the queue order and the current job set.

    Returns ``(job_id_to_start, stale_ids)``:

    - ``job_id_to_start`` is the FIRST queued id whose job is still queueable, or None.
    - ``stale_ids`` are entries that can never start — the job is gone, already
      running, or finished — and should be dropped from the queue.

    Scanning past a stale head (rather than stopping at it) is what makes "start job B
    by hand while A, B, C are queued" behave: B is dropped, C still runs after A.
    """
    by_id = {j.job_id: j for j in jobs}
    stale: list[str] = []
    pick: Optional[str] = None
    for jid in job_ids:
        job = by_id.get(jid)
        if job is None or not job_is_queueable(job):
            stale.append(jid)
            continue
        pick = jid
        break
    return pick, stale


# ── mutations (persisted) ────────────────────────────────────────────────────────

def enqueue(workspace, job_id: str) -> list[str]:
    """Append to the end.  Idempotent — re-queueing a job keeps its existing place."""
    return save_queue(workspace, [*load_queue(workspace), job_id])


def dequeue(workspace, job_id: str) -> list[str]:
    return save_queue(workspace, [j for j in load_queue(workspace) if j != job_id])


def reorder(workspace, job_ids: Sequence[str]) -> list[str]:
    return save_queue(workspace, job_ids)


def prune(workspace, jobs: Iterable) -> list[str]:
    """Drop entries whose job no longer exists at all (deleted from the list).

    Deliberately narrower than ``next_startable``'s staleness: a job that is currently
    RUNNING keeps its place here, because the drain pass is the only thing allowed to
    decide a queued job has been superseded.
    """
    known = {j.job_id for j in jobs}
    current = load_queue(workspace)
    kept = [j for j in current if j in known]
    return save_queue(workspace, kept) if kept != current else current


def queue_view(workspace, jobs: Optional[Iterable] = None) -> list[dict]:
    """The queue as the UI reads it: order, id, and enough naming to render a row
    without a second fetch."""
    by_id = {j.job_id: j for j in (jobs if jobs is not None else [])}
    out: list[dict] = []
    for i, jid in enumerate(load_queue(workspace)):
        job = by_id.get(jid)
        out.append({
            "job_id": jid,
            "position": i + 1,
            "design_name": getattr(job, "design_name", None),
            "status": job.status.value if job is not None else None,
        })
    return out


def list_jobs(workspace) -> list[MdJob]:
    return MdJob.list_jobs(Path(workspace))
