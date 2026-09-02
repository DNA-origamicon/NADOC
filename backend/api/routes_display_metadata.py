"""
API layer — display-only metadata route handlers (extracted from crud.py).

This module hosts small sibling clusters that persist *display-only
metadata* blobs onto the active ``Design`` — they touch no topology or geometry,
so each one simply validates that its referenced ids exist, assigns a single
``Design`` field via ``mutate_and_validate``, and returns a design response
*without* geometry:

  - **Plate/tube layout** (``/design/plate-layout``) — the 96-well plate + tube
    assignment used for IDT ordering convenience (topic: plates_and_tubes).
  - **Per-region representation overrides** (``/design/representation-overrides``)
    — pin a render rep onto selected strands/clusters so a focal region can show
    full detail against a coarser background (topic: mixed_representation).
  - **Element visibility** (``/design/visibility``) — hidden base keys, explicit
    shown exceptions, and hidden cluster ids used by the unified hide system.

One reason to change: *how a display-only metadata blob is validated and persisted
on Design.* Both clusters share that exact parse → validate-ids → assign-field →
``_design_response`` shape.

Factored out of ``crud.py`` following the same template as the cluster (routes_clusters),
camera-poses (13-B), and extensions sub-routers — the plate-layout / representation
routes were physically interleaved under the old ``# ── Strand extensions`` banner and
were explicitly flagged a future extraction by Refactor #2.

URLs are unchanged from their previous home in crud.py. Mounting is done in
``backend/api/main.py`` via ``app.include_router(...)``.
"""

from __future__ import annotations

from typing import List, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.api import state as design_state

# _design_response is the shared response helper used by 100+ crud.py routes; it
# stays in crud.py and is imported back here (same convention as the other
# extracted routers). bespoke-B=0.
from backend.api.crud import _design_response
from backend.core.models import (
    Design,
    PlateLayout,
    RepresentationOverride,
    ViewVolume,
    StapleGroup,
    TubeAssignment,
    VisibilityState,
    WellAssignment,
)

router = APIRouter()


class PlateWellItem(BaseModel):
    strand_id: str
    plate: int
    row: int
    col: int


class PlateTubeItem(BaseModel):
    strand_id: str
    reason: Literal["modification", "long", "both", "manual"]


class PlateLayoutSaveRequest(BaseModel):
    orientation: Literal["8x12", "12x8"]
    plate_count: int
    wells: List[PlateWellItem]
    tubes: List[PlateTubeItem]


class RepresentationOverridesSaveRequest(BaseModel):
    """Replace the design's full list of per-region representation overrides."""

    overrides: List[RepresentationOverride]


class ViewVolumesSaveRequest(BaseModel):
    volumes: List[ViewVolume]


class StapleGroupsSaveRequest(BaseModel):
    groups: List[StapleGroup]


@router.get("/design/view-volumes", status_code=200)
def get_view_volumes() -> dict:
    """Return only persisted view volumes for fast UI/test verification."""
    design = design_state.get_or_404()
    return {
        "view_volumes": [volume.model_dump(mode="json") for volume in design.view_volumes],
        "revision": design_state.revision(),
    }


@router.put("/design/staple-groups", status_code=200)
def save_staple_groups(body: StapleGroupsSaveRequest) -> dict:
    """Persist the Staple groups sidebar state in the active design."""
    design = design_state.get_or_404()
    valid_ids = {s.id for s in design.strands}
    for group in body.groups:
        unknown = set(group.strand_ids) - valid_ids
        if unknown:
            raise HTTPException(404, detail=f"Strand {sorted(unknown)[0]!r} not found.")

    def _apply(d: Design) -> None:
        d.staple_groups = [group.model_copy(deep=True) for group in body.groups]

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.put("/design/plate-layout", status_code=200)
def save_plate_layout(body: PlateLayoutSaveRequest) -> dict:
    """Replace the design's plate/tube layout (IDT ordering convenience).

    Display-only metadata: this touches no topology or geometry, so it uses the
    plain mutate_and_validate path and returns a design response without geometry.
    All referenced strand IDs must exist in the design (404 otherwise).
    """
    design = design_state.get_or_404()
    valid_ids = {s.id for s in design.strands}
    for w in body.wells:
        if w.strand_id not in valid_ids:
            raise HTTPException(404, detail=f"Strand {w.strand_id!r} not found.")
    for t in body.tubes:
        if t.strand_id not in valid_ids:
            raise HTTPException(404, detail=f"Strand {t.strand_id!r} not found.")

    def _apply(d: Design) -> None:
        d.plate_layout = PlateLayout(
            orientation=body.orientation,
            plate_count=body.plate_count,
            wells=[WellAssignment(**w.model_dump()) for w in body.wells],
            tubes=[TubeAssignment(**t.model_dump()) for t in body.tubes],
        )

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.delete("/design/plate-layout", status_code=200)
def clear_plate_layout() -> dict:
    """Clear any saved plate/tube layout."""
    design = design_state.get_or_404()

    def _apply(d: Design) -> None:
        d.plate_layout = None

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.put("/design/representation-overrides", status_code=200)
def save_representation_overrides(body: RepresentationOverridesSaveRequest) -> dict:
    """Replace the design's per-region representation overrides.

    Display-only metadata (pin a render rep onto selected strands/clusters so a
    focal region can show full detail against a coarser background). Touches no
    topology or geometry. Every referenced strand and cluster id must exist
    (404 otherwise); an override that names neither is rejected (422).
    """
    design = design_state.get_or_404()
    valid_helices = {h.id for h in design.helices}
    valid_proteins = {a.id for a in design.protein_attachments}
    for ov in body.overrides:
        if not ov.segments and not ov.protein_attachment_ids:
            raise HTTPException(422, detail=f"Override {ov.id!r} covers no elements.")
        missing_h = {seg.helix_id for seg in ov.segments} - valid_helices
        if missing_h:
            raise HTTPException(
                404, detail=f"Helix id(s) not found: {sorted(missing_h)}"
            )
        missing_p = set(ov.protein_attachment_ids) - valid_proteins
        if missing_p:
            raise HTTPException(
                404, detail=f"Protein attachment id(s) not found: {sorted(missing_p)}"
            )

    def _apply(d: Design) -> None:
        d.representation_overrides = [ov.model_copy(deep=True) for ov in body.overrides]

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.delete("/design/representation-overrides", status_code=200)
def clear_representation_overrides() -> dict:
    """Clear all per-region representation overrides."""
    design = design_state.get_or_404()

    def _apply(d: Design) -> None:
        d.representation_overrides = []

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.put("/design/view-volumes", status_code=200)
def save_view_volumes(body: ViewVolumesSaveRequest) -> dict:
    """Replace spatial view-volume metadata without validating/returning a huge design.

    The request body has already validated every ViewVolume. Revalidating and then
    serializing the complete Design made a pointer-up on VoltronCoreArm transfer an
    82 MB response. This display-only assignment cannot invalidate topology.
    """
    def _apply(design: Design) -> None:
        design.view_volumes = [volume.model_copy(deep=True) for volume in body.volumes]

    design, revision = design_state.mutate_display_metadata(_apply)
    return {
        "view_volumes": [volume.model_dump(mode="json") for volume in design.view_volumes],
        "revision": revision,
    }


@router.put("/design/visibility", status_code=200)
def save_visibility_state(body: VisibilityState) -> dict:
    """Persist visibility metadata without adding a topology feature-log entry."""
    design_state.get_or_404()

    def _apply(d: Design) -> None:
        d.visibility_state = VisibilityState(
            hidden_base_keys=list(dict.fromkeys(body.hidden_base_keys)),
            shown_base_keys=list(dict.fromkeys(body.shown_base_keys)),
            hidden_cluster_ids=list(dict.fromkeys(body.hidden_cluster_ids)),
        )

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)
