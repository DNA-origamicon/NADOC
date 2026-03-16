"""
API layer — Phase 2 CRUD routes.

All mutating endpoints return:
  { "design": {...}, "validation": { "passed": bool, "results": [...] } }

plus the created/updated item for POST/PUT.

Routes
------
  GET    /design                                — active design + validation
  POST   /design                                — create new empty design
  PUT    /design/metadata                       — update name/description/author/tags
  GET    /design/geometry                       — full geometry (all helices)

  GET    /design/helices                        — list helices
  POST   /design/helices                        — add helix
  GET    /design/helices/{id}                   — get helix + its geometry
  PUT    /design/helices/{id}                   — replace helix
  DELETE /design/helices/{id}                   — delete helix (409 if strand references it)

  POST   /design/strands                        — add strand
  PUT    /design/strands/{id}                   — replace strand
  DELETE /design/strands/{id}                   — delete strand + cascade crossovers

  POST   /design/strands/{id}/domains           — append domain to strand
  DELETE /design/strands/{id}/domains/{index}   — remove domain by index

  GET    /design/crossovers/valid               — pre-compute valid positions (query: helix_a_id, helix_b_id)
  POST   /design/crossovers                     — add crossover
  DELETE /design/crossovers/{id}                — remove crossover

  POST   /design/load                           — load .nadoc file from server-side path
  POST   /design/save                           — save active design to server-side path
"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel

from backend.api import state as design_state
from backend.core.crossover_positions import (
    MAX_CROSSOVER_REACH_NM,
    clear_cache as clear_crossover_cache,
    sync_cache  as sync_crossover_cache,
    valid_crossover_positions,
)
from backend.core.geometry import nucleotide_positions
from backend.core.deformation import (
    deformed_frame_at_bp,
    deformed_helix_axes,
    deformed_nucleotide_positions,
    helices_crossing_planes,
)
from backend.core.models import (
    BendParams,
    Crossover,
    CrossoverType,
    DeformationOp,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    TwistParams,
    Vec3,
)
from backend.core.validator import ValidationReport

router = APIRouter()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validation_dict(report: ValidationReport, design: "Design | None" = None) -> dict:
    from backend.core.validator import _is_loop_strand
    loop_ids: list[str] = []
    if design is not None:
        loop_ids = [s.id for s in design.strands if not s.is_scaffold and _is_loop_strand(s)]
    return {
        "passed":        report.passed,
        "results":       [{"ok": r.ok, "message": r.message} for r in report.results],
        "loop_strand_ids": loop_ids,
    }


def _strand_nucleotide_info(design: Design) -> dict:
    """(helix_id, bp_index, Direction) → strand metadata dict."""
    info: dict = {}
    for strand in design.strands:
        if not strand.domains:
            continue
        first = strand.domains[0]
        last  = strand.domains[-1]
        five_prime_key  = (first.helix_id, first.start_bp, first.direction)
        three_prime_key = (last.helix_id,  last.end_bp,   last.direction)
        for di, domain in enumerate(strand.domains):
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                key = (domain.helix_id, bp, domain.direction)
                info[key] = {
                    "strand_id":      strand.id,
                    "is_scaffold":    strand.is_scaffold,
                    "is_five_prime":  key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                    "domain_index":   di,
                }
    return info


def _geometry_for_design_straight(design: Design) -> list[dict]:
    """Return geometry with no deformations applied (straight bundle positions)."""
    straight = design.model_copy(update={"deformations": []})
    return _geometry_for_design(straight)


def _straight_helix_axes(design: Design) -> list[dict]:
    """Return un-deformed helix axes (axis_start / axis_end from the model, no samples)."""
    return [
        {
            "helix_id": h.id,
            "start":    [h.axis_start.x, h.axis_start.y, h.axis_start.z],
            "end":      [h.axis_end.x,   h.axis_end.y,   h.axis_end.z],
            "samples":  None,
        }
        for h in design.helices
    ]


def _geometry_for_design(design: Design) -> list[dict]:
    nuc_info = _strand_nucleotide_info(design)
    _missing = {"strand_id": None, "is_scaffold": False,
                "is_five_prime": False, "is_three_prime": False, "domain_index": 0}
    result: list[dict] = []
    for helix in design.helices:
        for nuc in deformed_nucleotide_positions(helix, design):
            key = (nuc.helix_id, nuc.bp_index, nuc.direction)
            sinfo = nuc_info.get(key, _missing)
            result.append({
                "helix_id":          nuc.helix_id,
                "bp_index":          nuc.bp_index,
                "direction":         nuc.direction.value,
                "backbone_position": nuc.position.tolist(),
                "base_position":     nuc.base_position.tolist(),
                "base_normal":       nuc.base_normal.tolist(),
                "axis_tangent":      nuc.axis_tangent.tolist(),
                **sinfo,
            })
    return result


def _design_response(design: Design, report: ValidationReport) -> dict:
    return {
        "design":     design.to_dict(),
        "validation": _validation_dict(report, design),
    }


def _find_helix(design: Design, helix_id: str) -> Helix:
    for h in design.helices:
        if h.id == helix_id:
            return h
    raise HTTPException(404, detail=f"Helix {helix_id!r} not found.")


def _find_strand(design: Design, strand_id: str) -> Strand:
    for s in design.strands:
        if s.id == strand_id:
            return s
    raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")


# ── Request models ────────────────────────────────────────────────────────────


class CreateDesignRequest(BaseModel):
    name: str = "Untitled"
    lattice_type: LatticeType = LatticeType.HONEYCOMB


class MetadataUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    author: Optional[str] = None
    tags: Optional[List[str]] = None


class HelixRequest(BaseModel):
    axis_start: Vec3
    axis_end: Vec3
    length_bp: int
    phase_offset: float = 0.0


class DomainRequest(BaseModel):
    helix_id: str
    start_bp: int
    end_bp: int
    direction: Direction


class StrandRequest(BaseModel):
    domains: List[DomainRequest] = []
    is_scaffold: bool = False
    sequence: Optional[str] = None


class CrossoverRequest(BaseModel):
    strand_a_id: str
    domain_a_index: int
    strand_b_id: str
    domain_b_index: int
    crossover_type: CrossoverType


class FilePathRequest(BaseModel):
    path: str


class DesignImportRequest(BaseModel):
    content: str


class BundleRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int
    name: str = "Bundle"
    plane: str = "XY"


class BundleSegmentRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int           # may be negative — extrudes in -axis direction
    plane: str = "XY"
    offset_nm: float = 0.0   # position of axis_start along the plane normal


class BundleContinuationRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...] — may mix continuation and fresh cells
    length_bp: int
    plane: str = "XY"
    offset_nm: float = 0.0


class BundleDeformedContinuationRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int
    # Deformed cross-section frame from GET /design/deformed-frame
    grid_origin: List[float]   # [x, y, z]
    axis_dir:    List[float]   # [x, y, z]
    frame_right: List[float]   # [x, y, z]
    frame_up:    List[float]   # [x, y, z]
    plane: str = "XY"          # used for helix/strand ID naming only


class StapleCrossoverRequest(BaseModel):
    helix_a_id: str
    bp_a: int
    direction_a: Direction
    helix_b_id: str
    bp_b: int
    direction_b: Direction


class NickRequest(BaseModel):
    helix_id: str
    bp_index: int
    direction: Direction


# ── Design endpoints ──────────────────────────────────────────────────────────


@router.get("/design")
def get_active_design() -> dict:
    """Return the active design and its current validation report."""
    from backend.core.validator import validate_design
    design = design_state.get_or_404()
    report = validate_design(design)
    return _design_response(design, report)


@router.get("/design/export")
def export_design() -> Response:
    """Download the active design as a .nadoc file."""
    design = design_state.get_or_404()
    filename = f"{design.metadata.name or 'design'}.nadoc"
    # Sanitise filename: replace characters that are problematic in Content-Disposition.
    safe = "".join(c if c.isalnum() or c in "-_. " else "_" for c in filename)
    return Response(
        content=design.to_json(),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.post("/design/undo")
def undo_design() -> dict:
    """Revert the active design to the state before the last mutation.

    Returns 404 if nothing to undo.
    """
    design, report = design_state.undo()
    return _design_response(design, report)


@router.post("/design/redo")
def redo_design() -> dict:
    """Re-apply the last undone mutation.

    Returns 404 if nothing to redo.
    """
    design, report = design_state.redo()
    return _design_response(design, report)


@router.post("/design/bundle-segment", status_code=201)
def add_bundle_segment(body: BundleSegmentRequest) -> dict:
    """Append a honeycomb bundle segment to the active design (slice-plane extrude).

    Generates collision-safe helix/strand IDs automatically.
    Returns the updated design and validation report.
    """
    from backend.core.lattice import make_bundle_segment
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
        updated = make_bundle_segment(design, cells, body.length_bp, body.plane, body.offset_nm)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/bundle-continuation", status_code=201)
def add_bundle_continuation(body: BundleContinuationRequest) -> dict:
    """Extrude a bundle segment in continuation mode (occupied cells ending at offset extend existing strands).

    Fresh cells get new scaffold + staple strands; continuation cells append domains to the
    existing strands whose helices end at offset_nm.
    """
    from backend.core.lattice import make_bundle_continuation
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        cells   = [tuple(c) for c in body.cells]  # type: ignore[misc]
        updated = make_bundle_continuation(design, cells, body.length_bp, body.plane, body.offset_nm)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.get("/design/deformed-frame")
def get_deformed_frame(
    source_bp: int = Query(..., description="bp index at which to sample the deformed frame"),
    ref_helix_id: Optional[str] = Query(None, description="Reference helix ID to select arm"),
) -> dict:
    """Return the deformed cross-section frame at source_bp.

    Used by the frontend to orient the slice plane after a bend/twist.

    Returns: { grid_origin, axis_dir, frame_right, frame_up } — each a list of 3 floats.
    """
    design = design_state.get_or_404()
    return deformed_frame_at_bp(design, source_bp, ref_helix_id)


@router.post("/design/bundle-deformed-continuation", status_code=201)
def add_bundle_deformed_continuation(body: BundleDeformedContinuationRequest) -> dict:
    """Extrude a continuation segment using a deformed cross-section frame.

    Positions new helices using grid_origin/axis_dir/frame_right/frame_up from
    a prior call to GET /design/deformed-frame.  Continuation detection uses
    3-D proximity of deformed helix endpoints.
    """
    from backend.core.lattice import make_bundle_deformed_continuation
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    frame = {
        "grid_origin": body.grid_origin,
        "axis_dir":    body.axis_dir,
        "frame_right": body.frame_right,
        "frame_up":    body.frame_up,
    }
    # Build deformed endpoints from current geometry
    axes = deformed_helix_axes(design)
    deformed_endpoints = {ax["helix_id"]: {"start": ax["start"], "end": ax["end"]} for ax in axes}

    try:
        cells   = [tuple(c) for c in body.cells]  # type: ignore[misc]
        updated = make_bundle_deformed_continuation(
            design, cells, body.length_bp, frame, deformed_endpoints, body.plane
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/bundle", status_code=201)
def create_bundle(body: BundleRequest) -> dict:
    """Create a honeycomb bundle design from a list of (row, col) lattice cells."""
    from backend.core.lattice import make_bundle_design
    from backend.core.validator import validate_design

    try:
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
        new_design = make_bundle_design(cells, body.length_bp, body.name, body.plane)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(new_design)
    report = validate_design(new_design)
    return _design_response(new_design, report)


@router.post("/design", status_code=201)
def create_design(body: CreateDesignRequest) -> dict:
    """Create and activate a new empty design, discarding any current design."""
    from backend.core.validator import validate_design
    new_design = Design(
        metadata=DesignMetadata(name=body.name),
        lattice_type=body.lattice_type,
    )
    design_state.set_design(new_design)
    report = validate_design(new_design)
    return _design_response(new_design, report)


@router.put("/design/metadata")
def update_metadata(body: MetadataUpdateRequest) -> dict:
    """Update design name, description, author, or tags."""
    def _apply(d: Design) -> None:
        if body.name        is not None: d.metadata.name        = body.name
        if body.description is not None: d.metadata.description = body.description
        if body.author      is not None: d.metadata.author      = body.author
        if body.tags        is not None: d.metadata.tags        = body.tags

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.get("/design/geometry")
def get_geometry(apply_deformations: bool = Query(True)) -> dict:
    """Return full geometry (all helices) for the active design.

    Returns { nucleotides: [...], helix_axes: [{helix_id, start, end}, ...] }

    When apply_deformations=false, returns the straight (un-deformed) bundle
    positions regardless of any DeformationOps stored on the design.
    """
    design = design_state.get_or_404()
    if apply_deformations:
        return {
            "nucleotides": _geometry_for_design(design),
            "helix_axes":  deformed_helix_axes(design),
        }
    else:
        return {
            "nucleotides": _geometry_for_design_straight(design),
            "helix_axes":  _straight_helix_axes(design),
        }


@router.post("/design/load")
def load_design(body: FilePathRequest) -> dict:
    """Load a .nadoc file from the given server-side path."""
    from backend.core.validator import validate_design
    path = os.path.abspath(body.path)
    if not os.path.isfile(path):
        raise HTTPException(400, detail=f"File not found: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
        design = Design.from_json(text)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to load design: {exc}") from exc
    design_state.clear_history()   # fresh baseline — no undo into previous session
    clear_crossover_cache()        # force recompute for new design's helix geometry
    design_state.set_design(design)
    report = validate_design(design)
    return _design_response(design, report)


@router.post("/design/import", status_code=200)
def import_design(body: DesignImportRequest) -> dict:
    """Load a design from raw .nadoc JSON content sent by the browser.

    Unlike ``/design/load`` (which reads a server-side file path), this endpoint
    accepts the file content directly, enabling browser-based file-open dialogs.
    Clears undo history and crossover cache so the loaded design starts fresh.
    """
    from backend.core.validator import validate_design
    try:
        design = Design.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to parse design: {exc}") from exc
    design_state.clear_history()
    clear_crossover_cache()
    design_state.set_design(design)
    report = validate_design(design)
    return _design_response(design, report)


@router.post("/design/save")
def save_design(body: FilePathRequest) -> dict:
    """Save the active design to the given server-side path as .nadoc JSON."""
    design = design_state.get_or_404()
    path = os.path.abspath(body.path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(design.to_json())
    except OSError as exc:
        raise HTTPException(500, detail=f"Failed to save design: {exc}") from exc
    return {"saved_to": path}


# ── Helix endpoints ───────────────────────────────────────────────────────────


@router.get("/design/helices")
def list_helices() -> list[dict]:
    design = design_state.get_or_404()
    return [h.model_dump() for h in design.helices]


@router.post("/design/helices", status_code=201)
def add_helix(body: HelixRequest) -> dict:
    new_helix = Helix(
        axis_start=body.axis_start,
        axis_end=body.axis_end,
        length_bp=body.length_bp,
        phase_offset=body.phase_offset,
    )
    design, report = design_state.mutate_and_validate(
        lambda d: d.helices.append(new_helix)
    )
    return {
        "helix":      new_helix.model_dump(),
        "geometry":   [
            {
                "helix_id":          n.helix_id,
                "bp_index":          n.bp_index,
                "direction":         n.direction.value,
                "backbone_position": n.position.tolist(),
                "base_position":     n.base_position.tolist(),
                "base_normal":       n.base_normal.tolist(),
                "axis_tangent":      n.axis_tangent.tolist(),
            }
            for n in nucleotide_positions(new_helix)
        ],
        **_design_response(design, report),
    }


@router.get("/design/helices/{helix_id}")
def get_helix(helix_id: str) -> dict:
    design = design_state.get_or_404()
    helix = _find_helix(design, helix_id)
    return {
        "helix":    helix.model_dump(),
        "geometry": [
            {
                "helix_id":          n.helix_id,
                "bp_index":          n.bp_index,
                "direction":         n.direction.value,
                "backbone_position": n.position.tolist(),
                "base_position":     n.base_position.tolist(),
                "base_normal":       n.base_normal.tolist(),
                "axis_tangent":      n.axis_tangent.tolist(),
            }
            for n in nucleotide_positions(helix)
        ],
    }


@router.put("/design/helices/{helix_id}")
def update_helix(helix_id: str, body: HelixRequest) -> dict:
    replacement = Helix(
        id=helix_id,
        axis_start=body.axis_start,
        axis_end=body.axis_end,
        length_bp=body.length_bp,
        phase_offset=body.phase_offset,
    )

    def _apply(d: Design) -> None:
        for i, h in enumerate(d.helices):
            if h.id == helix_id:
                d.helices[i] = replacement
                return
        raise HTTPException(404, detail=f"Helix {helix_id!r} not found.")

    design, report = design_state.mutate_and_validate(_apply)
    return {
        "helix": replacement.model_dump(),
        **_design_response(design, report),
    }


@router.delete("/design/helices/{helix_id}")
def delete_helix(helix_id: str) -> dict:
    # Referential integrity check — reject if any strand domain references this helix.
    design = design_state.get_or_404()
    blocking = [
        s.id for s in design.strands
        if any(dom.helix_id == helix_id for dom in s.domains)
    ]
    if blocking:
        raise HTTPException(
            409,
            detail=f"Helix referenced by strands: {blocking}",
        )

    def _apply(d: Design) -> None:
        idx = next((i for i, h in enumerate(d.helices) if h.id == helix_id), None)
        if idx is None:
            raise HTTPException(404, detail=f"Helix {helix_id!r} not found.")
        d.helices.pop(idx)

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


# ── Strand endpoints ──────────────────────────────────────────────────────────


@router.post("/design/strands", status_code=201)
def add_strand(body: StrandRequest) -> dict:
    new_strand = Strand(
        domains=[
            Domain(
                helix_id=dom.helix_id,
                start_bp=dom.start_bp,
                end_bp=dom.end_bp,
                direction=dom.direction,
            )
            for dom in body.domains
        ],
        is_scaffold=body.is_scaffold,
        sequence=body.sequence,
    )
    design, report = design_state.mutate_and_validate(
        lambda d: d.strands.append(new_strand)
    )
    return {
        "strand": new_strand.model_dump(),
        **_design_response(design, report),
    }


@router.put("/design/strands/{strand_id}")
def update_strand(strand_id: str, body: StrandRequest) -> dict:
    replacement = Strand(
        id=strand_id,
        domains=[
            Domain(
                helix_id=dom.helix_id,
                start_bp=dom.start_bp,
                end_bp=dom.end_bp,
                direction=dom.direction,
            )
            for dom in body.domains
        ],
        is_scaffold=body.is_scaffold,
        sequence=body.sequence,
    )

    def _apply(d: Design) -> None:
        for i, s in enumerate(d.strands):
            if s.id == strand_id:
                d.strands[i] = replacement
                return
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")

    design, report = design_state.mutate_and_validate(_apply)
    return {
        "strand": replacement.model_dump(),
        **_design_response(design, report),
    }


@router.delete("/design/strands/{strand_id}")
def delete_strand(strand_id: str) -> dict:
    # Collect crossover IDs that reference this strand (cascade delete).
    design = design_state.get_or_404()
    _find_strand(design, strand_id)  # 404 if not found
    xo_ids = [
        xo.id for xo in design.crossovers
        if xo.strand_a_id == strand_id or xo.strand_b_id == strand_id
    ]

    def _apply(d: Design) -> None:
        d.strands   = [s for s in d.strands   if s.id != strand_id]
        d.crossovers = [x for x in d.crossovers if x.id not in xo_ids]

    design, report = design_state.mutate_and_validate(_apply)
    return {
        "removed_crossovers": xo_ids,
        **_design_response(design, report),
    }


# ── Domain sub-resource ───────────────────────────────────────────────────────


@router.post("/design/strands/{strand_id}/domains", status_code=201)
def add_domain(strand_id: str, body: DomainRequest) -> dict:
    new_domain = Domain(
        helix_id=body.helix_id,
        start_bp=body.start_bp,
        end_bp=body.end_bp,
        direction=body.direction,
    )

    def _apply(d: Design) -> None:
        strand = _find_strand(d, strand_id)
        strand.domains.append(new_domain)

    design, report = design_state.mutate_and_validate(_apply)
    strand = _find_strand(design, strand_id)
    return {
        "strand": strand.model_dump(),
        **_design_response(design, report),
    }


@router.delete("/design/strands/{strand_id}/domains/{domain_index}")
def delete_domain(strand_id: str, domain_index: int) -> dict:
    # Reject if a crossover references this domain index on this strand.
    design = design_state.get_or_404()
    strand = _find_strand(design, strand_id)
    if domain_index < 0 or domain_index >= len(strand.domains):
        raise HTTPException(400, detail=f"domain_index {domain_index} out of range.")
    blocking_xo = [
        xo.id for xo in design.crossovers
        if (xo.strand_a_id == strand_id and xo.domain_a_index == domain_index)
        or (xo.strand_b_id == strand_id and xo.domain_b_index == domain_index)
    ]
    if blocking_xo:
        raise HTTPException(
            409,
            detail=f"Cannot delete domain: crossover(s) reference domain_index {domain_index}: {blocking_xo}",
        )

    def _apply(d: Design) -> None:
        s = _find_strand(d, strand_id)
        s.domains.pop(domain_index)

    design, report = design_state.mutate_and_validate(_apply)
    strand = _find_strand(design, strand_id)
    return {
        "strand": strand.model_dump(),
        **_design_response(design, report),
    }


# ── Crossover endpoints ───────────────────────────────────────────────────────


@router.get("/design/crossovers/valid")
def get_valid_crossover_positions(
    helix_a_id: str = Query(..., description="ID of the first helix"),
    helix_b_id: str = Query(..., description="ID of the second helix"),
) -> dict:
    """Pre-compute valid crossover bp positions between two helices (DTP-2)."""
    design = design_state.get_or_404()
    helix_a = _find_helix(design, helix_a_id)
    helix_b = _find_helix(design, helix_b_id)
    candidates = valid_crossover_positions(helix_a, helix_b)
    return {
        "helix_a_id": helix_a_id,
        "helix_b_id": helix_b_id,
        "max_reach_nm": MAX_CROSSOVER_REACH_NM,
        "positions": [
            {
                "bp_a": c.bp_a, "bp_b": c.bp_b,
                "distance_nm": c.distance_nm,
                "direction_a": c.direction_a.value,
                "direction_b": c.direction_b.value,
            }
            for c in candidates
        ],
    }


def _half_placed_flags(design: Design) -> set[tuple]:
    """Return a set of (helix_from_id, bp_from, dir_from, helix_to_id, bp_to, dir_to)
    tuples for every consecutive-domain backbone jump currently present in any strand.
    Used to compute half_ab_placed / half_ba_placed flags.
    """
    placed: set[tuple] = set()
    for strand in design.strands:
        for k in range(len(strand.domains) - 1):
            d0 = strand.domains[k]
            d1 = strand.domains[k + 1]
            if d0.helix_id == d1.helix_id:
                continue  # same-helix; not a cross-helix jump
            placed.add((d0.helix_id, d0.end_bp, d0.direction, d1.helix_id, d1.start_bp, d1.direction))
    return placed


@router.get("/design/crossovers/all-valid")
def get_all_valid_crossover_positions() -> list[dict]:
    """Return valid crossover positions for every neighboring helix pair in the design.

    Two helices are considered neighbors if at least one (bp_a, bp_b) pair has
    backbone-to-backbone distance ≤ MAX_CROSSOVER_REACH_NM.  The response is a
    list of per-pair objects, each containing direction information so the frontend
    knows exactly which strand to operate on when a crossover is placed.

    Scaffold positions are flagged via ``is_scaffold_a`` / ``is_scaffold_b`` so the
    frontend can filter staple-only display without a separate lookup.

    ``half_ab_placed`` / ``half_ba_placed`` indicate whether each half of the DX
    junction has already been placed.  The frontend uses these to hide the
    corresponding cylinder once its half has been committed.
    """
    design = design_state.get_or_404()
    sync_crossover_cache(design)   # invalidate if helix set changed (extrusion/undo/redo)
    nuc_info = _strand_nucleotide_info(design)
    placed   = _half_placed_flags(design)
    helices  = design.helices
    result: list[dict] = []

    for i in range(len(helices)):
        for j in range(i + 1, len(helices)):
            ha = helices[i]
            hb = helices[j]
            candidates = valid_crossover_positions(ha, hb)
            if not candidates:
                continue
            positions = []
            for c in candidates:
                key_a = (ha.id, c.bp_a, c.direction_a)
                key_b = (hb.id, c.bp_b, c.direction_b)
                info_a = nuc_info.get(key_a, {})
                info_b = nuc_info.get(key_b, {})
                # half_ab: jump from helix_a@bp_a to helix_b@bp_b
                half_ab = (ha.id, c.bp_a, c.direction_a, hb.id, c.bp_b, c.direction_b) in placed
                # half_ba: jump from helix_b@bp_b to helix_a@bp_a
                half_ba = (hb.id, c.bp_b, c.direction_b, ha.id, c.bp_a, c.direction_a) in placed
                positions.append({
                    "bp_a":           c.bp_a,
                    "bp_b":           c.bp_b,
                    "distance_nm":    c.distance_nm,
                    "direction_a":    c.direction_a.value,
                    "direction_b":    c.direction_b.value,
                    "is_scaffold_a":  info_a.get("is_scaffold", False),
                    "is_scaffold_b":  info_b.get("is_scaffold", False),
                    "half_ab_placed": half_ab,
                    "half_ba_placed": half_ba,
                })
            result.append({
                "helix_a_id": ha.id,
                "helix_b_id": hb.id,
                "positions":  positions,
            })

    return result


@router.post("/design/staple-crossover", status_code=201)
def add_staple_crossover(body: StapleCrossoverRequest) -> dict:
    """Perform a staple strand crossover: split two strands at the given bp positions
    and reconnect them so the backbone path jumps from helix_a bp_a to helix_b bp_b.

    This is a true topological operation — the strand domains are modified in-place.
    Raises 400 if either strand is a scaffold or both positions are on the same strand.
    """
    from backend.core.lattice import make_staple_crossover
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        updated = make_staple_crossover(
            design,
            body.helix_a_id, body.bp_a, body.direction_a,
            body.helix_b_id, body.bp_b, body.direction_b,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/half-crossover", status_code=201)
def add_half_crossover(body: StapleCrossoverRequest) -> dict:
    """Place a single backbone jump (one half of a DX junction).

    Unlike ``/design/staple-crossover`` which atomically places both crossovers
    of a DX motif, this endpoint places only the A→B jump.  The displaced strand
    pieces (B_left and A_right) become independent free strands.

    If the target positions happen to be the 3′ end of strand_b and the 5′ start
    of strand_a respectively, the two pieces are simply concatenated (endpoint-join
    case — no splitting required).

    Raises 400 if either position is on a scaffold strand.
    """
    from backend.core.lattice import make_half_crossover
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        updated = make_half_crossover(
            design,
            body.helix_a_id, body.bp_a, body.direction_a,
            body.helix_b_id, body.bp_b, body.direction_b,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/nick", status_code=201)
def add_nick(body: NickRequest) -> dict:
    """Create a nick (strand break) at the 3′ side of the specified nucleotide.

    The strand covering (helix_id, bp_index, direction) is split: bp_index
    becomes the 3′ end of the left fragment; the next nucleotide in 5′→3′ order
    becomes the 5′ end of the right fragment.

    Raises 400 if bp_index is the 3′ terminus of the strand (nothing to split).
    """
    from backend.core.lattice import make_nick
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        updated = make_nick(design, body.helix_id, body.bp_index, body.direction)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class AutoScaffoldRequest(BaseModel):
    mode: str = "seam_line"    # "seam_line" | "end_to_end"
    nick_offset: int = 7       # bp from helix-1 terminal where scaffold 5′ starts


@router.post("/design/auto-scaffold", status_code=200)
def run_auto_scaffold(body: AutoScaffoldRequest = AutoScaffoldRequest()) -> dict:
    """Route the scaffold strand through all helices via a greedy Hamiltonian path.

    Replaces individual per-helix scaffold strands with one continuous scaffold.
    Two modes are supported:
      - ``seam_line``: mid-helix DX crossovers at valid backbone positions (default).
      - ``end_to_end``: full-domain concatenation, no mid-helix crossovers.

    The scaffold's 5′ end is placed ``nick_offset`` bp from helix 1's terminal
    (default 7).  Requires an even number of helices.

    Returns 422 if routing fails (odd helix count or disconnected graph).
    """
    from backend.core.lattice import auto_scaffold
    from backend.core.validator import validate_design
    from fastapi import HTTPException

    design = design_state.get_or_404()
    try:
        updated = auto_scaffold(design, mode=body.mode, nick_offset=body.nick_offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Deformation endpoints ─────────────────────────────────────────────────────


class AddDeformationBody(BaseModel):
    type: str           # 'twist' | 'bend'
    plane_a_bp: int
    plane_b_bp: int
    affected_helix_ids: list[str] = []
    params: dict        # raw dict; validated into TwistParams | BendParams below
    preview: bool = False  # when True, use silent update (no undo push)


class UpdateDeformationBody(BaseModel):
    params: dict        # updated params only


def _parse_params(op_type: str, params_dict: dict):
    if op_type == 'twist':
        return TwistParams(**{k: v for k, v in params_dict.items() if k != 'kind'})
    elif op_type == 'bend':
        return BendParams(**{k: v for k, v in params_dict.items() if k != 'kind'})
    raise HTTPException(400, detail=f"Unknown deformation type {op_type!r}")


@router.post("/design/deformation", status_code=200)
def add_deformation(body: AddDeformationBody) -> dict:
    """Add a twist or bend deformation op to the active design.

    Pushes to the undo stack.  If affected_helix_ids is empty, auto-populates
    with all helices whose bp range covers both planes.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    params = _parse_params(body.type, body.params)

    helix_ids = body.affected_helix_ids or helices_crossing_planes(
        design, body.plane_a_bp, body.plane_b_bp
    )

    op = DeformationOp(
        type=body.type,
        plane_a_bp=body.plane_a_bp,
        plane_b_bp=body.plane_b_bp,
        affected_helix_ids=helix_ids,
        params=params,
    )
    updated = design.model_copy(
        update={"deformations": list(design.deformations) + [op]}, deep=True
    )
    if body.preview:
        design_state.set_design_silent(updated)
    else:
        design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/deformation/{op_id}", status_code=200)
def update_deformation(op_id: str, body: UpdateDeformationBody) -> dict:
    """Update params of an existing deformation op (live preview — no undo push)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    ops = list(design.deformations)
    idx = next((i for i, op in enumerate(ops) if op.id == op_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Deformation {op_id!r} not found.")

    old_op = ops[idx]
    new_params = _parse_params(old_op.type, body.params)
    ops[idx] = old_op.model_copy(update={"params": new_params})

    updated = design.model_copy(update={"deformations": ops}, deep=True)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/deformation/{op_id}", status_code=200)
def delete_deformation(op_id: str, preview: bool = Query(False)) -> dict:
    """Remove a deformation op.

    When preview=true, uses a silent update (no undo push).  Used during
    preview cycles so only confirmed deformations appear in undo history.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    ops = [op for op in design.deformations if op.id != op_id]
    if len(ops) == len(design.deformations):
        raise HTTPException(404, detail=f"Deformation {op_id!r} not found.")

    updated = design.model_copy(update={"deformations": ops}, deep=True)
    if preview:
        design_state.set_design_silent(updated)
    else:
        design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/loop-skip/twist", status_code=200)
def apply_twist_loop_skips(body: dict) -> dict:
    """
    Compute and apply loop/skip modifications to produce target global twist.

    Body:
      helix_ids   : list[str]  — helices to modify (must all cross both planes)
      plane_a_bp  : int        — start of modified segment (bp index)
      plane_b_bp  : int        — end of modified segment (bp index)
      target_twist_deg : float — desired twist (+ = left-handed, − = right-handed)

    Returns the full design response plus a "loop_skips" summary:
      { helix_id: [ { bp_index, delta }, ... ], ... }

    Raises 422 if target exceeds physical limits.
    """
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        twist_loop_skips,
    )
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    helix_ids: list[str] = body.get("helix_ids", [])
    plane_a_bp: int = int(body["plane_a_bp"])
    plane_b_bp: int = int(body["plane_b_bp"])
    target_twist_deg: float = float(body["target_twist_deg"])

    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in helix_ids if hid in h_map]
    if not segment_helices:
        raise HTTPException(422, "No valid helix_ids provided.")

    try:
        mods = twist_loop_skips(segment_helices, plane_a_bp, plane_b_bp, target_twist_deg)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    updated = apply_loop_skips(design, mods)
    design_state.set_design(updated)
    report = validate_design(updated)
    response = _design_response(updated, report)
    response["loop_skips"] = {
        hid: [{"bp_index": ls.bp_index, "delta": ls.delta} for ls in lst]
        for hid, lst in mods.items()
    }
    return response


@router.post("/design/loop-skip/bend", status_code=200)
def apply_bend_loop_skips(body: dict) -> dict:
    """
    Compute and apply loop/skip modifications to produce target bend radius.

    Body:
      helix_ids    : list[str]
      plane_a_bp   : int
      plane_b_bp   : int
      radius_nm    : float  — desired radius of curvature (nm); minimum ≈ 5 nm
      direction_deg: float  — bend direction in cross-section (0 = +X)

    Raises 422 if radius is below the physical minimum for this cross-section.
    """
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        bend_loop_skips,
    )
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    helix_ids: list[str] = body.get("helix_ids", [])
    plane_a_bp: int = int(body["plane_a_bp"])
    plane_b_bp: int = int(body["plane_b_bp"])
    radius_nm: float = float(body["radius_nm"])
    direction_deg: float = float(body.get("direction_deg", 0.0))

    if radius_nm <= 0:
        raise HTTPException(422, "radius_nm must be positive.")

    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in helix_ids if hid in h_map]
    if not segment_helices:
        raise HTTPException(422, "No valid helix_ids provided.")

    try:
        mods = bend_loop_skips(segment_helices, plane_a_bp, plane_b_bp, radius_nm, direction_deg)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    updated = apply_loop_skips(design, mods)
    design_state.set_design(updated)
    report = validate_design(updated)
    response = _design_response(updated, report)
    response["loop_skips"] = {
        hid: [{"bp_index": ls.bp_index, "delta": ls.delta} for ls in lst]
        for hid, lst in mods.items()
    }
    return response


@router.get("/design/loop-skip/limits", status_code=200)
def get_loop_skip_limits(
    helix_ids: str = Query(..., description="comma-separated helix IDs"),
    plane_a_bp: int = Query(...),
    plane_b_bp: int = Query(...),
    direction_deg: float = Query(0.0),
) -> dict:
    """
    Return the physical limits for loop/skip modifications over the given segment.

    Returns:
      min_bend_radius_nm : float  — minimum achievable radius (nm)
      max_twist_deg      : float  — maximum |twist| achievable
      n_cells            : int    — number of 7-bp array cells in the segment
    """
    from backend.core.loop_skip_calculator import (
        _cell_boundaries,
        max_twist_deg,
        min_bend_radius_nm,
    )

    design = design_state.get_or_404()
    ids = [s.strip() for s in helix_ids.split(",") if s.strip()]
    h_map = {h.id: h for h in design.helices}
    segment_helices = [h_map[hid] for hid in ids if hid in h_map]

    cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(cells)
    min_r = min_bend_radius_nm(segment_helices, plane_a_bp, plane_b_bp, direction_deg)
    max_t = max_twist_deg(n_cells)

    return {
        "min_bend_radius_nm": min_r if min_r != float("inf") else None,
        "max_twist_deg":      max_t,
        "n_cells":            n_cells,
    }


@router.delete("/design/loop-skip", status_code=200)
def clear_loop_skip_range(
    helix_ids: str = Query(..., description="comma-separated helix IDs"),
    plane_a_bp: int = Query(...),
    plane_b_bp: int = Query(...),
) -> dict:
    """Remove all loop/skip modifications in [plane_a_bp, plane_b_bp) from the given helices."""
    from backend.core.loop_skip_calculator import clear_loop_skips
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    ids = [s.strip() for s in helix_ids.split(",") if s.strip()]
    updated = clear_loop_skips(design, ids, plane_a_bp, plane_b_bp)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/loop-skip/apply-deformations", status_code=200)
def apply_loop_skips_from_deformations() -> dict:
    """Apply all DeformationOps on the design as loop/skip topology modifications.

    For each DeformationOp:
      - twist → call twist_loop_skips with computed target_twist_deg
      - bend  → convert angle_deg to radius_nm and call bend_loop_skips

    All modifications are merged and applied atomically via apply_loop_skips.
    Pushes to undo history.

    Requires that the design has at least one crossover placed (crossovers break the
    bundle into 7-bp cells which are required for loop/skip placement).
    """
    import math
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        bend_loop_skips,
        twist_loop_skips,
        CELL_BP_DEFAULT,
    )
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    # Check for cross-helix domain transitions (design.crossovers is always [] —
    # actual crossover topology lives in strand domain sequences).
    has_crossovers = any(
        d0.helix_id != d1.helix_id
        for strand in design.strands
        for d0, d1 in zip(strand.domains, strand.domains[1:])
    )
    if not has_crossovers:
        raise HTTPException(
            400,
            detail="No crossovers placed. Add crossovers before applying staple routing.",
        )
    if not design.deformations:
        raise HTTPException(400, detail="No deformation ops on the current design.")

    helix_map = {h.id: h for h in design.helices}

    # Accumulate all per-helix modifications from every DeformationOp
    all_mods: dict[str, list] = {}

    for op in design.deformations:
        affected = [helix_map[hid] for hid in op.affected_helix_ids if hid in helix_map]
        if not affected:
            continue

        plane_a = op.plane_a_bp
        plane_b = op.plane_b_bp
        n_cells = (plane_b - plane_a) // CELL_BP_DEFAULT
        if n_cells < 1:
            continue

        if op.type == "twist":
            p = op.params
            if p.total_degrees is not None:
                target_deg = p.total_degrees
            elif p.degrees_per_nm is not None:
                length_nm = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
                target_deg = p.degrees_per_nm * length_nm
            else:
                continue
            mods = twist_loop_skips(affected, plane_a, plane_b, target_deg)
        else:  # bend
            p = op.params
            angle_rad = math.radians(p.angle_deg)
            if angle_rad < 1e-9:
                continue
            length_nm = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
            radius_nm = length_nm / angle_rad
            mods = bend_loop_skips(affected, plane_a, plane_b, radius_nm, p.direction_deg)

        for hid, ls_list in mods.items():
            all_mods.setdefault(hid, []).extend(ls_list)

    if not all_mods:
        raise HTTPException(400, detail="Deformation ops produced no loop/skip modifications.")

    design_state.snapshot()
    updated = apply_loop_skips(design, all_mods)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    response = _design_response(updated, report)
    response["loop_skips"] = {hid: len(ls) for hid, ls in all_mods.items()}
    return response


@router.post("/design/prebreak", status_code=200)
def prebreak() -> dict:
    """Nick every staple at every canonical crossover position (diagnostic tool)."""
    from backend.core.lattice import make_prebreak
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    updated = make_prebreak(design)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/auto-break", status_code=200)
def auto_break() -> dict:
    """Nick all non-scaffold strands into 21–60 nt segments, preferring 42 or 49 nt,
    and avoiding the no-sandwich rule.

    Stage 2 of the autostaple pipeline; apply after auto-crossover.
    Pushed onto the undo stack.
    """
    from backend.core.lattice import make_nicks_for_autostaple
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    updated = make_nicks_for_autostaple(design)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/auto-crossover", status_code=200)
def auto_crossover() -> dict:
    """Place all canonical DX crossovers on every adjacent helix pair.

    Rules (per 21-bp period, from ground-truth files):
      VERT  (same col, |row_diff|=1):               {0, 20}
      HORIZ-A (lower-col cell has FORWARD scaffold): {6, 7}
      HORIZ-B (lower-col cell has REVERSE scaffold): {13, 14}

    The design is pushed onto the undo stack so the operation can be undone with Ctrl-Z.
    """
    from backend.core.lattice import make_auto_crossover
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    updated = make_auto_crossover(design)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/crossovers", status_code=201)
def add_crossover(body: CrossoverRequest) -> dict:
    # Validate that the geometric distance is within reach.
    design = design_state.get_or_404()
    strand_a = _find_strand(design, body.strand_a_id)
    strand_b = _find_strand(design, body.strand_b_id)

    if body.domain_a_index >= len(strand_a.domains):
        raise HTTPException(400, detail=f"domain_a_index {body.domain_a_index} out of range.")
    if body.domain_b_index >= len(strand_b.domains):
        raise HTTPException(400, detail=f"domain_b_index {body.domain_b_index} out of range.")

    dom_a = strand_a.domains[body.domain_a_index]
    dom_b = strand_b.domains[body.domain_b_index]

    # Find helices and compute backbone distance at the crossover junction bps.
    helix_a = _find_helix(design, dom_a.helix_id)
    helix_b = _find_helix(design, dom_b.helix_id)

    import numpy as np
    from backend.core.geometry import nucleotide_positions as _npos

    # Use the 3′ bp of domain_a and 5′ bp of domain_b as the junction point.
    # For FORWARD: 3′ end = end_bp. For REVERSE: 3′ end = start_bp.
    bp_a = dom_a.end_bp   if dom_a.direction == Direction.FORWARD else dom_a.start_bp
    bp_b = dom_b.start_bp if dom_b.direction == Direction.FORWARD else dom_b.end_bp

    nucs_a = {(n.bp_index, n.direction): n.position for n in _npos(helix_a)}
    nucs_b = {(n.bp_index, n.direction): n.position for n in _npos(helix_b)}

    pos_a = nucs_a.get((bp_a, dom_a.direction))
    pos_b = nucs_b.get((bp_b, dom_b.direction))

    if pos_a is not None and pos_b is not None:
        dist = float(np.linalg.norm(pos_a - pos_b))
        if dist > MAX_CROSSOVER_REACH_NM:
            raise HTTPException(
                400,
                detail=(
                    f"Crossover distance {dist:.3f} nm exceeds maximum "
                    f"{MAX_CROSSOVER_REACH_NM} nm. Place crossover at a valid position."
                ),
            )

    new_xo = Crossover(
        strand_a_id=body.strand_a_id,
        domain_a_index=body.domain_a_index,
        strand_b_id=body.strand_b_id,
        domain_b_index=body.domain_b_index,
        crossover_type=body.crossover_type,
    )
    design, report = design_state.mutate_and_validate(
        lambda d: d.crossovers.append(new_xo)
    )
    return {
        "crossover": new_xo.model_dump(),
        **_design_response(design, report),
    }


@router.delete("/design/crossovers/{crossover_id}")
def delete_crossover(crossover_id: str) -> dict:
    design = design_state.get_or_404()
    if not any(xo.id == crossover_id for xo in design.crossovers):
        raise HTTPException(404, detail=f"Crossover {crossover_id!r} not found.")

    design, report = design_state.mutate_and_validate(
        lambda d: setattr(d, "crossovers", [x for x in d.crossovers if x.id != crossover_id])
    )
    return _design_response(design, report)


# ── oxDNA export / run ────────────────────────────────────────────────────────


@router.post("/design/oxdna/export")
def export_oxdna() -> Response:
    """
    Export the active design as a ZIP archive containing oxDNA files:
      - topology.top
      - conf.dat
      - input.txt  (ready-to-run MC input; requires oxDNA binary)
      - README.txt (installation + run instructions)

    Returns the ZIP as a binary download.
    """
    import io
    import zipfile

    from backend.physics.oxdna_interface import (
        write_configuration,
        write_topology,
        write_oxdna_input,
    )

    design = design_state.get_or_404()
    geometry = _geometry_for_design(design)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # topology.top
        top_buf = io.StringIO()
        import tempfile, pathlib
        with tempfile.TemporaryDirectory() as tmpdir:
            top_path  = pathlib.Path(tmpdir) / "topology.top"
            conf_path = pathlib.Path(tmpdir) / "conf.dat"
            inp_path  = pathlib.Path(tmpdir) / "input.txt"

            write_topology(design, top_path)
            write_configuration(design, geometry, conf_path)
            write_oxdna_input(top_path, conf_path, inp_path, steps=10_000, relaxation_steps=1_000)

            zf.write(top_path,  "topology.top")
            zf.write(conf_path, "conf.dat")
            zf.write(inp_path,  "input.txt")

        readme = (
            "# NADOC oxDNA Export\n\n"
            "## Install oxDNA\n\n"
            "```bash\n"
            "# Option A — conda (recommended)\n"
            "conda install -c bioconda oxdna\n\n"
            "# Option B — build from source\n"
            "git clone https://github.com/lorenzo-rovigatti/oxDNA\n"
            "cd oxDNA && mkdir build && cd build\n"
            "cmake .. -DCUDA=OFF && make -j4\n"
            "```\n\n"
            "## Run simulation\n\n"
            "```bash\n"
            "oxDNA input.txt\n"
            "```\n\n"
            "Output: `last_conf.dat` — final relaxed configuration.\n\n"
            "## Re-import (future feature)\n\n"
            "Once oxDNA runs, the relaxed positions in `last_conf.dat` can be\n"
            "read back with `backend.physics.oxdna_interface.read_configuration()`.\n"
        )
        zf.writestr("README.txt", readme)

    buf.seek(0)
    name = design.metadata.name or "design"
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}_oxdna.zip"'},
    )


@router.post("/design/oxdna/run")
def run_oxdna_simulation(steps: int = 10_000) -> dict:
    """
    Try to run an oxDNA energy minimisation on the current design.

    Requires the oxDNA binary to be on PATH (or set OXDNA_BIN env var).
    Returns {available: bool, message: str, positions: [...] | null}.

    If oxDNA is not installed, returns available=false with installation info.
    """
    import os
    import tempfile
    import pathlib

    from backend.physics.oxdna_interface import (
        run_oxdna,
        write_configuration,
        write_topology,
        write_oxdna_input,
        read_configuration,
    )

    oxdna_bin = os.environ.get("OXDNA_BIN", "oxDNA")
    design  = design_state.get_or_404()
    geometry = _geometry_for_design(design)

    with tempfile.TemporaryDirectory() as tmpdir:
        p = pathlib.Path(tmpdir)
        write_topology(design,   p / "topology.top")
        write_configuration(design, geometry, p / "conf.dat")
        write_oxdna_input(p / "topology.top", p / "conf.dat",
                          p / "input.txt", steps=steps, relaxation_steps=min(steps // 10, 1000))

        ret = run_oxdna(p / "input.txt", oxdna_bin=oxdna_bin, timeout=120)

        if ret is None:
            return {
                "available": False,
                "message": (
                    f"oxDNA binary not found (tried: {oxdna_bin!r}). "
                    "Install with: conda install -c bioconda oxdna  "
                    "or set OXDNA_BIN env var to the binary path. "
                    "Use 'Export oxDNA' to download files for manual simulation."
                ),
                "positions": None,
            }

        if ret != 0:
            return {
                "available": True,
                "message": f"oxDNA exited with code {ret}. Check topology/configuration.",
                "positions": None,
            }

        # Read back relaxed positions.
        last_conf = p / "last_conf.dat"
        if not last_conf.exists():
            return {
                "available": True,
                "message": "oxDNA finished but no last_conf.dat produced.",
                "positions": None,
            }

        pos_map = read_configuration(last_conf, design)
        positions = [
            {
                "helix_id":          k[0],
                "bp_index":          k[1],
                "direction":         k[2],
                "backbone_position": v.tolist(),
            }
            for k, v in pos_map.items()
        ]
        return {
            "available": True,
            "message":   f"oxDNA relaxation complete ({steps} steps).",
            "positions": positions,
        }
