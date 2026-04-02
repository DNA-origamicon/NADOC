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
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

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
    AnimationKeyframe,
    BendParams,
    CameraPose,
    ClusterOpLogEntry,
    DesignAnimation,
    Crossover,
    CrossoverBases,
    CrossoverType,
    DeformationLogEntry,
    DeformationOp,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandExtension,
    StrandType,
    TwistParams,
    VALID_MODIFICATIONS,
    Vec3,
)
from backend.core.validator import ValidationReport

router = APIRouter()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validation_dict(report: ValidationReport, design: "Design | None" = None) -> dict:
    from backend.core.validator import _is_loop_strand
    loop_ids: list[str] = []
    if design is not None:
        loop_ids = [s.id for s in design.strands if s.strand_type == StrandType.STAPLE and _is_loop_strand(s)]
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
                    "strand_type":    strand.strand_type.value,
                    "is_five_prime":  key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                    "domain_index":   di,
                    "overhang_id":    domain.overhang_id,
                }
    return info


def _geometry_for_design_straight(design: Design) -> list[dict]:
    """Return geometry with no deformations applied (straight bundle positions)."""
    straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
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


def _crossover_bases_geometry(design: Design, nuc_pos_map: dict) -> list[dict]:
    """
    Compute geometry dicts for CrossoverBases entries.

    nuc_pos_map: {(helix_id, bp_index, Direction) -> NucleotidePosition}

    Extra-base nucleotides are placed along a quadratic Bézier arc between the
    two anchor nucleotides on either side of the crossover.  They use a synthetic
    helix_id of the form ``__xb_{cb.id}`` so renderers can identify and handle
    them separately.  The ``domain_index`` is set to ``domain_a_index + 0.5``
    (a float) so JS sorting places them between the two real domains.
    """
    import numpy as np
    from collections import defaultdict
    result = []

    xo_by_id = {xo.id: xo for xo in design.crossovers}
    strand_by_id = {s.id: s for s in design.strands}

    # Build helix-pair → list of (departure_bp, xo_id) for companion-based z_sign.
    # departure_bp = dom_a.end_bp (3′ end of domain_a = the crossover junction bp).
    helix_pair_bps: dict = defaultdict(list)
    for other_xo in design.crossovers:
        _os = strand_by_id.get(other_xo.strand_a_id)
        if _os is None or other_xo.domain_a_index >= len(_os.domains):
            continue
        _oda = _os.domains[other_xo.domain_a_index]
        _osb = strand_by_id.get(other_xo.strand_b_id)
        if _osb is None or other_xo.domain_b_index >= len(_osb.domains):
            continue
        _odb = _osb.domains[other_xo.domain_b_index]
        _hp = frozenset({_oda.helix_id, _odb.helix_id})
        helix_pair_bps[_hp].append((_oda.end_bp, other_xo.id))

    for cb in design.crossover_bases:
        xo = xo_by_id.get(cb.crossover_id)
        if xo is None:
            continue
        strand = strand_by_id.get(cb.strand_id)
        if strand is None:
            continue
        if xo.domain_a_index >= len(strand.domains) or xo.domain_b_index >= len(strand.domains):
            continue

        dom_a = strand.domains[xo.domain_a_index]
        dom_b = strand.domains[xo.domain_b_index]

        # Anchor bps: 3′ end of domain_a, 5′ end of domain_b.
        # end_bp is always the 3′ end and start_bp is always the 5′ end,
        # regardless of direction — no direction check needed.
        bp_a = dom_a.end_bp
        bp_b = dom_b.start_bp

        nuc_a = nuc_pos_map.get((dom_a.helix_id, bp_a, dom_a.direction))
        nuc_b = nuc_pos_map.get((dom_b.helix_id, bp_b, dom_b.direction))

        if nuc_a is None or nuc_b is None:
            continue

        p0 = nuc_a.position
        p2 = nuc_b.position
        mid = (p0 + p2) * 0.5
        dist = float(np.linalg.norm(p2 - p0))

        # Bézier control point: bow perpendicular to the chord
        if dist > 1e-6:
            chord_hat = (p2 - p0) / dist
            perp = np.cross(chord_hat, np.array([0.0, 0.0, 1.0]))
            if np.linalg.norm(perp) < 1e-6:
                perp = np.cross(chord_hat, np.array([0.0, 1.0, 0.0]))
            perp = perp / np.linalg.norm(perp)
        else:
            perp = np.array([0.0, 1.0, 0.0])
        p1 = mid + perp * dist * 0.15  # quadratic Bézier control point

        n = len(cb.sequence)
        synthetic_helix_id = f"__xb_{cb.id}"

        # Slab base-normal direction: all bases on this crossover share a single ±Z.
        # DX pairs are adjacent bp positions (diff=1 or period-boundary adjacent).
        # Use nearest companion on the same helix pair to determine the pair.
        # Lower bp of the DX pair → -Z, higher bp → +Z.
        # e.g. p210: (6,7) → 6=-Z, 7=+Z
        #      p330: (20,21) boundary → 20=-Z, 21=+Z  [not (0,20) — those are different periods]
        this_bp = dom_a.end_bp
        hp = frozenset({dom_a.helix_id, dom_b.helix_id})
        companions = [(bp, xid) for bp, xid in helix_pair_bps.get(hp, []) if xid != xo.id]
        if companions:
            companion_bp = min(companions, key=lambda e: abs(e[0] - this_bp))[0]
            z_sign = -1.0 if this_bp < companion_bp else 1.0
        else:
            z_sign = -1.0  # fallback: isolated crossover with no companion
        bn = np.array([0.0, 0.0, z_sign])

        for i in range(n):
            t = (i + 1) / (n + 1)
            # Quadratic Bézier: B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2
            pos = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
            # Bézier first derivative — used as axis_tangent (sets the slab's thin axis)
            tangent = 2 * (1 - t) * (p1 - p0) + 2 * t * (p2 - p1)
            tang_len = np.linalg.norm(tangent)
            if tang_len > 1e-6:
                tangent = tangent / tang_len
            else:
                tangent = nuc_a.axis_tangent

            base_pos = pos + 0.3 * bn

            result.append({
                "helix_id":           synthetic_helix_id,
                "bp_index":           i,
                "direction":          dom_a.direction.value,
                "backbone_position":  pos.tolist(),
                "base_position":      base_pos.tolist(),
                "base_normal":        bn.tolist(),
                "axis_tangent":       tangent.tolist(),
                "strand_id":          cb.strand_id,
                "strand_type":        strand.strand_type.value,
                "is_five_prime":      False,
                "is_three_prime":     False,
                "domain_index":       xo.domain_a_index + 0.5,
                "overhang_id":        None,
                "crossover_bases_id": cb.id,
                "crossover_bases_t":  t,
            })

    return result


def _strand_extension_geometry(design: Design, nuc_pos_map: dict) -> list[dict]:
    """
    Compute geometry dicts for StrandExtension entries.

    Extension beads are placed along a quadratic Bézier arc starting at the
    terminal nucleotide and curving radially outward from the helix centre in
    XY, with a +Z bow of 30 % of the total arc length.  Sequence beads come
    first (bp_index 0…n-1), then the fluorophore bead if a modification is
    set (bp_index n, is_modification=True).

    Synthetic helix_id: ``__ext_{extension.id}``
    """
    import numpy as np

    result = []
    strand_by_id = {s.id: s for s in design.strands}

    for ext in design.extensions:
        strand = strand_by_id.get(ext.strand_id)
        if strand is None or not strand.domains:
            continue

        if ext.end == "five_prime":
            dom = strand.domains[0]
            terminal_bp = dom.start_bp
            domain_index = -1.0
        else:
            dom = strand.domains[-1]
            terminal_bp = dom.end_bp
            domain_index = float(len(strand.domains))

        nuc_a = nuc_pos_map.get((dom.helix_id, terminal_bp, dom.direction))
        if nuc_a is None:
            continue

        helix = next((h for h in design.helices if h.id == dom.helix_id), None)
        if helix is None:
            continue

        p0 = nuc_a.position  # terminal nucleotide backbone position (numpy array)

        # Radial outward direction in XY from helix axis centre.
        cx = (helix.axis_start.x + helix.axis_end.x) * 0.5
        cy = (helix.axis_start.y + helix.axis_end.y) * 0.5
        radial = np.array([p0[0] - cx, p0[1] - cy, 0.0])
        radial_len = float(np.linalg.norm(radial))
        if radial_len < 1e-6:
            radial = np.array([1.0, 0.0, 0.0])
        else:
            radial = radial / radial_len

        n_seq = len(ext.sequence) if ext.sequence else 0
        has_mod = ext.modification is not None
        n_total = n_seq + (1 if has_mod else 0)
        if n_total == 0:
            continue

        # Arc endpoint and Bézier control point.
        arc_len = n_total * 0.34           # nm, one bead-spacing per bead
        p2 = p0 + radial * arc_len
        mid = (p0 + p2) * 0.5
        p1 = mid + np.array([0.0, 0.0, arc_len * 0.30])  # +Z bow

        # Base-normal: inward radial (slabs face toward the helix).
        bn = -radial

        synthetic_helix_id = f"__ext_{ext.id}"

        def _bead(i: int, is_mod: bool, mod_name: str | None) -> dict:
            t = (i + 1) / (n_total + 1)
            pos = (1 - t) ** 2 * p0 + 2 * (1 - t) * t * p1 + t ** 2 * p2
            tangent = 2 * (1 - t) * (p1 - p0) + 2 * t * (p2 - p1)
            tlen = float(np.linalg.norm(tangent))
            tangent = tangent / tlen if tlen > 1e-6 else np.array(nuc_a.axis_tangent)
            base_pos = pos + 0.3 * bn
            d = {
                "helix_id":           synthetic_helix_id,
                "bp_index":           i,
                "direction":          dom.direction.value,
                "backbone_position":  pos.tolist(),
                "base_position":      base_pos.tolist(),
                "base_normal":        bn.tolist(),
                "axis_tangent":       tangent.tolist(),
                "strand_id":          ext.strand_id,
                "strand_type":        strand.strand_type.value,
                "is_five_prime":      (not is_mod) and (ext.end == "five_prime") and (i == n_seq - 1),
                "is_three_prime":     False,
                "domain_index":       domain_index,
                "overhang_id":        None,
                "crossover_bases_id": None,
                "crossover_bases_t":  None,
                "extension_id":       ext.id,
                "is_modification":    is_mod,
                "modification":       mod_name,
            }
            return d

        for i in range(n_seq):
            result.append(_bead(i, False, None))

        if has_mod:
            result.append(_bead(n_seq, True, ext.modification))

    return result


def _geometry_for_design(design: Design) -> list[dict]:
    nuc_info = _strand_nucleotide_info(design)
    # Suppress is_five_prime on the real-helix terminal for strands with a 5' extension.
    five_prime_ext_strands = {ext.strand_id for ext in design.extensions if ext.end == "five_prime"}
    for strand in design.strands:
        if strand.id not in five_prime_ext_strands or not strand.domains:
            continue
        first = strand.domains[0]
        key = (first.helix_id, first.start_bp, first.direction)
        entry = nuc_info.get(key)
        if entry and entry.get("is_five_prime"):
            nuc_info[key] = {**entry, "is_five_prime": False}
    _missing = {"strand_id": None, "strand_type": StrandType.STAPLE.value,
                "is_five_prime": False, "is_three_prime": False, "domain_index": 0,
                "overhang_id": None}
    result: list[dict] = []
    nuc_pos_map: dict = {}
    for helix in design.helices:
        for nuc in deformed_nucleotide_positions(helix, design):
            key = (nuc.helix_id, nuc.bp_index, nuc.direction)
            nuc_pos_map[key] = nuc
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
    if design.crossover_bases:
        result.extend(_crossover_bases_geometry(design, nuc_pos_map))
    if design.extensions:
        result.extend(_strand_extension_geometry(design, nuc_pos_map))
    return result


def _ensure_default_cluster(design: Design) -> Design:
    """If the design has helices but no clusters, auto-create a default cluster
    containing all helices and persist it silently (no undo snapshot)."""
    if design.cluster_transforms or not design.helices:
        return design
    from backend.core.models import ClusterRigidTransform
    default_ct = ClusterRigidTransform(
        name="Cluster 1",
        is_default=True,
        helix_ids=[h.id for h in design.helices],
    )
    updated = design.copy_with(cluster_transforms=[default_ct])
    design_state.set_design_silent(updated)
    return updated


def _design_response(design: Design, report: ValidationReport) -> dict:
    design = _ensure_default_cluster(design)
    return {
        "design":     design.to_dict(),
        "validation": _validation_dict(report, design),
    }


def _design_response_with_geometry(design: Design, report: ValidationReport) -> dict:
    """Like _design_response but embeds geometry so the frontend needs only one
    round-trip and can update design + geometry atomically (one scene rebuild)."""
    return {
        **_design_response(design, report),
        "nucleotides": _geometry_for_design(design),
        "helix_axes":  deformed_helix_axes(design),
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
    strand_type: StrandType = StrandType.STAPLE
    sequence: Optional[str] = None


class CrossoverRequest(BaseModel):
    strand_a_id: str
    domain_a_index: int
    strand_b_id: str
    domain_b_index: int
    crossover_type: CrossoverType


class CrossoverBasesRequest(BaseModel):
    crossover_id: str
    strand_id: str
    sequence: str   # ACGTN characters, length >= 1


class CrossoverBasesUpdateRequest(BaseModel):
    sequence: str   # ACGTN characters, length >= 1


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


class StrandBatchDeleteRequest(BaseModel):
    strand_ids: List[str]


class FilePathRequest(BaseModel):
    path: str


class DesignImportRequest(BaseModel):
    content: str


class BundleRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int
    name: str = "Bundle"
    plane: str = "XY"
    strand_filter: str = "both"   # "both" | "scaffold" | "staples"
    lattice_type: LatticeType = LatticeType.HONEYCOMB


class BundleSegmentRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int           # may be negative — extrudes in -axis direction
    plane: str = "XY"
    offset_nm: float = 0.0   # position of axis_start along the plane normal
    strand_filter: str = "both"   # "both" | "scaffold" | "staples"


class BundleContinuationRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...] — may mix continuation and fresh cells
    length_bp: int
    plane: str = "XY"
    offset_nm: float = 0.0
    strand_filter: str = "both"   # "both" | "scaffold" | "staples"
    extend_inplace: bool = True   # True = extend existing helix axis in-place; False = create new helix


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


class NickBatchRequest(BaseModel):
    nicks: list[NickRequest]


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
    return _design_response_with_geometry(design, report)


@router.post("/design/redo")
def redo_design() -> dict:
    """Re-apply the last undone mutation.

    Returns 404 if nothing to redo.
    """
    design, report = design_state.redo()
    return _design_response_with_geometry(design, report)


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
        updated = make_bundle_segment(
            design, cells, body.length_bp, body.plane, body.offset_nm, body.strand_filter,
        )
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
        updated = make_bundle_continuation(
            design, cells, body.length_bp, body.plane, body.offset_nm, body.strand_filter,
            extend_inplace=body.extend_inplace,
        )
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
        new_design = make_bundle_design(cells, body.length_bp, body.name, body.plane, strand_filter=body.strand_filter, lattice_type=body.lattice_type)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.clear_history()
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
    design_state.clear_history()
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


class CadnanoImportRequest(BaseModel):
    content: str   # raw caDNAno v2 JSON string sent by the browser


@router.post("/design/import/cadnano", status_code=200)
def import_cadnano_design(body: CadnanoImportRequest) -> dict:
    """Load a caDNAno v2 .json file sent by the browser as raw JSON text.

    Parses the caDNAno linked-list format, reconstructs helices, strands,
    domains, and crossovers as a NADOC Design, then sets it as the active
    design (clearing undo history).
    """
    from backend.core.cadnano import import_cadnano
    from backend.core.lattice import autodetect_all_overhangs
    from backend.core.validator import validate_design
    import json as _json
    try:
        data = _json.loads(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid JSON: {exc}") from exc
    try:
        design, import_warnings = import_cadnano(data)
    except Exception as exc:
        raise HTTPException(400, detail=f"caDNAno import failed: {exc}") from exc
    design = autodetect_all_overhangs(design)
    design_state.clear_history()
    clear_crossover_cache()
    design_state.set_design(design)
    report = validate_design(design)
    resp = _design_response(design, report)
    if import_warnings:
        resp["import_warnings"] = import_warnings
    return resp


@router.get("/design/export/cadnano")
def export_cadnano_design() -> Response:
    """Export the active design as a caDNAno v2 JSON file download.

    Returns a JSON file with Content-Disposition: attachment so the browser
    triggers a download.  Raises 400 if the design cannot be exported
    (e.g. square-lattice).
    """
    import json as _json
    from backend.core.cadnano import export_cadnano, check_cadnano_compatibility

    design = design_state.get_or_404()
    warnings = check_cadnano_compatibility(design)
    errors = [w for w in warnings if w.startswith("ERROR")]
    if errors:
        raise HTTPException(400, detail="; ".join(errors))
    try:
        data = export_cadnano(design)
    except Exception as exc:
        raise HTTPException(400, detail=f"caDNAno export failed: {exc}") from exc
    json_bytes = _json.dumps(data, separators=(",", ":")).encode("utf-8")
    design_name = design.metadata.name or "design"
    filename = f"{design_name}.json"
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
        strand_type=body.strand_type,
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
        strand_type=body.strand_type,
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


@router.delete("/design/strands/batch", status_code=200)
def delete_strands_batch(body: StrandBatchDeleteRequest) -> dict:
    """Delete multiple strands by ID in one operation."""
    design = design_state.get_or_404()
    id_set = set(body.strand_ids)
    missing = id_set - {s.id for s in design.strands}
    if missing:
        raise HTTPException(404, detail=f"Strand ID(s) not found: {sorted(missing)}")

    xo_ids = [
        xo.id for xo in design.crossovers
        if xo.strand_a_id in id_set or xo.strand_b_id in id_set
    ]
    ovhg_ids_to_remove = {o.id for o in design.overhangs if o.strand_id in id_set}

    def _apply(d: Design) -> None:
        d.strands    = [s for s in d.strands    if s.id not in id_set]
        d.crossovers = [x for x in d.crossovers if x.id not in xo_ids]
        d.overhangs  = [o for o in d.overhangs  if o.id not in ovhg_ids_to_remove]
        cov: dict[str, tuple[int, int]] = {}
        for s in d.strands:
            for dom in s.domains:
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                if dom.helix_id in cov:
                    p_lo, p_hi = cov[dom.helix_id]
                    cov[dom.helix_id] = (min(lo, p_lo), max(hi, p_hi))
                else:
                    cov[dom.helix_id] = (lo, hi)
        new_helices: list[Helix] = []
        for h in d.helices:
            if h.id not in cov:
                continue
            new_lo, new_hi = cov[h.id]
            old_lo = h.bp_start
            old_hi = h.bp_start + h.length_bp - 1
            if new_lo == old_lo and new_hi == old_hi:
                new_helices.append(h)
                continue
            t0 = (new_lo - old_lo) / h.length_bp
            t1 = (new_hi - old_lo + 1) / h.length_bp
            def _lerp(a: float, b: float, t: float) -> float:
                return a + t * (b - a)
            ax_s = Vec3(
                x=_lerp(h.axis_start.x, h.axis_end.x, t0),
                y=_lerp(h.axis_start.y, h.axis_end.y, t0),
                z=_lerp(h.axis_start.z, h.axis_end.z, t0),
            )
            ax_e = Vec3(
                x=_lerp(h.axis_start.x, h.axis_end.x, t1),
                y=_lerp(h.axis_start.y, h.axis_end.y, t1),
                z=_lerp(h.axis_start.z, h.axis_end.z, t1),
            )
            new_helices.append(h.model_copy(update={
                "bp_start":   new_lo,
                "length_bp":  new_hi - new_lo + 1,
                "axis_start": ax_s,
                "axis_end":   ax_e,
            }))
        d.helices = new_helices

    design, report = design_state.mutate_and_validate(_apply)
    return {
        "removed_crossovers": xo_ids,
        **_design_response_with_geometry(design, report),
    }


@router.delete("/design/strands/{strand_id}")
def delete_strand(strand_id: str) -> dict:
    # Collect crossover IDs that reference this strand (cascade delete).
    design = design_state.get_or_404()
    strand_to_del = _find_strand(design, strand_id)  # 404 if not found
    xo_ids = [
        xo.id for xo in design.crossovers
        if xo.strand_a_id == strand_id or xo.strand_b_id == strand_id
    ]
    # Overhang specs that belong to the deleted strand
    ovhg_ids_to_remove = {o.id for o in design.overhangs if o.strand_id == strand_id}

    def _apply(d: Design) -> None:
        d.strands    = [s for s in d.strands    if s.id != strand_id]
        d.crossovers = [x for x in d.crossovers if x.id not in xo_ids]
        d.overhangs  = [o for o in d.overhangs  if o.id not in ovhg_ids_to_remove]
        # Build bp coverage per helix from remaining strands.
        # We use (min_bp, max_bp) so we can trim helices whose strand coverage
        # has shrunk — e.g. when one half of a nicked strand is deleted, the
        # helix should shrink to match the remaining half rather than keeping
        # its original extent (which would show stale blunt-end rings and axis
        # arrows over the now-empty region).
        cov: dict[str, tuple[int, int]] = {}
        for s in d.strands:
            for dom in s.domains:
                lo = min(dom.start_bp, dom.end_bp)
                hi = max(dom.start_bp, dom.end_bp)
                if dom.helix_id in cov:
                    p_lo, p_hi = cov[dom.helix_id]
                    cov[dom.helix_id] = (min(lo, p_lo), max(hi, p_hi))
                else:
                    cov[dom.helix_id] = (lo, hi)
        new_helices: list[Helix] = []
        for h in d.helices:
            if h.id not in cov:
                continue  # empty — drop it
            new_lo, new_hi = cov[h.id]
            old_lo = h.bp_start
            old_hi = h.bp_start + h.length_bp - 1
            if new_lo == old_lo and new_hi == old_hi:
                new_helices.append(h)
                continue
            # Trim helix axis to the actual strand coverage.
            # axis_end corresponds to bp_start + length_bp (one past the last
            # bp), so t_end = (new_hi - old_lo + 1) / length_bp gives exactly
            # the new axis_end for a helix ending at new_hi.
            t0 = (new_lo - old_lo) / h.length_bp
            t1 = (new_hi - old_lo + 1) / h.length_bp
            def _lerp(a: float, b: float, t: float) -> float:
                return a + t * (b - a)
            ax_s = Vec3(
                x=_lerp(h.axis_start.x, h.axis_end.x, t0),
                y=_lerp(h.axis_start.y, h.axis_end.y, t0),
                z=_lerp(h.axis_start.z, h.axis_end.z, t0),
            )
            ax_e = Vec3(
                x=_lerp(h.axis_start.x, h.axis_end.x, t1),
                y=_lerp(h.axis_start.y, h.axis_end.y, t1),
                z=_lerp(h.axis_start.z, h.axis_end.z, t1),
            )
            new_helices.append(h.model_copy(update={
                "bp_start":   new_lo,
                "length_bp":  new_hi - new_lo + 1,
                "axis_start": ax_s,
                "axis_end":   ax_e,
            }))
        d.helices = new_helices

    design, report = design_state.mutate_and_validate(_apply)
    return {
        "removed_crossovers": xo_ids,
        **_design_response_with_geometry(design, report),
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

    Scaffold positions are flagged via ``strand_type_a`` / ``strand_type_b`` so the
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
                    "strand_type_a":  info_a.get("strand_type", StrandType.STAPLE.value),
                    "strand_type_b":  info_b.get("strand_type", StrandType.STAPLE.value),
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
    return _design_response_with_geometry(updated, report)


@router.post("/design/half-crossover", status_code=201)
def add_half_crossover(body: StapleCrossoverRequest) -> dict:
    """Place a single backbone jump (one half of a DX junction).

    Unlike ``/design/staple-crossover`` which atomically places both crossovers
    of a DX motif, this endpoint places only the A→B jump.  The displaced strand
    pieces (B_left and A_right) become independent free strands.

    If the target positions happen to be the 3′ end of strand_b and the 5′ start
    of strand_a respectively, the two pieces are simply concatenated (endpoint-join
    case — no splitting required).

    Raises 400 if the placement would create a circular strand.
    """
    from backend.core.lattice import make_half_crossover, autodetect_overhangs
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

    updated = autodetect_overhangs(updated)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


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

    # Find Crossover objects at this junction so they can be cascade-deleted.
    # A crossover junction is an inter-domain boundary where domain[di].end_bp
    # equals bp_index on the same helix/direction.  The Crossover object has
    # strand_a_id = strand.id and domain_a_index = di.
    xo_ids_to_delete: set[str] = set()
    for strand in design.strands:
        for di, domain in enumerate(strand.domains[:-1]):
            if domain.helix_id != body.helix_id or domain.direction != body.direction:
                continue
            if domain.end_bp == body.bp_index:
                for xo in design.crossovers:
                    if xo.strand_a_id == strand.id and xo.domain_a_index == di:
                        xo_ids_to_delete.add(xo.id)
                break

    try:
        updated = make_nick(design, body.helix_id, body.bp_index, body.direction)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    if xo_ids_to_delete:
        updated = updated.model_copy(update={
            "crossovers":      [xo for xo in updated.crossovers      if xo.id not in xo_ids_to_delete],
            "crossover_bases": [cb for cb in updated.crossover_bases  if cb.crossover_id not in xo_ids_to_delete],
        })

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


@router.post("/design/nick/batch", status_code=201)
def add_nick_batch(body: NickBatchRequest) -> dict:
    """Nick at multiple positions in one operation (unplace N crossovers at once)."""
    from backend.core.lattice import make_nick
    from backend.core.validator import validate_design

    current = design_state.get_or_404()

    for nick in body.nicks:
        xo_ids_to_delete: set[str] = set()
        for strand in current.strands:
            for di, domain in enumerate(strand.domains[:-1]):
                if domain.helix_id != nick.helix_id or domain.direction != nick.direction:
                    continue
                if domain.end_bp == nick.bp_index:
                    for xo in current.crossovers:
                        if xo.strand_a_id == strand.id and xo.domain_a_index == di:
                            xo_ids_to_delete.add(xo.id)
                    break
        try:
            current = make_nick(current, nick.helix_id, nick.bp_index, nick.direction)
        except ValueError:
            continue
        if xo_ids_to_delete:
            current = current.model_copy(update={
                "crossovers":      [xo for xo in current.crossovers      if xo.id not in xo_ids_to_delete],
                "crossover_bases": [cb for cb in current.crossover_bases  if cb.crossover_id not in xo_ids_to_delete],
            })

    design_state.set_design(current)
    report = validate_design(current)
    return _design_response_with_geometry(current, report)


class OverhangExtrudeRequest(BaseModel):
    helix_id:      str
    bp_index:      int
    direction:     Direction
    is_five_prime: bool
    neighbor_row:  int
    neighbor_col:  int
    length_bp:     int


@router.post("/design/overhang/extrude", status_code=200)
def overhang_extrude(body: OverhangExtrudeRequest) -> dict:
    """Extrude a staple-only overhang from a nick into an unoccupied honeycomb neighbour.

    Creates a new helix at (neighbor_row, neighbor_col) and extends the existing
    staple strand at (helix_id, bp_index) with a new domain in that helix.
    """
    from backend.core.lattice import make_overhang_extrude
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        updated = make_overhang_extrude(
            design,
            body.helix_id,
            body.bp_index,
            body.direction,
            body.is_five_prime,
            body.neighbor_row,
            body.neighbor_col,
            body.length_bp,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class OverhangPatchRequest(BaseModel):
    sequence: str | None = None
    label: str | None = None


@router.patch("/design/overhang/{overhang_id}", status_code=200)
def patch_overhang(overhang_id: str, body: OverhangPatchRequest) -> dict:
    """Update sequence and/or label of an existing OverhangSpec.

    When a non-empty sequence is provided the domain bp range is resized to
    match len(sequence) so that the 3D geometry stays consistent.

    For extrude-style overhangs (on their own dedicated helix) the helix
    axis_end and length_bp are also updated.  For inline overhangs
    (``ovhg_inline_*`` IDs, on the parent staple's helix) the helix is never
    touched — only the overhang domain is resized and the main helix is grown
    backward/forward if the new domain extent falls outside its current bounds.

    The parent strand's sequence is cleared because the topology has changed.
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.validator import validate_design
    import math as _math

    design = design_state.get_or_404()
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")

    is_inline = overhang_id.startswith("ovhg_inline_")
    # For inline overhangs the ID encodes the end: ovhg_inline_{strand_id}_{5p|3p}
    inline_end: str | None = overhang_id.rsplit("_", 1)[-1] if is_inline else None  # "5p" or "3p"

    # ── Build updated OverhangSpec ────────────────────────────────────────────
    spec_updates: dict = {}
    if body.sequence is not None:
        spec_updates["sequence"] = body.sequence.upper() if body.sequence else None
    if body.label is not None:
        spec_updates["label"] = body.label

    new_seq: str | None = spec_updates.get("sequence", spec.sequence)
    new_length_bp: int | None = len(new_seq) if new_seq else None

    new_spec = spec.model_copy(update=spec_updates)
    new_overhangs = [new_spec if o.id == overhang_id else o for o in design.overhangs]

    # ── Resize helix + domain when sequence length changes ───────────────────
    new_helices = list(design.helices)
    new_strands = list(design.strands)

    if new_length_bp is not None:

        if not is_inline:
            # ── Extrude-style: resize the dedicated overhang helix ────────────
            for hi, helix in enumerate(new_helices):
                if helix.id != spec.helix_id:
                    continue
                if helix.length_bp == new_length_bp:
                    break
                ax = helix.axis_end.to_array() - helix.axis_start.to_array()
                ax_len = _math.sqrt(ax[0]**2 + ax[1]**2 + ax[2]**2)
                if ax_len < 1e-9:
                    break
                unit = ax / ax_len
                new_len_nm = new_length_bp * BDNA_RISE_PER_BP
                new_end = helix.axis_start.to_array() + unit * new_len_nm
                new_helices[hi] = helix.model_copy(update={
                    "length_bp": new_length_bp,
                    "axis_end":  Vec3(x=float(new_end[0]), y=float(new_end[1]), z=float(new_end[2])),
                })
                break

        # ── Resize the overhang domain ────────────────────────────────────────
        for si, strand in enumerate(new_strands):
            for di, domain in enumerate(strand.domains):
                if domain.overhang_id != overhang_id:
                    continue

                is_fwd = domain.direction == Direction.FORWARD

                if is_inline:
                    # Junction end (adjacent to scaffold) is fixed; free end moves.
                    # inline_end tells us which terminus is the free (dragged) end.
                    if inline_end == "3p":
                        if is_fwd:
                            # 5' junction = start_bp (fixed), 3' free = end_bp
                            new_domain = domain.model_copy(update={"end_bp": domain.start_bp + new_length_bp - 1})
                        else:
                            # 5' junction = start_bp (fixed), 3' free = end_bp (lower)
                            new_domain = domain.model_copy(update={"end_bp": domain.start_bp - (new_length_bp - 1)})
                    else:  # "5p"
                        if is_fwd:
                            # 3' junction = end_bp (fixed), 5' free = start_bp (lower)
                            new_domain = domain.model_copy(update={"start_bp": domain.end_bp - (new_length_bp - 1)})
                        else:
                            # 3' junction = end_bp (fixed), 5' free = start_bp (higher)
                            new_domain = domain.model_copy(update={"start_bp": domain.end_bp + (new_length_bp - 1)})

                    # Grow the main helix if the new domain falls outside its bounds
                    helix_idx = next((hi for hi, h in enumerate(new_helices) if h.id == spec.helix_id), None)
                    if helix_idx is not None:
                        h = new_helices[helix_idx]
                        free_bp = new_domain.end_bp if inline_end == "3p" else new_domain.start_bp
                        helix_end_bp = h.bp_start + h.length_bp - 1
                        ax = h.axis_end.to_array() - h.axis_start.to_array()
                        ax_len = _math.sqrt(ax[0]**2 + ax[1]**2 + ax[2]**2)
                        unit = ax / ax_len if ax_len > 1e-9 else ax
                        if free_bp < h.bp_start:
                            extra = h.bp_start - free_bp
                            new_start = h.axis_start.to_array() - extra * BDNA_RISE_PER_BP * unit
                            new_helices[helix_idx] = h.model_copy(update={
                                "axis_start":    Vec3(x=float(new_start[0]), y=float(new_start[1]), z=float(new_start[2])),
                                "length_bp":     h.length_bp + extra,
                                "bp_start":      free_bp,
                                "phase_offset":  h.phase_offset - extra * h.twist_per_bp_rad,
                            })
                        elif free_bp > helix_end_bp:
                            extra = free_bp - helix_end_bp
                            new_end = h.axis_end.to_array() + extra * BDNA_RISE_PER_BP * unit
                            new_helices[helix_idx] = h.model_copy(update={
                                "axis_end":  Vec3(x=float(new_end[0]), y=float(new_end[1]), z=float(new_end[2])),
                                "length_bp": h.length_bp + extra,
                            })
                else:
                    # Extrude-style: junction is at bp 0 of the dedicated helix.
                    # FORWARD: start_bp=0 is fixed, extend end_bp outward.
                    # REVERSE: end_bp=0 is fixed, extend start_bp outward.
                    if is_fwd:
                        new_domain = domain.model_copy(update={"end_bp": domain.start_bp + new_length_bp - 1})
                    else:
                        new_domain = domain.model_copy(update={"start_bp": domain.end_bp + new_length_bp - 1})

                new_domains = list(strand.domains)
                new_domains[di] = new_domain
                new_strands[si] = strand.model_copy(update={"domains": new_domains, "sequence": None})
                break

    updated = design.model_copy(update={
        "helices":   new_helices,
        "strands":   new_strands,
        "overhangs": new_overhangs,
    })
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class StrandPatchRequest(BaseModel):
    notes: str | None = None
    color: str | None = None   # "#RRGGBB" hex string, or None to reset to palette


@router.patch("/design/strand/{strand_id}", status_code=200)
def patch_strand(strand_id: str, body: StrandPatchRequest) -> dict:
    """Update editable metadata on a strand (notes and/or color).

    Pushes an undo snapshot before modifying so the change can be reverted.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    strand = next((s for s in design.strands if s.id == strand_id), None)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")

    design_state.push_undo(design)

    patch: dict = {}
    if body.notes is not None or "notes" in body.model_fields_set:
        patch["notes"] = body.notes
    if body.color is not None or "color" in body.model_fields_set:
        patch["color"] = body.color

    new_strands = [
        s.model_copy(update=patch) if s.id == strand_id else s
        for s in design.strands
    ]
    updated = design.model_copy(update={"strands": new_strands})
    design_state.set(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class AutoScaffoldRequest(BaseModel):
    mode: str = "seam_line"        # "seam_line" | "end_to_end"
    nick_offset: int = 7           # bp from helix-1 terminal where scaffold 5′ starts (only used when scaffold_loops=False)
    scaffold_loops: bool = True    # extend scaffold to physical termini for ss-DNA end loops
    loop_size: int = 7             # bp offset from far terminus for loop crossovers (even-indexed pairs)


@router.post("/design/auto-scaffold", status_code=200)
def run_auto_scaffold(body: AutoScaffoldRequest = AutoScaffoldRequest()) -> dict:
    """Route the scaffold strand through all helices via a greedy Hamiltonian path.

    Replaces individual per-helix scaffold strands with one continuous scaffold.
    Two modes are supported:
      - ``seam_line``: mid-helix DX crossovers at valid backbone positions (default).
      - ``end_to_end``: full-domain concatenation, no mid-helix crossovers.

    When ``scaffold_loops`` is True (default) the scaffold's 5′ end is placed at
    the physical terminus of helix 1 (bp 0 or N−1), creating a single-stranded
    scaffold loop at the blunt end.  When False, the legacy ``nick_offset`` placement
    is used instead.

    Returns 422 if routing fails (odd helix count or disconnected graph).
    """
    from backend.core.lattice import auto_scaffold
    from backend.core.validator import validate_design
    from fastapi import HTTPException

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = auto_scaffold(
            design,
            mode=body.mode,
            nick_offset=body.nick_offset,
            scaffold_loops=body.scaffold_loops,
            loop_size=body.loop_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Scaffold end-loop endpoints ───────────────────────────────────────────────


class ScaffoldNickRequest(BaseModel):
    nick_offset: int = 7  # bp from near-end terminal where scaffold 5′ starts


class ScaffoldExtrudeRequest(BaseModel):
    length_bp: int = 10   # number of bp to extrude


class ScaffoldEndCrossoversRequest(BaseModel):
    min_end_margin: int = 1  # margin used for path computation only


@router.post("/design/scaffold-nick", status_code=200)
def scaffold_nick_endpoint(body: ScaffoldNickRequest = ScaffoldNickRequest()) -> dict:
    """Nick the scaffold on the first helix (by sorted ID) at *nick_offset* bp from the near end.

    For FORWARD helices: scaffold 5′ is placed at bp *nick_offset*.
    For REVERSE helices: a *nick_offset*-bp single-stranded near loop is left at the blunt end.
    """
    from backend.core.lattice import scaffold_nick
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_nick(design, nick_offset=body.nick_offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/scaffold-extrude-near", status_code=200)
def scaffold_extrude_near_endpoint(body: ScaffoldExtrudeRequest = ScaffoldExtrudeRequest()) -> dict:
    """Extend all near-end helices backward by *length_bp* bp, scaffold strands only.

    Uses in-place backward extension so existing bp indices shift up by *length_bp*.
    Staple strands are not modified.
    """
    from backend.core.lattice import scaffold_extrude_near
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_extrude_near(design, length_bp=body.length_bp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/scaffold-extrude-far", status_code=200)
def scaffold_extrude_far_endpoint(body: ScaffoldExtrudeRequest = ScaffoldExtrudeRequest()) -> dict:
    """Extend all far-end helices forward by *length_bp* bp, scaffold strands only.

    Uses in-place forward extension so existing bp indices are unchanged.
    Staple strands are not modified.
    """
    from backend.core.lattice import scaffold_extrude_far
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_extrude_far(design, length_bp=body.length_bp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class StrandEndResizeEntry(BaseModel):
    strand_id: str
    helix_id:  str
    end:       Literal["5p", "3p"]
    delta_bp:  int

class StrandEndResizeRequest(BaseModel):
    entries: list[StrandEndResizeEntry]

@router.post("/design/strand-end-resize", status_code=200)
def strand_end_resize_endpoint(body: StrandEndResizeRequest) -> dict:
    """Move one or more strand terminal domains by *delta_bp* each.

    delta_bp > 0 moves toward higher global bp (extends forward / shortens 5′
    FORWARD ends); delta_bp < 0 moves toward lower global bp.  The helix axis
    is grown automatically when the new bp lies outside its current bounds.
    """
    from backend.core.lattice import resize_strand_ends
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = resize_strand_ends(design, [e.model_dump() for e in body.entries])
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


@router.post("/design/scaffold-end-crossovers", status_code=200)
def scaffold_end_crossovers_endpoint(
    body: ScaffoldEndCrossoversRequest = ScaffoldEndCrossoversRequest(),
) -> dict:
    """Ligate seam-routed scaffold U-strands into two linear scaffold strands.

    After ``auto_scaffold`` (seam_line mode), each helix pair has a near-U and far-U
    strand.  This endpoint connects them via near-end (bp 0) and far-end (bp L-1)
    ligations, producing:

    - **Near strand**: 5′ at path[0] bp 0, 3′ at path[-1] bp 0
    - **Far strand**: 5′ at path[-1] bp L-1, 3′ at path[0] bp L-1

    Call ``/design/scaffold-nick`` afterwards to set the final 5′/3′ termini.
    """
    from backend.core.lattice import scaffold_add_end_crossovers
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_add_end_crossovers(design, min_end_margin=body.min_end_margin)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Sequence assignment endpoints ─────────────────────────────────────────────


class _ScaffoldSeqBody(BaseModel):
    scaffold_name: str = "M13mp18"


@router.post("/design/assign-scaffold-sequence", status_code=200)
def assign_scaffold_sequence_endpoint(body: _ScaffoldSeqBody = _ScaffoldSeqBody()) -> dict:
    """Assign a scaffold sequence to the scaffold strand.

    Accepts a JSON body ``{"scaffold_name": "M13mp18" | "p7560" | "p8064"}``.
    Defaults to M13mp18 if omitted.

    When the scaffold strand is longer than the chosen sequence, excess positions
    are filled with 'N'.  The response includes ``total_nt``, ``scaffold_len``,
    and ``padded_nt`` so the frontend can surface a warning.
    """
    from backend.core.sequences import assign_scaffold_sequence
    from backend.core.sequences import SCAFFOLD_LIBRARY
    from backend.core.validator import validate_design
    from fastapi import HTTPException

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated, total_nt, padded_nt = assign_scaffold_sequence(design, body.scaffold_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    resp = _design_response(updated, report)
    scaffold_len = next((ln for name, ln, _ in SCAFFOLD_LIBRARY if name == body.scaffold_name), 0)
    resp["total_nt"]    = total_nt
    resp["scaffold_len"] = scaffold_len
    resp["padded_nt"]   = padded_nt
    return resp


@router.post("/design/assign-staple-sequences", status_code=200)
def assign_staple_sequences_endpoint() -> dict:
    """Assign complementary sequences to all staple strands.

    Each staple base is derived as the Watson-Crick complement of the scaffold
    base at the antiparallel position on the same helix.  Unmatched positions
    (no scaffold coverage) receive 'N'.

    Requires the scaffold to have a sequence assigned first
    (via ``POST /design/assign-scaffold-sequence``).

    Returns 422 if no scaffold or scaffold has no sequence.
    """
    from backend.core.sequences import assign_staple_sequences
    from backend.core.validator import validate_design
    from fastapi import HTTPException

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = assign_staple_sequences(design)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── caDNAno sequence export ────────────────────────────────────────────────────


@router.get("/design/export/sequence-csv")
def export_sequence_csv() -> Response:
    """Export strand sequences in caDNAno-compatible CSV format.

    Returns a CSV file (one row per non-scaffold strand) with columns:
      Strand, Sequence, Length, Color, Start Helix, Start Position,
      End Helix, End Position

    Scaffold strand is included as the first row (Strand=0).
    """
    import csv
    import io

    design = design_state.get_or_404()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Strand", "Sequence", "Length", "Color",
        "Start Helix", "Start Position", "End Helix", "End Position",
    ])

    # Helper: get color from store-independent palette index
    _PALETTE = [
        "#FF6B6B", "#FFD93D", "#6BCB77", "#F9844A", "#A29BFE", "#FF9FF3",
        "#00CEC9", "#E17055", "#74B9FF", "#55EFC4", "#FDCB6E", "#D63031",
    ]

    strands_sorted = sorted(design.strands, key=lambda s: (s.strand_type == StrandType.STAPLE, s.id))
    for row_idx, strand in enumerate(strands_sorted):
        if not strand.domains:
            continue
        total_nt = sum(abs(d.end_bp - d.start_bp) + 1 for d in strand.domains)
        seq = strand.sequence or ""
        first_d = strand.domains[0]
        last_d  = strand.domains[-1]
        color = "#29B6F6" if strand.strand_type == StrandType.SCAFFOLD else _PALETTE[row_idx % len(_PALETTE)]
        writer.writerow([
            row_idx,
            seq,
            total_nt,
            color,
            first_d.helix_id,
            first_d.start_bp,
            last_d.helix_id,
            last_d.end_bp,
        ])

    csv_bytes = output.getvalue().encode("utf-8")
    design_name = design.metadata.name or "design"
    filename = f"{design_name}_sequences.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Feature log endpoints ─────────────────────────────────────────────────────


@router.delete("/design/features/last", status_code=200)
def rollback_last_feature() -> dict:
    """Remove the last non-checkpoint feature from the log and undo its effect.

    Pushes the rolled-back state to the undo stack so the rollback itself can
    be undone via Ctrl+Z.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    updated = _rollback_last_feature(design)
    if updated is design:
        raise HTTPException(400, detail="Nothing to roll back.")
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/features/{index}", status_code=200)
def delete_feature(index: int) -> dict:
    """Remove the feature at the given log index (0-based) and reconstruct state.

    The cursor is adjusted so the active window stays consistent:
    - If the cursor was pointing at or past the deleted entry, it shifts left.
    - If the deleted entry was the only active one (cursor == index == 0), the
      cursor resets to -2 (empty state).
    Pushes to the undo stack.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    log = list(design.feature_log)

    if index < 0 or index >= len(log):
        raise HTTPException(400, detail=f"Feature index {index} out of range (log has {len(log)} entries).")

    entry = log[index]
    if entry.feature_type == "checkpoint":
        raise HTTPException(400, detail="Cannot delete checkpoint entries.")

    new_log = [e for e in log if e.id != entry.id]

    # Adjust the cursor so the active window remains consistent after removal.
    cursor = design.feature_log_cursor
    if cursor == -2 or cursor < index:
        new_cursor = cursor                # active window unaffected
    elif cursor == -1:
        new_cursor = -1                    # all remaining entries stay active
    elif cursor == 0:
        new_cursor = -2                    # only active entry was just deleted → empty
    else:
        new_cursor = cursor - 1            # shift left by one

    temp = design.copy_with(feature_log=new_log)
    updated = _seek_feature_log(temp, new_cursor)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


def _seek_feature_log(design: Design, position: int) -> Design:
    """Replay feature_log[0..position] to compute effective deformations + cluster states.

    position = -1 means 'seek to end' (all entries active).
    Deformations are reconstructed from op_snapshot (if present) or by looking up
    deformation_id in design.deformations (backward compat for old log entries).
    Cluster transforms are set to the last cluster_op state in the active window,
    or identity if no op exists for a cluster in the active range.
    """
    log = list(design.feature_log)

    if position == -2:
        # Seeking to empty state — no features active.
        return design.copy_with(deformations=[], feature_log_cursor=-2)

    if not log:
        return design.copy_with(feature_log_cursor=-1)

    if position == -1 or position >= len(log) - 1:
        # Seeking to end — restore all deformations from log and latest cluster states.
        cursor_val = -1
        active = log
    else:
        cursor_val = position
        active = log[:position + 1]

    # Rebuild deformation list from active entries.
    deform_map = {d.id: d for d in design.deformations}
    new_deformations = []
    for entry in active:
        if entry.feature_type == 'deformation':
            op = entry.op_snapshot or deform_map.get(entry.deformation_id)
            if op:
                new_deformations.append(op)

    # Rebuild cluster states: use the last cluster_op per cluster in the active window.
    cluster_last: dict[str, ClusterOpLogEntry] = {}
    for entry in active:
        if entry.feature_type == 'cluster_op':
            cluster_last[entry.cluster_id] = entry

    # Collect cluster IDs that have ANY cluster_op anywhere in the full log.
    clusters_with_ops = {
        e.cluster_id for e in log if e.feature_type == 'cluster_op'
    }

    new_cts = []
    for ct in design.cluster_transforms:
        if ct.id in cluster_last:
            op = cluster_last[ct.id]
            ct = ct.model_copy(update={
                'translation': op.translation,
                'rotation':    op.rotation,
                'pivot':       op.pivot,
            })
        elif ct.id in clusters_with_ops:
            # Cluster has ops in the log but none in the active window → identity.
            ct = ct.model_copy(update={
                'translation': [0.0, 0.0, 0.0],
                'rotation':    [0.0, 0.0, 0.0, 1.0],
            })
        new_cts.append(ct)

    return design.copy_with(
        deformations=new_deformations,
        cluster_transforms=new_cts,
        feature_log_cursor=cursor_val,
    )


class SeekFeaturesBody(BaseModel):
    position: int   # -2 = empty (no features); -1 = end (all active); ≥0 = index of last active entry


@router.post("/design/features/seek", status_code=200)
def seek_features(body: SeekFeaturesBody) -> dict:
    """Replay the feature log up to the given position, updating derived geometry fields.

    Pushes to the undo stack so seek can be undone via Ctrl+Z.
    position = -1 means seek to end (restore all features).
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    updated = _seek_feature_log(design, body.position)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class GeometryBatchBody(BaseModel):
    positions: list[int]   # e.g. [-2, 0, 1, -1]; duplicates ignored


@router.post("/design/features/geometry-batch", status_code=200)
def geometry_batch(body: GeometryBatchBody) -> dict:
    """Return pre-computed geometry for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake keyframe states before playback so that
    all geometry interpolation is client-side and frame-accurate.

    Returns: { "<position>": { nucleotides, helix_axes }, ... }
    """
    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        result[str(position)] = {
            "nucleotides": _geometry_for_design(d),
            "helix_axes":  deformed_helix_axes(d),
        }
    return result


# ── Deformation endpoints ─────────────────────────────────────────────────────


class AddDeformationBody(BaseModel):
    type: str           # 'twist' | 'bend'
    plane_a_bp: int
    plane_b_bp: int
    affected_helix_ids: list[str] = []
    cluster_id: Optional[str] = None  # when set, restrict affected helices to this cluster
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


def _rollback_last_feature(design: Design) -> Design:
    """Remove the last non-checkpoint entry from feature_log and undo its effect.

    Checkpoints are removed only via delete_configuration; this function skips them.
    Returns the original design unchanged if there is nothing to roll back.
    """
    log = list(design.feature_log)
    idx = next(
        (i for i in range(len(log) - 1, -1, -1) if log[i].feature_type != 'checkpoint'),
        None,
    )
    if idx is None:
        return design

    entry = log[idx]
    new_log = [e for e in log if e.id != entry.id]

    if entry.feature_type == 'deformation':
        new_deformations = [d for d in design.deformations if d.id != entry.deformation_id]
        return design.copy_with(deformations=new_deformations, feature_log=new_log)

    if entry.feature_type == 'cluster_op':
        # Restore the previous absolute state of this cluster, or identity if none.
        prev = next(
            (e for e in reversed(log[:idx])
             if e.feature_type == 'cluster_op' and e.cluster_id == entry.cluster_id),
            None,
        )
        new_cts = []
        for ct in design.cluster_transforms:
            if ct.id == entry.cluster_id:
                if prev:
                    ct = ct.model_copy(update={
                        'translation': prev.translation,
                        'rotation':    prev.rotation,
                        'pivot':       prev.pivot,
                    })
                else:
                    ct = ct.model_copy(update={
                        'translation': [0.0, 0.0, 0.0],
                        'rotation':    [0.0, 0.0, 0.0, 1.0],
                        'pivot':       ct.pivot,
                    })
            new_cts.append(ct)
        return design.copy_with(cluster_transforms=new_cts, feature_log=new_log)

    # Unknown type — just remove from log with no other side-effect.
    return design.copy_with(feature_log=new_log)


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

    # If a cluster is active, restrict deformation to only that cluster's helices.
    resolved_cluster_id = body.cluster_id
    if resolved_cluster_id:
        cluster = next((c for c in design.cluster_transforms if c.id == resolved_cluster_id), None)
        if cluster:
            cluster_set = set(cluster.helix_ids)
            helix_ids = [h for h in helix_ids if h in cluster_set]
        else:
            resolved_cluster_id = None  # cluster no longer exists; ignore scoping

    op = DeformationOp(
        type=body.type,
        plane_a_bp=body.plane_a_bp,
        plane_b_bp=body.plane_b_bp,
        affected_helix_ids=helix_ids,
        cluster_id=resolved_cluster_id,
        params=params,
    )
    new_deformations = list(design.deformations) + [op]
    if body.preview:
        updated = design.copy_with(deformations=new_deformations)
        design_state.set_design_silent(updated)
    else:
        # Truncate suppressed future entries if cursor is not at end.
        # cursor=-2 (empty/F0 state) means all entries are suppressed — clear the log.
        log = list(design.feature_log)
        if design.feature_log_cursor == -2:
            log = []
        elif design.feature_log_cursor >= 0:
            log = log[:design.feature_log_cursor + 1]
        log_entry = DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
        updated = design.copy_with(
            deformations=new_deformations,
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )
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


# ── Deformation debug ────────────────────────────────────────────────────────


@router.get("/design/deformation/debug", status_code=200)
def deformation_debug() -> dict:
    """
    Return intermediate deformation-geometry values for every helix.

    Intended for diagnosing bend/twist placement bugs.  Call this BEFORE and
    AFTER applying a deformation to see exactly what centroid, tangent,
    cs_offset, and frame values are used.

    Response shape:
      {
        ops: [ { id, type, plane_a_bp, plane_b_bp, affected_helix_ids, params } ],
        cluster_transforms: [ { id, name, helix_ids, translation, rotation, pivot } ],
        helices: [
          {
            helix_id, bp_start, length_bp,
            axis_start, axis_end,
            arm_helix_ids,          # IDs used after cluster filtering
            centroid_0,             # centroid of arm_helices at bp 0
            tangent_0,              # unit tangent of the arm
            cs_offset,              # radial cross-section offset from centroid
            arm_min_bp_start,
            frames: [               # sampled at key bp values
              { bp_local, bp_global, spine, R_row0, R_row1, R_row2,
                axis_deformed, tangent }
            ]
          }
        ]
      }
    """
    import numpy as np
    from backend.core.deformation import (
        _arm_helices_for, _bundle_centroid_and_tangent,
        _cluster_for_helix, _frame_at_bp,
    )

    design = design_state.get_or_404()

    def _v(arr) -> list[float]:
        return [round(float(x), 6) for x in arr]

    # ── ops summary ──────────────────────────────────────────────────────────
    ops_out = []
    for op in design.deformations:
        ops_out.append({
            "id":                op.id,
            "type":              op.type,
            "plane_a_bp":        op.plane_a_bp,
            "plane_b_bp":        op.plane_b_bp,
            "cluster_id":        op.cluster_id,
            "affected_helix_ids": list(op.affected_helix_ids),
            "params":            op.params.model_dump(),
        })

    # ── cluster_transforms summary ───────────────────────────────────────────
    cts_out = []
    for ct in design.cluster_transforms:
        cts_out.append({
            "id":          ct.id,
            "name":        ct.name,
            "is_default":  ct.is_default,
            "helix_ids":   list(ct.helix_ids),
            "translation": _v(ct.translation),
            "rotation":    _v(ct.rotation),
            "pivot":       _v(ct.pivot),
        })

    # ── per-helix breakdown ──────────────────────────────────────────────────
    helices_out = []
    for h in design.helices:
        cluster = _cluster_for_helix(design, h.id)

        arm_all = _arm_helices_for(design, h.id)
        arm_helices = arm_all
        if cluster:
            cluster_ids = set(cluster.helix_ids)
            filtered = [ah for ah in arm_all if ah.id in cluster_ids]
            if filtered:
                arm_helices = filtered

        centroid_0, tangent_0 = _bundle_centroid_and_tangent(arm_helices)
        h_start   = h.axis_start.to_array()
        cs_raw    = h_start - centroid_0
        cs_offset = cs_raw - float(np.dot(cs_raw, tangent_0)) * tangent_0

        arm_min_bp_start = min((ah.bp_start for ah in arm_helices), default=0)

        # ── sample key bp values ─────────────────────────────────────────────
        sample_local_bps: list[int] = [0]
        for op in design.deformations:
            # Only include ops relevant to this helix
            arm_ids = {ah.id for ah in arm_helices}
            if op.affected_helix_ids and not (arm_ids & set(op.affected_helix_ids)):
                continue
            for bp_global in (op.plane_a_bp, (op.plane_a_bp + op.plane_b_bp) // 2, op.plane_b_bp):
                local = bp_global - arm_min_bp_start
                if 0 <= local < h.length_bp:
                    sample_local_bps.append(local)
            # One step past each plane to see the post-bend tangent
            for bp_global in (op.plane_b_bp + 1, op.plane_b_bp + 5):
                local = bp_global - arm_min_bp_start
                if 0 <= local < h.length_bp:
                    sample_local_bps.append(local)
        sample_local_bps.append(h.length_bp - 1)
        sample_local_bps = sorted(set(sample_local_bps))

        frames_out = []
        for local_bp in sample_local_bps:
            spine_p, R_p, tang = _frame_at_bp(design, local_bp, arm_helices)
            axis_d = spine_p + R_p @ cs_offset
            frames_out.append({
                "bp_local":     local_bp,
                "bp_global":    local_bp + arm_min_bp_start,
                "spine":        _v(spine_p),
                "axis_deformed": _v(axis_d),
                "tangent":      _v(tang),
                "R":            [_v(R_p[0]), _v(R_p[1]), _v(R_p[2])],
            })

        helices_out.append({
            "helix_id":         h.id,
            "bp_start":         h.bp_start,
            "length_bp":        h.length_bp,
            "axis_start":       _v(h.axis_start.to_array()),
            "axis_end":         _v(h.axis_end.to_array()),
            "cluster_id":       cluster.id if cluster else None,
            "arm_helix_ids":    [ah.id for ah in arm_helices],
            "arm_all_ids":      [ah.id for ah in arm_all],
            "centroid_0":       _v(centroid_0),
            "tangent_0":        _v(tangent_0),
            "cs_offset":        _v(cs_offset),
            "arm_min_bp_start": arm_min_bp_start,
            "frames":           frames_out,
        })

    return {
        "ops":               ops_out,
        "cluster_transforms": cts_out,
        "helices":           helices_out,
    }


# ── Camera poses ─────────────────────────────────────────────────────────────


class CreateCameraPoseBody(BaseModel):
    name: str = "Camera Pose"
    position: List[float]   # [x, y, z]
    target: List[float]     # [x, y, z]
    up: List[float]         # [x, y, z]
    fov: float = 55.0
    orbit_mode: str = "trackball"


class PatchCameraPoseBody(BaseModel):
    name: Optional[str] = None
    position: Optional[List[float]] = None
    target: Optional[List[float]] = None
    up: Optional[List[float]] = None
    fov: Optional[float] = None
    orbit_mode: Optional[str] = None


class ReorderCameraPosesBody(BaseModel):
    ordered_ids: List[str]


@router.post("/design/camera-poses", status_code=200)
def create_camera_pose(body: CreateCameraPoseBody) -> dict:
    """Save a new named camera pose. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    pose = CameraPose(
        name=body.name,
        position=body.position,
        target=body.target,
        up=body.up,
        fov=body.fov,
        orbit_mode=body.orbit_mode,
    )
    updated = design.model_copy(
        update={"camera_poses": list(design.camera_poses) + [pose]}, deep=True
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/camera-poses/{pose_id}", status_code=200)
def update_camera_pose(pose_id: str, body: PatchCameraPoseBody) -> dict:
    """Rename or overwrite an existing camera pose (silent — no undo push)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    poses = list(design.camera_poses)
    idx = next((i for i, p in enumerate(poses) if p.id == pose_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")

    patch = body.model_dump(exclude_none=True)
    poses[idx] = poses[idx].model_copy(update=patch)
    updated = design.model_copy(update={"camera_poses": poses}, deep=True)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/camera-poses/{pose_id}", status_code=200)
def delete_camera_pose(pose_id: str) -> dict:
    """Remove a camera pose. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    poses = [p for p in design.camera_poses if p.id != pose_id]
    if len(poses) == len(design.camera_poses):
        raise HTTPException(404, detail=f"Camera pose {pose_id!r} not found.")

    updated = design.model_copy(update={"camera_poses": poses}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.put("/design/camera-poses/reorder", status_code=200)
def reorder_camera_poses(body: ReorderCameraPosesBody) -> dict:
    """Reorder camera poses by providing a full ordered list of IDs. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    pose_map = {p.id: p for p in design.camera_poses}
    missing = [pid for pid in body.ordered_ids if pid not in pose_map]
    if missing:
        raise HTTPException(400, detail=f"Unknown pose IDs: {missing}")

    reordered = [pose_map[pid] for pid in body.ordered_ids]
    # Include any poses not listed in ordered_ids at the end (safety net)
    listed = set(body.ordered_ids)
    reordered += [p for p in design.camera_poses if p.id not in listed]

    updated = design.model_copy(update={"camera_poses": reordered}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Animations ───────────────────────────────────────────────────────────────


class CreateAnimationBody(BaseModel):
    name: str = "Animation"
    fps: int = 30
    loop: bool = False


class PatchAnimationBody(BaseModel):
    name: Optional[str] = None
    fps: Optional[int] = None
    loop: Optional[bool] = None


class CreateKeyframeBody(BaseModel):
    name: str = ""
    camera_pose_id: Optional[str] = None
    feature_log_index: Optional[int] = None
    hold_duration_s: float = 1.0
    transition_duration_s: float = 0.5
    easing: str = "ease-in-out"


class PatchKeyframeBody(BaseModel):
    name: Optional[str] = None
    camera_pose_id: Optional[str] = None
    feature_log_index: Optional[int] = None
    hold_duration_s: Optional[float] = None
    transition_duration_s: Optional[float] = None
    easing: Optional[str] = None


class ReorderKeyframesBody(BaseModel):
    ordered_ids: List[str]


@router.post("/design/animations", status_code=200)
def create_animation(body: CreateAnimationBody) -> dict:
    """Create a new named animation. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anim = DesignAnimation(name=body.name, fps=body.fps, loop=body.loop)
    updated = design.model_copy(
        update={"animations": list(design.animations) + [anim]}, deep=True
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/animations/{anim_id}", status_code=200)
def update_animation(anim_id: str, body: PatchAnimationBody) -> dict:
    """Update animation metadata (name/fps/loop). Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    patch = body.model_dump(exclude_none=True)
    anims[idx] = anims[idx].model_copy(update=patch)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/animations/{anim_id}", status_code=200)
def delete_animation(anim_id: str) -> dict:
    """Remove an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = [a for a in design.animations if a.id != anim_id]
    if len(anims) == len(design.animations):
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/animations/{anim_id}/keyframes", status_code=200)
def create_keyframe(anim_id: str, body: CreateKeyframeBody) -> dict:
    """Append a keyframe to an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kf = AnimationKeyframe(
        name=body.name,
        camera_pose_id=body.camera_pose_id,
        feature_log_index=body.feature_log_index,
        hold_duration_s=body.hold_duration_s,
        transition_duration_s=body.transition_duration_s,
        easing=body.easing,
    )
    updated_anim = anims[idx].model_copy(
        update={"keyframes": list(anims[idx].keyframes) + [kf]}, deep=True
    )
    anims[idx] = updated_anim
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def update_keyframe(anim_id: str, kf_id: str, body: PatchKeyframeBody) -> dict:
    """Update a keyframe's properties (silent — no undo push)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kfs = list(anims[anim_idx].keyframes)
    kf_idx = next((i for i, k in enumerate(kfs) if k.id == kf_id), None)
    if kf_idx is None:
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")

    patch = body.model_dump(exclude_none=True)
    kfs[kf_idx] = kfs[kf_idx].model_copy(update=patch)
    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/animations/{anim_id}/keyframes/{kf_id}", status_code=200)
def delete_keyframe(anim_id: str, kf_id: str) -> dict:
    """Remove a keyframe from an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kfs = [k for k in anims[anim_idx].keyframes if k.id != kf_id]
    if len(kfs) == len(anims[anim_idx].keyframes):
        raise HTTPException(404, detail=f"Keyframe {kf_id!r} not found.")

    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": kfs}, deep=True)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.put("/design/animations/{anim_id}/keyframes/reorder", status_code=200)
def reorder_keyframes(anim_id: str, body: ReorderKeyframesBody) -> dict:
    """Reorder keyframes within an animation. Pushes to undo."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    anims = list(design.animations)
    anim_idx = next((i for i, a in enumerate(anims) if a.id == anim_id), None)
    if anim_idx is None:
        raise HTTPException(404, detail=f"Animation {anim_id!r} not found.")

    kf_map = {k.id: k for k in anims[anim_idx].keyframes}
    missing = [kid for kid in body.ordered_ids if kid not in kf_map]
    if missing:
        raise HTTPException(400, detail=f"Unknown keyframe IDs: {missing}")

    reordered = [kf_map[kid] for kid in body.ordered_ids]
    listed = set(body.ordered_ids)
    reordered += [k for k in anims[anim_idx].keyframes if k.id not in listed]

    anims[anim_idx] = anims[anim_idx].model_copy(update={"keyframes": reordered}, deep=True)
    updated = design.model_copy(update={"animations": anims}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Cluster rigid transforms ──────────────────────────────────────────────────


class AddClusterBody(BaseModel):
    name: str = "Cluster"
    helix_ids: List[str]
    domain_ids: List[dict] = Field(default_factory=list)  # [{strand_id, domain_index}]


class PatchClusterBody(BaseModel):
    name: Optional[str] = None
    helix_ids: Optional[List[str]] = None
    domain_ids: Optional[List[dict]] = None     # [{strand_id, domain_index}]
    translation: Optional[List[float]] = None   # [x, y, z] nm
    rotation: Optional[List[float]] = None      # [x, y, z, w] quaternion
    pivot: Optional[List[float]] = None         # [x, y, z] nm
    commit: bool = False                         # when True: push to undo + append to feature_log


@router.post("/design/cluster", status_code=200)
def add_cluster(body: AddClusterBody) -> dict:
    """Create a named cluster of helices. Pushes to the undo stack.

    Removes the new cluster's helix_ids from all existing clusters so each
    helix belongs to at most one cluster.  Existing clusters that become empty
    are deleted.  If no clusters exist beforehand, auto-creates the default
    cluster first so the remainder always has a home.
    """
    from backend.core.models import ClusterRigidTransform, DomainRef
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    # Ensure a default cluster exists before splitting so the remainder lands somewhere.
    design = _ensure_default_cluster(design)

    new_helix_set = set(body.helix_ids)

    # Remove newly claimed helices from every existing cluster; drop empty ones.
    surviving = []
    for c in design.cluster_transforms:
        remaining = [h for h in c.helix_ids if h not in new_helix_set]
        if remaining:
            surviving.append(c.model_copy(update={"helix_ids": remaining}))
        # Clusters with no remaining helices are silently dropped.

    domain_ids = [DomainRef(**d) for d in (body.domain_ids or [])]
    ct = ClusterRigidTransform(name=body.name, helix_ids=body.helix_ids, domain_ids=domain_ids)
    updated = design.copy_with(cluster_transforms=surviving + [ct])
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/cluster/{cluster_id}", status_code=200)
def update_cluster(cluster_id: str, body: PatchClusterBody) -> dict:
    """Update cluster properties (silent — no undo push, used for live gizmo drag)."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    cts = list(design.cluster_transforms)
    idx = next((i for i, c in enumerate(cts) if c.id == cluster_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    from backend.core.models import DomainRef
    fields: dict = {}
    if body.name        is not None: fields["name"]        = body.name
    if body.helix_ids   is not None: fields["helix_ids"]   = body.helix_ids
    if body.domain_ids  is not None: fields["domain_ids"]  = [DomainRef(**d) for d in body.domain_ids]
    if body.translation is not None: fields["translation"] = body.translation
    if body.rotation    is not None: fields["rotation"]    = body.rotation
    if body.pivot       is not None: fields["pivot"]       = body.pivot

    cts[idx] = cts[idx].model_copy(update=fields)
    updated_ct = cts[idx]

    if body.commit and (body.translation is not None or body.rotation is not None):
        # Final commit of a drag — push to undo stack and record in feature_log.
        # Truncate suppressed future entries if cursor is not at end.
        log = list(design.feature_log)
        if design.feature_log_cursor >= 0:
            log = log[:design.feature_log_cursor + 1]
        log_entry = ClusterOpLogEntry(
            cluster_id=cluster_id,
            translation=list(updated_ct.translation),
            rotation=list(updated_ct.rotation),
            pivot=list(updated_ct.pivot),
        )
        updated = design.copy_with(
            cluster_transforms=cts,
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )
        design_state.set_design(updated)
    else:
        updated = design.copy_with(cluster_transforms=cts)
        design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/cluster/{cluster_id}", status_code=200)
def delete_cluster(cluster_id: str) -> dict:
    """Remove a cluster. Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    cts = [c for c in design.cluster_transforms if c.id != cluster_id]
    if len(cts) == len(design.cluster_transforms):
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    updated = design.model_copy(update={"cluster_transforms": cts}, deep=True)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/cluster/{cluster_id}/begin-drag", status_code=200)
def begin_cluster_drag(cluster_id: str) -> dict:
    """Snapshot undo stack at drag start so the drag can be undone as one step."""
    design = design_state.get_or_404()
    if not any(c.id == cluster_id for c in design.cluster_transforms):
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")
    design_state.snapshot()
    return {}


@router.post("/design/snapshot", status_code=200)
def snapshot_design() -> dict:
    """Push the current design onto the undo stack without changing it.
    Used by the Translate/Rotate tool to create a single undo point for the session."""
    design = design_state.get_or_404()
    design_state.snapshot()
    return {}


class LoopSkipInsertRequest(BaseModel):
    helix_id: str
    bp_index: int
    delta: int   # +1 = loop (insertion), -1 = skip (deletion), 0 = remove existing


@router.post("/design/loop-skip/insert", status_code=200)
def insert_loop_skip(body: LoopSkipInsertRequest) -> dict:
    """Insert or remove a single loop/skip modification at a bp position.

    delta=+1 inserts a loop (extra bp), delta=-1 inserts a skip (deleted bp),
    delta=0 removes any existing modification at that position.
    """
    from backend.core.models import LoopSkip
    from backend.core.loop_skip_calculator import apply_loop_skips
    from backend.core.validator import validate_design

    design = design_state.get_or_404()

    helix = next((h for h in design.helices if h.id == body.helix_id), None)
    if helix is None:
        raise HTTPException(404, detail=f"Helix '{body.helix_id}' not found")
    if body.bp_index < helix.bp_start or body.bp_index >= helix.bp_start + helix.length_bp:
        raise HTTPException(400, detail=f"bp_index {body.bp_index} out of range [{helix.bp_start}, {helix.bp_start + helix.length_bp - 1}]")
    if body.delta not in (-1, 0, 1):
        raise HTTPException(400, detail=f"delta must be -1, 0, or +1, got {body.delta}")

    design_state.snapshot()

    if body.delta == 0:
        # Remove any existing loop/skip at this position
        new_ls = [ls for ls in helix.loop_skips if ls.bp_index != body.bp_index]
        new_helix = helix.model_copy(update={"loop_skips": new_ls})
        new_helices = [new_helix if h.id == body.helix_id else h for h in design.helices]
        from backend.core.models import Design as DesignModel
        updated = DesignModel(
            id=design.id,
            helices=new_helices,
            strands=design.strands,
            crossovers=design.crossovers,
            lattice_type=design.lattice_type,
            metadata=design.metadata,
            deformations=design.deformations,
            cluster_transforms=design.cluster_transforms,
        )
    else:
        updated = apply_loop_skips(design, {body.helix_id: [LoopSkip(bp_index=body.bp_index, delta=body.delta)]})

    design_state.set_design_silent(updated)
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
        sq_lattice_periodic_skips,
        twist_loop_skips,
        CELL_BP_DEFAULT,
    )
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import LatticeType
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
    if not design.deformations and design.lattice_type != LatticeType.SQUARE:
        raise HTTPException(400, detail="No deformation ops on the current design.")

    helix_map = {h.id: h for h in design.helices}

    # Accumulate all per-helix modifications from every DeformationOp.
    # SQ periodic skips go first so deformation mods win at any conflicting position.
    all_mods: dict[str, list] = {}

    if design.lattice_type == LatticeType.SQUARE:
        for hid, ls_list in sq_lattice_periodic_skips(design).items():
            all_mods.setdefault(hid, []).extend(ls_list)

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
            mods = twist_loop_skips(affected, plane_a, plane_b, target_deg, design=design)
        else:  # bend
            p = op.params
            angle_rad = math.radians(p.angle_deg)
            if angle_rad < 1e-9:
                continue
            length_nm = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
            radius_nm = length_nm / angle_rad
            mods = bend_loop_skips(affected, plane_a, plane_b, radius_nm, p.direction_deg, design=design)

        for hid, ls_list in mods.items():
            all_mods.setdefault(hid, []).extend(ls_list)

    if not all_mods:
        raise HTTPException(400, detail="No loop/skip modifications were produced.")

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


@router.post("/design/auto-merge", status_code=200)
def auto_merge() -> dict:
    """Merge adjacent short staple strands when their combined length ≤ 56 nt
    and the result is sandwich-free.

    Stage 3 of the autostaple pipeline; apply after auto-break.
    Repeats until no further merges are possible.
    Pushed onto the undo stack.
    """
    from backend.core.lattice import make_merge_short_staples
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    updated = make_merge_short_staples(design)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/auto-crossover", status_code=200)
def auto_crossover() -> dict:
    """Place all canonical DX crossovers on every adjacent helix pair.

    Rules (per 21-bp period) come from the lookup table in crossover_positions.py.
    See drawings/lattice_ground_truth.png for ground truth:
      p330  (FORWARD→REVERSE angle 330°): {0, 20}
      p90   (FORWARD→REVERSE angle  90°): {13, 14}
      p210  (FORWARD→REVERSE angle 210°): {6, 7}

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

    def _apply(d: Design) -> None:
        d.crossovers = [x for x in d.crossovers if x.id != crossover_id]
        # Cascade: remove any extra bases attached to this crossover
        d.crossover_bases = [cb for cb in d.crossover_bases if cb.crossover_id != crossover_id]

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


# ── Crossover bases (CPD / crosslinking tools) ────────────────────────────────


_XB_VALID_RE = __import__("re").compile(r"^[ACGTNacgtn]+$")


class CrossoverBasesBatchRequest(BaseModel):
    items: List[CrossoverBasesRequest]


@router.post("/design/crossover-bases/batch", status_code=201)
def add_crossover_bases_batch(body: CrossoverBasesBatchRequest) -> dict:
    """Add extra single-stranded bases at multiple crossover junctions in one operation."""
    import re
    design = design_state.get_or_404()

    existing_xo_ids = {cb.crossover_id for cb in design.crossover_bases}
    seen_in_request: set[str] = set()
    new_cbs: list[CrossoverBases] = []

    for item in body.items:
        if not item.sequence:
            raise HTTPException(422, detail="sequence must be at least 1 base.")
        if not re.match(r"^[ACGTNacgtn]+$", item.sequence):
            raise HTTPException(422, detail="sequence must contain only A, C, G, T, N.")

        xo = next((x for x in design.crossovers if x.id == item.crossover_id), None)
        if xo is None:
            raise HTTPException(404, detail=f"Crossover {item.crossover_id!r} not found.")
        if xo.crossover_type == CrossoverType.HALF:
            raise HTTPException(422, detail="Cannot add extra bases to a HALF (nick) crossover.")
        if item.strand_id not in (xo.strand_a_id, xo.strand_b_id):
            raise HTTPException(422, detail=f"Strand {item.strand_id!r} is not part of crossover {item.crossover_id!r}.")
        if item.crossover_id in existing_xo_ids:
            raise HTTPException(409, detail=f"Crossover {item.crossover_id!r} already has extra bases.")
        if item.crossover_id in seen_in_request:
            raise HTTPException(409, detail=f"Crossover {item.crossover_id!r} appears more than once in batch request.")
        seen_in_request.add(item.crossover_id)

        new_cbs.append(CrossoverBases(
            crossover_id=item.crossover_id,
            strand_id=item.strand_id,
            sequence=item.sequence.upper(),
        ))

    design, report = design_state.mutate_and_validate(
        lambda d: d.crossover_bases.extend(new_cbs)
    )
    return _design_response(design, report)


@router.post("/design/crossover-bases", status_code=201)
def add_crossover_bases(body: CrossoverBasesRequest) -> dict:
    """Add extra single-stranded bases at a crossover junction."""
    import re
    design = design_state.get_or_404()

    # Validate sequence
    if not body.sequence:
        raise HTTPException(422, detail="sequence must be at least 1 base.")
    if not re.match(r"^[ACGTNacgtn]+$", body.sequence):
        raise HTTPException(422, detail="sequence must contain only A, C, G, T, N.")

    # Validate crossover exists and is not a HALF type
    xo = next((x for x in design.crossovers if x.id == body.crossover_id), None)
    if xo is None:
        raise HTTPException(404, detail=f"Crossover {body.crossover_id!r} not found.")
    if xo.crossover_type == CrossoverType.HALF:
        raise HTTPException(422, detail="Cannot add extra bases to a HALF (nick) crossover.")

    # Validate strand belongs to this crossover
    if body.strand_id not in (xo.strand_a_id, xo.strand_b_id):
        raise HTTPException(422, detail=f"Strand {body.strand_id!r} is not part of crossover {body.crossover_id!r}.")

    # Only one CrossoverBases per crossover allowed
    if any(cb.crossover_id == body.crossover_id for cb in design.crossover_bases):
        raise HTTPException(409, detail=f"Crossover {body.crossover_id!r} already has extra bases. Use PUT to update.")

    new_cb = CrossoverBases(
        crossover_id=body.crossover_id,
        strand_id=body.strand_id,
        sequence=body.sequence.upper(),
    )
    design, report = design_state.mutate_and_validate(
        lambda d: d.crossover_bases.append(new_cb)
    )
    return {
        "crossover_bases": new_cb.model_dump(),
        **_design_response(design, report),
    }


@router.put("/design/crossover-bases/{cb_id}")
def update_crossover_bases(cb_id: str, body: CrossoverBasesUpdateRequest) -> dict:
    """Update the sequence of existing extra bases at a crossover."""
    import re
    design = design_state.get_or_404()

    if not body.sequence:
        raise HTTPException(422, detail="sequence must be at least 1 base.")
    if not re.match(r"^[ACGTNacgtn]+$", body.sequence):
        raise HTTPException(422, detail="sequence must contain only A, C, G, T, N.")

    cb = next((x for x in design.crossover_bases if x.id == cb_id), None)
    if cb is None:
        raise HTTPException(404, detail=f"CrossoverBases {cb_id!r} not found.")

    new_seq = body.sequence.upper()

    def _apply(d: Design) -> None:
        for x in d.crossover_bases:
            if x.id == cb_id:
                x.sequence = new_seq
                break

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.delete("/design/crossover-bases/{cb_id}")
def delete_crossover_bases(cb_id: str) -> dict:
    """Remove extra bases from a crossover."""
    design = design_state.get_or_404()
    if not any(x.id == cb_id for x in design.crossover_bases):
        raise HTTPException(404, detail=f"CrossoverBases {cb_id!r} not found.")

    design, report = design_state.mutate_and_validate(
        lambda d: setattr(d, "crossover_bases", [x for x in d.crossover_bases if x.id != cb_id])
    )
    return _design_response(design, report)


# ── Strand extensions ─────────────────────────────────────────────────────────
# NOTE: batch endpoints (/design/extensions/batch) MUST be registered before the
# parameterised single-item endpoints (/design/extensions/{ext_id}) so that
# FastAPI/Starlette does not swallow the literal segment "batch" as an ext_id.


_EXT_SEQ_RE = __import__("re").compile(r"^[ACGTNacgtn]+$")


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
        if strand.strand_type != StrandType.STAPLE:
            raise HTTPException(400, detail=f"Strand {item.strand_id!r} is not a staple strand.")
        if item.sequence is None and item.modification is None:
            raise HTTPException(400, detail=f"Strand {item.strand_id!r}: at least one of sequence or modification must be provided.")
        if item.sequence and not _re.match(r"^[ACGTNacgtn]+$", item.sequence):
            raise HTTPException(400, detail=f"Strand {item.strand_id!r}: sequence must contain only ACGTN characters.")
        if item.modification and item.modification not in VALID_MODIFICATIONS:
            raise HTTPException(400, detail=f"Unknown modification {item.modification!r}. Valid: {sorted(VALID_MODIFICATIONS)}")

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
                d.extensions[i] = d.extensions[i].model_copy(update={
                    "sequence":     seq,
                    "modification": item.modification,
                    "label":        item.label,
                })
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

    design, report = design_state.mutate_and_validate(_apply)
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

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


@router.post("/design/extensions", status_code=201)
def add_strand_extension(body: StrandExtensionRequest) -> dict:
    """Add a terminal extension (sequence and/or modification) to a staple strand's 5′ or 3′ end."""
    import re

    design = design_state.get_or_404()

    strand = next((s for s in design.strands if s.id == body.strand_id), None)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {body.strand_id!r} not found.")
    if strand.strand_type != StrandType.STAPLE:
        raise HTTPException(400, detail="Extensions can only be added to staple strands.")

    if body.sequence is None and body.modification is None:
        raise HTTPException(400, detail="At least one of sequence or modification must be provided.")

    if body.sequence is not None:
        if not body.sequence or not re.match(r"^[ACGTNacgtn]+$", body.sequence):
            raise HTTPException(400, detail="sequence must contain only ACGTN characters.")

    if body.modification is not None:
        if body.modification not in VALID_MODIFICATIONS:
            raise HTTPException(
                400,
                detail=f"Unknown modification {body.modification!r}. "
                       f"Valid values: {sorted(VALID_MODIFICATIONS)}",
            )

    if any(x.strand_id == body.strand_id and x.end == body.end for x in design.extensions):
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

    design, report = design_state.mutate_and_validate(
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
        raise HTTPException(400, detail="At least one of sequence or modification must be set.")

    if new_seq is not None:
        if not re.match(r"^[ACGTNacgtn]+$", new_seq):
            raise HTTPException(400, detail="sequence must contain only ACGTN characters.")
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

    design, report = design_state.mutate_and_validate(_apply)
    updated = next(x for x in design.extensions if x.id == ext_id)
    return {"extension": updated.model_dump(), **_design_response(design, report)}


@router.delete("/design/extensions/{ext_id}")
def delete_strand_extension(ext_id: str) -> dict:
    """Remove a strand extension."""
    design = design_state.get_or_404()
    if not any(x.id == ext_id for x in design.extensions):
        raise HTTPException(404, detail=f"StrandExtension {ext_id!r} not found.")

    design, report = design_state.mutate_and_validate(
        lambda d: setattr(d, "extensions", [x for x in d.extensions if x.id != ext_id])
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


# ── Atomistic model + PDB/PSF export (Phase AA) ───────────────────────────────


@router.get("/design/atomistic")
def get_atomistic(
    delta_deg:      float = 0.0,
    gamma_deg:      float = 0.0,
    beta_deg:       float = 0.0,
    frame_rot_deg:  float = 39.0,
    frame_shift_n:  float = -0.07,
    frame_shift_y:  float = -0.59,
    frame_shift_z:  float =  0.00,
    crossover_mode: str   = 'none',
) -> dict:
    """
    Return the heavy-atom all-atom model for the atomistic Three.js renderer.

    Query params:
      delta_deg     — extra rotation around C3′–C4′ bond (adjusts δ; moves C5′/O5′/P/OP1/OP2).
      gamma_deg     — extra rotation around C4′–C5′ bond (adjusts γ; moves O5′/P/OP1/OP2).
      beta_deg      — extra rotation around C5′–O5′ bond (adjusts β; moves P/OP1/OP2).
      frame_rot_deg — in-plane rotation of each residue (moves all atoms; default 26°).
      frame_shift_n — shift along e_n toward partner strand in nm (default 0.06).
      frame_shift_y — shift along e_y tangential in nm (default −0.27).
      frame_shift_z — shift along e_z axial in nm (default 0.00).

    Response: { atoms: [...], bonds: [[i,j], ...], element_meta: {...} }
    Each atom dict contains: serial, name, element, residue, chain_id,
    seq_num, x, y, z (nm), strand_id, helix_id, bp_index, direction,
    is_modified.
    """
    import math
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json

    design = design_state.get_or_404()
    model  = build_atomistic_model(
        design,
        delta_rad=math.radians(delta_deg),
        gamma_rad=math.radians(gamma_deg),
        beta_rad=math.radians(beta_deg),
        frame_rot_rad=math.radians(frame_rot_deg),
        frame_shift_n=frame_shift_n,
        frame_shift_y=frame_shift_y,
        frame_shift_z=frame_shift_z,
        crossover_mode=crossover_mode,
    )
    return atomistic_to_json(model)


@router.get("/design/surface")
def get_surface(
    color_mode:     str   = "strand",
    grid_spacing:   float = 0.20,
    probe_radius:   float = 0.28,
    delta_deg:      float = 0.0,
    gamma_deg:      float = 0.0,
    beta_deg:       float = 0.0,
    frame_rot_deg:  float = 39.0,
    frame_shift_n:  float = -0.07,
    frame_shift_y:  float = -0.59,
    frame_shift_z:  float =  0.00,
    crossover_mode: str   = "none",
) -> dict:
    """
    Compute and return a triangulated molecular surface mesh.

    The surface is computed from the all-atom model with atom radii scaled ×1.2,
    followed by a morphological closing of radius probe_radius.  probe_radius=0
    gives a tight surface; larger values produce a smoother envelope with small
    grooves filled in.

    Query params:
      color_mode    — "strand" (per-vertex strand colours) or "uniform" (no colours).
      grid_spacing  — voxel size in nm (default 0.20).
      probe_radius  — controls smoothness; 0 = tight, 0.28 = smooth (default).
      delta/gamma/beta/frame_rot/frame_shift/crossover_mode — forwarded to the
                      atomistic pipeline (same semantics as /design/atomistic).

    Response: {
      vertices: [x,y,z, ...],      flat float array, nm coords
      faces:    [i,j,k, ...],      flat int array
      vertex_colors: [r,g,b, ...], flat float 0-1, or null for uniform mode
      stats: { n_verts, n_faces, compute_ms }
    }
    """
    import math
    import time
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, surface_to_json

    design = design_state.get_or_404()
    model = build_atomistic_model(
        design,
        delta_rad=math.radians(delta_deg),
        gamma_rad=math.radians(gamma_deg),
        beta_rad=math.radians(beta_deg),
        frame_rot_rad=math.radians(frame_rot_deg),
        frame_shift_n=frame_shift_n,
        frame_shift_y=frame_shift_y,
        frame_shift_z=frame_shift_z,
        crossover_mode=crossover_mode,
    )

    t0 = time.perf_counter()
    mesh = compute_surface(model.atoms, grid_spacing=grid_spacing, probe_radius=probe_radius)
    t_ms = (time.perf_counter() - t0) * 1000.0

    return surface_to_json(mesh, design, color_mode=color_mode, t_ms=t_ms)


@router.get("/design/export/pdb")
def export_pdb_file() -> Response:
    """Export the active design as an all-atom PDB file (heavy atoms, CHARMM36 names)."""
    from backend.core.pdb_export import export_pdb

    design   = design_state.get_or_404()
    pdb_text = export_pdb(design)
    name     = (design.metadata.name or "design").replace(" ", "_")
    return Response(
        content     = pdb_text.encode("utf-8"),
        media_type  = "chemical/x-pdb",
        headers     = {"Content-Disposition": f'attachment; filename="{name}.pdb"'},
    )


@router.get("/design/debug/strand-stats")
def debug_strand_stats() -> dict:
    """Return strand terminus statistics to diagnose crossover placement issues.

    Returns total staple count, min/max terminus bp, and a bucketed histogram
    of terminus positions (20 equal buckets across the helix range).
    """
    design = design_state.get_or_404()

    staples = [s for s in design.strands if s.strand_type != "scaffold"]

    termini_bps: list[int] = []
    for s in staples:
        termini_bps.append(s.domains[0].start_bp)
        termini_bps.append(s.domains[-1].end_bp)

    helix_bp_starts = [h.bp_start for h in design.helices]
    helix_lengths   = [h.length_bp for h in design.helices]
    all_lo = min(helix_bp_starts) if helix_bp_starts else 0
    all_hi = max(b + l - 1 for b, l in zip(helix_bp_starts, helix_lengths)) if helix_bp_starts else 0

    # Build 20-bucket histogram
    span = all_hi - all_lo + 1
    n_buckets = 20
    bucket_size = max(1, span // n_buckets)
    buckets: dict[str, int] = {}
    for bp in termini_bps:
        idx = min((bp - all_lo) // bucket_size, n_buckets - 1)
        lo_b = all_lo + idx * bucket_size
        hi_b = lo_b + bucket_size - 1
        key = f"{lo_b}-{hi_b}"
        buckets[key] = buckets.get(key, 0) + 1

    # Per-helix cross-helix domain count (measures how many crossovers each helix has)
    xover_counts: dict[str, int] = {}
    for s in staples:
        for i in range(len(s.domains) - 1):
            da, db = s.domains[i], s.domains[i + 1]
            if da.helix_id != db.helix_id:
                xover_counts[da.helix_id] = xover_counts.get(da.helix_id, 0) + 1
                xover_counts[db.helix_id] = xover_counts.get(db.helix_id, 0) + 1

    # Max/min crossover bp
    xover_bps: list[int] = []
    for s in staples:
        for i in range(len(s.domains) - 1):
            da, db = s.domains[i], s.domains[i + 1]
            if da.helix_id != db.helix_id:
                xover_bps.append(da.end_bp)

    return {
        "staple_count": len(staples),
        "terminus_count": len(termini_bps),
        "terminus_min_bp": min(termini_bps) if termini_bps else None,
        "terminus_max_bp": max(termini_bps) if termini_bps else None,
        "helix_range": {"lo": all_lo, "hi": all_hi},
        "terminus_histogram": buckets,
        "crossover_count": len(xover_bps),
        "crossover_min_bp": min(xover_bps) if xover_bps else None,
        "crossover_max_bp": max(xover_bps) if xover_bps else None,
        "per_helix_crossover_counts": xover_counts,
        "helix_info": [
            {"id": h.id, "bp_start": h.bp_start, "length_bp": h.length_bp,
             "axis_start_z": round(h.axis_start.z, 4), "axis_end_z": round(h.axis_end.z, 4)}
            for h in design.helices
        ],
    }


@router.get("/design/debug/crossovers")
def debug_crossovers() -> dict:
    """Return all Crossover model objects and any domain-junction mismatches.

    For each Crossover, also reports whether the stored (strand_a_id,
    domain_a_index) and (strand_b_id, domain_b_index) actually correspond to a
    cross-helix domain transition in the current strand layout.  Mismatches
    indicate stale Crossover objects that will cause the frontend context-menu
    lookup to return null.
    """
    design = design_state.get_or_404()
    strand_map = {s.id: s for s in design.strands}

    # Build the set of actual cross-helix junctions: (strand_id, di) → (from_helix, to_helix, from_bp, to_bp)
    junctions: dict[tuple[str, int], dict] = {}
    for s in design.strands:
        for di in range(len(s.domains) - 1):
            da = s.domains[di]
            db = s.domains[di + 1]
            if da.helix_id != db.helix_id:
                junctions[(s.id, di)] = {
                    "from_helix": da.helix_id, "from_bp": da.end_bp,
                    "to_helix":   db.helix_id, "to_bp":   db.start_bp,
                }

    results = []
    for xo in design.crossovers:
        a_key = (xo.strand_a_id, xo.domain_a_index)
        a_junc = junctions.get(a_key)
        strand_a = strand_map.get(xo.strand_a_id)
        strand_b = strand_map.get(xo.strand_b_id)
        # b_domain_exists: domain_b_index is a valid index in strand_b (not necessarily a crossover source)
        b_domain_exists = strand_b is not None and xo.domain_b_index < len(strand_b.domains)
        results.append({
            "id":             xo.id,
            "type":           xo.crossover_type,
            "strand_a_id":    xo.strand_a_id,
            "domain_a_index": xo.domain_a_index,
            "strand_b_id":    xo.strand_b_id,
            "domain_b_index": xo.domain_b_index,
            "strand_a_exists": strand_a is not None,
            "strand_b_exists": strand_b is not None,
            "a_junction":     a_junc,   # null if no cross-helix junction at (strand_a, domain_a)
            "a_ok":           a_junc is not None,
            "b_domain_exists": b_domain_exists,
        })

    broken = [r for r in results if not r["a_ok"] or not r["b_domain_exists"] or not r["strand_a_exists"]]

    # Also find cross-helix junctions that have NO matching Crossover object
    covered_a = {(xo.strand_a_id, xo.domain_a_index) for xo in design.crossovers}
    covered_b = {(xo.strand_b_id, xo.domain_b_index) for xo in design.crossovers}
    uncovered = [
        {"strand_id": sid, "domain_index": di, **junc}
        for (sid, di), junc in junctions.items()
        if (sid, di) not in covered_a and (sid, di) not in covered_b
    ]

    return {
        "crossover_count": len(design.crossovers),
        "junction_count":  len(junctions),
        "broken_count":    len(broken),
        "uncovered_junctions_count": len(uncovered),
        "crossovers": results,
        "broken": broken,
        "uncovered_junctions": uncovered,
    }


@router.get("/design/export/psf")
def export_psf_file() -> Response:
    """Export the active design as a NAMD-compatible PSF topology file."""
    from backend.core.pdb_export import export_psf

    design   = design_state.get_or_404()
    psf_text = export_psf(design)
    name     = (design.metadata.name or "design").replace(" ", "_")
    return Response(
        content     = psf_text.encode("utf-8"),
        media_type  = "text/plain",
        headers     = {"Content-Disposition": f'attachment; filename="{name}.psf"'},
    )


# ── NAMD bundle templates ──────────────────────────────────────────────────────

_NAMD_CONF_TEMPLATE = """\
# NAMD configuration generated by NADOC
# ─────────────────────────────────────────────────────────────────────────────
# IMPORTANT: This PSF has no angles/dihedrals.  Complete it first (see README).
# ─────────────────────────────────────────────────────────────────────────────

structure          complete.psf
coordinates        {name}.pdb
outputName         output

# CHARMM36 nucleic acid force field
# Download: http://mackerell.umaryland.edu/charmm_ff.shtml
paraTypeCharmm     on
parameters         par_all36_na.prm

# Thermostat (310 K = body temperature)
temperature        310
langevin           on
langevinDamping    5
langevinTemp       310

# Periodic boundary conditions (cell from NADOC bounding box + 5 nm margin)
PME                yes
PMEGridSpacing     1.0
cellBasisVector1   {ax:.3f}  0.000  0.000
cellBasisVector2   0.000  {ay:.3f}  0.000
cellBasisVector3   0.000  0.000  {az:.3f}
cellOrigin         {ox:.3f}  {oy:.3f}  {oz:.3f}

# Integration
timestep           2.0
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      10

# Energy minimization then short MD run
minimize           1000
reinitvels         310
run                50000
"""

_NAMD_README_TEMPLATE = """\
NADOC NAMD Export
=================

Files in this archive
---------------------
  {name}.pdb   All-atom model, heavy atoms only (CHARMM36 naming, Angstroms)
  {name}.psf   Topology: atoms + bonds.  INCOMPLETE — angles/dihedrals are stubs.
  namd.conf    NAMD configuration template
  README.txt   This file

Prerequisites
-------------
  - CHARMM36 NA force field files:
      top_all36_na.rtf
      par_all36_na.prm
    Download from: http://mackerell.umaryland.edu/charmm_ff.shtml
  - psfgen (bundled with VMD or NAMD distributions)
  - NAMD2 or NAMD3

Step 1 — Complete the PSF (add angles, dihedrals, impropers)
------------------------------------------------------------
The PSF exported by NADOC contains atoms and bonds only.  Use psfgen to
generate the full CHARMM topology before running NAMD.

Create a file complete_psf.tcl with the following content:

    package require psfgen
    topology top_all36_na.rtf
    readpsf {name}.psf
    guesscoord
    writepsf complete.psf
    writepdb {name}_complete.pdb

Then run it through VMD:

    vmd -dispdev none -e complete_psf.tcl

Step 2 — Edit namd.conf
------------------------
Open namd.conf and update the path to par_all36_na.prm:

    parameters  /path/to/par_all36_na.prm

Step 3 — Run NAMD
------------------
    namd2 +p4 namd.conf > namd.log

For NAMD3 with GPU acceleration:

    namd3 +p4 +devices 0 namd.conf > namd.log

Notes
-----
  - Coordinates reflect the idealised B-form geometry from NADOC.  The
    included namd.conf runs 1000 steps of energy minimisation before
    dynamics — always minimise before production runs.
  - The model contains heavy atoms only (no hydrogens).  psfgen's
    guesscoord will place hydrogens from the RTF topology.
  - No solvent or counter-ions are included.  Add them using VMD's
    Solvation and Autoionize plugins before production MD.
  - Crossover O3\\'→P bonds are present in both PSF !NBOND and PDB LINK
    records.
"""


@router.get("/design/export/namd-complete")
def export_namd_complete() -> Response:
    """Complete NAMD simulation package — ready to run on a fresh Ubuntu machine."""
    from backend.core.namd_package import build_namd_package

    design    = design_state.get_or_404()
    name      = (design.metadata.name or "design").replace(" ", "_")
    zip_bytes = build_namd_package(design)
    return Response(
        content    = zip_bytes,
        media_type = "application/zip",
        headers    = {"Content-Disposition": f'attachment; filename="{name}_namd_complete.zip"'},
    )


@router.get("/design/export/namd-prompt")
def export_namd_prompt() -> Response:
    """Return the AI assistant prompt text for the current design (plain text)."""
    from backend.core.namd_package import get_ai_prompt

    design = design_state.get_or_404()
    return Response(
        content    = get_ai_prompt(design),
        media_type = "text/plain; charset=utf-8",
    )


@router.get("/design/export/namd-bundle")
def export_namd_bundle_file() -> Response:
    """ZIP archive: {name}.pdb, {name}.psf, namd.conf, README.txt"""
    import io
    import zipfile
    from backend.core.atomistic import build_atomistic_model
    from backend.core.pdb_export import _box_dimensions, export_pdb, export_psf

    design = design_state.get_or_404()
    name   = (design.metadata.name or "design").replace(" ", "_")

    model              = build_atomistic_model(design, crossover_mode='lerp')
    ax, ay, az, ox, oy, oz = _box_dimensions(model.atoms, margin_nm=5.0)

    pdb_text    = export_pdb(design)
    psf_text    = export_psf(design)
    conf_text   = _NAMD_CONF_TEMPLATE.format(
        name=name, ax=ax, ay=ay, az=az, ox=ox, oy=oy, oz=oz,
    )
    readme_text = _NAMD_README_TEMPLATE.format(name=name)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}.pdb",  pdb_text)
        zf.writestr(f"{name}.psf",  psf_text)
        zf.writestr("namd.conf",    conf_text)
        zf.writestr("README.txt",   readme_text)
    buf.seek(0)

    return Response(
        content    = buf.getvalue(),
        media_type = "application/zip",
        headers    = {"Content-Disposition": f'attachment; filename="{name}_namd.zip"'},
    )
