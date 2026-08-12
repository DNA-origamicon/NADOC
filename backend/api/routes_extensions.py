"""
API layer — strand-extension route handlers (extracted from crud.py).

This module hosts the ``/design/extensions`` endpoints: single-item CRUD plus
batch upsert/delete of terminal 5′/3′ strand extensions (added sequence and/or
modification on a strand terminus). Factored out of ``crud.py`` following the
same template as routes_animations.py / routes_camera_poses.py (13-B).

Routes
------
  POST   /design/extensions/batch     — upsert multiple extensions (reconcile)
  DELETE /design/extensions/batch     — delete multiple extensions (reconcile)
  POST   /design/extensions           — add one extension (reconcile)
  PUT    /design/extensions/{ext_id}  — update one extension (reconcile)
  DELETE /design/extensions/{ext_id}  — remove one extension (reconcile)

NOTE: the batch endpoints (/design/extensions/batch) MUST be registered before
the parameterised single-item endpoints (/design/extensions/{ext_id}) so that
FastAPI/Starlette does not swallow the literal segment "batch" as an ext_id.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Optional
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state

# _design_response is a response helper shared with the rest of crud.py's
# route handlers. It stays in crud.py (used by 100+ routes there) and is
# imported here. Same convention as routes_animations.py / routes_camera_poses.py.
from backend.api.crud import _design_response, _design_response_with_geometry
from backend.core.models import Design, StrandExtension, VALID_MODIFICATIONS

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
    items: List[StrandExtensionBatchItem]


class StrandExtensionBatchDeleteRequest(BaseModel):
    ext_ids: List[str]


@router.post("/design/extensions/batch", status_code=200)
def upsert_strand_extensions_batch(body: StrandExtensionBatchRequest) -> dict:
    """Upsert (create or update) multiple strand extensions in one operation.

    Each item is matched by (strand_id, end): if an extension already exists for
    that terminus it is updated in-place; otherwise a new one is appended.
    All mutations happen inside a single mutate_and_validate call.
    """
    import re as _re

    design = design_state.get_or_404()
    strand_map = {s.id: s for s in design.strands}

    # Validate all items before mutating anything.
    for item in body.items:
        strand = strand_map.get(item.strand_id)
        if strand is None:
            raise HTTPException(404, detail=f"Strand {item.strand_id!r} not found.")
        if item.sequence is None and item.modification is None:
            raise HTTPException(
                400,
                detail=f"Strand {item.strand_id!r}: at least one of sequence or modification must be provided.",
            )
        if item.sequence and not _re.match(r"^[ACGTNacgtn]+$", item.sequence):
            raise HTTPException(
                400,
                detail=f"Strand {item.strand_id!r}: sequence must contain only ACGTN characters.",
            )
        if item.modification and item.modification not in VALID_MODIFICATIONS:
            raise HTTPException(
                400,
                detail=f"Unknown modification {item.modification!r}. Valid: {sorted(VALID_MODIFICATIONS)}",
            )

    def _apply(d: Design) -> None:
        # Build a mutable index: (strand_id, end) → list position
        ext_index: dict[tuple[str, str], int] = {
            (e.strand_id, e.end): i for i, e in enumerate(d.extensions)
        }
        for item in body.items:
            seq = item.sequence.upper() if item.sequence else None
            key = (item.strand_id, item.end)
            if key in ext_index:
                i = ext_index[key]
                d.extensions[i] = d.extensions[i].model_copy(
                    update={
                        "sequence": seq,
                        "modification": item.modification,
                        "label": item.label,
                    }
                )
            else:
                new_ext = StrandExtension(
                    strand_id=item.strand_id,
                    end=item.end,
                    sequence=seq,
                    modification=item.modification,
                    label=item.label,
                )
                ext_index[key] = len(d.extensions)
                d.extensions.append(new_ext)

    design, report = design_state.mutate_with_reconcile(_apply)
    return _design_response(design, report)


@router.delete("/design/extensions/batch", status_code=200)
def delete_strand_extensions_batch(body: StrandExtensionBatchDeleteRequest) -> dict:
    """Delete multiple strand extensions by ID in one operation."""
    design = design_state.get_or_404()
    id_set = set(body.ext_ids)
    missing = id_set - {e.id for e in design.extensions}
    if missing:
        raise HTTPException(404, detail=f"Extension ID(s) not found: {sorted(missing)}")

    def _apply(d: Design) -> None:
        d.extensions = [e for e in d.extensions if e.id not in id_set]

    # Extensions are terminal annotations/synthetic geometry; removing one cannot
    # change strand domains, cluster membership, or pending ligations. Running the
    # full cluster reconciler here made a one-item delete scale with the entire design.
    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


@router.post("/design/extensions", status_code=201)
def add_strand_extension(body: StrandExtensionRequest) -> dict:
    """Add a terminal extension (sequence and/or modification) to a strand's 5′ or 3′ end."""
    import re

    design = design_state.get_or_404()

    strand = design.find_strand(body.strand_id)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {body.strand_id!r} not found.")
    if body.sequence is None and body.modification is None:
        raise HTTPException(
            400, detail="At least one of sequence or modification must be provided."
        )

    if body.sequence is not None:
        if not body.sequence or not re.match(r"^[ACGTNacgtn]+$", body.sequence):
            raise HTTPException(
                400, detail="sequence must contain only ACGTN characters."
            )

    if body.modification is not None:
        if body.modification not in VALID_MODIFICATIONS:
            raise HTTPException(
                400,
                detail=f"Unknown modification {body.modification!r}. "
                f"Valid values: {sorted(VALID_MODIFICATIONS)}",
            )

    if any(
        x.strand_id == body.strand_id and x.end == body.end for x in design.extensions
    ):
        raise HTTPException(
            400,
            detail=f"Strand {body.strand_id!r} already has a {body.end} extension.",
        )

    new_ext = StrandExtension(
        strand_id=body.strand_id,
        end=body.end,
        sequence=body.sequence.upper() if body.sequence else None,
        modification=body.modification,
        label=body.label,
    )

    design, report = design_state.mutate_with_reconcile(
        lambda d: d.extensions.append(new_ext)
    )
    return {"extension": new_ext.model_dump(), **_design_response(design, report)}


@router.put("/design/extensions/{ext_id}")
def update_strand_extension(ext_id: str, body: StrandExtensionUpdateRequest) -> dict:
    """Update the sequence, modification, or label of an existing strand extension."""
    import re

    design = design_state.get_or_404()
    ext = next((x for x in design.extensions if x.id == ext_id), None)
    if ext is None:
        raise HTTPException(404, detail=f"StrandExtension {ext_id!r} not found.")

    new_seq = body.sequence if body.sequence is not None else ext.sequence
    new_mod = body.modification if body.modification is not None else ext.modification
    new_lbl = body.label if body.label is not None else ext.label

    # Allow explicit None to clear a field: treat empty string as clear.
    if body.sequence == "":
        new_seq = None
    if body.modification == "":
        new_mod = None

    if new_seq is None and new_mod is None:
        raise HTTPException(
            400, detail="At least one of sequence or modification must be set."
        )

    if new_seq is not None:
        if not re.match(r"^[ACGTNacgtn]+$", new_seq):
            raise HTTPException(
                400, detail="sequence must contain only ACGTN characters."
            )
        new_seq = new_seq.upper()

    if new_mod is not None and new_mod not in VALID_MODIFICATIONS:
        raise HTTPException(
            400,
            detail=f"Unknown modification {new_mod!r}. "
            f"Valid values: {sorted(VALID_MODIFICATIONS)}",
        )

    def _apply(d: Design) -> None:
        target = next(x for x in d.extensions if x.id == ext_id)
        target.sequence = new_seq
        target.modification = new_mod
        target.label = new_lbl

    design, report = design_state.mutate_with_reconcile(_apply)
    updated = next(x for x in design.extensions if x.id == ext_id)
    return {"extension": updated.model_dump(), **_design_response(design, report)}


@router.delete("/design/extensions/{ext_id}")
def delete_strand_extension(ext_id: str) -> dict:
    """Remove a strand extension."""
    design = design_state.get_or_404()
    if not any(x.id == ext_id for x in design.extensions):
        raise HTTPException(404, detail=f"StrandExtension {ext_id!r} not found.")

    # Same fast path as batch delete: extension removal is not a topology mutation.
    design, report = design_state.mutate_and_validate(
        lambda d: setattr(d, "extensions", [x for x in d.extensions if x.id != ext_id])
    )
    return _design_response_with_geometry(design, report)
