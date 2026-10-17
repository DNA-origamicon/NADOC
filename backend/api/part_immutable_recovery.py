"""Explicit cold recovery through the existing bounded evaluation job owner.

    Saved bytes, file leases and scope seals supply no proof or publication
    authority. Only this host's observed worker completion qualifies a candidate.
"""

from dataclasses import dataclass
from threading import Thread
from time import monotonic
from uuid import uuid4
from weakref import ref

from fastapi import HTTPException

from backend.api import part_evaluation_jobs as jobs, part_publication_permit as permits
from backend.api import part_publication_policy as policy, state
from backend.api.doc_context import get_current_doc
from backend.api.document_identity import require_document_identity
from backend.api.part_history_verification import _slot
from backend.api.part_immutable_recovery_inputs import RestoreRequest
from backend.api.part_immutable_recovery_worker import RecoveryWorker, reserve_input
from backend.api.part_immutable_revision import revision_metadata
from backend.api.part_immutable_storage import require_empty_session
from backend.api.part_verification_jobs import Stopped, supervise
from backend.api.part_verification_worker import failure
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from backend.core.part_verification_capture import CaptureLimit


TIME_BUDGET = 5.0
_QUALIFICATION = object()


@dataclass
class RecoveryJob(jobs.EvaluationJob):
    persistence: object | None = None
    lease: object | None = None
    candidate: object | None = None
    qualification: object | None = None


@dataclass(frozen=True, slots=True, init=False)
class _Qualification:
    token: object
    owner: object
    candidate: object
    admission: object

    def __init__(self):
        raise TypeError("Recovery qualification is a private host observation")


def is_recovery_job(job):
    return type(job) is RecoveryJob


def discard_candidate(job):
    if is_recovery_job(job):
        job.candidate = job.qualification = job.lease = None


def require_qualification(qualification, admission, candidate):
    if type(qualification) is not _Qualification:
        raise HTTPException(409, detail="Recovery has no host-observed cold qualification")
    owner = qualification.owner()
    if (qualification.token is not _QUALIFICATION or owner is None
            or owner.qualification is not qualification or owner.admission is not admission
            or qualification.admission is not admission or qualification.candidate() is not candidate
            or owner.candidate is not candidate or owner.cancelled.is_set()):
        raise HTTPException(409, detail="Recovery qualification no longer matches its exact candidate")


def _qualify(job, candidate):
    value = object.__new__(_Qualification)
    for name, item in (("token", _QUALIFICATION), ("owner", ref(job)),
                       ("candidate", ref(candidate)), ("admission", job.admission)):
        object.__setattr__(value, name, item)
    return value


def _owner():
    from backend.api import session_cache
    from backend.api.part_immutable_persistence import StrictPersistence

    owner = session_cache._strict_persistence
    if type(owner) is not StrictPersistence:
        raise HTTPException(503, detail={"code": "strict_cache_unavailable",
            "detail": "Typed recovery storage is unavailable on this host"})
    return owner


def _owner_matches(owner):
    from backend.api import session_cache

    return session_cache._strict_persistence is owner


def _require_current_owner(owner):
    if not _owner_matches(owner):
        raise HTTPException(409, detail={"code": "strict_cache_changed",
            "detail": "Recovery storage changed; start a new recovery assessment"})


def _context_locked(doc, expected_generation):
    selected = policy.resolve(doc)
    if not selected.strict:
        raise HTTPException(403, detail={"code": "construction_policy", "detail": "Recovery requires strict host policy"})
    if expected_generation is not None and selected.generation != expected_generation:
        raise HTTPException(409, detail={"code": "policy_changed", "detail": "Host policy changed during recovery admission"})
    return selected


def status(*, expected_policy_generation=None):
    doc = require_document_identity(get_current_doc())
    owner = _owner()
    with state._lock:
        selected = _context_locked(doc, expected_policy_generation)
        session = state._sessions.get(doc)
        revision = 0 if session is None else session.revision
    issues = []
    try:
        manifest = owner.cache.inspect(doc)
        record = ({"state": "absent"} if manifest is None else {"state": "pending",
            "storage_version": manifest.storage_version, "payload_bytes": manifest.payload_bytes})
    except CommandContractError as error:
        record, issues = {"state": "unavailable"}, [error.as_issue()]
    with state._lock:
        _context_locked(doc, selected.generation)
        _require_current_owner(owner)
        if state._sessions.get(doc) is not session or (session is not None and session.revision != revision):
            raise HTTPException(409, detail={"code": "source_changed", "detail": "Document changed during recovery status"})
    return {"doc_id": doc, "revision": revision, "policy_generation": selected.generation,
        "record": record, "assessment": "unverified", "issues": issues}


def start(request, *, expected_policy_generation=None):
    return _start(request, expected_policy_generation=expected_policy_generation, geometry=False)


def start_geometry(request, *, expected_policy_generation=None):
    """Private explicit recovery; public restore remains on its original scope."""
    return _start(request, expected_policy_generation=expected_policy_generation, geometry=True)


def _start(request, *, expected_policy_generation, geometry):
    request = RestoreRequest.model_validate(request)
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    identity = None
    try:
        owner = _owner()
        doc = require_document_identity(get_current_doc())
        request_hash = digest({"operation": "restore", **request.model_dump(mode="json")})
        if geometry:
            request_hash = digest({'operation': 'geometry_restore', **request.model_dump(mode='json')})
        with state._lock:
            _context_locked(doc, expected_policy_generation)
            _require_current_owner(owner)
            session = state._sessions.get(doc)
            if request.expected_revision != (0 if session is None else session.revision):
                raise HTTPException(409, detail={"code": "source_changed", "detail": "Recovery belongs to an earlier revision"})
            if session is None:
                session = state._session()  # Explicit restore reserves an actual incarnation.
            require_empty_session(session)
            admit = permits.admit_geometry_recovery if geometry else permits.admit_recovery
            admission = admit(doc, session, request_sha256=request_hash)
            job = RecoveryJob(doc, lambda: None, session.revision, created=monotonic(),
                admitted_operation="restore", session_identity=session.identity, admission=admission,
                request_sha256=request_hash, persistence=owner)
        identity = str(uuid4())
        with jobs._lock:
            while len(jobs._jobs) >= jobs.MAX_RESULTS:
                _key, evicted = jobs._jobs.popitem(last=False)
                jobs._discard_candidate(evicted)
            jobs._jobs[identity] = job
        _submit(job)
        return {"job_id": identity, "status": "running", "source_revision": job.revision,
            "time_budget_seconds": TIME_BUDGET}
    except BaseException:
        if identity is not None:
            with jobs._lock:
                jobs._jobs.pop(identity, None)
        _slot.release()
        raise


def _checkpoint(job, deadline):
    if job.cancelled.is_set():
        raise Stopped("cancelled")
    if monotonic() >= deadline:
        raise Stopped("time_limit")
    if not _owner_matches(job.persistence):
        raise Stopped("strict_cache_changed")
    matches = state.verification_source_matches(job.doc, None, job.revision, blocking=False,
        expected_session_identity=job.session_identity, expected_policy_generation=job.policy_generation)
    if matches is False:
        raise Stopped("policy_changed" if jobs._policy_changed(job) else "source_changed")
    return matches


def _run(job):
    """Own one admission through private preparation, child reaping and cleanup."""
    deadline = job.created + TIME_BUDGET
    supervised = False
    worker = None
    try:
        checkpoint = lambda: _checkpoint(job, deadline)
        checkpoint()
        stored = job.persistence.read_pending(job.doc)
        checkpoint()
        lease = stored.lease
        ticket = reserve_input(stored, admission=job.admission)
        del stored
        checkpoint()

        def construct(owned):
            nonlocal worker
            if owned is not ticket:
                raise ValueError("Recovery supervisor changed its original input ticket")
            worker = RecoveryWorker(owned)
            return worker

        supervised = True  # supervise owns release, including constructor failure.
        result = supervise(job, ticket, construct, max(0, deadline - monotonic()), status_lock=jobs._lock)
        if (result.get("status") == "verified" and result.get("native_editable") is True
                and result.get("issues") == []):
            with jobs._lock:
                # Supervision has released native admission. A subsequent job
                # may have evicted this one; never resurrect its retained bytes.
                if not any(retained is job for retained in jobs._jobs.values()):
                    raise Stopped("result_expired")
                if jobs._admission_context(job) is None:
                    raise Stopped("invalid_evaluation_admission")
                if checkpoint() is None:
                    raise Stopped("source_busy")
                candidate = worker.take_revision(ticket, admission=job.admission)
                if checkpoint() is None:
                    raise Stopped("source_busy")
                job.candidate, job.lease = candidate, lease
                job.qualification = _qualify(job, candidate)
                design_id = revision_metadata(candidate).design_id
                job.result = {"status": "ready", "native_editable": True, "issues": [],
                    "restoration_assessment": {**result, "design_id": design_id},
                    "source_revision": job.revision, "design_id": design_id}
                job.status = "complete"
                return
    except Stopped as error:
        result = failure(str(error))
    except CommandContractError as error:
        result = {"status": "unverified", "native_editable": False, "issues": [error.as_issue()]}
    except CaptureLimit as error:
        result = failure("strict_recovery_limit", error)
    except Exception as error:
        result = failure("strict_recovery_error", error)
    finally:
        if not supervised:
            _slot.release()
    with jobs._lock:
        discard_candidate(job)
        job.result = result
        job.status = "complete"


def _submit(job):
    Thread(target=_run, args=(job,), name="part-recovery-supervisor", daemon=False).start()


def commit_registered(identity, job):
    """Called only by the existing commit owner while it holds the native slot."""
    from backend.api.part_immutable_persistence import PersistenceCapture

    with jobs._lock:
        if jobs._lookup(identity) is not job or not is_recovery_job(job) or jobs._admission_context(job) is None:
            raise HTTPException(409, detail="Recovery has no original private host admission")
        _require_current_owner(job.persistence)
        if jobs._policy_changed(job):
            raise HTTPException(409, detail={"code": "policy_changed", "detail": "Recovery host policy changed"})
        if job.committed_revision is not None:
            if not state.evaluation_session_matches(job.doc, job.session_identity,
                    expected_policy_generation=job.policy_generation):
                raise HTTPException(409, detail="Recovery belongs to an earlier session")
            return {"job_id": identity, "status": "committed", "revision": job.committed_revision}
        candidate = job.candidate
        if candidate is None or job.cancelled.is_set() or job.status != "complete":
            raise HTTPException(409, detail="Recovery has no qualified candidate")
        require_qualification(job.qualification, job.admission, candidate)
        permit = permits.issue_recovery_permit(job.admission, candidate, qualification=job.qualification,
            expires=job.created + jobs.RESULT_TTL, cancelled=job.cancelled)
        capture = PersistenceCapture(job.doc, job.session_identity, job.revision + 1, candidate)
        try:
            # File/hash work precedes state.set_design; this lease serializes
            # cooperating writers through the short locked publication only.
            with job.persistence.bind_for_publication(capture, job.lease):
                jobs._lookup(identity)
                _require_current_owner(job.persistence)
                job.committed_revision = state.set_design(candidate, expected_revision=job.revision,
                    expected_session_identity=job.session_identity, expected_policy_generation=job.policy_generation,
                    publication_permit=permit)
                discard_candidate(job)
                job.status = "committed"
        except CommandContractError as error:
            raise HTTPException(409, detail=error.as_issue()) from error
        return {"job_id": identity, "status": "committed", "revision": job.committed_revision,
            "design_id": revision_metadata(candidate).design_id}
