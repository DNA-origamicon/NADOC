"""Document-owned capture/publication seams for explicit repair-source uploads.

State supplies this host through thin facade calls. No global document state,
geometry undo, fingerprint hashing or source decoding is introduced here.
"""

from dataclasses import dataclass

from fastapi import HTTPException
from backend.api import doc_context
from backend.api.part_repair_draft_transaction import publish_sources
from backend.api.part_repair_source_policy import admit_descriptor
from backend.core.part_command_errors import CommandContractError
from backend.core.part_repair_document import draft_summary
from backend.core.part_repair_sources import (
    RepairSourceError, _prepare_checked_source, blob_expectation, capture_source_inputs,
    check_blob_expectation, parse_source_request, select_source,
)
from backend.core.part_verification_capture import CaptureLimit


@dataclass(frozen=True)
class CapturedUpload:
    request: object
    captured: object
    session: object
    source: object
    doc_id: str
    checked_source: object = None


def _raise_http(error):
    if isinstance(error, CaptureLimit):
        raise HTTPException(413, detail={"code": "draft_capture_limit", "detail": str(error)}) from error
    if isinstance(error, ValueError) and not isinstance(error, CommandContractError):
        raise HTTPException(422, detail={"code": "invalid_source_request", "detail": str(error)}) from error
    conflicts = {"draft_conflict", "repair_conflict", "source_blob_conflict", "source_binding_conflict",
                 "restore_published_required", "source_unchanged"}
    status = 413 if error.code == "source_limit" else 409 if error.code in conflicts else 422
    raise HTTPException(status, detail=error.as_issue()) from error


def capture_source_request(value, *, mutation=False):
    """Capture definitions/immutable source refs, then admit the named binding."""
    from backend.api import state as host
    from backend.api.part_proof_commands import dependencies

    try:
        request = parse_source_request(value, mutation=mutation)
        with host._lock:
            session = host._session()
            source, revision = session.design, session.revision
            if source is None:
                raise HTTPException(404, detail="No active design.")
            draft = source.repair_draft
            if (source.id != request.expected_design_id or revision != request.expected_revision
                    or draft is None or draft.draft_id != request.expected_draft_id
                    or draft.generation != request.expected_generation):
                raise RepairSourceError("The part, revision or saved proposal changed", code="draft_conflict")
            if mutation:
                host._assert_active_loadout_editable(source)
            captured = capture_source_inputs(source, source_revision=revision)
            doc_id = doc_context.get_current_doc()
        select_source(captured, request, dependencies=dependencies, admit_descriptor=admit_descriptor)
        checked = check_blob_expectation(captured, request) if mutation else None
        return CapturedUpload(request, captured, session, source, doc_id, checked)
    except (CaptureLimit, ValueError) as error:
        _raise_http(error)


def inspect_source(value):
    """Return an exact prior-byte expectation; no readiness or source restoration."""
    upload = capture_source_request(value)
    request = upload.request
    receipt = blob_expectation(upload.captured.sources.get(request.source.sha256))
    return {**request.model_dump(mode="json"), "expected_blob": receipt.model_dump(mode="json")}


def prepare_upload(upload, raw):
    """Prepare/serialize outside the state lock, before any publication."""
    try:
        prepared = _prepare_checked_source(upload.checked_source, raw)
        response = {"design_id": upload.request.expected_design_id,
            "revision": upload.request.expected_revision + 1,
            "operation": upload.request.operation, "source": upload.request.source.model_dump(mode="json"),
            "published_source_changed": prepared.published_source_changed,
            "repair_draft": draft_summary(upload.captured.definitions.draft)}
        if prepared.published_source_changed:
            response["repair_draft"]["base_status"] = "rebase_required"
        return prepared, response
    except CommandContractError as error:
        _raise_http(error)


def publish_upload(upload, prepared, response, *, cancelled=lambda: False):
    """One state-owned, failure-atomic metadata revision; no feature/undo entry."""
    from backend.api import state as host

    request = upload.request
    try:
        with host._lock:
            if cancelled():
                raise HTTPException(499, detail="Source upload cancelled before publication.")
            # The exact captured source identity is checked by the transaction.
            # Repeat branch protection here, since clients may navigate during
            # upload. No historical/immutable branch gets a write exception.
            host._assert_active_loadout_editable(upload.source)
            revision = publish_sources(host._sessions.get(upload.doc_id), prepared.sources,
                expected_session=upload.session, expected_source=upload.source,
                expected_doc_id=upload.doc_id, expected_design_id=request.expected_design_id,
                expected_revision=request.expected_revision, expected_draft_id=request.expected_draft_id,
                expected_generation=request.expected_generation,
                bump_revision=host._bump_revision, context=doc_context)
        response["revision"] = revision
        return response
    except CommandContractError as error:
        _raise_http(error)
