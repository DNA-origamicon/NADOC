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
  PATCH  /design/crossovers/extra-bases/batch   — set extra bases on multiple crossovers (batch)
  PATCH  /design/crossovers/{id}/extra-bases    — set (or clear) extra bases on a crossover

  POST   /design/load                           — load .nadoc file from server-side path
  POST   /design/save                           — save active design to server-side path
"""

from __future__ import annotations

import json
import math
import os
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import Response
from pydantic import BaseModel, Field

from backend.api import state as design_state
from backend.core.geometry import (
    nucleotide_positions,
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
from backend.core.deformation import (
    _rot_from_quaternion,
    deformed_frame_at_bp,
    deformed_helix_axes,
    deformed_nucleotide_arrays,
    deformed_nucleotide_positions,
    helices_crossing_planes,
)
from backend.core.models import (
    AnimationKeyframe,
    BendParams,
    CameraPose,
    ClusterJoint,
    ClusterOpLogEntry,
    Crossover,
    DesignAnimation,
    DeformationLogEntry,
    DeformationOp,
    Design,
    DesignMetadata,
    Direction,
    Domain,
    HalfCrossover,
    Helix,
    LatticeType,
    Strand,
    StrandExtension,
    StrandType,
    TwistParams,
    VALID_MODIFICATIONS,
    Vec3,
)
from backend.core.constants import STAPLE_PALETTE
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


def _strand_nucleotide_info(design: Design, helix_ids: frozenset[str] | None = None) -> dict:
    """(helix_id, bp_index, Direction) → strand metadata dict.

    If *helix_ids* is given, only nucleotides whose domain is on one of those
    helices are included.  Used by partial geometry to avoid iterating all strands.
    """
    info: dict = {}
    for strand in design.strands:
        if not strand.domains:
            continue
        first = strand.domains[0]
        last  = strand.domains[-1]
        five_prime_key  = (first.helix_id, first.start_bp, first.direction)
        three_prime_key = (last.helix_id,  last.end_bp,   last.direction)
        for di, domain in enumerate(strand.domains):
            if helix_ids is not None and domain.helix_id not in helix_ids:
                continue
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
    """Return geometry with both deformations and cluster transforms removed.

    This is the t=0 base for the deform lerp: the original unmodified bundle positions
    before any deformation ops or cluster rotations.  Stripping cluster_transforms here
    means the deform toggle visually returns a cluster to its pre-rotation position.
    Cone directions at t=1 are derived from the current bead positions (fe.pos/te.pos)
    in helix_renderer.applyDeformLerp rather than from this map, so removing cluster
    transforms here no longer causes cone-direction mismatches at t=1.
    """
    straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
    return _geometry_for_design(straight)


def _straight_helix_axes(design: Design) -> list[dict]:
    """Return un-deformed helix axes, derived from grid_pos when available."""
    from backend.core.deformation import _normalize_helix_for_grid
    result = []
    for h in design.helices:
        hn = _normalize_helix_for_grid(h, design.lattice_type)
        result.append({
            "helix_id": h.id,
            "start":    [hn.axis_start.x, hn.axis_start.y, hn.axis_start.z],
            "end":      [hn.axis_end.x,   hn.axis_end.y,   hn.axis_end.z],
            "samples":  None,
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

        # Radial outward direction: the deformed base_normal points inward
        # (backbone → base, toward the axis).  Negating it gives the outward
        # radial in the already-deformed frame, so extensions follow
        # bend / twist / translate / rotate transforms automatically.
        bn_raw = np.array(nuc_a.base_normal, dtype=float)
        radial_len = float(np.linalg.norm(bn_raw))
        if radial_len < 1e-6:
            radial = np.array([1.0, 0.0, 0.0])
        else:
            radial = -bn_raw / radial_len

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


def _geometry_for_helices(
    design: Design,
    helix_ids: frozenset[str] | None = None,
) -> list[dict]:
    """Compute nucleotide geometry for *design*.

    If *helix_ids* is given, only nucleotides on those helices are returned.
    This is the partial-update fast path for Fix B: callers that know which
    helices changed pass that set to skip the other 90 % of geometry work.

    Extensions are only appended in full mode (helix_ids is None) — they depend
    on positions from arbitrary helices and must be returned together with the
    full geometry.
    """
    from types import SimpleNamespace
    full_mode = helix_ids is None
    nuc_info  = _strand_nucleotide_info(design, helix_ids)

    # Suppress is_five_prime on the real-helix terminal for strands with a 5' extension.
    five_prime_ext_strands = {ext.strand_id for ext in design.extensions if ext.end == "five_prime"}
    for strand in design.strands:
        if strand.id not in five_prime_ext_strands or not strand.domains:
            continue
        first = strand.domains[0]
        if helix_ids is not None and first.helix_id not in helix_ids:
            continue
        key = (first.helix_id, first.start_bp, first.direction)
        entry = nuc_info.get(key)
        if entry and entry.get("is_five_prime"):
            nuc_info[key] = {**entry, "is_five_prime": False}

    _missing   = {"strand_id": None, "strand_type": StrandType.STAPLE.value,
                  "is_five_prime": False, "is_three_prime": False, "domain_index": 0,
                  "overhang_id": None}
    _dir_enums = (Direction.FORWARD, Direction.REVERSE)  # index by int 0/1
    needs_pos_map = full_mode and bool(design.extensions)
    result:      list[dict] = []
    nuc_pos_map: dict       = {}

    # Pre-compute min/max bp referenced by any strand domain per helix.
    # Needed to render ss-scaffold loops that extend outside the physical helix span.
    min_domain_bp: dict[str, int] = {}
    max_domain_bp: dict[str, int] = {}
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            hid = domain.helix_id
            if hid not in min_domain_bp or lo < min_domain_bp[hid]:
                min_domain_bp[hid] = lo
            if hid not in max_domain_bp or hi > max_domain_bp[hid]:
                max_domain_bp[hid] = hi

    def _emit_arrs(arrs: dict, helix_id: str) -> None:
        """Append geometry dicts from a nucleotide arrays block."""
        M = len(arrs['bp_indices'])
        if M == 0:
            return
        bp_list   = arrs['bp_indices'].tolist()
        dir_arr   = arrs['directions']
        pos_list  = arrs['positions'].tolist()
        base_list = arrs['base_positions'].tolist()
        bn_list   = arrs['base_normals'].tolist()
        at_list   = arrs['axis_tangents'].tolist()
        for i in range(M):
            bp     = bp_list[i]
            d_enum = _dir_enums[dir_arr[i]]
            key    = (helix_id, bp, d_enum)
            if needs_pos_map:
                nuc_pos_map[key] = SimpleNamespace(
                    position     = arrs['positions'][i],
                    axis_tangent = arrs['axis_tangents'][i],
                    base_normal  = arrs['base_normals'][i],
                )
            sinfo = nuc_info.get(key, _missing)
            result.append({
                "helix_id":          helix_id,
                "bp_index":          bp,
                "direction":         d_enum.value,
                "backbone_position": pos_list[i],
                "base_position":     base_list[i],
                "base_normal":       bn_list[i],
                "axis_tangent":      at_list[i],
                **sinfo,
            })

    for helix in design.helices:
        if helix_ids is not None and helix.id not in helix_ids:
            continue
        arrs = deformed_nucleotide_arrays(helix, design)
        _emit_arrs(arrs, arrs['helix_id'])

        # Render nucleotides outside the physical helix span (ss-scaffold loops).
        # These must go through the same deformation / cluster transform pipeline
        # so they follow bend / twist / translate / rotate ops.
        from backend.core.deformation import _normalize_helix_for_grid, deform_extended_arrays
        norm_helix = None  # lazy — only normalise once if either side needs it

        lo_bp = min_domain_bp.get(helix.id, helix.bp_start)
        if lo_bp < helix.bp_start:
            norm_helix = _normalize_helix_for_grid(helix, design.lattice_type)
            extra_arrs = nucleotide_positions_arrays_extended(norm_helix, lo_bp)
            extra_arrs = deform_extended_arrays(extra_arrs, helix, design, edge_bp=helix.bp_start)
            _emit_arrs(extra_arrs, helix.id)

        hi_bp = max_domain_bp.get(helix.id, helix.bp_start + helix.length_bp - 1)
        helix_hi = helix.bp_start + helix.length_bp   # first bp past helix right edge
        if hi_bp >= helix_hi:
            if norm_helix is None:
                norm_helix = _normalize_helix_for_grid(helix, design.lattice_type)
            extra_arrs = nucleotide_positions_arrays_extended_right(norm_helix, hi_bp)
            extra_arrs = deform_extended_arrays(extra_arrs, helix, design, edge_bp=helix_hi - 1)
            _emit_arrs(extra_arrs, helix.id)

    if full_mode:
        if design.extensions:
            result.extend(_strand_extension_geometry(design, nuc_pos_map))
    return result


def _geometry_for_design(design: Design) -> list[dict]:
    return _geometry_for_helices(design)


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


def _init_multiscaffold_clusters(design: Design) -> Design:
    """For designs with 2+ scaffold strands, create one domain-level cluster per scaffold.

    Each cluster contains:
    - All domains of that scaffold strand.
    - All staple domains whose bp overlap with that scaffold exceeds every other scaffold.

    Staples with an exact tie in bp overlap are left unassigned (no cluster).
    Single-scaffold designs are returned unchanged.
    """
    from backend.core.models import ClusterRigidTransform, DomainRef

    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    if len(scaffolds) < 2:
        return design

    # Build per-helix bp interval lists for each scaffold.
    # scaf_intervals[scaf_id][helix_id] = [(lo, hi), ...]
    scaf_intervals: dict[str, dict[str, list[tuple[int, int]]]] = {}
    for scaf in scaffolds:
        cov: dict[str, list[tuple[int, int]]] = {}
        for domain in scaf.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            cov.setdefault(domain.helix_id, []).append((lo, hi))
        scaf_intervals[scaf.id] = cov

    def _domain_overlap(domain, scaf_id: str) -> int:
        """Count bp positions in *domain* that overlap scaffold *scaf_id*."""
        intervals = scaf_intervals[scaf_id].get(domain.helix_id, [])
        if not intervals:
            return 0
        lo = min(domain.start_bp, domain.end_bp)
        hi = max(domain.start_bp, domain.end_bp)
        total = 0
        for slo, shi in intervals:
            olo, ohi = max(lo, slo), min(hi, shi)
            if ohi >= olo:
                total += ohi - olo + 1
        return total

    # Assign each staple to the scaffold with the most overlapping bp.
    # None = unassigned (tie or no overlap).
    staple_assignment: dict[str, str | None] = {}
    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE:
            continue
        overlap = {
            scaf.id: sum(_domain_overlap(d, scaf.id) for d in strand.domains)
            for scaf in scaffolds
        }
        max_bp = max(overlap.values())
        if max_bp == 0:
            staple_assignment[strand.id] = None
            continue
        winners = [sid for sid, bp in overlap.items() if bp == max_bp]
        staple_assignment[strand.id] = winners[0] if len(winners) == 1 else None

    # Build one ClusterRigidTransform per scaffold.
    clusters: list[ClusterRigidTransform] = []
    for n, scaf in enumerate(scaffolds, start=1):
        domain_refs: list[DomainRef] = []
        helix_set: set[str] = set()

        for di, domain in enumerate(scaf.domains):
            domain_refs.append(DomainRef(strand_id=scaf.id, domain_index=di))
            helix_set.add(domain.helix_id)

        for strand in design.strands:
            if strand.strand_type != StrandType.STAPLE:
                continue
            if staple_assignment.get(strand.id) != scaf.id:
                continue
            for di, domain in enumerate(strand.domains):
                domain_refs.append(DomainRef(strand_id=strand.id, domain_index=di))
                helix_set.add(domain.helix_id)

        clusters.append(ClusterRigidTransform(
            name=f"Scaffold {n}",
            is_default=False,
            helix_ids=sorted(helix_set),
            domain_ids=domain_refs,
        ))

    return design.copy_with(cluster_transforms=clusters)


def _design_response(design: Design, report: ValidationReport) -> dict:
    design = _ensure_default_cluster(design)
    return {
        "design":     design.to_dict(),
        "validation": _validation_dict(report, design),
    }


def _design_response_with_geometry(
    design: Design,
    report: ValidationReport,
    changed_helix_ids: list[str] | None = None,
) -> dict:
    """Like _design_response but embeds geometry so the frontend needs only one
    round-trip and can update design + geometry atomically (one scene rebuild).

    *changed_helix_ids* — when given, activates partial geometry (Fix B):
      • Only nucleotides on those helices are computed and returned.
      • Synthetic IDs (``__xb_*``, ``__ext_*``) are kept in the list so the
        frontend can remove stale entries from its geometry cache, but they are
        filtered out before calling _geometry_for_helices (no real helix).
      • ``helix_axes`` is intentionally omitted: crossover / xb mutations do not
        move helix axes, so the frontend keeps its existing currentHelixAxes.
    When None, full geometry is returned (legacy path, used for bulk ops).
    """
    if changed_helix_ids is not None:
        # Partial path — compute only the real helices that actually changed.
        real_ids = frozenset(hid for hid in changed_helix_ids if not hid.startswith('__'))
        return {
            **_design_response(design, report),
            "nucleotides":       _geometry_for_helices(design, real_ids) if real_ids else [],
            "partial_geometry":  True,
            "changed_helix_ids": changed_helix_ids,
            # helix_axes omitted on purpose — see docstring.
        }
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


class HelixAtCellRequest(BaseModel):
    row: int
    col: int
    length_bp: int = 42


class DomainRequest(BaseModel):
    helix_id: str
    start_bp: int
    end_bp: int
    direction: Direction


class StrandRequest(BaseModel):
    domains: List[DomainRequest] = []
    strand_type: StrandType = StrandType.STAPLE
    sequence: Optional[str] = None


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


class HalfCrossoverRequest(BaseModel):
    helix_id: str
    index: int
    strand: Direction


class CrossoverExtraBasesRequest(BaseModel):
    sequence: str  # "" to clear; must match [ACGTNacgtn]*


class CrossoverExtraBasesBatchEntry(BaseModel):
    crossover_id: str
    sequence: str


class BatchCrossoverExtraBasesRequest(BaseModel):
    entries: List[CrossoverExtraBasesBatchEntry]


class BatchDeleteCrossoversRequest(BaseModel):
    crossover_ids: List[str]


class MoveCrossoverRequest(BaseModel):
    crossover_id: str
    new_index: int


class BatchMoveCrossoversRequest(BaseModel):
    moves: List[MoveCrossoverRequest]


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
    ligate_adjacent: bool = True


class BundleSegmentRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int           # may be negative — extrudes in -axis direction
    plane: str = "XY"
    offset_nm: float = 0.0   # position of axis_start along the plane normal
    strand_filter: str = "both"   # "both" | "scaffold" | "staples"
    ligate_adjacent: bool = True


class BundleContinuationRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...] — may mix continuation and fresh cells
    length_bp: int
    plane: str = "XY"
    offset_nm: float = 0.0
    strand_filter: str = "both"   # "both" | "scaffold" | "staples"
    extend_inplace: bool = True   # True = extend existing helix axis in-place; False = create new helix
    ligate_adjacent: bool = True


class BundleDeformedContinuationRequest(BaseModel):
    cells: List[List[int]]   # [[row, col], ...]
    length_bp: int
    # Deformed cross-section frame from GET /design/deformed-frame
    grid_origin: List[float]   # [x, y, z]
    axis_dir:    List[float]   # [x, y, z]
    frame_right: List[float]   # [x, y, z]
    frame_up:    List[float]   # [x, y, z]
    plane: str = "XY"          # used for helix/strand ID naming only
    ref_helix_id: Optional[str] = None  # helix that opened the slice plane — used for cluster membership


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
    from backend.core.lattice import make_bundle_segment, ligate_new_strands
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    try:
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
        updated = make_bundle_segment(
            design, cells, body.length_bp, body.plane, body.offset_nm, body.strand_filter,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    if body.ligate_adjacent:
        existing_ids = {s.id for s in design.strands}
        new_ids = {s.id for s in updated.strands if s.id not in existing_ids}
        if new_ids:
            updated = ligate_new_strands(updated, new_ids)

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/bundle-continuation", status_code=201)
def add_bundle_continuation(body: BundleContinuationRequest) -> dict:
    """Extrude a bundle segment in continuation mode (occupied cells ending at offset extend existing strands).

    Fresh cells get new scaffold + staple strands; continuation cells append domains to the
    existing strands whose helices end at offset_nm.
    """
    from backend.core.lattice import make_bundle_continuation, ligate_new_strands
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

    if body.ligate_adjacent:
        existing_ids = {s.id for s in design.strands}
        new_ids = {s.id for s in updated.strands if s.id not in existing_ids}
        if new_ids:
            updated = ligate_new_strands(updated, new_ids)

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
            design, cells, body.length_bp, frame, deformed_endpoints, body.plane,
            ref_helix_id=body.ref_helix_id,
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/bundle", status_code=201)
def create_bundle(body: BundleRequest) -> dict:
    """Create a honeycomb bundle design from a list of (row, col) lattice cells."""
    from backend.core.lattice import make_bundle_design, ligate_new_strands
    from backend.core.validator import validate_design

    try:
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
        new_design = make_bundle_design(cells, body.length_bp, body.name, body.plane, strand_filter=body.strand_filter, lattice_type=body.lattice_type)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    if body.ligate_adjacent:
        new_ids = {s.id for s in new_design.strands}
        if new_ids:
            new_design = ligate_new_strands(new_design, new_ids)

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
def get_geometry(
    apply_deformations: bool = Query(True),
    helix_ids: str | None = Query(
        None,
        description="Comma-separated helix IDs.  When given, only those helices "
                    "are returned (partial update for Fix B).  helix_axes always "
                    "covers all helices regardless of this filter.",
    ),
) -> dict:
    """Return geometry for the active design.

    Returns { nucleotides: [...], helix_axes: [{helix_id, start, end}, ...] }

    When apply_deformations=false, returns the straight (un-deformed) bundle
    positions regardless of any DeformationOps stored on the design.

    When helix_ids is supplied, only nucleotides on those helices are returned.
    The caller is responsible for merging the partial result into the existing
    full geometry (see Fix B in client.js).
    """
    design = design_state.get_or_404()
    ids: frozenset[str] | None = (
        frozenset(helix_ids.split(",")) if helix_ids else None
    )
    if apply_deformations:
        out = {
            "nucleotides": _geometry_for_helices(design, ids),
            "helix_axes":  deformed_helix_axes(design),
        }
    else:
        straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
        out = {
            "nucleotides": _geometry_for_helices(straight, ids),
            "helix_axes":  _straight_helix_axes(design),
        }
    if ids is not None:
        # Signal to the frontend that this is a partial response — only the
        # requested helices are present and the result should be merged rather
        # than replacing the full geometry (Fix B merge path in client.js).
        out["partial_geometry"]  = True
        out["changed_helix_ids"] = list(ids)
    return out


@router.post("/design/load")
def load_design(body: FilePathRequest) -> dict:
    """Load a .nadoc file from the given server-side path."""
    from backend.core.lattice import reconcile_all_inline_overhangs
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
    design = reconcile_all_inline_overhangs(design)
    design_state.clear_history()   # fresh baseline — no undo into previous session
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
    from backend.core.lattice import reconcile_all_inline_overhangs
    from backend.core.validator import validate_design
    try:
        design = Design.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to parse design: {exc}") from exc
    design = reconcile_all_inline_overhangs(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    return _design_response(design, report)


class CadnanoImportRequest(BaseModel):
    content: str   # raw caDNAno v2 JSON string sent by the browser


class ScadnanoImportRequest(BaseModel):
    content: str   # raw scadnano JSON string sent by the browser


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
    design = _init_multiscaffold_clusters(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    resp = _design_response(design, report)
    if import_warnings:
        resp["import_warnings"] = import_warnings
    return resp


def _backfill_overhang_sequences(design: Design) -> Design:
    """After autodetect_all_overhangs, populate OverhangSpec.sequence from strand.sequence.

    scadnano designs often carry pre-assigned sequences on all domains, including
    those that become overhangs after import.  autodetect_all_overhangs creates
    OverhangSpec objects with sequence=None.  This function walks each sequenced
    strand in 5'→3' domain order, extracts the substring corresponding to each
    overhang domain (accounting for skip positions), and stores it on the matching
    OverhangSpec so the sequence survives future assign_staple_sequences calls.

    Strands without a sequence, and overhangs whose OverhangSpec already has a
    sequence set, are left unchanged.
    """
    overhang_by_id: dict[str, object] = {o.id: o for o in design.overhangs}
    if not overhang_by_id:
        return design

    # Build per-helix skip sets once.
    helix_skips: dict[str, set] = {
        h.id: {ls.bp_index for ls in h.loop_skips if ls.delta == -1}
        for h in design.helices
    }

    updated_overhangs = list(design.overhangs)
    ovhg_index = {o.id: i for i, o in enumerate(updated_overhangs)}

    for strand in design.strands:
        if strand.sequence is None:
            continue
        seq = strand.sequence
        pos = 0
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            skips = helix_skips.get(domain.helix_id, set())
            n = (hi - lo + 1) - sum(1 for bp in skips if lo <= bp <= hi)
            if n <= 0:
                continue
            if domain.overhang_id is not None:
                spec_idx = ovhg_index.get(domain.overhang_id)
                if spec_idx is not None:
                    spec = updated_overhangs[spec_idx]
                    if spec.sequence is None:
                        updated_overhangs[spec_idx] = spec.model_copy(
                            update={"sequence": seq[pos : pos + n]}
                        )
            pos += n

    return design.copy_with(overhangs=updated_overhangs)


@router.post("/design/import/scadnano", status_code=200)
def import_scadnano_design(body: ScadnanoImportRequest) -> dict:
    """Load a scadnano .sc file sent by the browser as raw JSON text.

    Parses the scadnano JSON format, reconstructing helices, strands, domains,
    crossovers, crossover bases (from loopouts), and strand extensions as a
    NADOC Design, then sets it as the active design (clearing undo history).
    """
    from backend.core.scadnano import import_scadnano
    from backend.core.lattice import autodetect_all_overhangs
    from backend.core.validator import validate_design
    import json as _json
    try:
        data = _json.loads(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Invalid JSON: {exc}") from exc
    try:
        design, import_warnings = import_scadnano(data)
    except Exception as exc:
        raise HTTPException(400, detail=f"scadnano import failed: {exc}") from exc
    design = autodetect_all_overhangs(design)
    design = _backfill_overhang_sequences(design)
    design = _init_multiscaffold_clusters(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    resp = _design_response(design, report)
    if import_warnings:
        resp["import_warnings"] = import_warnings
    return resp


class PdbImportRequest(BaseModel):
    content: str   # raw PDB file text sent by the browser
    merge: bool = False  # if True, add to existing design instead of replacing


@router.post("/design/import/pdb", status_code=200)
def import_pdb_design(body: PdbImportRequest) -> dict:
    """Import a PDB file containing DNA, converting it to a NADOC Design.

    Non-DNA atoms (water, ions, protein) are removed.  Each duplex in the
    PDB becomes a helix with two strands.  The import is placed in its own
    cluster so it can be moved independently.

    When ``merge`` is True and a design already exists, the PDB helices and
    strands are added to the existing design as a new cluster.  Otherwise a
    fresh design is created.
    """
    from backend.core.pdb_to_design import import_pdb, merge_pdb_into_design
    from backend.core.validator import validate_design

    existing = design_state.get_design() if body.merge else None

    try:
        if existing and existing.helices:
            design, pdb_atomistic, import_warnings = merge_pdb_into_design(existing, body.content)
        else:
            design, pdb_atomistic, import_warnings = import_pdb(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"PDB import failed: {exc}") from exc

    design_state.clear_history()
    design_state.set_design(design)
    design_state.set_pdb_atomistic(pdb_atomistic)
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


@router.post("/design/helix-at-cell", status_code=201)
def add_helix_at_cell(body: HelixAtCellRequest) -> dict:
    """Add a helix at a lattice cell (row, col).

    Computes axis position, phase offset, and twist from the design's lattice
    type so the 2D editor does not need to know lattice constants.  Returns the
    same response shape as POST /design/helices plus the full design response.
    """
    from backend.core.constants import BDNA_RISE_PER_BP as _RISE
    from backend.core.lattice import (
        _lattice_direction,
        _lattice_phase_offset,
        _lattice_position,
        _lattice_twist,
    )

    design = design_state.get_or_404()
    lt = design.lattice_type

    lx, ly = _lattice_position(body.row, body.col, lt)
    direction    = _lattice_direction(body.row, body.col, lt)
    phase_offset = _lattice_phase_offset(direction, lt)
    twist        = _lattice_twist(lt)
    length_nm    = body.length_bp * _RISE

    axis_start = Vec3(x=lx, y=ly, z=0.0)
    axis_end   = Vec3(x=lx, y=ly, z=length_nm)

    new_helix = Helix(
        axis_start=axis_start,
        axis_end=axis_end,
        length_bp=body.length_bp,
        phase_offset=phase_offset,
        twist_per_bp_rad=twist,
        bp_start=0,
        grid_pos=(body.row, body.col),
    )
    design, report = design_state.mutate_and_validate(
        lambda d: d.helices.append(new_helix)
    )
    return {
        **_design_response(design, report),
        "nucleotides": [
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


class HelixExtendRequest(BaseModel):
    lo_bp: int   # desired minimum bp — only extends left, never shrinks
    hi_bp: int   # desired maximum bp — only extends right, never shrinks


@router.patch("/design/helices/{helix_id}/extend")
def extend_helix_bounds(helix_id: str, body: HelixExtendRequest) -> dict:
    """Extend a helix's bp range to cover [lo_bp, hi_bp].  Never shrinks.

    Adjusts axis_start/axis_end along the existing axis direction and updates
    bp_start, length_bp, and phase_offset to keep existing nucleotide geometry
    unchanged.
    """
    import math as _math

    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    helix  = _find_helix(design, helix_id)

    h_lo = helix.bp_start
    h_hi = helix.bp_start + helix.length_bp - 1

    new_lo = min(body.lo_bp, h_lo)
    new_hi = max(body.hi_bp, h_hi)

    if new_lo == h_lo and new_hi == h_hi:
        report = validate_design(design)
        return _design_response_with_geometry(design, report, changed_helix_ids=[helix_id])

    ax     = helix.axis_end.to_array() - helix.axis_start.to_array()
    ax_len = float(_math.sqrt(float((ax * ax).sum())))
    unit   = ax / ax_len if ax_len > 1e-9 else helix.axis_start.to_array() * 0 + [0, 0, 1]

    extra_lo = h_lo - new_lo   # bps prepended (≥ 0)
    extra_hi = new_hi - h_hi   # bps appended  (≥ 0)

    new_axis_start = helix.axis_start.to_array() - extra_lo * BDNA_RISE_PER_BP * unit
    new_axis_end   = helix.axis_end.to_array()   + extra_hi * BDNA_RISE_PER_BP * unit

    updated = helix.model_copy(update={
        "axis_start":   Vec3.from_array(new_axis_start),
        "axis_end":     Vec3.from_array(new_axis_end),
        "length_bp":    new_hi - new_lo + 1,
        "bp_start":     new_lo,
        # phase_offset is defined at local_bp=0 (= axis_start).  Moving axis_start
        # back by extra_lo steps means the old geometry now starts at local_bp=extra_lo,
        # so we subtract extra_lo × twist to keep the old nucleotides in place.
        "phase_offset": helix.phase_offset - extra_lo * helix.twist_per_bp_rad,
    })

    def _apply(d: Design) -> None:
        for i, h in enumerate(d.helices):
            if h.id == helix_id:
                d.helices[i] = updated
                return

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report, changed_helix_ids=[helix_id])


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


class ScaffoldPaintRequest(BaseModel):
    """Paint a contiguous scaffold domain onto a helix from the 2D editor pencil tool.

    lo_bp / hi_bp are the lower and upper bp indices (left-to-right in pathview,
    order-independent).  The server determines the strand direction from the
    helix's grid_pos + lattice_type and enforces correct start_bp/end_bp polarity.
    """
    helix_id: str
    lo_bp: int
    hi_bp: int


@router.post("/design/scaffold-domain-paint", status_code=201)
def scaffold_domain_paint(body: ScaffoldPaintRequest) -> dict:
    """Create a scaffold domain on a helix from the 2D editor pencil tool.

    Direction is derived from the helix's grid_pos and the design's lattice type.
    Returns 409 if a scaffold domain already overlaps the requested range.
    """
    import re
    from backend.core.lattice import (
        _lattice_direction,
    )

    _HC_RE = re.compile(r"^h_\w+_(-?\d+)_(-?\d+)$")

    design = design_state.get_or_404()
    helix  = _find_helix(design, body.helix_id)
    lt     = design.lattice_type

    # Resolve (row, col) for direction lookup
    if helix.grid_pos is not None:
        row, col = helix.grid_pos
    else:
        m = _HC_RE.match(helix.id)
        if m:
            row, col = int(m.group(1)), int(m.group(2))
        else:
            raise HTTPException(
                400,
                detail=f"Helix {helix.id!r} has no grid_pos — cannot determine scaffold direction.",
            )

    direction = _lattice_direction(row, col, lt)

    # Clamp to helix bp bounds
    h_lo = helix.bp_start
    h_hi = helix.bp_start + helix.length_bp - 1
    lo   = max(body.lo_bp, h_lo)
    hi   = min(body.hi_bp, h_hi)
    if lo > hi:
        raise HTTPException(400, detail="bp range outside helix bounds.")

    # Reject overlap with existing scaffold domains on this helix
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in strand.domains:
            if dom.helix_id != body.helix_id:
                continue
            d_lo = min(dom.start_bp, dom.end_bp)
            d_hi = max(dom.start_bp, dom.end_bp)
            if d_lo <= hi and d_hi >= lo:
                raise HTTPException(
                    409,
                    detail=(f"Scaffold domain already covers helix {body.helix_id!r} "
                            f"in range [{d_lo}, {d_hi}]."),
                )

    # Polarity: start_bp = 5' end
    if direction == Direction.FORWARD:
        start_bp, end_bp = lo, hi
    else:
        start_bp, end_bp = hi, lo   # REVERSE: 5' is at higher bp index

    new_strand = Strand(
        domains=[Domain(
            helix_id=body.helix_id,
            start_bp=start_bp,
            end_bp=end_bp,
            direction=direction,
        )],
        strand_type=StrandType.SCAFFOLD,
    )
    design, report = design_state.mutate_and_validate(
        lambda d: d.strands.append(new_strand)
    )
    return _design_response_with_geometry(design, report)


@router.post("/design/strands", status_code=201)
def add_strand(body: StrandRequest) -> dict:
    # Pre-assign a palette color so both views render the same hue.
    design_cur = design_state.get_or_404()
    color: str | None = None
    if body.strand_type == StrandType.STAPLE:
        # Index by total staple count (not just colored ones) so it matches
        # the cadnano editor's index-based fallback (STAPLE_PALETTE[strand_index]).
        staple_count = sum(1 for s in design_cur.strands if s.strand_type == StrandType.STAPLE)
        color = STAPLE_PALETTE[staple_count % len(STAPLE_PALETTE)]

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
        color=color,
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

    ovhg_ids_to_remove = {o.id for o in design.overhangs if o.strand_id in id_set}

    def _apply(d: Design) -> None:
        d.strands    = [s for s in d.strands    if s.id not in id_set]
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
    return _design_response_with_geometry(design, report)


@router.delete("/design/strands/{strand_id}")
def delete_strand(strand_id: str) -> dict:
    design = design_state.get_or_404()
    _find_strand(design, strand_id)  # 404 if not found
    # Overhang specs that belong to the deleted strand
    ovhg_ids_to_remove = {o.id for o in design.overhangs if o.strand_id == strand_id}

    def _apply(d: Design) -> None:
        d.strands    = [s for s in d.strands    if s.id != strand_id]
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
    return _design_response_with_geometry(design, report)


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
    design = design_state.get_or_404()
    strand = _find_strand(design, strand_id)
    if domain_index < 0 or domain_index >= len(strand.domains):
        raise HTTPException(400, detail=f"domain_index {domain_index} out of range.")

    # Capture overhang_id before mutation so we can clean up the spec.
    removed_ovhg_id = strand.domains[domain_index].overhang_id

    def _apply(d: Design) -> None:
        s = _find_strand(d, strand_id)
        s.domains.pop(domain_index)
        if removed_ovhg_id is not None:
            d.overhangs = [o for o in d.overhangs if o.id != removed_ovhg_id]

    design, report = design_state.mutate_and_validate(_apply)
    strand = _find_strand(design, strand_id)
    return {
        "strand": strand.model_dump(),
        **_design_response(design, report),
    }


# ── Crossover helpers ─────────────────────────────────────────────────────────


def _find_strand_domain_at(
    design: "Design",
    helix_id: str,
    index: int,
    direction: "Direction",
) -> tuple["Strand | None", int]:
    """Return (strand, domain_index) for the strand whose domain contains this slot.

    Returns (None, -1) if no strand occupies the slot.
    """
    for strand in design.strands:
        for di, domain in enumerate(strand.domains):
            if domain.helix_id != helix_id or domain.direction != direction:
                continue
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            if lo <= index <= hi:
                return strand, di
    return None, -1


def _desplice_strands_for_crossover(
    design: "Design",
    half_a: "HalfCrossover",
    half_b: "HalfCrossover",
) -> list["Strand"]:
    """Return updated strand list after removing a crossover.

    Finds the strand containing the cross-helix domain transition at the
    crossover index and splits it back into two per-helix fragments.  Checks
    both half_a→half_b and half_b→half_a orderings because the ligation
    direction depends on bow direction and parity.  Returns the strand list
    unchanged if no matching transition is found.
    """
    index = half_a.index  # == half_b.index

    def _try(ha: "HalfCrossover", hb: "HalfCrossover") -> "list[Strand] | None":
        for strand in design.strands:
            for di in range(len(strand.domains) - 1):
                d0 = strand.domains[di]
                d1 = strand.domains[di + 1]
                if d0.helix_id != ha.helix_id or d0.direction != ha.strand:
                    continue
                if d0.end_bp != index:
                    continue
                if d1.helix_id != hb.helix_id or d1.direction != hb.strand:
                    continue
                if d1.start_bp != index:
                    continue
                part_a = strand.model_copy(update={"domains": list(strand.domains[:di + 1])})
                part_b = Strand(
                    domains=list(strand.domains[di + 1:]),
                    strand_type=strand.strand_type,
                )
                new_strands = [s for s in design.strands if s.id != strand.id]
                if part_a.domains:
                    new_strands.append(part_a)
                if part_b.domains:
                    new_strands.append(part_b)
                return new_strands
        return None

    result = _try(half_a, half_b)
    if result is not None:
        return result
    result = _try(half_b, half_a)
    if result is not None:
        return result
    return list(design.strands)


# ── Crossover endpoints ───────────────────────────────────────────────────────


@router.get("/design/crossovers/valid")
def get_valid_crossovers(
    helix_a_id: Optional[str] = None,
    helix_b_id: Optional[str] = None,
) -> list[dict]:
    """Return all valid crossover sites for the current design.

    Both helices must have grid_pos set.  Results may be filtered by helix ID.
    """
    from backend.core.crossover_positions import all_valid_crossover_sites

    design = design_state.get_or_404()
    sites = all_valid_crossover_sites(design)
    if helix_a_id is not None:
        sites = [s for s in sites if s["helix_a_id"] == helix_a_id]
    if helix_b_id is not None:
        sites = [s for s in sites if s["helix_b_id"] == helix_b_id]
    return sites


def _ligate_crossover(design: "Design", xover: "Crossover") -> "Design":
    """Ligate the two strand fragments connected by a crossover.

    Finds the strand whose 3' end matches one half and the strand whose 5'
    start matches the other half, then joins them into a single multi-domain
    strand via _ligate().  Returns the design unchanged if no matching pair
    is found (e.g. both halves are already on the same strand).
    """
    from backend.core.lattice import _ligate

    ha, hb = xover.half_a, xover.half_b

    # Build terminal maps for current strands
    three_prime: dict[tuple[str, int, "Direction"], "Strand"] = {}
    five_prime: dict[tuple[str, int, "Direction"], "Strand"] = {}
    for s in design.strands:
        if not s.domains:
            continue
        ld = s.domains[-1]
        three_prime[(ld.helix_id, ld.end_bp, ld.direction)] = s
        fd = s.domains[0]
        five_prime[(fd.helix_id, fd.start_bp, fd.direction)] = s

    # Try: 3' on half_a → 5' on half_b
    s_from = three_prime.get((ha.helix_id, ha.index, ha.strand))
    s_to = five_prime.get((hb.helix_id, hb.index, hb.strand))
    if s_from is not None and s_to is not None and s_from.id != s_to.id:
        return _ligate(design, s_from, s_to)

    # Try reverse: 3' on half_b → 5' on half_a
    s_from = three_prime.get((hb.helix_id, hb.index, hb.strand))
    s_to = five_prime.get((ha.helix_id, ha.index, ha.strand))
    if s_from is not None and s_to is not None and s_from.id != s_to.id:
        return _ligate(design, s_from, s_to)

    return design


class PlaceCrossoverRequest(BaseModel):
    half_a:    HalfCrossoverRequest
    half_b:    HalfCrossoverRequest
    nick_bp_a: int
    nick_bp_b: int


def _nick_if_needed(d: "Design", helix_id: str, bp_index: int, direction: "Direction") -> "Design":
    """Nick at (helix_id, bp_index, direction) unless the strand already
    terminates there.  Three no-op cases:
    • "terminus" — bp_index is the 3′ end of the strand (already nicked).
    • "No strand covers" — bp_index is outside any strand's range, meaning
      the strand's 5′ end is already at or past this position (e.g. nick at
      bp −1 when the strand starts at bp 0, from the HC 20|0 period wrap).
    • inter-domain boundary — bp_index is at the end of a domain in a
      multi-domain strand (a crossover junction). The backbone already
      leaves this helix here; splitting would undo a prior crossover's
      ligation."""
    from backend.core.lattice import _find_strand_at, make_nick
    try:
        strand, domain_idx = _find_strand_at(d, helix_id, bp_index, direction)
    except ValueError:
        return d   # no strand covers this position — no-op
    domain = strand.domains[domain_idx]
    if bp_index == domain.end_bp and domain_idx < len(strand.domains) - 1:
        return d   # inter-domain boundary (crossover junction) — no-op
    try:
        return make_nick(d, helix_id, bp_index, direction)
    except ValueError as exc:
        if "terminus" in str(exc):
            return d   # already nicked — no-op
        raise


@router.post("/design/crossovers/place", status_code=201)
def place_crossover(body: PlaceCrossoverRequest) -> dict:
    """Place a crossover atomically: nick + ligate + record.

    CROSSOVER = nick + ligate + record. If changing this, ask user first.

    All steps are wrapped in a single undo checkpoint (snapshot + set_design_silent),
    so one Ctrl-Z reverts the entire placement.  The frontend passes pre-computed nick
    positions; no geometric reasoning is done here.
    """
    from backend.core.crossover_positions import validate_crossover
    from backend.core.validator import validate_design

    design = design_state.get_or_404()

    half_a = HalfCrossover(
        helix_id=body.half_a.helix_id,
        index=body.half_a.index,
        strand=body.half_a.strand,
    )
    half_b = HalfCrossover(
        helix_id=body.half_b.helix_id,
        index=body.half_b.index,
        strand=body.half_b.strand,
    )

    # Uses module-level _nick_if_needed (shared with auto_crossover).

    # Single undo checkpoint — covers all three steps below.
    design_state.snapshot()

    try:
        current = _nick_if_needed(design, body.half_a.helix_id, body.nick_bp_a, body.half_a.strand)
        current = _nick_if_needed(current, body.half_b.helix_id, body.nick_bp_b, body.half_b.strand)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    err = validate_crossover(current, half_a, half_b)
    if err:
        raise HTTPException(400, detail=err)

    xover = Crossover(half_a=half_a, half_b=half_b)
    # Build a new crossovers list so the snapshot reference in undo history
    # is not mutated (copy_with is shallow — current.crossovers would otherwise
    # alias the snapshot's crossovers list).
    current = current.copy_with(crossovers=list(current.crossovers) + [xover])

    # CROSSOVER = nick + ligate + record. If changing this, ask user first.
    # Ligate the two strand fragments that the crossover connects: the strand
    # whose 3' end sits at one half and the strand whose 5' start sits at the
    # other half become a single multi-domain strand.
    current = _ligate_crossover(current, xover)

    # set_design_silent: snapshot() above already captured the undo entry.
    design_state.set_design_silent(current)
    report = validate_design(current)
    return {
        "crossover": xover.model_dump(),
        **_design_response_with_geometry(current, report),
    }


@router.post("/design/crossovers/auto", status_code=200)
def auto_crossover() -> dict:
    """Place all possible staple crossovers automatically.

    For each valid, unoccupied crossover site where both staple slots are
    covered by strands:
      1. Nick helix A's staple strand at the appropriate bp.
      2. Nick helix B's staple strand at the appropriate bp.
      3. Ligate the two fragments into a multi-domain strand.
      4. Register the crossover record.

    Same nick + ligate + record flow as place_crossover, applied in bulk.
    Scaffold crossovers are not placed.

    Only the lower bp of each adjacent pair is used as the canonical site
    (e.g. HC pair (6,7) → canonical 6; SQ pair (7,8) → canonical 7).
    The upper bp (bow-right position) is skipped to avoid double-processing.
    """
    from backend.core.crossover_positions import (
        all_valid_crossover_sites,
        build_strand_ranges,
        slot_covered,
        validate_crossover,
    )
    from backend.core.validator import validate_design

    # Bow-right sets: the upper bp of each adjacent pair — skip these so each
    # pair is processed exactly once via its lower bp.
    HC_BOW_RIGHT: frozenset[int] = frozenset({0, 7, 14})   # HC period 21
    SQ_BOW_RIGHT: frozenset[int] = frozenset({0, 8, 16, 24})  # SQ period 32
    HC_PERIOD = 21
    SQ_PERIOD = 32

    design = design_state.get_or_404()
    is_hc     = design.lattice_type.value == "HONEYCOMB"
    period    = HC_PERIOD if is_hc else SQ_PERIOD
    bow_right = HC_BOW_RIGHT if is_hc else SQ_BOW_RIGHT

    # Occupied crossover slots: (helix_id, index, strand)
    occupied: set[tuple[str, int, str]] = set()
    for xo in design.crossovers:
        occupied.add((xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value))
        occupied.add((xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand.value))

    # helix.id → parity (True = even = scaffold runs FORWARD)
    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}

    def _scaffold_fwd(helix_id: str) -> bool:
        h = helix_map.get(helix_id)
        if h is None:
            return True
        row, col = h.grid_pos
        return (row + col) % 2 == 0

    # Build per-helix scaffold crossover index lists for proximity exclusion.
    # A crossover half is a scaffold half when its strand direction matches the
    # expected scaffold direction for that helix (even parity → FORWARD).
    scaffold_xover_by_helix: dict[str, list[int]] = {}
    for xo in design.crossovers:
        for half in (xo.half_a, xo.half_b):
            h = helix_map.get(half.helix_id)
            if h is None:
                continue
            row, col = h.grid_pos
            is_even_parity = (row + col) % 2 == 0
            expected_scaf_dir = "FORWARD" if is_even_parity else "REVERSE"
            if half.strand.value == expected_scaf_dir:
                scaffold_xover_by_helix.setdefault(half.helix_id, []).append(half.index)

    sites = all_valid_crossover_sites(design)

    # De-duplicate (A→B) vs (B→A) mirror duplicates emitted by all_valid_crossover_sites.
    # Both the bow-left and bow-right position of each major-groove pair are kept.
    seen_pairs: set[tuple[str, str, int]] = set()
    design_state.snapshot()

    current = design
    existing_xover_count = len(current.crossovers)
    placed = 0

    for site in sites:
        hid_a   = site["helix_a_id"]
        hid_b   = site["helix_b_id"]
        bp      = site["index"]   # lower bp of the pair

        # Skip B→A duplicates (all_valid_crossover_sites emits both directions)
        pair_key = (min(hid_a, hid_b), max(hid_a, hid_b), bp)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        # Staple direction: opposite of scaffold direction
        fwd_a  = _scaffold_fwd(hid_a)
        stap_a = "REVERSE" if fwd_a else "FORWARD"
        stap_b = "FORWARD" if fwd_a else "REVERSE"   # neighbor has opposite parity

        # lower_bp is the left boundary of the nick gap, matching the pathview rule:
        #   bow-right (bp % period in bow_right) → lower_bp = bp - 1
        #   bow-left                              → lower_bp = bp
        # The crossover is registered at `bp` (sprite position); nick positions use lower_bp.
        is_bow_right = (bp % period) in bow_right
        lower_bp = bp - 1 if is_bow_right else bp

        # Nick positions:
        #   FORWARD staple nicked at lower_bp  (3′ end of left fragment)
        #   REVERSE staple nicked at lower_bp+1 (3′ end of left fragment in 5′→3′ direction)
        nick_a = lower_bp     if stap_a == "FORWARD" else lower_bp + 1
        nick_b = lower_bp     if stap_b == "FORWARD" else lower_bp + 1

        # Skip if this staple crossover falls within 7 bp of any scaffold crossover
        # on either helix (checked independently per helix).
        _SCAF_MARGIN = 7
        if any(
            any(abs(lower_bp - sx) <= _SCAF_MARGIN for sx in scaffold_xover_by_helix.get(hid, []))
            for hid in (hid_a, hid_b)
        ):
            continue

        # Rebuild strand coverage from current (mutates with each nick)
        sr = build_strand_ranges(current)

        # Helix bp ranges — used to skip out-of-range checks at helix boundaries.
        # At bp=0 (bow-right), lower_bp=-1 which is before the helix start; the
        # strand already ends there so no coverage check or nick is needed.
        # At bp=helix_end (bow-left), lower_bp+1 is one past the end; same rule.
        ha = helix_map.get(hid_a)
        hb = helix_map.get(hid_b)
        ha_min = ha.bp_start if ha else 0
        ha_max = (ha.bp_start + ha.length_bp - 1) if ha else 0
        hb_min = hb.bp_start if hb else 0
        hb_max = (hb.bp_start + hb.length_bp - 1) if hb else 0

        # Both sides of the nick gap must be covered by strands (skip if out of range)
        if ha_min <= lower_bp <= ha_max and not slot_covered(sr, hid_a, lower_bp, stap_a):
            continue
        if ha_min <= lower_bp + 1 <= ha_max and not slot_covered(sr, hid_a, lower_bp + 1, stap_a):
            continue
        if hb_min <= lower_bp <= hb_max and not slot_covered(sr, hid_b, lower_bp, stap_b):
            continue
        if hb_min <= lower_bp + 1 <= hb_max and not slot_covered(sr, hid_b, lower_bp + 1, stap_b):
            continue

        # Crossover slot (registered at lowerBp) must not already be occupied
        if (hid_a, bp, stap_a) in occupied or (hid_b, bp, stap_b) in occupied:
            continue

        # Convert string directions to Direction enum for _nick_if_needed
        dir_a = Direction.FORWARD if stap_a == "FORWARD" else Direction.REVERSE
        dir_b = Direction.FORWARD if stap_b == "FORWARD" else Direction.REVERSE

        # Nick helix A then helix B.
        # Uses _nick_if_needed to guard against splitting multi-domain strands
        # at existing crossover junctions (inter-domain boundaries).  Also
        # handles terminus/no-coverage cases as no-ops.
        # Skip nick calls for positions outside the helix bp range (strand
        # already ends at the boundary — no nick needed).
        if ha_min <= nick_a <= ha_max:
            current = _nick_if_needed(current, hid_a, nick_a, dir_a)
        if hb_min <= nick_b <= hb_max:
            current = _nick_if_needed(current, hid_b, nick_b, dir_b)

        # Register crossover
        half_a = HalfCrossover(helix_id=hid_a, index=bp, strand=dir_a)
        half_b = HalfCrossover(helix_id=hid_b, index=bp, strand=dir_b)
        err = validate_crossover(current, half_a, half_b)
        if err:
            print(f"[AUTO XOVER] validate failed at bp={bp} {hid_a[:8]}↔{hid_b[:8]}: {err}", flush=True)
            continue

        xover = Crossover(half_a=half_a, half_b=half_b)
        # copy_with creates a new crossovers list so the snapshot reference in
        # undo history is not mutated (make_nick returns shallow copies — the
        # crossovers list would otherwise alias the snapshot's list).
        current = current.copy_with(crossovers=list(current.crossovers) + [xover])
        occupied.add((hid_a, bp, stap_a))
        occupied.add((hid_b, bp, stap_b))
        placed += 1

    # Bulk-ligate all crossover-linked fragments into multi-domain strands.
    # Per-crossover ligation (as in place_crossover) doesn't work here because
    # later nicks can split already-ligated strands; the bulk graph walk handles
    # the full crossover topology correctly in one pass.
    from backend.core.lattice import ligate_crossover_chains
    current = ligate_crossover_chains(current)

    design_state.set_design_silent(current)
    report = validate_design(current)
    print(f"[AUTO XOVER] placed {placed} crossovers", flush=True)
    return _design_response_with_geometry(current, report)


@router.post("/design/crossovers/move", status_code=200)
def move_crossover_endpoint(body: MoveCrossoverRequest) -> dict:
    """Move an existing crossover to a new bp index.

    Atomically: update crossover index + resize the two adjacent domains so
    the strand remains continuous.  The new index must be a valid crossover
    position for the same helix pair, and the resized domains must not overlap
    with other domains.
    """
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.validator import validate_design

    design = design_state.get_or_404()

    # ── Find the crossover ───────────────────────────────────────────────────
    xover = next((x for x in design.crossovers if x.id == body.crossover_id), None)
    if xover is None:
        raise HTTPException(404, detail=f"Crossover {body.crossover_id!r} not found.")

    old_index = xover.half_a.index
    new_index = body.new_index
    if new_index == old_index:
        report = validate_design(design)
        return _design_response_with_geometry(design, report)

    # ── Validate new position is a valid lattice crossover site ──────────────
    helix_map = {h.id: h for h in design.helices}
    h_a = helix_map.get(xover.half_a.helix_id)
    h_b = helix_map.get(xover.half_b.helix_id)
    if h_a is None or h_b is None or h_a.grid_pos is None or h_b.grid_pos is None:
        raise HTTPException(422, detail="Crossover helices missing or have no grid_pos")

    def _is_valid_at(idx: int) -> bool:
        for is_scaf in (False, True):
            eb = crossover_neighbor(design.lattice_type, *h_a.grid_pos, idx, is_scaffold=is_scaf)
            ea = crossover_neighbor(design.lattice_type, *h_b.grid_pos, idx, is_scaffold=is_scaf)
            if (eb is not None and eb == tuple(h_b.grid_pos)) or \
               (ea is not None and ea == tuple(h_a.grid_pos)):
                return True
        return False

    if not _is_valid_at(new_index):
        raise HTTPException(
            422,
            detail=f"Index {new_index} is not a valid crossover site for this helix pair",
        )

    # ── Check no other crossover occupies the new position ───────────────────
    for xo in design.crossovers:
        if xo.id == body.crossover_id:
            continue
        for half in (xo.half_a, xo.half_b):
            if half.helix_id == xover.half_a.helix_id and \
               half.index == new_index and half.strand == xover.half_a.strand:
                raise HTTPException(
                    422, detail=f"Position {new_index} on helix A already occupied by another crossover",
                )
            if half.helix_id == xover.half_b.helix_id and \
               half.index == new_index and half.strand == xover.half_b.strand:
                raise HTTPException(
                    422, detail=f"Position {new_index} on helix B already occupied by another crossover",
                )

    # ── Find the two adjacent domains that the crossover connects ────────────
    # Same lookup logic as _desplice_strands_for_crossover: consecutive domains
    # d0.end_bp == old_index → d1.start_bp == old_index.
    found = None
    for ha_half, hb_half in [(xover.half_a, xover.half_b), (xover.half_b, xover.half_a)]:
        if found:
            break
        for strand in design.strands:
            if found:
                break
            for di in range(len(strand.domains) - 1):
                d0 = strand.domains[di]
                d1 = strand.domains[di + 1]
                if d0.helix_id == ha_half.helix_id and d0.direction == ha_half.strand \
                        and d0.end_bp == old_index \
                        and d1.helix_id == hb_half.helix_id and d1.direction == hb_half.strand \
                        and d1.start_bp == old_index:
                    found = (strand, di, d0, d1)
                    break

    if found is None:
        raise HTTPException(422, detail="Could not find adjacent domains for this crossover")

    strand, di, d0, d1 = found

    # ── Validate resized domains ─────────────────────────────────────────────
    new_d0_end   = new_index
    new_d1_start = new_index

    # Domains must remain at least 1 bp long
    d0_lo = min(d0.start_bp, new_d0_end)
    d0_hi = max(d0.start_bp, new_d0_end)
    d1_lo = min(new_d1_start, d1.end_bp)
    d1_hi = max(new_d1_start, d1.end_bp)

    if d0_lo > d0_hi:
        raise HTTPException(422, detail="Moving crossover would make domain on first helix empty")
    if d1_lo > d1_hi:
        raise HTTPException(422, detail="Moving crossover would make domain on second helix empty")

    # Check overlap with other domains on same helix+direction
    def _overlaps(helix_id: str, direction, new_lo: int, new_hi: int,
                  exclude_strand_id: str, exclude_dom_idx: int) -> bool:
        for s in design.strands:
            for dj, dom in enumerate(s.domains):
                if s.id == exclude_strand_id and dj == exclude_dom_idx:
                    continue
                if dom.helix_id != helix_id or dom.direction != direction:
                    continue
                dom_lo = min(dom.start_bp, dom.end_bp)
                dom_hi = max(dom.start_bp, dom.end_bp)
                if new_lo <= dom_hi and dom_lo <= new_hi:
                    return True
        return False

    if _overlaps(d0.helix_id, d0.direction, d0_lo, d0_hi, strand.id, di):
        raise HTTPException(422, detail="Moving crossover would overlap with existing domain on first helix")
    if _overlaps(d1.helix_id, d1.direction, d1_lo, d1_hi, strand.id, di + 1):
        raise HTTPException(422, detail="Moving crossover would overlap with existing domain on second helix")

    # ── Apply the move ───────────────────────────────────────────────────────
    design_state.snapshot()

    # Update crossover index
    new_crossovers = []
    for xo in design.crossovers:
        if xo.id == body.crossover_id:
            new_crossovers.append(xo.model_copy(update={
                "half_a": xo.half_a.model_copy(update={"index": new_index}),
                "half_b": xo.half_b.model_copy(update={"index": new_index}),
            }))
        else:
            new_crossovers.append(xo)

    # Update domains
    new_domains = list(strand.domains)
    new_domains[di]     = d0.model_copy(update={"end_bp": new_d0_end})
    new_domains[di + 1] = d1.model_copy(update={"start_bp": new_d1_start})
    new_strand = strand.model_copy(update={"domains": new_domains})

    new_strands = [new_strand if s.id == strand.id else s for s in design.strands]

    # Grow helices if the new domain range extends past current helix bounds
    import math as _math
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import Vec3

    new_helices = list(design.helices)
    for idx_h, helix in enumerate(new_helices):
        if helix.id not in (d0.helix_id, d1.helix_id):
            continue
        check_lo = d0_lo if helix.id == d0.helix_id else d1_lo
        check_hi = d0_hi if helix.id == d0.helix_id else d1_hi
        helix_end_bp = helix.bp_start + helix.length_bp - 1

        if check_lo >= helix.bp_start and check_hi <= helix_end_bp:
            continue  # within bounds

        ax, bx = helix.axis_start, helix.axis_end
        dx = bx.x - ax.x; dy = bx.y - ax.y; dz = bx.z - ax.z
        length_nm = _math.sqrt(dx*dx + dy*dy + dz*dz)
        if length_nm < 1e-9:
            ux = uy = 0.0; uz = 1.0
        else:
            ux = dx / length_nm; uy = dy / length_nm; uz = dz / length_nm

        new_bp_start  = helix.bp_start
        new_length_bp = helix.length_bp
        new_axis_start = ax
        new_phase      = helix.phase_offset

        if check_lo < helix.bp_start:
            extra = helix.bp_start - check_lo
            new_axis_start = Vec3(
                x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                z=ax.z - extra * BDNA_RISE_PER_BP * uz,
            )
            new_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
            new_bp_start  = check_lo
            new_length_bp += extra

        new_axis_end = helix.axis_end
        if check_hi > helix_end_bp:
            extra = check_hi - helix_end_bp
            new_axis_end = Vec3(
                x=bx.x + extra * BDNA_RISE_PER_BP * ux,
                y=bx.y + extra * BDNA_RISE_PER_BP * uy,
                z=bx.z + extra * BDNA_RISE_PER_BP * uz,
            )
            new_length_bp += extra

        from backend.core.models import Helix
        new_helices[idx_h] = Helix(
            id=helix.id,
            axis_start=new_axis_start,
            axis_end=new_axis_end,
            length_bp=new_length_bp,
            bp_start=new_bp_start,
            phase_offset=new_phase,
            twist_per_bp_rad=helix.twist_per_bp_rad,
            grid_pos=helix.grid_pos,
            loop_skips=helix.loop_skips,
        )

    updated = design.copy_with(
        crossovers=new_crossovers,
        strands=new_strands,
        helices=new_helices,
    )
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    changed_helix_ids = list({d0.helix_id, d1.helix_id})
    return _design_response_with_geometry(updated, report, changed_helix_ids=changed_helix_ids)


@router.post("/design/crossovers/batch-move", status_code=200)
def batch_move_crossovers(body: BatchMoveCrossoversRequest) -> dict:
    """Move multiple crossovers to new bp indices in a single atomic operation.

    Each entry specifies a crossover_id and new_index.  All moves are applied
    sequentially on the same design snapshot so they share a single undo step.
    Validation (lattice position, occupancy, overlap) is checked for each move
    against the state that includes prior moves in the batch.
    """
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.validator import validate_design
    import math as _math
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import Vec3, Helix

    design = design_state.get_or_404()

    # Filter out no-ops
    moves = []
    for m in body.moves:
        xover = next((x for x in design.crossovers if x.id == m.crossover_id), None)
        if xover is None:
            raise HTTPException(404, detail=f"Crossover {m.crossover_id!r} not found.")
        if m.new_index != xover.half_a.index:
            moves.append(m)

    if not moves:
        report = validate_design(design)
        return _design_response_with_geometry(design, report)

    # Build a map of crossover_id → new_index for all moves in this batch
    move_ids = {m.crossover_id for m in moves}
    changed_helix_ids: set[str] = set()

    # ── Phase 1: Validate all moves against current design state ─────────
    # Collect move info from current state before any mutations
    move_infos = []  # list of (xover, new_index, strand, di, d0, d1)
    helix_map = {h.id: h for h in design.helices}

    for m in moves:
        xover = next((x for x in design.crossovers if x.id == m.crossover_id), None)
        if xover is None:
            raise HTTPException(404, detail=f"Crossover {m.crossover_id!r} not found.")

        old_index = xover.half_a.index
        new_index = m.new_index

        # Validate lattice position
        h_a = helix_map.get(xover.half_a.helix_id)
        h_b = helix_map.get(xover.half_b.helix_id)
        if h_a is None or h_b is None or h_a.grid_pos is None or h_b.grid_pos is None:
            raise HTTPException(422, detail="Crossover helices missing or have no grid_pos")

        valid = False
        for is_scaf in (False, True):
            eb = crossover_neighbor(design.lattice_type, *h_a.grid_pos, new_index, is_scaffold=is_scaf)
            ea = crossover_neighbor(design.lattice_type, *h_b.grid_pos, new_index, is_scaffold=is_scaf)
            if (eb is not None and eb == tuple(h_b.grid_pos)) or \
               (ea is not None and ea == tuple(h_a.grid_pos)):
                valid = True
                break
        if not valid:
            raise HTTPException(422, detail=f"Index {new_index} is not a valid crossover site")

        # Check occupancy — skip crossovers that are also being moved in this batch
        for xo in design.crossovers:
            if xo.id == m.crossover_id or xo.id in move_ids:
                continue
            for half in (xo.half_a, xo.half_b):
                if half.helix_id == xover.half_a.helix_id and \
                   half.index == new_index and half.strand == xover.half_a.strand:
                    raise HTTPException(422, detail=f"Position {new_index} already occupied")
                if half.helix_id == xover.half_b.helix_id and \
                   half.index == new_index and half.strand == xover.half_b.strand:
                    raise HTTPException(422, detail=f"Position {new_index} already occupied")

        # Find adjacent domains
        found = None
        for ha_half, hb_half in [(xover.half_a, xover.half_b), (xover.half_b, xover.half_a)]:
            if found:
                break
            for strand in design.strands:
                if found:
                    break
                for di in range(len(strand.domains) - 1):
                    d0 = strand.domains[di]
                    d1 = strand.domains[di + 1]
                    if d0.helix_id == ha_half.helix_id and d0.direction == ha_half.strand \
                            and d0.end_bp == old_index \
                            and d1.helix_id == hb_half.helix_id and d1.direction == hb_half.strand \
                            and d1.start_bp == old_index:
                        found = (strand, di, d0, d1)
                        break

        if found is None:
            raise HTTPException(422, detail="Could not find adjacent domains for crossover")

        move_infos.append((xover, new_index, *found))

    # ── Phase 2: Apply all moves atomically ──────────────────────────────
    def _apply(d: "Design") -> None:
        nonlocal changed_helix_ids

        # Update crossover indices
        xover_updates = {m.crossover_id: m.new_index for m in moves}
        for i, xo in enumerate(d.crossovers):
            if xo.id in xover_updates:
                ni = xover_updates[xo.id]
                d.crossovers[i] = xo.model_copy(update={
                    "half_a": xo.half_a.model_copy(update={"index": ni}),
                    "half_b": xo.half_b.model_copy(update={"index": ni}),
                })

        # Update domains — group edits by strand to handle multiple moves on same strand
        strand_dom_edits: dict[str, list[tuple[int, int]]] = {}
        for xover, new_index, strand, di, d0, d1 in move_infos:
            strand_dom_edits.setdefault(strand.id, []).append((di, new_index))
            changed_helix_ids.update({d0.helix_id, d1.helix_id})

        for si, s in enumerate(d.strands):
            if s.id not in strand_dom_edits:
                continue
            new_doms = list(s.domains)
            for di, new_index in strand_dom_edits[s.id]:
                new_doms[di]     = new_doms[di].model_copy(update={"end_bp": new_index})
                new_doms[di + 1] = new_doms[di + 1].model_copy(update={"start_bp": new_index})
            d.strands[si] = s.model_copy(update={"domains": new_doms})

        # Grow helices if needed
        for _, new_index, strand, di, d0, d1 in move_infos:
            d0_lo = min(d0.start_bp, new_index)
            d0_hi = max(d0.start_bp, new_index)
            d1_lo = min(new_index, d1.end_bp)
            d1_hi = max(new_index, d1.end_bp)

            for idx_h, helix in enumerate(d.helices):
                if helix.id not in (d0.helix_id, d1.helix_id):
                    continue
                check_lo = d0_lo if helix.id == d0.helix_id else d1_lo
                check_hi = d0_hi if helix.id == d0.helix_id else d1_hi
                helix_end_bp = helix.bp_start + helix.length_bp - 1
                if check_lo >= helix.bp_start and check_hi <= helix_end_bp:
                    continue

                ax, bx = helix.axis_start, helix.axis_end
                dx = bx.x - ax.x; dy = bx.y - ax.y; dz = bx.z - ax.z
                length_nm = _math.sqrt(dx*dx + dy*dy + dz*dz)
                if length_nm < 1e-9:
                    ux = uy = 0.0; uz = 1.0
                else:
                    ux = dx / length_nm; uy = dy / length_nm; uz = dz / length_nm

                new_bp_start  = helix.bp_start
                new_length_bp = helix.length_bp
                new_axis_start = ax
                new_phase      = helix.phase_offset
                new_axis_end   = helix.axis_end

                if check_lo < helix.bp_start:
                    extra = helix.bp_start - check_lo
                    new_axis_start = Vec3(
                        x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                        y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                        z=ax.z - extra * BDNA_RISE_PER_BP * uz,
                    )
                    new_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
                    new_bp_start  = check_lo
                    new_length_bp += extra
                if check_hi > helix_end_bp:
                    extra = check_hi - helix_end_bp
                    new_axis_end = Vec3(
                        x=bx.x + extra * BDNA_RISE_PER_BP * ux,
                        y=bx.y + extra * BDNA_RISE_PER_BP * uy,
                        z=bx.z + extra * BDNA_RISE_PER_BP * uz,
                    )
                    new_length_bp += extra

                d.helices[idx_h] = Helix(
                    id=helix.id,
                    axis_start=new_axis_start,
                    axis_end=new_axis_end,
                    length_bp=new_length_bp,
                    bp_start=new_bp_start,
                    phase_offset=new_phase,
                    twist_per_bp_rad=helix.twist_per_bp_rad,
                    grid_pos=helix.grid_pos,
                    loop_skips=helix.loop_skips,
                )

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report, changed_helix_ids=list(changed_helix_ids))


@router.delete("/design/crossovers/{crossover_id}", status_code=200)
def delete_crossover(crossover_id: str) -> dict:
    """Remove a crossover by ID.

    If the crossover joins two domains within a multi-domain strand, the
    strand is split back into two single-helix fragments (desplice).
    """
    design = design_state.get_or_404()
    xover = next((x for x in design.crossovers if x.id == crossover_id), None)
    if xover is None:
        raise HTTPException(404, detail=f"Crossover {crossover_id!r} not found.")

    new_strands = _desplice_strands_for_crossover(design, xover.half_a, xover.half_b)

    def _apply(d: Design) -> None:
        d.crossovers = [x for x in d.crossovers if x.id != crossover_id]
        d.strands = new_strands

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


@router.post("/design/crossovers/batch-delete", status_code=200)
def batch_delete_crossovers(body: BatchDeleteCrossoversRequest) -> dict:
    """Remove multiple crossovers in a single atomic operation.

    Each crossover is despliced (strand split) in sequence on the same design
    snapshot, then validated and geometry-recomputed once at the end.
    """
    design = design_state.get_or_404()
    ids_to_delete = set(body.crossover_ids)
    if not ids_to_delete:
        report = validate_design(design)
        return _design_response_with_geometry(design, report)

    existing_ids = {x.id for x in design.crossovers}
    missing = ids_to_delete - existing_ids
    if missing:
        raise HTTPException(404, detail=f"Crossovers not found: {sorted(missing)}")

    def _apply(d: "Design") -> None:
        for xo in list(d.crossovers):
            if xo.id not in ids_to_delete:
                continue
            d.strands = _desplice_strands_for_crossover(d, xo.half_a, xo.half_b)
        d.crossovers = [x for x in d.crossovers if x.id not in ids_to_delete]

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


_EXTRA_BASES_RE = __import__("re").compile(r"^[ACGTNacgtn]*$")


@router.patch("/design/crossovers/extra-bases/batch", status_code=200)
def batch_patch_crossover_extra_bases(body: BatchCrossoverExtraBasesRequest) -> dict:
    """Set (or clear) extra bases on multiple crossovers in a single atomic operation.

    Each entry must have a valid crossover_id and a sequence matching [ACGTNacgtn]*.
    An empty sequence clears extra_bases for that crossover.
    All sequences are validated before any mutations are applied.
    """
    design = design_state.get_or_404()

    for entry in body.entries:
        if not _EXTRA_BASES_RE.match(entry.sequence):
            raise HTTPException(
                422,
                detail=f"Sequence {entry.sequence!r} for crossover {entry.crossover_id!r} "
                       f"contains invalid bases. Only A, T, G, C, N are allowed.",
            )

    id_to_seq: dict[str, str] = {e.crossover_id: e.sequence.upper() for e in body.entries}
    missing = [cid for cid in id_to_seq if not any(x.id == cid for x in design.crossovers)]
    if missing:
        raise HTTPException(404, detail=f"Crossovers not found: {missing}")

    def _apply(d: "Design") -> None:
        for xo in d.crossovers:
            if xo.id in id_to_seq:
                seq = id_to_seq[xo.id]
                xo.extra_bases = seq if seq else None

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


@router.patch("/design/crossovers/{crossover_id}/extra-bases", status_code=200)
def patch_crossover_extra_bases(crossover_id: str, body: CrossoverExtraBasesRequest) -> dict:
    """Set (or clear) extra bases on a single crossover.

    sequence must match [ACGTNacgtn]*.  Pass an empty string to remove extra bases.
    """
    if not _EXTRA_BASES_RE.match(body.sequence):
        raise HTTPException(
            422,
            detail=f"Sequence {body.sequence!r} contains invalid bases. "
                   f"Only A, T, G, C, N are allowed.",
        )

    design = design_state.get_or_404()
    xover = next((x for x in design.crossovers if x.id == crossover_id), None)
    if xover is None:
        raise HTTPException(404, detail=f"Crossover {crossover_id!r} not found.")

    seq = body.sequence.upper()

    def _apply(d: "Design") -> None:
        for xo in d.crossovers:
            if xo.id == crossover_id:
                xo.extra_bases = seq if seq else None
                break

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


@router.post("/design/nick", status_code=201)
def add_nick(body: NickRequest) -> dict:
    """Create a nick (strand break) at the 3′ side of the specified nucleotide.

    The strand covering (helix_id, bp_index, direction) is split: bp_index
    becomes the 3′ end of the left fragment; the next nucleotide in 5′→3′ order
    becomes the 5′ end of the right fragment.

    Raises 400 if bp_index is the 3′ terminus of the strand (nothing to split).
    """
    from backend.core.lattice import _find_strand_at, make_nick
    from backend.core.validator import validate_design

    design = design_state.get_or_404()

    # Identify all helices belonging to the nicked strand BEFORE the nick.
    # A nick at a crossover boundary splits the strand across helices, so the
    # partial geometry response must include every helix whose nucleotides
    # change strand_id — not just the helix where the nick is placed.
    try:
        nicked_strand, _ = _find_strand_at(design, body.helix_id, body.bp_index, body.direction)
    except ValueError:
        nicked_strand = None
    changed_hids = list({dom.helix_id for dom in nicked_strand.domains}) if nicked_strand else [body.helix_id]

    try:
        updated = make_nick(design, body.helix_id, body.bp_index, body.direction)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    # Assign palette color to only the newly created strand(s) — do NOT touch
    # existing strands, which the 3D view already colors by geometry order.
    original_ids = {s.id for s in design.strands}
    original_staple_count = sum(1 for s in design.strands if s.strand_type == StrandType.STAPLE)
    palette_idx = original_staple_count
    new_strands_list = []
    any_colored = False
    for s in updated.strands:
        if (s.id not in original_ids
                and s.strand_type == StrandType.STAPLE
                and s.color is None):
            new_strands_list.append(s.model_copy(update={"color": STAPLE_PALETTE[palette_idx % len(STAPLE_PALETTE)]}))
            palette_idx += 1
            any_colored = True
        else:
            new_strands_list.append(s)
    if any_colored:
        updated = updated.model_copy(update={"strands": new_strands_list})
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report, changed_helix_ids=changed_hids)


@router.post("/design/ligate", status_code=200)
def ligate_strand(body: NickRequest) -> dict:
    """Repair a nick (ligate) by merging the two strand ends adjacent to the nick.

    Uses the same request shape as POST /design/nick.  body.bp_index is the 3′ end
    bp of the left fragment (identical convention to make_nick).

    Finds strand A (3′ end at bp_index) and strand B (5′ end at the adjacent bp),
    then merges them into a single strand.  The two terminal domains — which are
    adjacent on the same helix with the same direction — are collapsed into one.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()

    helix_id  = body.helix_id
    bp_index  = body.bp_index
    direction = body.direction
    adj_bp    = bp_index + 1 if direction == Direction.FORWARD else bp_index - 1

    # ── Same-strand domain merge ─────────────────────────────────────────────
    # If a single strand has two adjacent domains at this boundary (e.g. from
    # a forced ligation), merge them — this is the inverse of a nick.
    for s in design.strands:
        for di in range(len(s.domains) - 1):
            d_left  = s.domains[di]
            d_right = s.domains[di + 1]
            if (d_left.helix_id == helix_id and d_left.direction == direction
                    and d_left.end_bp == bp_index
                    and d_right.helix_id == helix_id and d_right.direction == direction
                    and d_right.start_bp == adj_bp):
                merged_dom = Domain(
                    helix_id  = helix_id,
                    start_bp  = d_left.start_bp,
                    end_bp    = d_right.end_bp,
                    direction = direction,
                )
                new_domains = (
                    list(s.domains[:di])
                    + [merged_dom]
                    + list(s.domains[di + 2:])
                )
                patched = s.model_copy(update={
                    "domains": new_domains, "sequence": None,
                })

                def _apply_merge(d: Design, *, sid=s.id, p=patched) -> None:
                    d.strands = [p if st.id == sid else st for st in d.strands]

                design, report = design_state.mutate_and_validate(_apply_merge)
                return _design_response(design, report)

    # ── Cross-strand ligation ────────────────────────────────────────────────
    # Find strand A: 3′ terminus at bp_index
    strand_a: Strand | None = None
    idx_a: int = -1
    for i, s in enumerate(design.strands):
        last = s.domains[-1]
        if (last.helix_id == helix_id and last.direction == direction
                and last.end_bp == bp_index):
            strand_a = s; idx_a = i; break
    if strand_a is None:
        raise HTTPException(404, detail=(
            f"No strand has a 3′ end at helix={helix_id!r} bp={bp_index} "
            f"direction={direction.value}."
        ))

    # Find strand B: 5′ terminus at adj_bp
    strand_b: Strand | None = None
    for s in design.strands:
        first = s.domains[0]
        if (first.helix_id == helix_id and first.direction == direction
                and first.start_bp == adj_bp):
            strand_b = s; break
    if strand_b is None:
        raise HTTPException(404, detail=(
            f"No strand has a 5′ end at helix={helix_id!r} bp={adj_bp} "
            f"direction={direction.value}."
        ))
    if strand_b.id == strand_a.id:
        raise HTTPException(409, detail="Cannot ligate a strand to itself.")

    # Merge the two touching domains into one, combine domain lists
    dom_a_last  = strand_a.domains[-1]
    dom_b_first = strand_b.domains[0]
    merged_dom  = Domain(
        helix_id  = helix_id,
        start_bp  = dom_a_last.start_bp,
        end_bp    = dom_b_first.end_bp,
        direction = direction,
    )
    merged_domains = (
        list(strand_a.domains[:-1])
        + [merged_dom]
        + list(strand_b.domains[1:])
    )

    merged_strand = Strand(
        id          = strand_a.id,
        domains     = merged_domains,
        strand_type = strand_a.strand_type,
        color       = strand_a.color,
        sequence    = None,   # topology changed — clear sequence
    )

    def _apply(d: Design) -> None:
        new_strands = []
        for s in d.strands:
            if s.id == strand_b.id:
                continue            # drop strand B (absorbed into A)
            elif s.id == strand_a.id:
                new_strands.append(merged_strand)   # replace A with merged
            else:
                new_strands.append(s)
        d.strands = new_strands

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response(design, report)


# ── Forced ligation (manual pencil-tool only — NOT for autocrossover) ────────


class ForcedLigationRequest(BaseModel):
    """Connect any 3' end to any 5' end, bypassing crossover lookup tables.

    This is a manual user action only (pencil tool).  It must never be called
    by autocrossover, autobreak, or any automated pipeline.
    """
    three_prime_strand_id: str   # strand whose 3' end we connect FROM
    five_prime_strand_id: str    # strand whose 5' end we connect TO


@router.post("/design/forced-ligation", status_code=201)
def forced_ligation(body: ForcedLigationRequest) -> dict:
    """Ligate two strands by connecting the 3' end of one to the 5' end of
    another, regardless of helix adjacency or crossover lookup tables.

    Manual user feature only — must NOT be used by autocrossover or any
    automated pipeline.

    The result is a single multi-domain strand.  No Crossover record is
    created because this connection is not at a canonical crossover site.
    """
    from backend.core.lattice import _ligate
    from backend.core.validator import validate_design

    design = design_state.get_or_404()

    strand_a: Strand | None = None
    strand_b: Strand | None = None
    for s in design.strands:
        if s.id == body.three_prime_strand_id:
            strand_a = s
        if s.id == body.five_prime_strand_id:
            strand_b = s
    if strand_a is None:
        raise HTTPException(404, detail=f"3' strand {body.three_prime_strand_id!r} not found.")
    if strand_b is None:
        raise HTTPException(404, detail=f"5' strand {body.five_prime_strand_id!r} not found.")
    if strand_a.id == strand_b.id:
        raise HTTPException(409, detail="Cannot ligate a strand to itself (would create circular strand).")

    # Single undo checkpoint
    design_state.snapshot()

    # Record the forced ligation endpoints before _ligate merges domains.
    from backend.core.models import ForcedLigation
    three_dom = strand_a.domains[-1]
    five_dom = strand_b.domains[0]
    fl = ForcedLigation(
        three_prime_helix_id=three_dom.helix_id,
        three_prime_bp=three_dom.end_bp,
        three_prime_direction=three_dom.direction,
        five_prime_helix_id=five_dom.helix_id,
        five_prime_bp=five_dom.start_bp,
        five_prime_direction=five_dom.direction,
    )

    current = _ligate(design, strand_a, strand_b)
    current = current.model_copy(update={
        "forced_ligations": list(current.forced_ligations) + [fl],
    })

    design_state.set_design_silent(current)
    report = validate_design(current)
    return _design_response_with_geometry(current, report)


@router.delete("/design/forced-ligations/{fl_id}", status_code=200)
def delete_forced_ligation(fl_id: str) -> dict:
    """Remove a forced ligation by ID.

    Splits the strand at the forced-ligation junction back into two fragments
    and removes the ForcedLigation record from the design.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    fl = next((f for f in design.forced_ligations if f.id == fl_id), None)
    if fl is None:
        raise HTTPException(404, detail=f"Forced ligation {fl_id!r} not found.")

    # Find the strand containing the junction and split it.
    new_strands = list(design.strands)
    for strand in design.strands:
        for di in range(len(strand.domains) - 1):
            d0 = strand.domains[di]
            d1 = strand.domains[di + 1]
            if (d0.helix_id == fl.three_prime_helix_id
                    and d0.end_bp == fl.three_prime_bp
                    and d0.direction == fl.three_prime_direction
                    and d1.helix_id == fl.five_prime_helix_id
                    and d1.start_bp == fl.five_prime_bp
                    and d1.direction == fl.five_prime_direction):
                part_a = strand.model_copy(update={"domains": list(strand.domains[:di + 1])})
                part_b = Strand(
                    domains=list(strand.domains[di + 1:]),
                    strand_type=strand.strand_type,
                )
                new_strands = [s for s in design.strands if s.id != strand.id]
                if part_a.domains:
                    new_strands.append(part_a)
                if part_b.domains:
                    new_strands.append(part_b)
                break
        else:
            continue
        break

    def _apply(d: Design) -> None:
        d.forced_ligations = [f for f in d.forced_ligations if f.id != fl_id]
        d.strands = new_strands

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


class BatchDeleteForcedLigationsRequest(BaseModel):
    forced_ligation_ids: list[str]


@router.post("/design/forced-ligations/batch-delete", status_code=200)
def batch_delete_forced_ligations(body: BatchDeleteForcedLigationsRequest) -> dict:
    """Remove multiple forced ligations in a single atomic operation."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    ids_to_delete = set(body.forced_ligation_ids)
    if not ids_to_delete:
        report = validate_design(design)
        return _design_response_with_geometry(design, report)

    existing_ids = {f.id for f in design.forced_ligations}
    missing = ids_to_delete - existing_ids
    if missing:
        raise HTTPException(404, detail=f"Forced ligations not found: {sorted(missing)}")

    def _apply(d: "Design") -> None:
        for fl in list(d.forced_ligations):
            if fl.id not in ids_to_delete:
                continue
            # Split the strand at this junction
            for strand in list(d.strands):
                found = False
                for di in range(len(strand.domains) - 1):
                    d0 = strand.domains[di]
                    d1 = strand.domains[di + 1]
                    if (d0.helix_id == fl.three_prime_helix_id
                            and d0.end_bp == fl.three_prime_bp
                            and d0.direction == fl.three_prime_direction
                            and d1.helix_id == fl.five_prime_helix_id
                            and d1.start_bp == fl.five_prime_bp
                            and d1.direction == fl.five_prime_direction):
                        part_a = strand.model_copy(
                            update={"domains": list(strand.domains[:di + 1])})
                        part_b = Strand(
                            domains=list(strand.domains[di + 1:]),
                            strand_type=strand.strand_type,
                        )
                        d.strands = [s for s in d.strands if s.id != strand.id]
                        if part_a.domains:
                            d.strands.append(part_a)
                        if part_b.domains:
                            d.strands.append(part_b)
                        found = True
                        break
                if found:
                    break
        d.forced_ligations = [f for f in d.forced_ligations if f.id not in ids_to_delete]

    design, report = design_state.mutate_and_validate(_apply)
    return _design_response_with_geometry(design, report)


@router.post("/design/nick/batch", status_code=201)
def add_nick_batch(body: NickBatchRequest) -> dict:
    """Nick at multiple positions in one operation."""
    from backend.core.lattice import _find_strand_at, make_nick
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    all_changed: set[str] = set()

    for nick in body.nicks:
        # Collect all helix IDs from the strand being nicked (not just the
        # nick helix) so that cross-helix strand splits update all affected nucs.
        try:
            nicked_strand, _ = _find_strand_at(current, nick.helix_id, nick.bp_index, nick.direction)
            all_changed.update(dom.helix_id for dom in nicked_strand.domains)
        except ValueError:
            all_changed.add(nick.helix_id)
        try:
            current = make_nick(current, nick.helix_id, nick.bp_index, nick.direction)
        except ValueError:
            continue

    design_state.set_design(current)
    report = validate_design(current)
    changed_helix_ids = list(all_changed) if all_changed else None
    return _design_response_with_geometry(current, report, changed_helix_ids=changed_helix_ids)


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
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class BulkColorRequest(BaseModel):
    strand_ids: list[str]
    color: str | None = None   # "#RRGGBB" hex string, or None to reset to palette


@router.patch("/design/strands/colors", status_code=200)
def patch_strands_color(body: BulkColorRequest) -> dict:
    """Apply the same color to multiple strands atomically in one undo step."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    id_set = set(body.strand_ids)
    missing = id_set - {s.id for s in design.strands}
    if missing:
        raise HTTPException(404, detail=f"Strand(s) not found: {sorted(missing)}")
    new_strands = [
        s.model_copy(update={"color": body.color}) if s.id in id_set else s
        for s in design.strands
    ]
    updated = design.model_copy(update={"strands": new_strands})
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class AutoScaffoldRequest(BaseModel):
    min_staple_margin: int = 3   # min bp gap between crossover and any staple end


@router.post("/design/auto-scaffold", status_code=200)
def run_auto_scaffold(body: AutoScaffoldRequest = AutoScaffoldRequest()) -> dict:
    """Route a single continuous scaffold strand via L/M/R crossover pattern.

    Creates ss-loop crossovers on both left and right ends (L/R pairs) and standard
    DX crossovers near the midpoint of each interior helix pair (M pairs), producing
    one scaffold strand with two open termini.

    Returns 422 if routing fails (e.g. no Hamiltonian path or no valid crossover positions).
    """
    from backend.core.lattice import auto_scaffold_basic
    from backend.core.validator import validate_design
    from fastapi import HTTPException

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = auto_scaffold_basic(
            design,
            min_staple_margin=body.min_staple_margin,
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


@router.post("/design/scaffold-nick", status_code=200)
def scaffold_nick_endpoint(body: ScaffoldNickRequest = ScaffoldNickRequest()) -> dict:
    """Nick the scaffold on the first helix (by sorted ID) at *nick_offset* bp from the near end.

    For FORWARD helices: scaffold 5′ is placed at bp *nick_offset*.
    For REVERSE helices: a *nick_offset*-bp single-stranded near loop is left at the blunt end.
    """
    from backend.core.lattice import reconcile_all_inline_overhangs, scaffold_nick
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_nick(design, nick_offset=body.nick_offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/scaffold-extrude-near", status_code=200)
def scaffold_extrude_near_endpoint(body: ScaffoldExtrudeRequest = ScaffoldExtrudeRequest()) -> dict:
    """Extend all near-end helices backward by *length_bp* bp, scaffold strands only.

    Uses in-place backward extension so existing bp indices shift up by *length_bp*.
    Staple strands are not modified.
    """
    from backend.core.lattice import reconcile_all_inline_overhangs, scaffold_extrude_near
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_extrude_near(design, length_bp=body.length_bp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.post("/design/scaffold-extrude-far", status_code=200)
def scaffold_extrude_far_endpoint(body: ScaffoldExtrudeRequest = ScaffoldExtrudeRequest()) -> dict:
    """Extend all far-end helices forward by *length_bp* bp, scaffold strands only.

    Uses in-place forward extension so existing bp indices are unchanged.
    Staple strands are not modified.
    """
    from backend.core.lattice import reconcile_all_inline_overhangs, scaffold_extrude_far
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_extrude_far(design, length_bp=body.length_bp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
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
    changed_helix_ids = list({e.helix_id for e in body.entries})
    return _design_response_with_geometry(updated, report, changed_helix_ids=changed_helix_ids)


# ── Advanced scaffold routing endpoints ───────────────────────────────────────


class SeamlessScaffoldRequest(BaseModel):
    min_staple_margin: int = 3


@router.post("/design/auto-scaffold-seamless", status_code=200)
def auto_scaffold_seamless_endpoint(
    body: SeamlessScaffoldRequest = SeamlessScaffoldRequest(),
) -> dict:
    """Route scaffold with seamless (no-seam) crossovers — Phase 1: left-side only.

    Resets scaffold to per-helix full-span strands, then connects adjacent helix
    pairs via crossovers on the low-bp (left) side.  Each scaffold strand gets at
    most one crossover on this side.

    Returns 422 if no valid crossover positions exist (e.g. single isolated helix).
    """
    from backend.core.lattice import auto_scaffold_seamless, reconcile_all_inline_overhangs
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = auto_scaffold_seamless(
            design,
            min_staple_margin=body.min_staple_margin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class PartitionScaffoldRequest(BaseModel):
    helix_groups: list[list[str]]
    mode: str = "end_to_end"
    nick_offset: int = 7
    min_end_margin: int = 9


@router.post("/design/partition-scaffold", status_code=200)
def partition_scaffold_endpoint(body: PartitionScaffoldRequest) -> dict:
    """Route independent scaffold strands for each specified group of helices.

    Each group is auto-scaffolded independently.  Groups must be disjoint.
    Returns 422 if any helix ID is unrecognised or groups overlap.
    """
    from backend.core.lattice import auto_scaffold_partition, reconcile_all_inline_overhangs
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = auto_scaffold_partition(
            design,
            helix_groups=body.helix_groups,
            mode=body.mode,
            nick_offset=body.nick_offset,
            min_end_margin=body.min_end_margin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class JointedScaffoldRequest(BaseModel):
    mode: str = "end_to_end"
    nick_offset: int = 7
    min_end_margin: int = 9


@router.post("/design/jointed-scaffold", status_code=200)
def jointed_scaffold_endpoint(
    body: JointedScaffoldRequest = JointedScaffoldRequest(),
) -> dict:
    """Route scaffold for jointed/hinge designs while preserving manually-placed cross-arm strands.

    Identifies scaffold strands whose domains span disconnected helix groups (cross-arm
    fixed strands) and preserves them.  Routes the remaining free helices within each
    arm independently.  Where a newly routed arm scaffold endpoint co-locates (same bp)
    on an XY-adjacent helix to a fixed strand endpoint, the two are automatically ligated.

    Returns 422 if routing fails for any arm.
    """
    from backend.core.lattice import auto_scaffold_jointed, reconcile_all_inline_overhangs
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = auto_scaffold_jointed(
            design,
            mode=body.mode,
            nick_offset=body.nick_offset,
            min_end_margin=body.min_end_margin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


class ScaffoldSplitRequest(BaseModel):
    strand_id: str
    helix_id: str
    bp_position: int


@router.post("/design/scaffold-split", status_code=200)
def scaffold_split_endpoint(body: ScaffoldSplitRequest) -> dict:
    """Split a scaffold strand into two by placing a nick at the given bp position.

    Both resulting strands retain scaffold type.
    Returns 422 if the strand is not a scaffold or the position is invalid.
    """
    from backend.core.lattice import reconcile_all_inline_overhangs, scaffold_split
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    design_state.snapshot()
    try:
        updated = scaffold_split(
            design,
            strand_id=body.strand_id,
            helix_id=body.helix_id,
            bp_position=body.bp_position,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated = reconcile_all_inline_overhangs(updated)
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


# ── Sequence assignment endpoints ─────────────────────────────────────────────


class _ScaffoldSeqBody(BaseModel):
    scaffold_name: str = "M13mp18"
    custom_sequence: Optional[str] = None  # if set, overrides scaffold_name
    strand_id: Optional[str] = None        # target strand (multi-scaffold support)


@router.post("/design/assign-scaffold-sequence", status_code=200)
def assign_scaffold_sequence_endpoint(body: _ScaffoldSeqBody = _ScaffoldSeqBody()) -> dict:
    """Assign a scaffold sequence to a scaffold strand.

    Body fields:
    - ``scaffold_name``: one of "M13mp18", "p7560", "p8064" (default: M13mp18).
    - ``custom_sequence``: raw ATGCN string; when non-empty overrides scaffold_name.
    - ``strand_id``: target a specific scaffold strand (for multi-scaffold designs).

    The response includes ``total_nt``, ``scaffold_len``, and ``padded_nt``.
    """
    from backend.core.sequences import (
        SCAFFOLD_LIBRARY,
        assign_custom_scaffold_sequence,
        assign_scaffold_sequence,
    )
    from backend.core.validator import validate_design
    from fastapi import HTTPException

    design = design_state.get_or_404()
    design_state.snapshot()
    use_custom = bool(body.custom_sequence and body.custom_sequence.strip())
    try:
        if use_custom:
            updated, total_nt, padded_nt = assign_custom_scaffold_sequence(
                design, body.custom_sequence, strand_id=body.strand_id
            )
            scaffold_len = len(body.custom_sequence.strip().upper().replace(" ", "").replace("\n", "").replace("\r", ""))
        else:
            updated, total_nt, padded_nt = assign_scaffold_sequence(
                design, body.scaffold_name, strand_id=body.strand_id
            )
            scaffold_len = next(
                (ln for name, ln, _ in SCAFFOLD_LIBRARY if name == body.scaffold_name), 0
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    design_state.set_design_silent(updated)
    report = validate_design(updated)
    resp = _design_response(updated, report)
    resp["total_nt"]     = total_nt
    resp["scaffold_len"] = scaffold_len
    resp["padded_nt"]    = padded_nt
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

    # If the deleted entry was a cluster_op and the cluster has no remaining ops
    # in new_log, _seek_feature_log won't know to reset it (the cluster won't appear
    # in clusters_with_ops).  Pre-reset the transform here so the seek sees identity.
    if entry.feature_type == 'cluster_op':
        still_has_ops = any(
            e.feature_type == 'cluster_op' and e.cluster_id == entry.cluster_id
            for e in new_log
        )
        if not still_has_ops:
            new_cts = [
                ct.model_copy(update={'translation': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0, 1.0]})
                if ct.id == entry.cluster_id else ct
                for ct in temp.cluster_transforms
            ]
            temp = temp.copy_with(cluster_transforms=new_cts)

    updated = _seek_feature_log(temp, new_cursor)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


def _rebase_joints_to_cts(design: "Design", new_cts: list) -> list:
    """Return a new cluster_joints list with axis_origin/axis_direction recomputed
    so that each joint's world position matches *new_cts* rather than the current
    design.cluster_transforms.

    Formula (same as update_cluster):
        R_delta = R_new @ R_old^-1
        J_new   = R_delta @ (J_old - D_old) + D_new   where D = pivot + T
        dir_new = R_delta @ dir_old
    """
    import numpy as np

    old_ct_map = {ct.id: ct for ct in design.cluster_transforms}
    new_ct_map = {ct.id: ct for ct in new_cts}
    new_joints = list(design.cluster_joints)
    for i, j in enumerate(new_joints):
        old_ct = old_ct_map.get(j.cluster_id)
        new_ct = new_ct_map.get(j.cluster_id)
        if old_ct is None or new_ct is None:
            continue
        pivot   = np.array(old_ct.pivot, dtype=float)
        D_old   = pivot + np.array(old_ct.translation, dtype=float)
        D_new   = pivot + np.array(new_ct.translation, dtype=float)
        R_old   = _rot_from_quaternion(*old_ct.rotation)
        R_new   = _rot_from_quaternion(*new_ct.rotation)
        R_delta = R_new @ R_old.T
        J_old   = np.array(j.axis_origin,   dtype=float)
        d_old   = np.array(j.axis_direction, dtype=float)
        new_joints[i] = j.model_copy(update={
            "axis_origin":    (R_delta @ (J_old - D_old) + D_new).tolist(),
            "axis_direction": (R_delta @ d_old).tolist(),
        })
    return new_joints


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
        # Reset cluster transforms for any cluster that has ops in the log.
        clusters_with_any_op = {e.cluster_id for e in log if e.feature_type == 'cluster_op'}
        new_cts = [
            ct.model_copy(update={'translation': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0, 1.0]})
            if ct.id in clusters_with_any_op else ct
            for ct in design.cluster_transforms
        ]
        new_joints = _rebase_joints_to_cts(design, new_cts)
        return design.copy_with(
            deformations=[], cluster_transforms=new_cts,
            cluster_joints=new_joints, feature_log_cursor=-2,
        )

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

    new_joints = _rebase_joints_to_cts(design, new_cts)
    return design.copy_with(
        deformations=new_deformations,
        cluster_transforms=new_cts,
        cluster_joints=new_joints,
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
    commit: bool = False                         # when True: push to undo stack
    log: bool = False                            # when True (with commit): append to feature_log


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

    old_ct = design.cluster_transforms[idx]
    cts[idx] = cts[idx].model_copy(update=fields)
    updated_ct = cts[idx]

    # Update joint axis_origin / axis_direction when translation or rotation changes.
    # The cluster rigid transform is: p_world = R @ (p_local - pivot) + pivot + T
    # So the "display origin" D = pivot + T. When T or R changes we compute:
    #   D_old = pivot + old_T,  D_new = pivot + new_T
    #   R_delta = R_new @ R_old^-1
    #   J_new   = R_delta @ (J_old - D_old) + D_new
    #   dir_new = R_delta @ dir_old
    updated_joints = list(design.cluster_joints)
    if (body.translation is not None or body.rotation is not None) and body.commit:
        import numpy as np
        pivot   = np.array(old_ct.pivot, dtype=float)
        old_T   = np.array(old_ct.translation, dtype=float)
        new_T   = np.array(updated_ct.translation, dtype=float)
        R_old   = _rot_from_quaternion(*old_ct.rotation)
        R_new   = _rot_from_quaternion(*updated_ct.rotation)
        R_delta = R_new @ R_old.T          # R_old is orthogonal so R_old^-1 = R_old.T
        D_old   = pivot + old_T
        D_new   = pivot + new_T
        for i, j in enumerate(updated_joints):
            if j.cluster_id != cluster_id:
                continue
            J_old   = np.array(j.axis_origin,    dtype=float)
            dir_old = np.array(j.axis_direction,  dtype=float)
            J_new   = R_delta @ (J_old - D_old) + D_new
            dir_new = R_delta @ dir_old
            updated_joints[i] = j.model_copy(update={
                "axis_origin":    J_new.tolist(),
                "axis_direction": dir_new.tolist(),
            })

    if body.commit and body.log:
        # Final tool confirm — push to undo stack and record in feature_log.
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
            cluster_joints=updated_joints,
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )
        design_state.set_design(updated)
    elif body.commit:
        # Drag-end commit — push to undo stack only (no feature_log entry).
        updated = design.copy_with(cluster_transforms=cts, cluster_joints=updated_joints)
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


# ── Cluster joint routes ───────────────────────────────────────────────────────


class AddJointBody(BaseModel):
    axis_origin: List[float]       # [x, y, z] nm world-space
    axis_direction: List[float]    # unit vector (normalised by backend)
    surface_detail: int = 6        # lateral face count used in surface approximation
    name: str = "Joint"


class PatchJointBody(BaseModel):
    axis_origin: Optional[List[float]] = None
    axis_direction: Optional[List[float]] = None
    surface_detail: Optional[int] = None
    name: Optional[str] = None


@router.post("/design/cluster/{cluster_id}/joint", status_code=200)
def add_joint(cluster_id: str, body: AddJointBody) -> dict:
    """Create a revolute joint on a cluster.  Pushes to the undo stack.

    The axis is computed frontend-side (face-normal of the surface approximation)
    and sent here for storage.  The backend normalises axis_direction.
    """
    import math as _math
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    if not any(c.id == cluster_id for c in design.cluster_transforms):
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    # Normalise direction (guard against near-zero vectors)
    dx, dy, dz = body.axis_direction[0], body.axis_direction[1], body.axis_direction[2]
    length = _math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-9:
        raise HTTPException(400, detail="axis_direction must be a non-zero vector.")
    direction = [dx / length, dy / length, dz / length]

    joint = ClusterJoint(
        cluster_id=cluster_id,
        name=body.name,
        axis_origin=list(body.axis_origin),
        axis_direction=direction,
        surface_detail=body.surface_detail,
    )
    # Each cluster has at most one joint — replace any existing one for this cluster.
    existing = [j for j in design.cluster_joints if j.cluster_id != cluster_id]
    updated = design.copy_with(cluster_joints=existing + [joint])
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.patch("/design/joint/{joint_id}", status_code=200)
def update_joint(joint_id: str, body: PatchJointBody) -> dict:
    """Update joint properties.  Pushes to the undo stack."""
    import math as _math
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    joints = list(design.cluster_joints)
    idx = next((i for i, j in enumerate(joints) if j.id == joint_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")

    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.axis_origin is not None:
        fields["axis_origin"] = list(body.axis_origin)
    if body.axis_direction is not None:
        dx, dy, dz = body.axis_direction[0], body.axis_direction[1], body.axis_direction[2]
        length = _math.sqrt(dx * dx + dy * dy + dz * dz)
        if length < 1e-9:
            raise HTTPException(400, detail="axis_direction must be a non-zero vector.")
        fields["axis_direction"] = [dx / length, dy / length, dz / length]
    if body.surface_detail is not None:
        fields["surface_detail"] = body.surface_detail

    joints[idx] = joints[idx].model_copy(update=fields)
    updated = design.copy_with(cluster_joints=joints)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/joint/{joint_id}", status_code=200)
def delete_joint(joint_id: str) -> dict:
    """Delete a joint.  Pushes to the undo stack."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    joints = [j for j in design.cluster_joints if j.id != joint_id]
    if len(joints) == len(design.cluster_joints):
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")

    updated = design.copy_with(cluster_joints=joints)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


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
        updated = design.model_copy(update={"helices": new_helices})
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



@router.post("/design/auto-break", status_code=200)
def auto_break(payload: dict | None = Body(None)) -> dict:
    """Nick all non-scaffold strands at major tick marks (every 7 bp HC / 8 bp SQ),
    producing segments as long as possible without exceeding 60 nt.
    The sandwich rule (no long-short-long domain pattern) overrides the length
    preference.  Apply after auto-crossover.
    Pushed onto the undo stack.
    """
    from backend.core.lattice import make_autobreak, make_nicks_for_autostaple, make_nick
    from backend.core.validator import validate_design
    from backend.core import staple_routing
    from backend.core.sequences import build_scaffold_index_map
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    algo = (payload or {}).get('algorithm', 'basic')
    design_state.snapshot()
    if algo == 'basic':
        # Basic: Stage 2 autostaple nick planner
        updated = make_nicks_for_autostaple(design)
    elif algo == 'advanced':
        # TEMPORARY: Advanced thermodynamic optimizer disabled — too slow,
        # causes timeouts.  Falling back to basic algorithm until perf is fixed.
        updated = make_nicks_for_autostaple(design)
    else:
        # Fallback: original tick-mark autobreak algorithm
        updated = make_autobreak(design)
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
def get_atomistic() -> dict:
    """
    Return the heavy-atom all-atom model for the atomistic Three.js renderer.

    Response: { atoms: [...], bonds: [[i,j], ...], element_meta: {...} }
    Each atom dict contains: serial, name, element, residue, chain_id,
    seq_num, x, y, z (nm), strand_id, helix_id, bp_index, direction,
    is_modified.

    The −32° helical phase offset (aligning the all-atom backbone groove with the
    NADOC CG model) is baked into build_atomistic_model via _ATOMISTIC_PHASE_OFFSET_RAD.
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_to_json, merge_models

    design = design_state.get_or_404()

    pdb_model = design_state.get_pdb_atomistic()

    if pdb_model is not None:
        pdb_helix_ids = {a.helix_id for a in pdb_model.atoms}
        all_helix_ids = {h.id for h in design.helices}
        template_helix_ids = all_helix_ids - pdb_helix_ids

        if not template_helix_ids:
            return atomistic_to_json(pdb_model)

        template_model = build_atomistic_model(design, exclude_helix_ids=pdb_helix_ids)
        return atomistic_to_json(merge_models(pdb_model, template_model))

    return atomistic_to_json(build_atomistic_model(design))


@router.get("/design/surface")
def get_surface(
    color_mode:     str   = "strand",
    grid_spacing:   float = 0.20,
    probe_radius:   float = 0.28,
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

    Response: {
      vertices: [x,y,z, ...],      flat float array, nm coords
      faces:    [i,j,k, ...],      flat int array
      vertex_colors: [r,g,b, ...], flat float 0-1, or null for uniform mode
      stats: { n_verts, n_faces, compute_ms }
    }
    """
    import time
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface, surface_to_json

    design = design_state.get_or_404()
    model = build_atomistic_model(design)

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

    model              = build_atomistic_model(design)
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
