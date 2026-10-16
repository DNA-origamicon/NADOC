"""Private evaluation preparation for an already sealed strict source.

The state facade retains the actual source/session under its lock. A private
byte-input reservation is bound to that same host context before admission.
Decode and ordinary projection run only inside the isolated child. Candidate
preparation at commit still happens outside the state lock in the parent.
"""

from fastapi import HTTPException

from backend.api import part_publication_policy as policy
from backend.api.part_immutable_preservation import preservation_digest
from backend.api.part_immutable_revision import prepare_revision
from backend.api.part_immutable_storage import require_sealed
from backend.core.models import Design
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
        from backend.api.part_batch_publication_scope import admit_prospective_rows

        admit_prospective_rows(metadata.history_rows, request.batch.commands)


def capture_reserved(doc_id, session, source, revision, generation, request, request_digest,
                     *, include_session_identity, include_admission):
    from backend.api import state
    from backend.api.part_immutable_worker import reserve_input

    captured = reserve_input(source)
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
    """Preserve the closed document projection without decoding source undo.

    The job owner already checked exact recipe/authoring transport digests. The
    seal still grants no proof or publication authority; its permit is separate.
    """
    metadata = require_sealed(source)
    if type(candidate) is not Design:
        raise CommandContractError("Strict publication requires a private exact Design model")
    candidate = candidate.model_copy(update={"id": metadata.design_id,
        "annotations_enabled": metadata.annotations_enabled})
    if preservation_digest(candidate) != metadata.preserved_document_sha256:
        raise CommandContractError("Candidate changed preserved document state",
                                   code="revision_preservation_changed")
    return prepare_revision(candidate)
