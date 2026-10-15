"""Read leases delegated by the existing evaluation job owner.

The live source is weak-referenced by jobs, not owned or immutable. This helper
captures it under the state lock before projecting outside all owner locks. It
has no registry, readiness cache, second numerical job, or publication operation.
"""

from time import monotonic

from fastapi import HTTPException

from backend.api import doc_context, part_publication_policy as policy, state
from backend.api.part_comparison_worker import ComparisonWorker
from backend.api.part_evaluation import EvaluationRequest
from backend.api.part_verification_jobs import Job, supervise
from backend.core.part_command_errors import CommandContractError
from backend.core.part_comparison_projection import candidate_digests, check_scope, parse_request
from backend.core.part_history_proof import digest
from backend.core.part_repair_capture import _Copier
from backend.core.part_verification_capture import CaptureLimit, capture


TIME_BUDGET = 5.0
CAPTURE_SECONDS = 0.025
CAPTURE_BYTES = 2_000_000
CAPTURE_NODES = 30_000


def _conflict(detail, code="comparison_conflict"):
    raise HTTPException(409, detail={"code": code, "detail": detail})


def _draft_matches(source, request):
    draft = source.repair_draft
    return (source.id == request.expected_design_id and draft is not None
            and draft.draft_id == request.expected_draft_id
            and draft.generation == request.expected_generation)


def _capture_source(job, request):
    """One common capture allowance, with all cheap context guards first."""
    if not state._lock.acquire(blocking=False):
        _conflict("The source is busy; request comparison again", "source_busy")
    try:
        copier = _Copier(CAPTURE_NODES, CAPTURE_BYTES, CAPTURE_SECONDS)
        configuration = policy.require_compatibility(job.doc, "repair_comparison")
        session = state._sessions.get(job.doc)
        source = job.source()
        if (session is None or source is None or session.identity != job.session_identity
                or session.design is not source or session.revision != job.revision
                or configuration.generation != job.policy_generation
                or job.revision != request.expected_revision or not _draft_matches(source, request)):
            _conflict("The source, document session or saved proposal changed")
        check_scope(source, checkpoint=copier.check)
        # Loadouts are excluded from the geometry capture, but the existing
        # editability guard scans their IDs. Bound that scan before entering it.
        if len(source.loadouts) > 128:
            raise CaptureLimit("Comparison loadout guard count exceeded")
        for identity in [source.active_loadout_id, *(loadout.id for loadout in source.loadouts)]:
            copier.check()
            if identity is not None and (type(identity) is not str or len(identity) > 256):
                raise CaptureLimit("Comparison loadout identity budget exceeded")
        state._assert_active_loadout_editable(source)
        draft = copier.clone(source.repair_draft)
        copied = capture(source, preserve_entry_types=True, max_nodes=copier.nodes,
                         max_bytes=copier.size, seconds=max(0, copier.deadline - monotonic()))
        copier.check()
        return copied, draft
    finally:
        state._lock.release()


def _saved_request_digest(source, draft, revision):
    # Only reconstruct the saved request envelope. No planning, fingerprinting,
    # dependency resolution, numerical selection or native execution occurs.
    value = EvaluationRequest.model_validate({"operation": "repair", "expected_revision": revision,
        "repair": {"repair_version": draft.repair_version, "expected_design_id": source.id,
                   "expected_revision": revision,
                   "actions": [action.model_dump(mode="json") for action in draft.actions]}})
    return digest(value.model_dump(mode="json"))


def _admit(owner, identity, request, *, expected_job=None, expected_candidate=None):
    """Caller owns the catalog lock; never claim the shared slot is a lease."""
    job = owner._lookup(identity)
    if expected_job is not None and job is not expected_job:
        _conflict("The evaluated job was removed or replaced")
    owner._assert_publishable(job)
    if job.admitted_operation != "repair":
        _conflict("Comparison requires the saved proposal's evaluated repair")
    if (job.committed_revision is not None or job.cancelled.is_set() or job.status != "complete"
            or not job.result or job.result.get("status") != "ready"
            or not isinstance(job.result.get("candidate"), dict)):
        _conflict("The repair has no current uncommitted candidate")
    candidate = job.result["candidate"]
    if expected_candidate is not None and candidate is not expected_candidate:
        _conflict("The evaluated candidate changed")
    if job.revision != request.expected_revision:
        _conflict("The repair belongs to another source revision")
    return job, candidate


def _final_source_guard(job, request):
    # Source metadata can change independently from candidate decoding. Use the
    # same state lock to verify draft, source, session and policy once more.
    if not state._lock.acquire(blocking=False):
        _conflict("The source is busy; request comparison again", "source_busy")
    try:
        configuration = policy.require_compatibility(job.doc, "repair_comparison")
        session, source = state._sessions.get(job.doc), job.source()
        if (session is None or source is None or session.identity != job.session_identity
                or session.design is not source or session.revision != job.revision
                or configuration.generation != job.policy_generation or not _draft_matches(source, request)):
            _conflict("The source, document session or saved proposal changed")
    finally:
        state._lock.release()


def compare(identity, value):
    """Called through jobs.comparison; route code never accesses the catalog."""
    from backend.api import part_evaluation_jobs as owner

    try:
        request = parse_request(value)
    except ValueError as error:
        raise HTTPException(422, detail={"code": "invalid_comparison_request", "detail": str(error)}) from error
    policy.require_compatibility(doc_context.get_current_doc(), "repair_comparison")
    if not owner._slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history operation is already running")
    supervision_started = False
    try:
        with owner._lock:
            job, candidate = _admit(owner, identity, request)
        source, draft = _capture_source(job, request)
        if _saved_request_digest(source, draft, job.revision) != job.request_sha256:
            _conflict("The evaluated repair does not match the saved proposal")
        # A temporary supervisor receipt is not registered. Cleanup failures
        # cannot overwrite the original job's candidate/readiness metadata.
        read = Job(job.doc, job.source, job.revision, cancelled=job.cancelled)
        read.session_identity, read.policy_generation = job.session_identity, job.policy_generation
        remaining = min(TIME_BUDGET, max(0, owner.RESULT_TTL - (owner.monotonic() - job.created)))
        supervision_started = True  # supervise releases admission only after reaping
        result = supervise(read, source, lambda captured: ComparisonWorker(captured, candidate), remaining,
                           status_lock=owner._lock)
        if result.get("status") != "projected":
            issue = (result.get("issues") or [{"code": "comparison_error"}])[0]
            code = issue.get("code")
            status = (413 if code in {"worker_input_limit", "result_limit", "comparison_limit"} else
                      409 if code in {"source_changed", "source_busy", "policy_changed", "cancelled"} else
                      504 if code == "time_limit" else 422)
            raise HTTPException(status, detail=issue)
        # Both transport and source were bounded before projection. Hashing
        # retained private candidate data happens outside state/catalog locks.
        try:
            unchanged = candidate_digests(candidate) == result.pop("candidate_digests")
        except (KeyError, TypeError, ValueError):
            unchanged = False
        if not unchanged:
            _conflict("The retained candidate changed while it was projected")
        with owner._lock:
            _admit(owner, identity, request, expected_job=job, expected_candidate=candidate)
            _final_source_guard(job, request)
            expires_in = min(owner.RESULT_TTL, owner.RESULT_TTL - (owner.monotonic() - job.created))
            if expires_in <= 0:
                raise HTTPException(410, detail={"code": "comparison_expired", "detail": "The evaluated repair expired"})
        return {**result, "job_id": identity, "design_id": request.expected_design_id,
                "source_revision": job.revision, "expires_in_seconds": expires_in,
                "repair_draft": {"draft_id": request.expected_draft_id, "generation": request.expected_generation}}
    except CaptureLimit as error:
        raise HTTPException(413, detail={"code": "comparison_capture_limit", "detail": str(error)}) from error
    except CommandContractError as error:
        raise HTTPException(413 if error.code == "comparison_limit" else 422, detail=error.as_issue()) from error
    finally:
        if not supervision_started:
            owner._slot.release()
