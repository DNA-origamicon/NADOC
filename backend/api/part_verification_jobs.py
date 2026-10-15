"""Bounded, document-scoped, cancellable verification jobs with stale-result checks."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException

from backend.api import state
from backend.api.doc_context import get_current_doc
from backend.api.part_history_verification import _slot
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history
from backend.core.part_verification_capture import CaptureLimit


_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="part-proof")
_lock = Lock()
_jobs = OrderedDict()
MAX_RESULTS = 8
TIME_BUDGET = 5.0


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


def _run(job, design):
    deadline = monotonic() + TIME_BUDGET

    def checkpoint():
        if job.cancelled.is_set():
            raise Stopped("cancelled")
        if monotonic() >= deadline:
            raise Stopped("time_limit")
        if not state.verification_source_matches(job.doc, job.source(), job.revision):
            raise Stopped("source_changed")

    try:
        result = assess_part_history(design, execute=execute, dependencies=dependencies, checkpoint=checkpoint)
        checkpoint()
    except Stopped as exc:
        result = {"status": "unverified", "native_editable": False, "issues": [{"code": str(exc)}]}
    except Exception as exc:
        result = {"status": "unverified", "native_editable": False,
                  "issues": [{"code": "verification_error", "detail": str(exc)}]}
    finally:
        # No capture or user design is retained by the result registry.
        _slot.release()
    with _lock:
        job.result = {**result, "source_revision": job.revision, "design_id": design.id}
        job.status = "complete"


def start():
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history check is already running")
    try:
        source, captured, revision = state.capture_design_for_verification()
        job = Job(get_current_doc(), ref(source), revision)
        job_id = str(uuid4())
        with _lock:
            while len(_jobs) >= MAX_RESULTS:
                _jobs.popitem(last=False)
            _jobs[job_id] = job
        _executor.submit(_run, job, captured)
        return {"job_id": job_id, "status": "running", "source_revision": revision}
    except CaptureLimit as exc:
        _slot.release()
        raise HTTPException(413, detail=str(exc)) from exc
    except BaseException:
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
