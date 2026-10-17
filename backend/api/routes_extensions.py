"""
API layer — strand-extension route handlers (extracted from crud.py).

This module hosts the ``/design/extensions`` endpoints: single-item CRUD plus
batch upsert/delete of terminal 5′/3′ strand extensions (added sequence and/or
modification on a strand terminus). Factored out of ``crud.py`` following the
same template as routes_animations.py / routes_camera_poses.py (13-B).

Routes
------
  POST   /design/extensions/batch     — upsert multiple extensions
  DELETE /design/extensions/batch     — delete multiple extensions (synthetic geometry only)
  POST   /design/extensions           — add one extension
  PUT    /design/extensions/{ext_id}  — update one extension
  DELETE /design/extensions/{ext_id}  — remove one extension (synthetic geometry only)

NOTE: the batch endpoints (/design/extensions/batch) MUST be registered before
the parameterised single-item endpoints (/design/extensions/{ext_id}) so that
FastAPI/Starlette does not swallow the literal segment "batch" as an ext_id.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
Legacy v1 upserts retain reconciliation; organized v2 edits own extensions only.
"""

from __future__ import annotations

from typing import List, Optional
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from backend.api.part_extension_recording import record
from backend.api.part_extension_transport import ExtensionRoute

# _design_response_with_geometry is shared with the rest of crud.py's
# route handlers. It stays in crud.py (used by 100+ routes there) and is
# imported here. Same convention as routes_animations.py / routes_camera_poses.py.
from backend.api.crud import _design_response_with_geometry

router = APIRouter(route_class=ExtensionRoute)


class ExtensionRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt | None = Field(default=None, ge=0)


class StrandExtensionRequest(ExtensionRevisionRequest):
    strand_id: str
    end: Literal["five_prime", "three_prime"]
    sequence: Optional[str] = None
    modification: Optional[str] = None
    label: Optional[str] = None


class StrandExtensionUpdateRequest(ExtensionRevisionRequest):
    sequence: Optional[str] = None
    modification: Optional[str] = None
    label: Optional[str] = None


class StrandExtensionBatchItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strand_id: str
    end: Literal["five_prime", "three_prime"]
    sequence: Optional[str] = None
    modification: Optional[str] = None
    label: Optional[str] = None


class StrandExtensionBatchRequest(ExtensionRevisionRequest):
    items: List[StrandExtensionBatchItem] = Field(max_length=256)


class StrandExtensionBatchDeleteRequest(ExtensionRevisionRequest):
    ext_ids: List[str] = Field(max_length=256)


@router.post("/design/extensions/batch", status_code=200)
def upsert_strand_extensions_batch(body: StrandExtensionBatchRequest) -> dict:
    """Record one input-defined batch; repeated termini retain last-item-wins."""
    design, report, _ids = record("batch", [item.model_dump() for item in body.items],
                                  expected_revision=body.expected_revision)
    return _response(design, report, expected_revision=body.expected_revision)


@router.delete("/design/extensions/batch", status_code=200)
def delete_strand_extensions_batch(body: StrandExtensionBatchDeleteRequest) -> dict:
    design, report, ids = record("delete", body.ext_ids, expected_revision=body.expected_revision)
    return _response(design, report, deleted=ids, expected_revision=body.expected_revision)


@router.post("/design/extensions", status_code=201)
def add_strand_extension(body: StrandExtensionRequest) -> dict:
    design, report, ids = record("create", [body.model_dump(exclude={"expected_revision"})],
                                 expected_revision=body.expected_revision)
    extension = next(ext for ext in design.extensions if ext.id == ids[0])
    return {"extension": extension.model_dump(), **_response(design, report, expected_revision=body.expected_revision)}


@router.put("/design/extensions/{ext_id}")
def update_strand_extension(ext_id: str, body: StrandExtensionUpdateRequest) -> dict:
    design, report, _ids = record("update", [body.model_dump(exclude={"expected_revision"})],
                                  extension_id=ext_id, expected_revision=body.expected_revision)
    extension = next(ext for ext in design.extensions if ext.id == ext_id)
    return {"extension": extension.model_dump(), **_response(design, report, expected_revision=body.expected_revision)}


@router.delete("/design/extensions/{ext_id}")
def delete_strand_extension(ext_id: str, body: ExtensionRevisionRequest | None = None) -> dict:
    design, report, ids = record("delete", [ext_id], expected_revision=body.expected_revision if body else None)
    return _response(design, report, deleted=ids, expected_revision=body.expected_revision if body else None)


def _response(design, report, *, deleted=None, expected_revision=None):
    # Geometry and metadata come from the exact published candidate. Deletion
    # retains its existing synthetic-only path; the 2D request skips geometry.
    response = _design_response_with_geometry(design, report,
        changed_helix_ids=None if deleted is None else [f"__ext_{identity}" for identity in deleted],
        normalize_legacy=design.group_organization is None)
    # The recorder binds this revision atomically, including accepted no-ops.
    response["no_op"] = expected_revision is not None and response["revision"] == expected_revision
    return response
