"""Bounded, document-scoped, cancellable verification jobs with stale-result checks."""
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Event, Lock, Thread
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException

from backend.api import state
from backend.api.doc_context import get_current_doc
from backend.api.part_history_verification import _slot
from backend.api.part_verification_worker import VerificationWorker, WorkerLimit, failure
from backend.core.part_verification_capture import CaptureLimit


_lock = Lock()
_jobs = OrderedDict()
MAX_RESULTS = 8
TIME_BUDGET = 5.0
POLL_SECONDS = 0.05


@dataclass
class Job:
    doc: str
    source: object
    revision: int
    cancelled: Event = field(default_factory=Event)
    status: str = "running"
    result: dict | None = None


class Stopped(Exception):
    pass


def _dispose(job, worker, design_id, *, status_lock=None):
    """Retain admission until the child AND its shared buffers are released."""
    problem = None
    status_lock = status_lock or _lock
    while True:
        try:
            worker.close()
            return problem
        except Exception as exc:
            problem = failure("worker_cleanup_error", exc)
            with status_lock:
                job.result = {**problem, "source_revision": job.revision, "design_id": design_id}
                job.status = "stopping"
            # A dead process can still retain mappings or named shared memory.
            # Do not admit another allocation until close/unlink really succeeds.
            Event().wait(POLL_SECONDS)


def supervise(job, design, worker_factory, seconds, *, status_lock=None):
    """Own one admitted child through reaping; return a revision-bound result."""
    deadline = monotonic() + seconds
    worker = None

    def checkpoint():
        if job.cancelled.is_set():
            raise Stopped("cancelled")
        if monotonic() >= deadline:
            raise Stopped("time_limit")
        matches = state.verification_source_matches(job.doc, job.source(), job.revision, blocking=False,
            expected_session_identity=getattr(job, "session_identity", None),
            expected_policy_generation=getattr(job, "policy_generation", None))
        if matches is False:
            generation = getattr(job, "policy_generation", None)
            if generation is not None:
                from backend.api.part_publication_policy import resolve
                if resolve(job.doc).generation != generation:
                    raise Stopped("policy_changed")
            raise Stopped("source_changed")
        return matches

    try:
        checkpoint()
        worker = worker_factory(design)
        checkpoint()
        worker.start()
        while True:
            checkpoint()
            ready = worker.wait(min(POLL_SECONDS, max(0, deadline - monotonic())))
            checkpoint()
            if ready:
                result = worker.result()
                break
            if not worker.is_alive():
                # Completion can race the wait timeout; inspect its exit
                # sentinel once more before treating the child as a crash.
                result = worker.result() if worker.wait(0) else failure("worker_exited")
                break
    except Stopped as exc:
        result = failure(str(exc))
    except WorkerLimit as exc:
        result = failure("worker_input_limit", exc)
    except Exception as exc:
        result = failure("verification_error", exc)
    finally:
        # Never free admission while native work can still consume resources.
        # No capture or user design is retained by the result registry.
        if worker is not None:
            cleanup_problem = _dispose(job, worker, design.id, status_lock=status_lock)
            if cleanup_problem is not None:
                result = cleanup_problem
        _slot.release()
    try:
        if checkpoint() is None:
            result = failure("source_busy")
    except Stopped as exc:
        if result["issues"] and result["issues"][0]["code"] == "worker_cleanup_error":
            result["issues"].append({"code": str(exc)})
        else:
            result = failure(str(exc))
    return {**result, "source_revision": job.revision, "design_id": design.id}


def _run(job, design):
    result = supervise(job, design, VerificationWorker, TIME_BUDGET)
    with _lock:
        job.result = result
        job.status = "complete"


def _submit(job, captured):
    # No executor queue: a failed thread start cannot leave deferred work behind.
    # A non-daemon supervisor completes child cleanup during normal shutdown.
    Thread(target=_run, args=(job, captured), name="part-proof-supervisor", daemon=False).start()


def start():
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history check is already running")
    job_id = None
    try:
        source, captured, revision = state.capture_design_for_verification()
        job = Job(get_current_doc(), ref(source), revision)
        job_id = str(uuid4())
        with _lock:
            while len(_jobs) >= MAX_RESULTS:
                _jobs.popitem(last=False)
            _jobs[job_id] = job
        _submit(job, captured)
        return {"job_id": job_id, "status": "running", "source_revision": revision}
    except CaptureLimit as exc:
        _slot.release()
        raise HTTPException(413, detail=str(exc)) from exc
    except BaseException:
        if job_id is not None:
            with _lock:
                _jobs.pop(job_id, None)
        _slot.release()
        raise


def inspect(job_id, *, cancel=False):
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job.doc != get_current_doc():
            raise HTTPException(404, detail="Unknown part verification job")
        if cancel:
            job.cancelled.set()
        result = deepcopy(job.result)
        status = job.status
    matches = state.verification_source_matches(job.doc, job.source(), job.revision, blocking=False)
    stale, busy = matches is False, matches is None
    if result is not None and (stale or busy or job.cancelled.is_set()):
        result["status"] = "unverified"
        result["native_editable"] = False
        result["issues"].append({"code": "cancelled" if job.cancelled.is_set() else "source_changed" if stale else "source_busy"})
    return {"job_id": job_id, "status": status, "stale": stale, "source_busy": busy, "result": result}
