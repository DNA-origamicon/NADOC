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


def _dispose(job, worker, design_id):
    """Retry cleanup without allowing another worker to overlap a live child."""
    problem = None
    while True:
        try:
            worker.close()
            return problem
        except Exception as exc:
            problem = failure("worker_cleanup_error", exc)
            with _lock:
                job.result = {**problem, "source_revision": job.revision, "design_id": design_id}
                job.status = "stopping"
            try:
                if not worker.is_alive():
                    return problem
            except Exception:
                # A broken process handle cannot justify freeing admission.
                pass
            Event().wait(POLL_SECONDS)


def _run(job, design):
    deadline = monotonic() + TIME_BUDGET
    worker = None

    def checkpoint():
        if job.cancelled.is_set():
            raise Stopped("cancelled")
        if monotonic() >= deadline:
            raise Stopped("time_limit")
        if not state.verification_source_matches(job.doc, job.source(), job.revision):
            raise Stopped("source_changed")

    try:
        checkpoint()
        worker = VerificationWorker(design)
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
            cleanup_problem = _dispose(job, worker, design.id)
            if cleanup_problem is not None:
                result = cleanup_problem
        _slot.release()
    try:
        checkpoint()
    except Stopped as exc:
        if result["issues"] and result["issues"][0]["code"] == "worker_cleanup_error":
            result["issues"].append({"code": str(exc)})
        else:
            result = failure(str(exc))
    with _lock:
        job.result = {**result, "source_revision": job.revision, "design_id": design.id}
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
    stale = not state.verification_source_matches(job.doc, job.source(), job.revision)
    if result is not None and (stale or job.cancelled.is_set()):
        result["status"] = "unverified"
        result["native_editable"] = False
        result["issues"].append({"code": "source_changed" if stale else "cancelled"})
    return {"job_id": job_id, "status": status, "stale": stale, "result": result}
