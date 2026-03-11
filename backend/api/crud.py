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
from pydantic import BaseModel

from backend.api import state as design_state
from backend.core.crossover_positions import (
    MAX_CROSSOVER_REACH_NM,
    valid_crossover_positions,
)
from backend.core.geometry import nucleotide_positions
from backend.core.models import (
    Crossover,
    CrossoverType,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    Vec3,
)
from backend.core.validator import ValidationReport

router = APIRouter()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validation_dict(report: ValidationReport) -> dict:
    return {
        "passed": report.passed,
        "results": [{"ok": r.ok, "message": r.message} for r in report.results],
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
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                key = (domain.helix_id, bp, domain.direction)
                info[key] = {
                    "strand_id":      strand.id,
                    "is_scaffold":    strand.is_scaffold,
                    "is_five_prime":  key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                }
    return info


def _geometry_for_design(design: Design) -> list[dict]:
    nuc_info = _strand_nucleotide_info(design)
    _missing = {"strand_id": None, "is_scaffold": False,
                "is_five_prime": False, "is_three_prime": False}
    result: list[dict] = []
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
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
        "validation": _validation_dict(report),
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


class BundleRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int
    name: str = "Bundle"
    plane: str = "XY"


# ── Design endpoints ──────────────────────────────────────────────────────────


@router.get("/design")
def get_active_design() -> dict:
    """Return the active design and its current validation report."""
    from backend.core.validator import validate_design
    design = design_state.get_or_404()
    report = validate_design(design)
    return _design_response(design, report)


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
def get_geometry() -> list[dict]:
    """Return full geometry (all helices) for the active design."""
    design = design_state.get_or_404()
    return _geometry_for_design(design)


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
            {"bp_a": c.bp_a, "bp_b": c.bp_b, "distance_nm": c.distance_nm}
            for c in candidates
        ],
    }


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
