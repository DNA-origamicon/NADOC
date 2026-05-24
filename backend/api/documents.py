"""
Document registry routes (multi-document, Phase 2).

A "document" is one editing context keyed by an opaque ``doc_id``.  Each frontend
tab owns a doc_id (carried in its URL ``?doc=`` and the ``X-NADOC-Doc`` header).
The backend lazily creates a design/assembly session the first time a request
names a doc_id, so most flows never call these routes — but they let the UI mint
a fresh doc_id for a new tab, enumerate open documents, and close one.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter
from pydantic import BaseModel

from backend.api import assembly_state
from backend.api import state as design_state
from backend.api.doc_context import DEFAULT_DOC_ID

router = APIRouter()


class CreateDocumentRequest(BaseModel):
    # Optional human label (not stored server-side — the document is seeded by
    # the client's subsequent create/load call, which carries the new doc id).
    label: str | None = None


def _name_of(obj) -> str | None:
    meta = getattr(obj, "metadata", None)
    return getattr(meta, "name", None) if meta is not None else getattr(obj, "name", None)


def _doc_meta(doc_id: str) -> dict:
    design = design_state.peek_design(doc_id)
    assembly = assembly_state.peek_assembly(doc_id)
    return {
        "doc_id": doc_id,
        "is_default": doc_id == DEFAULT_DOC_ID,
        "design": ({"id": design.id, "name": _name_of(design)} if design is not None else None),
        "assembly": ({"id": getattr(assembly, "id", None), "name": _name_of(assembly)}
                     if assembly is not None else None),
    }


@router.post("/documents", status_code=201)
def create_document(body: CreateDocumentRequest | None = None) -> dict:
    """Mint a fresh doc_id for a new editing context (a new tab).

    The session itself is created lazily when the new tab's first request
    (create/load design or assembly) arrives carrying this id.
    """
    return {"doc_id": uuid.uuid4().hex}


@router.get("/documents")
def list_documents() -> dict:
    """All documents that currently hold a design and/or assembly."""
    ids = sorted(set(design_state.list_doc_ids()) | set(assembly_state.list_doc_ids()))
    return {"documents": [_doc_meta(d) for d in ids], "default_doc_id": DEFAULT_DOC_ID}


@router.delete("/documents/{doc_id}", status_code=200)
def close_document(doc_id: str) -> dict:
    """Close one document: drop its design + assembly sessions.

    Leaves the shared protein library intact (other open documents may
    reference it).
    """
    dropped_design = design_state.drop_doc(doc_id)
    dropped_assembly = assembly_state.drop_doc(doc_id)
    return {"ok": True, "dropped": {"design": dropped_design, "assembly": dropped_assembly}}
