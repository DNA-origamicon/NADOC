"""Explicit repair metadata operations used by the document state facade.

Definition capture and the final compare-and-swap use the existing state lock.
Fingerprinting, schema admission and response serialization run outside it. No
geometry is executed or copied, and proposals never imply regeneration success.
"""

from uuid import uuid4

from fastapi import HTTPException

from backend.api import doc_context
from backend.api.part_repair_draft_transaction import publish_draft
from backend.core.part_command_errors import CommandContractError
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_document import draft_summary
from backend.core.part_repair_draft_host import (
    CreateDraft, DiscardDraft, RebaseDraft, parse_draft_request, prepare_draft,
)
from backend.core.part_repair_fingerprint import RepairFingerprintLimit
from backend.core.part_repair_proposal import DraftInputError
from backend.core.part_verification_capture import CaptureLimit


def _response(identity, revision, draft):
    return {"design_id": identity, "revision": revision,
            "repair_draft": draft_summary(draft),
            "draft": None if draft is None else draft.model_dump(mode="json")}


def _conflict(detail):
    raise DraftInputError(detail, code="draft_conflict")


def _raise_http(error):
    if isinstance(error, (CaptureLimit, RepairFingerprintLimit)):
        raise HTTPException(413, detail={"code": "draft_capture_limit", "detail": str(error)}) from error
    conflict = error.code in {"draft_conflict", "draft_rebase_required", "repair_conflict"}
    raise HTTPException(409 if conflict else 422, detail=error.as_issue()) from error


def inspect_draft():
    """Explicit bounded read of proposal inputs; no base hash or readiness check."""
    from backend.api import state as host

    try:
        with host._lock:
            session = host._session()
            source = session.design
            if source is None:
                raise HTTPException(404, detail="No active design.")
            captured = capture_draft_inputs(source, source_revision=session.revision,
                draft=source.repair_draft, include_definitions=False)
        return _response(captured.id, captured.source_revision, captured.draft)
    except (CaptureLimit, RepairFingerprintLimit, CommandContractError) as error:
        _raise_http(error)


def mutate_draft(request):
    """Prepare privately, then publish one revision with no geometry undo entry."""
    from backend.api import state as host
    from backend.api.part_proof_commands import dependencies

    # A typed HTTP request is owned by the host. Dumping it also prevents a
    # direct caller's mutable action JSON from becoming persisted draft aliases.
    request = parse_draft_request(request.model_dump(mode="json") if hasattr(request, "model_dump") else request)
    try:
        with host._lock:
            session = host._session()
            source, revision = session.design, session.revision
            if source is None:
                raise HTTPException(404, detail="No active design.")
            if source.id != request.expected_design_id or revision != request.expected_revision:
                _conflict("The part or revision changed before draft capture")
            host._assert_active_loadout_editable(source)
            previous = source.repair_draft
            actual = (None, None) if previous is None else (previous.draft_id, previous.generation)
            if actual != (request.expected_draft_id, request.expected_generation):
                _conflict("The repair draft was replaced, changed or discarded")
            actions = () if isinstance(request, DiscardDraft) else (
                previous.actions if isinstance(request, RebaseDraft) and request.actions is None else request.actions)
            captured = capture_draft_inputs(source, source_revision=revision, draft=previous,
                proposed_actions=actions, include_definitions=not isinstance(request, DiscardDraft))
            doc_id = doc_context.get_current_doc()
        prepared = prepare_draft(captured, request, dependencies=dependencies,
            new_draft_id=str(uuid4()) if isinstance(request, CreateDraft) else None)
        # Serialize before publication: a serialization failure cannot leave a
        # successful metadata mutation hidden behind a failed HTTP response.
        response = _response(captured.id, revision + 1, prepared)
        with host._lock:
            committed_revision = publish_draft(host._sessions.get(doc_id), prepared,
                expected_session=session, expected_source=source, expected_doc_id=doc_id,
                expected_design_id=captured.id, expected_revision=revision,
                expected_draft_id=request.expected_draft_id, expected_generation=request.expected_generation,
                bump_revision=host._bump_revision, context=doc_context)
        response["revision"] = committed_revision
        return response
    except (CaptureLimit, RepairFingerprintLimit, CommandContractError) as error:
        _raise_http(error)
