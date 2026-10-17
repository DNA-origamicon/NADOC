"""Owned scalar revision status shared by compatibility and strict HTTP reads."""

from fastapi import HTTPException

from backend.api import state
from backend.api.doc_context import get_current_doc
from backend.api.part_immutable_storage import content_identity


def revision_status_locked(doc_id):
    """Caller owns state._lock. Never create a session or expose a model alias."""
    if type(doc_id) is not str or not doc_id or len(doc_id) > 1024:
        raise HTTPException(422, detail={"code": "revision_context_limit",
            "detail": "Document context exceeds the bounded revision read allowance"})
    session = state._sessions.get(doc_id)
    design = None if session is None else session.design
    identity = content_identity(design)
    if identity is not None and (type(identity) is not str or len(identity) > 1024):
        raise HTTPException(422, detail={"code": "revision_identity_limit",
            "detail": "Document identity exceeds the bounded revision read allowance"})
    return {"doc_id": doc_id, "design_id": identity,
        "revision": 0 if session is None else session.revision, "has_design": design is not None}


def revision_status():
    with state._lock:
        return revision_status_locked(get_current_doc())
