"""Bounded session-content operations; no materialization or model traversal.

The cumulative allowance is provisional while immutable public creation remains
disabled. Two individually admitted 16 MB payloads always fit one immediate undo;
qualification still must measure total process/GIL costs before enabling it.
"""

from fastapi import HTTPException

from backend.api.part_immutable_revision import StrictPartRevision, is_prepared_revision, revision_metadata
from backend.core.part_verification_capture import CaptureLimit


MAX_RETAINED_REVISION_BYTES = 32_000_000


def _refuse(detail, code="immutable_publication_scope"):
    raise HTTPException(409, detail={"code": code, "detail": detail})


def is_immutable(value):
    # Invalid instances must also enter the refusal path, never a mutable path.
    return isinstance(value, StrictPartRevision)


def require_sealed(value):
    if not is_prepared_revision(value):
        _refuse("Strict session content requires a privately prepared immutable revision")
    return revision_metadata(value)


def mutable_design(value):
    if is_immutable(value):
        _refuse("This document has immutable content; use an explicitly owned materialization",
                code="immutable_design_access")
    return value


def content_metadata(value):
    if value is None:
        return None
    if is_immutable(value):
        meta = require_sealed(value)
        return {"id": meta.design_id, "name": meta.name}
    meta = getattr(value, "metadata", None)
    name = getattr(meta, "name", None) if meta is not None else getattr(value, "name", None)
    return {"id": value.id, "name": name}


def content_identity(value):
    """Revision reads need identity only, independent of legacy metadata shape."""
    if value is None:
        return None
    return require_sealed(value).design_id if is_immutable(value) else value.id


def immutable_pair(source, candidate):
    if not is_immutable(source) and not is_immutable(candidate):
        return False
    before, after = require_sealed(source), require_sealed(candidate)
    if before.scope_tag != after.scope_tag:
        _refuse("Immutable replacement must preserve the admitted storage scope")
    if before.design_id != after.design_id:
        _refuse("Immutable replacement must preserve the captured part identity")
    return True


def require_empty_session(session):
    if session.design is not None:
        _refuse("Close the active part before creating a new empty part", code="part_already_open")
    if session.history or session.redo or session.pdb_atomistic is not None or session.workspace_heads:
        _refuse("Immutable empty creation requires an empty session, including undo and auxiliary state",
                code="immutable_empty_session_required")


def retained_history(session, candidate, *, max_steps):
    """Prepare bounded handle retention without changing either stack.

    Caller owns the session lock. No source/candidate graph is copied. Distinct
    handles count independently even if bytes match; repeat references to one
    handle are charged once. Redo is cleared by publication after this admission.
    """
    after = require_sealed(candidate)
    if session.design is None:
        require_empty_session(session)
        return []
    immutable_pair(session.design, candidate)
    if len(session.history) > max_steps or len(session.redo) > max_steps:
        _refuse("Immutable undo/redo exceeds the existing step allowance")
    for held in (*session.history, *session.redo):
        if require_sealed(held).design_id != after.design_id:
            _refuse("Immutable undo cannot contain another part or mutable content")
    history = [*session.history, session.design][-max_steps:]

    def total(values):
        return sum(len(value.payload) for value in {id(item): item for item in values}.values())

    if total((candidate, session.design)) > MAX_RETAINED_REVISION_BYTES:
        raise CaptureLimit("Immutable revision retention cannot preserve the immediate source undo")
    while total((candidate, *history)) > MAX_RETAINED_REVISION_BYTES:
        history.pop(0)
    return history
