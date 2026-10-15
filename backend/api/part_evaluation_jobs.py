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
from backend.core.part_command_errors import CommandContractError
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
    selection_only: bool = False


def _run(job, captured, operation):
    result = supervise(job, captured, lambda d: EvaluationWorker(d, operation),
                       TIME_BUDGET, status_lock=_lock)
    if job.selection_only and ("candidate" in result or result.get("status") == "ready"):
        # The host retains the nonpublishing operation type independently of
        # worker output. A future dispatch defect cannot promote a selector.
        result = {"status": "unverified", "native_editable": False,
                  "issues": [{"code": "invalid_selection_result"}],
                  "source_revision": job.revision, "design_id": captured.id}
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
        try:
            source, captured, revision = state.capture_design_for_evaluation(request)
        except CommandContractError as error:
            conflict = error.code in {"source_changed", "repair_conflict", "selection_conflict"}
            raise HTTPException(409 if conflict else 422, detail=error.as_issue()) from error
        if request.expected_revision is not None and request.expected_revision != revision:
            raise HTTPException(409, detail="Design changed before evaluation started")
        if request.operation in {"repair", "selection"}:
            nested = request.repair if request.operation == "repair" else request.selection
            if nested.expected_design_id != captured.id or nested.expected_revision != revision:
                raise HTTPException(409, detail={"code": f"{request.operation}_conflict",
                    "detail": f"The {request.operation} belongs to a different part or revision."})
        job = EvaluationJob(get_current_doc(), ref(source), revision, created=monotonic(),
                            selection_only=request.operation == "selection")
        identity = str(uuid4())
        operation = {"request": request.model_dump(mode="json"), "header": {
            "identity": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_revision": revision, "source_design_id": captured.id,
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
        if job.selection_only and isinstance(result.get("selection"), dict):
            selection = result["selection"]
            selection.update(candidates=[], candidates_invalidated=True)
            selection.pop("eligible_count", None)
            selection.pop("truncated", None)
    return {"job_id": identity, "status": status, "stale": stale, "source_busy": busy, "result": result}


def commit(identity):
    """Publish the exact evaluated candidate once, without rerunning its solver."""
    from backend.core.models import Design

    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    try:
        with _lock:
            job = _lookup(identity)
            if job.selection_only:
                raise HTTPException(409, detail="Reference selection is a nonpublishing preview")
            if job.committed_revision is not None:
                return {"job_id": identity, "status": "committed", "revision": job.committed_revision}
            if job.cancelled.is_set() or job.status != "complete" or not job.result or job.result["status"] != "ready":
                raise HTTPException(409, detail="Part evaluation has no publishable candidate")
            source = job.source()
            if not state.verification_source_matches(job.doc, source, job.revision):
                job.result.pop("candidate", None)
                raise HTTPException(409, detail="Design changed; evaluate the current recipe again")
            data = job.result["candidate"]
        # Pydantic Any-valued params/metadata can retain transport aliases.
        # Fingerprint both bounded JSON projections before decoding, outside
        # the state lock, without retaining another full molecular graph.
        from backend.core.part_history_proof import AUTHORING_FIELDS, digest
        recipe_fields = {"recipe_root", "feature_log", "input_sources", "feature_log_cursor", "feature_log_sub_cursor"}
        expected_recipe = digest({name: data[name] for name in recipe_fields})
        expected_authoring = digest({name: data[name] for name in AUTHORING_FIELDS})
        candidate = Design.model_validate(data)
        if digest(candidate.model_dump(mode="json", include=AUTHORING_FIELDS)) != expected_authoring:
            with _lock:
                job.result.pop("candidate", None)
                job.result.update(status="unverified", issues=[{"code": "candidate_decode_changed_authoring"}])
            raise HTTPException(409, detail="Candidate changed during decoding; evaluation cannot be committed")
        # Pins, stable command identities and source descriptors belong to
        # every evaluated recipe, including appends and ordinary edits.
        if digest(candidate.model_dump(mode="json", include=recipe_fields)) != expected_recipe:
            with _lock:
                job.result.pop("candidate", None)
                job.result.update(status="unverified", issues=[{"code": "candidate_decode_changed_recipe"}])
            raise HTTPException(409, detail="Recipe changed during decoding; evaluation cannot be committed")
        # The worker intentionally omitted physical/display state. Preserve
        # it from the unchanged live source; it never becomes replay evidence.
        from backend.core.part_recipe_publication import preserve_document_state
        candidate = preserve_document_state(source, candidate)
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
