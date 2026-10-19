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
from backend.api import part_publication_permit as permits, part_publication_policy as policy
from backend.api.part_verification_jobs import Job, supervise
from backend.core.part_command_errors import CommandContractError
from backend.core.part_verification_capture import CaptureLimit


TIME_BUDGET = 180.0
MAX_RESULTS = 2
RESULT_TTL = 900.0
PUBLISHABLE_OPERATIONS = frozenset({"append", "edit", "delete", "repair", "batch"})
_lock = Lock()
_jobs = OrderedDict()


@dataclass
class EvaluationJob(Job):
    created: float = 0.0
    committed_revision: int | None = None
    # Set only from the host-validated request. Worker output and saved Design
    # JSON cannot supply publication authority; absent admission fails closed.
    admitted_operation: str | None = None
    session_identity: str | None = None
    admission: object | None = None
    request_sha256: str | None = None

    @property
    def policy_generation(self):
        context = permits.admission_context(self.admission)
        return None if context is None else context.policy_generation

    @property
    def selection_only(self):
        return self.admitted_operation == "selection"


def _assert_publishable(job):
    if job.selection_only:
        raise HTTPException(409, detail="Reference selection is a nonpublishing preview")
    if job.admitted_operation == "verify":
        raise HTTPException(409, detail="Verification is a nonpublishing assessment")
    if job.admitted_operation not in PUBLISHABLE_OPERATIONS:
        raise HTTPException(409, detail={"code": "invalid_operation_admission",
            "detail": "This job has no admitted publishing operation"})
    if not _has_session_context(job):
        raise HTTPException(409, detail={"code": "invalid_evaluation_context",
            "detail": "This job has no captured document session"})
    if _admission_context(job) is None:
        raise HTTPException(409, detail={"code": "invalid_evaluation_admission",
            "detail": "This job has no matching private host admission"})
    if _policy_changed(job):
        raise HTTPException(409, detail={"code": "policy_changed", "detail": "Construction policy changed; evaluate again"})


def _discard_candidate(job):
    if job.result is not None:
        job.result.pop("candidate", None)
    from backend.api.part_immutable_recovery import discard_candidate

    discard_candidate(job)


def _has_session_context(job):
    return type(job.session_identity) is str and bool(job.session_identity)


def _admission_context(job):
    context = permits.admission_context(job.admission)
    if (context is None or context.doc_id != job.doc or context.session_identity != job.session_identity
            or context.source_revision != job.revision or context.source() is not job.source()
            or context.operation != job.admitted_operation or context.request_sha256 != job.request_sha256):
        return None
    return context


def _policy_changed(job):
    generation = job.policy_generation
    return generation is not None and generation != policy.resolve(job.doc).generation


def _request_matches(job, operation):
    from backend.core.part_history_proof import digest
    from backend.core.part_operation_input import validate_operation_input

    context = _admission_context(job)
    if context is None:
        return False
    try:
        definition = operation["request"]
        validate_operation_input(definition)
        return digest(definition) == context.request_sha256
    except (KeyError, TypeError, ValueError):
        return False


def _run(job, captured, operation):
    def worker(design):
        if not _request_matches(job, operation):
            raise ValueError("Evaluation request no longer matches its host admission")
        from backend.api.part_immutable_worker import ImmutableEvaluationWorker, is_immutable_input

        if is_immutable_input(design):
            if design.source is not job.source():
                raise ValueError("Immutable worker input differs from the admitted source")
            return ImmutableEvaluationWorker(design, operation)
        return EvaluationWorker(design, operation)

    result = supervise(job, captured, worker,
                       TIME_BUDGET, status_lock=_lock)
    known_operation = job.admitted_operation in PUBLISHABLE_OPERATIONS | {"verify", "selection"}
    matching_admission = _request_matches(job, operation)
    if not known_operation or not _has_session_context(job) or not matching_admission or (job.admitted_operation not in PUBLISHABLE_OPERATIONS
                              and ("candidate" in result or result.get("status") == "ready")):
        # A future dispatch defect cannot promote a read operation or invent
        # publication authority by returning a ready candidate or actor label.
        code = ("invalid_operation_admission" if not known_operation else
                "invalid_evaluation_context" if not _has_session_context(job) else
                "invalid_evaluation_admission" if not matching_admission else
                "invalid_selection_result" if job.selection_only else
                "invalid_verification_result" if job.admitted_operation == "verify" else
                "invalid_operation_admission")
        result = {"status": "unverified", "native_editable": False,
                  "issues": [{"code": code}],
                  "source_revision": job.revision, "design_id": captured.id}
    with _lock:
        job.result = result
        job.status = "complete"


def _submit(job, captured, operation):
    Thread(target=_run, args=(job, captured, operation),
           name="part-evaluation-supervisor", daemon=False).start()


def start(request, *, expected_source=None, expected_session_identity=None, expected_policy_generation=None):
    """Admit a request, optionally bound to a privately prepared draft source."""
    request = EvaluationRequest.model_validate(request)
    if request.operation == "append" and request.kind in {"linear-pattern", "circular-pattern"}:
        raise HTTPException(422, detail={"code": "pattern_owned_host_required",
            "detail": "Pattern creation requires its owned ordinary pattern host"})
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    identity = None
    try:
        # Own nested Any-valued inputs after busy admission, before capture.
        # Earlier Python dictionary/model aliases cannot alter worker inputs.
        request = EvaluationRequest.model_validate_json(request.model_dump_json())
        try:
            source, captured, revision, session_identity, admission = state.capture_design_for_evaluation(request,
                include_admission=True, expected_source=expected_source,
                expected_session_identity=expected_session_identity,
                expected_policy_generation=expected_policy_generation)
        except CommandContractError as error:
            conflict = error.code in {"source_changed", "repair_conflict", "selection_conflict", "batch_conflict"}
            raise HTTPException(409 if conflict else 422, detail=error.as_issue()) from error
        if request.expected_revision is not None and request.expected_revision != revision:
            raise HTTPException(409, detail="Design changed before evaluation started")
        if request.operation in {"repair", "selection", "batch"}:
            nested = getattr(request, request.operation)
            if nested.expected_design_id != captured.id or nested.expected_revision != revision:
                raise HTTPException(409, detail={"code": f"{request.operation}_conflict",
                    "detail": f"The {request.operation} belongs to a different part or revision."})
        job = EvaluationJob(get_current_doc(), ref(source), revision, created=monotonic(),
                            admitted_operation=request.operation, session_identity=session_identity, admission=admission,
                            request_sha256=permits.admission_context(admission).request_sha256)
        identity = str(uuid4())
        operation = {"request": request.model_dump(mode="json"), "header": {
            "identity": str(uuid4()), "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_revision": revision, "source_design_id": captured.id,
        }}
        with _lock:
            while len(_jobs) >= MAX_RESULTS:
                _key, evicted = _jobs.popitem(last=False)
                _discard_candidate(evicted)
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
        _discard_candidate(job)
        raise HTTPException(410, detail="Part evaluation result expired")
    return job


def inspect(identity, *, cancel=False):
    with _lock:
        job = _lookup(identity)
        if job.committed_revision is not None:
            matches = state.evaluation_session_matches(job.doc, job.session_identity, blocking=False,
                expected_policy_generation=job.policy_generation)
            return {"job_id": identity, "status": "committed", "revision": job.committed_revision,
                    "stale": matches is False, "source_busy": matches is None}
        if cancel:
            job.cancelled.set()
            _discard_candidate(job)
        # Candidate/recovery bytes remain internal and bounded; polling never
        # clones or transmits an entire design merely to show job progress.
        result = None if job.result is None else deepcopy({
            key: value for key, value in job.result.items() if key != "candidate"
        })
        status = job.status
    matches = (state.verification_source_matches(job.doc, job.source(), job.revision, blocking=False,
        expected_session_identity=job.session_identity, expected_policy_generation=job.policy_generation)
        if _has_session_context(job) and _admission_context(job) is not None else False)
    stale, busy = matches is False, matches is None
    if result is not None and (stale or busy or job.cancelled.is_set()):
        result.update(status="unverified", native_editable=False)
        result["issues"].append({"code": "cancelled" if job.cancelled.is_set() else
            "policy_changed" if _policy_changed(job) else "source_changed" if stale else "source_busy"})
        if job.selection_only and isinstance(result.get("selection"), dict):
            selection = result["selection"]
            selection.update(candidates=[], candidates_invalidated=True)
            selection.pop("eligible_count", None)
            selection.pop("truncated", None)
    return {"job_id": identity, "status": status, "stale": stale, "source_busy": busy, "result": result}


def commit(identity):
    """Publish the exact evaluated candidate once, without rerunning its solver."""
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    try:
        from backend.api.part_immutable_recovery import is_recovery_job, commit_registered

        with _lock:
            restoring = _lookup(identity)
        if is_recovery_job(restoring):
            return commit_registered(identity, restoring)
        with _lock:
            job = _lookup(identity)
            _assert_publishable(job)
            if job.committed_revision is not None:
                if not state.evaluation_session_matches(job.doc, job.session_identity,
                        expected_policy_generation=job.policy_generation):
                    raise HTTPException(409, detail="The evaluation belongs to an earlier document session")
                return {"job_id": identity, "status": "committed", "revision": job.committed_revision}
            if job.cancelled.is_set() or job.status != "complete" or not job.result or job.result["status"] != "ready":
                raise HTTPException(409, detail="Part evaluation has no publishable candidate")
            source = job.source()
            if not state.verification_source_matches(job.doc, source, job.revision,
                    expected_session_identity=job.session_identity, expected_policy_generation=job.policy_generation):
                job.result.pop("candidate", None)
                raise HTTPException(409, detail="Design changed; evaluate the current recipe again")
            data = job.result["candidate"]
        # Pydantic Any-valued params/metadata can retain transport aliases.
        # Fingerprint both bounded JSON projections before decoding, outside
        # the state lock, without retaining another full molecular graph.
        from backend.api.part_evaluation_candidate import CandidateDecodeError, decode_candidate
        try:
            candidate, expected_authoring, expected_recipe = decode_candidate(data)
        except CandidateDecodeError as error:
            with _lock:
                job.result.pop("candidate", None)
                job.result.update(status="unverified", issues=[{"code": error.code}])
            raise HTTPException(409, detail=str(error)) from error
        # The worker intentionally omitted physical/display state. Preserve
        # it from the unchanged live source; it never becomes replay evidence.
        from backend.api.part_immutable_storage import content_identity, is_immutable

        if is_immutable(source):
            from backend.api.part_immutable_evaluation import prepare_candidate

            try:
                candidate = prepare_candidate(source, candidate)
            except CaptureLimit as error:
                raise HTTPException(413, detail={"code": "immutable_candidate_limit", "detail": str(error)}) from error
            except CommandContractError as error:
                raise HTTPException(422, detail=error.as_issue()) from error
        else:
            from backend.core.part_recipe_publication import preserve_document_state

            candidate = preserve_document_state(source, candidate)
        with _lock:
            _lookup(identity)  # expiration is checked again after candidate decoding
            _assert_publishable(job)
            if job.cancelled.is_set():
                raise HTTPException(409, detail="Part evaluation was cancelled")
            permit = None
            if job.admitted_operation == "batch":
                permit = permits.issue_batch_permit(job.admission, candidate,
                    request_sha256=job.request_sha256, authoring_sha256=expected_authoring,
                    recipe_sha256=expected_recipe, expires=job.created + RESULT_TTL,
                    cancelled=job.cancelled, source_status=job.result.get("source_assessment", {}).get("status"))
            elif (context := permits.admission_context(job.admission)) is not None and context.scope_tag == "organized_recipe_v1":
                permit = permits.issue_organized_recipe_permit(job.admission, candidate,
                    request_sha256=job.request_sha256, expires=job.created + RESULT_TTL,
                    cancelled=job.cancelled)
            job.committed_revision = state.set_design(candidate, expected_revision=job.revision, expected_source=source,
                expected_session_identity=job.session_identity, expected_policy_generation=job.policy_generation,
                publication_permit=permit)
            job.result.pop("candidate", None)
            job.status = "committed"
            response = {"job_id": identity, "status": "committed", "revision": job.committed_revision,
                        "design_id": content_identity(candidate)}
            if removed := job.result.get("removed_features"):
                response["removed_features"] = removed
                response["placement_warnings"] = [
                    f"Removed {len(removed)} fine-routing feature(s) whose positions are no longer "
                    "occupied by a strand: " + ", ".join(r["label"] for r in removed)]
            return response
    finally:
        _slot.release()


def comparison(identity, request):
    """Read a bounded private display projection through this job owner."""
    from backend.api.part_evaluation_comparison import compare

    return compare(identity, request)
