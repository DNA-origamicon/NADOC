"""Private evaluation preparation for an already sealed strict source.

The state facade retains the actual source/session under its lock. Decode and
ordinary capture run outside that lock, then the same host context is checked
before an admission is minted. No decoded model is retained by the session.
"""

from fastapi import HTTPException

from backend.api import part_publication_policy as policy
from backend.api.part_immutable_revision import materialize_revision, prepare_revision
from backend.api.part_immutable_storage import require_sealed
from backend.core.part_command_errors import CommandContractError


def check_request(source, request, revision, configuration):
    """Constant-size source checks before any full private materialization."""
    metadata = require_sealed(source)
    if not configuration.strict or request.operation not in {"batch", "verify"}:
        raise HTTPException(409, detail={"code": "immutable_publication_scope",
            "detail": "Immutable evaluation requires the admitted strict host operation"})
    if request.expected_revision is not None and request.expected_revision != revision:
        raise CommandContractError("Design changed before evaluation capture", code="source_changed")
    if request.operation == "batch":
        from backend.api import part_batch_evaluation

        if not part_batch_evaluation.REGISTERED_BATCH_ENABLED:
            raise CommandContractError("Registered batches are not enabled on this server",
                                       code="registered_batch_unavailable")
        if (request.batch.expected_design_id != metadata.design_id
                or request.batch.expected_revision != revision):
            raise CommandContractError("Batch belongs to a different part or captured revision", code="batch_conflict")


def _capture_owned_revision(source, *, request, revision):
    """Own materialization through transfer; never accept a live mutable model.

    Full-byte decoding remains checked. The ordinary authoring projection and
    30k-node/2 MB/25 ms accounting are shared with mutable capture, including
    recovery stripping. Nested authored models may transfer because the only
    published source is immutable bytes; no decoded alias survives this call.
    """
    from time import monotonic
    from backend.api.part_batch_evaluation import admit_batch_capture
    from backend.core.part_capture_inputs import visit_inputs

    require_sealed(source)
    if request.operation not in {"batch", "verify"}:
        raise CommandContractError("Immutable capture requires batch or verify", code="immutable_publication_scope")
    if request.expected_revision is not None and request.expected_revision != revision:
        raise CommandContractError("Design changed before evaluation capture", code="source_changed")
    private = materialize_revision(source)
    deadline = (admit_batch_capture(private, request, revision=revision)
                if request.operation == "batch" else monotonic() + 0.025)
    return visit_inputs(private, max_nodes=30_000, max_bytes=2_000_000,
        seconds=max(0, deadline - monotonic()), preserve_entry_types=True,
        copy_inputs=False, retain_owned=True)


def capture_reserved(doc_id, session, source, revision, generation, request, request_digest,
                     *, include_session_identity, include_admission):
    from backend.api import state

    captured = _capture_owned_revision(source, request=request, revision=revision)
    with state._lock:
        current = policy.require_evaluation(doc_id, request.operation)
        if current.generation != generation:
            raise HTTPException(409, detail={"code": "policy_changed",
                "detail": "Construction policy changed during private source preparation"})
        if (state._sessions.get(doc_id) is not session or session.design is not source
                or session.revision != revision):
            raise HTTPException(409, detail={"code": "source_changed",
                "detail": "The document session or source changed during private preparation"})
        result = (source, captured, revision)
        if include_admission:
            from backend.api.part_publication_permit import admit_evaluation

            admission = admit_evaluation(doc_id, session, operation=request.operation, request_sha256=request_digest)
            return (*result, session.identity, admission)
        return (*result, session.identity) if include_session_identity else result


def prepare_candidate(source, candidate):
    """Preserve non-proof state from owned bytes, then seal private full content.

    The job owner already checked exact recipe/authoring transport digests. The
    seal still grants no proof or publication authority; its permit is separate.
    """
    from backend.core.part_recipe_publication import preserve_document_state

    private_source = materialize_revision(source)
    candidate = preserve_document_state(private_source, candidate)
    return prepare_revision(candidate)
