"""
API layer — strand-extension route handlers (extracted from crud.py).

This module hosts the ``/design/extensions`` endpoints: single-item CRUD plus
batch upsert/delete of terminal 5′/3′ strand extensions (added sequence and/or
modification on a strand terminus). Factored out of ``crud.py`` following the
same template as routes_animations.py / routes_camera_poses.py (13-B).

Routes
------
  POST   /design/extensions/batch     — upsert multiple extensions (reconcile)
  DELETE /design/extensions/batch     — delete multiple extensions (synthetic geometry only)
  POST   /design/extensions           — add one extension (reconcile)
  PUT    /design/extensions/{ext_id}  — update one extension (reconcile)
  DELETE /design/extensions/{ext_id}  — remove one extension (synthetic geometry only)

NOTE: the batch endpoints (/design/extensions/batch) MUST be registered before
the parameterised single-item endpoints (/design/extensions/{ext_id}) so that
FastAPI/Starlette does not swallow the literal segment "batch" as an ext_id.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Optional
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.api.part_extension_recording import record

# _design_response is a response helper shared with the rest of crud.py's
# route handlers. It stays in crud.py (used by 100+ routes there) and is
# imported here. Same convention as routes_animations.py / routes_camera_poses.py.
from backend.api.crud import _design_response, _design_response_with_geometry

router = APIRouter()


class StrandExtensionRequest(BaseModel):
    strand_id: str
    end: Literal["five_prime", "three_prime"]
    sequence: Optional[str] = None
    modification: Optional[str] = None
    label: Optional[str] = None


class StrandExtensionUpdateRequest(BaseModel):
    sequence: Optional[str] = None
    modification: Optional[str] = None
    label: Optional[str] = None


class StrandExtensionBatchItem(BaseModel):
    strand_id: str
    end: Literal["five_prime", "three_prime"]
    sequence: Optional[str] = None
    modification: Optional[str] = None
    label: Optional[str] = None


class StrandExtensionBatchRequest(BaseModel):
    items: List[StrandExtensionBatchItem] = Field(max_length=256)


class StrandExtensionBatchDeleteRequest(BaseModel):
    ext_ids: List[str] = Field(max_length=256)


@router.post("/design/extensions/batch", status_code=200)
def upsert_strand_extensions_batch(body: StrandExtensionBatchRequest) -> dict:
    """Record one input-defined batch; repeated termini retain last-item-wins."""
    design, report, _ids = record("batch", [item.model_dump() for item in body.items])
    return _design_response(design, report)


@router.delete("/design/extensions/batch", status_code=200)
def delete_strand_extensions_batch(body: StrandExtensionBatchDeleteRequest) -> dict:
    design, report, ids = record("delete", body.ext_ids)
    return _design_response_with_geometry(design, report,
        changed_helix_ids=[f"__ext_{identity}" for identity in ids])


@router.post("/design/extensions", status_code=201)
def add_strand_extension(body: StrandExtensionRequest) -> dict:
    design, report, ids = record("create", [body.model_dump()])
    extension = next(ext for ext in design.extensions if ext.id == ids[0])
    return {"extension": extension.model_dump(), **_design_response(design, report)}


@router.put("/design/extensions/{ext_id}")
def update_strand_extension(ext_id: str, body: StrandExtensionUpdateRequest) -> dict:
    design, report, _ids = record("update", [body.model_dump()], extension_id=ext_id)
    extension = next(ext for ext in design.extensions if ext.id == ext_id)
    return {"extension": extension.model_dump(), **_design_response(design, report)}


@router.delete("/design/extensions/{ext_id}")
def delete_strand_extension(ext_id: str) -> dict:
    design, report, ids = record("delete", [ext_id])
    return _design_response_with_geometry(design, report,
        changed_helix_ids=[f"__ext_{identity}" for identity in ids])
