"""Small strict HTTP projections; no live Design leaves these handlers.

The request context is supplied only by the host ASGI dispatcher, not a header,
model field or saved document.
"""

from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from backend.api import part_publication_policy as policy
from backend.api import state
from backend.api.doc_context import get_current_doc


CONTEXT_KEY = "nadoc.strict_part_context"


@dataclass(frozen=True)
class StrictRequestContext:
    doc_id: str
    policy_generation: int


def _require_context_locked(request: Request):
    """Caller owns state._lock; it is deliberately not a reentrant lock."""
    context = request.scope.get(CONTEXT_KEY)
    if type(context) is not StrictRequestContext or context.doc_id != get_current_doc():
        raise HTTPException(403, detail={"code": "strict_request_context",
            "detail": "The request has no host-selected strict document context"})
    current = policy.resolve(context.doc_id)
    if not current.strict or current.generation != context.policy_generation:
        raise HTTPException(409, detail={"code": "policy_changed",
            "detail": "Host construction policy changed during this request"})
    return context, current


def require_context(request: Request):
    """Check dispatch policy before shared handlers; they own their own locks."""
    with state._lock:
        return _require_context_locked(request)


class EmptyPartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr = Field(default="Untitled", min_length=1, max_length=1024)
    lattice_type: Literal["HONEYCOMB", "SQUARE"] = "HONEYCOMB"

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Part name must contain non-whitespace text")
        return value


def create_registered_empty(body: EmptyPartRequest, request: Request):
    """Publish a host-built empty root and return only owned scalar metadata."""
    from backend.api.part_publication_host import _create_empty_part_locked

    with state._lock:
        context, current = _require_context_locked(request)
        created = _create_empty_part_locked(body.name, body.lattice_type)
        return {"status": "created", "doc_id": context.doc_id, "design_id": created.id,
            "revision": state._sessions[context.doc_id].revision,
            "recipe_root": {"kind": created.recipe_root.kind, "version": created.recipe_root.version},
            "name": body.name, "lattice_type": body.lattice_type,
            "policy_generation": current.generation}


def construction_policy(request: Request):
    """Constant-size host capability metadata, without walking a document."""
    from backend.api.part_batch_evaluation import REGISTERED_BATCH_ENABLED

    with state._lock:
        context, current = _require_context_locked(request)
        return {"doc_id": context.doc_id, "mode": current.mode, "profile": current.profile_id,
            "policy_generation": current.generation, "operations": {
                "registered_empty": True, "verify": True, "batch": REGISTERED_BATCH_ENABLED},
            "assessment": "capabilities_only", "independent_cold_proof": False}


def revision_metadata(request: Request):
    """No lazy session creation, model serialization, validation or geometry."""
    from backend.api.part_revision_status import revision_status_locked

    with state._lock:
        context, current = _require_context_locked(request)
        return {**revision_status_locked(context.doc_id), "policy_generation": current.generation}
