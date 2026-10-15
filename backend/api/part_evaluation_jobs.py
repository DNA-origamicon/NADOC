"""Explicit long part jobs with bounded candidates and revision-bound commit."""

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock, Thread
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException

from backend.api import state
from backend.api.doc_context import get_current_doc
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_evaluation_worker import EvaluationWorker
from backend.api.part_history_verification import _slot
from backend.api.part_verification_jobs import Job, supervise
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_verification_capture import CaptureLimit


TIME_BUDGET = 180.0
MAX_RESULTS = 2
RESULT_TTL = 900.0
_lock = Lock()
_jobs = OrderedDict()


@dataclass
class EvaluationJob(Job):
    created: float = 0.0
    committed_revision: int | None = None


def _run(job, captured, operation):
    result = supervise(job, captured, lambda d: EvaluationWorker(d, operation),
                       TIME_BUDGET, status_lock=_lock)
    with _lock:
        job.result = result
        job.status = "complete"


def _submit(job, captured, operation):
    Thread(target=_run, args=(job, captured, operation),
           name="part-evaluation-supervisor", daemon=False).start()


def start(request):
    request = EvaluationRequest.model_validate(request)
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    identity = None
    try:
        source, captured, revision = state.capture_design_for_verification(preserve_entry_types=True)
        if request.expected_revision is not None and request.expected_revision != revision:
            raise HTTPException(409, detail="Design changed before evaluation started")
        job = EvaluationJob(get_current_doc(), ref(source), revision, created=monotonic())
        identity = str(uuid4())
        operation = {"request": request.model_dump(mode="json"), "header": {
            "identity": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
        }}
        with _lock:
            while len(_jobs) >= MAX_RESULTS:
                _jobs.popitem(last=False)
            _jobs[identity] = job
        _submit(job, captured, operation)
        return {"job_id": identity, "status": "running", "source_revision": revision,
                "time_budget_seconds": TIME_BUDGET}
    except CaptureLimit as exc:
        _slot.release()
        raise HTTPException(413, detail=str(exc)) from exc
    except BaseException:
        if identity is not None:
            with _lock:
                _jobs.pop(identity, None)
        _slot.release()
        raise


def _lookup(identity):
    job = _jobs.get(identity)
    if job is None or job.doc != get_current_doc():
        raise HTTPException(404, detail="Unknown part evaluation job")
    if job.committed_revision is None and monotonic() - job.created > RESULT_TTL:
        job.cancelled.set()
        if job.result is not None:
            job.result.pop("candidate", None)
        raise HTTPException(410, detail="Part evaluation result expired")
    return job


def inspect(identity, *, cancel=False):
    with _lock:
        job = _lookup(identity)
        if job.committed_revision is not None:
            return {"job_id": identity, "status": "committed", "revision": job.committed_revision}
        if cancel:
            job.cancelled.set()
            if job.result is not None:
                job.result.pop("candidate", None)
        # Candidate/recovery bytes remain internal and bounded; polling never
        # clones or transmits an entire design merely to show job progress.
        result = None if job.result is None else deepcopy({
            key: value for key, value in job.result.items() if key != "candidate"
        })
        status = job.status
    matches = state.verification_source_matches(job.doc, job.source(), job.revision, blocking=False)
    stale, busy = matches is False, matches is None
    if result is not None and (stale or busy or job.cancelled.is_set()):
        result.update(status="unverified", native_editable=False)
        result["issues"].append({"code": "cancelled" if job.cancelled.is_set() else "source_changed" if stale else "source_busy"})
    return {"job_id": identity, "status": status, "stale": stale, "source_busy": busy, "result": result}


def commit(identity):
    """Publish the exact evaluated candidate once, without rerunning its solver."""
    from backend.core.models import Design

    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    try:
        with _lock:
            job = _lookup(identity)
            if job.committed_revision is not None:
                return {"job_id": identity, "status": "committed", "revision": job.committed_revision}
            if job.cancelled.is_set() or job.status != "complete" or not job.result or job.result["status"] != "ready":
                raise HTTPException(409, detail="Part evaluation has no publishable candidate")
            source = job.source()
            if not state.verification_source_matches(job.doc, source, job.revision):
                job.result.pop("candidate", None)
                raise HTTPException(409, detail="Design changed; evaluate the current recipe again")
            data = job.result["candidate"]
        candidate = Design.model_validate(data)
        from backend.core.part_history_proof import AUTHORING_FIELDS
        if candidate.model_dump(mode="json", include=AUTHORING_FIELDS) != {
            name: data[name] for name in AUTHORING_FIELDS
        }:
            with _lock:
                job.result.pop("candidate", None)
                job.result.update(status="unverified", issues=[{"code": "candidate_decode_changed_authoring"}])
            raise HTTPException(409, detail="Candidate changed during decoding; evaluation cannot be committed")
        # The worker intentionally omitted physical/display state. Preserve
        # it from the unchanged live source; it never becomes replay evidence.
        candidate = candidate.copy_with(**{
            name: getattr(source, name) for name, role in FIELD_ROLES.items()
            if role in {"presentation", "physical", "document_identity"}
        })
        with _lock:
            _lookup(identity)  # expiration is checked again after candidate decoding
            if job.cancelled.is_set():
                raise HTTPException(409, detail="Part evaluation was cancelled")
            job.committed_revision = state.set_design(candidate, expected_revision=job.revision, expected_source=source)
            job.result.pop("candidate", None)
            job.status = "committed"
            return {"job_id": identity, "status": "committed", "revision": job.committed_revision,
                    "design_id": candidate.id}
    finally:
        _slot.release()
