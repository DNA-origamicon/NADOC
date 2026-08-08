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

import base64
import gzip
import math
import os
import re
import time as _time
import uuid as _uuid

import numpy as np
from contextlib import contextmanager
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import Response, ORJSONResponse
from pydantic import BaseModel, ValidationError


# ── Per-request timing trace (Server-Timing header) ──────────────────────────
#
# Lightweight stopwatch used by slow endpoints (seek, geometry) to expose a
# per-step breakdown to the client via the standard ``Server-Timing`` HTTP
# header. The frontend's _request() helper parses and logs the header so the
# user can see exactly where backend wall-clock time is spent without poking
# at the server. Use as:
#     trace = _TimingTrace()
#     with trace.step('seek_log'):
#         ...
#     return trace.attach(ORJSONResponse(payload))
class _TimingTrace:
    __slots__ = ("_steps",)

    def __init__(self) -> None:
        self._steps: list[tuple[str, float]] = []

    @contextmanager
    def step(self, name: str):
        t0 = _time.perf_counter()
        try:
            yield
        finally:
            self._steps.append((name, (_time.perf_counter() - t0) * 1000.0))

    def header_value(self) -> str:
        # Server-Timing format: ``name;dur=<ms>, other;dur=<ms>``.
        # Names must contain only token characters (no spaces / commas).
        parts = []
        for name, dur in self._steps:
            safe = name.replace(" ", "_").replace(",", "_").replace(";", "_")
            parts.append(f"{safe};dur={dur:.1f}")
        return ", ".join(parts)

    def attach(self, response):
        if self._steps:
            response.headers["Server-Timing"] = self.header_value()
        return response


from backend.api import state as design_state
from backend.api.doc_context import should_skip_geometry
from backend.core.geometry import (
    nucleotide_positions,
)
from backend.core.deformation import (
    _apply_ovhg_rotations_to_axes,
    deformed_frame_at_bp,
    deformed_helix_axes,
)
from backend.core.feature_log_edit import (
    FeatureEditError,
    edit_cluster_op_entry,
    edit_deformation_entry,
)
from backend.core.models import (
    ClusterOpLogEntry,
    Crossover,
    DeformationLogEntry,
    Design,
    DesignLoadout,
    DesignMetadata,
    Direction,
    Domain,
    HalfCrossover,
    Helix,
    LatticeType,
    OverhangConnection,
    OverhangBinding,
    ConnectionVersion,
    OverhangSpec,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.constants import STAPLE_PALETTE
from backend.core.validator import ValidationReport

# Cluster auto-detection lives in backend/core (pure topology; carve-up #34).
# Only the two entry points called by crud routes are imported back; the three
# inner phase helpers are module-private to cluster_autodetect (L17).
from backend.core.cluster_autodetect import (  # noqa: F401
    _autodetect_clusters,
    _cluster_bundle_regions,
)

# Per-nucleotide display-geometry kernel lives in backend/core (pure compute;
# carve-up service push #46). Re-exported here under the original underscore
# names so the ~15 cross-file callers that import them from backend.api.crud
# (assembly geometry routes, exporters, feature-log preview, linker_relax, …)
# keep working unchanged.
from backend.core.design_geometry import (  # noqa: F401
    _compact_geometry_for_design,
    _compact_geometry_from_nucleotides,
    _emit_bridge_nucs,
    _geometry_for_design,
    _geometry_for_design_straight,
    _geometry_for_helices,
    _positions_by_helix,
    _positions_for_design,
    _straight_helix_axes,
    _strand_extension_geometry,
    _strand_nucleotide_info,
)

# Render fast-path diff kernel lives in backend/core (pure Design×Design
# comparison; carve-up service push #47). Re-exported here under the original
# underscore names so the response fast-path callers + the test imports
# (`from backend.api.crud import _topology_diff_field`) keep working unchanged.
from backend.core.render_diff import (  # noqa: F401
    _cluster_diff_payload,
    _diff_is_cluster_only,
    _local_changed_helices,
    _strand_occupancy,
    _topology_diff_field,
    _topology_unchanged,
)
from backend.core.overhang_ops import (
    SubDomainTilingError,
    _apply_boundary_hairpin_warnings,
    _check_linker_compatibility,
    _compute_sub_domain_annotations,
    _overhang_end,
    _ovhg_backing_length,
    _ovhg_domain_lengths,
    _replace_ovhg,
    _resolve_sub_domain_sequence,
    _used_overhang_ends,
    validate_sub_domain_tiling,
)

router = APIRouter()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _validation_dict(report: ValidationReport, design: "Design | None" = None) -> dict:
    from backend.core.validator import _is_loop_strand

    loop_ids: list[str] = []
    if design is not None:
        loop_ids = [
            s.id
            for s in design.strands
            if s.strand_type == StrandType.STAPLE and _is_loop_strand(s)
        ]
    return {
        "passed": report.passed,
        "results": [{"ok": r.ok, "message": r.message} for r in report.results],
        "loop_strand_ids": loop_ids,
    }


def _design_for_export() -> Design:
    """Active design with reference geometry stripped, for export/analysis paths.

    Reference strands are excluded from every export (oxDNA / PDB / PSF / NAMD /
    GROMACS / caDNAno / sequence CSV) and from the atomistic model.  Exporters
    are strand-driven — they look up positions from per-helix geometry by slot —
    so removing reference strands cleanly omits their nucleotides without leaving
    dangling records.  Helices/crossovers/overhangs are untouched (a reference
    strand may share a helix with active geometry).
    """
    d = design_state.get_or_404()
    if not any(s.is_reference for s in d.strands):
        return d
    return d.model_copy(update={"strands": d.active_strands()})


def _export_filename_stem(name: str | None, fallback: str = "design") -> str:
    """Return a conservative filename stem for browser download headers."""
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", (name or "").strip())
    stem = stem.strip(" .")
    return stem or fallback


def _ensure_default_cluster(design: Design) -> Design:
    """If the design has helices but no clusters, auto-create a default cluster
    containing all helices and persist it silently (no undo snapshot)."""
    if design.cluster_transforms or not design.helices:
        return design
    from backend.core.models import ClusterRigidTransform

    # Reference geometry is excluded from clusters — keep it a fixed backdrop.
    ref_ids = design.reference_helix_ids()
    default_ct = ClusterRigidTransform(
        name="Cluster 1",
        is_default=True,
        auto_created=True,
        helix_ids=[h.id for h in design.helices if h.id not in ref_ids],
    )
    updated = design.copy_with(cluster_transforms=[default_ct])
    design_state.set_design_silent(updated)
    return updated


def _strip_feature_log_payloads(design_dict: dict) -> None:
    """Drop heavy feature_log payload blobs from a response dict IN PLACE, keeping
    the gating signals the feature-log panel actually reads.

    The 2D editor (skip-geometry) renders from topology and never decodes these
    blobs; it only checks ``evicted`` / ``diffs_evicted`` and per-child diff
    PRESENCE. So:
      - snapshot pre/post blobs → "" (panel gates revert on ``evicted``, not the
        blob; size fields like ``snapshot_size_bytes`` are kept for the tooltip)
      - per-child diff blobs → "1" when non-empty (preserve truthiness for the
        per-sub-step button gating), "" when empty.
    The backend's own design keeps the real blobs — this only edits the response
    copy — so revert/seek/save (which run server-side) are unaffected.
    """
    for e in design_dict.get("feature_log", []):
        for k in ("design_snapshot_gz_b64", "pre_state_gz_b64", "post_state_gz_b64"):
            if e.get(k):
                e[k] = ""
        for c in e.get("children", []):
            for k in ("diff_added_b64", "diff_removed_b64", "diff_modified_b64"):
                if c.get(k):
                    c[k] = "1"


def _design_response(design: Design, report: ValidationReport) -> dict:
    design = _ensure_default_cluster(design)
    design_dict = design.to_dict()
    # Loadout branch payloads are full compressed design snapshots. They must
    # persist in server-side state and .nadoc saves, but shipping every branch
    # snapshot on every UI response bloats ordinary edits. The frontend only
    # needs ids, names, and active cursor metadata for the dropdown.
    design_dict["loadouts"] = [
        {
            "id": l.id,
            "name": l.name,
            "snapshot_size_bytes": l.snapshot_size_bytes,
        }
        for l in design.loadouts
    ]
    _inject_joint_world_axes(design_dict)
    # Editor (skip-geometry) responses: drop the heavy feature_log payload blobs.
    # The 2D editor renders from topology and never decodes snapshot/diff blobs;
    # they were ~1.2 MB of every VoltronCore response (1.1 MB pre/post snapshots +
    # 0.1 MB per-step diffs). The backend keeps the real blobs (for revert/seek/
    # save), so this only shrinks the wire payload + the editor's JSON.parse.
    if should_skip_geometry():
        _strip_feature_log_payloads(design_dict)
    # Monotonic per-document revision, captured ATOMICALLY at mutation time for a
    # mutating request (falls back to the current value for read-only GETs). The
    # client drops any design response whose revision is older than the newest
    # already applied, so out-of-order/stale responses from rapid edits can't
    # clobber newer state (see _isStaleDesignResponse in client.js).
    rev = design_state.current_request_revision()
    if rev is None:
        rev = design_state.revision()
    return {
        "design": design_dict,
        "validation": _validation_dict(report, design),
        # Crossovers whose two halves currently resolve to the same strand
        # (would form a circular strand on ligation, so _ligate_crossover
        # skipped them). Frontend renders a ⚠ marker on these. Recomputed
        # on every response, so the marker auto-clears when the user nicks
        # the strand to break the cycle.
        "unligated_crossover_ids": unligated_crossover_ids(design),
        "revision": rev,
    }


def _inject_joint_world_axes(design_dict: dict) -> None:
    """Mutate *design_dict* in place: for each cluster_joint, compute the
    derived world-space axes (``axis_origin`` / ``axis_direction``) from the
    canonical local-frame storage (``local_axis_origin`` /
    ``local_axis_direction``) and the joint's parent ``cluster_transforms``
    record. These derived fields are convenience for API consumers
    (frontend renderer, exports) that expect world-space; the canonical
    storage remains local so cluster transforms apply lazily.
    """
    from backend.core.models import _local_to_world_joint

    cts = design_dict.get("cluster_transforms") or []
    if not cts:
        return
    ct_by_id = {ct.get("id"): ct for ct in cts if isinstance(ct, dict)}
    for j in design_dict.get("cluster_joints") or []:
        if not isinstance(j, dict):
            continue
        local_origin = j.get("local_axis_origin")
        local_dir = j.get("local_axis_direction")
        if local_origin is None or local_dir is None:
            continue
        ct = ct_by_id.get(j.get("cluster_id"))
        world_origin, world_dir = _local_to_world_joint(local_origin, local_dir, ct)
        j["axis_origin"] = world_origin
        j["axis_direction"] = world_dir


def _design_response_with_geometry(
    design: Design,
    report: ValidationReport,
    changed_helix_ids: list[str] | None = None,
    *,
    embed_straight: bool | None = None,
    compact_deformed: bool = False,
    partial_axes: bool = False,
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
        Straight axes are similarly stable across these mutations and need
        not be re-shipped.
    When None, full geometry is returned (legacy path, used for bulk ops).

    *embed_straight* — controls whether the un-deformed nucleotide positions
    and helix axes are embedded as ``straight_positions_by_helix`` /
    ``straight_helix_axes``. Three settings:
      • ``None`` (default): auto — embed iff the design has deformations OR
        cluster_transforms. When neither is present, straight == current and
        the frontend uses currentGeometry as the t=0 lerp anchor directly
        (see deform_view.js's hasDeformations/hasTransforms fast path).
      • ``True``: force embed regardless.
      • ``False``: never embed.
    The auto default eliminates the frontend's ``getStraightGeometry()``
    round-trip after every topology-changing mutation when deformations
    exist, while costing nothing for clean designs.

    When the request set ``X-NADOC-Skip-Geometry`` (the 2D cadnano editor, which
    draws from topology and never reads embedded geometry), return the
    geometry-free ``_design_response`` instead — sparing the backend a
    full-design geometry recompute (hundreds of ms on large designs) and the
    editor a multi-MB JSON.parse of a payload it would discard.
    """
    if should_skip_geometry():
        return _design_response(design, report)
    if changed_helix_ids is not None:
        # Partial path — compute only the real helices that actually changed.
        real_ids = frozenset(
            hid for hid in changed_helix_ids if not hid.startswith("__")
        )
        nucs = _geometry_for_helices(design, real_ids) if real_ids else []
        resp = {
            **_design_response(design, report),
            "nucleotides": nucs,
            "partial_geometry": True,
            "changed_helix_ids": changed_helix_ids,
            # helix_axes omitted by default — see docstring (crossover/xb mutations
            # don't move axes, so the frontend keeps its existing currentHelixAxes).
        }
        if partial_axes and real_ids:
            # Resize-style ops GROW/SHRINK the changed helix's axis, so the
            # frontend can't keep its stale axis. Ship axes for just the changed
            # helices. Cheap: deformed_helix_axes is axis-only (~all helices but
            # no per-nuc work); ovhg rotations reuse the partial nucs we just
            # computed (junction nuc present for the changed helix → precise;
            # absent elsewhere → ovhg.pivot fallback, but those are filtered out).
            all_axes = deformed_helix_axes(design)
            _apply_ovhg_rotations_to_axes(design, all_axes, nucs)
            resp["helix_axes"] = [ax for ax in all_axes if ax["helix_id"] in real_ids]
        return resp
    # Full path — compute nucleotides first, then derive axis positions using
    # nucleotide-derived pivots so axis arrows stay consistent with backbone beads.
    nucleotides = _geometry_for_design(design)
    axes = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
    if compact_deformed:
        # Re-bucket the per-nuc dicts into per-helix-per-direction parallel
        # arrays. Wire payload is ~50% of the dict-list form because field
        # names don't repeat per nuc. Frontend's _syncFromDesignResponse
        # rematerialises a flat nuc list before the renderer consumes it.
        out = {
            **_design_response(design, report),
            "nucleotides_compact": _compact_geometry_from_nucleotides(nucleotides),
            "helix_axes": axes,
        }
    else:
        out = {
            **_design_response(design, report),
            "nucleotides": nucleotides,
            "helix_axes": axes,
        }
    # Auto-decide: embed straight only when it would differ from the deformed
    # payload — i.e. design has deformations OR cluster_transforms. When
    # neither is present, the frontend's deform_view falls through its
    # hasDeformations/hasTransforms branch and builds straight maps from
    # currentGeometry directly, so shipping straight would be wasted bytes
    # plus a redundant geometry compute.
    if embed_straight is None:
        embed_straight = bool(design.deformations) or bool(design.cluster_transforms)
    if embed_straight:
        # Straight (un-deformed) geometry — strips deformations + cluster_transforms
        # before computing positions. Shipped in COMPACT positions_by_helix form
        # (parallel float arrays) instead of per-nuc dicts: deform_view and
        # unfold_view only read backbone_position / base_normal / (helix_id,
        # bp_index, direction) per nuc, so the full strand metadata is wasted
        # bytes. Compact format ~3× smaller on the wire, ~3× faster to parse.
        straight = design.model_copy(
            update={"deformations": [], "cluster_transforms": []}
        )
        straight_positions, straight_axes = _positions_for_design(straight)
        out["straight_positions_by_helix"] = straight_positions
        out["straight_helix_axes"] = straight_axes
    return out


def _find_helix(design: Design, helix_id: str) -> Helix:
    h = design.find_helix(helix_id)
    if h is None:
        raise HTTPException(404, detail=f"Helix {helix_id!r} not found.")
    return h


def _find_strand(design: Design, strand_id: str) -> Strand:
    s = design.find_strand(strand_id)
    if s is None:
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")
    return s


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
    populate_strands: bool = False  # if True, also adds a full-length scaffold + staple


class DomainRequest(BaseModel):
    helix_id: str
    start_bp: int
    end_bp: int
    direction: Direction


class StrandRequest(BaseModel):
    domains: List[DomainRequest] = []
    strand_type: StrandType = StrandType.STAPLE
    sequence: Optional[str] = None


# StrandExtension* request models moved to backend/api/routes_extensions.py.


# (Plate-layout + representation-override request models moved to
#  backend/api/routes_display_metadata.py alongside their routes.)


class StrandBatchDeleteRequest(BaseModel):
    strand_ids: List[str]


class OverhangBatchDeleteRequest(BaseModel):
    overhang_ids: List[str]


class StrandEndResizeEntry(BaseModel):
    strand_id: str
    helix_id: str
    end: Literal["5p", "3p"]
    delta_bp: int


class StrandEndResizeRequest(BaseModel):
    entries: List[StrandEndResizeEntry]


class DomainShiftEntry(BaseModel):
    strand_id: str
    domain_index: int
    delta_bp: int


class DomainShiftRequest(BaseModel):
    entries: List[DomainShiftEntry]


def _linker_conn_id_from_strand_id(strand_id: str) -> Optional[str]:
    prefix = "__lnk__"
    if not strand_id.startswith(prefix):
        return None
    rest = strand_id[len(prefix) :]
    if "__" not in rest:
        return None
    conn_id, side = rest.rsplit("__", 1)
    return conn_id if side in {"a", "b"} and conn_id else None


def _delete_regular_strands_from_design(design: Design, id_set: set[str]) -> Design:
    """Delete ordinary strands and cascade overhang/crossover/empty-helix cleanup.

    Chain cascade (Alt A): when an overhang is removed because its parent
    strand is deleted, every descendant overhang in the chain is also removed
    along with its strand. Without this, child OHs would orphan with their
    parent_overhang_id pointing at a missing record.
    """
    if not id_set:
        return design

    from backend.core.lattice import _overhang_chain_descendants

    ovhg_ids_to_remove = {o.id for o in design.overhangs if o.strand_id in id_set}
    # Expand to chain descendants — and pull THEIR strands into the delete set.
    pending = list(ovhg_ids_to_remove)
    while pending:
        cur = pending.pop()
        for desc_id in _overhang_chain_descendants(design, cur):
            if desc_id not in ovhg_ids_to_remove:
                ovhg_ids_to_remove.add(desc_id)
    desc_strand_ids = {
        o.strand_id for o in design.overhangs if o.id in ovhg_ids_to_remove
    }
    id_set = id_set | desc_strand_ids

    new_strands = [s for s in design.strands if s.id not in id_set]
    new_overhangs = [o for o in design.overhangs if o.id not in ovhg_ids_to_remove]

    covered_helix_ids: set[str] = {
        dom.helix_id for s in new_strands for dom in s.domains
    }
    new_helices = [h for h in design.helices if h.id in covered_helix_ids]

    slot_cov: dict[str, list[tuple[int, int]]] = {}
    for s in new_strands:
        for dom in s.domains:
            key = f"{dom.helix_id}_{dom.direction}"
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            slot_cov.setdefault(key, []).append((lo, hi))

    def _covered(helix_id: str, bp: int, direction: str) -> bool:
        return any(
            lo <= bp <= hi for lo, hi in slot_cov.get(f"{helix_id}_{direction}", [])
        )

    new_crossovers = [
        xo
        for xo in design.crossovers
        if _covered(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
        and _covered(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
    ]

    return design.model_copy(
        update={
            "strands": new_strands,
            "overhangs": new_overhangs,
            "helices": new_helices,
            "crossovers": new_crossovers,
        }
    )


def _delete_linker_connections_from_design(
    design: Design, conn_ids: set[str]
) -> Design:
    """Delete linker connection records and all generated linker topology."""
    if not conn_ids:
        return design
    from backend.core.lattice import remove_linker_topology

    updated = design.model_copy(
        update={
            "overhang_connections": [
                conn for conn in design.overhang_connections if conn.id not in conn_ids
            ]
        }
    )
    for conn_id in conn_ids:
        updated = remove_linker_topology(updated, conn_id)
    return updated


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
    cells: List[List[int]]  # [[row, col], ...]
    length_bp: int
    name: str = "Bundle"
    plane: str = "XY"
    strand_filter: str = "both"  # "both" | "scaffold" | "staples"
    lattice_type: LatticeType = LatticeType.HONEYCOMB
    ligate_adjacent: bool = True


class BundleSegmentRequest(BaseModel):
    cells: List[List[int]]  # [[row, col], ...]
    length_bp: int  # may be negative — extrudes in -axis direction
    plane: str = "XY"
    offset_nm: float = 0.0  # position of axis_start along the plane normal
    strand_filter: str = "both"  # "both" | "scaffold" | "staples"
    ligate_adjacent: bool = True


class CircleSegmentRequest(BaseModel):
    cells: List[List[int]]  # [[row, col], ...] — a single row (the disc footprint)
    cell_lengths: List[
        int
    ]  # per-cell bp length, parallel to cells (circular chord profile)
    plane: str = "XY"
    offset_nm: float = 0.0  # the slice plane bisects the disc (helices centred on it)
    strand_filter: str = "both"  # "both" | "scaffold" | "staples"
    ligate_adjacent: bool = True


class BundleContinuationRequest(BaseModel):
    cells: List[List[int]]  # [[row, col], ...] — may mix continuation and fresh cells
    length_bp: int
    plane: str = "XY"
    offset_nm: float = 0.0
    strand_filter: str = "both"  # "both" | "scaffold" | "staples"
    extend_inplace: bool = (
        True  # True = extend existing helix axis in-place; False = create new helix
    )
    ligate_adjacent: bool = True


class BundleDeformedContinuationRequest(BaseModel):
    cells: List[List[int]]  # [[row, col], ...]
    length_bp: int
    # Deformed cross-section frame from GET /design/deformed-frame
    grid_origin: List[float]  # [x, y, z]
    axis_dir: List[float]  # [x, y, z]
    frame_right: List[float]  # [x, y, z]
    frame_up: List[float]  # [x, y, z]
    plane: str = "XY"  # used for helix/strand ID naming only
    ref_helix_id: Optional[str] = (
        None  # helix that opened the slice plane — used for cluster membership
    )
    # bp index at which the deformed frame was sampled. When present, the frame is
    # RECOMPUTED server-side from the live design at this bp (instead of trusting the
    # baked grid_origin/axis_dir/... fields), which makes the op replayable: if an
    # upstream bend/twist is later deleted or edited, re-running this continuation
    # against the un-bent design re-derives a straight frame and re-places the
    # segment. Legacy requests without source_bp fall back to the baked frame.
    source_bp: Optional[int] = None


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


@router.delete("/design", status_code=200)
def close_session() -> dict:
    """Erase the active design and all history, returning the server to an empty state."""
    design_state.close_session()
    return {"ok": True}


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


def _design_replace_response(
    prev_design: "Design",
    design: "Design",
    report: "ValidationReport",
    trace: "_TimingTrace | None" = None,
) -> dict:
    """Build the response for any endpoint that REPLACES the active design
    (undo, redo, feature-log slider seek). Picks one of three shapes,
    in increasing payload size:

      1. ``cluster_only`` — diff is purely cluster_transform changes;
         frontend applies a delta transform in-place, zero geometry
         recompute or scene rebuild.
      2. ``positions_only`` — topology unchanged but cluster_transforms
         and/or deformations differ; backend ships compact per-nuc
         positions (parallel arrays, no per-nuc strand metadata) and
         the frontend mutates existing entry.nuc fields in place. Skips
         the per-nuc dict construction that dominates the full-geometry
         response and the per-nuc dict parse on the frontend.
      3. Embedded full geometry — fallback for true topology changes
         (extrusion, helix add/delete, strand mutation). Frontend needs
         a full scene rebuild.

    When *trace* is given, the chosen path is appended as a 0-duration step
    so the frontend's API perf log shows which fast path fired.
    """
    if _diff_is_cluster_only(prev_design, design):
        if trace is not None:
            trace._steps.append(("path:cluster_only", 0.0))
        return {
            **_design_response(design, report),
            "diff_kind": "cluster_only",
            "cluster_diffs": _cluster_diff_payload(prev_design, design),
        }
    diff_field = _topology_diff_field(prev_design, design)
    if diff_field is None:
        if trace is not None:
            trace._steps.append(("path:positions_only", 0.0))
        # Straight topology is identical; ship compact positions for the
        # changed deformed/cluster geometry. Helix axes ride along since
        # cluster transforms move axes too.
        # _positions_for_design builds the parallel arrays directly from
        # numpy without the per-nuc dict round-trip that dominated the
        # earlier _positions_by_helix(_geometry_for_helices(design)) chain.
        positions, axes = _positions_for_design(design)
        return {
            **_design_response(design, report),
            "diff_kind": "positions_only",
            "positions_by_helix": positions,
            "helix_axes": axes,
        }
    if trace is not None:
        # Tag with the rejecting field so the frontend perf log shows
        # why positions_only didn't fire (e.g. path:full_geometry_strands).
        trace._steps.append((f"path:full_geometry_{diff_field}", 0.0))
    if diff_field == "flexible_segment_marks" or design.flexible_connections:
        # The compact deformed arrays omit per-nuc metadata (see
        # _compact_geometry_from_nucleotides — no `is_flexible_segment` key), but
        # that per-bead flag MUST ride along so beads re-classify (rigid vs. bowed
        # arc) on undo/redo/seek. Ship the per-nuc form whenever the diff changed
        # the marks OR the target design currently has flexible connections — the
        # latter covers ANY other topology-changing replace (e.g. adding/removing
        # an OH-binder strand, whose undo would otherwise drop the flag and
        # silently re-rigidify a flexible scaffold run).
        return _design_response_with_geometry(
            design,
            report,
            embed_straight=True,
            compact_deformed=False,
        )
    # embed_straight=True bundles the straight (un-deformed) geometry into
    # the same response, so deform_view doesn't have to fire a second
    # ~5-second `/design/geometry?apply_deformations=false` round-trip
    # on every topology-changing seek / undo / redo / delete-feature.
    # compact_deformed=True ships the deformed geometry as parallel arrays
    # per helix per direction (instead of a list of per-nuc dicts), cutting
    # wire size and JSON.parse time roughly in half.
    return _design_response_with_geometry(
        design,
        report,
        embed_straight=True,
        compact_deformed=True,
    )


@router.post("/design/undo")
def undo_design():
    """Revert the active design to the state before the last mutation.

    Returns 404 if nothing to undo. Per-step wall-clock is exposed via the
    ``Server-Timing`` header.
    """
    trace = _TimingTrace()
    with trace.step("clone_prev"):
        prev = design_state.get_or_404().model_copy(deep=True)
    with trace.step("undo"):
        design, report = design_state.undo()
    with trace.step("response"):
        payload = _design_replace_response(prev, design, report)
    return trace.attach(ORJSONResponse(payload))


@router.post("/design/redo")
def redo_design():
    """Re-apply the last undone mutation.

    Returns 404 if nothing to redo. Per-step wall-clock is exposed via the
    ``Server-Timing`` header.
    """
    trace = _TimingTrace()
    with trace.step("clone_prev"):
        prev = design_state.get_or_404().model_copy(deep=True)
    with trace.step("redo"):
        design, report = design_state.redo()
    with trace.step("response"):
        payload = _design_replace_response(prev, design, report)
    return trace.attach(ORJSONResponse(payload))


def _origins_by_grid_pos(
    design_before: Design,
    design_after: Design,
    fallback_origin: Optional[str] = None,
) -> dict[str, str]:
    """Compute new_helix_origins by matching grid_pos.

    A new helix at the same (row, col) cell as a pre-existing helix is treated
    as a continuation of that helix → inherits its cluster.  ``fallback_origin``
    (if provided) is used for new helices whose grid_pos has no existing match
    — typical for deformed-continuation calls with a ref_helix_id.
    """
    before_helix_ids = {h.id for h in design_before.helices}
    grid_to_existing: dict[tuple, str] = {}
    for h in design_before.helices:
        if h.grid_pos is not None and h.grid_pos not in grid_to_existing:
            grid_to_existing[h.grid_pos] = h.id

    origins: dict[str, str] = {}
    for h in design_after.helices:
        if h.id in before_helix_ids:
            continue
        parent: Optional[str] = None
        if h.grid_pos is not None:
            parent = grid_to_existing.get(h.grid_pos)
        if parent is None:
            parent = fallback_origin
        if parent is not None:
            origins[h.id] = parent
    return origins


def _build_extrude_segment(d: Design, body: "BundleSegmentRequest"):
    """Pure builder + cluster-membership report for a slice-plane extrude."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_bundle_segment, ligate_new_strands

    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_bundle_segment(
        d,
        cells,
        body.length_bp,
        body.plane,
        body.offset_nm,
        body.strand_filter,
    )
    if body.ligate_adjacent:
        existing_ids = {s.id for s in d.strands}
        new_ids = {s.id for s in updated.strands if s.id not in existing_ids}
        if new_ids:
            updated = ligate_new_strands(updated, new_ids)
    return updated, MutationReport(new_helix_origins=_origins_by_grid_pos(d, updated))


@router.post("/design/bundle-segment", status_code=201)
def add_bundle_segment(body: BundleSegmentRequest) -> dict:
    """Append a honeycomb bundle segment to the active design (slice-plane extrude).

    Emits a ``snapshot`` feature-log entry so the extrude can be reverted
    after a refresh and replayed via the edit-feature endpoint.
    """
    holder: dict = {}

    def _fn(d: Design) -> Design:
        try:
            updated, mreport = _build_extrude_segment(d, body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        holder["mreport"] = mreport
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="extrude-segment",
        label=f"Extrude segment: {len(body.cells)} cells × {body.length_bp} bp",
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    return _design_response(updated, report)


def _build_circle_segment(d: Design, body: "CircleSegmentRequest"):
    """Pure builder + cluster-membership report for a circle/disc placement."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import ligate_new_strands, make_circle_segment

    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_circle_segment(
        d,
        cells,
        body.cell_lengths,
        body.plane,
        body.offset_nm,
        body.strand_filter,
    )
    if body.ligate_adjacent:
        existing_ids = {s.id for s in d.strands}
        new_ids = {s.id for s in updated.strands if s.id not in existing_ids}
        if new_ids:
            updated = ligate_new_strands(updated, new_ids)
    return updated, MutationReport(new_helix_origins=_origins_by_grid_pos(d, updated))


@router.post("/design/circle-segment", status_code=201)
def add_circle_segment(body: CircleSegmentRequest) -> dict:
    """Place a parametric circle (flat disc) primitive: a row of helices whose
    per-cell lengths trace a circular chord profile, centred on the slice plane.

    The per-cell lengths arrive pre-computed from the radius (see
    ``backend.core.circle_primitive``); this route just lays down the final
    geometry as one additive, revertable ``circle-segment`` feature-log entry.
    """

    def _fn(d: Design) -> Design:
        try:
            updated, mreport = _build_circle_segment(d, body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        holder["mreport"] = mreport
        return updated

    holder: dict = {}
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="circle-segment",
        label=f"Place circle: {len(body.cells)} helices",
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    return _design_response(updated, report)


def _build_extrude_continuation(d: Design, body: "BundleContinuationRequest"):
    """Pure builder + cluster-membership report for a bundle-continuation extrude."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_bundle_continuation, ligate_new_strands

    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_bundle_continuation(
        d,
        cells,
        body.length_bp,
        body.plane,
        body.offset_nm,
        body.strand_filter,
        extend_inplace=body.extend_inplace,
    )
    if body.ligate_adjacent:
        existing_ids = {s.id for s in d.strands}
        new_ids = {s.id for s in updated.strands if s.id not in existing_ids}
        if new_ids:
            updated = ligate_new_strands(updated, new_ids)
    return updated, MutationReport(new_helix_origins=_origins_by_grid_pos(d, updated))


@router.post("/design/bundle-continuation", status_code=201)
def add_bundle_continuation(body: BundleContinuationRequest) -> dict:
    """Extrude a bundle segment in continuation mode (occupied cells ending at offset extend existing strands).

    Emits a ``snapshot`` feature-log entry so the extrude can be reverted
    after a refresh and replayed via the edit-feature endpoint.
    """
    holder: dict = {}

    def _fn(d: Design) -> Design:
        try:
            updated, mreport = _build_extrude_continuation(d, body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        holder["mreport"] = mreport
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="extrude-continuation",
        label=f"Extrude continuation: {len(body.cells)} cells × {body.length_bp} bp",
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    return _design_response(updated, report)


@router.get("/design/deformed-frame")
def get_deformed_frame(
    source_bp: int = Query(
        ..., description="bp index at which to sample the deformed frame"
    ),
    ref_helix_id: Optional[str] = Query(
        None, description="Reference helix ID to select arm"
    ),
) -> dict:
    """Return the deformed cross-section frame at source_bp.

    Used by the frontend to orient the slice plane after a bend/twist.

    Returns: { grid_origin, axis_dir, frame_right, frame_up } — each a list of 3 floats.
    """
    design = design_state.get_or_404()
    return deformed_frame_at_bp(design, source_bp, ref_helix_id)


def _build_extrude_deformed_continuation(
    d: Design, body: "BundleDeformedContinuationRequest"
):
    """Pure builder + cluster-membership report for a deformed-continuation extrude."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_bundle_deformed_continuation

    # Prefer recomputing the deformed frame from the LIVE design at source_bp so the
    # op is replayable (see BundleDeformedContinuationRequest.source_bp). Falls back
    # to the baked frame for legacy requests that didn't send source_bp.
    if body.source_bp is not None:
        frame = deformed_frame_at_bp(d, body.source_bp, body.ref_helix_id)
    else:
        frame = {
            "grid_origin": body.grid_origin,
            "axis_dir": body.axis_dir,
            "frame_right": body.frame_right,
            "frame_up": body.frame_up,
        }
    axes = deformed_helix_axes(d)
    deformed_endpoints = {
        ax["helix_id"]: {"start": ax["start"], "end": ax["end"]} for ax in axes
    }
    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_bundle_deformed_continuation(
        d,
        cells,
        body.length_bp,
        frame,
        deformed_endpoints,
        body.plane,
        ref_helix_id=body.ref_helix_id,
    )
    return updated, MutationReport(
        new_helix_origins=_origins_by_grid_pos(
            d, updated, fallback_origin=body.ref_helix_id
        ),
    )


@router.post("/design/bundle-deformed-continuation", status_code=201)
def add_bundle_deformed_continuation(body: BundleDeformedContinuationRequest) -> dict:
    """Extrude a continuation segment using a deformed cross-section frame.

    Positions new helices using grid_origin/axis_dir/frame_right/frame_up from
    a prior call to GET /design/deformed-frame.  Continuation detection uses
    3-D proximity of deformed helix endpoints.

    Emits a ``snapshot`` feature-log entry so the extrude can be reverted
    after a refresh and replayed via the edit-feature endpoint.
    """

    def _fn(d: Design) -> Design:
        try:
            updated, _mreport = _build_extrude_deformed_continuation(d, body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="extrude-deformed-continuation",
        label=f"Extrude (deformed): {len(body.cells)} cells × {body.length_bp} bp",
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    return _design_response(updated, report)


@router.post("/design/bundle", status_code=201)
def create_bundle(body: BundleRequest) -> dict:
    """Create a honeycomb bundle design from a list of (row, col) lattice cells.

    This is the canonical fresh-start endpoint. To guarantee that F0 (slider
    seek to ``-2``) is an empty workspace regardless of what was loaded
    before, we first reset the active design to an empty ``Design`` and only
    then run bundle creation through the snapshot wrapper. The resulting
    snapshot's pre-state is therefore the canonical empty design.
    """
    try:
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    # Reset to a canonical empty workspace so the snapshot's pre-state is empty.
    empty = Design(
        metadata=DesignMetadata(name=body.name),
        lattice_type=body.lattice_type,
    )
    design_state.clear_history()
    design_state.set_design(empty)

    new_design, report, _entry = design_state.mutate_with_feature_log(
        op_kind="bundle-create",
        label=f"Create bundle: {body.name}",
        params=body.model_dump(mode="json"),
        fn=lambda _d: _cluster_bundle_regions(_build_bundle(cells, body)),
    )
    return _design_response(new_design, report)


def _build_bundle(cells, body: "BundleRequest") -> Design:
    """Pure builder for a fresh bundle design — used by both the create-bundle
    endpoint and the edit-feature dispatcher."""
    from backend.core.lattice import make_bundle_design, ligate_new_strands

    new_design = make_bundle_design(
        cells,
        body.length_bp,
        body.name,
        body.plane,
        strand_filter=body.strand_filter,
        lattice_type=body.lattice_type,
    )
    if body.ligate_adjacent:
        new_ids = {s.id for s in new_design.strands}
        if new_ids:
            new_design = ligate_new_strands(new_design, new_ids)
    return new_design


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
        if body.name is not None:
            d.metadata.name = body.name
        if body.description is not None:
            d.metadata.description = body.description
        if body.author is not None:
            d.metadata.author = body.author
        if body.tags is not None:
            d.metadata.tags = body.tags

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
    measured_positioning: bool = Query(
        False,
        description="Display-only.  Re-place backbone beads and base beads onto the "
        "MD-measured radii and P-P azimuthal separation instead of the "
        "legacy HELIX_RADIUS / +-150 deg groove.  The app always states "
        "this explicitly; it stays opt-out here because the other CG "
        "position paths (oxDNA seeding, linker relax, extension tails) do "
        "not yet share the measured placement, unlike the ATOMISTIC layer, "
        "which is measured natively.  Topology and the geometric layer are "
        "untouched; see core/measured_positioning.py.",
    ),
):
    """Return geometry for the active design.

    Returns { nucleotides: [...], helix_axes: [{helix_id, start, end}, ...] }

    When apply_deformations=false, returns the straight (un-deformed) bundle
    positions regardless of any DeformationOps stored on the design.

    When helix_ids is supplied, only nucleotides on those helices are returned.
    The caller is responsible for merging the partial result into the existing
    full geometry (see Fix B in client.js).

    Per-step wall-clock is exposed in the ``Server-Timing`` response header
    so the frontend can log where each call's time was spent (nucleotide
    compute vs. axes compute vs. JSON serialisation downstream).
    """
    trace = _TimingTrace()
    with trace.step("get_design"):
        design = design_state.get_or_404()
    ids: frozenset[str] | None = frozenset(helix_ids.split(",")) if helix_ids else None
    if apply_deformations:
        with trace.step("nucleotides"):
            nucleotides = _geometry_for_helices(
                design, ids, measured_positioning=measured_positioning
            )
        with trace.step("helix_axes"):
            axes = deformed_helix_axes(design)
        with trace.step("ovhg_rotations"):
            _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
        out = {
            "nucleotides": nucleotides,
            "helix_axes": axes,
        }
        # Auto-embed straight geometry whenever the design has deformations
        # or cluster_transforms — mirrors _design_response_with_geometry's
        # auto-embed so frontend callers (getGeometry / refetch / preview
        # revert / debug refetch) update currentGeometry and straightGeometry
        # atomically in one setState batch. Without this, the deform_view
        # subscriber would see currentGeometry change without a matching
        # straightGeometry update and fall back to a second round-trip via
        # getStraightGeometry(), reopening the race window the auto-embed
        # was meant to close. Skipped for partial responses (ids != None):
        # partial mutations leave axes unchanged, so cached straight maps
        # on the frontend stay valid.
        if ids is None and (design.deformations or design.cluster_transforms):
            with trace.step("strip_for_embed_straight"):
                straight_design = design.model_copy(
                    update={"deformations": [], "cluster_transforms": []}
                )
            with trace.step("straight_positions_embed"):
                straight_positions, straight_axes = _positions_for_design(
                    straight_design, measured_positioning=measured_positioning
                )
            out["straight_positions_by_helix"] = straight_positions
            out["straight_helix_axes"] = straight_axes
    else:
        with trace.step("strip_deformations"):
            straight = design.model_copy(
                update={"deformations": [], "cluster_transforms": []}
            )
        with trace.step("nucleotides_straight"):
            nucleotides = _geometry_for_helices(
                straight, ids, measured_positioning=measured_positioning
            )
        with trace.step("helix_axes_straight"):
            axes = _straight_helix_axes(design)
        out = {
            "nucleotides": nucleotides,
            "helix_axes": axes,
        }
    if ids is not None:
        # Signal to the frontend that this is a partial response — only the
        # requested helices are present and the result should be merged rather
        # than replacing the full geometry (Fix B merge path in client.js).
        out["partial_geometry"] = True
        out["changed_helix_ids"] = list(ids)
    return trace.attach(ORJSONResponse(out))


@router.post("/design/load")
def load_design(body: FilePathRequest) -> dict:
    """Load a .nadoc file from the given server-side path.

    Native .nadoc files preserve their saved absolute positions — recentering
    is only applied to non-native imports (caDNAno / scadnano) where source
    coordinates are arbitrary. The user can manually trigger recentering via
    POST ``/design/center``.
    """
    from backend.core.lattice import (
        migrate_split_staple_domains,
        autodetect_all_overhangs,
    )
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
    design = migrate_split_staple_domains(design)
    # Full detection (Pass 1 autodetect + Pass 2 reconcile), not just reconcile:
    # idempotent for already-tagged overhangs, but also catches overhangs the
    # original import missed (e.g. cross-over tails entirely outside scaffold —
    # the stap_36_331 case), so existing .nadoc files self-correct on load.
    design = autodetect_all_overhangs(design)
    design = _fix_stale_ovhg_pivots(design)
    design = _backfill_sub_domains_if_empty(design)
    design = _derive_duplexes_if_empty(design)
    design = _materialize_duplex_clusters_on_load(design)
    design = _recompute_flexible_connections(design)
    design_state.clear_history()  # fresh baseline — no undo into previous session
    design_state.set_design(design)
    report = validate_design(design)
    return _design_response(design, report)


@router.post("/design/import", status_code=200)
def import_design(body: DesignImportRequest) -> dict:
    """Load a design from raw .nadoc JSON content sent by the browser.

    Unlike ``/design/load`` (which reads a server-side file path), this endpoint
    accepts the file content directly, enabling browser-based file-open dialogs.
    Clears undo history and crossover cache so the loaded design starts fresh.

    Like ``/design/load``, native .nadoc content preserves absolute positions —
    recentering is only applied to non-native imports.
    """
    from backend.core.lattice import (
        migrate_split_staple_domains,
        autodetect_all_overhangs,
    )
    from backend.core.validator import validate_design

    try:
        design = Design.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to parse design: {exc}") from exc
    design = migrate_split_staple_domains(design)
    # Full detection (Pass 1 autodetect + Pass 2 reconcile), not just reconcile:
    # idempotent for already-tagged overhangs, but also catches overhangs the
    # original import missed (e.g. cross-over tails entirely outside scaffold —
    # the stap_36_331 case), so existing .nadoc files self-correct on load.
    design = autodetect_all_overhangs(design)
    design = _fix_stale_ovhg_pivots(design)
    design = _backfill_sub_domains_if_empty(design)
    design = _derive_duplexes_if_empty(design)
    design = _materialize_duplex_clusters_on_load(design)
    design = _recompute_flexible_connections(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    return _design_response(design, report)


class CadnanoImportRequest(BaseModel):
    content: str  # raw caDNAno v2 JSON string sent by the browser


class ScadnanoImportRequest(BaseModel):
    content: str  # raw scadnano JSON string sent by the browser
    name: Optional[str] = (
        None  # filename (without extension) from the browser — overrides embedded name
    )


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
    design = _recenter_design(design)
    design = autodetect_all_overhangs(design)
    design = _autodetect_clusters(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    resp = _design_response(design, report)
    if import_warnings:
        resp["import_warnings"] = import_warnings
    return resp


def _fix_stale_ovhg_pivots(design: "Design") -> "Design":
    """Recompute pivot for OverhangSpec objects still carrying the zero-vector default.

    Old .nadoc files saved before pivot computation was added to
    autodetect_overhangs / _reconcile_inline_overhangs have pivot=[0,0,0].
    This migration runs at load time and leaves non-zero pivots untouched.
    Must be called BEFORE _recenter_design so the pivot is computed in the
    same coordinate frame as the helix axes before recentering.
    """
    from backend.core.lattice import _pivot_for_junction

    _ZERO = [0.0, 0.0, 0.0]
    if not any(list(o.pivot) == _ZERO for o in design.overhangs):
        return design

    helices_by_id = {h.id: h for h in design.helices}
    strand_by_id = {s.id: s for s in design.strands}

    new_overhangs = []
    for ovhg in design.overhangs:
        if list(ovhg.pivot) != _ZERO:
            new_overhangs.append(ovhg)
            continue

        strand = strand_by_id.get(ovhg.strand_id)
        if strand is None:
            new_overhangs.append(ovhg)
            continue

        domains = strand.domains
        dom_idx = next(
            (i for i, d in enumerate(domains) if d.overhang_id == ovhg.id),
            None,
        )
        if dom_idx is None:
            new_overhangs.append(ovhg)
            continue

        domain = domains[dom_idx]
        n = len(domains)

        # Find the adjacent domain that borders the crossover junction.
        # Prefer a cross-helix neighbour; fall back to same-helix for
        # split-domain inline overhangs.
        adj_dom = None
        adj_is_before = False
        for ai, is_before in ((dom_idx - 1, True), (dom_idx + 1, False)):
            if 0 <= ai < n:
                adj_dom = domains[ai]
                adj_is_before = is_before
                if adj_dom.helix_id != domain.helix_id:
                    break  # prefer cross-helix neighbour

        if adj_dom is None:
            new_overhangs.append(ovhg)
            continue

        # Junction bp: the end of adj_dom that faces the overhang domain
        junc_bp = adj_dom.end_bp if adj_is_before else adj_dom.start_bp
        pivot_xyz = _pivot_for_junction(helices_by_id, adj_dom.helix_id, junc_bp)
        new_overhangs.append(ovhg.model_copy(update={"pivot": pivot_xyz}))

    return design.model_copy(update={"overhangs": new_overhangs})


def _recenter_design(design: "Design") -> "Design":
    """Translate all helix axes so the XY bounding box center is at the origin.

    Only X and Y are shifted (Z runs along the helix axis and is left alone).
    No-op when the design has no helices or is already centered.
    """
    if not design.helices:
        return design
    xs = [h.axis_start.x for h in design.helices]
    ys = [h.axis_start.y for h in design.helices]
    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    if abs(cx) < 1e-6 and abs(cy) < 1e-6:
        return design
    new_helices = [
        h.model_copy(
            update={
                "axis_start": Vec3(
                    x=h.axis_start.x - cx, y=h.axis_start.y - cy, z=h.axis_start.z
                ),
                "axis_end": Vec3(
                    x=h.axis_end.x - cx, y=h.axis_end.y - cy, z=h.axis_end.z
                ),
            }
        )
        for h in design.helices
    ]
    new_overhangs = [
        o.model_copy(update={"pivot": [o.pivot[0] - cx, o.pivot[1] - cy, o.pivot[2]]})
        for o in design.overhangs
    ]
    # Shift previously-set cluster pivots so they stay in sync with the recentered
    # helix axes.  Skip pivots that are still [0,0,0] (never activated) — those will
    # be computed fresh from geometry when the move/rotate tool is first used.
    _ZERO = [0.0, 0.0, 0.0]
    new_clusters = [
        ct.model_copy(
            update={"pivot": [ct.pivot[0] - cx, ct.pivot[1] - cy, ct.pivot[2]]}
        )
        if list(ct.pivot) != _ZERO
        else ct
        for ct in design.cluster_transforms
    ]
    return design.model_copy(
        update={
            "helices": new_helices,
            "overhangs": new_overhangs,
            "cluster_transforms": new_clusters,
        }
    )


@router.post("/design/center", status_code=200)
def center_design() -> dict:
    """Translate all helix axes so the XY bounding box center is at the origin.

    Preserves all relative helix positions.  No-op if already centered.
    """
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    centered = _recenter_design(design)
    if centered is design:
        return _design_response(design, validate_design(design))

    design_state.snapshot()
    design_state.set_design_silent(centered)
    return _design_response(centered, validate_design(centered))


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
    if body.name:
        design = design.model_copy(
            update={"metadata": design.metadata.model_copy(update={"name": body.name})}
        )
    design = autodetect_all_overhangs(design)
    design = _backfill_overhang_sequences(design)
    # Capture sample positions before and after re-centering for debug info.
    _pre_recenter = [
        (h.id, round(h.axis_start.x, 4), round(h.axis_start.y, 4))
        for h in design.helices[:5]
    ]
    design = _recenter_design(design)
    _post_recenter = [
        (h.id, round(h.axis_start.x, 4), round(h.axis_start.y, 4))
        for h in design.helices[:5]
    ]
    _cx = round(_post_recenter[0][1] - _pre_recenter[0][1], 4) if _pre_recenter else 0.0
    _cy = round(_post_recenter[0][2] - _pre_recenter[0][2], 4) if _pre_recenter else 0.0
    design = _autodetect_clusters(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    resp = _design_response(design, report)
    if import_warnings:
        resp["import_warnings"] = import_warnings
    resp["debug"] = {
        "recentered": True,
        "center_shift": {"x": _cx, "y": _cy},
        "helix_count": len(design.helices),
        "sample_axes_before": [
            {"id": hid, "x": x, "y": y} for hid, x, y in _pre_recenter
        ],
        "sample_axes_after": [
            {"id": hid, "x": x, "y": y} for hid, x, y in _post_recenter
        ],
    }
    return resp


@router.get("/debug/design-positions")
def debug_design_positions() -> dict:
    """Compare stored axis_start vs what _normalize_helix_for_grid would produce.

    Useful for diagnosing re-centering bugs: if 'match' is False for any helix,
    that helix's geometry will be placed at the un-centered grid position.
    """
    design = design_state.get_or_404()
    from backend.core.deformation import _normalize_helix_for_grid

    rows = []
    for h in design.helices:
        hn = _normalize_helix_for_grid(h, design.lattice_type)
        rows.append(
            {
                "id": h.id,
                "grid_pos": list(h.grid_pos) if h.grid_pos is not None else None,
                "axis_x": round(h.axis_start.x, 4),
                "axis_y": round(h.axis_start.y, 4),
                "normalized_x": round(hn.axis_start.x, 4),
                "normalized_y": round(hn.axis_start.y, 4),
                "match": abs(h.axis_start.x - hn.axis_start.x) < 0.01
                and abs(h.axis_start.y - hn.axis_start.y) < 0.01,
            }
        )
    return {"helix_count": len(rows), "helices": rows}


class PdbImportRequest(BaseModel):
    content: str  # raw PDB file text sent by the browser
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
            design, pdb_atomistic, import_warnings = merge_pdb_into_design(
                existing, body.content
            )
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


def _download_rcsb_pdb(pdb_id: str) -> str:
    """Download a structure from the RCSB Protein Data Bank by 4-char ID.

    Fetches the legacy ``.pdb`` format server-side (avoids browser CORS).  Some
    very large/modern entries are deposited only as mmCIF and 404 here.
    """
    import re
    import urllib.error
    import urllib.request

    pid = pdb_id.strip().upper()
    if not re.fullmatch(r"[0-9A-Z]{4}", pid):
        raise HTTPException(
            400, detail="PDB ID must be 4 alphanumeric characters (e.g. 1BNA)."
        )
    url = f"https://files.rcsb.org/download/{pid}.pdb"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:  # noqa: S310 (fixed host)
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise HTTPException(
                404,
                detail=f"PDB {pid} not found in RCSB as .pdb (it may be mmCIF-only).",
            ) from exc
        raise HTTPException(502, detail=f"RCSB download failed ({exc.code}).") from exc
    except Exception as exc:
        raise HTTPException(502, detail=f"RCSB download failed: {exc}") from exc


class PdbAutoImportRequest(BaseModel):
    content: Optional[str] = None  # raw PDB text (file import)
    pdb_id: Optional[str] = None  # 4-char RCSB id (download)
    name: str = ""
    # None = undecided (ask the user when the structure has both protein + DNA);
    # True/False = remove (or keep) DNA in the imported protein object.
    remove_dna_from_protein: Optional[bool] = None


@router.post("/design/import/pdb-auto", status_code=200)
def import_pdb_auto(body: PdbAutoImportRequest) -> dict:
    """Unified PDB import: download by RCSB id or accept file content, then
    route by residue content.

    * Protein present → imported as a free-standing, movable protein object
      (embedded in the design, logged in the feature log).  If DNA is ALSO
      present and ``remove_dna_from_protein`` is undecided, returns
      ``needs_dna_decision`` (with the resolved ``content``) instead of
      importing, so the UI can ask whether to strip the DNA.
    * DNA only → imported as a design (the classic PDB-as-design path).
    """
    from backend.core.pdb_to_design import import_pdb, merge_pdb_into_design
    from backend.core.protein import classify_pdb_content, parse_protein_pdb
    from backend.core.validator import validate_design

    if body.pdb_id:
        content = _download_rcsb_pdb(body.pdb_id)
        name = body.name or body.pdb_id.strip().upper()
        source = f"rcsb:{body.pdb_id.strip().upper()}"
    elif body.content:
        content = body.content
        name = body.name or "structure"
        source = "file"
    else:
        raise HTTPException(400, detail="Provide either pdb_id or content.")

    has_dna, has_protein = classify_pdb_content(content)
    if not has_dna and not has_protein:
        raise HTTPException(400, detail="No DNA or protein residues found in the PDB.")

    resp: dict = {
        "imported": {"dna": False, "protein": False},
        "source": source,
        "name": name,
    }

    if has_protein:
        # Ask before stripping DNA from a protein-DNA complex.
        if has_dna and body.remove_dna_from_protein is None:
            return {
                **resp,
                "needs_dna_decision": True,
                "has_dna": True,
                "has_protein": True,
                "content": content,
            }
        exclude_dna = bool(body.remove_dna_from_protein)
        try:
            asset = parse_protein_pdb(
                content, name=name, source_filename=name, exclude_dna=exclude_dna
            )
        except Exception as exc:
            raise HTTPException(
                400, detail=f"Protein PDB import failed: {exc}"
            ) from exc
        if not asset.atoms:
            raise HTTPException(400, detail="No protein atoms found after parsing.")
        updated, report, meta = _import_protein_free(asset)
        resp.update(_design_response(updated, report))
        resp["protein"] = meta
        resp["imported"]["protein"] = True
        return resp

    # DNA only → design import.
    existing = design_state.get_design()
    try:
        if existing and existing.helices:
            design, pdb_atomistic, w = merge_pdb_into_design(existing, content)
        else:
            design, pdb_atomistic, w = import_pdb(content)
    except Exception as exc:
        raise HTTPException(400, detail=f"DNA PDB import failed: {exc}") from exc
    design_state.clear_history()
    design_state.set_design(design)
    design_state.set_pdb_atomistic(pdb_atomistic)
    report = validate_design(design)
    resp.update(_design_response(design, report))
    resp["imported"]["dna"] = True
    if w:
        resp["import_warnings"] = w
    return resp


def _import_protein_free(asset):
    """Embed a protein asset + add a free-standing placement, logged.

    Also registers the asset in the session library (so the attach-to-overhang
    picker can list it).  Creates an empty design if none is active, so the
    import has a feature log to record into.
    """
    from backend.core.models import Design, ProteinAttachment, ProteinTargetFree
    from backend.core.protein import protein_asset_meta

    design_state.add_protein_asset(asset)
    if design_state.get_design() is None:
        design_state.set_design(Design())

    attachment = ProteinAttachment(
        asset_id=asset.id,
        target=ProteinTargetFree(),
        conjugation_atom_serial=asset.default_conjugation_atom_serial,
    )

    def _fn(d: Design) -> None:
        if not any(a.id == asset.id for a in d.protein_assets):
            d.protein_assets = [*d.protein_assets, asset]
        d.protein_attachments = [*d.protein_attachments, attachment]

    updated, report, _entry = design_state.mutate_with_feature_log(
        "protein-import",
        f"Import protein {asset.name}",
        {"asset_id": asset.id, "name": asset.name},
        _fn,
    )
    return updated, report, protein_asset_meta(asset)


@router.get("/design/export/cadnano")
def export_cadnano_design() -> Response:
    """Export the active design as a caDNAno v2 JSON file download.

    Returns a JSON file with Content-Disposition: attachment so the browser
    triggers a download.  Raises 400 if the design cannot be exported
    (e.g. square-lattice).
    """
    import json as _json
    from backend.core.cadnano import export_cadnano, check_cadnano_compatibility

    design = _design_for_export()
    warnings = check_cadnano_compatibility(design)
    errors = [w for w in warnings if w.startswith("ERROR")]
    if errors:
        raise HTTPException(400, detail="; ".join(errors))
    try:
        data = export_cadnano(design)
    except Exception as exc:
        raise HTTPException(400, detail=f"caDNAno export failed: {exc}") from exc
    json_bytes = _json.dumps(data, separators=(",", ":")).encode("utf-8")
    filename = f"{_export_filename_stem(design.metadata.name)}.json"
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

    def _apply(d: Design) -> None:
        d.helices.append(new_helix)

    label = f"Add helix · {new_helix.length_bp} bp"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="helix-add",
        label=label,
        params={**body.model_dump(mode="json"), "_helix_id": new_helix.id},
        fn=_apply,
    )
    return {
        "helix": new_helix.model_dump(),
        "geometry": [
            {
                "helix_id": n.helix_id,
                "bp_index": n.bp_index,
                "direction": n.direction.value,
                "backbone_position": n.position.tolist(),
                "base_position": n.base_position.tolist(),
                "base_normal": n.base_normal.tolist(),
                "axis_tangent": n.axis_tangent.tolist(),
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

    The new helix is placed ADJACENT to its neighbours in 3D: it is positioned
    relative to the nearest existing lattice helix (using that helix's *actual*
    axis, not the raw lattice formula) and inherits its axis Z-span, bp_start and
    length.  This keeps cell-clicks correct for imported / re-centered designs
    (whose helices don't sit at _lattice_position) and makes the new track
    co-extensive with its neighbours in both the path view and the 3D view, so a
    strand later penned onto it lands beside the neighbour it sits next to.
    """
    from backend.core.constants import BDNA_RISE_PER_BP as _RISE
    from backend.core.lattice import (
        _LINKER_HELIX_PREFIX,
        _lattice_direction,
        _lattice_phase_offset,
        _lattice_position,
        _lattice_twist,
        _overhang_neighbor_xy,
    )

    design = design_state.get_or_404()
    lt = design.lattice_type

    direction = _lattice_direction(body.row, body.col, lt)
    phase_base = _lattice_phase_offset(direction, lt)  # angle at global bp 0
    twist = _lattice_twist(lt)

    # Reference = nearest existing lattice helix (Manhattan distance in grid
    # cells).  Linker helices are synthetic and parked far off-lattice, so they
    # are excluded as references.
    candidates = [
        h
        for h in design.helices
        if h.grid_pos is not None and not h.id.startswith(_LINKER_HELIX_PREFIX)
    ]
    ref = (
        min(
            candidates,
            key=lambda h: abs(h.grid_pos[0] - body.row) + abs(h.grid_pos[1] - body.col),
        )
        if candidates
        else None
    )

    if ref is not None:
        # Adjacent placement: XY offset from the reference's real axis, Z-span +
        # bp_start + length copied so the new track lines up with its neighbours.
        nx, ny = _overhang_neighbor_xy(ref, body.row, body.col, design)
        bp_start = ref.bp_start
        length_bp = ref.length_bp
        axis_start = Vec3(x=nx, y=ny, z=ref.axis_start.z)
        axis_end = Vec3(x=nx, y=ny, z=ref.axis_end.z)
        phase_offset = phase_base + bp_start * twist
    else:
        # Empty design (first helix): raw lattice position, requested default length.
        lx, ly = _lattice_position(body.row, body.col, lt)
        bp_start = 0
        length_bp = body.length_bp
        axis_start = Vec3(x=lx, y=ly, z=0.0)
        axis_end = Vec3(x=lx, y=ly, z=length_bp * _RISE)
        phase_offset = phase_base

    new_helix = Helix(
        axis_start=axis_start,
        axis_end=axis_end,
        length_bp=length_bp,
        phase_offset=phase_offset,
        twist_per_bp_rad=twist,
        bp_start=bp_start,
        grid_pos=(body.row, body.col),
    )

    # When populate_strands is set, also add a full-length scaffold + staple
    # strand to the new helix (same convention as make_bundle_design: scaffold
    # runs in the lattice direction, staple runs opposite; start_bp is the 5′ end).
    # Legacy path — the 2D editor now creates empty helices.  Domains use GLOBAL
    # bp indices so they remain correct when bp_start was inherited from a neighbour.
    if body.populate_strands:
        lo = bp_start
        hi = bp_start + length_bp - 1
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = lo, hi
        else:
            scaf_start, scaf_end = hi, lo
        staple_dir = (
            Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
        )
        if staple_dir == Direction.FORWARD:
            stpl_start, stpl_end = lo, hi
        else:
            stpl_start, stpl_end = hi, lo

        scaffold = Strand(
            domains=[
                Domain(
                    helix_id=new_helix.id,
                    start_bp=scaf_start,
                    end_bp=scaf_end,
                    direction=direction,
                )
            ],
            strand_type=StrandType.SCAFFOLD,
        )
        staple = Strand(
            domains=[
                Domain(
                    helix_id=new_helix.id,
                    start_bp=stpl_start,
                    end_bp=stpl_end,
                    direction=staple_dir,
                )
            ],
            strand_type=StrandType.STAPLE,
        )

        def _apply(d):
            d.helices.append(new_helix)
            d.strands.append(scaffold)
            d.strands.append(staple)
    else:

        def _apply(d):
            d.helices.append(new_helix)

    label = f"Add helix at ({body.row}, {body.col}) · {length_bp} bp"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="helix-add-at-cell",
        label=label,
        params={**body.model_dump(mode="json"), "_helix_id": new_helix.id},
        fn=_apply,
    )
    return {
        **_design_response(design, report),
        "nucleotides": [
            {
                "helix_id": n.helix_id,
                "bp_index": n.bp_index,
                "direction": n.direction.value,
                "backbone_position": n.position.tolist(),
                "base_position": n.base_position.tolist(),
                "base_normal": n.base_normal.tolist(),
                "axis_tangent": n.axis_tangent.tolist(),
            }
            for n in nucleotide_positions(new_helix)
        ],
    }


class ReorderHelicesBody(BaseModel):
    ordered_ids: List[str]


# NOTE: this static-path route MUST be declared before the dynamic
# `/design/helices/{helix_id}` routes below — otherwise FastAPI matches
# "reorder" as a helix_id and routes here never fire.
@router.put("/design/helices/reorder")
def reorder_helices(body: ReorderHelicesBody) -> dict:
    """Permute the vertical order of helices in the pathview.

    Vertical order in the 2D editor *is* the order of ``design.helices`` — there
    is no separate ordering field — so reordering is a pure display concern.  It
    touches array order ONLY: helix UUIDs, ``grid_pos``, strands, and crossovers
    are all untouched, so topology and geometry are invariant.  The new order
    persists because ``Design.to_json()`` serialises ``helices`` in array order.

    Validation is strict: the supplied id list must contain every existing helix
    id exactly once (a missing/duplicated id would be silent data loss, since a
    helix dropped from the array would vanish from the editor).
    """
    design = design_state.get_or_404()
    helix_map = {h.id: h for h in design.helices}
    ids = body.ordered_ids
    if len(ids) != len(set(ids)):
        raise HTTPException(400, detail="Duplicate helix IDs in reorder list.")
    if set(ids) != set(helix_map):
        raise HTTPException(
            400,
            detail="Reorder list must contain every helix ID exactly once.",
        )

    def _apply(d: Design) -> None:
        # Freeze each helix's CURRENT number onto it as a persistent label
        # BEFORE permuting, so the gutter / sliceview label follows the helix
        # identity rather than its (about-to-change) array position. Both views
        # render `helix.label ?? array_index`, so a label-less helix would
        # otherwise re-number to its new row. Helices that already carry a label
        # (e.g. a scadnano import index) keep it. Persists via Design.to_json().
        for i, h in enumerate(d.helices):
            if h.label is None:
                h.label = str(i)
        m = {h.id: h for h in d.helices}
        d.helices = [m[i] for i in ids]

    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="helix-reorder",
        label="Reorder helices",
        params={"ordered_ids": ids},
        fn=_apply,
    )
    return _design_response(design, report)


@router.get("/design/helices/{helix_id}")
def get_helix(helix_id: str) -> dict:
    design = design_state.get_or_404()
    helix = _find_helix(design, helix_id)
    return {
        "helix": helix.model_dump(),
        "geometry": [
            {
                "helix_id": n.helix_id,
                "bp_index": n.bp_index,
                "direction": n.direction.value,
                "backbone_position": n.position.tolist(),
                "base_position": n.base_position.tolist(),
                "base_normal": n.base_normal.tolist(),
                "axis_tangent": n.axis_tangent.tolist(),
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

    label = f"Update helix {_helix_label(design_state.get_or_404(), helix_id)}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="helix-update",
        label=label,
        params={"helix_id": helix_id, **body.model_dump(mode="json")},
        fn=_apply,
    )
    return {
        "helix": replacement.model_dump(),
        **_design_response(design, report),
    }


class HelixExtendRequest(BaseModel):
    lo_bp: int  # desired minimum bp — only extends left, never shrinks
    hi_bp: int  # desired maximum bp — only extends right, never shrinks


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
    helix = _find_helix(design, helix_id)

    h_lo = helix.bp_start
    h_hi = helix.bp_start + helix.length_bp - 1

    new_lo = min(body.lo_bp, h_lo)
    new_hi = max(body.hi_bp, h_hi)

    if new_lo == h_lo and new_hi == h_hi:
        report = validate_design(design)
        return _design_response_with_geometry(
            design, report, changed_helix_ids=[helix_id]
        )

    ax = helix.axis_end.to_array() - helix.axis_start.to_array()
    ax_len = float(_math.sqrt(float((ax * ax).sum())))
    unit = ax / ax_len if ax_len > 1e-9 else helix.axis_start.to_array() * 0 + [0, 0, 1]

    extra_lo = h_lo - new_lo  # bps prepended (≥ 0)
    extra_hi = new_hi - h_hi  # bps appended  (≥ 0)

    new_axis_start = helix.axis_start.to_array() - extra_lo * BDNA_RISE_PER_BP * unit
    new_axis_end = helix.axis_end.to_array() + extra_hi * BDNA_RISE_PER_BP * unit

    updated = helix.model_copy(
        update={
            "axis_start": Vec3.from_array(new_axis_start),
            "axis_end": Vec3.from_array(new_axis_end),
            "length_bp": new_hi - new_lo + 1,
            "bp_start": new_lo,
            # phase_offset is defined at local_bp=0 (= axis_start).  Moving axis_start
            # back by extra_lo steps means the old geometry now starts at local_bp=extra_lo,
            # so we subtract extra_lo × twist to keep the old nucleotides in place.
            "phase_offset": helix.phase_offset - extra_lo * helix.twist_per_bp_rad,
        }
    )

    def _apply(d: Design) -> None:
        for i, h in enumerate(d.helices):
            if h.id == helix_id:
                d.helices[i] = updated
                return

    label = f"Extend helix {_helix_label(design, helix_id)} · bp [{new_lo}, {new_hi}]"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="helix-extend",
        label=label,
        params={"helix_id": helix_id, **body.model_dump(mode="json")},
        fn=_apply,
    )
    return _design_response_with_geometry(design, report, changed_helix_ids=[helix_id])


@router.delete("/design/helices/{helix_id}")
def delete_helix(helix_id: str) -> dict:
    # Referential integrity check — reject if any strand domain references this helix.
    design = design_state.get_or_404()
    blocking = [
        s.id
        for s in design.strands
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

    label = f"Delete helix {_helix_label(design, helix_id)}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="helix-delete",
        label=label,
        params={"helix_id": helix_id},
        fn=_apply,
    )
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
    helix = _find_helix(design, body.helix_id)
    lt = design.lattice_type

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
    lo = max(body.lo_bp, h_lo)
    hi = min(body.hi_bp, h_hi)
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
                    detail=(
                        f"Scaffold domain already covers helix {body.helix_id!r} "
                        f"in range [{d_lo}, {d_hi}]."
                    ),
                )

    # Polarity: start_bp = 5' end
    if direction == Direction.FORWARD:
        start_bp, end_bp = lo, hi
    else:
        start_bp, end_bp = hi, lo  # REVERSE: 5' is at higher bp index

    new_strand = Strand(
        domains=[
            Domain(
                helix_id=body.helix_id,
                start_bp=start_bp,
                end_bp=end_bp,
                direction=direction,
            )
        ],
        strand_type=StrandType.SCAFFOLD,
    )

    def _apply(d: Design) -> None:
        d.strands.append(new_strand)

    label = (
        f"Scaffold paint · helix {_helix_label(design, body.helix_id)} bp [{lo}, {hi}]"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="scaffold-domain-paint",
        label=label,
        params={**body.model_dump(mode="json"), "_strand_id": new_strand.id},
        fn=_apply,
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
        staple_count = sum(
            1 for s in design_cur.strands if s.strand_type == StrandType.STAPLE
        )
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

    # Pen-tool auto-designation: a staple painted antiparallel over an existing
    # overhang becomes an OH binder linked to that overhang.
    if new_strand.strand_type == StrandType.STAPLE:
        from backend.core.lattice import tag_painted_binder

        new_strand = tag_painted_binder(design_cur, new_strand)

    def _apply(d: Design) -> None:
        d.strands.append(new_strand)

    label = f"Add {new_strand.strand_type.value} strand · {len(body.domains)} domain(s)"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strand-add",
        label=label,
        params={
            **body.model_dump(mode="json"),
            "_strand_id": new_strand.id,
            "_color": color,
        },
        fn=_apply,
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

    label = f"Update strand {strand_id} · {len(body.domains)} domain(s)"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strand-update",
        label=label,
        params={"strand_id": strand_id, **body.model_dump(mode="json")},
        fn=_apply,
    )
    return {
        "strand": replacement.model_dump(),
        **_design_response(design, report),
    }


@router.post("/design/strands/{strand_id}/convert-to-binder", status_code=200)
def convert_strand_to_binder_endpoint(strand_id: str) -> dict:
    """Re-designate a strand as an OH binder (overhang-binding oligo).

    Links each domain to the overhang it antiparallel-overlaps, tagging the
    partner region as an overhang if it isn't one yet. 404 if the strand is
    missing; 422 when the strand has no antiparallel partner to bind.
    """
    from backend.core.lattice import convert_strand_to_binder

    before_occ = _strand_occupancy(design_state.get_or_404())

    def _build(d: Design) -> Design:
        return convert_strand_to_binder(d, strand_id)

    try:
        design, report, _entry = design_state.mutate_with_feature_log(
            op_kind="overhang-bulk",
            label=f"Convert strand {strand_id} → OH binder",
            params={"strand_id": strand_id},
            fn=_build,
        )
    except ValueError as exc:
        msg = str(exc)
        status = 404 if "not found" in msg else 422
        raise HTTPException(status, detail=msg) from exc

    # Position-preserving retype (+ possible overhang re-tag) — reship only the
    # affected strands' helices instead of the whole design.
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


@router.post("/design/overhang/{overhang_id}/generate-binder", status_code=201)
def generate_binder_for_overhang_endpoint(overhang_id: str) -> dict:
    """Create a new OH-binder strand antiparallel to an overhang.

    Same length as the overhang, reverse complement of its sequence when set.
    404 if the overhang (or its backing domain) is missing.
    """
    from backend.core.lattice import make_binder_for_overhang

    def _build(d: Design) -> Design:
        return make_binder_for_overhang(d, overhang_id)

    try:
        design, report, _entry = design_state.mutate_with_feature_log(
            op_kind="overhang-bulk",
            label=f"Generate OH binding strand for {overhang_id}",
            params={"overhang_id": overhang_id},
            fn=_build,
        )
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc)) from exc

    return _design_response_with_geometry(design, report)


@router.post("/design/strands/{strand_id}/convert-to-scaffold", status_code=200)
def convert_binder_to_scaffold_endpoint(strand_id: str) -> dict:
    """Inverse of convert-to-binder: retype an OH-binder strand back to scaffold,
    clear its binder links, and remove any overhang the conversion auto-created
    once orphaned. 404 if the strand is missing.
    """
    from backend.core.lattice import convert_binder_to_scaffold

    before_occ = _strand_occupancy(design_state.get_or_404())

    def _build(d: Design) -> Design:
        return convert_binder_to_scaffold(d, strand_id)

    try:
        design, report, _entry = design_state.mutate_with_feature_log(
            op_kind="overhang-bulk",
            label=f"Convert strand {strand_id} → scaffold",
            params={"strand_id": strand_id},
            fn=_build,
        )
    except ValueError as exc:
        raise HTTPException(404, detail=str(exc)) from exc

    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


def _build_strand_end_resize(d: Design, body: "StrandEndResizeRequest") -> Design:
    """Pure builder for a strand end resize."""
    from backend.core.lattice import resize_strand_ends
    from backend.core.duplex import drop_invalid_duplexes

    out = resize_strand_ends(d, [entry.model_dump() for entry in body.entries])
    # A shrink can push a duplex register out of its (now shorter) domain; drop
    # such duplexes so the resize doesn't break the connections graph.
    return drop_invalid_duplexes(out)


@router.post("/design/strand-end-resize", status_code=200)
def strand_end_resize(body: StrandEndResizeRequest) -> dict:
    """Resize terminal strand domains from the 3D/cadnano drag handles."""
    try:
        n = len(body.entries)
        label = f"Resize {n} strand end{'s' if n != 1 else ''}"
        updated, report, _entry = design_state.mutate_with_minor_log(
            op_subtype="strand-end-resize",
            label=label,
            params=body.model_dump(mode="json"),
            fn=lambda d: _build_strand_end_resize(d, body),
        )
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "unknown"
        raise HTTPException(
            404, detail=f"Resize target not found: {missing!r}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    # A resize only touches geometry on the entries' helices (the terminal domain
    # + any inline-overhang split/merge live on that same helix). Ship just those
    # helices' nucleotides + (grown/shrunk) axes instead of recomputing the whole
    # design's geometry — ~16× faster on large designs (332 ms → 20 ms on a 16k-nuc
    # design). The frontend's _scaffoldCoverageChanged guard forces a correct full
    # JS rebuild from the merged geometry when nuc count / coverage changed.
    changed_helix_ids = list({entry.helix_id for entry in body.entries})
    return _design_response_with_geometry(
        updated,
        report,
        changed_helix_ids=changed_helix_ids,
        partial_axes=True,
    )


def _build_domain_shift(d: Design, body: "DomainShiftRequest") -> Design:
    """Pure builder for a domain-shift batch."""
    from backend.core.lattice import shift_domains
    from backend.core.duplex import shift_duplex_ends, drop_invalid_duplexes

    # Map each moved overhang → its Δbp (pre-shift), so its duplex ends move with
    # it and the SAME bases stay paired (Q1: a move preserves the register).
    deltas: dict[str, int] = {}
    for entry in body.entries:
        strand = next((s for s in d.strands if s.id == entry.strand_id), None)
        if strand and 0 <= entry.domain_index < len(strand.domains):
            oid = strand.domains[entry.domain_index].overhang_id
            if oid:
                deltas[oid] = deltas.get(oid, 0) + entry.delta_bp
    out = shift_domains(d, [entry.model_dump() for entry in body.entries])
    out = shift_duplex_ends(out, deltas)
    return drop_invalid_duplexes(out)


@router.post("/design/domain-shift", status_code=200)
def domain_shift(body: DomainShiftRequest) -> dict:
    """Shift one or more whole domains by a signed bp offset (cadnano drag-to-move)."""
    if not body.entries:
        raise HTTPException(400, detail="domain-shift requires at least one entry.")
    try:
        n = len(body.entries)
        deltas = {entry.delta_bp for entry in body.entries}
        if len(deltas) == 1:
            d = next(iter(deltas))
            label = f"Shift {n} domain{'s' if n != 1 else ''} by {d:+d} bp"
        else:
            label = f"Shift {n} domains"
        updated, report, _entry = design_state.mutate_with_minor_log(
            op_subtype="domain-shift",
            label=label,
            params=body.model_dump(mode="json"),
            fn=lambda d: _build_domain_shift(d, body),
        )
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "unknown"
        raise HTTPException(
            404, detail=f"Domain-shift target not found: {missing!r}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return _design_response_with_geometry(updated, report)


def _build_delete_strands_batch(d: Design, body: "StrandBatchDeleteRequest") -> Design:
    """Pure builder: remove specified strands (handling linker connections too)
    and re-detect overhangs on now-orphaned ends."""
    from backend.core.lattice import autodetect_all_overhangs

    id_set = set(body.strand_ids)
    missing = id_set - {s.id for s in d.strands}
    if missing:
        raise HTTPException(404, detail=f"Strand ID(s) not found: {sorted(missing)}")

    existing_conn_ids = {conn.id for conn in d.overhang_connections}
    linker_conn_ids = {
        conn_id
        for strand_id in id_set
        if (conn_id := _linker_conn_id_from_strand_id(strand_id)) in existing_conn_ids
    }
    linker_strand_ids = {
        s.id
        for s in d.strands
        if _linker_conn_id_from_strand_id(s.id) in linker_conn_ids
    }
    regular_ids = id_set - linker_strand_ids

    out = _delete_linker_connections_from_design(d, linker_conn_ids)
    out = _delete_regular_strands_from_design(out, regular_ids)
    return autodetect_all_overhangs(out)


@router.delete("/design/strands/batch", status_code=200)
def delete_strands_batch(body: StrandBatchDeleteRequest) -> dict:
    """Delete multiple strands by ID in one operation."""
    before_occ = _strand_occupancy(design_state.get_or_404())
    n = len(body.strand_ids)
    label = f"Delete {n} strand{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strand-delete-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=lambda d: _build_delete_strands_batch(d, body),
    )
    # Deletion moves no nucleotide — reship only the deleted strands' helices
    # (+ any helix where autodetect re-tagged a now-orphaned end as an overhang,
    # caught by the occupancy diff) instead of recomputing the whole design.
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


def _build_delete_strand(d: Design, strand_id: str) -> Design:
    """Pure builder: delete a single strand (handling linker connections too)
    and re-detect overhangs on now-orphaned ends."""
    from backend.core.lattice import autodetect_all_overhangs

    _find_strand(d, strand_id)  # 404 if not found

    existing_conn_ids = {conn.id for conn in d.overhang_connections}
    linker_conn_id = _linker_conn_id_from_strand_id(strand_id)
    if linker_conn_id in existing_conn_ids:
        out = _delete_linker_connections_from_design(d, {linker_conn_id})
    else:
        out = _delete_regular_strands_from_design(d, {strand_id})

    # Re-run overhang detection: deleting a strand (especially a scaffold segment)
    # may leave staple terminal domains on now-scaffold-free helices that should
    # be registered as overhangs. autodetect_all_overhangs is idempotent — already-
    # tagged domains are untouched; only newly eligible ends get OverhangSpec entries.
    return autodetect_all_overhangs(out)


@router.delete("/design/strands/{strand_id}")
def delete_strand(strand_id: str) -> dict:
    before_occ = _strand_occupancy(design_state.get_or_404())
    label = f"Delete strand {strand_id}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strand-delete",
        label=label,
        params={"strand_id": strand_id},
        fn=lambda d: _build_delete_strand(d, strand_id),
    )
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


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

    label = (
        f"Add domain · helix {_helix_label(design_state.get_or_404(), body.helix_id)} "
        f"bp [{body.start_bp}, {body.end_bp}] {body.direction.value}"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="domain-add",
        label=label,
        params={"strand_id": strand_id, **body.model_dump(mode="json")},
        fn=_apply,
    )
    strand = _find_strand(design, strand_id)
    return {
        "strand": strand.model_dump(),
        **_design_response(design, report),
    }


def _build_delete_domain(d: Design, strand_id: str, domain_index: int) -> Design:
    """Pure builder for deleting a single domain (handles linker-strand cleanup
    and orphan-strand removal)."""
    strand = _find_strand(d, strand_id)
    if domain_index < 0 or domain_index >= len(strand.domains):
        raise HTTPException(400, detail=f"domain_index {domain_index} out of range.")

    existing_conn_ids = {conn.id for conn in d.overhang_connections}
    linker_conn_id = _linker_conn_id_from_strand_id(strand_id)
    if linker_conn_id in existing_conn_ids:
        return _delete_linker_connections_from_design(d, {linker_conn_id})

    # Capture overhang_id before mutation so we can clean up the spec.
    removed_ovhg_id = strand.domains[domain_index].overhang_id
    out = d.model_copy(deep=True)
    s = _find_strand(out, strand_id)
    s.domains.pop(domain_index)
    if removed_ovhg_id is not None:
        out.overhangs = [o for o in out.overhangs if o.id != removed_ovhg_id]
    # If no domains remain, remove the whole strand to avoid an orphan.
    if not s.domains:
        out.strands = [st for st in out.strands if st.id != strand_id]
    return out


@router.delete("/design/strands/{strand_id}/domains/{domain_index}")
def delete_domain(strand_id: str, domain_index: int) -> dict:
    label = f"Delete domain · {strand_id}[{domain_index}]"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="domain-delete",
        label=label,
        params={"strand_id": strand_id, "domain_index": domain_index},
        fn=lambda d: _build_delete_domain(d, strand_id, domain_index),
    )
    # Strand may have been auto-removed; return None strand in that case.
    try:
        strand = _find_strand(design, strand_id)
        strand_dict = strand.model_dump()
    except HTTPException:
        strand_dict = None
    return {
        "strand": strand_dict,
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
                part_a = strand.model_copy(
                    update={"domains": list(strand.domains[: di + 1])}
                )
                part_b = Strand(
                    domains=list(strand.domains[di + 1 :]),
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


def _build_terminal_maps(design: "Design") -> tuple[dict, dict]:
    """Return (three_prime, five_prime) dicts keyed by (helix_id, bp, direction)
    mapping to the Strand whose 3'-end / 5'-start is at that slot. Used by
    _ligate_crossover and unligated_crossover_ids."""
    three_prime: dict[tuple[str, int, "Direction"], "Strand"] = {}
    five_prime: dict[tuple[str, int, "Direction"], "Strand"] = {}
    for s in design.strands:
        if not s.domains:
            continue
        ld = s.domains[-1]
        three_prime[(ld.helix_id, ld.end_bp, ld.direction)] = s
        fd = s.domains[0]
        five_prime[(fd.helix_id, fd.start_bp, fd.direction)] = s
    return three_prime, five_prime


def _ligate_crossover(design: "Design", xover: "Crossover") -> tuple["Design", bool]:
    """Ligate the two strand fragments connected by a crossover.

    Finds the strand whose 3' end matches one half and the strand whose 5'
    start matches the other half, then joins them into a single multi-domain
    strand via _ligate().

    Returns (design, ligated) where ligated is True iff a merge happened.
    Returns (design unchanged, False) when no matching pair is found OR when
    both halves resolve to the same strand (would close a cycle — circular
    strands aren't a first-class concept in the model). Callers can use the
    bool to surface a placement_warning.
    """
    from backend.core.lattice import _ligate

    ha, hb = xover.half_a, xover.half_b
    three_prime, five_prime = _build_terminal_maps(design)

    # Try: 3' on half_a → 5' on half_b
    s_from = three_prime.get((ha.helix_id, ha.index, ha.strand))
    s_to = five_prime.get((hb.helix_id, hb.index, hb.strand))
    if s_from is not None and s_to is not None and s_from.id != s_to.id:
        return _ligate(design, s_from, s_to), True

    # Try reverse: 3' on half_b → 5' on half_a
    s_from = three_prime.get((hb.helix_id, hb.index, hb.strand))
    s_to = five_prime.get((ha.helix_id, ha.index, ha.strand))
    if s_from is not None and s_to is not None and s_from.id != s_to.id:
        return _ligate(design, s_from, s_to), True

    return design, False


def unligated_crossover_ids(design: "Design") -> list[str]:
    """IDs of crossovers whose two halves currently resolve to the same strand
    (i.e. ligating would close a cycle, so _ligate_crossover skipped them).

    Derived — recompute on every design-bearing response. The marker auto-
    clears when the user nicks the strand: nick splits the strand → the two
    halves resolve to different strands → no longer in this set.
    """
    three_prime, five_prime = _build_terminal_maps(design)
    out: list[str] = []
    for x in design.crossovers:
        ha, hb = x.half_a, x.half_b
        for a, b in ((ha, hb), (hb, ha)):
            sf = three_prime.get((a.helix_id, a.index, a.strand))
            st = five_prime.get((b.helix_id, b.index, b.strand))
            if sf is not None and st is not None and sf.id == st.id:
                out.append(x.id)
                break
    return out


class PlaceCrossoverRequest(BaseModel):
    half_a: HalfCrossoverRequest
    half_b: HalfCrossoverRequest
    nick_bp_a: int
    nick_bp_b: int
    process_id: Optional[str] = "manual"


def _nick_if_needed(
    d: "Design", helix_id: str, bp_index: int, direction: "Direction"
) -> "Design":
    """Nick at (helix_id, bp_index, direction) unless the strand already
    terminates there.  No-op cases:
    • "terminus" — bp_index is the 3′ end of the strand (already nicked).
    • "No strand covers" — bp_index is outside any strand's range, meaning
      the strand's 5′ end is already at or past this position (e.g. nick at
      bp −1 when the strand starts at bp 0, from the HC 20|0 period wrap).
    • inter-domain boundary — bp_index is at the end of a domain in a
      multi-domain strand (a crossover junction). The backbone already
      leaves this helix here; splitting would undo a prior crossover's
      ligation.
    • 1-nt terminal stub — the nick would produce a single-nucleotide fragment
      at a strand terminus.  This happens when the extension placed the domain
      terminus exactly at the crossover bp so no nick is needed; ligation will
      find the terminus directly via the five_prime/three_prime endpoint map.
        FORWARD first-domain nick at start_bp  → 1-nt left stub
        FORWARD last-domain nick at end_bp-1   → 1-nt right stub
        REVERSE first-domain nick at start_bp  → 1-nt left stub
        REVERSE last-domain nick at end_bp+1   → 1-nt right stub"""
    from backend.core.lattice import _find_strand_at, make_nick

    try:
        strand, domain_idx = _find_strand_at(d, helix_id, bp_index, direction)
    except ValueError:
        return d  # no strand covers this position — no-op
    domain = strand.domains[domain_idx]
    n_doms = len(strand.domains)
    if bp_index == domain.end_bp and domain_idx < n_doms - 1:
        # Only a CROSS-helix boundary is a crossover junction we must not undo.
        # A same-helix boundary (e.g. an inline-overhang tail continuing on this
        # helix) is not a junction — nick through it, severing the beyond-part into
        # its own strand so bp_index becomes a terminus the crossover can ligate to.
        if strand.domains[domain_idx + 1].helix_id != helix_id:
            return d  # cross-helix crossover junction — no-op
    # NOTE: no 1-nt-stub guard here.  A nick that lands one bp inside a strand's
    # terminus (or on a first domain's 5′ start) legitimately splits off a single-
    # nucleotide stub — that is the intended result when a crossover sits just
    # short of a strand end (crossover_edge_cases helices 0/1).  Crossovers that
    # land *exactly* on an existing junction are rejected upstream in
    # _build_place_crossover; a crossover exactly on a free terminus is a no-op
    # via the make_nick "terminus" branch below.
    try:
        return make_nick(d, helix_id, bp_index, direction)
    except ValueError as exc:
        if "terminus" in str(exc):
            return d  # already nicked — no-op
        raise


def _strip_orphan_inline_overhangs(design: "Design") -> "Design":
    """Clear ``ovhg_inline_*`` tags from strands that have no paired anchor domain.

    An inline overhang is, by definition, an unpaired *tail* on a scaffold-paired
    staple. When a crossover nicks through a same-helix overhang boundary, the
    overhang sub-domain can be severed into its own strand — which then has no
    paired anchor, so it is just a plain unpaired staple, not an overhang. This
    enforces that invariant (and drops the now-orphaned auto-created OverhangSpec).
    User-placed / extruded overhangs (non ``ovhg_inline_`` ids) are untouched.
    """
    _INLINE = "ovhg_inline_"
    dropped: set[str] = set()
    new_strands = []
    changed = False
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE:
            new_strands.append(s)
            continue
        # A "paired anchor" domain is any domain that is NOT an inline overhang.
        has_anchor = any(
            not (d.overhang_id and d.overhang_id.startswith(_INLINE)) for d in s.domains
        )
        if has_anchor:
            new_strands.append(s)
            continue
        new_doms = []
        for d in s.domains:
            if d.overhang_id and d.overhang_id.startswith(_INLINE):
                dropped.add(d.overhang_id)
                new_doms.append(d.model_copy(update={"overhang_id": None}))
            else:
                new_doms.append(d)
        new_strands.append(s.model_copy(update={"domains": new_doms}))
        changed = True
    if not changed:
        return design
    new_overhangs = [o for o in design.overhangs if o.id not in dropped]
    return design.copy_with(strands=new_strands, overhangs=new_overhangs)


def _build_place_crossover(
    d: Design, body: "PlaceCrossoverRequest"
) -> tuple[Design, "Crossover", bool]:
    """Pure builder: nick + ligate + record one crossover.

    Returns (new design, xover, ligated). `ligated` is False iff the crossover's
    two halves resolved to the same strand (would close a cycle); the crossover
    is still recorded but the strands stay split. Caller can surface a
    placement_warning.

    CROSSOVER = nick + ligate + record. If changing this, ask user first.
    """
    from backend.core.crossover_positions import (
        build_strand_ranges,
        crossover_junction_slots,
        slot_covered,
        validate_crossover,
    )

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
    # Reject a crossover that lands on an existing crossover junction (either half).
    # Checked on the pre-nick design so the nicks we are about to place don't count
    # as junctions. Free termini / helix-end u-turns are not junctions → still allowed.
    # Slots backed by a recorded Crossover fall through to validate_crossover's more
    # specific "already occupied" error (duplicate placement).
    junctions = crossover_junction_slots(d)
    recorded = set()
    for xo in d.crossovers:
        recorded.add((xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand))
        recorded.add((xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand))
    for half in (half_a, half_b):
        slot = (half.helix_id, half.index, half.strand)
        if slot in junctions and slot not in recorded:
            raise HTTPException(
                422,
                detail=(
                    f"Crossover slot (helix {_helix_label(d, half.helix_id)}, bp "
                    f"{half.index}, {half.strand.value}) is already a crossover junction"
                ),
            )

    # Reject a crossover at the extreme edge of strand coverage. A crossover
    # connects material on the side its bow points — bow-right (the sprite is the
    # upper member of the pair, min(nick) < index) toward bp index+1, bow-left
    # toward index-1. That side must have strand on both helices, else the
    # crossover would only join a stub (nothing beyond the rightmost/leftmost bp).
    lower_bp = min(body.nick_bp_a, body.nick_bp_b)
    required_bp = half_a.index + 1 if lower_bp < half_a.index else half_a.index - 1
    sr = build_strand_ranges(d)
    if not (
        slot_covered(sr, half_a.helix_id, required_bp, half_a.strand.value)
        and slot_covered(sr, half_b.helix_id, required_bp, half_b.strand.value)
    ):
        raise HTTPException(
            422,
            detail=(
                f"Crossover at bp {half_a.index} has no strand at bp {required_bp} "
                "on the side it would connect toward (nothing beyond the edge)"
            ),
        )

    current = _nick_if_needed(
        d, body.half_a.helix_id, body.nick_bp_a, body.half_a.strand
    )
    current = _nick_if_needed(
        current, body.half_b.helix_id, body.nick_bp_b, body.half_b.strand
    )

    err = validate_crossover(current, half_a, half_b)
    if err:
        raise HTTPException(400, detail=err)

    xover = Crossover(half_a=half_a, half_b=half_b, process_id=body.process_id)
    # Build a new crossovers list so the snapshot reference in undo history
    # is not mutated (copy_with is shallow).
    current = current.copy_with(crossovers=list(current.crossovers) + [xover])
    current, ligated = _ligate_crossover(current, xover)
    # A same-helix overhang tail severed by this crossover becomes a standalone
    # unpaired staple — no longer an overhang. Enforce that invariant.
    current = _strip_orphan_inline_overhangs(current)
    return current, xover, ligated


@router.post("/design/crossovers/place", status_code=201)
def place_crossover(body: PlaceCrossoverRequest) -> dict:
    """Place a crossover atomically: nick + ligate + record.

    CROSSOVER = nick + ligate + record. If changing this, ask user first.

    Logged as a child of the open Fine Routing cluster.
    """
    holder: dict = {}

    def _fn(d: Design) -> Design:
        try:
            current, xover, ligated = _build_place_crossover(d, body)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        holder["xover"] = xover
        holder["ligated"] = ligated
        return current

    _d = design_state.get_or_404()
    label = (
        f"Crossover h{_helix_label(_d, body.half_a.helix_id)} ↔ "
        f"h{_helix_label(_d, body.half_b.helix_id)} bp {body.half_a.index}"
    )
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-place",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    resp = {
        "crossover": holder["xover"].model_dump(),
        **_design_response_with_geometry(current, report),
    }
    if not holder.get("ligated"):
        x = holder["xover"]
        resp["placement_warnings"] = [
            f"Crossover at h{_helix_label(current, x.half_a.helix_id)} ↔ "
            f"h{_helix_label(current, x.half_b.helix_id)} bp {x.half_a.index} "
            "left unligated to avoid circular strand. Nick the strand to ligate."
        ]
    return resp


class PlaceCrossoverBatchRequest(BaseModel):
    placements: list[PlaceCrossoverRequest]


def _build_place_crossover_batch(
    d: Design, body: "PlaceCrossoverBatchRequest"
) -> tuple[Design, list, list]:
    """Pure builder: place multiple crossovers in order.

    Returns (new design, [xovers], [skipped_xover_ids]). skipped_xover_ids
    lists crossovers that were recorded but left unligated (would have
    circularized a strand).
    """
    current = d
    new_crossovers = []
    skipped_ids: list[str] = []
    for p in body.placements:
        current, xover, ligated = _build_place_crossover(current, p)
        new_crossovers.append(xover)
        if not ligated:
            skipped_ids.append(xover.id)
    return current, new_crossovers, skipped_ids


@router.post("/design/crossovers/place-batch", status_code=201)
def place_crossover_batch(body: PlaceCrossoverBatchRequest) -> dict:
    """Place multiple crossovers atomically under a single Fine Routing entry."""
    holder: dict = {}

    def _fn(d: Design) -> Design:
        try:
            current, new_crossovers, skipped_ids = _build_place_crossover_batch(d, body)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        holder["xovers"] = new_crossovers
        holder["skipped_ids"] = skipped_ids
        return current

    n = len(body.placements)
    label = f"Place {n} crossover{'s' if n != 1 else ''}"
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-place-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    resp = {
        "crossovers": [x.model_dump() for x in holder["xovers"]],
        **_design_response_with_geometry(current, report),
    }
    skipped = holder.get("skipped_ids") or []
    if skipped:
        m = len(skipped)
        resp["placement_warnings"] = [
            f"Placed {n} crossover{'s' if n != 1 else ''} — {m} left unligated to "
            f"avoid circular strand{'s' if m != 1 else ''}. Nick the strand to ligate."
        ]
    return resp


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

    Crossovers are placed everywhere a valid bow site survives the gates, except
    within 7 (HC) / 8 (SQ) bp of an internal scaffold seam (a double scaffold
    crossover).  A single pass of :func:`_place_auto_crossovers` is order-dependent and
    starves some valid sites (see its WARNING), so this iterates it to a FIXPOINT —
    each re-run starts from the placed + re-ligated state and fills the gaps.
    """
    design = design_state.get_or_404()
    new_design = design
    placed_total = 0
    sites_considered = 0
    for _ in range(12):  # safety bound; placement is monotonic so it converges fast
        new_design, stats = _place_auto_crossovers(new_design)
        sites_considered = sites_considered or stats["sites_considered"]
        placed_total += stats["placed"]
        if stats["placed"] == 0:
            break
    stats = {"sites_considered": sites_considered, "placed": placed_total}

    current, report, _entry = design_state.mutate_with_feature_log(
        op_kind="auto-crossover",
        label="Auto-crossover",
        params={
            "sites_considered": stats["sites_considered"],
            "placed": stats["placed"],
        },
        fn=lambda _d: new_design,
    )
    print(f"[AUTO XOVER] placed {stats['placed']} crossovers", flush=True)
    return _design_response_with_geometry(current, report)


def _place_auto_crossovers(
    design: Design,
    protected_strand_ids: frozenset[str] = frozenset(),
    *,
    tip_only_strand_ids: frozenset[str] = frozenset(),
) -> tuple[Design, dict]:
    """Place all possible staple crossovers, skipping a margin around scaffold seams.

    Pure core shared by the ``/design/crossovers/auto`` endpoint and full-autostaple.
    A staple crossover is placed at most valid bow sites except where it falls within
    ``7`` (HC) / ``8`` (SQ) bp of an internal scaffold *seam* — a double scaffold
    crossover (see :func:`scaffold_seam_positions`).  Single u-turn end caps are not
    seams, so they are not excluded.

    WARNING — ONE call is a SINGLE order-dependent pass, NOT a full-density guarantee.
    Each placement nicks the two staples in-place and ``sr`` (the staple-coverage
    map) is recomputed every iteration, but fragments are only re-ligated once at the
    very end.  So as the pass proceeds the staples become progressively fragmented,
    and the ``_staple_arm_too_short`` / ``_coverage_hole`` gates below can FALSELY
    reject a later bow site whose arm was shortened by an earlier nearby placement.
    The result is order-dependent gaps: valid sites — including one half of a
    double-crossover pair, which then renders as a lone, "wrong-bowing" arc — get
    silently skipped.  **Both callers therefore iterate this to a fixpoint** (re-run
    until a pass places 0): each re-run starts from the already-placed + re-ligated
    state and fills the gaps.  Keep this function a single pass; do the looping in the
    caller so locked/overhang protection can be re-detected on the re-ligated strands.

    ``protected_strand_ids`` names hand-routed staples (manual crossovers / forced
    ligations) that full-autostaple must not disturb: any bow site whose nick would
    land inside one of these strands is skipped, so auto-crossovers route *around*
    them instead of splitting them — the whole staple is protected.

    ``tip_only_strand_ids`` names overhang staples.  An overhang is *embedded* in the
    duplex structure, not a standalone strand, so its duplex **body** must still be
    woven in with crossovers — only its overhang TIP / binder domains (those carrying
    ``overhang_id`` / ``binds_overhang_id``) are protected here.  This decouples
    crossover routing from the linearization protection (where overhang staples are
    kept whole to preserve their ``overhang_id``).
    """
    from backend.core.crossover_positions import (
        all_valid_crossover_sites,
        build_strand_ranges,
        scaffold_seam_positions,
        slot_covered,
        validate_crossover,
    )
    from backend.core.lattice import ligate_crossover_chains

    hc_bow_right: frozenset[int] = frozenset({0, 7, 14})
    sq_bow_right: frozenset[int] = frozenset({0, 8, 16, 24})
    is_hc = design.lattice_type.value == "HONEYCOMB"
    period = 21 if is_hc else 32
    bow_right = hc_bow_right if is_hc else sq_bow_right

    occupied: set[tuple[str, int, str]] = set()
    for xo in design.crossovers:
        occupied.add((xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value))
        occupied.add((xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand.value))

    # Positions covered by hand-routed strands that must not be split: a bow site
    # whose nick lands here is skipped so crossovers route around them.  Locked
    # staples are protected whole; overhang staples are protected only on their
    # overhang TIP / binder domains so the duplex body stays eligible for crossovers.
    protected_pos: set[tuple[str, int, str]] = set()
    for s in design.strands:
        tip_only = s.id in tip_only_strand_ids
        # Overhang (tip-only) protection WINS over locked-full protection: an overhang
        # staple is routinely flagged "locked" by its own overhang-attachment forced
        # ligation, but that must not protect its duplex body — only the tip.  Genuine
        # locked (hand-routed) non-overhang staples are still protected whole.
        fully = s.id in protected_strand_ids and not tip_only
        if not (fully or tip_only):
            continue
        for d in s.domains:
            if not fully and not (
                d.overhang_id is not None or d.binds_overhang_id is not None
            ):
                continue  # overhang body domain — leave eligible so it gets woven in
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            for b in range(lo, hi + 1):
                protected_pos.add((d.helix_id, b, d.direction.value))

    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}

    def _scaffold_fwd(helix_id: str) -> bool:
        h = helix_map.get(helix_id)
        if h is None:
            return True
        row, col = h.grid_pos
        return (row + col) % 2 == 0

    # Internal scaffold seams (double scaffold crossovers).  Staple crossovers are
    # excluded within `seam_margin` bp of a seam; end caps get full density.
    seams = scaffold_seam_positions(design)
    seam_margin = 7 if is_hc else 8

    sites = all_valid_crossover_sites(design)
    min_autocrossover_segment_nt = 7 if is_hc else 8
    seen_pairs: set[tuple[str, str, int]] = set()
    current = design
    placed = 0

    for site in sites:
        hid_a = site["helix_a_id"]
        hid_b = site["helix_b_id"]
        bp = site["index"]
        pair_key = (min(hid_a, hid_b), max(hid_a, hid_b), bp)
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        fwd_a = _scaffold_fwd(hid_a)
        stap_a = "REVERSE" if fwd_a else "FORWARD"
        stap_b = "FORWARD" if fwd_a else "REVERSE"
        lower_bp = bp - 1 if (bp % period) in bow_right else bp
        nick_a = lower_bp if stap_a == "FORWARD" else lower_bp + 1
        nick_b = lower_bp if stap_b == "FORWARD" else lower_bp + 1

        # Route around hand-routed strands: skip a site whose arm/nick would fall
        # inside a protected staple on either helix.
        if protected_pos and any(
            (hid, b, sd) in protected_pos
            for hid, sd in ((hid_a, stap_a), (hid_b, stap_b))
            for b in (lower_bp, lower_bp + 1)
        ):
            continue

        if any(
            any(abs(lower_bp - sp) <= seam_margin for sp in seams.get(hid, ()))
            for hid in (hid_a, hid_b)
        ):
            continue

        sr = build_strand_ranges(
            current.model_copy(update={"strands": current.active_strands()})
        )
        ha = helix_map.get(hid_a)
        hb = helix_map.get(hid_b)
        ha_min = ha.bp_start if ha else 0
        ha_max = (ha.bp_start + ha.length_bp - 1) if ha else 0
        hb_min = hb.bp_start if hb else 0
        hb_max = (hb.bp_start + hb.length_bp - 1) if hb else 0

        # Intended behaviour: place every valid bow site (matching the standalone
        # auto-crossover endpoint and the hand-routed convention).  In practice the
        # single-pass order dependence documented in this function's WARNING means
        # some valid sites are starved on any one pass — do NOT read this as a
        # full-density guarantee.
        # Staple nicks are routed AT bow columns by the break stage
        # (allow_crossover_breaks=True), so no phase thinning is needed to leave
        # mid-arm room — the seam bow-phase carries the nick, the others carry
        # crossovers (the honeycomb/square staple-seam pattern).

        # Match the standalone auto-crossover endpoint: only skip a site that
        # would leave a staple arm shorter than the lattice min segment, measured
        # against the STAPLE STRAND's own coverage boundary — which is wherever
        # the user put it, and may end well short of the scaffold (ssDNA loop).

        def _staple_arm_too_short(hid: str, stap_dir: str) -> bool:
            for lo, hi in sr.get((hid, stap_dir), []):
                if lo <= lower_bp <= hi:
                    left_len = lower_bp - lo + 1
                    right_len = hi - lower_bp
                    return (
                        0 < left_len < min_autocrossover_segment_nt
                        or 0 < right_len < min_autocrossover_segment_nt
                    )
            return False

        if _staple_arm_too_short(hid_a, stap_a) or _staple_arm_too_short(hid_b, stap_b):
            continue

        # A staple's extent is the USER'S INTENT.  Scaffold with no staple opposite
        # it is a deliberate ssDNA loop (they suppress aggregation by blunt-end
        # stacking), so EVERY staple-interval boundary is a legitimate 5'/3'
        # terminus — not only the ones at the bundle caps.  Ask the same question
        # manual placement asks (`_build_place_crossover`): a crossover connects
        # material on the side its bow points — bow-right (min(nick) < index)
        # toward bp index+1, bow-left toward index-1.  That bp must carry staple on
        # BOTH helices, else the crossover joins nothing but a stub.  A nick landing
        # in the ssDNA loop itself is a no-op (`_nick_if_needed` finds no strand).
        #
        # The old test asked instead whether an unstapled bp fell inside the slot's
        # global [min, max] staple span, and rejected it as an accidental hole.  That
        # holds only when every ssDNA loop is at a helix end; designs with interior
        # loops (a comb/"teeth" cross-section) had their tooth-edge crossovers
        # silently starved, while the identical site at a bundle cap was allowed.
        required_bp = bp + 1 if lower_bp < bp else bp - 1
        if not (
            slot_covered(sr, hid_a, required_bp, stap_a)
            and slot_covered(sr, hid_b, required_bp, stap_b)
        ):
            continue
        if (hid_a, bp, stap_a) in occupied or (hid_b, bp, stap_b) in occupied:
            continue

        dir_a = Direction.FORWARD if stap_a == "FORWARD" else Direction.REVERSE
        dir_b = Direction.FORWARD if stap_b == "FORWARD" else Direction.REVERSE
        if ha_min <= nick_a <= ha_max:
            current = _nick_if_needed(current, hid_a, nick_a, dir_a)
        if hb_min <= nick_b <= hb_max:
            current = _nick_if_needed(current, hid_b, nick_b, dir_b)

        half_a = HalfCrossover(helix_id=hid_a, index=bp, strand=dir_a)
        half_b = HalfCrossover(helix_id=hid_b, index=bp, strand=dir_b)
        if validate_crossover(current, half_a, half_b):
            continue
        xover = Crossover(half_a=half_a, half_b=half_b, process_id="auto_crossover")
        current = current.copy_with(crossovers=list(current.crossovers) + [xover])
        occupied.add((hid_a, bp, stap_a))
        occupied.add((hid_b, bp, stap_b))
        placed += 1

    current = ligate_crossover_chains(current)
    return current, {"sites_considered": len(sites), "placed": placed}


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
            eb = crossover_neighbor(
                design.lattice_type, *h_a.grid_pos, idx, is_scaffold=is_scaf
            )
            ea = crossover_neighbor(
                design.lattice_type, *h_b.grid_pos, idx, is_scaffold=is_scaf
            )
            if (eb is not None and eb == tuple(h_b.grid_pos)) or (
                ea is not None and ea == tuple(h_a.grid_pos)
            ):
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
            if (
                half.helix_id == xover.half_a.helix_id
                and half.index == new_index
                and half.strand == xover.half_a.strand
            ):
                raise HTTPException(
                    422,
                    detail=f"Position {new_index} on helix A already occupied by another crossover",
                )
            if (
                half.helix_id == xover.half_b.helix_id
                and half.index == new_index
                and half.strand == xover.half_b.strand
            ):
                raise HTTPException(
                    422,
                    detail=f"Position {new_index} on helix B already occupied by another crossover",
                )

    # ── Find the two adjacent domains that the crossover connects ────────────
    # Same lookup logic as _desplice_strands_for_crossover: consecutive domains
    # d0.end_bp == old_index → d1.start_bp == old_index.
    found = None
    for ha_half, hb_half in [
        (xover.half_a, xover.half_b),
        (xover.half_b, xover.half_a),
    ]:
        if found:
            break
        for strand in design.strands:
            if found:
                break
            for di in range(len(strand.domains) - 1):
                d0 = strand.domains[di]
                d1 = strand.domains[di + 1]
                if (
                    d0.helix_id == ha_half.helix_id
                    and d0.direction == ha_half.strand
                    and d0.end_bp == old_index
                    and d1.helix_id == hb_half.helix_id
                    and d1.direction == hb_half.strand
                    and d1.start_bp == old_index
                ):
                    found = (strand, di, d0, d1)
                    break

    if found is None:
        raise HTTPException(
            422, detail="Could not find adjacent domains for this crossover"
        )

    strand, di, d0, d1 = found

    # ── Validate resized domains ─────────────────────────────────────────────
    new_d0_end = new_index
    new_d1_start = new_index

    # Domains must remain at least 1 bp long
    d0_lo = min(d0.start_bp, new_d0_end)
    d0_hi = max(d0.start_bp, new_d0_end)
    d1_lo = min(new_d1_start, d1.end_bp)
    d1_hi = max(new_d1_start, d1.end_bp)

    if d0_lo > d0_hi:
        raise HTTPException(
            422, detail="Moving crossover would make domain on first helix empty"
        )
    if d1_lo > d1_hi:
        raise HTTPException(
            422, detail="Moving crossover would make domain on second helix empty"
        )

    # Check overlap with other domains on same helix+direction
    def _overlaps(
        helix_id: str,
        direction,
        new_lo: int,
        new_hi: int,
        exclude_strand_id: str,
        exclude_dom_idx: int,
    ) -> bool:
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
        raise HTTPException(
            422,
            detail="Moving crossover would overlap with existing domain on first helix",
        )
    if _overlaps(d1.helix_id, d1.direction, d1_lo, d1_hi, strand.id, di + 1):
        raise HTTPException(
            422,
            detail="Moving crossover would overlap with existing domain on second helix",
        )

    # ── Apply the move ───────────────────────────────────────────────────────
    # (No explicit design_state.snapshot() — the mutate_with_minor_log wrapper
    # at the end handles undo bookkeeping in one place.)

    # Update crossover index
    new_crossovers = []
    for xo in design.crossovers:
        if xo.id == body.crossover_id:
            new_crossovers.append(
                xo.model_copy(
                    update={
                        "half_a": xo.half_a.model_copy(update={"index": new_index}),
                        "half_b": xo.half_b.model_copy(update={"index": new_index}),
                    }
                )
            )
        else:
            new_crossovers.append(xo)

    # Update domains
    new_domains = list(strand.domains)
    new_domains[di] = d0.model_copy(update={"end_bp": new_d0_end})
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
        dx = bx.x - ax.x
        dy = bx.y - ax.y
        dz = bx.z - ax.z
        length_nm = _math.sqrt(dx * dx + dy * dy + dz * dz)
        if length_nm < 1e-9:
            ux = uy = 0.0
            uz = 1.0
        else:
            ux = dx / length_nm
            uy = dy / length_nm
            uz = dz / length_nm

        new_bp_start = helix.bp_start
        new_length_bp = helix.length_bp
        new_axis_start = ax
        new_phase = helix.phase_offset

        if check_lo < helix.bp_start:
            extra = helix.bp_start - check_lo
            new_axis_start = Vec3(
                x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                z=ax.z - extra * BDNA_RISE_PER_BP * uz,
            )
            new_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
            new_bp_start = check_lo
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

    label = (
        f"Move crossover h{_helix_label(design, xover.half_a.helix_id)} ↔ "
        f"h{_helix_label(design, xover.half_b.helix_id)} · bp {old_index} → {new_index}"
    )
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-move",
        label=label,
        params=body.model_dump(mode="json"),
        fn=lambda _d: updated,
    )
    changed_helix_ids = list({d0.helix_id, d1.helix_id})
    return _design_response_with_geometry(
        updated, report, changed_helix_ids=changed_helix_ids
    )


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
            raise HTTPException(
                422, detail="Crossover helices missing or have no grid_pos"
            )

        valid = False
        for is_scaf in (False, True):
            eb = crossover_neighbor(
                design.lattice_type, *h_a.grid_pos, new_index, is_scaffold=is_scaf
            )
            ea = crossover_neighbor(
                design.lattice_type, *h_b.grid_pos, new_index, is_scaffold=is_scaf
            )
            if (eb is not None and eb == tuple(h_b.grid_pos)) or (
                ea is not None and ea == tuple(h_a.grid_pos)
            ):
                valid = True
                break
        if not valid:
            raise HTTPException(
                422, detail=f"Index {new_index} is not a valid crossover site"
            )

        # Check occupancy — skip crossovers that are also being moved in this batch
        for xo in design.crossovers:
            if xo.id == m.crossover_id or xo.id in move_ids:
                continue
            for half in (xo.half_a, xo.half_b):
                if (
                    half.helix_id == xover.half_a.helix_id
                    and half.index == new_index
                    and half.strand == xover.half_a.strand
                ):
                    raise HTTPException(
                        422, detail=f"Position {new_index} already occupied"
                    )
                if (
                    half.helix_id == xover.half_b.helix_id
                    and half.index == new_index
                    and half.strand == xover.half_b.strand
                ):
                    raise HTTPException(
                        422, detail=f"Position {new_index} already occupied"
                    )

        # Find adjacent domains
        found = None
        for ha_half, hb_half in [
            (xover.half_a, xover.half_b),
            (xover.half_b, xover.half_a),
        ]:
            if found:
                break
            for strand in design.strands:
                if found:
                    break
                for di in range(len(strand.domains) - 1):
                    d0 = strand.domains[di]
                    d1 = strand.domains[di + 1]
                    if (
                        d0.helix_id == ha_half.helix_id
                        and d0.direction == ha_half.strand
                        and d0.end_bp == old_index
                        and d1.helix_id == hb_half.helix_id
                        and d1.direction == hb_half.strand
                        and d1.start_bp == old_index
                    ):
                        found = (strand, di, d0, d1)
                        break

        if found is None:
            raise HTTPException(
                422, detail="Could not find adjacent domains for crossover"
            )

        move_infos.append((xover, new_index, *found))

    # ── Phase 2: Apply all moves atomically ──────────────────────────────
    def _apply(d: "Design") -> None:
        nonlocal changed_helix_ids

        # Update crossover indices
        xover_updates = {m.crossover_id: m.new_index for m in moves}
        for i, xo in enumerate(d.crossovers):
            if xo.id in xover_updates:
                ni = xover_updates[xo.id]
                d.crossovers[i] = xo.model_copy(
                    update={
                        "half_a": xo.half_a.model_copy(update={"index": ni}),
                        "half_b": xo.half_b.model_copy(update={"index": ni}),
                    }
                )

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
                new_doms[di] = new_doms[di].model_copy(update={"end_bp": new_index})
                new_doms[di + 1] = new_doms[di + 1].model_copy(
                    update={"start_bp": new_index}
                )
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
                dx = bx.x - ax.x
                dy = bx.y - ax.y
                dz = bx.z - ax.z
                length_nm = _math.sqrt(dx * dx + dy * dy + dz * dz)
                if length_nm < 1e-9:
                    ux = uy = 0.0
                    uz = 1.0
                else:
                    ux = dx / length_nm
                    uy = dy / length_nm
                    uz = dz / length_nm

                new_bp_start = helix.bp_start
                new_length_bp = helix.length_bp
                new_axis_start = ax
                new_phase = helix.phase_offset
                new_axis_end = helix.axis_end

                if check_lo < helix.bp_start:
                    extra = helix.bp_start - check_lo
                    new_axis_start = Vec3(
                        x=ax.x - extra * BDNA_RISE_PER_BP * ux,
                        y=ax.y - extra * BDNA_RISE_PER_BP * uy,
                        z=ax.z - extra * BDNA_RISE_PER_BP * uz,
                    )
                    new_phase = helix.phase_offset - extra * helix.twist_per_bp_rad
                    new_bp_start = check_lo
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

    n = len(moves)
    label = f"Move {n} crossover{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-move-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_apply,
    )
    return _design_response_with_geometry(
        design, report, changed_helix_ids=list(changed_helix_ids)
    )


@router.delete("/design/crossovers/{crossover_id}", status_code=200)
def delete_crossover(crossover_id: str) -> dict:
    """Remove a crossover by ID.

    If the crossover joins two domains within a multi-domain strand, the
    strand is split back into two single-helix fragments (desplice).
    """
    design = design_state.get_or_404()
    before_occ = _strand_occupancy(design)
    xover = next((x for x in design.crossovers if x.id == crossover_id), None)
    if xover is None:
        raise HTTPException(404, detail=f"Crossover {crossover_id!r} not found.")

    new_strands = _desplice_strands_for_crossover(design, xover.half_a, xover.half_b)

    def _apply(d: Design) -> None:
        d.crossovers = [x for x in d.crossovers if x.id != crossover_id]
        d.strands = new_strands

    label = (
        f"Delete crossover h{_helix_label(design, xover.half_a.helix_id)} ↔ "
        f"h{_helix_label(design, xover.half_b.helix_id)} bp {xover.half_a.index}"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-delete",
        label=label,
        params={"crossover_id": crossover_id},
        fn=_apply,
    )
    # Desplice moves no nucleotide — it only splits a strand at the junction and
    # retags the fragment. Reship just the affected strands' helices.
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


@router.post("/design/crossovers/batch-delete", status_code=200)
def batch_delete_crossovers(body: BatchDeleteCrossoversRequest) -> dict:
    """Remove multiple crossovers in a single atomic operation.

    Each crossover is despliced (strand split) in sequence on the same design
    snapshot, then validated and geometry-recomputed once at the end.
    """
    design = design_state.get_or_404()
    before_occ = _strand_occupancy(design)
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

    n = len(ids_to_delete)
    label = f"Delete {n} crossover{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-delete-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_apply,
    )
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


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

    id_to_seq: dict[str, str] = {
        e.crossover_id: e.sequence.upper() for e in body.entries
    }
    missing = [
        cid for cid in id_to_seq if not any(x.id == cid for x in design.crossovers)
    ]
    if missing:
        raise HTTPException(404, detail=f"Crossovers not found: {missing}")

    def _apply(d: "Design") -> None:
        for xo in d.crossovers:
            if xo.id in id_to_seq:
                seq = id_to_seq[xo.id]
                xo.extra_bases = seq if seq else None

    n = len(id_to_seq)
    label = f"Set extra bases on {n} crossover{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-extra-bases-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_apply,
    )
    return _design_response_with_geometry(design, report)


@router.patch("/design/crossovers/{crossover_id}/extra-bases", status_code=200)
def patch_crossover_extra_bases(
    crossover_id: str, body: CrossoverExtraBasesRequest
) -> dict:
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

    label = f"Extra bases on crossover {crossover_id} · {seq or '(cleared)'}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="crossover-extra-bases",
        label=label,
        params={"crossover_id": crossover_id, **body.model_dump(mode="json")},
        fn=_apply,
    )
    return _design_response_with_geometry(design, report)


@router.patch("/design/forced-ligations/{fl_id}/extra-bases", status_code=200)
def patch_forced_ligation_extra_bases(
    fl_id: str, body: CrossoverExtraBasesRequest
) -> dict:
    """Set (or clear) extra bases on a single forced ligation junction.

    sequence must match [ACGTNacgtn]*.  Pass an empty string to remove extra bases.
    """
    if not _EXTRA_BASES_RE.match(body.sequence):
        raise HTTPException(
            422,
            detail=f"Sequence {body.sequence!r} contains invalid bases. "
            f"Only A, T, G, C, N are allowed.",
        )

    design = design_state.get_or_404()
    fl = next((f for f in design.forced_ligations if f.id == fl_id), None)
    if fl is None:
        raise HTTPException(404, detail=f"Forced ligation {fl_id!r} not found.")

    seq = body.sequence.upper()

    def _apply(d: "Design") -> None:
        for f in d.forced_ligations:
            if f.id == fl_id:
                f.extra_bases = seq if seq else None
                break

    label = f"Extra bases on forced ligation {fl_id} · {seq or '(cleared)'}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="forced-ligation-extra-bases",
        label=label,
        params={"fl_id": fl_id, **body.model_dump(mode="json")},
        fn=_apply,
    )
    return _design_response_with_geometry(design, report)


def _build_nick(design: Design, body: "NickRequest") -> Design:
    """Pure builder for a nick: ``make_nick`` + auto-color any new staple
    fragments using the palette indexing rule. Used by both the live
    endpoint and the mid-cluster replay dispatcher.
    """
    from backend.core.lattice import make_nick

    updated = make_nick(design, body.helix_id, body.bp_index, body.direction)

    # Assign palette color to only the newly created strand(s) — do NOT touch
    # existing strands, which the 3D view already colors by geometry order.
    original_ids = {s.id for s in design.strands}
    original_staple_count = sum(
        1 for s in design.strands if s.strand_type == StrandType.STAPLE
    )
    palette_idx = original_staple_count
    new_strands_list = []
    any_colored = False
    for s in updated.strands:
        if (
            s.id not in original_ids
            and s.strand_type == StrandType.STAPLE
            and s.color is None
        ):
            new_strands_list.append(
                s.model_copy(
                    update={"color": STAPLE_PALETTE[palette_idx % len(STAPLE_PALETTE)]}
                )
            )
            palette_idx += 1
            any_colored = True
        else:
            new_strands_list.append(s)
    if any_colored:
        updated = updated.model_copy(update={"strands": new_strands_list})
    return updated


def _helix_label(design: Design, helix_id: str) -> str:
    """Resolve a helix to its short display label for feature-log entries.

    Convention (mirrors pathview.js / sliceview.js gutter rendering):
      * Use ``helix.label`` when explicitly set (e.g. scadnano helix index).
      * Otherwise use the positional index in ``design.helices``.
      * Fall back to the raw helix_id only if the helix is missing (defensive).

    Result is always a short string suitable for in-line labels (e.g.
    ``"13"`` rather than ``"h_xy_3_0"``).
    """
    for i, h in enumerate(design.helices):
        if h.id == helix_id:
            return str(h.label) if h.label is not None else str(i)
    return helix_id


def _label_nick(design: Design, body: "NickRequest") -> str:
    """Compose the rendered detail line for a nick log entry."""
    return f"Nick: helix {_helix_label(design, body.helix_id)} bp {body.bp_index} {body.direction.value}"


@router.post("/design/nick", status_code=201)
def add_nick(body: NickRequest) -> dict:
    """Create a nick (strand break) at the 3′ side of the specified nucleotide.

    The strand covering (helix_id, bp_index, direction) is split: bp_index
    becomes the 3′ end of the left fragment; the next nucleotide in 5′→3′ order
    becomes the 5′ end of the right fragment.

    Raises 400 if bp_index is the 3′ terminus of the strand (nothing to split).

    Logged as a child of the open Fine Routing cluster (or starts a new cluster
    if the last log entry isn't one).
    """
    from backend.core.lattice import _find_strand_at

    design = design_state.get_or_404()

    # Identify all helices belonging to the nicked strand BEFORE the nick.
    # A nick at a crossover boundary splits the strand across helices, so the
    # partial geometry response must include every helix whose nucleotides
    # change strand_id — not just the helix where the nick is placed.
    try:
        nicked_strand, _ = _find_strand_at(
            design, body.helix_id, body.bp_index, body.direction
        )
    except ValueError:
        nicked_strand = None
    changed_hids = (
        list({dom.helix_id for dom in nicked_strand.domains})
        if nicked_strand
        else [body.helix_id]
    )

    label = _label_nick(design, body)
    try:
        updated, report, _entry = design_state.mutate_with_minor_log(
            op_subtype="nick",
            label=label,
            params=body.model_dump(mode="json"),
            fn=lambda d: _build_nick(d, body),
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return _design_response_with_geometry(
        updated, report, changed_helix_ids=changed_hids
    )


@router.post("/design/ligate", status_code=200)
def ligate_strand(body: NickRequest) -> dict:
    """Repair a nick (ligate) by merging the two strand ends adjacent to the nick.

    Uses the same request shape as POST /design/nick.  body.bp_index is the 3′ end
    bp of the left fragment (identical convention to make_nick).

    Finds strand A (3′ end at bp_index) and strand B (5′ end at the adjacent bp),
    then merges them into a single strand.  The two terminal domains — which are
    adjacent on the same helix with the same direction — are collapsed into one.
    """
    design = design_state.get_or_404()

    helix_id = body.helix_id
    bp_index = body.bp_index
    direction = body.direction
    adj_bp = bp_index + 1 if direction == Direction.FORWARD else bp_index - 1
    label = (
        f"Ligate helix {_helix_label(design, helix_id)} bp {bp_index} {direction.value}"
    )

    # ── Same-strand domain merge ─────────────────────────────────────────────
    # If a single strand has two adjacent domains at this boundary (e.g. from
    # a forced ligation), merge them — this is the inverse of a nick.
    for s in design.strands:
        for di in range(len(s.domains) - 1):
            d_left = s.domains[di]
            d_right = s.domains[di + 1]
            if (
                d_left.helix_id == helix_id
                and d_left.direction == direction
                and d_left.end_bp == bp_index
                and d_right.helix_id == helix_id
                and d_right.direction == direction
                and d_right.start_bp == adj_bp
            ):
                merged_dom = Domain(
                    helix_id=helix_id,
                    start_bp=d_left.start_bp,
                    end_bp=d_right.end_bp,
                    direction=direction,
                )
                new_domains = (
                    list(s.domains[:di]) + [merged_dom] + list(s.domains[di + 2 :])
                )
                patched = s.model_copy(
                    update={
                        "domains": new_domains,
                        "sequence": None,
                    }
                )

                def _apply_merge(d: Design, *, sid=s.id, p=patched) -> None:
                    d.strands = [p if st.id == sid else st for st in d.strands]

                design, report, _entry = design_state.mutate_with_minor_log(
                    op_subtype="ligate",
                    label=label,
                    params=body.model_dump(mode="json"),
                    fn=_apply_merge,
                )
                return _design_response(design, report)

    # ── Cross-strand ligation ────────────────────────────────────────────────
    # Find strand A: 3′ terminus at bp_index
    strand_a: Strand | None = None
    for s in design.strands:
        if not s.domains:
            continue
        last = s.domains[-1]
        if (
            last.helix_id == helix_id
            and last.direction == direction
            and last.end_bp == bp_index
        ):
            strand_a = s
            break
    if strand_a is None:
        raise HTTPException(
            404,
            detail=(
                f"No strand has a 3′ end at helix={helix_id!r} bp={bp_index} "
                f"direction={direction.value}."
            ),
        )

    # Find strand B: 5′ terminus at adj_bp
    strand_b: Strand | None = None
    for s in design.strands:
        if not s.domains:
            continue
        first = s.domains[0]
        if (
            first.helix_id == helix_id
            and first.direction == direction
            and first.start_bp == adj_bp
        ):
            strand_b = s
            break
    if strand_b is None:
        raise HTTPException(
            404,
            detail=(
                f"No strand has a 5′ end at helix={helix_id!r} bp={adj_bp} "
                f"direction={direction.value}."
            ),
        )
    if strand_b.id == strand_a.id:
        raise HTTPException(409, detail="Cannot ligate a strand to itself.")

    # Merge the two touching domains into one, combine domain lists
    dom_a_last = strand_a.domains[-1]
    dom_b_first = strand_b.domains[0]
    merged_dom = Domain(
        helix_id=helix_id,
        start_bp=dom_a_last.start_bp,
        end_bp=dom_b_first.end_bp,
        direction=direction,
    )
    merged_domains = (
        list(strand_a.domains[:-1]) + [merged_dom] + list(strand_b.domains[1:])
    )

    merged_strand = Strand(
        id=strand_a.id,
        domains=merged_domains,
        strand_type=strand_a.strand_type,
        color=strand_a.color,
        sequence=None,  # topology changed — clear sequence
    )

    def _apply(d: Design) -> None:
        new_strands = []
        for s in d.strands:
            if s.id == strand_b.id:
                continue  # drop strand B (absorbed into A)
            elif s.id == strand_a.id:
                new_strands.append(merged_strand)  # replace A with merged
            else:
                new_strands.append(s)
        d.strands = new_strands

    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="ligate",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_apply,
    )
    return _design_response(design, report)


# ── Forced ligation (manual pencil-tool only — NOT for autocrossover) ────────


class ForcedLigationRequest(BaseModel):
    """Connect any 3' end to any 5' end, bypassing crossover lookup tables.

    This is a manual user action only (pencil tool).  It must never be called
    by autocrossover, autobreak, or any automated pipeline.
    """

    three_prime_strand_id: str  # strand whose 3' end we connect FROM
    five_prime_strand_id: str  # strand whose 5' end we connect TO
    is_periodic_seam: bool = (
        False  # True if made across the 2D periodic-boundary mirror
    )


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

    design = design_state.get_or_404()

    strand_a: Strand | None = None
    strand_b: Strand | None = None
    for s in design.strands:
        if s.id == body.three_prime_strand_id:
            strand_a = s
        if s.id == body.five_prime_strand_id:
            strand_b = s
    if strand_a is None:
        raise HTTPException(
            404, detail=f"3' strand {body.three_prime_strand_id!r} not found."
        )
    if strand_b is None:
        raise HTTPException(
            404, detail=f"5' strand {body.five_prime_strand_id!r} not found."
        )
    if strand_a.id == strand_b.id:
        raise HTTPException(
            409,
            detail="Cannot ligate a strand to itself (would create circular strand).",
        )

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
        is_periodic_seam=body.is_periodic_seam,
    )

    current = _ligate(design, strand_a, strand_b)
    current = current.model_copy(
        update={
            "forced_ligations": list(current.forced_ligations) + [fl],
        }
    )

    label = (
        f"Forced ligation · h{_helix_label(design, three_dom.helix_id)}:{three_dom.end_bp} "
        f"→ h{_helix_label(design, five_dom.helix_id)}:{five_dom.start_bp}"
    )
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="forced-ligation-create",
        label=label,
        params={**body.model_dump(mode="json"), "_fl_id": fl.id},
        fn=lambda _d: current,
    )
    # A ligation moves NO nucleotide — it only re-tags strand_b's nucs onto
    # strand_a and clears the two junction end-flags. So ship geometry for just
    # the two strands' helices (partial fast path) instead of recomputing the
    # whole design (~560 ms → a few ms on a 26-helix design). Extensions are
    # only emitted in full-geometry mode, and _ligate can drop a 5' extension /
    # remap a 3' one, so fall back to full when either strand carries one.
    touches_extension = any(
        ext.strand_id in (strand_a.id, strand_b.id) for ext in design.extensions
    )
    changed_helix_ids = (
        None
        if touches_extension
        else list({d.helix_id for d in (*strand_a.domains, *strand_b.domains)})
    )
    return _design_response_with_geometry(
        current, report, changed_helix_ids=changed_helix_ids
    )


@router.delete("/design/forced-ligations/{fl_id}", status_code=200)
def delete_forced_ligation(fl_id: str) -> dict:
    """Remove a forced ligation by ID.

    Splits the strand at the forced-ligation junction back into two fragments
    and removes the ForcedLigation record from the design.
    """

    design = design_state.get_or_404()
    before_occ = _strand_occupancy(design)
    fl = next((f for f in design.forced_ligations if f.id == fl_id), None)
    if fl is None:
        raise HTTPException(404, detail=f"Forced ligation {fl_id!r} not found.")

    # Find the strand containing the junction and split it.
    new_strands = list(design.strands)
    for strand in design.strands:
        for di in range(len(strand.domains) - 1):
            d0 = strand.domains[di]
            d1 = strand.domains[di + 1]
            if (
                d0.helix_id == fl.three_prime_helix_id
                and d0.end_bp == fl.three_prime_bp
                and d0.direction == fl.three_prime_direction
                and d1.helix_id == fl.five_prime_helix_id
                and d1.start_bp == fl.five_prime_bp
                and d1.direction == fl.five_prime_direction
            ):
                part_a = strand.model_copy(
                    update={"domains": list(strand.domains[: di + 1])}
                )
                part_b = Strand(
                    domains=list(strand.domains[di + 1 :]),
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

    label = (
        f"Delete forced ligation · h{_helix_label(design, fl.three_prime_helix_id)}:{fl.three_prime_bp} "
        f"→ h{_helix_label(design, fl.five_prime_helix_id)}:{fl.five_prime_bp}"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="forced-ligation-delete",
        label=label,
        params={"fl_id": fl_id},
        fn=_apply,
    )
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


class BatchDeleteForcedLigationsRequest(BaseModel):
    forced_ligation_ids: list[str]


@router.post("/design/forced-ligations/batch-delete", status_code=200)
def batch_delete_forced_ligations(body: BatchDeleteForcedLigationsRequest) -> dict:
    """Remove multiple forced ligations in a single atomic operation."""
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    before_occ = _strand_occupancy(design)
    ids_to_delete = set(body.forced_ligation_ids)
    if not ids_to_delete:
        report = validate_design(design)
        return _design_response_with_geometry(design, report)

    existing_ids = {f.id for f in design.forced_ligations}
    missing = ids_to_delete - existing_ids
    if missing:
        raise HTTPException(
            404, detail=f"Forced ligations not found: {sorted(missing)}"
        )

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
                    if (
                        d0.helix_id == fl.three_prime_helix_id
                        and d0.end_bp == fl.three_prime_bp
                        and d0.direction == fl.three_prime_direction
                        and d1.helix_id == fl.five_prime_helix_id
                        and d1.start_bp == fl.five_prime_bp
                        and d1.direction == fl.five_prime_direction
                    ):
                        part_a = strand.model_copy(
                            update={"domains": list(strand.domains[: di + 1])}
                        )
                        part_b = Strand(
                            domains=list(strand.domains[di + 1 :]),
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
        d.forced_ligations = [
            f for f in d.forced_ligations if f.id not in ids_to_delete
        ]

    n = len(ids_to_delete)
    label = f"Delete {n} forced ligation{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="forced-ligation-delete-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_apply,
    )
    changed = _local_changed_helices(before_occ, _strand_occupancy(design))
    return _design_response_with_geometry(
        design, report, changed_helix_ids=changed, partial_axes=True
    )


def _build_nick_batch(d: Design, body: "NickBatchRequest") -> Design:
    """Pure builder: apply multiple nicks in order, skipping any that fail."""
    from backend.core.lattice import make_nick

    current = d
    for nick in body.nicks:
        try:
            current = make_nick(current, nick.helix_id, nick.bp_index, nick.direction)
        except ValueError:
            continue
    return current


@router.post("/design/nick/batch", status_code=201)
def add_nick_batch(body: NickBatchRequest) -> dict:
    """Nick at multiple positions in one operation."""
    from backend.core.lattice import _find_strand_at

    design = design_state.get_or_404()
    all_changed: set[str] = set()

    for nick in body.nicks:
        # Collect all helix IDs from the strand being nicked (not just the
        # nick helix) so that cross-helix strand splits update all affected nucs.
        try:
            nicked_strand, _ = _find_strand_at(
                design, nick.helix_id, nick.bp_index, nick.direction
            )
            all_changed.update(dom.helix_id for dom in nicked_strand.domains)
        except ValueError:
            all_changed.add(nick.helix_id)

    n = len(body.nicks)
    label = f"{n} nick{'s' if n != 1 else ''} (batch)"
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="nick-batch",
        label=label,
        params=body.model_dump(mode="json"),
        fn=lambda d: _build_nick_batch(d, body),
    )
    changed_helix_ids = list(all_changed) if all_changed else None
    return _design_response_with_geometry(
        current, report, changed_helix_ids=changed_helix_ids
    )


class OverhangExtrudeRequest(BaseModel):
    helix_id: str
    bp_index: int
    direction: Direction
    is_five_prime: bool
    neighbor_row: int
    neighbor_col: int
    length_bp: int


def _build_overhang_extrude(
    d: Design, body: "OverhangExtrudeRequest"
) -> tuple[Design, "MutationReport"]:
    """Pure builder for a single-helix overhang extrude.

    Returns ``(design_after, mutation_report)``. The report's
    ``new_helix_origins`` map pins any freshly-created helix to the
    extruded-from parent helix, so the cluster reconciler inherits the
    parent's cluster membership (and therefore its transform) instead of
    falling back to ``_infer_origin_via_lattice_neighbors`` — which can
    pick a non-parent neighbour by lex tiebreak when multiple eligible
    helices are within Manhattan distance 2 on the lattice grid.
    """
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_overhang_extrude, overhang_candidate_error

    # Placement gate (mirrors the UI overhang tool): reject any position the tool
    # would not offer — neighbour must be a vacant nearest-neighbour cell at the
    # staple end's Z whose direction the backbone bead faces.  Enforced here at the
    # endpoint/generation layer so the UI, direct API, and headless build all get a
    # 400; the core ``make_overhang_extrude`` primitive stays ungated for geometry
    # unit tests that probe arbitrary positions.
    orig_helix = d.find_helix(body.helix_id)
    if orig_helix is not None:
        gate_err = overhang_candidate_error(
            d,
            orig_helix,
            body.bp_index,
            body.direction,
            body.neighbor_row,
            body.neighbor_col,
        )
        if gate_err:
            raise ValueError(gate_err)

    before_helix_ids = {h.id for h in d.helices}
    out = make_overhang_extrude(
        d,
        body.helix_id,
        body.bp_index,
        body.direction,
        body.is_five_prime,
        body.neighbor_row,
        body.neighbor_col,
        body.length_bp,
    )
    after_helix_ids = {h.id for h in out.helices}
    new_helix_ids = after_helix_ids - before_helix_ids

    origins: dict[str, str | None] = {
        new_hid: body.helix_id for new_hid in new_helix_ids
    }
    return out, MutationReport(new_helix_origins=origins)


@router.post("/design/overhang/extrude", status_code=200)
def overhang_extrude(body: OverhangExtrudeRequest) -> dict:
    """Extrude a staple-only overhang from a nick into an unoccupied honeycomb neighbour.

    Creates a new helix at (neighbor_row, neighbor_col) and extends the existing
    staple strand at (helix_id, bp_index) with a new domain in that helix.

    Emits a ``snapshot`` feature-log entry so the extrude can be reverted
    after a refresh and replayed via the edit-feature endpoint.
    """

    def _fn(d: Design) -> Design:
        try:
            return _build_overhang_extrude(d, body)
        except ValueError as exc:
            raise HTTPException(400, detail=str(exc)) from exc

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-extrude",
        label=f"Overhang extrude: {body.length_bp} bp",
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    # Embed geometry inline so design + nucleotides + helix_axes arrive in
    # ONE setState on the frontend. Without this the frontend does design
    # first, then a separate getGeometry round-trip; the design_renderer
    # rebuilds with the new helix BEFORE the transformed geometry arrives,
    # and the new helix's axis stick gets placed at its raw lattice position
    # (no cluster transform applied). See .claude/rules/rendering.md.
    return _design_response_with_geometry(updated, report)


class OverhangPatchRequest(BaseModel):
    sequence: str | None = None
    label: str | None = None
    rotation: list[float] | None = (
        None  # unit quaternion [qx, qy, qz, qw]; None = no change
    )
    # When True, skip the auto re-derivation of staple sequences after a sequence write.
    # Used by the connection-CREATION flow, which sets both overhangs' sequences then
    # immediately applies the connection (which re-derives once, with the FINAL topology) —
    # so the intermediate per-set re-derivations are redundant. Standalone edits leave this
    # False (default) and re-derive as before.
    defer_reassign: bool = False


def _build_overhang_patch(
    design: Design, overhang_id: str, body: "OverhangPatchRequest"
) -> tuple[Design, dict, OverhangSpec]:
    """Pure builder for patch_overhang. Returns (updated_design, spec_updates, new_spec).

    Raises HTTPException for validation errors (404, 409, 422). Does NOT mutate
    feature_log or push to history — that bookkeeping is the caller's choice
    (design-mode path appends OverhangRotationLogEntry inline; assembly-mode
    path wraps the whole thing in a SnapshotLogEntry).
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    import math as _math

    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")

    is_inline = overhang_id.startswith("ovhg_inline_")
    # For inline overhangs the ID encodes the end: ovhg_inline_{strand_id}_{5p|3p}
    inline_end: str | None = (
        overhang_id.rsplit("_", 1)[-1] if is_inline else None
    )  # "5p" or "3p"

    # ── Build updated OverhangSpec ────────────────────────────────────────────
    # Use model_fields_set so that an explicit {"sequence": null} (clear) is
    # distinguished from the field simply being absent from the request body.
    spec_updates: dict = {}
    sequence_was_set = "sequence" in body.model_fields_set
    if sequence_was_set:
        spec_updates["sequence"] = body.sequence.upper() if body.sequence else None
    if body.label is not None:
        spec_updates["label"] = body.label
    if body.rotation is not None:
        if len(body.rotation) != 4:
            raise HTTPException(
                422, detail="rotation must be a length-4 quaternion [qx, qy, qz, qw]."
            )
        import math as _math_rot

        mag = _math_rot.sqrt(sum(x * x for x in body.rotation))
        if abs(mag) < 1e-9:
            raise HTTPException(
                422, detail="rotation quaternion must not be zero-length."
            )
        # Normalise to unit quaternion in case of minor floating-point drift.
        spec_updates["rotation"] = [x / mag for x in body.rotation]

    # ── Sub-domain override conflict guard ──────────────────────────────────
    # A whole-overhang sequence write is incompatible with sub-domain
    # overrides because the override slices would be silently overwritten.
    # Require the user to clear them first (Phase 1 design contract).
    if sequence_was_set and body.sequence is not None:
        conflicting = [
            sd.id for sd in (spec.sub_domains or []) if sd.sequence_override is not None
        ]
        if conflicting:
            raise HTTPException(
                409,
                detail={
                    "detail": "Sub-domain overrides conflict with whole-overhang sequence write",
                    "sub_domain_ids": conflicting,
                },
            )

    new_seq: str | None = spec_updates.get("sequence", spec.sequence)
    new_length_bp: int | None = len(new_seq) if new_seq else None

    # ── Resize policy: last sub-domain absorbs Δ; reject pathological shrink ─
    # If the sequence write changes the backing domain length, we must update
    # the sub-domain tiling so that Σ length_bp == new_length_bp. Per the
    # locked design: the highest-offset sub-domain absorbs the delta.
    if new_length_bp is not None and spec.sub_domains:
        current_total = sum(sd.length_bp for sd in spec.sub_domains)
        delta = new_length_bp - current_total
        if delta != 0:
            sub_doms_sorted = sorted(
                spec.sub_domains, key=lambda sd: sd.start_bp_offset
            )
            last = sub_doms_sorted[-1]
            new_last_len = last.length_bp + delta
            if new_last_len < 1:
                raise HTTPException(
                    422,
                    detail=(
                        f"Shrink would reduce sub-domain {last.name!r} ({last.id}) "
                        f"below 1 bp; delete it (or another sub-domain) first."
                    ),
                )
            if last.sequence_override is not None and new_last_len < len(
                last.sequence_override
            ):
                raise HTTPException(
                    422,
                    detail=(
                        f"Shrink would shorten sub-domain {last.name!r} ({last.id}) "
                        f"below its locked override length ({len(last.sequence_override)} bp); "
                        f"clear the override first."
                    ),
                )
            new_sub_doms = [sd for sd in sub_doms_sorted[:-1]]
            new_sub_doms.append(
                last.model_copy(
                    update={
                        "length_bp": new_last_len,
                        # Annotation caches are stale once length changes.
                        "tm_celsius": None,
                        "gc_percent": None,
                        "hairpin_warning": False,
                        "dimer_warning": False,
                    }
                )
            )
            spec_updates["sub_domains"] = new_sub_doms
    elif new_length_bp is not None and not spec.sub_domains:
        # Edge case: backfill validator hasn't run (shouldn't happen post-load
        # because validators are always invoked). Insert a single whole-overhang
        # sub-domain matching the new length.
        from backend.core.models import (
            SubDomain as _SubDomain,
            NADOC_SUBDOMAIN_NS as _NS,
        )
        import uuid as _uuid_local

        spec_updates["sub_domains"] = [
            _SubDomain(
                id=str(_uuid_local.uuid5(_NS, f"{spec.id}:whole")),
                name="a",
                start_bp_offset=0,
                length_bp=new_length_bp,
            )
        ]

    new_spec = spec.model_copy(update=spec_updates)
    new_overhangs = [new_spec if o.id == overhang_id else o for o in design.overhangs]

    # ── Resize helix + domain when sequence length changes ───────────────────
    new_helices = list(design.helices)
    new_strands = list(design.strands)

    # For extrude-style overhangs we need the junction bp on the dedicated
    # helix. The junction can be at the helix's low (+Z extrude) OR high
    # (−Z extrude, axis flipped) bp end — see Bug 06.
    extrude_junction_bp: int | None = None
    if not is_inline:
        from backend.core.lattice import _overhang_junction_bp

        extrude_junction_bp = _overhang_junction_bp(design, spec.helix_id)

    if new_length_bp is not None:
        if not is_inline:
            # ── Extrude-style: resize the dedicated overhang helix ────────────
            # Keep the junction's world-space position fixed; move axis_start
            # inward/outward on the tip side. Correct for both +Z and −Z
            # extrudes (the latter has bp_start at the tip end of the bp range).
            for hi, helix in enumerate(new_helices):
                if helix.id != spec.helix_id:
                    continue
                if helix.length_bp == new_length_bp:
                    break
                ax = helix.axis_end.to_array() - helix.axis_start.to_array()
                ax_len = _math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2)
                if ax_len < 1e-9:
                    break
                unit = ax / ax_len
                if extrude_junction_bp is None:
                    # Fall back to legacy +Z behaviour if no crossover record.
                    new_len_nm = new_length_bp * BDNA_RISE_PER_BP
                    new_end = helix.axis_start.to_array() + unit * new_len_nm
                    new_helices[hi] = helix.model_copy(
                        update={
                            "length_bp": new_length_bp,
                            "axis_end": Vec3(
                                x=float(new_end[0]),
                                y=float(new_end[1]),
                                z=float(new_end[2]),
                            ),
                        }
                    )
                    break
                helix_lo = helix.bp_start
                helix_hi = helix.bp_start + helix.length_bp - 1
                # Find the current tip bp (the helix endpoint that is not the junction).
                tip_bp = helix_hi if extrude_junction_bp == helix_lo else helix_lo
                tip_sign = 1 if tip_bp > extrude_junction_bp else -1
                new_tip_bp = extrude_junction_bp + tip_sign * (new_length_bp - 1)
                new_bp_start = min(extrude_junction_bp, new_tip_bp)
                # Junction's world position from the current axis.
                local_junc_old = extrude_junction_bp - helix.bp_start
                junction_world = (
                    helix.axis_start.to_array()
                    + local_junc_old * BDNA_RISE_PER_BP * unit
                )
                # New axis_start = junction_world − (junction_local_new) * RISE * unit.
                local_junc_new = extrude_junction_bp - new_bp_start
                new_axis_start = (
                    junction_world - local_junc_new * BDNA_RISE_PER_BP * unit
                )
                new_axis_end = new_axis_start + new_length_bp * BDNA_RISE_PER_BP * unit
                new_helices[hi] = helix.model_copy(
                    update={
                        "length_bp": new_length_bp,
                        "bp_start": new_bp_start,
                        "axis_start": Vec3(
                            x=float(new_axis_start[0]),
                            y=float(new_axis_start[1]),
                            z=float(new_axis_start[2]),
                        ),
                        "axis_end": Vec3(
                            x=float(new_axis_end[0]),
                            y=float(new_axis_end[1]),
                            z=float(new_axis_end[2]),
                        ),
                    }
                )
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
                            new_domain = domain.model_copy(
                                update={"end_bp": domain.start_bp + new_length_bp - 1}
                            )
                        else:
                            # 5' junction = start_bp (fixed), 3' free = end_bp (lower)
                            new_domain = domain.model_copy(
                                update={"end_bp": domain.start_bp - (new_length_bp - 1)}
                            )
                    else:  # "5p"
                        if is_fwd:
                            # 3' junction = end_bp (fixed), 5' free = start_bp (lower)
                            new_domain = domain.model_copy(
                                update={"start_bp": domain.end_bp - (new_length_bp - 1)}
                            )
                        else:
                            # 3' junction = end_bp (fixed), 5' free = start_bp (higher)
                            new_domain = domain.model_copy(
                                update={"start_bp": domain.end_bp + (new_length_bp - 1)}
                            )

                    # Grow the main helix if the new domain falls outside its bounds
                    helix_idx = next(
                        (
                            hi
                            for hi, h in enumerate(new_helices)
                            if h.id == spec.helix_id
                        ),
                        None,
                    )
                    if helix_idx is not None:
                        h = new_helices[helix_idx]
                        free_bp = (
                            new_domain.end_bp
                            if inline_end == "3p"
                            else new_domain.start_bp
                        )
                        helix_end_bp = h.bp_start + h.length_bp - 1
                        ax = h.axis_end.to_array() - h.axis_start.to_array()
                        ax_len = _math.sqrt(ax[0] ** 2 + ax[1] ** 2 + ax[2] ** 2)
                        unit = ax / ax_len if ax_len > 1e-9 else ax
                        if free_bp < h.bp_start:
                            extra = h.bp_start - free_bp
                            new_start = (
                                h.axis_start.to_array()
                                - extra * BDNA_RISE_PER_BP * unit
                            )
                            new_helices[helix_idx] = h.model_copy(
                                update={
                                    "axis_start": Vec3(
                                        x=float(new_start[0]),
                                        y=float(new_start[1]),
                                        z=float(new_start[2]),
                                    ),
                                    "length_bp": h.length_bp + extra,
                                    "bp_start": free_bp,
                                    "phase_offset": h.phase_offset
                                    - extra * h.twist_per_bp_rad,
                                }
                            )
                        elif free_bp > helix_end_bp:
                            extra = free_bp - helix_end_bp
                            new_end = (
                                h.axis_end.to_array() + extra * BDNA_RISE_PER_BP * unit
                            )
                            new_helices[helix_idx] = h.model_copy(
                                update={
                                    "axis_end": Vec3(
                                        x=float(new_end[0]),
                                        y=float(new_end[1]),
                                        z=float(new_end[2]),
                                    ),
                                    "length_bp": h.length_bp + extra,
                                }
                            )
                else:
                    # Extrude-style: keep the junction bp fixed; move only the
                    # tip endpoint of the domain. The tip is whichever endpoint
                    # is NOT the junction. Works for +Z and −Z extrudes.
                    if extrude_junction_bp is None:
                        # Legacy fallback (no crossover record found).
                        if is_fwd:
                            new_domain = domain.model_copy(
                                update={"end_bp": domain.start_bp + new_length_bp - 1}
                            )
                        else:
                            new_domain = domain.model_copy(
                                update={"start_bp": domain.end_bp + new_length_bp - 1}
                            )
                    else:
                        if domain.start_bp == extrude_junction_bp:
                            tip_sign = 1 if domain.end_bp > domain.start_bp else -1
                            new_tip = domain.start_bp + tip_sign * (new_length_bp - 1)
                            new_domain = domain.model_copy(update={"end_bp": new_tip})
                        else:
                            tip_sign = 1 if domain.start_bp > domain.end_bp else -1
                            new_tip = domain.end_bp + tip_sign * (new_length_bp - 1)
                            new_domain = domain.model_copy(update={"start_bp": new_tip})

                new_domains = list(strand.domains)
                new_domains[di] = new_domain
                new_strands[si] = strand.model_copy(
                    update={"domains": new_domains, "sequence": None}
                )
                break

    updated = design.model_copy(
        update={
            "helices": new_helices,
            "strands": new_strands,
            "overhangs": new_overhangs,
        }
    )

    # When the sequence is cleared (no resize happened so strand.sequence was not
    # touched above), re-derive the strand's assembled sequence so the overhang
    # position reverts to N×len instead of retaining the old bases.
    if new_seq is None and "sequence" in body.model_fields_set:
        updated = _resplice_overhang_in_strand(updated, overhang_id, spec.strand_id)

    return updated, spec_updates, new_spec


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
    design = design_state.get_or_404()
    updated, spec_updates, new_spec = _build_overhang_patch(design, overhang_id, body)

    sequence_was_set = "sequence" in body.model_fields_set
    label_was_set = body.label is not None

    # Auto-assign on set: _build_overhang_patch cleared the parent strand's
    # sequence, so re-derive real bases for it AND any complement / binder domain
    # (binds_overhang_id) that reads this overhang's reverse-complement, so the
    # result is simulation-ready without a manual Assign Staple Sequences. No-op
    # until the scaffold is sequenced.
    #
    # TARGETED, not design-wide: only the strands derived from THIS overhang are
    # re-derived. A whole-design assign_staple_sequences here would silently wipe
    # any sequence the user typed by hand on an unrelated staple.
    if sequence_was_set and not body.defer_reassign:
        from backend.core.sequences import (
            overhang_dependent_strand_ids,
            reassign_strands,
        )

        affected = overhang_dependent_strand_ids(updated, [overhang_id])
        updated = reassign_strands(updated, affected)

    # A sequence (or label) write changes a build-fingerprint field, so it must
    # be a real feature-log step — otherwise seeking the slider back to this
    # state cannot reproduce it, the live design and the timeline silently
    # diverge, and an oxDNA job's out-of-date ⚠ can never clear (the assigned
    # sequence is invisible to the seek/staleness machinery). Record a snapshot
    # the same way overhang-extrude / overhang-bulk do; the snapshot's post-state
    # also captures a concurrent rotation, so the separate rotation delta below
    # is skipped in that case.
    if sequence_was_set or label_was_set:
        params: dict = {"overhang_id": overhang_id}
        if sequence_was_set:
            params["sequence"] = spec_updates.get("sequence")
        if label_was_set:
            params["label"] = body.label
        if body.rotation is not None:
            params["rotation"] = spec_updates["rotation"]
        log_label = (
            f"Overhang sequence: {spec_updates.get('sequence') or 'cleared'}"
            if sequence_was_set
            else f"Overhang label: {body.label}"
        )
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind="overhang-sequence",
            label=log_label,
            params=params,
            fn=lambda _d: updated,
        )
        return _design_response(updated, report)

    # Append rotation to feature log when rotation was changed.
    if body.rotation is not None:
        from backend.core.models import OverhangRotationLogEntry

        log = list(updated.feature_log)
        if updated.feature_log_cursor == -2:
            log = []
        elif updated.feature_log_cursor >= 0:
            log = log[: updated.feature_log_cursor + 1]
        log_entry = OverhangRotationLogEntry(
            overhang_ids=[overhang_id],
            rotations=[spec_updates["rotation"]],
            labels=[new_spec.label],
        )
        updated = updated.copy_with(
            feature_log=log + [log_entry],
            feature_log_cursor=-1,
        )

    updated, report = design_state.replace_with_reconcile(updated)
    # For rotation-only patches, embed geometry in the response so the frontend
    # can update design + geometry atomically in one store.setState (no intermediate
    # render from stale geometry).  Full geometry for topology-changing patches.
    rotation_only = body.rotation is not None
    if rotation_only:
        # Full geometry (no partial flag) forces a complete scene rebuild on the
        # frontend so backbone positions and slab normals are read fresh from the
        # server-computed arrays rather than relying on the in-memory preview state.
        return _design_response_with_geometry(updated, report)
    return _design_response(updated, report)


class OverhangRotationBatchItem(BaseModel):
    overhang_id: str
    rotation: List[float]  # [qx, qy, qz, qw]


class PatchOverhangRotationsBatchBody(BaseModel):
    ops: List[OverhangRotationBatchItem]


@router.patch("/design/overhangs/rotations", status_code=200)
def patch_overhang_rotations_batch(body: PatchOverhangRotationsBatchBody) -> dict:
    """Apply rotation changes to multiple overhangs atomically.

    All ops are applied in one atomic design update and appended as a single
    OverhangRotationLogEntry to the feature log so undo undoes the whole batch.
    """
    import math as _math_b
    from backend.core.models import OverhangRotationLogEntry
    from backend.core.validator import validate_design

    if not body.ops:
        design = design_state.get_or_404()
        return _design_response_with_geometry(design, validate_design(design))

    design = design_state.get_or_404()
    ovhg_map = {o.id: o for o in design.overhangs}

    normalised: list[OverhangRotationBatchItem] = []
    for item in body.ops:
        if item.overhang_id not in ovhg_map:
            raise HTTPException(404, detail=f"Overhang {item.overhang_id!r} not found.")
        if len(item.rotation) != 4:
            raise HTTPException(
                422, detail="rotation must be a length-4 quaternion [qx, qy, qz, qw]."
            )
        mag = _math_b.sqrt(sum(x * x for x in item.rotation))
        if abs(mag) < 1e-9:
            raise HTTPException(
                422, detail="rotation quaternion must not be zero-length."
            )
        normalised.append(
            OverhangRotationBatchItem(
                overhang_id=item.overhang_id,
                rotation=[x / mag for x in item.rotation],
            )
        )

    # Apply all rotations to overhangs list.
    rot_by_id = {n.overhang_id: n.rotation for n in normalised}
    new_overhangs = [
        o.model_copy(update={"rotation": rot_by_id[o.id]}) if o.id in rot_by_id else o
        for o in design.overhangs
    ]

    # Build feature log entry for the batch.
    log = list(design.feature_log)
    if design.feature_log_cursor == -2:
        log = []
    elif design.feature_log_cursor >= 0:
        log = log[: design.feature_log_cursor + 1]

    log_entry = OverhangRotationLogEntry(
        overhang_ids=[n.overhang_id for n in normalised],
        rotations=[n.rotation for n in normalised],
        labels=[ovhg_map[n.overhang_id].label for n in normalised],
    )

    updated = design.copy_with(
        overhangs=new_overhangs,
        feature_log=log + [log_entry],
        feature_log_cursor=-1,
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


# ── Phase 4: per-sub-domain (theta, phi) rotation endpoints ───────────────────
#
# These complement the existing whole-overhang rotation endpoints.  The chain
# of per-sub-domain rotations is consumed by
# ``backend.core.deformation.apply_overhang_rotation_if_needed`` at geometry
# time; the topology layer only stores (theta_deg, phi_deg) per SubDomain.
#
# Coalescing rule (commit:true only): when the previous feature_log entry is
# an OverhangRotationLogEntry whose ONLY slot matches (ovhg_id, sd_id) and
# whose timestamp is within 2s, we replace its slot's theta/phi in-place
# rather than appending a new entry. Keeps repeated drag-commits compact.


_SUBDOMAIN_COALESCE_WINDOW_S = 2.0


class SubDomainRotationPatchBody(BaseModel):
    theta_deg: float
    phi_deg: float
    commit: bool = False


def _validate_sd_angles(theta_deg: float, phi_deg: float) -> None:
    import math as _math

    if not _math.isfinite(float(theta_deg)) or not _math.isfinite(float(phi_deg)):
        raise HTTPException(422, detail="theta_deg and phi_deg must be finite.")
    if not (-180.0 <= float(theta_deg) <= 180.0):
        raise HTTPException(
            422, detail=f"theta_deg out of range [-180, 180]: {theta_deg}"
        )
    if not (0.0 <= float(phi_deg) <= 180.0):
        raise HTTPException(422, detail=f"phi_deg out of range [0, 180]: {phi_deg}")


def _set_subdomain_angles(
    design: Design,
    overhang_id: str,
    sub_domain_id: str,
    theta_deg: float,
    phi_deg: float,
) -> Design:
    """Return a new Design with the sub-domain's angles updated.

    Raises HTTPException 404 if the sub-domain doesn't exist.
    """
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )
    new_sd = sd.model_copy(
        update={
            "rotation_theta_deg": float(theta_deg),
            "rotation_phi_deg": float(phi_deg),
        }
    )
    new_sds = [new_sd if s.id == sub_domain_id else s for s in spec.sub_domains]
    new_spec = spec.model_copy(update={"sub_domains": new_sds})
    new_overhangs = [new_spec if o.id == overhang_id else o for o in design.overhangs]
    return design.copy_with(overhangs=new_overhangs)


def _try_coalesce_subdomain_rotation_entry(
    log: list,
    overhang_id: str,
    sub_domain_id: str,
    theta_deg: float,
    phi_deg: float,
    label: Optional[str],
) -> bool:
    """If the last log entry is an OverhangRotationLogEntry with a single
    matching (ovhg_id, sd_id) slot and timestamp within
    ``_SUBDOMAIN_COALESCE_WINDOW_S`` seconds of now, mutate its angles in
    place and return True. Otherwise return False.
    """
    if not log:
        return False
    last = log[-1]
    if last.feature_type != "overhang_rotation":
        return False
    if len(last.overhang_ids) != 1:
        return False
    if last.overhang_ids[0] != overhang_id:
        return False
    sd_ids = last.sub_domain_ids
    if len(sd_ids) != 1 or sd_ids[0] != sub_domain_id:
        return False

    import datetime as _dt

    ts = getattr(last, "timestamp", "") or ""
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        prev_ts = _dt.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if (now - prev_ts).total_seconds() > _SUBDOMAIN_COALESCE_WINDOW_S:
        return False

    # Update in place.
    last.sub_domain_thetas_deg[0] = float(theta_deg)
    last.sub_domain_phis_deg[0] = float(phi_deg)
    if label is not None:
        last.labels = [label]
    return True


@router.patch(
    "/design/overhang/{overhang_id}/sub-domains/{sub_domain_id}/rotation",
    status_code=200,
)
def patch_sub_domain_rotation(
    overhang_id: str,
    sub_domain_id: str,
    body: SubDomainRotationPatchBody,
) -> dict:
    """Set a sub-domain's parent-relative (theta_deg, phi_deg) angles.

    ``commit: false`` — live preview during gizmo drag. Mutates state
    silently with no feature_log entry.

    ``commit: true``  — final commit on pointerup. Appends an
    OverhangRotationLogEntry (or coalesces with the previous entry when
    the same sub-domain was just committed within 2 seconds).
    """
    import datetime as _dt
    from backend.core.models import OverhangRotationLogEntry
    from backend.core.validator import validate_design

    _validate_sd_angles(body.theta_deg, body.phi_deg)

    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    if not any(s.id == sub_domain_id for s in spec.sub_domains):
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    updated = _set_subdomain_angles(
        design,
        overhang_id,
        sub_domain_id,
        body.theta_deg,
        body.phi_deg,
    )

    if not body.commit:
        design_state.set_design_silent(updated)
        report = validate_design(updated)
        return _design_response_with_geometry(updated, report)

    # Commit path — try coalesce first, else append a new entry.
    log = list(updated.feature_log)
    if updated.feature_log_cursor == -2:
        log = []
    elif updated.feature_log_cursor >= 0:
        log = log[: updated.feature_log_cursor + 1]

    label = spec.label
    if not _try_coalesce_subdomain_rotation_entry(
        log,
        overhang_id,
        sub_domain_id,
        body.theta_deg,
        body.phi_deg,
        label,
    ):
        entry = OverhangRotationLogEntry(
            overhang_ids=[overhang_id],
            rotations=[list(_IDENTITY_QUAT_LIST)],
            labels=[label],
            sub_domain_ids=[sub_domain_id],
            sub_domain_thetas_deg=[float(body.theta_deg)],
            sub_domain_phis_deg=[float(body.phi_deg)],
        )
        # Attach a timestamp matching mutate_with_feature_log so the
        # coalesce window works.
        try:
            entry.__dict__["timestamp"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
        except Exception:
            pass
        log = log + [entry]

    updated = updated.copy_with(feature_log=log, feature_log_cursor=-1)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


class SubDomainRotationBatchOp(BaseModel):
    sub_domain_id: str
    theta_deg: float
    phi_deg: float


class SubDomainRotationBatchBody(BaseModel):
    ops: List[SubDomainRotationBatchOp]
    commit: bool = False


@router.patch(
    "/design/overhang/{overhang_id}/sub-domains/rotations-batch",
    status_code=200,
)
def patch_sub_domain_rotations_batch(
    overhang_id: str,
    body: SubDomainRotationBatchBody,
) -> dict:
    """Set multiple sub-domain rotations on one overhang atomically.

    422 on duplicate sub_domain_id; 422 on out-of-range angles. All-or-nothing
    validation: if any op fails, none are applied. Emits a single
    OverhangRotationLogEntry on commit.
    """
    import datetime as _dt
    from backend.core.models import OverhangRotationLogEntry
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    sd_by_id = {s.id: s for s in spec.sub_domains}

    if not body.ops:
        report = validate_design(design)
        return _design_response_with_geometry(design, report)

    seen: set[str] = set()
    for op in body.ops:
        if op.sub_domain_id in seen:
            raise HTTPException(
                422, detail=(f"Duplicate sub_domain_id in batch: {op.sub_domain_id!r}.")
            )
        seen.add(op.sub_domain_id)
        if op.sub_domain_id not in sd_by_id:
            raise HTTPException(
                404,
                detail=(
                    f"Sub-domain {op.sub_domain_id!r} not found on overhang "
                    f"{overhang_id!r}."
                ),
            )
        _validate_sd_angles(op.theta_deg, op.phi_deg)

    updated = design
    for op in body.ops:
        updated = _set_subdomain_angles(
            updated,
            overhang_id,
            op.sub_domain_id,
            op.theta_deg,
            op.phi_deg,
        )

    if not body.commit:
        design_state.set_design_silent(updated)
        report = validate_design(updated)
        return _design_response_with_geometry(updated, report)

    log = list(updated.feature_log)
    if updated.feature_log_cursor == -2:
        log = []
    elif updated.feature_log_cursor >= 0:
        log = log[: updated.feature_log_cursor + 1]

    n = len(body.ops)
    entry = OverhangRotationLogEntry(
        overhang_ids=[overhang_id] * n,
        rotations=[list(_IDENTITY_QUAT_LIST) for _ in range(n)],
        labels=[spec.label] * n,
        sub_domain_ids=[op.sub_domain_id for op in body.ops],
        sub_domain_thetas_deg=[float(op.theta_deg) for op in body.ops],
        sub_domain_phis_deg=[float(op.phi_deg) for op in body.ops],
    )
    try:
        entry.__dict__["timestamp"] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    except Exception:
        pass
    updated = updated.copy_with(
        feature_log=log + [entry],
        feature_log_cursor=-1,
    )
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


@router.get(
    "/design/overhang/{overhang_id}/sub-domains/{sub_domain_id}/frame",
    status_code=200,
)
def get_sub_domain_frame(overhang_id: str, sub_domain_id: str) -> dict:
    """Return the world-space rotation frame for a sub-domain.

    The frame is computed post-upstream-rotations, so a Phase 4 gizmo
    attaches at the right pivot even after several sub-domains have
    already been bent in the chain.

    Returns ``{pivot: [x,y,z], parent_axis: [x,y,z], phi_ref: [x,y,z]}``
    with both direction vectors unit-normalised.
    """
    import numpy as _np
    from backend.core.deformation import _default_phi_ref
    from backend.core.geometry import nucleotide_positions_arrays
    from backend.core.models import Direction as _Direction

    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    # Find the overhang's backing domain.
    strand = next((s for s in design.strands if s.id == spec.strand_id), None)
    if strand is None:
        raise HTTPException(
            409, detail=(f"Overhang {overhang_id!r} has no backing strand.")
        )
    dom_idx = next(
        (i for i, d in enumerate(strand.domains) if d.overhang_id == overhang_id),
        None,
    )
    if dom_idx is None:
        raise HTTPException(
            409, detail=(f"Overhang {overhang_id!r} backing domain missing.")
        )
    domain = strand.domains[dom_idx]
    is_first = dom_idx == 0
    sign = 1 if domain.direction == _Direction.FORWARD else -1

    junction_side_bp = domain.start_bp + sd.start_bp_offset * sign
    if is_first:
        junction_side_bp = (
            domain.start_bp + (sd.start_bp_offset + sd.length_bp - 1) * sign
        )

    helix = next((h for h in design.helices if h.id == spec.helix_id), None)
    if helix is None:
        raise HTTPException(
            409,
            detail=(f"Helix {spec.helix_id!r} not found for overhang {overhang_id!r}."),
        )

    arrs = nucleotide_positions_arrays(helix)
    # Apply existing deformations and rotations so the returned frame is
    # post-upstream.
    from backend.core.deformation import (
        apply_overhang_rotation_if_needed,
        _apply_cluster_transforms_domain_aware,
        _clusters_for_helix,
    )

    clusters = _clusters_for_helix(design, helix.id)
    if clusters:
        arrs = _apply_cluster_transforms_domain_aware(arrs, clusters, helix, design)
    arrs = apply_overhang_rotation_if_needed(arrs, helix, design)

    dir_int = 0 if domain.direction == _Direction.FORWARD else 1
    mask = (arrs["bp_indices"] == junction_side_bp) & (arrs["directions"] == dir_int)
    if not mask.any():
        raise HTTPException(
            409,
            detail=(
                f"Could not locate pivot bp {junction_side_bp} on helix "
                f"{spec.helix_id!r}; design may need geometry rebuild."
            ),
        )

    pivot = arrs["positions"][mask][0].astype(float)
    pa = arrs["axis_tangents"][mask][0].astype(float)
    pa_norm = float(_np.linalg.norm(pa))
    if pa_norm < 1e-9:
        pa = _np.array([0.0, 0.0, 1.0])
    else:
        pa = pa / pa_norm
    pr = _default_phi_ref(pa)

    return {
        "pivot": [float(pivot[0]), float(pivot[1]), float(pivot[2])],
        "parent_axis": [float(pa[0]), float(pa[1]), float(pa[2])],
        "phi_ref": [float(pr[0]), float(pr[1]), float(pr[2])],
    }


_IDENTITY_QUAT_LIST = [0.0, 0.0, 0.0, 1.0]


class StrandPatchRequest(BaseModel):
    notes: str | None = None
    color: str | None = None  # "#RRGGBB" hex string, or None to reset to palette
    # A full 5'→3' ATGCN sequence to SET by hand, or null to CLEAR back to the
    # unsequenced state. A set must match the strand's nucleotide count exactly.
    sequence: str | None = None


@router.patch("/design/strand/{strand_id}", status_code=200)
def patch_strand(strand_id: str, body: StrandPatchRequest) -> dict:
    """Update editable metadata on a strand (notes, color, and/or sequence).

    ``sequence`` accepts either:

    * **a string** — set the strand's sequence by hand, 5'→3' over the WHOLE
      strand.  Whitespace is stripped and the input uppercased; only A/T/G/C/N
      are allowed (422 otherwise) and the length must equal the strand's
      nucleotide count (422 otherwise).  Bases that fall inside an overhang
      domain are written back onto that ``OverhangSpec`` so the two stores stay
      in sync — skipped for an overhang whose sub-domains carry
      ``sequence_override``s (those bases are owned per sub-domain; edit them in
      the Domain Designer).  Recorded as a ``strand-sequence`` feature-log step,
      because a sequence is a build-fingerprint field: a feature-log seek must be
      able to reproduce it or an oxDNA job's out-of-date ⚠ can never clear.
    * **null** — clear the assembled sequence back to the unsequenced state
      (displayed as N×length in the spreadsheet), also clearing the sequence on
      any overhang the strand carries.

    A hand-set sequence is deliberately NOT protected from the explicit bulk
    commands: "Assign staple sequences" and "Full autostaple" re-derive it, and
    both push an undo snapshot so the manual value can be brought back.  The
    *implicit* auto-assign hooks (overhang patch / connection create / version
    apply) are targeted and leave unrelated strands alone — see
    ``sequences.reassign_strands``.

    Pushes an undo snapshot before modifying so the change can be reverted.
    """
    from backend.core.sequences import (
        normalize_sequence_input,
        strand_sequence_length,
        strand_sequence_segments,
    )

    design = design_state.get_or_404()
    strand = design.find_strand(strand_id)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")

    setting_sequence = "sequence" in body.model_fields_set and body.sequence is not None
    clearing_sequence = "sequence" in body.model_fields_set and body.sequence is None

    patch: dict = {}
    if body.notes is not None or "notes" in body.model_fields_set:
        patch["notes"] = body.notes
    if body.color is not None or "color" in body.model_fields_set:
        patch["color"] = body.color

    new_seq: str | None = None
    if setting_sequence:
        try:
            new_seq = normalize_sequence_input(body.sequence or "")
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc))
        expected = strand_sequence_length(design, strand)
        if len(new_seq) != expected:
            raise HTTPException(
                422,
                detail=(
                    f"Sequence length {len(new_seq)} does not match strand "
                    f"{strand_id!r}, which has {expected} nucleotides."
                ),
            )
        patch["sequence"] = new_seq
    elif clearing_sequence:
        patch["sequence"] = None

    new_strands = [
        s.model_copy(update=patch) if s.id == strand_id else s for s in design.strands
    ]

    new_overhangs = design.overhangs
    if clearing_sequence:
        strand_overhang_ids = {
            d.overhang_id for d in strand.domains if d.overhang_id is not None
        }
        if strand_overhang_ids:
            new_overhangs = [
                o.model_copy(update={"sequence": None})
                if o.id in strand_overhang_ids
                else o
                for o in design.overhangs
            ]
    elif setting_sequence:
        # Write each overhang span back onto its OverhangSpec. Set the field
        # DIRECTLY rather than via _build_overhang_patch — that helper resizes the
        # overhang domain to len(sequence), and here the slice is the domain's
        # existing length by construction, so no resize must happen.
        oh_slices = {
            seg["overhang_id"]: new_seq[seg["start"] : seg["start"] + seg["length"]]
            for seg in strand_sequence_segments(design, strand)
            if seg["kind"] == "overhang" and seg["editable"] and seg["overhang_id"]
        }
        if oh_slices:
            new_overhangs = [
                o.model_copy(update={"sequence": oh_slices[o.id]})
                if o.id in oh_slices
                else o
                for o in design.overhangs
            ]

    updated = design.model_copy(
        update={"strands": new_strands, "overhangs": new_overhangs}
    )

    bits = []
    if "color" in patch:
        bits.append(f"color={patch['color']}")
    if "notes" in patch:
        bits.append("notes")
    if clearing_sequence:
        bits.append("seq cleared")

    if setting_sequence:
        # Feature-log step (not a minor log): a sequence is a build-fingerprint field.
        preview = new_seq if len(new_seq) <= 24 else f"{new_seq[:21]}…"
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind="strand-sequence",
            label=f"Strand sequence: {preview} ({len(new_seq)} nt)",
            params={"strand_id": strand_id, "sequence": new_seq},
            fn=lambda _d: updated,
        )
        return _design_response(updated, report)

    label = f"Patch strand {strand_id}" + (f" · {', '.join(bits)}" if bits else "")
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strand-patch",
        label=label,
        params={
            "strand_id": strand_id,
            **body.model_dump(mode="json", exclude_unset=True),
        },
        fn=lambda _d: updated,
    )
    return _design_response(updated, report)


class BulkColorRequest(BaseModel):
    strand_ids: list[str]
    color: str | None = None  # "#RRGGBB" hex string, or None to reset to palette


@router.patch("/design/strands/colors", status_code=200)
def patch_strands_color(body: BulkColorRequest) -> dict:
    """Apply the same color to multiple strands atomically in one undo step."""
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
    n = len(id_set)
    label = (
        f"Color {n} strand{'s' if n != 1 else ''} · {body.color or '(palette reset)'}"
    )
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strands-color-bulk",
        label=label,
        params=body.model_dump(mode="json"),
        fn=lambda _d: updated,
    )
    return _design_response(updated, report)


class BulkReferenceRequest(BaseModel):
    strand_ids: list[str]
    is_reference: bool


@router.patch("/design/strands/reference", status_code=200)
def patch_strands_reference(body: BulkReferenceRequest) -> dict:
    """Mark/clear strands as inactive reference geometry, atomically in one undo step.

    Reference strands are ignored by all generative features (bend/twist, sequence
    assignment, scaffold routing, autostaple/break/merge, auto-crossover) and excluded
    from exports/validation, while staying visible (rendered translucent) and manually
    editable.  Returns geometry because toggling reference changes the bend/twist freeze,
    so nucleotide positions move.
    """
    design = design_state.get_or_404()
    id_set = set(body.strand_ids)
    missing = id_set - {s.id for s in design.strands}
    if missing:
        raise HTTPException(404, detail=f"Strand(s) not found: {sorted(missing)}")
    new_strands = [
        s.model_copy(update={"is_reference": body.is_reference})
        if s.id in id_set
        else s
        for s in design.strands
    ]
    updated = design.model_copy(update={"strands": new_strands})

    # Reference geometry is excluded from clusters: prune reference-only helices
    # and reference strands' domain refs from every cluster so it's a fixed backdrop
    # (immune to cluster joints/drags and not counted in cluster calculations).
    ref_strand_ids = {s.id for s in new_strands if s.is_reference}
    ref_helix_ids = updated.reference_helix_ids()
    if ref_helix_ids or ref_strand_ids:
        pruned = []
        for c in updated.cluster_transforms:
            new_hids = [h for h in c.helix_ids if h not in ref_helix_ids]
            new_drs = [dr for dr in c.domain_ids if dr.strand_id not in ref_strand_ids]
            if len(new_hids) != len(c.helix_ids) or len(new_drs) != len(c.domain_ids):
                pruned.append(
                    c.model_copy(update={"helix_ids": new_hids, "domain_ids": new_drs})
                )
            else:
                pruned.append(c)
        updated = updated.model_copy(update={"cluster_transforms": pruned})

    n = len(id_set)
    verb = "Mark" if body.is_reference else "Clear"
    label = f"{verb} reference · {n} strand{'s' if n != 1 else ''}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype="strands-reference",
        label=label,
        params=body.model_dump(mode="json"),
        fn=lambda _d: updated,
    )
    return _design_response_with_geometry(updated, report)


# ── Autostaple: autobreak + auto-merge ────────────────────────────────────────


@router.post("/design/auto-break", status_code=200)
def auto_break(payload: dict | None = Body(None)) -> dict:
    """Nick all non-scaffold strands at every major tick mark (multiples of 7 bp HC /
    8 bp SQ), then merge fragments to be as long as possible without exceeding 56 nt.
    Apply after auto-crossover.

    Emits a ``snapshot`` feature-log entry so the operation can be reverted
    even after a browser refresh (POST ``/design/features/{index}/revert``).
    """
    from backend.core.lattice import make_autobreak

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="auto-break",
        label="Autobreak",
        params={},
        fn=lambda d: make_autobreak(d),
    )
    return _design_response(updated, report)


@router.post("/design/auto-merge", status_code=200)
def auto_merge() -> dict:
    """Merge adjacent short staple strands when their combined length ≤ 56 nt
    and the result is sandwich-free.

    Stage 3 of the autostaple pipeline; apply after auto-break.
    Repeats until no further merges are possible.

    Emits a ``snapshot`` feature-log entry so the operation can be reverted
    even after a browser refresh.
    """
    from backend.core.lattice import make_merge_short_staples

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="auto-merge",
        label="Auto-merge staples",
        params={},
        fn=lambda d: make_merge_short_staples(d),
    )
    return _design_response(updated, report)


# ── Overhang random-sequence generation ───────────────────────────────────────


def _resplice_overhang_in_strand(design, overhang_id: str, strand_id: str):
    """Re-derive and update the sequence for only the strand that owns the overhang.

    If the strand already has an assembled sequence (from assign_staple_sequences)
    this re-derives it using the updated overhang spec so the new random sequence
    appears in the correct position while the rest of the strand is preserved.
    Silently no-ops when the strand has no sequence or there is no scaffold sequence.
    """
    from backend.core.sequences import reassign_strands

    strand = design.find_strand(strand_id)
    if strand is None or strand.sequence is None:
        return design
    return reassign_strands(design, {strand_id})


@router.delete("/design/overhangs", status_code=200)
def clear_all_overhangs() -> dict:
    """Remove all OverhangSpec objects and clear overhang_id on all domains.

    Emits a ``snapshot`` feature-log entry so the bulk delete can be reverted
    even after a browser refresh.
    """

    def _build(d: Design) -> Design:
        new_strands = [
            s.model_copy(
                update={
                    "domains": [
                        dm.model_copy(update={"overhang_id": None}) for dm in s.domains
                    ]
                }
            )
            for s in d.strands
        ]
        return d.model_copy(update={"strands": new_strands, "overhangs": []})

    overhang_count = len(design_state.get_or_404().overhangs)
    design, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label="Clear all overhangs",
        params={"overhang_count_before": overhang_count, "action": "clear-all"},
        fn=_build,
    )
    return _design_response(design, report)


@router.post("/design/overhangs/batch-delete", status_code=200)
def delete_overhangs_batch(body: OverhangBatchDeleteRequest) -> dict:
    """Remove selected OverhangSpec records and clear matching domain links.

    Any child overhangs in a chain are deleted with their selected ancestor, and
    linker/binding records that reference removed overhangs are removed too.
    The operation is snapshot-backed so undo and feature-log seek can restore
    the previous state.
    """
    from backend.core.lattice import _overhang_chain_descendants

    design = design_state.get_or_404()
    requested_ids = {oid for oid in body.overhang_ids if oid}
    existing_ids = {o.id for o in design.overhangs}
    target_ids = requested_ids & existing_ids
    if not target_ids:
        raise HTTPException(404, detail="No selected overhangs were found.")

    expanded_ids = set(target_ids)
    for oid in list(target_ids):
        expanded_ids.update(_overhang_chain_descendants(design, oid))

    labels = [(o.label or o.id) for o in design.overhangs if o.id in expanded_ids]

    def _build(d: Design) -> Design:
        conn_ids = {
            c.id
            for c in d.overhang_connections
            if c.overhang_a_id in expanded_ids or c.overhang_b_id in expanded_ids
        }
        out = _delete_linker_connections_from_design(d, conn_ids)
        remove_binding_ids = {
            b.id
            for b in out.overhang_bindings
            if b.overhang_a_id in expanded_ids or b.overhang_b_id in expanded_ids
        }
        bindings = list(out.overhang_bindings)
        affected_joint_ids = {
            b.target_joint_id
            for b in bindings
            if b.id in remove_binding_ids and b.target_joint_id is not None
        }
        fallback_windows: dict[str, tuple[float, float]] = {}
        for jid in affected_joint_ids:
            removed = [
                b
                for b in bindings
                if b.id in remove_binding_ids and b.target_joint_id == jid
            ]
            removed.sort(key=lambda b: (b.created_at, b.id))
            snapshot_src = next(
                (
                    b
                    for b in removed
                    if b.prior_min_angle_deg is not None
                    and b.prior_max_angle_deg is not None
                ),
                None,
            )
            if snapshot_src is None:
                continue
            fallback_windows[jid] = (
                snapshot_src.prior_min_angle_deg,
                snapshot_src.prior_max_angle_deg,
            )
            heirs = [
                b
                for b in bindings
                if b.id not in remove_binding_ids and b.target_joint_id == jid
            ]
            heirs.sort(key=lambda b: (b.created_at, b.id))
            if heirs:
                heir = heirs[0]
                if (
                    heir.prior_min_angle_deg is None
                    and heir.prior_max_angle_deg is None
                ):
                    new_heir = heir.model_copy(
                        update={
                            "prior_min_angle_deg": snapshot_src.prior_min_angle_deg,
                            "prior_max_angle_deg": snapshot_src.prior_max_angle_deg,
                        }
                    )
                    bindings = [new_heir if b.id == heir.id else b for b in bindings]

        def _domain_len(dm: Domain) -> int:
            return abs(int(dm.end_bp) - int(dm.start_bp)) + 1

        new_strands = []
        for strand in out.strands:
            new_domains = []
            seq_parts: list[str] = []
            seq_offset = 0
            has_exact_sequence = strand.sequence is not None and len(
                strand.sequence
            ) == sum(_domain_len(dm) for dm in strand.domains)
            for dm in strand.domains:
                n = _domain_len(dm)
                if dm.overhang_id in expanded_ids:
                    seq_offset += n
                    continue
                new_domains.append(dm)
                if has_exact_sequence:
                    seq_parts.append(strand.sequence[seq_offset : seq_offset + n])
                seq_offset += n
            if not new_domains:
                continue
            updates: dict = {"domains": new_domains}
            if has_exact_sequence:
                updates["sequence"] = "".join(seq_parts)
            new_strands.append(strand.model_copy(update=updates))

        covered_helix_ids = {
            dm.helix_id for strand in new_strands for dm in strand.domains
        }
        new_helices = [h for h in out.helices if h.id in covered_helix_ids]

        slot_cov: dict[str, list[tuple[int, int]]] = {}
        for strand in new_strands:
            for dm in strand.domains:
                key = f"{dm.helix_id}_{dm.direction}"
                lo = min(dm.start_bp, dm.end_bp)
                hi = max(dm.start_bp, dm.end_bp)
                slot_cov.setdefault(key, []).append((lo, hi))

        def _covered(helix_id: str, bp: int, direction: str) -> bool:
            return any(
                lo <= bp <= hi for lo, hi in slot_cov.get(f"{helix_id}_{direction}", [])
            )

        new_crossovers = [
            xo
            for xo in out.crossovers
            if _covered(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
            and _covered(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
        ]

        new_bindings = [b for b in bindings if b.id not in remove_binding_ids]
        new_overhangs = [o for o in out.overhangs if o.id not in expanded_ids]
        out = out.model_copy(
            update={
                "strands": new_strands,
                "helices": new_helices,
                "crossovers": new_crossovers,
                "overhangs": new_overhangs,
                "overhang_bindings": new_bindings,
            }
        )
        for jid in affected_joint_ids:
            out = _apply_driver_to_joint(out, jid)
            if (
                _select_driver_for_joint(out, jid) is None
                and _first_claimant_for_joint(out, jid) is None
            ):
                fallback = fallback_windows.get(jid)
                if fallback is not None:
                    min_angle, max_angle = fallback
                    out = out.model_copy(
                        update={
                            "cluster_joints": [
                                j.model_copy(
                                    update={
                                        "min_angle_deg": min_angle,
                                        "max_angle_deg": max_angle,
                                    }
                                )
                                if j.id == jid
                                else j
                                for j in out.cluster_joints
                            ],
                        }
                    )
        return out

    n = len(expanded_ids)
    label = f"Delete {n} overhang{'s' if n != 1 else ''}"
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=label,
        params={
            "action": "delete-selected",
            "overhang_ids": sorted(expanded_ids),
            "labels": labels,
        },
        fn=_build,
    )
    return _design_response_with_geometry(updated, report)


class RandomSequenceRequest(BaseModel):
    length: int


@router.post("/design/random-sequence", status_code=200)
def random_sequence(body: RandomSequenceRequest) -> dict:
    """Produce a single Johnson-algorithm random sequence of a given length.

    Used by the Connection Types tab's bridge-sequence "Gen" button to
    populate the box BEFORE the linker exists. Scored against the current
    scaffold + staple corpus so the chosen bridge inherits the same rarity /
    GC / hairpin filters as the spreadsheet Gen button. Read-only — does
    not mutate the design.
    """
    from backend.core.overhang_generator import generate_overhang_sequences

    if body.length <= 0:
        raise HTTPException(400, detail="length must be a positive integer.")
    design = design_state.get_or_404()
    scaffold = design.scaffold()
    scaffold_seq = scaffold.sequence if scaffold and scaffold.sequence else ""
    staple_seqs = [
        s.sequence
        for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]
    seq = generate_overhang_sequences(
        scaffold_seq,
        staple_seqs,
        length=body.length,
        count=1,
    )[0]
    return {"sequence": seq}


@router.post("/design/overhang/{overhang_id}/generate-random", status_code=200)
def generate_overhang_random_sequence(
    overhang_id: str, defer_reassign: bool = False
) -> dict:
    """Generate a rare, structure-safe sequence for a single undefined overhang.

    The generated sequence has the same length as the current overhang domain.
    Uses the 5-mer scoring algorithm to find a sequence that is rare in the
    scaffold + staple corpus, has acceptable GC content, and avoids hairpins
    / self-dimers.  If the parent strand already has an assembled sequence,
    only the overhang portion is updated — the rest of the strand's sequence
    is preserved.

    Returns 404 if the overhang does not exist and 422 if it already has a
    sequence (clear it first via PATCH /design/overhang/{id}).
    """
    from backend.core.overhang_generator import (
        generate_overhang_sequences,
        generate_overhang_sequence_with_overrides,
    )

    design = design_state.get_or_404()
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    lengths = _ovhg_domain_lengths(design)
    domain_len = lengths.get(overhang_id)
    if domain_len is None:
        raise HTTPException(
            404, detail=f"No domain references overhang {overhang_id!r}."
        )

    scaffold = design.scaffold()
    scaffold_seq = scaffold.sequence if scaffold and scaffold.sequence else ""
    staple_seqs = [
        s.sequence
        for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]
    # Honour locked sub-domain overrides: only re-roll the unlocked slices.
    sub_doms = list(spec.sub_domains or [])
    if sub_doms and any(sd.sequence_override for sd in sub_doms):
        seq = generate_overhang_sequence_with_overrides(
            scaffold_seq, staple_seqs, sub_doms
        )
    else:
        seq = generate_overhang_sequences(
            scaffold_seq, staple_seqs, length=domain_len, count=1
        )[0]
    new_overhangs = [
        spec.model_copy(update={"sequence": seq}) if o.id == overhang_id else o
        for o in design.overhangs
    ]
    updated = design.model_copy(update={"overhangs": new_overhangs})

    # Splice new overhang sequence into the strand's assembled sequence (if present),
    # leaving all non-overhang bases unchanged.
    updated = _resplice_overhang_in_strand(updated, overhang_id, spec.strand_id)

    # Propagate the reverse complement to any OH-binder / linker complement
    # strands bound to this overhang (no-op for strands without a sequence).
    for s in list(updated.strands):
        if s.id != spec.strand_id and any(
            d.binds_overhang_id == overhang_id for d in s.domains
        ):
            updated = _resplice_overhang_in_strand(updated, overhang_id, s.id)

    # Phase 3: rescan boundaries for hairpins spanning adjacent sub-domains
    # (the generator already filters per-sub-domain hairpins, but a junction
    # window can still form one).
    updated = _apply_boundary_hairpin_warnings(updated, overhang_id)

    # Record a feature-log snapshot (not a silent set_design) so the assigned
    # sequence is a real timeline step — seeking back to it reproduces the
    # sequence and keeps oxDNA job staleness in sync (see patch_overhang).
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-sequence",
        label=f"Generate overhang sequence: {seq}",
        params={"overhang_id": overhang_id, "action": "generate-random"},
        fn=lambda _d: updated,
    )
    return _design_response(updated, report)


@router.post("/design/generate-overhang-sequences", status_code=200)
def generate_all_overhang_sequences() -> dict:
    """Generate rare, structure-safe sequences for all overhangs.

    Uses the 5-mer scoring algorithm for each overhang in turn, growing the
    corpus with each newly generated sequence so that all overhangs are mutually
    diverse.  Existing sequences are overwritten — this is intentional so that
    sequences imported from caDNAno/scadnano files can be regenerated with
    NADOC's algorithm.
    If the design has an assembled scaffold sequence, affected strand sequences
    are updated in-place (overhang positions only; other bases are preserved).
    Returns 422 if the design has no overhangs at all.
    """
    from backend.core.overhang_generator import (
        generate_overhang_sequences,
        generate_overhang_sequence_with_overrides,
        reverse_complement,
    )
    from backend.core.sequences import assign_staple_sequences

    design = design_state.get_or_404()
    to_generate = list(design.overhangs)
    if not to_generate:
        raise HTTPException(422, detail="No overhangs found.")

    lengths = _ovhg_domain_lengths(design)

    scaffold = design.scaffold()
    scaffold_seq = scaffold.sequence if scaffold and scaffold.sequence else ""
    staple_seqs = [
        s.sequence
        for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]

    # Generate one overhang at a time so each new sequence is added to the
    # corpus before the next is generated (enforces mutual diversity). When an
    # overhang has locked sub-domain overrides, only the unlocked sub-domain
    # slices are re-rolled — the overrides are preserved verbatim.
    extra_seqs: list[str] = []
    generated: dict[str, str] = {}
    for spec in to_generate:
        domain_len = lengths.get(spec.id)
        if domain_len is None:
            continue
        sub_doms = list(spec.sub_domains or [])
        if sub_doms and any(sd.sequence_override for sd in sub_doms):
            seq = generate_overhang_sequence_with_overrides(
                scaffold_seq,
                staple_seqs + extra_seqs,
                sub_doms,
            )
        else:
            seq = generate_overhang_sequences(
                scaffold_seq,
                staple_seqs + extra_seqs,
                length=domain_len,
                count=1,
            )[0]
        generated[spec.id] = seq
        extra_seqs.append(seq * 10)
        extra_seqs.append(reverse_complement(seq) * 10)

    new_overhangs = []
    count = 0
    affected_strand_ids: set[str] = set()
    for spec in design.overhangs:
        if spec.id in generated:
            new_overhangs.append(
                spec.model_copy(update={"sequence": generated[spec.id]})
            )
            affected_strand_ids.add(spec.strand_id)
            count += 1
        else:
            new_overhangs.append(spec)

    # OH-binder / linker complement strands that pair with a regenerated
    # overhang must re-derive their reverse-complement sequence too.
    for s in design.strands:
        if any(
            d.binds_overhang_id in generated for d in s.domains if d.binds_overhang_id
        ):
            affected_strand_ids.add(s.id)

    updated = design.model_copy(update={"overhangs": new_overhangs})

    # Re-derive assembled sequences for affected strands (only if scaffold is sequenced).
    # Skipped when the caller defers (the connection-creation flow re-derives once at apply).
    scaffold = updated.scaffold()
    if scaffold is not None and scaffold.sequence is not None and not defer_reassign:
        strands_with_seq = {s.id for s in design.strands if s.sequence is not None}
        to_update = affected_strand_ids & strands_with_seq
        if to_update:
            try:
                re_derived = assign_staple_sequences(updated)
                re_seq_map = {
                    s.id: s.sequence for s in re_derived.strands if s.id in to_update
                }
                new_strands = [
                    s.model_copy(update={"sequence": re_seq_map[s.id]})
                    if s.id in re_seq_map
                    else s
                    for s in updated.strands
                ]
                updated = updated.model_copy(update={"strands": new_strands})
            except Exception:
                pass

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label="Generate overhang sequences",
        params={"generated_count": count, "action": "generate-sequences"},
        fn=lambda _d: updated,
    )
    result = _design_response(updated, report)
    result["generated_count"] = count
    return result


# ── Sub-domains (Phase 1, overhang revamp) ────────────────────────────────────
#
# Sub-domains are a topological-layer concept: pure metadata stored on
# OverhangSpec.sub_domains. They tile the overhang gap-lessly 5'→3' and can
# carry their own sequence_override + cached annotations. Endpoint contract:
#
#   GET    /design/overhang/{id}/sub-domains
#   POST   /design/overhang/{id}/sub-domains/split
#   POST   /design/overhang/{id}/sub-domains/merge
#   PATCH  /design/overhang/{id}/sub-domains/{sub_id}
#   POST   /design/overhang/{id}/sub-domains/{sub_id}/recompute-annotations
#   PATCH  /design/tm-settings
#
# The OverhangSpec model_validator backfills a single whole-overhang sub-domain
# on load so legacy `.nadoc` files keep working unchanged.


import re as _re_subdomain  # noqa: E402  (section-scoped helper)

_HEX_RE = _re_subdomain.compile(r"^#[0-9A-Fa-f]{6}$")
_DNA_BASES = set("ACGTN")


def _validate_sub_domain_tiling(design: Design, overhang_id: str) -> None:
    """Thin api shim — delegate tiling validation to ``backend.core.overhang_ops``
    and translate its ``SubDomainTilingError`` into ``HTTPException`` (L15).

    The invariants enforced live in ``overhang_ops.validate_sub_domain_tiling``
    (Σ length_bp == backing length, gap-less contiguous offsets, length_bp ≥ 1,
    ACGTN sequence_override). This shim keeps the HTTP translation in the api
    layer so the rule itself stays pure + directly testable.
    """
    try:
        validate_sub_domain_tiling(design, overhang_id)
    except SubDomainTilingError as exc:
        raise HTTPException(exc.status, detail=exc.detail)


def _backfill_sub_domains_if_empty(design: Design) -> Design:
    """Safety-net helper called from load/import paths.

    Two responsibilities:
      1. Insert a whole-overhang sub-domain on any overhang where the
         ``sub_domains`` list is empty (defensive — the model validator
         normally handles this).
      2. Correct stale length on a SINGLE auto-backfilled whole-overhang
         sub-domain whose length doesn't match the backing domain. The
         model validator fires before the OverhangSpec sees its backing
         domain (it lives in the strand list), so on file load it picks
         ``length_bp = 1`` when there is no parent sequence. This helper
         repairs that mismatch.

    It is idempotent for healthy designs: when every overhang's sub-domain
    tiling already sums to the backing length, the design is returned
    unchanged.
    """
    if not design.overhangs:
        return design
    from backend.core.models import SubDomain as _SD, NADOC_SUBDOMAIN_NS as _NS

    needs_update = False
    new_overhangs = []
    for ovhg in design.overhangs:
        backing = _ovhg_backing_length(design, ovhg.id)
        if backing is None:
            backing = len(ovhg.sequence) if ovhg.sequence else 1
        if ovhg.sub_domains:
            total = sum(sd.length_bp for sd in ovhg.sub_domains)
            # Healthy: tiling already covers the backing domain.
            if total == backing:
                new_overhangs.append(ovhg)
                continue
            # Single auto-backfilled sub-domain with wrong length → repair it
            # in place (deterministic id, same name as the auto-backfill).
            if len(ovhg.sub_domains) == 1:
                solo = ovhg.sub_domains[0]
                expected_id = str(_uuid.uuid5(_NS, f"{ovhg.id}:whole"))
                # Repair if the id matches the deterministic UUID5 OR if no
                # override is set (we only auto-fix the safe whole-overhang case).
                if solo.id == expected_id and solo.sequence_override is None:
                    needs_update = True
                    new_solo = solo.model_copy(update={"length_bp": max(backing, 1)})
                    new_overhangs.append(
                        ovhg.model_copy(update={"sub_domains": [new_solo]})
                    )
                    continue
            # Multi-sub-domain mismatch — preserve verbatim; the endpoint-
            # level validator will reject any subsequent mutation. The
            # frontend can surface a repair UI in Phase 3+.
            new_overhangs.append(ovhg)
            continue
        # Truly empty (out-of-band construction skipped the validator).
        needs_update = True
        whole = _SD(
            id=str(_uuid.uuid5(_NS, f"{ovhg.id}:whole")),
            name="a",
            start_bp_offset=0,
            length_bp=max(backing, 1),
        )
        new_overhangs.append(ovhg.model_copy(update={"sub_domains": [whole]}))
    if not needs_update:
        return design
    return design.model_copy(update={"overhangs": new_overhangs})


def _derive_duplexes_if_empty(design: Design) -> Design:
    """Bridge helper (Proposal-B Phase 3) called from load/import paths.

    Populate ``design.duplexes`` from legacy ``OverhangBinding`` records so an
    existing design shows the register-bearing pairing graph (multivalency,
    toeholds, mismatch colours) in the UI. Read-only + one-time: fires only when
    ``duplexes`` is empty AND bindings exist. The bindings are left intact (they
    still drive geometry/relax until Phase 4; retired in Phase 6). Idempotent —
    a design that already carries duplexes is returned unchanged. See
    ``memory/project_overhang_duplex_foundation.md``.
    """
    if design.duplexes or not design.overhang_bindings:
        return design
    from backend.core.duplex import synthesize_duplexes_from_bindings

    dux = synthesize_duplexes_from_bindings(design)
    if not dux:
        return design
    return design.model_copy(update={"duplexes": dux})


def _materialize_duplex_clusters_on_load(design: Design) -> Design:
    """Migrate legacy per-overhang duplex POSES (``OverhangSpec.rotation``/``translation`` on
    a bound direct binding/duplex's driver) onto first-class child DUPLEX clusters, so an
    existing .nadoc shows the duplex as a sidebar-listed, gizmo-movable, drift-free cluster.
    Geometry+axis neutral (proven on 2x2_OH_test). Idempotent: skips a driver that already
    has a duplex cluster. [[overhang-duplex-cluster]] P1b."""
    from backend.core.duplex_cluster import (
        duplex_cluster_for,
        materialize_duplex_cluster,
    )

    drivers: list[str] = [
        b.driver_oh_id for b in design.overhang_bindings if b.bound and b.driver_oh_id
    ]
    drivers += [
        (dx.left.overhang_id if dx.driver == "left" else dx.right.overhang_id)
        for dx in design.duplexes
        if dx.bound
    ]
    seen: set = set()
    for drv in drivers:
        if drv in seen or duplex_cluster_for(design, drv) is not None:
            continue
        seen.add(drv)
        if not any(o.id == drv for o in design.overhangs):
            continue
        design, _cid = materialize_duplex_cluster(design, drv)
    return design


def _recompute_flexible_connections(design: Design) -> Design:
    """Safety-net helper called from load/import paths.

    ``flexible_connections`` is DERIVED from ``flexible_segment_marks`` and is
    only a persisted cache. Recompute it on load so existing .nadoc files
    self-correct — in particular files saved before the cluster-ownership
    tie-break fix, whose marks resolved to zero connections (the marked beads
    were then excluded from rigid rendering with no arc drawn → "disappeared").
    Idempotent: a healthy design re-derives the same connection list.
    """
    if not design.flexible_segment_marks:
        return design
    from backend.core.flexible_segments import apply_marks

    return apply_marks(design)


def _find_ovhg_or_404(design: Design, overhang_id: str):
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    return spec


# ── Overhang free-end resize ──────────────────────────────────────────────────
#
# Wraps the existing strand-end-resize machinery and additionally re-tiles the
# affected overhang's sub-domains: per the locked Phase 1 policy, the LAST
# sub-domain absorbs the Δ length. Rejects shrink that would push the last
# sub-domain below 1 bp (or below its sequence_override length when one is set).


class OverhangResizeFreeEndRequest(BaseModel):
    end: Literal["5p", "3p"]
    delta_bp: int


@router.post("/design/overhang/{overhang_id}/resize-free-end", status_code=200)
def resize_overhang_free_end(
    overhang_id: str, body: OverhangResizeFreeEndRequest
) -> dict:
    """Resize an overhang by dragging its FREE end cap in the Domain Designer.

    Steps (atomic from the user's perspective — single feature-log entry):
      1. Resolve the overhang and its backing strand domain.
      2. Reject if the requested end is the ROOT end (must be the free tip).
      3. Run resize_strand_ends on the strand-domain endpoint.
      4. Adjust sub-domain tiling: last sub-domain absorbs Δ length_bp.
         422 if shrink pushes the last sub-domain below 1 bp or below its
         sequence_override length.
      5. Validate tiling.
    """
    from backend.core.lattice import resize_strand_ends as _resize_strand_ends

    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)

    # Locate the backing domain on the strand to determine which strand-end
    # is the FREE end. Designs in the wild can have an "orphan" overhang
    # (id not on any strand domain) when an inline-style overhang and an
    # extrude-style overhang both reference the same helix; in that case fall
    # back to the strand's terminal domain on the overhang's helix so the
    # resize still lands on the physically-correct end.
    strand = next((s for s in design.strands if s.id == spec.strand_id), None)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {spec.strand_id!r} not found.")
    domains = list(strand.domains or [])
    # Strict match: domain whose overhang_id == this overhang's id.
    dom_idx = next(
        (i for i, d in enumerate(domains) if d.overhang_id == overhang_id),
        -1,
    )
    if dom_idx < 0:
        # Fallback 1: any domain on the overhang's helix that already carries
        # SOME overhang_id tag (typically an inline-overhang sibling).
        dom_idx = next(
            (
                i
                for i, d in enumerate(domains)
                if d.helix_id == spec.helix_id and d.overhang_id is not None
            ),
            -1,
        )
    if dom_idx < 0:
        # Fallback 2: the strand's first domain that touches this helix.
        dom_idx = next(
            (i for i, d in enumerate(domains) if d.helix_id == spec.helix_id),
            -1,
        )
    if dom_idx < 0:
        raise HTTPException(
            404,
            detail=f"Backing domain for {overhang_id!r} not found on strand "
            f"(also tried fallback to helix {spec.helix_id!r}).",
        )
    is_first = dom_idx == 0
    is_last = dom_idx == len(domains) - 1
    free_end: str
    if is_first and not is_last:
        free_end = "5p"
    elif is_last and not is_first:
        free_end = "3p"
    elif is_first and is_last:
        free_end = "5p"  # whole-strand: arbitrary
    else:
        raise HTTPException(
            409, detail="Overhang is sandwiched between domains; resize unsupported."
        )

    if body.end != free_end:
        raise HTTPException(
            422,
            detail=f"Requested end {body.end!r} is the root, not the free end ({free_end!r}).",
        )

    # Sub-domain length change matches |Δ length of overhang|. We resolve the
    # signed Δ from the backing domain length change, NOT from delta_bp (which
    # is signed in global-bp space; for REVERSE strands the polarity flips).
    backing = domains[dom_idx]
    old_len = abs(backing.end_bp - backing.start_bp) + 1

    if not spec.sub_domains:
        raise HTTPException(
            409,
            detail="Overhang has no sub-domains; legacy state — open it once to migrate.",
        )
    last_sd = spec.sub_domains[-1]
    # Predict the new sub-domain length so we can fail BEFORE mutating state.
    # The resize moves the free end by `delta_bp` in global bp. For the FREE
    # end, the strand-domain length change equals (delta_bp * sign) where sign
    # depends on whether free is 5' (which contracts when delta_bp > 0 on a
    # FORWARD strand) or 3'. We compute the predicted new length empirically:
    #   new_start = start_bp + delta_bp if end == '5p' else start_bp
    #   new_end   = end_bp   + delta_bp if end == '3p' else end_bp
    new_start = backing.start_bp + (body.delta_bp if free_end == "5p" else 0)
    new_end = backing.end_bp + (body.delta_bp if free_end == "3p" else 0)
    new_len = abs(new_end - new_start) + 1
    delta_len = new_len - old_len  # positive = grow, negative = shrink

    new_last_len = (last_sd.length_bp or 0) + delta_len
    # Last sub-domain must remain ≥ 1 bp. Sequence_override (if present) is
    # auto-truncated/extended in `_fn` to track length_bp, so we don't gate
    # on its current length here.
    if new_last_len < 1:
        raise HTTPException(
            422,
            detail=f"Shrink would push last sub-domain below 1 bp (would become {new_last_len}).",
        )

    def _fn(d: Design) -> Design:
        # 1. Resize the strand domain. _reconcile_inline_overhangs runs inside
        #    and preserves existing sub-domains as-is (Σ length will now drift
        #    from the new overhang length until step 2 fixes it).
        d2 = _resize_strand_ends(
            d,
            [
                {
                    "strand_id": spec.strand_id,
                    "helix_id": spec.helix_id,
                    "end": body.end,
                    "delta_bp": body.delta_bp,
                }
            ],
        )
        # 2. Re-tile sub-domains: last absorbs Δ length.
        ovhg_after = next((o for o in d2.overhangs if o.id == overhang_id), None)
        if ovhg_after is None or not ovhg_after.sub_domains:
            return d2
        new_subs = list(ovhg_after.sub_domains)
        last_after = new_subs[-1]
        new_last_len_inner = (last_after.length_bp or 0) + delta_len
        # Keep sequence_override length in sync with length_bp (validator
        # requires equality). Extend with 'N' on grow, truncate on shrink.
        new_override = last_after.sequence_override
        if new_override is not None:
            cur_len = len(new_override)
            if new_last_len_inner > cur_len:
                new_override = new_override + ("N" * (new_last_len_inner - cur_len))
            elif new_last_len_inner < cur_len:
                new_override = new_override[:new_last_len_inner]
        adjusted_last = last_after.model_copy(
            update={
                "length_bp": new_last_len_inner,
                "sequence_override": new_override,
                # Tm/GC/warning caches invalidate when the slice length changes.
                "tm_celsius": None,
                "gc_percent": None,
                "hairpin_warning": False,
                "dimer_warning": False,
            }
        )
        new_subs[-1] = adjusted_last
        new_overhangs = [
            o.model_copy(update={"sub_domains": new_subs}) if o.id == overhang_id else o
            for o in d2.overhangs
        ]
        return d2.model_copy(update={"overhangs": new_overhangs})

    try:
        updated, report, _entry = design_state.mutate_with_feature_log(
            op_kind="overhang-bulk",
            label=f"Resize overhang {body.delta_bp:+d} bp",
            params={"overhang_id": overhang_id, **body.model_dump(mode="json")},
            fn=_fn,
        )
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "unknown"
        raise HTTPException(
            404, detail=f"Resize target not found: {missing!r}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    _validate_sub_domain_tiling(updated, overhang_id)
    return _design_response_with_geometry(updated, report)


# ── Sub-domain endpoints ──────────────────────────────────────────────────────


@router.get("/design/overhang/{overhang_id}/sub-domains", status_code=200)
def list_sub_domains(overhang_id: str) -> dict:
    """List sub-domains for an overhang, ordered 5'→3' by ``start_bp_offset``."""
    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    return {
        "overhang_id": overhang_id,
        "sub_domains": [
            sd.model_dump()
            for sd in sorted(spec.sub_domains, key=lambda sd: sd.start_bp_offset)
        ],
    }


class SubDomainSplitRequest(BaseModel):
    sub_domain_id: str
    split_at_offset: int  # offset within the parent overhang (0-based, strict interior)


@router.post("/design/overhang/{overhang_id}/sub-domains/split", status_code=200)
def split_sub_domain(overhang_id: str, body: SubDomainSplitRequest) -> dict:
    """Split a sub-domain into two at an interior offset.

    The 5' half retains the original sub-domain id (and any cached annotations
    are invalidated). The 3' half gets a new random UUID, name suffix
    ``" (split)"``, the same color + notes. If a ``sequence_override`` exists,
    it is sliced at the same boundary.
    """
    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)

    target = next((sd for sd in spec.sub_domains if sd.id == body.sub_domain_id), None)
    if target is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {body.sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    # ``split_at_offset`` is the absolute overhang offset (5'→3'). Translate to
    # a within-sub-domain offset and require strict interior.
    rel = body.split_at_offset - target.start_bp_offset
    if rel <= 0 or rel >= target.length_bp:
        raise HTTPException(
            422,
            detail=(
                f"split_at_offset {body.split_at_offset} is not strictly interior "
                f"to sub-domain {target.name!r} "
                f"(offset {target.start_bp_offset}, length {target.length_bp})."
            ),
        )

    # Phase 5: a sub-domain that is the endpoint of an OverhangBinding can't
    # be split without invalidating that binding's identity. Reject with 409
    # listing the offending binding ids.
    referencing = [
        bb.id
        for bb in design.overhang_bindings
        if target.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
    ]
    if referencing:
        raise HTTPException(
            409,
            detail={
                "error": "sub_domain_referenced_by_binding",
                "binding_ids": referencing,
            },
        )

    from backend.core.models import SubDomain as _SD

    override_5p = target.sequence_override[:rel] if target.sequence_override else None
    override_3p = target.sequence_override[rel:] if target.sequence_override else None

    new_5p = target.model_copy(
        update={
            "length_bp": rel,
            "sequence_override": override_5p,
            # Annotation caches must be re-derived after a split.
            "tm_celsius": None,
            "gc_percent": None,
            "hairpin_warning": False,
            "dimer_warning": False,
        }
    )
    new_3p = _SD(
        id=str(_uuid.uuid4()),
        name=f"{target.name} (split)",
        color=target.color,
        start_bp_offset=target.start_bp_offset + rel,
        length_bp=target.length_bp - rel,
        sequence_override=override_3p,
        rotation_theta_deg=target.rotation_theta_deg,
        rotation_phi_deg=target.rotation_phi_deg,
        notes=target.notes,
    )

    new_sub_doms = []
    for sd in spec.sub_domains:
        if sd.id == target.id:
            new_sub_doms.append(new_5p)
            new_sub_doms.append(new_3p)
        else:
            new_sub_doms.append(sd)
    new_sub_doms.sort(key=lambda sd: sd.start_bp_offset)

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Split sub-domain {target.name!r}",
        params={
            "overhang_id": overhang_id,
            "sub_domain_id": body.sub_domain_id,
            "split_at_offset": body.split_at_offset,
            "action": "sub-domain-split",
        },
        fn=_fn,
    )
    _validate_sub_domain_tiling(updated, overhang_id)
    return {
        **_design_response(updated, report),
        "sub_domains": [new_5p.model_dump(), new_3p.model_dump()],
    }


class SubDomainMergeRequest(BaseModel):
    sub_domain_a_id: str
    sub_domain_b_id: str


@router.post("/design/overhang/{overhang_id}/sub-domains/merge", status_code=200)
def merge_sub_domains(overhang_id: str, body: SubDomainMergeRequest) -> dict:
    """Merge two adjacent (5'→3') sub-domains into a single survivor.

    The 5' sub-domain's id is retained. ``sequence_override`` is concatenated
    when either side has one; otherwise the survivor's override is None.
    Returns 409 if any Phase-5+ binding references the retiring id (no
    such references exist yet — this is a forward-compatibility no-op check).
    """
    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)

    a = next((sd for sd in spec.sub_domains if sd.id == body.sub_domain_a_id), None)
    b = next((sd for sd in spec.sub_domains if sd.id == body.sub_domain_b_id), None)
    if a is None or b is None:
        raise HTTPException(
            404,
            detail=(f"One or both sub-domains not found on overhang {overhang_id!r}."),
        )
    if a.id == b.id:
        raise HTTPException(422, detail="Cannot merge a sub-domain with itself.")

    # Order 5'→3'; require adjacency.
    if a.start_bp_offset > b.start_bp_offset:
        a, b = b, a
    if a.start_bp_offset + a.length_bp != b.start_bp_offset:
        raise HTTPException(
            422,
            detail=(
                f"Sub-domains {a.name!r} and {b.name!r} are not adjacent "
                f"(a ends at {a.start_bp_offset + a.length_bp}, "
                f"b starts at {b.start_bp_offset})."
            ),
        )

    # Phase 5: a sub-domain that is the endpoint of an OverhangBinding can't
    # disappear without orphaning that binding. Reject the merge with 409 and
    # list the offending binding ids so the UI can offer to remove them.
    _bound: set[str] = {bb.sub_domain_a_id for bb in design.overhang_bindings} | {
        bb.sub_domain_b_id for bb in design.overhang_bindings
    }
    referencing = [
        bb.id
        for bb in design.overhang_bindings
        if a.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
        or b.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
    ]
    if (a.id in _bound or b.id in _bound) and referencing:
        raise HTTPException(
            409,
            detail={
                "error": "sub_domain_referenced_by_binding",
                "binding_ids": referencing,
            },
        )

    if a.sequence_override is not None or b.sequence_override is not None:
        # Fill missing side with 'N'×length to keep the override length valid.
        seq_a = a.sequence_override or ("N" * a.length_bp)
        seq_b = b.sequence_override or ("N" * b.length_bp)
        merged_override: Optional[str] = (seq_a + seq_b).upper()
    else:
        merged_override = None

    survivor = a.model_copy(
        update={
            "length_bp": a.length_bp + b.length_bp,
            "sequence_override": merged_override,
            "notes": (a.notes + (" + " + b.notes if b.notes else ""))
            if a.notes
            else b.notes,
            "tm_celsius": None,
            "gc_percent": None,
            "hairpin_warning": False,
            "dimer_warning": False,
        }
    )

    new_sub_doms = [
        survivor if sd.id == a.id else sd for sd in spec.sub_domains if sd.id != b.id
    ]
    new_sub_doms.sort(key=lambda sd: sd.start_bp_offset)

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Merge sub-domains {a.name!r} + {b.name!r}",
        params={
            "overhang_id": overhang_id,
            "sub_domain_a_id": body.sub_domain_a_id,
            "sub_domain_b_id": body.sub_domain_b_id,
            "action": "sub-domain-merge",
        },
        fn=_fn,
    )
    _validate_sub_domain_tiling(updated, overhang_id)
    return {
        **_design_response(updated, report),
        "sub_domain": survivor.model_dump(),
    }


class SubDomainPatchRequest(BaseModel):
    name: Optional[str] = None
    color: Optional[str] = None  # "#RRGGBB" or empty-string / null to clear
    sequence_override: Optional[str] = (
        None  # ACGTN of length == length_bp; empty/null clears
    )
    rotation_theta_deg: Optional[float] = None
    rotation_phi_deg: Optional[float] = None
    notes: Optional[str] = None


@router.patch(
    "/design/overhang/{overhang_id}/sub-domains/{sub_domain_id}", status_code=200
)
def patch_sub_domain(
    overhang_id: str, sub_domain_id: str, body: SubDomainPatchRequest
) -> dict:
    """Patch a subset of sub-domain fields.

    Per the locked design: changing ``sequence_override`` invalidates the
    annotation cache on this sub-domain AND auto-recomputes it from the
    resolved sequence (override > parent slice). If the parent strand has an
    assembled sequence, ``_resplice_overhang_in_strand`` is also invoked so
    the strand's assembled sequence reflects the new override.
    """
    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    fields_set = body.model_fields_set
    updates: dict = {}

    if "name" in fields_set and body.name is not None:
        if not body.name.strip():
            raise HTTPException(422, detail="name must be non-empty.")
        updates["name"] = body.name

    if "color" in fields_set:
        if body.color is None or body.color == "":
            updates["color"] = None
        else:
            if not _HEX_RE.match(body.color):
                raise HTTPException(422, detail="color must be #RRGGBB hex.")
            updates["color"] = body.color

    sequence_override_changed = False
    if "sequence_override" in fields_set:
        if body.sequence_override is None or body.sequence_override == "":
            updates["sequence_override"] = None
        else:
            override = body.sequence_override.upper()
            if len(override) != sd.length_bp:
                raise HTTPException(
                    422,
                    detail=(
                        f"sequence_override length ({len(override)}) must equal "
                        f"length_bp ({sd.length_bp})."
                    ),
                )
            if any(b not in _DNA_BASES for b in override):
                raise HTTPException(
                    422, detail=("sequence_override must contain only ACGTN bases.")
                )
            updates["sequence_override"] = override
        sequence_override_changed = True

    if "rotation_theta_deg" in fields_set and body.rotation_theta_deg is not None:
        updates["rotation_theta_deg"] = float(body.rotation_theta_deg)
    if "rotation_phi_deg" in fields_set and body.rotation_phi_deg is not None:
        updates["rotation_phi_deg"] = float(body.rotation_phi_deg)
    if "notes" in fields_set and body.notes is not None:
        updates["notes"] = body.notes

    if not updates:
        # Nothing changed — return current state.
        from backend.core.validator import validate_design as _vd

        return _design_response(design, _vd(design))

    # If the override changed, invalidate the cache and recompute annotations.
    if sequence_override_changed:
        updates.update(
            {
                "tm_celsius": None,
                "gc_percent": None,
                "hairpin_warning": False,
                "dimer_warning": False,
            }
        )

    new_sd = sd.model_copy(update=updates)

    if sequence_override_changed:
        # Recompute annotations from the new resolved sequence.
        new_seq = (
            new_sd.sequence_override
            if new_sd.sequence_override is not None
            else _resolve_sub_domain_sequence(spec, new_sd)
        )
        ann = _compute_sub_domain_annotations(
            new_seq, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
        )
        new_sd = new_sd.model_copy(update=ann)

    new_sub_doms = [new_sd if s.id == sd.id else s for s in spec.sub_domains]

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        updated = _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))
        if sequence_override_changed:
            updated = _resplice_overhang_in_strand(updated, overhang_id, cur.strand_id)
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Patch sub-domain {sd.name!r}",
        params={
            "overhang_id": overhang_id,
            "sub_domain_id": sub_domain_id,
            "fields": sorted(fields_set),
            "action": "sub-domain-patch",
        },
        fn=_fn,
    )
    _validate_sub_domain_tiling(updated, overhang_id)
    # Phase 3: after any sub-domain mutation that can change a resolved
    # sequence, rescan for boundary hairpins (junctions spanning adjacent
    # sub-domains). Both sides of a flagged boundary get hairpin_warning=True;
    # stale warnings are cleared on the same pass. Persist via set_design so
    # the response we hand back reflects the warnings.
    if sequence_override_changed:
        updated = _apply_boundary_hairpin_warnings(updated, overhang_id)
        design_state.set_design(updated)
        from backend.core.validator import validate_design as _vd

        report = _vd(updated)
    return _design_response(updated, report)


@router.post(
    "/design/overhang/{overhang_id}/sub-domains/{sub_domain_id}/recompute-annotations",
    status_code=200,
)
def recompute_sub_domain_annotations(overhang_id: str, sub_domain_id: str) -> dict:
    """Recompute Tm/GC/hairpin/dimer cache from the resolved sequence.

    Uses the active design's ``tm_settings`` for Na+ and oligo concentration.
    Returns 404 if either id is missing.
    """
    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    seq = _resolve_sub_domain_sequence(spec, sd)
    ann = _compute_sub_domain_annotations(
        seq, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
    )
    new_sd = sd.model_copy(update=ann)
    new_sub_doms = [new_sd if s.id == sd.id else s for s in spec.sub_domains]

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Recompute annotations: {sd.name!r}",
        params={
            "overhang_id": overhang_id,
            "sub_domain_id": sub_domain_id,
            "action": "sub-domain-recompute-annotations",
        },
        fn=_fn,
    )
    _validate_sub_domain_tiling(updated, overhang_id)
    # Phase 3: boundary-hairpin scan after annotation recompute (this endpoint
    # is the explicit "user clicked the ↻ button" path; treat it the same as
    # PATCH).
    updated = _apply_boundary_hairpin_warnings(updated, overhang_id)
    design_state.set_design(updated)
    from backend.core.validator import validate_design as _vd

    report = _vd(updated)
    # Refresh the local new_sd reference for the response payload — boundary
    # detection may have flipped hairpin_warning on this sub-domain.
    cur_ovhg = next((o for o in updated.overhangs if o.id == overhang_id), None)
    cur_sd = next(
        (
            s
            for s in (cur_ovhg.sub_domains if cur_ovhg else [])
            if s.id == sub_domain_id
        ),
        None,
    )
    return {
        **_design_response(updated, report),
        "sub_domain": (cur_sd or new_sd).model_dump(),
    }


class GenerateSubDomainRequest(BaseModel):
    seed: Optional[int] = None


@router.post(
    "/design/overhang/{overhang_id}/sub-domains/{sub_domain_id}/generate-random",
    status_code=200,
)
def generate_sub_domain_random(
    overhang_id: str,
    sub_domain_id: str,
    body: GenerateSubDomainRequest,
) -> dict:
    """Generate a rare structure-safe sequence for ONE sub-domain.

    Phase 3 (overhang revamp): the user clicks "Gen this sub-domain" in the
    Domain Designer. We re-roll only the target sub-domain. Neighbours are
    treated as locked: their resolved sequence (override OR parent slice) is
    fed as a locked override into the generator's corpus so it knows to avoid
    matching them. The target's old override (if any) is dropped before the
    re-roll.

    Blocks (422) when the target already has an active ``hairpin_warning`` or
    ``dimer_warning`` — clear those upstream first (e.g. tweak the parent or
    a neighbour) so we don't blindly regenerate into the same trap.

    Body: ``{seed?: int}``. When present, seeds ``random`` for reproducible
    generation in tests / for record-and-replay.
    """
    import random as _random
    from backend.core.overhang_generator import (
        generate_overhang_sequence_with_overrides,
    )
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    spec = _find_ovhg_or_404(design, overhang_id)
    sd = next((s for s in spec.sub_domains if s.id == sub_domain_id), None)
    if sd is None:
        raise HTTPException(
            404,
            detail=(
                f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
            ),
        )

    # 1. Block on existing warnings — user should fix those first.
    if sd.hairpin_warning or sd.dimer_warning:
        raise HTTPException(
            422,
            detail=(
                f"Sub-domain {sd.name!r} has an active hairpin/dimer warning; "
                f"resolve it before regenerating."
            ),
        )

    # 2. Build a temp sub-domain list where this target has NO override
    #    (so the generator fills it) and every other sub-domain's resolved
    #    sequence is locked as a temporary override. This pins neighbours
    #    even when they had no explicit override (the parent-slice resolves).
    temp_sub_doms = []
    for s in spec.sub_domains:
        if s.id == sub_domain_id:
            temp_sub_doms.append(s.model_copy(update={"sequence_override": None}))
            continue
        resolved = _resolve_sub_domain_sequence(spec, s)
        if resolved is None or len(resolved) != s.length_bp:
            # No resolvable sequence — fall back to whatever override it has
            # (may be None; the generator will then fill it as an unlocked
            # slice, but neighbouring fills still avoid each other via the
            # corpus).
            temp_sub_doms.append(s)
        else:
            temp_sub_doms.append(s.model_copy(update={"sequence_override": resolved}))

    # 3. Seeded generation (optional). random.seed mutates global RNG state;
    #    callers that care about determinism pass seed.
    if body.seed is not None:
        _random.seed(int(body.seed))

    scaffold = design.scaffold()
    scaffold_seq = scaffold.sequence if scaffold and scaffold.sequence else ""
    staple_seqs = [
        s.sequence
        for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]

    # 4. Call the override-aware generator. It returns the FULL overhang
    #    sequence with the locked overrides verbatim and the target slot
    #    filled with a freshly generated piece.
    full_seq = generate_overhang_sequence_with_overrides(
        scaffold_seq,
        staple_seqs,
        temp_sub_doms,
    )

    # 5. Slice out the target sub-domain's segment.
    start = sd.start_bp_offset
    end = start + sd.length_bp
    new_override = full_seq[start:end]
    if len(new_override) != sd.length_bp:
        raise HTTPException(
            500,
            detail=(
                f"Sub-domain generator returned wrong length "
                f"({len(new_override)} vs {sd.length_bp})."
            ),
        )

    # 6. Apply via mutate_with_feature_log. The patch sets sequence_override
    #    and recomputes annotations from the new resolved sequence.
    ann = _compute_sub_domain_annotations(
        new_override,
        na_mM=design.tm_settings.na_mM,
        conc_nM=design.tm_settings.conc_nM,
    )
    new_sd = sd.model_copy(update={"sequence_override": new_override, **ann})
    new_sub_doms = [new_sd if s.id == sd.id else s for s in spec.sub_domains]

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        updated_ = _replace_ovhg(
            d, cur.model_copy(update={"sub_domains": new_sub_doms})
        )
        # Re-splice into the assembled strand sequence so downstream consumers
        # (atomistic, CSV export, etc.) see the new bases.
        updated_ = _resplice_overhang_in_strand(updated_, overhang_id, cur.strand_id)
        return updated_

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Generate sub-domain {sd.name!r}",
        params={
            "overhang_id": overhang_id,
            "sub_domain_id": sub_domain_id,
            "action": "sub-domain-generate-random",
        },
        fn=_fn,
    )
    _validate_sub_domain_tiling(updated, overhang_id)

    # 7. Re-run boundary-hairpin detection now that the target has a new
    #    sequence; flag/clear adjacent sub-domains accordingly.
    updated = _apply_boundary_hairpin_warnings(updated, overhang_id)
    design_state.set_design(updated)
    report = validate_design(updated)

    cur_ovhg = next((o for o in updated.overhangs if o.id == overhang_id), None)
    cur_sd = next(
        (
            s
            for s in (cur_ovhg.sub_domains if cur_ovhg else [])
            if s.id == sub_domain_id
        ),
        None,
    )
    return {
        **_design_response(updated, report),
        "sub_domain": (cur_sd or new_sd).model_dump(),
    }


class TmSettingsPatchRequest(BaseModel):
    na_mM: Optional[float] = None
    conc_nM: Optional[float] = None


@router.patch("/design/tm-settings", status_code=200)
def patch_tm_settings(body: TmSettingsPatchRequest) -> dict:
    """Update design-level Tm conditions. Invalidates all sub-domain Tm caches.

    Salt and concentration values must be positive. Both fields are optional;
    omitting one leaves it unchanged.
    """
    design = design_state.get_or_404()

    new_na = design.tm_settings.na_mM if body.na_mM is None else float(body.na_mM)
    new_conc = (
        design.tm_settings.conc_nM if body.conc_nM is None else float(body.conc_nM)
    )
    if new_na <= 0 or new_conc <= 0:
        raise HTTPException(422, detail="na_mM and conc_nM must be positive.")

    from backend.core.models import TmSettings

    new_settings = TmSettings(na_mM=new_na, conc_nM=new_conc)

    # Invalidate ALL sub-domain Tm caches across every overhang. GC / hairpin /
    # dimer are independent of conditions, so we leave them set — callers can
    # explicitly re-run /recompute-annotations to refresh everything together.
    new_overhangs = []
    for ovhg in design.overhangs:
        if not ovhg.sub_domains:
            new_overhangs.append(ovhg)
            continue
        new_sub_doms = [
            sd.model_copy(update={"tm_celsius": None}) for sd in ovhg.sub_domains
        ]
        new_overhangs.append(ovhg.model_copy(update={"sub_domains": new_sub_doms}))

    def _fn(d: Design) -> Design:
        return d.model_copy(
            update={
                "tm_settings": new_settings,
                "overhangs": new_overhangs,
            }
        )

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Tm settings: Na+ {new_na:g} mM, oligo {new_conc:g} nM",
        params={
            "na_mM": new_na,
            "conc_nM": new_conc,
            "action": "tm-settings-update",
        },
        fn=_fn,
    )
    return _design_response(updated, report)


# ── Overhang connections (metadata-only linker records) ───────────────────────


# Overhang end-polarity & linker-compatibility rules live in
# backend/core/overhang_ops.py (pure topology, no api deps — Refactor #38).
# _overhang_end / _used_overhang_ends / _check_linker_compatibility are
# imported back at the top of this module.


class OverhangConnectionCreateRequest(BaseModel):
    overhang_a_id: str
    overhang_a_attach: Literal["root", "free_end"]
    overhang_b_id: str
    overhang_b_attach: Literal["root", "free_end"]
    linker_type: Literal["ss", "ds"]
    length_value: float
    length_unit: Literal["bp", "nm"]
    name: Optional[str] = None  # auto-assigned L1/L2/… if omitted
    # Optional bridge sequence supplied by the Connection Types tab's bridge
    # text box. When provided, it's stitched into the linker strand(s) after
    # topology creation: ss strand sequence = [comp_a, bridge, comp_b];
    # ds strand __a = [comp_a, bridge]; ds strand __b uses RC(bridge) so the
    # two halves pair on the virtual helix. Complement portions come from the
    # bound overhang sequence (RC), or N×L when the overhang has none.
    bridge_sequence: Optional[str] = None


class OverhangConnectionPatchRequest(BaseModel):
    name: Optional[str] = None
    length_value: Optional[float] = None
    length_unit: Optional[Literal["bp", "nm"]] = None
    # Sentinel-style update for the linker's bridge_sequence: omit the field
    # to leave it untouched; pass an empty string ("") to clear it; pass a
    # non-empty string to assign. Uppercased + stripped server-side; only
    # ACGTN characters survive.
    bridge_sequence: Optional[str] = None


@router.post("/design/overhang-connections", status_code=201)
def create_overhang_connection(body: OverhangConnectionCreateRequest) -> dict:
    """Append a new metadata-only OverhangConnection to the active design.

    Validates that both referenced overhangs exist, are distinct, and that the
    end-type / attach-type / linker-type combination is physically feasible.
    Does not modify any strand topology — purely a user-defined annotation.
    """
    from backend.core.lattice import (
        assign_overhang_connection_names,
        generate_linker_topology,
    )

    design = design_state.get_or_404()

    if body.overhang_a_id == body.overhang_b_id:
        raise HTTPException(400, detail="overhang_a_id and overhang_b_id must differ.")
    # Allow length_value == 0 for indirect connection types (shared linker
    # strand → no user-controllable bridge nucleotides).
    if body.length_value < 0:
        raise HTTPException(400, detail="length_value must be non-negative.")
    existing_ids = {o.id for o in design.overhangs}
    for ovhg_id in (body.overhang_a_id, body.overhang_b_id):
        if ovhg_id not in existing_ids:
            raise HTTPException(404, detail=f"Overhang {ovhg_id!r} not found.")

    err = _check_linker_compatibility(
        _overhang_end(body.overhang_a_id),
        _overhang_end(body.overhang_b_id),
        body.overhang_a_attach,
        body.overhang_b_attach,
        body.linker_type,
    )
    if err:
        raise HTTPException(400, detail=err)

    # Per-end uniqueness: a (overhang, attach) pair can only be in one connection.
    used = _used_overhang_ends(design)
    for ovhg_id, attach in (
        (body.overhang_a_id, body.overhang_a_attach),
        (body.overhang_b_id, body.overhang_b_attach),
    ):
        if (ovhg_id, attach) in used:
            attach_label = "free end" if attach == "free_end" else "root"
            raise HTTPException(
                400,
                detail=f"Overhang {ovhg_id!r} is already linked at its {attach_label}.",
            )

    bridge_seq = (body.bridge_sequence or "").upper().strip() or None
    conn = OverhangConnection(
        name=body.name,
        overhang_a_id=body.overhang_a_id,
        overhang_a_attach=body.overhang_a_attach,
        overhang_b_id=body.overhang_b_id,
        overhang_b_attach=body.overhang_b_attach,
        linker_type=body.linker_type,
        length_value=body.length_value,
        length_unit=body.length_unit,
        bridge_sequence=bridge_seq,
    )

    from backend.core.cluster_reconcile import MutationReport

    bridge_id = f"__lnk__{conn.id}"

    def _fn(d: Design):
        nxt = d.model_copy(
            update={"overhang_connections": [*d.overhang_connections, conn]}
        )
        nxt = assign_overhang_connection_names(nxt)
        nxt = generate_linker_topology(nxt, conn)
        # Auto-assign so the new linker complement (binds_overhang_id) carries the
        # real reverse-complement of its overhang for simulation — no-op until the
        # scaffold is sequenced. Targeted to the two overhangs' own strands, their
        # binders, and the strands on the new __lnk__ bridge helix, so a hand-typed
        # sequence on an unrelated staple survives the connection.
        from backend.core.sequences import (
            overhang_dependent_strand_ids,
            reassign_strands,
        )

        affected = overhang_dependent_strand_ids(
            nxt, [conn.overhang_a_id, conn.overhang_b_id], extra_helix_ids=[bridge_id]
        )
        nxt = reassign_strands(nxt, affected)
        # The virtual __lnk__ bridge helix is invisible to clustering — orphan it
        # so the reconciler doesn't pull it into a cluster via lattice proximity.
        return nxt, MutationReport(new_helix_origins={bridge_id: None})

    a_label = next(
        (o.label for o in design.overhangs if o.id == body.overhang_a_id),
        body.overhang_a_id[:10],
    )
    b_label = next(
        (o.label for o in design.overhangs if o.id == body.overhang_b_id),
        body.overhang_b_id[:10],
    )
    label = f"Linker {body.linker_type} {a_label}↔{b_label} ({body.length_value:g} {body.length_unit})"

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="linker-add",
        label=label,
        params=body.model_dump(mode="json"),
        fn=_fn,
    )
    return _design_response(updated, report)


@router.patch("/design/overhang-connections/{conn_id}", status_code=200)
def patch_overhang_connection(
    conn_id: str, body: OverhangConnectionPatchRequest
) -> dict:
    """Update name / length_value / length_unit on an existing connection.

    Changing length_value or length_unit auto-rebuilds the linker topology
    (the old strand(s) and virtual helix are stripped and regenerated against
    the new length). Other fields (overhangs, attach points, linker_type) are
    immutable through this endpoint — to change them, delete and re-create.
    """
    from backend.core.lattice import (
        generate_linker_topology,
        remove_linker_topology,
    )

    design = design_state.get_or_404()
    target = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)
    if "name" in patch:
        new_name = (patch["name"] or "").strip()
        if not new_name:
            raise HTTPException(400, detail="name must be a non-empty string.")
        clash = next(
            (
                c
                for c in design.overhang_connections
                if c.id != conn_id and c.name == new_name
            ),
            None,
        )
        if clash is not None:
            raise HTTPException(
                400, detail=f"Connection name {new_name!r} is already in use."
            )
        patch["name"] = new_name
    if (
        "length_value" in patch
        and patch["length_value"] is not None
        and patch["length_value"] < 0
    ):
        raise HTTPException(400, detail="length_value must be non-negative.")
    # bridge_sequence: "" → clear, "ACGT…" → assign (uppercased, ACGTN only),
    # omitted → leave untouched. Run this BEFORE the `if v is not None` filter
    # below so an explicit clear isn't silently dropped.
    bridge_clear = False
    if "bridge_sequence" in patch:
        raw = patch["bridge_sequence"]
        if raw is None or raw == "":
            bridge_clear = True
            del patch["bridge_sequence"]
        else:
            cleaned = "".join(ch for ch in str(raw).upper() if ch in "ACGTN")
            patch["bridge_sequence"] = cleaned or None
            if patch["bridge_sequence"] is None:
                bridge_clear = True
                del patch["bridge_sequence"]

    new_target = target.model_copy(
        update={k: v for k, v in patch.items() if v is not None}
    )
    if bridge_clear:
        new_target = new_target.model_copy(update={"bridge_sequence": None})
    new_list = [
        new_target if c.id == conn_id else c for c in design.overhang_connections
    ]
    updated = design.model_copy(update={"overhang_connections": new_list})

    # Auto-rebuild the linker topology if length changed (length_value or unit).
    length_changed = (
        "length_value" in patch and new_target.length_value != target.length_value
    ) or ("length_unit" in patch and new_target.length_unit != target.length_unit)
    if length_changed:
        # Capture the EXISTING complement-domain (binding) bp ranges so they
        # survive the bridge regeneration. Without this, the user's manually-
        # resized binding domains would snap back to the overhang's full
        # length on every linker bridge resize. Each strand may have ONE
        # complement (ds case) or TWO (ss case: complementA + complementB).
        bridge_helix_id = f"__lnk__{conn_id}"
        # strand_id → list of {helix_id, start_bp, end_bp, direction}, in
        # 5'→3' order matching how _make_complement_domain produced them.
        prev_complements: dict[str, list[dict]] = {}
        for strand in updated.strands:
            if not strand.id.startswith(bridge_helix_id + "__"):
                continue
            comps = [
                {
                    "helix_id": d.helix_id,
                    "start_bp": d.start_bp,
                    "end_bp": d.end_bp,
                    "direction": d.direction,
                }
                for d in strand.domains
                if d.helix_id != bridge_helix_id
            ]
            if comps:
                prev_complements[strand.id] = comps

        updated = remove_linker_topology(updated, conn_id)
        updated = generate_linker_topology(updated, new_target)

        # Restore the user-set complement-domain bp ranges on the regenerated
        # strands. Match snapshot complements to new domains by `helix_id`
        # (each helix id appears at most once per strand because each strand
        # touches each overhang helix at most once).
        if prev_complements:
            new_strands = []
            for strand in updated.strands:
                snaps = prev_complements.get(strand.id)
                if not snaps:
                    new_strands.append(strand)
                    continue
                snap_by_helix = {s["helix_id"]: s for s in snaps}
                patched_doms = []
                for d in strand.domains:
                    s = (
                        snap_by_helix.get(d.helix_id)
                        if d.helix_id != bridge_helix_id
                        else None
                    )
                    if s is not None:
                        patched_doms.append(
                            d.model_copy(
                                update={
                                    "start_bp": s["start_bp"],
                                    "end_bp": s["end_bp"],
                                    "direction": s["direction"],
                                }
                            )
                        )
                    else:
                        patched_doms.append(d)
                new_strands.append(
                    strand.model_copy(
                        update={
                            "domains": patched_doms,
                            "sequence": None,  # length may have changed; clear
                        }
                    )
                )
            updated = updated.model_copy(update={"strands": new_strands})

    from backend.core.cluster_reconcile import MutationReport

    bridge_id = f"__lnk__{conn_id}"
    mreport = MutationReport(new_helix_origins={bridge_id: None})
    updated, report = design_state.replace_with_reconcile(updated, mreport)
    return _design_response(updated, report)


@router.delete("/design/overhang-connections/{conn_id}", status_code=200)
def delete_overhang_connection(conn_id: str) -> dict:
    """Remove a single OverhangConnection by id, plus its linker topology.

    Emits a `linker-delete` SnapshotLogEntry so the deletion shows up on the
    feature-log timeline alongside the linker's `linker-add` entry — keeps
    the Overhangs Manager and the feature log in sync (any change in either
    surface is visible in the timeline). Reverting the delete entry brings
    the linker back exactly as it was.
    """
    from backend.core.lattice import remove_linker_topology

    design = design_state.get_or_404()
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    a_label = next(
        (o.label for o in design.overhangs if o.id == conn.overhang_a_id),
        conn.overhang_a_id[:10],
    )
    b_label = next(
        (o.label for o in design.overhangs if o.id == conn.overhang_b_id),
        conn.overhang_b_id[:10],
    )
    label = f"Delete linker {conn.name or conn.id[:8]} ({a_label}↔{b_label})"

    def _fn(d: Design) -> Design:
        new_list = [c for c in d.overhang_connections if c.id != conn_id]
        nxt = d.model_copy(update={"overhang_connections": new_list})
        return remove_linker_topology(nxt, conn_id)

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="linker-delete",
        label=label,
        params={
            "conn_id": conn_id,
            "linker_type": conn.linker_type,
            "overhang_a_id": conn.overhang_a_id,
            "overhang_b_id": conn.overhang_b_id,
        },
        fn=_fn,
    )
    return _design_response(updated, report)


# ── Connection versions (design-exploration candidates) ───────────────────────
# Pure metadata: alternative connection specs for the same overhang pair, with
# at most one `applied` (materialized) per pair. Persisted on the design so they
# survive save/reload. Materializing a version ("Apply") is frontend-orchestrated
# in v1 (resize overhangs + set sequences + recreate the real connection/binding);
# these endpoints only store/manage the candidate specs.


class ConnectionVersionCreateRequest(BaseModel):
    overhang_a_id: str
    overhang_b_id: str
    connection_type: str  # CT variant id
    overhang_a_seq: Optional[str] = None
    overhang_b_seq: Optional[str] = None
    bridge_length: int = 0
    bridge_seq: Optional[str] = None
    applied: bool = False
    name: Optional[str] = None  # auto V1/V2/… per pair if omitted


class ConnectionVersionPatchRequest(BaseModel):
    name: Optional[str] = None
    connection_type: Optional[str] = None
    overhang_a_seq: Optional[str] = None
    overhang_b_seq: Optional[str] = None
    bridge_length: Optional[int] = None
    bridge_seq: Optional[str] = None
    applied: Optional[bool] = None


def _cv_clean_seq(s) -> Optional[str]:
    if not s:
        return None
    cleaned = "".join(ch for ch in str(s).upper() if ch in "ACGTN")
    return cleaned or None


def _cv_sequence_for_live_overhang(
    d: Design, overhang_id: str, seq: Optional[str]
) -> Optional[str]:
    """Return *seq* adjusted to the overhang's current backing-domain length.

    Connection versions remember sequence content, but the live overhang geometry
    can change later via free-end resize. Applying a stale version must not use
    an old sequence length to resize the user's current geometry back.
    """
    cleaned = _cv_clean_seq(seq)
    if cleaned is None:
        return None
    live_len = _ovhg_backing_length(d, overhang_id)
    if live_len is None:
        ov = next((o for o in d.overhangs if o.id == overhang_id), None)
        live_len = sum(sd.length_bp for sd in (ov.sub_domains or [])) if ov else None
    if live_len is None or live_len <= 0:
        return cleaned
    if len(cleaned) == live_len:
        return cleaned
    if len(cleaned) > live_len:
        return cleaned[:live_len]
    return cleaned + ("N" * (live_len - len(cleaned)))


def _cv_pair_key(a: str, b: str) -> frozenset:
    return frozenset((a, b))


def _assign_connection_version_names(d: Design) -> None:
    """Fill empty version names V1, V2, … per (unordered) overhang pair."""
    by_pair: dict = {}
    for v in d.connection_versions:
        by_pair.setdefault(_cv_pair_key(v.overhang_a_id, v.overhang_b_id), []).append(v)
    for versions in by_pair.values():
        versions.sort(key=lambda v: v.created_at)
        used = {v.name for v in versions if v.name}
        n = 1
        for v in versions:
            if v.name:
                continue
            while f"V{n}" in used:
                n += 1
            v.name = f"V{n}"
            used.add(v.name)
            n += 1


def _cv_enforce_applied_mutex(d: Design, applied_id: str) -> None:
    """When version `applied_id` is applied, clear `applied` on its pair-siblings."""
    target = next((v for v in d.connection_versions if v.id == applied_id), None)
    if target is None or not target.applied:
        return
    key = _cv_pair_key(target.overhang_a_id, target.overhang_b_id)
    for v in d.connection_versions:
        if v.id != applied_id and _cv_pair_key(v.overhang_a_id, v.overhang_b_id) == key:
            v.applied = False


@router.post("/design/connection-versions", status_code=201)
def create_connection_version(body: ConnectionVersionCreateRequest) -> dict:
    """Append a candidate connection version for an overhang pair."""
    design = design_state.get_or_404()
    ids = {o.id for o in design.overhangs}
    for oid in (body.overhang_a_id, body.overhang_b_id):
        if oid not in ids:
            raise HTTPException(404, detail=f"Overhang {oid!r} not found.")
    if body.overhang_a_id == body.overhang_b_id:
        raise HTTPException(
            400, detail="A connection version needs two distinct overhangs."
        )

    version = ConnectionVersion(
        name=(body.name or "").strip(),
        overhang_a_id=body.overhang_a_id,
        overhang_b_id=body.overhang_b_id,
        connection_type=body.connection_type,
        overhang_a_seq=_cv_clean_seq(body.overhang_a_seq),
        overhang_b_seq=_cv_clean_seq(body.overhang_b_seq),
        bridge_length=max(0, int(body.bridge_length or 0)),
        bridge_seq=_cv_clean_seq(body.bridge_seq),
        applied=bool(body.applied),
    )

    def _fn(d: Design) -> None:
        d.connection_versions = [*d.connection_versions, version]
        _cv_enforce_applied_mutex(d, version.id)
        _assign_connection_version_names(d)

    updated, report = design_state.mutate_and_validate(_fn)
    return _design_response(updated, report)


@router.patch("/design/connection-versions/{version_id}", status_code=200)
def patch_connection_version(
    version_id: str, body: ConnectionVersionPatchRequest
) -> dict:
    """Update a candidate version's fields. Setting applied=True clears applied
    on the pair's other versions (at most one materialized per pair)."""
    design = design_state.get_or_404()
    if not any(v.id == version_id for v in design.connection_versions):
        raise HTTPException(404, detail=f"Connection version {version_id!r} not found.")
    patch = body.model_dump(exclude_unset=True)

    def _fn(d: Design) -> None:
        v = next((x for x in d.connection_versions if x.id == version_id), None)
        if v is None:
            return
        if "name" in patch and (patch["name"] or "").strip():
            v.name = patch["name"].strip()
        if "connection_type" in patch and patch["connection_type"]:
            v.connection_type = patch["connection_type"]
        if "overhang_a_seq" in patch:
            v.overhang_a_seq = _cv_clean_seq(patch["overhang_a_seq"])
        if "overhang_b_seq" in patch:
            v.overhang_b_seq = _cv_clean_seq(patch["overhang_b_seq"])
        if "bridge_length" in patch and patch["bridge_length"] is not None:
            v.bridge_length = max(0, int(patch["bridge_length"]))
        if "bridge_seq" in patch:
            v.bridge_seq = _cv_clean_seq(patch["bridge_seq"])
        if "applied" in patch and patch["applied"] is not None:
            v.applied = bool(patch["applied"])
            if v.applied:
                _cv_enforce_applied_mutex(d, v.id)

    updated, report = design_state.mutate_and_validate(_fn)
    return _design_response(updated, report)


@router.delete("/design/connection-versions/{version_id}", status_code=200)
def delete_connection_version(version_id: str) -> dict:
    """Remove a candidate version (does NOT touch any materialized topology)."""
    design = design_state.get_or_404()
    if not any(v.id == version_id for v in design.connection_versions):
        raise HTTPException(404, detail=f"Connection version {version_id!r} not found.")

    def _fn(d: Design) -> None:
        d.connection_versions = [v for v in d.connection_versions if v.id != version_id]

    updated, report = design_state.mutate_and_validate(_fn)
    return _design_response(updated, report)


# ── Connection-version mapping helpers (mirror frontend ct_icons.js) ───────────


def _cv_attach_pair(t: str):
    if isinstance(t, str):
        if t.startswith("end-to-root"):
            return ("free_end", "root")
        if t.startswith("root-to-end"):
            return ("root", "free_end")
        if t.startswith("root-to-root"):
            return ("root", "root")
        if t.startswith("end-to-end"):
            return ("free_end", "free_end")
    return ("root", "root")


def _cv_is_direct(t: str) -> bool:
    return t in ("end-to-root", "root-to-root")


def _cv_is_indirect(t: str) -> bool:
    return t in ("root-to-root-indirect", "end-to-end-indirect")


def _cv_linker_type(t: str) -> str:
    return "ds" if (isinstance(t, str) and "dsdna" in t) else "ss"


def _cv_sub_domain_at_attach(d: Design, ovhg_id: str, attach: str):
    ov = next((o for o in d.overhangs if o.id == ovhg_id), None)
    if ov is None or not ov.sub_domains:
        return None
    ordered = sorted(ov.sub_domains, key=lambda sd: sd.start_bp_offset or 0)
    return (ordered[0] if attach == "root" else ordered[-1]).id


def _cv_create_bound_binding(
    d: Design, a_id: str, b_id: str, attach_a: str, attach_b: str, connection_type: str
) -> Design:
    """Materialize a DIRECT connection (root-to-root OR end-to-root) as a single
    non-consuming `OverhangBinding`, relocated on apply so the duplex renders
    immediately and overhang B's embedded-strand bond is left stretched.

    Unified path (2026-06-30, replaces the end-to-root binder splice): A is the
    driver (its helix HOSTS the duplex), B is the driven side (its tip domain is
    relocated onto A's helix, antiparallel — `compute_bind_topology`/`apply_bind_topology`).
    Neither overhang is consumed; both stay in `design.overhangs`. The bound flag is
    set but NO cluster relax runs, so the cross-helix root↔tip bond is visibly
    stretched until the user hits Relax.
    """
    from backend.core.binding_relax import apply_bind_topology, compute_bind_topology

    sd_a = _cv_sub_domain_at_attach(d, a_id, attach_a)
    sd_b = _cv_sub_domain_at_attach(d, b_id, attach_b)
    if not (sd_a and sd_b):
        return d  # no sub-domains → can't bind (mirrors the old direct silent-skip)

    # Length-preservation: a direct binding relocates one WHOLE tip domain onto the
    # other, so it requires equal-length attach sub-domains. DIFFERENT-length
    # overhangs are represented by the Duplex (paired window + toehold) — skip the
    # binding here (its unequal-length record would fail validation anyway; the
    # binding-based geometry for different lengths is deferred). The duplex is
    # created separately by the frontend's _ensureDuplexForPair.
    def _sd_len(sd_id: str) -> Optional[int]:
        for o in d.overhangs:
            for sd in o.sub_domains or []:
                if sd.id == sd_id:
                    return sd.length_bp
        return None

    if _sd_len(sd_a) != _sd_len(sd_b):
        return d

    used = {b.name for b in d.overhang_bindings}
    n = 1
    while f"B{n}" in used:
        n += 1
    binding = OverhangBinding(
        name=f"B{n}",
        sub_domain_a_id=sd_a,
        sub_domain_b_id=sd_b,
        overhang_a_id=a_id,
        overhang_b_id=b_id,
        driver_oh_id=a_id,
        driven_oh_id=b_id,
        connection_type=connection_type,
        bound=True,
    )
    topology = compute_bind_topology(d, binding, driver_side="a")
    binding = binding.model_copy(update={"prior_driven_topology": topology.snapshot})
    d = d.model_copy(update={"overhang_bindings": [*d.overhang_bindings, binding]})
    d = apply_bind_topology(d, topology)

    # Re-seat the relocated duplex like a linker bridge: ORIENTED along and CENTERED
    # on the chord between its two embedded-staple connections (A's root junction and
    # B's root junction), so both root bonds share the stretch symmetrically and are
    # minimized. Persisted as the DRIVER's OverhangSpec.rotation + translation so the
    # whole duplex (driver overhang + co-moving driven tip partner) transforms rigidly
    # at geometry time. Zero both first so the placement is measured against the
    # freshly-relocated (un-seated, identity) geometry, then store the result.
    from backend.core.direct_relax import duplex_midpoint_placement

    d = d.model_copy(
        update={
            "overhangs": [
                o.model_copy(
                    update={
                        "rotation": [0.0, 0.0, 0.0, 1.0],
                        "translation": [0.0, 0.0, 0.0],
                    }
                )
                if o.id == a_id
                else o
                for o in d.overhangs
            ]
        }
    )
    placement = duplex_midpoint_placement(d, a_id, b_id)
    if placement is not None:
        rot, trans = placement
        d = d.model_copy(
            update={
                "overhangs": [
                    o.model_copy(update={"rotation": rot, "translation": trans})
                    if o.id == a_id
                    else o
                    for o in d.overhangs
                ]
            }
        )
    # Promote the just-placed pose onto a first-class child DUPLEX cluster (sidebar-listed,
    # gizmo-movable, drift-free) — geometry+axis neutral (proven on 2x2_OH_test).
    # [[overhang-duplex-cluster]] P1b.
    from backend.core.duplex_cluster import materialize_duplex_cluster

    d, _cid = materialize_duplex_cluster(d, a_id)
    return d


@router.post("/design/connection-versions/{version_id}/apply", status_code=200)
def apply_connection_version(version_id: str) -> dict:
    """Materialize a candidate version ATOMICALLY (one undo): set both overhang
    sequences (resizing each overhang to the sequence length), tear down the
    pair's current OverhangConnection / OverhangBinding, and (re)create the
    version's connection type (linker with bridge, or a direct binding). Marks
    the version ``applied`` and clears ``applied`` on the pair's other versions.

    This is the backend replacement for the v1 frontend-orchestrated apply — it
    handles overhang LENGTH + sequence + connection-type changes in one step.
    """
    from backend.core.binding_relax import revert_bind_topology
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import (
        generate_linker_topology,
        remove_linker_topology,
        assign_overhang_connection_names,
    )

    design = design_state.get_or_404()
    v = next((x for x in design.connection_versions if x.id == version_id), None)
    if v is None:
        raise HTTPException(404, detail=f"Connection version {version_id!r} not found.")
    a_id, b_id, vtype = v.overhang_a_id, v.overhang_b_id, v.connection_type
    direct = _cv_is_direct(vtype)
    indirect = _cv_is_indirect(vtype)
    attach_a, attach_b = _cv_attach_pair(vtype)
    bridge_seq = (v.bridge_seq or "").upper().strip() or None
    a_label = next((o.label for o in design.overhangs if o.id == a_id), a_id[:8])
    b_label = next((o.label for o in design.overhangs if o.id == b_id), b_id[:8])

    def _fn(d: Design):
        # 1. Sequences: patch each overhang, but preserve the live geometry
        #    length. A version can be created, then the user can drag-resize one
        #    of its overhangs before applying; the captured sequence length must
        #    not snap the overhang back to its old size.
        applied_a_seq = _cv_sequence_for_live_overhang(d, a_id, v.overhang_a_seq)
        applied_b_seq = _cv_sequence_for_live_overhang(d, b_id, v.overhang_b_seq)
        if applied_a_seq:
            d = _build_overhang_patch(
                d, a_id, OverhangPatchRequest(sequence=applied_a_seq)
            )[0]
        if applied_b_seq:
            d = _build_overhang_patch(
                d, b_id, OverhangPatchRequest(sequence=applied_b_seq)
            )[0]

        # 2. Tear down EVERY materialized connection / binding that shares either
        #    overhang — an overhang can be in only one applied connection, so any
        #    prior one involving a_id or b_id (even with a third overhang) is
        #    unapplied here before the new one is created.
        def _involves(x):
            return a_id in (x.overhang_a_id, x.overhang_b_id) or b_id in (
                x.overhang_a_id,
                x.overhang_b_id,
            )

        for c in list(d.overhang_connections):
            if _involves(c):
                d = remove_linker_topology(
                    d.model_copy(
                        update={
                            "overhang_connections": [
                                x for x in d.overhang_connections if x.id != c.id
                            ]
                        }
                    ),
                    c.id,
                )
        # Bound direct bindings relocated the driven OH's domain — revert that
        # relocation (restore the driven helix + domain + crossovers) BEFORE dropping
        # the binding, else the relocated domain is orphaned on the driver helix.
        for bd in [b for b in d.overhang_bindings if _involves(b)]:
            if bd.bound and bd.prior_driven_topology:
                d = revert_bind_topology(d, bd.prior_driven_topology)
        d = d.model_copy(
            update={
                "overhang_bindings": [
                    b for b in d.overhang_bindings if not _involves(b)
                ]
            }
        )
        # 3. Create the version's connection type.
        report = None
        bridge_helix_ids: list[str] = []
        if direct:
            # BOTH root-to-root and end-to-root: one non-consuming bound binding,
            # relocated on apply (duplex forms now; B's embedded-strand bond left
            # stretched). The only per-type difference is the attach pair. (Replaces
            # the end-to-root binder splice that consumed B — removed 2026-06-30.)
            d = _cv_create_bound_binding(d, a_id, b_id, attach_a, attach_b, vtype)
        else:
            conn = OverhangConnection(
                overhang_a_id=a_id,
                overhang_a_attach=attach_a,
                overhang_b_id=b_id,
                overhang_b_attach=attach_b,
                linker_type=_cv_linker_type(vtype),
                length_value=0 if indirect else max(1, int(v.bridge_length or 1)),
                length_unit="bp",
                bridge_sequence=bridge_seq,
            )
            d = assign_overhang_connection_names(
                d.model_copy(
                    update={"overhang_connections": [*d.overhang_connections, conn]}
                )
            )
            d = generate_linker_topology(d, conn)
            bridge_helix_ids.append(f"__lnk__{conn.id}")
            report = MutationReport(new_helix_origins={f"__lnk__{conn.id}": None})
        # 3b. Auto-assign so the materialized connection's complement / binder
        #     domains (binds_overhang_id) carry real reverse-complement bases for
        #     simulation — no-op until the scaffold is sequenced. Targeted to the
        #     pair's own strands, their binders and any new __lnk__ bridge helix,
        #     so hand-typed sequences elsewhere in the design are left alone.
        from backend.core.sequences import (
            overhang_dependent_strand_ids,
            reassign_strands,
        )

        affected = overhang_dependent_strand_ids(
            d, [a_id, b_id], extra_helix_ids=bridge_helix_ids
        )
        d = reassign_strands(d, affected)
        # 4. Mark this version applied; clear `applied` on every version that
        #    shares either overhang (mirrors the topology teardown in step 2).
        d = d.model_copy(
            update={
                "connection_versions": [
                    ver.model_copy(
                        update={
                            "applied": ver.id == version_id,
                            **(
                                {"overhang_a_seq": applied_a_seq}
                                if ver.id == version_id and applied_a_seq
                                else {}
                            ),
                            **(
                                {"overhang_b_seq": applied_b_seq}
                                if ver.id == version_id and applied_b_seq
                                else {}
                            ),
                        }
                    )
                    if (ver.id == version_id or _involves(ver))
                    else ver
                    for ver in d.connection_versions
                ]
            }
        )
        return (d, report) if report else d

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Apply version {v.name or v.id[:8]} ({a_label}↔{b_label})",
        params={"version_id": version_id, "connection_type": vtype},
        fn=_fn,
    )
    return _design_response_with_geometry(updated, report)


@router.post("/design/overhang-bindings/{binding_id}/relax", status_code=200)
def relax_overhang_binding(binding_id: str) -> dict:
    """Settle a DIRECT binding's geometry — UNIFIED for root-to-root AND
    end-to-root (2026-06-30).

    A direct connection relocated the driven overhang's tip onto the driver's
    helix on apply, leaving the driven tip↔root backbone bond stretched across
    helices. This closes that bond to one backbone-bond length (~0.67 nm) by
    swinging the driver's overhang duplex about its root (persisted as the
    driver's OverhangSpec.rotation; the driven tip co-rotates) plus cluster
    kinematics (rotate the connecting joint(s), else rigid-translate the driven
    root cluster). Same rigid body → swing only. The binding stays bound — there
    is no longer an unbind/rebind dance.
    """
    from backend.core.direct_relax import relax_direct_binding
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    binding = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if binding is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    driver_oh_id = binding.driver_oh_id or binding.overhang_a_id
    driven_oh_id = binding.driven_oh_id or binding.overhang_b_id
    try:
        updated, info = relax_direct_binding(design, driver_oh_id, driven_oh_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, detail=f"relax_overhang_binding failed: {exc!r}")

    design_state.set_design(updated)
    report = validate_design(updated)
    payload = _design_response_with_geometry(updated, report)
    payload["relax_info"] = info
    return payload


@router.patch("/design/overhang-connections/{conn_id}/display-pose", status_code=200)
def patch_connection_display_pose(conn_id: str, body: BindingDisplayPoseBody) -> dict:
    """Authored display-only hinge angles for a LINKER (animation driver).

    Sets `unbound_angle_deg` / `bound_angle_deg` and auto-detects + stores
    `target_joint_id` (the single ClusterJoint connecting the two clusters the
    linker spans). Annotation-only — never modifies the linker topology, bridge,
    or any joint window; read solely by the display/animation layer.
    """
    from backend.core.linker_relax import _overhang_owning_cluster_id

    design = design_state.get_or_404()
    target = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    # Auto-detect the spanning joint: the single ClusterJoint whose cluster is
    # one of the two clusters the linker's overhangs belong to.
    auto_joint = target.target_joint_id
    if auto_joint is None:
        ca = _overhang_owning_cluster_id(design, target.overhang_a_id)
        cb = _overhang_owning_cluster_id(design, target.overhang_b_id)
        cands = [j for j in design.cluster_joints if j.cluster_id in (ca, cb)]
        if len(cands) == 1:
            auto_joint = cands[0].id

    def _fn(d: Design) -> None:
        c = next((cc for cc in d.overhang_connections if cc.id == conn_id), None)
        if c is None:
            return
        if "unbound_angle_deg" in patch:
            c.unbound_angle_deg = patch["unbound_angle_deg"]
        if "bound_angle_deg" in patch:
            c.bound_angle_deg = patch["bound_angle_deg"]
        if auto_joint is not None:
            c.target_joint_id = auto_joint

    updated, report = design_state.mutate_and_validate(_fn)
    return _design_response(updated, report)


@router.get("/ssdna-fjc-lookup", status_code=200)
def get_ssdna_fjc_lookup() -> dict:
    """Pre-computed ssDNA freely-jointed-chain lookup.

    Served as a static JSON snapshot of ``backend/data/ssdna_fjc_lookup.json``
    so the frontend can fetch the table once on init and render ss linker
    bridges in their natural FJC random-walk shape (instead of a smooth
    Bezier chord between anchors). Body shape: ``{metadata, entries}``;
    ``entries[str(n_bp)]`` holds ``positions`` (canonical: first bead at
    origin, last bead on +x axis at R_ee), ``r_ee_nm``, ``rg_achieved_nm``,
    etc. See ``backend/core/ssdna_fjc.py`` for accessor docs.
    """
    from backend.core import ssdna_fjc

    return ssdna_fjc.dump_all()


@router.get("/design/overhang-connections/{conn_id}/relax-status", status_code=200)
def get_overhang_connection_relax_status(conn_id: str) -> dict:
    """Lightweight DOF check used by the linker context menu so it can render
    "Relax Linker" enabled or grayed out without an optimization round-trip."""
    from backend.core.linker_relax import dof_topology

    design = design_state.get_or_404()
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")
    topo = dof_topology(design, conn)
    # Both ds and ss linkers can relax now (ds: chord → duplex visualLength;
    # ss: chord → mean R_ee from the FJC lookup table). The topology gate
    # (1-DOF or explicit multi-DOF) is the same for both.
    available = topo["status"] == "ok" and topo["n_dof"] == 1
    reason = topo["reason"]
    return {
        "available": available,
        "reason": reason,
        "n_dof": topo["n_dof"],
        "linker_type": conn.linker_type,
    }


class RelaxLinkerRequest(BaseModel):
    """Optional joint selection + ss-linker bin selection + kinematic limits.

    ``joint_ids``: omit (or send empty) for the 1-DOF auto-pick path;
    provide an explicit list for multi-DOF.

    ``bin_index``: ss linker only — which pre-baked FJC R_ee histogram bin
    to render. Values 0..hist_bins-1 (typically 0..39); the loader walks
    to the nearest occupied bin when empty. Omit to keep the connection's
    current ``bridge_bin_index``.

    ``r_ee_min_nm`` / ``r_ee_max_nm``: ss linker only — kinematic limits
    captured from the modal's range thumbs on the R_ee histogram. Stored
    on the connection for downstream simulation / animation use.
    """

    joint_ids: Optional[list[str]] = None
    bin_index: Optional[int] = None
    r_ee_min_nm: Optional[float] = None
    r_ee_max_nm: Optional[float] = None


@router.post("/design/overhang-connections/{conn_id}/relax", status_code=200)
def relax_overhang_connection(conn_id: str, body: RelaxLinkerRequest | None = None):
    """Optimize joint angles so the linker's connector arcs collapse.

    Requires a dsDNA linker. Two paths:

      1. ``body.joint_ids`` is None or empty → 1-DOF auto-pick: backend
         requires exactly one joint between the two overhangs' clusters.
      2. ``body.joint_ids`` is a non-empty list → multi-DOF: each joint's
         owning cluster rotates around its axis; angles optimized jointly.

    Each touched cluster gets a ClusterOpLogEntry so every angle change is
    undoable individually through the feature-log timeline.

    Response shape is the standard ``_design_replace_response`` picker, so
    typical relax operations (which only mutate cluster_transforms) take
    the lean ``cluster_only`` fast path — no full geometry recompute, no
    multi-MB JSON. ``relax_info`` always rides along.
    """
    from backend.core.linker_relax import (
        dof_topology,
        relax_linker,
        relax_ss_linker,
    )
    from backend.core.validator import validate_design

    trace = _TimingTrace()
    with trace.step("clone_prev"):
        design = design_state.get_or_404()
        prev = design.model_copy(deep=True)
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    selected = body.joint_ids if (body and body.joint_ids) else None

    if selected is None:
        with trace.step("dof_topology"):
            topo = dof_topology(design, conn)
        if topo["status"] != "ok" or topo["n_dof"] != 1:
            raise HTTPException(
                400, detail=topo["reason"] or "Relax requires exactly 1 DOF."
            )

    try:
        with trace.step("relax_linker"):
            if conn.linker_type == "ss":
                bin_index = body.bin_index if body is not None else None
                r_ee_min_nm = body.r_ee_min_nm if body is not None else None
                r_ee_max_nm = body.r_ee_max_nm if body is not None else None
                updated, info = relax_ss_linker(
                    design,
                    conn,
                    selected,
                    bin_index=bin_index,
                    r_ee_min_nm=r_ee_min_nm,
                    r_ee_max_nm=r_ee_max_nm,
                )
            else:
                updated, info = relax_linker(design, conn, selected)
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc))
    with trace.step("commit_state"):
        design_state.set_design(updated)
    with trace.step("validate"):
        report = validate_design(updated)
    with trace.step("response"):
        payload = _design_replace_response(prev, updated, report, trace=trace)
        payload["relax_info"] = info
    return trace.attach(ORJSONResponse(payload))


# ── Generic Relax Bond (any stretched backbone bond) ─────────────────────────
#
# One endpoint serves crossovers, forced ligations, linker connector arcs,
# and intra-strand cross-helix arcs. The caller identifies the bond by
# type + record id (for record-backed types) or by half-edge (the two
# nucleotide endpoints). Backend resolves to (anchor_a, anchor_b,
# cluster_a_id, cluster_b_id, target_nm) and delegates to
# ``backend.core.bond_relax.relax_bond``.


class RelaxBondEndpoint(BaseModel):
    """One end of a generic bond — a nucleotide's (helix, bp, direction)
    triple. ``strand_id`` is optional but used as a tiebreaker when the
    same slot is occupied by multiple strands (e.g. duplex regions).
    """

    helix_id: str
    bp_index: int
    direction: Literal["FORWARD", "REVERSE"]
    strand_id: Optional[str] = None


class RelaxBondRequest(BaseModel):
    """Request body for ``POST /design/relax-bond``.

    Identify the bond by EITHER a record id (``bond_id``, for record-backed
    types — crossover, ligation, linker_arc) OR by the two nucleotide
    endpoints (``side_a`` + ``side_b``). At least one of the two paths
    must resolve; the backend prefers the record path when both supplied.

    ``side_to_move`` is required when no joints connect the two endpoint
    clusters (0-DOF rigid translate); ignored for 1-DOF / N-DOF cases.

    ``joint_ids`` optionally pins which joints to optimise (intersected
    with the candidate set; subset must be on either endpoint's cluster).
    None / empty = auto-pick (all joints connecting the two clusters).

    ``target_nm`` overrides the type-default chord target (B-DNA backbone
    bond ~0.67 nm for crossovers and intra-strand arcs; 0 for ligations
    and the direct-binding pre-bind line; duplex/FJC for linker arcs).
    """

    bond_type: Literal["crossover", "ligation", "linker_arc", "strand_arc"]
    bond_id: Optional[str] = None
    linker_side: Optional[Literal["a", "b"]] = None
    side_a: Optional[RelaxBondEndpoint] = None
    side_b: Optional[RelaxBondEndpoint] = None
    side_to_move: Optional[Literal["a", "b"]] = None
    joint_ids: Optional[list[str]] = None
    target_nm: Optional[float] = None


# Type-default chord targets (overridable by request.target_nm).
_BOND_TYPE_DEFAULT_TARGET_NM: dict[str, float] = {
    "crossover": 0.13,  # tight nuc-to-nuc gap (was 0.67 = B-DNA backbone bond)
    "ligation": 0.0,  # the two endpoints should coincide
    "linker_arc": 0.67,  # bridge boundary → anchor gap
    "strand_arc": 0.67,  # generic cross-helix backbone bond
}


def _resolve_bond_anchor_from_endpoint(
    geometry: list[dict],
    endpoint: RelaxBondEndpoint,
) -> np.ndarray:
    """Look up the nucleotide at (helix, bp, direction) in *geometry* and
    return its backbone position. 422 if not found."""
    # Tighten match on strand_id only when the caller provided one (so the
    # request can ignore strand_id for inter-strand connections like
    # ligations across different strand_ids).
    match = None
    for n in geometry:
        if n.get("helix_id") != endpoint.helix_id:
            continue
        if n.get("bp_index") != endpoint.bp_index:
            continue
        if n.get("direction") != endpoint.direction:
            continue
        if endpoint.strand_id and n.get("strand_id") != endpoint.strand_id:
            continue
        match = n
        break
    if match is None:
        raise HTTPException(
            422,
            detail=(
                f"relax_bond: no nucleotide found at helix={endpoint.helix_id!r}, "
                f"bp={endpoint.bp_index}, direction={endpoint.direction}"
            ),
        )
    pos = match.get("backbone_position") or match.get("base_position")
    if pos is None:
        raise HTTPException(
            422, detail=("relax_bond: nucleotide has no backbone position.")
        )
    return np.asarray(pos, dtype=float)


def _cluster_id_for_helix(design: Design, helix_id: str) -> Optional[str]:
    """Return the (helix-level) cluster id containing *helix_id*. Falls back
    to None if the helix is orphaned (no cluster owns it)."""
    for ct in design.cluster_transforms:
        if helix_id in ct.helix_ids:
            return ct.id
    return None


def _cluster_pair_for_bond_relax(
    design: Design,
    helix_a: str,
    helix_b: str,
) -> tuple[Optional[str], Optional[str]]:
    """Pick a ``(cluster_a, cluster_b)`` pair such that the two ids DIFFER.

    ``_autodetect_clusters`` produces overlapping cluster sets (one scaffold
    cluster wrapping a whole scaffold + several geometry clusters covering
    rigid sub-bodies; bridge helices appear in both). A naive first-match
    lookup picks the scaffold cluster for both endpoints of any forced
    scaffold ligation, so the same-cluster guard fires and the relax submenu
    is silently dropped. Enumerating each helix's full cluster membership
    and returning the first pair with differing ids restores the relaxable
    geometry-cluster pairing whenever one exists.

    Falls back to the legacy first-match if no differing pair exists, so
    the downstream same-cluster guard still fires for genuinely intra-
    cluster bonds.
    """
    members_a = [ct.id for ct in design.cluster_transforms if helix_a in ct.helix_ids]
    members_b = [ct.id for ct in design.cluster_transforms if helix_b in ct.helix_ids]
    for a in members_a:
        for b in members_b:
            if a != b:
                return a, b
    return (
        members_a[0] if members_a else None,
        members_b[0] if members_b else None,
    )


def _resolve_relax_bond_request(
    design: Design,
    body: RelaxBondRequest,
    geometry: list[dict],
) -> tuple[np.ndarray, np.ndarray, str, str, float, str]:
    """Resolve (anchor_a, anchor_b, cluster_a, cluster_b, target_nm,
    source_tag) for a bond-relax request, dispatching on bond_type.

    Raises HTTPException(422) with a descriptive message on any failure.
    """
    target_nm = body.target_nm
    if target_nm is None:
        target_nm = _BOND_TYPE_DEFAULT_TARGET_NM[body.bond_type]
    source_tag = f"bond-relax:{body.bond_type}"

    # ── Record-backed types: prefer bond_id resolution ───────────────────
    if body.bond_type == "crossover" and body.bond_id:
        xo = next((x for x in design.crossovers if x.id == body.bond_id), None)
        if xo is None:
            raise HTTPException(404, detail=(f"crossover {body.bond_id!r} not found."))
        side_a = RelaxBondEndpoint(
            helix_id=xo.half_a.helix_id,
            bp_index=xo.half_a.index,
            direction=xo.half_a.strand.value,
        )
        side_b = RelaxBondEndpoint(
            helix_id=xo.half_b.helix_id,
            bp_index=xo.half_b.index,
            direction=xo.half_b.strand.value,
        )
    elif body.bond_type == "ligation" and body.bond_id:
        fl = next((f for f in design.forced_ligations if f.id == body.bond_id), None)
        if fl is None:
            raise HTTPException(
                404, detail=(f"forced ligation {body.bond_id!r} not found.")
            )
        side_a = RelaxBondEndpoint(
            helix_id=fl.three_prime_helix_id,
            bp_index=fl.three_prime_bp,
            direction=fl.three_prime_direction.value,
        )
        side_b = RelaxBondEndpoint(
            helix_id=fl.five_prime_helix_id,
            bp_index=fl.five_prime_bp,
            direction=fl.five_prime_direction.value,
        )
    elif body.bond_type == "linker_arc" and body.bond_id:
        # linker_arc identifies a SINGLE connector arc: (conn_id, side a|b).
        # Side "a" = OH-A anchor ↔ bridge boundary on the ``__lnk__/__a``
        # complement; side "b" symmetric for OH-B. We resolve to the two
        # nuc endpoints of that single arc.
        if body.linker_side not in ("a", "b"):
            raise HTTPException(
                422, detail=("relax_bond: linker_arc requires linker_side='a' or 'b'.")
            )
        conn = next(
            (c for c in design.overhang_connections if c.id == body.bond_id),
            None,
        )
        if conn is None:
            raise HTTPException(
                404, detail=(f"overhang connection {body.bond_id!r} not found.")
            )
        side_a, side_b = _resolve_linker_arc_endpoints(
            design, conn, body.linker_side, geometry
        )
    else:
        # Half-edge addressing.
        if body.side_a is None or body.side_b is None:
            raise HTTPException(
                422,
                detail=(
                    "relax_bond: must provide either bond_id (with linker_side "
                    "for linker_arc) or side_a + side_b half-edge endpoints."
                ),
            )
        side_a = body.side_a
        side_b = body.side_b

    anchor_a = _resolve_bond_anchor_from_endpoint(geometry, side_a)
    anchor_b = _resolve_bond_anchor_from_endpoint(geometry, side_b)

    cluster_a_id, cluster_b_id = _cluster_pair_for_bond_relax(
        design,
        side_a.helix_id,
        side_b.helix_id,
    )
    if cluster_a_id is None or cluster_b_id is None:
        raise HTTPException(
            422,
            detail=("relax_bond: one or both endpoint helices are not in a cluster."),
        )

    return anchor_a, anchor_b, cluster_a_id, cluster_b_id, target_nm, source_tag


def _resolve_linker_arc_endpoints(
    design: Design,
    conn,
    linker_side: str,
    geometry: list[dict],
) -> tuple[RelaxBondEndpoint, RelaxBondEndpoint]:
    """Return the two nuc endpoints of a single linker connector arc.

    Side "a": OH-A's attach anchor ↔ bridge boundary nuc on strand
    ``__lnk__<conn_id>__a`` (or ``__s`` for ss linkers).
    Side "b": OH-B's analog.

    Falls back to scanning geometry for the strand-id-matched bridge bp
    when the precise boundary identification isn't trivially derivable.
    """
    from backend.core.lattice import _find_overhang_domain

    oh = next(
        (
            o
            for o in design.overhangs
            if o.id
            == (conn.overhang_a_id if linker_side == "a" else conn.overhang_b_id)
        ),
        None,
    )
    if oh is None:
        raise HTTPException(
            422, detail=(f"relax_bond: linker_arc side {linker_side!r} OH not found.")
        )
    attach = conn.overhang_a_attach if linker_side == "a" else conn.overhang_b_attach
    oh_domain = _find_overhang_domain(design, oh.id)
    if oh_domain is None:
        raise HTTPException(
            422,
            detail=(
                f"relax_bond: linker_arc side {linker_side!r} OH domain not found."
            ),
        )
    # OH-end attach bp = the attach-side end of the OH's domain.
    if attach == "root":
        attach_bp = oh_domain.start_bp
    else:
        attach_bp = oh_domain.end_bp
    oh_endpoint = RelaxBondEndpoint(
        helix_id=oh_domain.helix_id,
        bp_index=attach_bp,
        direction=oh_domain.direction.value,
    )

    # Bridge-boundary endpoint: the first/last bp of the linker bridge
    # strand on the virtual ``__lnk__`` helix (or its ss equivalent).
    # We scan geometry for the bridge nuc whose strand_id matches the
    # linker strand for this side.
    suffix = "a" if linker_side == "a" else ("b" if conn.linker_type == "ds" else "s")
    bridge_strand_id = f"__lnk__{conn.id}__{suffix}"
    bridge_nucs = [
        n
        for n in geometry
        if n.get("strand_id") == bridge_strand_id
        and n.get("helix_id", "").startswith(f"__lnk__{conn.id}")
    ]
    if not bridge_nucs:
        raise HTTPException(
            422,
            detail=(
                f"relax_bond: no bridge nucleotides found for linker "
                f"{conn.id!r} side {linker_side!r}."
            ),
        )
    # Side "a" arc reaches the bridge bp closest to side A — the lowest bp
    # on a ds bridge with comp-first-a (linker strand traverses
    # [complement_a, bridge_forward]). The opposite side is bp L-1. Pick
    # by linker_side: a → min bp, b → max bp.
    bridge_nucs.sort(key=lambda n: n.get("bp_index", 0))
    bridge_nuc = bridge_nucs[0] if linker_side == "a" else bridge_nucs[-1]
    bridge_endpoint = RelaxBondEndpoint(
        helix_id=bridge_nuc["helix_id"],
        bp_index=bridge_nuc["bp_index"],
        direction=bridge_nuc.get("direction", "FORWARD"),
    )
    return oh_endpoint, bridge_endpoint


@router.post("/design/relax-bond", status_code=200)
def relax_bond_endpoint(body: RelaxBondRequest) -> dict:
    """Generic relax for any stretched backbone bond.

    Resolves the bond's two endpoints + their owning clusters, then runs:

      * 0-DOF (no joints between clusters): rigidly translate the cluster
        named by ``side_to_move`` so its anchor closes onto the fixed side.
      * 1-DOF (one joint): rotate the joint's owning cluster.
      * N-DOF (multiple joints): Powell over all qualifying joints
        (intersected with ``joint_ids`` if provided).

    Same-cluster bonds are refused (422) — no relaxation is possible.
    """
    from backend.core.bond_relax import relax_bond as core_relax_bond
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    prev = design.model_copy(deep=True)

    geometry = _geometry_for_design(design)
    (anchor_a, anchor_b, cluster_a_id, cluster_b_id, target_nm, source_tag) = (
        _resolve_relax_bond_request(design, body, geometry)
    )

    try:
        updated, info = core_relax_bond(
            design,
            anchor_a=anchor_a,
            anchor_b=anchor_b,
            cluster_a_id=cluster_a_id,
            cluster_b_id=cluster_b_id,
            target_nm=target_nm,
            side_to_move=body.side_to_move,
            joint_ids=body.joint_ids,
            source_tag=source_tag,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, detail=f"relax_bond failed: {exc!r}")

    design_state.set_design(updated)

    report = validate_design(updated)
    payload = _design_replace_response(prev, updated, report)
    payload["relax_info"] = info
    return payload


# ── OverhangBinding endpoints (Phase 5) ─────────────────────────────────────
#
# Bindings record a Watson-Crick sub-domain↔sub-domain pairing. Flipping a
# binding's `bound` flag locks the connecting ClusterJoint to the duplex-
# satisfying angle until the binding is released. See `OverhangBinding` in
# backend/core/models.py for the data model, and `backend.core.binding_relax`
# for the locked-angle computation.


def _select_driver_for_joint(
    design: Design, joint_id: str
) -> Optional[OverhangBinding]:
    """Return the bound binding currently driving *joint_id*.

    Driver selection: latest ``created_at`` among bound bindings targeting
    this joint. Tiebreak: lexicographic id.
    """
    candidates = [
        b for b in design.overhang_bindings if b.bound and b.target_joint_id == joint_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b.created_at, b.id))
    return candidates[-1]


def _first_claimant_for_joint(
    design: Design, joint_id: str
) -> Optional[OverhangBinding]:
    """Return the earliest-created binding (bound OR unbound) targeting *joint_id*.

    Used to locate the snapshot of the joint's pre-binding angle window so
    the window can be restored when the last bound claimant releases.
    """
    candidates = [b for b in design.overhang_bindings if b.target_joint_id == joint_id]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b.created_at, b.id))
    return candidates[0]


def _apply_driver_to_joint(design: Design, joint_id: str) -> Design:
    """When a driver exists, freeze the joint at the driver's locked angle.
    When no driver exists, restore the window from the first claimant's snapshot.

    Returns a new ``Design`` with the joint's min/max angles updated. Pure
    function — caller is responsible for committing via mutate_with_feature_log
    or its underlying primitive.
    """
    driver = _select_driver_for_joint(design, joint_id)
    new_joints = []
    for j in design.cluster_joints:
        if j.id != joint_id:
            new_joints.append(j)
            continue
        if driver is not None and driver.locked_angle_deg is not None:
            new_joints.append(
                j.model_copy(
                    update={
                        "min_angle_deg": driver.locked_angle_deg,
                        "max_angle_deg": driver.locked_angle_deg,
                    }
                )
            )
        else:
            # No driver — restore prior window if first claimant snapshotted it.
            first = _first_claimant_for_joint(design, joint_id)
            if (
                first is not None
                and first.prior_min_angle_deg is not None
                and first.prior_max_angle_deg is not None
            ):
                new_joints.append(
                    j.model_copy(
                        update={
                            "min_angle_deg": first.prior_min_angle_deg,
                            "max_angle_deg": first.prior_max_angle_deg,
                        }
                    )
                )
            else:
                # Nothing to restore; leave as-is.
                new_joints.append(j)
    return design.model_copy(update={"cluster_joints": new_joints})


def _binding_response(
    design: Design, report: ValidationReport, binding_id: Optional[str] = None
) -> dict:
    """Standard envelope: full design response, optionally including the
    affected binding by id for client convenience."""
    base = _design_response_with_geometry(design, report)
    if binding_id is not None:
        b = next((bb for bb in design.overhang_bindings if bb.id == binding_id), None)
        if b is not None:
            base["overhang_binding"] = b.model_dump()
    return base


@router.get("/design/overhang-bindings", status_code=200)
def list_overhang_bindings() -> dict:
    """List all OverhangBinding records on the active design."""
    design = design_state.get_or_404()
    return {"overhang_bindings": [b.model_dump() for b in design.overhang_bindings]}


class OverhangBindingCreateRequest(BaseModel):
    sub_domain_a_id: str
    sub_domain_b_id: str
    binding_mode: Literal["duplex", "toehold"] = "duplex"
    target_joint_id: Optional[str] = None
    allow_n_wildcard: bool = True


def _resolve_sd_for_binding(
    design: Design,
    sub_domain_id: str,
) -> tuple[Optional["OverhangSpec"], Optional["SubDomain"]]:
    for ovhg in design.overhangs:
        for sd in ovhg.sub_domains:
            if sd.id == sub_domain_id:
                return ovhg, sd
    return None, None


def _binding_pair_keys(design: Design) -> set[frozenset]:
    """Build the mutex pair-set for linkers + existing bindings."""
    from backend.core.models import _sub_domain_at_attach

    keys: set[frozenset] = set()
    for conn in design.overhang_connections:
        a = _sub_domain_at_attach(design, conn.overhang_a_id, conn.overhang_a_attach)
        b = _sub_domain_at_attach(design, conn.overhang_b_id, conn.overhang_b_attach)
        if a and b and a != b:
            keys.add(frozenset({a, b}))
    for binding in design.overhang_bindings:
        keys.add(frozenset({binding.sub_domain_a_id, binding.sub_domain_b_id}))
    return keys


def _smallest_unused_binding_name(design: Design) -> str:
    used = {b.name for b in design.overhang_bindings if b.name}
    n = 1
    while f"B{n}" in used:
        n += 1
    return f"B{n}"


@router.post("/design/overhang-bindings", status_code=201)
def create_overhang_binding(body: OverhangBindingCreateRequest) -> dict:
    """Create a new OverhangBinding. Starts unbound."""
    import time as _time
    from backend.core.models import OverhangBinding as _OB
    from backend.core.sequences import is_watson_crick_complement as _is_wc

    design = design_state.get_or_404()

    if body.sub_domain_a_id == body.sub_domain_b_id:
        raise HTTPException(
            422, detail="sub_domain_a_id and sub_domain_b_id must differ."
        )

    ovhg_a, sd_a = _resolve_sd_for_binding(design, body.sub_domain_a_id)
    ovhg_b, sd_b = _resolve_sd_for_binding(design, body.sub_domain_b_id)
    if ovhg_a is None or sd_a is None:
        raise HTTPException(
            404, detail=f"sub_domain_a_id {body.sub_domain_a_id!r} not found."
        )
    if ovhg_b is None or sd_b is None:
        raise HTTPException(
            404, detail=f"sub_domain_b_id {body.sub_domain_b_id!r} not found."
        )

    if sd_a.length_bp != sd_b.length_bp:
        raise HTTPException(
            422,
            detail=(
                f"sub-domain lengths must match ({sd_a.length_bp} vs {sd_b.length_bp})."
            ),
        )

    seq_a = _resolve_sub_domain_sequence(ovhg_a, sd_a)
    seq_b = _resolve_sub_domain_sequence(ovhg_b, sd_b)
    if seq_a is None or seq_b is None:
        raise HTTPException(
            422,
            detail=(
                "Both sub-domain sequences must be resolvable (override or parent slice) "
                "before a binding can be created."
            ),
        )
    if not _is_wc(seq_a, seq_b, allow_n=body.allow_n_wildcard):
        raise HTTPException(
            422,
            detail=(
                f"sequences are not Watson-Crick complementary "
                f"(allow_n_wildcard={body.allow_n_wildcard})."
            ),
        )

    pair_key = frozenset({body.sub_domain_a_id, body.sub_domain_b_id})
    if pair_key in _binding_pair_keys(design):
        raise HTTPException(
            409,
            detail=("sub-domain pair is already claimed by another linker or binding."),
        )

    if body.target_joint_id is not None:
        joint_ids = {j.id for j in design.cluster_joints}
        if body.target_joint_id not in joint_ids:
            raise HTTPException(
                404, detail=(f"target_joint_id {body.target_joint_id!r} not found.")
            )

    binding = _OB(
        name=_smallest_unused_binding_name(design),
        created_at=_time.time(),
        sub_domain_a_id=body.sub_domain_a_id,
        sub_domain_b_id=body.sub_domain_b_id,
        overhang_a_id=ovhg_a.id,
        overhang_b_id=ovhg_b.id,
        binding_mode=body.binding_mode,
        target_joint_id=body.target_joint_id,
        allow_n_wildcard=body.allow_n_wildcard,
        bound=False,
    )

    def _fn(d: Design) -> Design:
        return d.model_copy(
            update={
                "overhang_bindings": [*d.overhang_bindings, binding],
            }
        )

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Create binding {binding.name}",
        params={
            "binding_id": binding.id,
            "name": binding.name,
            "sub_domain_a_id": binding.sub_domain_a_id,
            "sub_domain_b_id": binding.sub_domain_b_id,
            "binding_mode": binding.binding_mode,
            "action": "overhang-binding-create",
        },
        fn=_fn,
    )
    response = _binding_response(updated, report, binding_id=binding.id)
    # 201 Created — return the response payload with the new binding embedded.
    return response


class OverhangBindingPatchRequest(BaseModel):
    name: Optional[str] = None
    bound: Optional[bool] = None
    binding_mode: Optional[Literal["duplex", "toehold"]] = None
    target_joint_id: Optional[str] = None
    allow_n_wildcard: Optional[bool] = None


@router.patch("/design/overhang-bindings/{binding_id}", status_code=200)
def patch_overhang_binding(binding_id: str, body: OverhangBindingPatchRequest) -> dict:
    """Update fields on an OverhangBinding.

    `bound` transitions trigger driver-selection / joint-window updates:

      • False → True: resolve target_joint_id (explicit or auto-detect via
        relax solver), compute locked_angle_deg, snapshot prior_min/max on
        the first claimant (if not already), apply driver to joint.
      • True → False: clear bound; re-select driver; if no driver remains,
        restore prior window from the first claimant snapshot AND clear it.
      • bound=True idempotent re-toggle: no double-snapshot, no
        double-apply.

    A target_joint_id change while bound = release old joint, claim new.
    """
    from backend.core.binding_relax import (
        BindTopology,
        apply_bind_topology,
        compute_bind_topology,
        revert_bind_topology,
    )

    design = design_state.get_or_404()
    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    if "name" in patch:
        new_name = (patch["name"] or "").strip()
        if not new_name:
            raise HTTPException(422, detail="name must be non-empty.")
        clash = next(
            (
                b
                for b in design.overhang_bindings
                if b.id != binding_id and b.name == new_name
            ),
            None,
        )
        if clash is not None:
            raise HTTPException(
                422, detail=f"binding name {new_name!r} is already in use."
            )
        patch["name"] = new_name

    if "target_joint_id" in patch and patch["target_joint_id"] is not None:
        joint_ids = {j.id for j in design.cluster_joints}
        if patch["target_joint_id"] not in joint_ids:
            raise HTTPException(
                404, detail=(f"target_joint_id {patch['target_joint_id']!r} not found.")
            )

    # Compute next binding state pieces. We resolve transitions explicitly
    # so all topology + joint mutations sit inside one mutate_with_feature_log atomic.
    prev_bound = target.bound
    prev_joint = target.target_joint_id
    next_joint = (
        patch.get("target_joint_id", prev_joint)
        if "target_joint_id" in patch
        else prev_joint
    )
    next_bound = patch.get("bound", prev_bound) if "bound" in patch else prev_bound

    # Topology change on bind / restore on unbind.
    #   topology: BindTopology | None — computed when we're entering bound state.
    #   restore_snapshot: dict | None — pre-bind topology snapshot to revert on unbind.
    topology: Optional[BindTopology] = None
    restore_snapshot: Optional[Dict[str, Any]] = None

    if next_bound and not prev_bound:
        # Going UNBOUND -> BOUND. compute_bind_topology snapshots the pre-bind
        # state; apply_bind_topology in _fn does the relocation. After the
        # relocation, the OH→parent crossover spans clusters and is what
        # visually matters — we run a bond-relax inside _fn (post-apply) to
        # rotate the joint's cluster so that crossover chord ≈ 0.67 nm, then
        # lock the joint at the resulting angle.
        # For a UNIFIED direct binding (created via apply_connection_version /
        # _cv_create_bound_binding) the driver/driven sides are already pinned on
        # the record. Pass driver_side so re-bind is a pure topology relocation —
        # this bypasses the same-cluster / cluster-None guards, which a root-to-root
        # binding on ONE rigid body would otherwise trip (422) on the second Bind.
        # Legacy pair bindings have driver_oh_id=None → driver_side stays None →
        # the guards still apply (unchanged behaviour).
        driver_side = None
        if target.driver_oh_id is not None:
            driver_side = "a" if target.driver_oh_id == target.overhang_a_id else "b"
        try:
            topology = compute_bind_topology(design, target, driver_side=driver_side)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, detail=f"compute_bind_topology failed: {exc!r}")
        # Snapshot for unbind restoration.
        patch["prior_driven_topology"] = topology.snapshot
        # Resolve the auto-pick joint id (when exactly one joint connects
        # the two clusters and the user didn't pin target_joint_id).
        if next_joint is None:
            from backend.core.linker_relax import _overhang_owning_cluster_id as _own

            cluster_a = _own(design, target.overhang_a_id)
            cluster_b = _own(design, target.overhang_b_id)
            cands = [
                j
                for j in design.cluster_joints
                if j.cluster_id == cluster_a or j.cluster_id == cluster_b
            ]
            if len(cands) == 1:
                next_joint = cands[0].id
                patch["target_joint_id"] = next_joint
        # locked_angle_deg is computed post-relocation inside _fn (see below).
        # Leave it None here; _fn writes the real value before _apply_driver_to_joint
        # reads it.
        patch["locked_angle_deg"] = None
        patch["bound"] = True
    elif prev_bound and not next_bound:
        # Going BOUND -> UNBOUND: clear locked_angle_deg + plan to restore
        # the topology snapshot taken at bind time (if any).
        patch["locked_angle_deg"] = None
        patch["bound"] = False
        restore_snapshot = target.prior_driven_topology
        patch["prior_driven_topology"] = None

    updated_target = target.model_copy(
        update={k: v for k, v in patch.items() if k in OverhangBinding.model_fields}
    )

    def _fn(d: Design) -> Design:
        # Replace the target binding in the list.
        new_bindings_list = []
        # Walk current bindings, swapping in updated_target.
        for b in d.overhang_bindings:
            if b.id == binding_id:
                new_bindings_list.append(updated_target)
            else:
                new_bindings_list.append(b)
        nxt = d.model_copy(update={"overhang_bindings": new_bindings_list})

        # ── Topology relocation (UNBOUND -> BOUND) or revert (BOUND -> UNBOUND).
        # The driven OH's strand domain moves onto the driver's helix at the
        # driver's bp range, antiparallel; driven helix is deleted. Unbind
        # restores the driven helix + the OH's domain from the snapshot.
        if topology is not None:
            nxt = apply_bind_topology(nxt, topology)
        elif restore_snapshot:
            nxt = revert_bind_topology(nxt, restore_snapshot)

        # NB: no automatic post-bind cluster relax. Binding does topology
        # relocation ONLY; the cross-cluster OH→parent crossover may end
        # up visibly stretched and the user closes it themselves via the
        # right-click "Relax bond" menu. (Earlier iterations auto-rotated
        # the joint on bind; reverted at user request 2026-05-14 so the
        # visual stretch is preserved as a kinematic-intent marker.)
        #
        # locked_angle_deg is therefore left None for Phase-6 bindings
        # unless an external caller provides it. _apply_driver_to_joint
        # below will not collapse the joint window when locked_angle_deg
        # is None (it only acts on the binding designated as joint
        # driver via locked_angle_deg).

        # ── Snapshot prior_min/max on first claimant if this is the first
        #    bound binding for next_joint and the snapshot hasn't been taken.
        if next_bound and next_joint is not None and not prev_bound:
            first = _first_claimant_for_joint(nxt, next_joint)
            # The first claimant might be this binding (often is). Snapshot
            # the joint's current min/max ONLY IF the first claimant has
            # no snapshot yet (idempotent re-toggle safe).
            if first is not None and first.prior_min_angle_deg is None:
                joint = next(
                    (j for j in nxt.cluster_joints if j.id == next_joint), None
                )
                if joint is not None:
                    new_first = first.model_copy(
                        update={
                            "prior_min_angle_deg": joint.min_angle_deg,
                            "prior_max_angle_deg": joint.max_angle_deg,
                        }
                    )
                    nxt = nxt.model_copy(
                        update={
                            "overhang_bindings": [
                                new_first if bb.id == first.id else bb
                                for bb in nxt.overhang_bindings
                            ],
                        }
                    )

        # ── Apply driver to affected joint(s). For 1-DOF bindings, this
        # collapses the joint window to [locked_angle, locked_angle].
        joints_to_recompute: set[str] = set()
        if prev_joint is not None:
            joints_to_recompute.add(prev_joint)
        if next_joint is not None:
            joints_to_recompute.add(next_joint)
        for jid in joints_to_recompute:
            nxt = _apply_driver_to_joint(nxt, jid)
            # If no driver left after release, clear the snapshot on the
            # first claimant (so a future re-binding picks up a fresh
            # snapshot from the restored window).
            if _select_driver_for_joint(nxt, jid) is None:
                first = _first_claimant_for_joint(nxt, jid)
                if first is not None and first.prior_min_angle_deg is not None:
                    new_first = first.model_copy(
                        update={
                            "prior_min_angle_deg": None,
                            "prior_max_angle_deg": None,
                        }
                    )
                    nxt = nxt.model_copy(
                        update={
                            "overhang_bindings": [
                                new_first if bb.id == first.id else bb
                                for bb in nxt.overhang_bindings
                            ],
                        }
                    )
        return nxt

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Patch binding {target.name}",
        params={
            "binding_id": binding_id,
            "fields": sorted(patch.keys()),
            "action": "overhang-binding-patch",
        },
        fn=_fn,
    )
    return _binding_response(updated, report, binding_id=binding_id)


def reapply_binding_driver(design: Design, binding_id: str) -> Design:
    """Re-place a BOUND binding's relocation after its driver changed (the duplex
    driver toggle, Phase 4b #4/#1–#3). Mechanically = unbind then re-bind with the
    binding's CURRENT ``driver_oh_id``, reusing the PROVEN bind primitives
    (``revert_bind_topology`` → ``compute_bind_topology(driver_side=…)`` →
    ``apply_bind_topology``) so the ENTIRE driven domain relocates onto the new
    driver's helix (Q4 #1). No-op when the binding isn't bound or has no snapshot.
    Best-effort: on any failure the design is returned unchanged so the driver
    field edit still sticks (the user can Unbind→Bind manually)."""
    from backend.core.binding_relax import (
        apply_bind_topology,
        compute_bind_topology,
        revert_bind_topology,
    )

    b = next((x for x in design.overhang_bindings if x.id == binding_id), None)
    if b is None or not b.bound or not b.prior_driven_topology:
        return design
    driver_side = "a" if b.driver_oh_id == b.overhang_a_id else "b"
    try:
        reverted = revert_bind_topology(design, b.prior_driven_topology)
        b2 = next((x for x in reverted.overhang_bindings if x.id == binding_id), None)
        topo = compute_bind_topology(reverted, b2, driver_side=driver_side)
        applied = apply_bind_topology(reverted, topo)
        out = applied.model_copy(
            update={
                "overhang_bindings": [
                    x.model_copy(update={"prior_driven_topology": topo.snapshot})
                    if x.id == binding_id
                    else x
                    for x in applied.overhang_bindings
                ]
            }
        )
        if b.target_joint_id:
            out = _apply_driver_to_joint(out, b.target_joint_id)
        return out
    except Exception:
        return design


@router.patch("/design/overhang-bindings/{binding_id}/display-pose", status_code=200)
def patch_binding_display_pose(binding_id: str, body: BindingDisplayPoseBody) -> dict:
    """Set the authored display-only hinge angles used by the animation player.

    Annotation-only: writes ONLY `unbound_angle_deg` / `bound_angle_deg`. Never
    touches `bound`, `target_joint_id`, `locked_angle_deg`, the joint's angle
    window, or `prior_driven_topology`. Does not relocate topology. Three-layer
    safe — these fields are read solely by the display/animation layer.
    """
    design = design_state.get_or_404()
    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    def _fn(d: Design) -> None:
        b = next((bb for bb in d.overhang_bindings if bb.id == binding_id), None)
        if b is None:
            return
        if "unbound_angle_deg" in patch:
            b.unbound_angle_deg = patch["unbound_angle_deg"]
        if "bound_angle_deg" in patch:
            b.bound_angle_deg = patch["bound_angle_deg"]

    updated, report = design_state.mutate_and_validate(_fn)
    return _binding_response(updated, report, binding_id=binding_id)


class StrandAnimSetupBody(BaseModel):
    """Display-only "Strand Animation" setup for one overhang+binder pair.

    `setup` is the full param dict captured from the right-sidebar panel (or null
    to clear). Annotation-only — never read by topology/relax/geometry; consumed
    solely by the animation player's rich un/hybridization driver.
    """

    setup: Optional[dict] = None


@router.patch("/design/overhangs/{overhang_id}/strand-anim-setup", status_code=200)
def patch_overhang_strand_anim_setup(
    overhang_id: str, body: StrandAnimSetupBody
) -> dict:
    """Set (or clear) the display-only strand-animation setup for an overhang.

    Writes ONLY `OverhangSpec.strand_anim_setup`. Three-layer safe — the field is
    read solely by the display/animation layer. Mirrors `patch_binding_display_pose`.
    """
    design = design_state.get_or_404()
    if not any(o.id == overhang_id for o in design.overhangs):
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")

    def _fn(d: Design) -> None:
        o = next((oo for oo in d.overhangs if oo.id == overhang_id), None)
        if o is not None:
            o.strand_anim_setup = body.setup

    updated, report = design_state.mutate_and_validate(_fn)
    return _design_response(updated, report)


@router.delete("/design/overhang-bindings/{binding_id}", status_code=200)
def delete_overhang_binding(binding_id: str) -> dict:
    """Remove an OverhangBinding.

    If the binding being deleted is the first claimant for a joint AND other
    bindings still claim that joint, the prior_min/max snapshot is migrated
    onto the next-earliest claimant before deletion so the restore path
    keeps working when the last bound binding eventually releases.
    """
    design = design_state.get_or_404()
    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    joint_id = target.target_joint_id
    must_migrate_snapshot = (
        joint_id is not None
        and target.prior_min_angle_deg is not None
        and target.prior_max_angle_deg is not None
    )

    # Snapshot the joint window to restore when no heir exists.
    fallback_min = target.prior_min_angle_deg
    fallback_max = target.prior_max_angle_deg

    def _fn(d: Design) -> Design:
        bindings = list(d.overhang_bindings)
        # Identify next claimant BEFORE removing target.
        heir_migrated = False
        if must_migrate_snapshot:
            others = [
                b
                for b in bindings
                if b.target_joint_id == joint_id and b.id != binding_id
            ]
            others.sort(key=lambda b: (b.created_at, b.id))
            if others:
                heir = others[0]
                # Migrate snapshot onto heir (only if heir has no snapshot yet).
                if (
                    heir.prior_min_angle_deg is None
                    and heir.prior_max_angle_deg is None
                ):
                    new_heir = heir.model_copy(
                        update={
                            "prior_min_angle_deg": target.prior_min_angle_deg,
                            "prior_max_angle_deg": target.prior_max_angle_deg,
                        }
                    )
                    bindings = [new_heir if b.id == heir.id else b for b in bindings]
                    heir_migrated = True
        # Remove target.
        bindings = [b for b in bindings if b.id != binding_id]
        nxt = d.model_copy(update={"overhang_bindings": bindings})
        # Re-apply driver to joint (may restore from heir's migrated snapshot).
        if joint_id is not None:
            nxt = _apply_driver_to_joint(nxt, joint_id)
            # Final fallback: no heir AND target carried a snapshot ⇒ the
            # joint was bound until just now and has no surviving claimant
            # to restore from. Apply the stored fallback window directly so
            # the joint un-locks.
            if (
                not heir_migrated
                and fallback_min is not None
                and fallback_max is not None
            ):
                # Check whether driver-apply already restored (it would only
                # do so if a remaining claimant carried a snapshot — i.e.,
                # heir_migrated case).
                driver_after = _select_driver_for_joint(nxt, joint_id)
                if driver_after is None:
                    new_joints = []
                    for j in nxt.cluster_joints:
                        if j.id == joint_id:
                            new_joints.append(
                                j.model_copy(
                                    update={
                                        "min_angle_deg": fallback_min,
                                        "max_angle_deg": fallback_max,
                                    }
                                )
                            )
                        else:
                            new_joints.append(j)
                    nxt = nxt.model_copy(update={"cluster_joints": new_joints})
        return nxt

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="overhang-bulk",
        label=f"Delete binding {target.name}",
        params={
            "binding_id": binding_id,
            "name": target.name,
            "action": "overhang-binding-delete",
        },
        fn=_fn,
    )
    return _design_response_with_geometry(updated, report)


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


def _reconcile_cluster_joints_between(
    design: "Design", from_design: "Design", to_design: "Design"
) -> "Design":
    """Migrate ``design.cluster_joints`` from reflecting ``from_design``'s joints
    to reflecting ``to_design``'s joints, and return the updated design.

    ``_seek_feature_log`` does NOT replay cluster_joints (joints are mutated only
    by minor ops nested inside routing-clusters), so whenever a routing-cluster's
    children change we have to fix up the live joints by hand. The live joints
    currently equal ``from_design``'s set; we want ``to_design``'s set:
      - joints in ``from`` but not ``to`` were removed → drop them
      - joints in ``to`` but not ``from`` were (re)added → append them
      - joints present in both but differing → take ``to``'s value
    Returns ``design`` unchanged when there is no joint delta.
    """
    frm = {j.id: j for j in from_design.cluster_joints}
    to = {j.id: j for j in to_design.cluster_joints}
    drop = frm.keys() - to.keys()
    add = to.keys() - frm.keys()
    changed = {jid for jid in frm.keys() & to.keys() if frm[jid] != to[jid]}
    if not (drop or add or changed):
        return design
    new_joints = []
    seen: set = set()
    for j in design.cluster_joints:
        if j.id in drop:
            continue
        new_joints.append(to[j.id] if j.id in changed else j)
        seen.add(j.id)
    for jid in add:
        if jid not in seen:
            new_joints.append(to[jid])
            seen.add(jid)
    return design.copy_with(cluster_joints=new_joints)


def _state_at_child_boundary(entry, k: int) -> "Design":
    """Return the design state AFTER ``entry.children[0..k-1]`` of a Fine Routing
    cluster (``k == 0`` → the cluster's pre-state).

    Decodes ``pre_state`` then, for each of the first ``k`` children, applies its
    recorded topology diff forward (works for ANY op type) — or falls back to
    ``_replay_minor_op`` for legacy children with no diff. Raises HTTP 410 if the
    pre-state is evicted/missing, HTTP 422 if a legacy child's op can't be
    replayed.

    Non-defensive: the prefix 0..k-1 is internally consistent. NEVER
    re-reconciles — diffs already include reconcile + ligation-retry effects
    (captured post-reconcile in ``mutate_with_minor_log``).
    """
    from backend.core.design_diff import apply_child_diff_forward, is_diff_child

    if entry.evicted or not entry.pre_state_gz_b64:
        raise HTTPException(
            410,
            detail="Fine Routing cluster snapshot was evicted to save space and can no "
            "longer be edited per sub-step.",
        )
    try:
        state = design_state.decode_design_snapshot(entry.pre_state_gz_b64)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(500, detail=f"Failed to decode Fine Routing pre-state: {e}")

    for child in entry.children[:k]:
        if is_diff_child(child):
            state, _w = apply_child_diff_forward(
                state,
                child.diff_added_b64,
                child.diff_removed_b64,
                child.diff_modified_b64,
            )
        else:
            try:
                state = _replay_minor_op(state, child.op_subtype, child.params)
            except NotImplementedError:
                raise HTTPException(
                    422,
                    detail="Cannot reconstruct this sub-step: an earlier sub-step predates "
                    "per-step history and uses an operation that can't be replayed. "
                    "Revert or delete the whole Fine Routing cluster instead.",
                )
    return state


def _n_failures(report) -> int:
    """Count failed validation results in a ValidationReport."""
    return sum(1 for r in report.results if not r.ok)


def _delete_routing_child(
    design: "Design", log: list, index: int, entry, child_index: int
) -> dict:
    """Surgically remove ``entry.children[child_index]`` from the Fine Routing
    cluster at log ``index``, keeping every other sub-step and all later log
    entries. Deleting the only remaining sub-step removes the whole cluster and
    restores the pre-cluster topology. Pushes to the undo stack.

    Diff-based: reconstruct the boundary just before the deleted child, then
    forward-apply the surviving tail (children j+1..) DEFENSIVELY — the deleted
    step's dependents may dangle. Best-effort: if the tail can't be cleanly
    reapplied OR validation regresses, a warning rides back on the response
    (``placement_warnings``); the user can Ctrl-Z.

    Caller guarantees ``entry`` is a routing-cluster and ``child_index`` is in
    range.
    """
    from backend.core.design_diff import apply_child_diff_forward, is_diff_child
    from backend.core.validator import validate_design

    if entry.evicted or not entry.pre_state_gz_b64:
        raise HTTPException(
            410,
            detail=f"Fine Routing cluster {index} was evicted to save space; its "
            "sub-steps can no longer be edited individually.",
        )

    # State just before the deleted child (children 0..j-1 applied).
    rebuilt = _state_at_child_boundary(entry, child_index)

    # Forward-apply the surviving tail (children j+1..n-1) defensively onto it.
    warnings: list[str] = []
    for child in entry.children[child_index + 1 :]:
        if is_diff_child(child):
            rebuilt, w = apply_child_diff_forward(
                rebuilt,
                child.diff_added_b64,
                child.diff_removed_b64,
                child.diff_modified_b64,
                defensive=True,
            )
            warnings += w
        else:
            try:
                rebuilt = _replay_minor_op(rebuilt, child.op_subtype, child.params)
            except NotImplementedError:
                raise HTTPException(
                    422,
                    detail="Cannot delete this sub-step: a later sub-step predates per-step "
                    "history and uses an operation that can't be replayed. Delete the "
                    "whole Fine Routing cluster instead.",
                )

    new_children = list(entry.children[:child_index]) + list(
        entry.children[child_index + 1 :]
    )

    if new_children:
        # Cluster survives: re-encode its post-state and leave it in the log so
        # _seek_feature_log uses it as the topology anchor. Top-level count
        # unchanged → top-level cursor unchanged. Surviving children keep their
        # stored diffs (a future boundary rebuild re-runs the same logic).
        new_post_b64, new_post_size = design_state.encode_design_snapshot(rebuilt)
        new_cluster = entry.model_copy(
            update={
                "children": new_children,
                "post_state_gz_b64": new_post_b64,
                "post_state_size_bytes": new_post_size,
            }
        )
        new_log = [new_cluster if e.id == entry.id else e for e in log]
        new_cursor = design.feature_log_cursor
        temp = design.copy_with(feature_log=new_log)
    else:
        # Last sub-step removed → drop the whole cluster. With the cluster (its
        # topology anchor) gone, _seek_snapshot_base has nothing to roll back
        # to, so substitute the pre-cluster topology onto the live design before
        # seeking later deltas/snapshots on top.
        new_log = [e for e in log if e.id != entry.id]
        cursor = design.feature_log_cursor
        if cursor == -2 or cursor < index:
            new_cursor = cursor
        elif cursor == -1:
            new_cursor = -1
        elif cursor == 0:
            new_cursor = -2
        else:
            new_cursor = cursor - 1
        temp = design.copy_with(feature_log=new_log)
        temp = _topology_substitute(temp, rebuilt)

    # Diffs already carry the joint delta; keep the legacy joint migration as an
    # idempotent safety net (a no-op when joints already match `rebuilt`).
    if entry.post_state_gz_b64:
        try:
            old_post = design_state.decode_design_snapshot(entry.post_state_gz_b64)
        except Exception:
            old_post = None
        if old_post is not None:
            temp = _reconcile_cluster_joints_between(temp, old_post, rebuilt)

    before_failures = _n_failures(validate_design(design))
    updated = _seek_feature_log(temp, new_cursor)
    design_state.set_design(updated)
    report = validate_design(updated)

    # Best-effort warning: defensive-apply anomalies and/or a validation
    # regression vs. the pre-delete design (later steps depended on this one).
    new_failures = _n_failures(report)
    if new_failures > before_failures:
        warnings.append(
            f"Deleting this sub-step introduced {new_failures - before_failures} new validation "
            "issue(s) — later steps may have depended on it. Ctrl-Z to undo."
        )
    resp = _design_replace_response(design, updated, report)
    if warnings:
        resp["placement_warnings"] = (
            list(resp.get("placement_warnings") or []) + warnings
        )
    return resp


def _feature_label(entry) -> str:
    """Short human label for a feature-log entry (used to list dependents)."""
    ft = getattr(entry, "feature_type", "")
    if ft == "snapshot":
        return getattr(entry, "label", None) or getattr(entry, "op_kind", "op")
    if ft == "routing-cluster":
        return getattr(entry, "label", None) or "Fine Routing"
    if ft == "deformation":
        op = getattr(entry, "op_snapshot", None)
        return (
            op.type.capitalize() if op and getattr(op, "type", None) else "Deformation"
        )
    if ft == "cluster_op":
        return "Cluster move"
    if ft == "cluster_create":
        return getattr(entry, "name", None) or "Create cluster"
    if ft == "overhang_rotation":
        return "Overhang rotation"
    return ft or "feature"


def _build_entry_info(entry, design):
    """Summarize one feature-log entry for dependency analysis.

    Decodes snapshot pre/post to compute the ids it added/modified; resolves the
    pre-existing ids a delta entry consumes. See
    :mod:`backend.core.feature_dependencies`.
    """
    from backend.core.feature_dependencies import (
        EntryInfo,
        REPLAYABLE_SNAPSHOT_OPS,
        snapshot_delta,
        structural_reference_targets,
        delta_entry_targets,
    )

    ft = entry.feature_type
    if ft == "snapshot":
        reconstructable = (not entry.evicted) and (
            entry.op_kind in REPLAYABLE_SNAPSHOT_OPS
        )
        added: set = set()
        modified: set = set()
        try:
            if entry.design_snapshot_gz_b64 and entry.post_state_gz_b64:
                pre = design_state.decode_design_snapshot(entry.design_snapshot_gz_b64)
                post = design_state.decode_design_snapshot(entry.post_state_gz_b64)
                added, modified = snapshot_delta(pre, post)
                targets = structural_reference_targets(pre, post, added, modified)
        except Exception:
            added, modified = set(), set()
            targets = None
        return EntryInfo(
            added=added,
            modified=modified,
            targets=targets,
            reconstructable=reconstructable,
        )

    if ft == "routing-cluster":
        added, modified = set(), set()
        try:
            if entry.pre_state_gz_b64 and entry.post_state_gz_b64 and not entry.evicted:
                pre = design_state.decode_design_snapshot(entry.pre_state_gz_b64)
                post = design_state.decode_design_snapshot(entry.post_state_gz_b64)
                added, modified = snapshot_delta(pre, post)
                targets = structural_reference_targets(pre, post, added, modified)
        except Exception:
            added, modified = set(), set()
            targets = None
        return EntryInfo(
            added=added, modified=modified, targets=targets, reconstructable=False
        )

    # Overlay delta (deformation / cluster_op / cluster_create / overhang_rotation):
    # always reconstructable by seek; depends only on the ids it targets.
    return EntryInfo(
        added=set(),
        modified=set(),
        targets=delta_entry_targets(entry, design),
        reconstructable=True,
    )


def _filter_removed_ids_from_design(design: Design, removed_ids: set) -> Design:
    """Drop removed topology ids and prune containers that point at removed helices."""
    if not removed_ids:
        return design

    def keep_id(item) -> bool:
        return getattr(item, "id", None) not in removed_ids

    removed_helices = {h.id for h in design.helices if h.id in removed_ids}
    removed_strands = {s.id for s in design.strands if s.id in removed_ids}
    removed_overhangs = {
        o.id
        for o in design.overhangs
        if o.id in removed_ids or o.helix_id in removed_helices
    }
    removed_clusters = {
        ct.id for ct in design.cluster_transforms if ct.id in removed_ids
    }
    removed_protein_assets = {
        a.id for a in design.protein_assets if a.id in removed_ids
    }

    new_cts = []
    for ct in design.cluster_transforms:
        if ct.id in removed_ids:
            continue
        helix_ids = [hid for hid in (ct.helix_ids or []) if hid not in removed_helices]
        domain_ids = [
            ref for ref in (ct.domain_ids or []) if ref.strand_id not in removed_strands
        ]
        if not helix_ids and not domain_ids:
            removed_clusters.add(ct.id)
            continue
        new_cts.append(
            ct.model_copy(update={"helix_ids": helix_ids, "domain_ids": domain_ids})
        )

    def strand_survives(s) -> bool:
        return (
            s.id not in removed_ids
            and all(dom.helix_id not in removed_helices for dom in s.domains)
            and all(
                (dom.overhang_id is None or dom.overhang_id not in removed_overhangs)
                for dom in s.domains
            )
            and all(
                (
                    dom.binds_overhang_id is None
                    or dom.binds_overhang_id not in removed_overhangs
                )
                for dom in s.domains
            )
        )

    def xover_survives(x) -> bool:
        return (
            x.id not in removed_ids
            and x.half_a.helix_id not in removed_helices
            and x.half_b.helix_id not in removed_helices
        )

    def fl_survives(f) -> bool:
        return (
            f.id not in removed_ids
            and f.three_prime_helix_id not in removed_helices
            and f.five_prime_helix_id not in removed_helices
        )

    return design.copy_with(
        helices=[h for h in design.helices if h.id not in removed_ids],
        strands=[s for s in design.strands if strand_survives(s)],
        crossovers=[x for x in design.crossovers if xover_survives(x)],
        overhangs=[
            o
            for o in design.overhangs
            if o.id not in removed_ids
            and o.helix_id not in removed_helices
            and o.strand_id not in removed_strands
        ],
        overhang_connections=[
            c
            for c in design.overhang_connections
            if c.id not in removed_ids
            and c.overhang_a_id not in removed_overhangs
            and c.overhang_b_id not in removed_overhangs
        ],
        extensions=[
            e
            for e in design.extensions
            if e.id not in removed_ids and e.strand_id not in removed_strands
        ],
        photoproduct_junctions=[
            p for p in design.photoproduct_junctions if p.id not in removed_ids
        ],
        forced_ligations=[f for f in design.forced_ligations if fl_survives(f)],
        cluster_transforms=new_cts,
        cluster_joints=[
            j
            for j in design.cluster_joints
            if j.id not in removed_ids and j.cluster_id not in removed_clusters
        ],
        flexible_segment_marks=[
            m
            for m in design.flexible_segment_marks
            if m.id not in removed_ids and m.strand_id not in removed_strands
        ],
        flexible_connections=[
            fc
            for fc in design.flexible_connections
            if (
                fc.id not in removed_ids
                and fc.cluster_a_id not in removed_clusters
                and fc.cluster_b_id not in removed_clusters
                and fc.anchor_a.strand_id not in removed_strands
                and fc.anchor_b.strand_id not in removed_strands
            )
        ],
        protein_assets=[a for a in design.protein_assets if a.id not in removed_ids],
        protein_attachments=[
            a
            for a in design.protein_attachments
            if a.id not in removed_ids and a.asset_id not in removed_protein_assets
        ],
    )


def _strip_removed_ids_from_snapshot(
    payload_b64: str, removed_ids: set
) -> tuple[str, int]:
    snap = design_state.decode_design_snapshot(payload_b64)
    scrubbed = _filter_removed_ids_from_design(snap, removed_ids)
    return design_state.encode_design_snapshot(scrubbed)


def _snapshot_removed_ids(entry) -> set:
    from backend.core.feature_dependencies import snapshot_removed

    if not getattr(entry, "design_snapshot_gz_b64", None) or not getattr(
        entry, "post_state_gz_b64", None
    ):
        return set()
    pre = design_state.decode_design_snapshot(entry.design_snapshot_gz_b64)
    post = design_state.decode_design_snapshot(entry.post_state_gz_b64)
    return snapshot_removed(pre, post)


def _delete_snapshot_feature_by_replay(
    design: Design, log: list, index: int, entry, deps: list
) -> dict:
    from backend.core.models import SnapshotLogEntry as _SnapEntry
    from backend.core.validator import validate_design

    removal = {index} | set(deps)
    state = design_state.decode_design_snapshot(entry.design_snapshot_gz_b64)

    new_entries: list = list(log[:index])
    for j in range(index + 1, len(log)):
        if j in removal:
            continue
        e = log[j]
        if isinstance(e, _SnapEntry):
            pre_b64, pre_sz = design_state.encode_design_snapshot(state)
            try:
                state = _edit_dispatch_run(e.op_kind, state, e.params)
            except (HTTPException, ValidationError, ValueError) as exc:
                raise HTTPException(
                    409,
                    detail=f"Could not surgically delete: '{_feature_label(e)}' "
                    f"could not be re-applied without the deleted feature. "
                    f"Revert to before it instead.",
                ) from exc
            post_b64, post_sz = design_state.encode_design_snapshot(state)
            new_entries.append(
                e.model_copy(
                    update={
                        "design_snapshot_gz_b64": pre_b64,
                        "snapshot_size_bytes": pre_sz,
                        "post_state_gz_b64": post_b64,
                        "post_state_size_bytes": post_sz,
                        "evicted": False,
                    }
                )
            )
        else:
            new_entries.append(e)

    base = state.copy_with(feature_log=new_entries)
    updated = _seek_feature_log(base, -1)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_replace_response(design, updated, report)


def _delete_snapshot_feature_by_subtraction(
    design: Design, log: list, index: int, deps: list, infos: list
) -> dict:
    from backend.core.models import (
        SnapshotLogEntry as _SnapEntry,
        RoutingClusterLogEntry as _RoutingEntry,
    )
    from backend.core.validator import validate_design

    removal = {index} | set(deps)
    removed_ids: set = set()
    for j in removal:
        removed_ids |= set(infos[j].added)

    new_entries: list = []
    for j, e in enumerate(log):
        if j in removal:
            continue
        if (
            j > index
            and isinstance(e, _SnapEntry)
            and e.design_snapshot_gz_b64
            and e.post_state_gz_b64
        ):
            pre_b64, pre_sz = _strip_removed_ids_from_snapshot(
                e.design_snapshot_gz_b64, removed_ids
            )
            post_b64, post_sz = _strip_removed_ids_from_snapshot(
                e.post_state_gz_b64, removed_ids
            )
            e = e.model_copy(
                update={
                    "design_snapshot_gz_b64": pre_b64,
                    "snapshot_size_bytes": pre_sz,
                    "post_state_gz_b64": post_b64,
                    "post_state_size_bytes": post_sz,
                }
            )
        elif (
            j > index
            and isinstance(e, _RoutingEntry)
            and e.pre_state_gz_b64
            and e.post_state_gz_b64
        ):
            pre_b64, pre_sz = _strip_removed_ids_from_snapshot(
                e.pre_state_gz_b64, removed_ids
            )
            post_b64, post_sz = _strip_removed_ids_from_snapshot(
                e.post_state_gz_b64, removed_ids
            )
            e = e.model_copy(
                update={
                    "pre_state_gz_b64": pre_b64,
                    "pre_state_size_bytes": pre_sz,
                    "post_state_gz_b64": post_b64,
                    "post_state_size_bytes": post_sz,
                }
            )
        new_entries.append(e)

    base = _filter_removed_ids_from_design(design, removed_ids).copy_with(
        feature_log=new_entries
    )
    updated = _seek_feature_log(base, -1)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_replace_response(design, updated, report)


def _delete_snapshot_feature(
    design: Design, log: list, index: int, entry, cascade: bool
) -> dict:
    """Option-1 surgical delete of a topology-producing snapshot entry.

    Computes the entry's dependents (later entries that can't survive its
    removal). With dependents and ``cascade=False``, returns a
    ``needs_cascade_decision`` payload (no mutation). Otherwise removes the
    entry (+ dependents on cascade), reconstructs the design by threading the
    entry's PRE-state forward through the surviving replayable extrusions, and
    re-seeks so overlay deltas rebuild on top. Pushes undo via ``set_design``.
    """
    from backend.core.feature_dependencies import analyze_dependents

    # Earlier entries can never be dependents, so only summarize index..end.
    infos: list = [None] * len(log)
    for j in range(index, len(log)):
        infos[j] = _build_entry_info(log[j], design)

    deps = analyze_dependents(infos, index)

    if deps and not cascade:
        return {
            "needs_cascade_decision": True,
            "target_index": index,
            "target_label": _feature_label(entry),
            "dependents": [{"index": j, "label": _feature_label(log[j])} for j in deps],
        }

    if entry.evicted or not entry.design_snapshot_gz_b64:
        raise HTTPException(
            410,
            detail="This feature's snapshot was evicted to free space, so its "
            "geometry can't be rolled back. Revert instead.",
        )

    try:
        non_additive = any(
            _snapshot_removed_ids(log[j]) or infos[j].modified
            for j in ({index} | set(deps))
        )
    except Exception:
        non_additive = True
    if non_additive:
        return _delete_snapshot_feature_by_replay(design, log, index, entry, deps)
    return _delete_snapshot_feature_by_subtraction(design, log, index, deps, infos)


@router.delete("/design/features/{index}", status_code=200)
def delete_feature(
    index: int, sub_index: int | None = None, cascade: bool = False
) -> dict:
    """Remove the feature at the given log index (0-based) and reconstruct state.

    **Delete = roll back this op's geometry (option-1 semantics).** Deleting a
    topology-producing snapshot entry removes both the log row AND the geometry
    that op created, keeping any later entries that don't depend on it. When
    later entries DO depend on it (built on its geometry, or non-replayable
    auto-ops baked on top of it), the call returns ``needs_cascade_decision``
    listing those dependents WITHOUT mutating the design; the client then either
    cascades (``?cascade=true`` → delete the entry + all its dependents) or
    reverts. See :mod:`backend.core.feature_dependencies`.

    Pure overlay deltas (deformation / cluster_op / cluster_create /
    overhang_rotation) already roll back on delete — ``_seek_feature_log``
    rebuilds them from the surviving log — so they keep their existing path.
    Fine-Routing clusters still keep their geometry on delete (their surgical
    rollback is deferred along with auto-op re-derivation).

    ``sub_index`` (optional, query param) targets a single sub-step inside a
    Fine Routing cluster: the named child is removed surgically and the rest of
    the cluster + later entries are replayed. Deleting the only remaining child
    falls through to removing the whole cluster.

    The cursor is adjusted so the active window stays consistent:
    - If the cursor was pointing at or past the deleted entry, it shifts left.
    - If the deleted entry was the only active one (cursor == index == 0), the
      cursor resets to -2 (empty state).
    Pushes to the undo stack.
    """
    from backend.core.models import SnapshotLogEntry as _SnapEntry
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    log = list(design.feature_log)

    if index < 0 or index >= len(log):
        raise HTTPException(
            400,
            detail=f"Feature index {index} out of range (log has {len(log)} entries).",
        )

    entry = log[index]
    if entry.feature_type == "checkpoint":
        raise HTTPException(400, detail="Cannot delete checkpoint entries.")

    # Per-sub-step delete inside a Fine Routing cluster.
    if sub_index is not None:
        if entry.feature_type != "routing-cluster":
            raise HTTPException(
                400, detail="sub_index is only valid for Fine Routing cluster entries."
            )
        n_children = len(entry.children)
        if sub_index < 0 or sub_index >= n_children:
            raise HTTPException(
                400,
                detail=f"sub_index {sub_index} out of range (cluster has {n_children} sub-steps).",
            )
        return _delete_routing_child(design, log, index, entry, sub_index)

    # Topology-producing snapshot ops (extrusions, auto-*, circle, protein,
    # assembly): option-1 surgical delete — roll back this op's geometry and
    # keep independent later ops, or list dependents for a cascade decision.
    if isinstance(entry, _SnapEntry):
        return _delete_snapshot_feature(design, log, index, entry, cascade)

    new_log = [e for e in log if e.id != entry.id]

    # Adjust the cursor so the active window remains consistent after removal.
    cursor = design.feature_log_cursor
    if cursor == -2 or cursor < index:
        new_cursor = cursor  # active window unaffected
    elif cursor == -1:
        new_cursor = -1  # all remaining entries stay active
    elif cursor == 0:
        new_cursor = -2  # only active entry was just deleted → empty
    else:
        new_cursor = cursor - 1  # shift left by one

    temp = design.copy_with(feature_log=new_log)

    # Reaching here means a delta / overlay entry (deformation / cluster_op /
    # cluster_create / overhang_rotation) — `_seek_feature_log` already rolls
    # these back by rebuilding them from the surviving log. (Topology-producing
    # snapshot entries took the `_delete_snapshot_feature` path above.)

    # If the deleted entry was a cluster_op and the cluster has no remaining ops
    # in new_log, _seek_feature_log won't know to reset it (the cluster won't appear
    # in clusters_with_ops).  Pre-reset the transform here so the seek sees identity.
    if entry.feature_type == "cluster_op":
        still_has_ops = any(
            e.feature_type == "cluster_op" and e.cluster_id == entry.cluster_id
            for e in new_log
        )
        if not still_has_ops:
            new_cts = [
                ct.model_copy(
                    update={
                        "translation": [0.0, 0.0, 0.0],
                        "rotation": [0.0, 0.0, 0.0, 1.0],
                    }
                )
                if ct.id == entry.cluster_id
                else ct
                for ct in temp.cluster_transforms
            ]
            temp = temp.copy_with(cluster_transforms=new_cts)

    # If the deleted entry was a routing-cluster that placed / updated / deleted
    # joints, _seek_feature_log doesn't replay cluster_joints from log entries
    # (joints are only mutated by minor ops nested inside routing-clusters), so
    # the orphaned indicators would stay on screen. Use the entry's stored
    # pre/post snapshots to invert this routing-cluster's joint delta on the
    # live cluster_joints. Without pre/post payload (evicted) we can't recover
    # the delta; the indicators stay until a manual joint-delete.
    if (
        entry.feature_type == "routing-cluster"
        and entry.pre_state_gz_b64
        and entry.post_state_gz_b64
    ):
        try:
            pre_design = design_state.decode_design_snapshot(entry.pre_state_gz_b64)
            post_design = design_state.decode_design_snapshot(entry.post_state_gz_b64)
        except Exception:
            pre_design = None
            post_design = None
        if pre_design is not None and post_design is not None:
            # Live joints reflect the cluster's POST-state; deleting it should
            # invert back to the PRE-state set (from=post, to=pre).
            temp = _reconcile_cluster_joints_between(temp, post_design, pre_design)

    updated = _seek_feature_log(temp, new_cursor)
    # Deleting a bend/twist must re-place any primitive that was appended onto the
    # bent face (a deformed continuation bakes the deformed frame), so its geometry
    # reflects the now-un-bent part. No-op when the design has no such continuation.
    if entry.feature_type == "deformation":
        updated = _rebuild_deformed_continuations(updated)
    design_state.set_design(updated)
    report = validate_design(updated)
    # Use the same fast-path picker as undo/redo/seek so deleting a cluster_op
    # entry takes the lean cluster-only path instead of the multi-MB embedded
    # full geometry path. positions_only kicks in for non-topology-changing
    # deletions; full geometry only for true topology changes (rare for delete).
    return _design_replace_response(design, updated, report)


class LoadoutCreateBody(BaseModel):
    name: Optional[str] = None


class LoadoutRenameBody(BaseModel):
    name: str


def _encode_loadout_design_snapshot(design: Design) -> tuple[str, int]:
    """Encode a branch snapshot with feature_log/cursor preserved.

    Unlike feature-log revert snapshots, loadouts are whole-branch saves. They
    therefore keep the feature timeline and slider cursor, but strip loadouts
    themselves to avoid recursive branch nesting.
    """
    stripped = design.model_copy(update={"loadouts": [], "active_loadout_id": None})
    raw = stripped.model_dump_json().encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    return base64.b64encode(gz).decode("ascii"), len(raw)


def _decode_loadout_design_snapshot(payload_b64: str) -> Design:
    if not payload_b64:
        raise ValueError("empty loadout snapshot payload")
    raw = gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))
    return Design.model_validate_json(raw)


def _ensure_loadouts(design: Design) -> tuple[list[DesignLoadout], str]:
    loadouts = list(design.loadouts or [])
    active_id = design.active_loadout_id
    if loadouts and any(l.id == active_id for l in loadouts):
        return loadouts, active_id
    if loadouts:
        return loadouts, loadouts[0].id
    payload, size = _encode_loadout_design_snapshot(design)
    first = DesignLoadout(
        id=str(_uuid.uuid4()),
        name="Loadout 1",
        design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size,
    )
    return [first], first.id


def _auto_loadout_name(loadouts: list[DesignLoadout]) -> str:
    """Lowest ``Loadout N`` not already taken by an existing loadout.

    Robust against renames/deletes: counting ``len + 1`` collides once any
    loadout has been removed or hand-renamed (e.g. delete "Loadout 1" then
    create → len 1 → "Loadout 2", which already exists). Scanning for the first
    free integer never collides.
    """
    existing = {l.name for l in loadouts}
    n = 1
    while f"Loadout {n}" in existing:
        n += 1
    return f"Loadout {n}"


def _save_active_loadout_snapshot(
    design: Design, loadouts: list[DesignLoadout], active_id: str
) -> list[DesignLoadout]:
    payload, size = _encode_loadout_design_snapshot(design)
    return [
        l.model_copy(
            update={
                "design_snapshot_gz_b64": payload,
                "snapshot_size_bytes": size,
            }
        )
        if l.id == active_id
        else l
        for l in loadouts
    ]


@router.post("/design/loadouts", status_code=200)
def create_loadout(body: LoadoutCreateBody) -> dict:
    """Create a new branch by copying the current design + feature-log cursor."""
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    loadouts, active_id = _ensure_loadouts(current)
    loadouts = _save_active_loadout_snapshot(current, loadouts, active_id)

    name = (body.name or "").strip() or _auto_loadout_name(loadouts)
    new_id = str(_uuid.uuid4())
    payload, size = _encode_loadout_design_snapshot(current)
    loadouts.append(
        DesignLoadout(
            id=new_id,
            name=name,
            design_snapshot_gz_b64=payload,
            snapshot_size_bytes=size,
        )
    )

    updated = current.copy_with(loadouts=loadouts, active_loadout_id=new_id)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


@router.post("/design/loadouts/{loadout_id}/select", status_code=200)
def select_loadout(loadout_id: str, save_current: bool = True) -> dict:
    """Save the current branch and restore the selected branch snapshot.

    ``save_current=false`` restores WITHOUT first folding the current design into the
    active loadout — used by the oxDNA/MD "Return to latest" action: after a roll the
    active design is the job's run-state (reproducible from the job), so it must NOT
    overwrite the loadout holding the user's latest edits."""
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    loadouts, active_id = _ensure_loadouts(current)
    if save_current:
        loadouts = _save_active_loadout_snapshot(current, loadouts, active_id)

    selected = next((l for l in loadouts if l.id == loadout_id), None)
    if selected is None:
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    try:
        restored = _decode_loadout_design_snapshot(selected.design_snapshot_gz_b64)
    except Exception as exc:
        raise HTTPException(500, detail=f"Failed to restore loadout: {exc}") from exc

    updated = restored.copy_with(loadouts=loadouts, active_loadout_id=loadout_id)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


@router.patch("/design/loadouts/{loadout_id}", status_code=200)
def rename_loadout(loadout_id: str, body: LoadoutRenameBody) -> dict:
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    loadouts, active_id = _ensure_loadouts(design)
    if loadout_id == "__implicit_loadout_1__":
        loadout_id = active_id
    name = body.name.strip()
    if not name:
        raise HTTPException(400, detail="Loadout name cannot be empty.")
    if not any(l.id == loadout_id for l in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")
    loadouts = [
        l.model_copy(update={"name": name}) if l.id == loadout_id else l
        for l in loadouts
    ]
    updated = design.copy_with(loadouts=loadouts, active_loadout_id=active_id)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response(updated, report)


@router.delete("/design/loadouts/{loadout_id}", status_code=200)
def delete_loadout(loadout_id: str) -> dict:
    """Delete a branch. The final remaining loadout cannot be deleted."""
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    loadouts, active_id = _ensure_loadouts(current)
    if len(loadouts) <= 1:
        raise HTTPException(400, detail="Cannot delete the only loadout.")
    if not any(l.id == loadout_id for l in loadouts):
        raise HTTPException(404, detail=f"Loadout {loadout_id!r} not found.")

    loadouts = _save_active_loadout_snapshot(current, loadouts, active_id)
    remaining = [l for l in loadouts if l.id != loadout_id]
    next_id = active_id if active_id != loadout_id else remaining[0].id
    if next_id == active_id:
        updated = current.copy_with(loadouts=remaining, active_loadout_id=next_id)
    else:
        try:
            restored = _decode_loadout_design_snapshot(
                remaining[0].design_snapshot_gz_b64
            )
        except Exception as exc:
            raise HTTPException(
                500, detail=f"Failed to restore next loadout: {exc}"
            ) from exc
        updated = restored.copy_with(loadouts=remaining, active_loadout_id=next_id)

    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


# ── Edit-feature dispatch ─────────────────────────────────────────────────────
#
# Maps each extrusion op_kind to the request-body class used by the original
# endpoint plus the pure builder. The edit endpoint validates the new params
# against the original schema, then replays the op against the snapshot's
# pre-state.
#
# Auto-op kinds (auto-scaffold variants, auto-break, etc.) are intentionally
# NOT in this table — those operations are usually re-run rather than
# parameter-edited; the user can revert them and rerun via the original UI.


def _edit_dispatch_run(op_kind: str, pre_state: Design, params: dict) -> Design:
    """Validate ``params`` against the schema for ``op_kind`` and return the
    new design produced by replaying the op on ``pre_state``. Raises HTTP 400
    on schema mismatch, HTTP 422 on op-runtime errors."""
    if op_kind == "bundle-create":
        body = BundleRequest.model_validate(params)
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
        return _build_bundle(cells, body)
    if op_kind == "extrude-segment":
        body = BundleSegmentRequest.model_validate(params)
        updated, _ = _build_extrude_segment(pre_state, body)
        return updated
    if op_kind == "extrude-continuation":
        body = BundleContinuationRequest.model_validate(params)
        updated, _ = _build_extrude_continuation(pre_state, body)
        return updated
    if op_kind == "extrude-deformed-continuation":
        body = BundleDeformedContinuationRequest.model_validate(params)
        updated, _ = _build_extrude_deformed_continuation(pre_state, body)
        return updated
    if op_kind == "overhang-extrude":
        body = OverhangExtrudeRequest.model_validate(params)
        updated, _ = _build_overhang_extrude(pre_state, body)
        return updated
    raise HTTPException(
        400,
        detail=f"op_kind {op_kind!r} is not editable via this endpoint. "
        "Auto-ops (auto-scaffold, auto-break, etc.) should be reverted and re-run.",
    )


class EditFeatureBody(BaseModel):
    params: dict


def _edit_cluster_op_feature(
    index: int,
    entry: "ClusterOpLogEntry",
    body: EditFeatureBody,
    design: Design,
) -> dict:
    """Edit branch for ``edit_feature`` when the target is a ClusterOpLogEntry.

    Thin api shell: delegate the pure pose-rewrite to
    ``backend.core.feature_log_edit.edit_cluster_op_entry`` (translate
    :class:`FeatureEditError` → HTTPException), then commit + respond.
    """
    try:
        updated = edit_cluster_op_entry(design, index, entry, body.params)
    except FeatureEditError as e:
        raise HTTPException(e.status, detail=str(e))

    from backend.core.validator import validate_design as _validate_design

    design_state.set_design(updated)
    report = _validate_design(updated)
    # Cluster-only diff: design differs from prev only in cluster_transforms,
    # so this typically lands in the lean cluster_only fast path. Frontend
    # applies the delta in place — no full geometry recompute.
    return _design_replace_response(design, updated, report)


def _edit_deformation_feature(
    index: int,
    entry: "DeformationLogEntry",
    body: EditFeatureBody,
    design: Design,
) -> dict:
    """Edit branch for ``edit_feature`` when the target is a DeformationLogEntry.

    Thin api shell: delegate the pure op-rewrite + deformation-set rebuild to
    ``backend.core.feature_log_edit.edit_deformation_entry`` (translate
    :class:`FeatureEditError` → HTTPException), then run the api-bound
    deformed-continuation re-bake, commit + respond.
    """
    try:
        updated = edit_deformation_entry(design, index, entry, body.params)
    except FeatureEditError as e:
        raise HTTPException(e.status, detail=str(e))

    from backend.core.validator import validate_design as _validate_design

    # Editing a bend/twist (e.g. changing its angle) must re-place any primitive
    # appended onto the bent face so it tracks the new deformation. No-op when the
    # design has no deformed continuation. (api-bound: needs snapshot decode +
    # live builders, so it stays here, not in core.)
    updated = _rebuild_deformed_continuations(updated)
    design_state.set_design(updated)
    report = _validate_design(updated)
    return _design_replace_response(design, updated, report)


@router.post("/design/features/{index}/edit", status_code=200)
def edit_feature(index: int, body: EditFeatureBody) -> dict:
    """Replay or update the feature at ``feature_log[index]`` in place.

    Two cases are supported:

    * **SnapshotLogEntry (extrusion)** — same legacy behaviour: decode the
      entry's pre-state, run the op with new params, splice the new
      post-state in. Only valid when:
        - the entry is non-evicted,
        - its ``op_kind`` is an extrusion (bundle-create, extrude-*,
          overhang-extrude),
        - no later ``SnapshotLogEntry`` exists in the log.

    * **DeformationLogEntry** — update the existing ``DeformationOp`` in
      ``design.deformations`` (fields type / plane_a_bp / plane_b_bp /
      params / affected_helix_ids / cluster_id) and refresh the entry's
      ``op_snapshot``. Avoids the previous behaviour of emitting a brand-new
      log entry on confirm-from-edit, which made the log grow on every edit.

    Both paths push the prior state onto the undo stack and return the
    response via the standard ``_design_replace_response`` fast-path picker.
    """
    from backend.core.models import (
        SnapshotLogEntry as _SnapshotLogEntry,
        DeformationLogEntry as _DeformationLogEntry,
    )

    design = design_state.get_or_404()
    log = list(design.feature_log)

    if index < 0 or index >= len(log):
        raise HTTPException(
            400,
            detail=f"Feature index {index} out of range (log has {len(log)} entries).",
        )

    entry = log[index]

    # ── Deformation edit branch ───────────────────────────────────────────────
    if isinstance(entry, _DeformationLogEntry):
        return _edit_deformation_feature(index, entry, body, design)

    # ── Cluster_op edit branch ────────────────────────────────────────────────
    from backend.core.models import ClusterOpLogEntry as _ClusterOpLogEntry

    if isinstance(entry, _ClusterOpLogEntry):
        return _edit_cluster_op_feature(index, entry, body, design)

    if not isinstance(entry, _SnapshotLogEntry):
        raise HTTPException(
            400,
            detail=f"Feature at index {index} is not editable (type {entry.feature_type!r}).",
        )
    if entry.evicted or not entry.design_snapshot_gz_b64:
        raise HTTPException(
            410,
            detail=f"Snapshot for feature {index} ({entry.label!r}) was evicted; cannot replay.",
        )

    later_snapshots = [
        i
        for i, e in enumerate(log[index + 1 :], start=index + 1)
        if isinstance(e, _SnapshotLogEntry)
    ]
    if later_snapshots:
        raise HTTPException(
            409,
            detail=(
                f"Cannot edit feature {index}: {len(later_snapshots)} later snapshot "
                "entries exist. Revert to this point first, then re-run subsequent "
                "operations."
            ),
        )

    pre_state = design_state.decode_design_snapshot(entry.design_snapshot_gz_b64)

    try:
        new_post = _edit_dispatch_run(entry.op_kind, pre_state, body.params)
    except HTTPException:
        raise
    except ValidationError as exc:
        raise HTTPException(
            400, detail=f"Invalid params for {entry.op_kind}: {exc}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    # Re-encode pre/post so size + payload reflect the new operation outcome.
    new_pre_b64, new_pre_size = design_state.encode_design_snapshot(pre_state)
    new_post_b64, new_post_size = design_state.encode_design_snapshot(new_post)

    updated_entry = entry.model_copy(
        update={
            "params": body.params,
            "design_snapshot_gz_b64": new_pre_b64,
            "snapshot_size_bytes": new_pre_size,
            "post_state_gz_b64": new_post_b64,
            "post_state_size_bytes": new_post_size,
        }
    )
    new_log = list(log)
    new_log[index] = updated_entry

    # Carry forward existing log entries that come AFTER the snapshot but are
    # delta entries (deformations / cluster_op / overhang_rotation). They were
    # filtered out of "later_snapshots" so they're safe to keep — the seek
    # logic best-effort applies them.
    from backend.core.validator import validate_design as _validate_design

    final = new_post.copy_with(feature_log=new_log, feature_log_cursor=-1)
    design_state.set_design(final)
    report = _validate_design(final)
    # Snapshot edits typically change topology (extrusion params), so the
    # response usually lands in the embedded full-geometry path. Cluster_only
    # / positions_only fire in the rare case where an extrusion edit happened
    # to leave the renderer-relevant fields unchanged.
    return _design_replace_response(design, final, report)


def roll_active_to_job_state(
    snapshot: Design, feature_log_position, return_name: str
) -> dict:
    """Roll the active design back to the state an oxDNA/MD job was run at, by SEEKING
    the feature-log cursor to the job's position — exactly like sliding the Feature Log
    tab's rail.  The full feature log is preserved (later entries — e.g. an overhang
    added after the run — become inactive/forward, so the model loses them and the
    user can seek forward again), and the cursor is visible in the Feature Log tab.

    Sequence assignment is now a logged op, so the seek reproduces the job's exact
    state (the out-of-date fingerprint clears).  For OLD jobs created before that,
    the seek may drop sequences → we overlay the job's saved snapshot topology while
    keeping the seeked feature_log + cursor, so the run is still consistent.

    The pre-roll design is saved as a loadout branch (``return_loadout_id``, the
    "Return to latest" target) and pushed to undo (Ctrl-Z restores)."""
    from backend.core.oxdna_staleness import design_build_fingerprint
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    loadouts = list(current.loadouts or [])
    active_id = current.active_loadout_id
    if loadouts and active_id and any(l.id == active_id for l in loadouts):
        loadouts = _save_active_loadout_snapshot(current, loadouts, active_id)
    return_id = str(_uuid.uuid4())
    payload, size = _encode_loadout_design_snapshot(current)
    loadouts.append(
        DesignLoadout(
            id=return_id,
            name=return_name,
            design_snapshot_gz_b64=payload,
            snapshot_size_bytes=size,
        )
    )

    # Seek the cursor to the job's run position (full log kept, cursor moves).
    n = len(current.feature_log)
    if feature_log_position is not None and -1 <= feature_log_position < n:
        seeked = _seek_feature_log(current, feature_log_position)
    else:
        seeked = current  # no recorded position / out of range → leave the cursor

    # New jobs: the seek already reproduces the job's state.  Old jobs: overlay the
    # job's exact snapshot topology onto the seeked log/cursor so it still runs.
    if design_build_fingerprint(seeked) == design_build_fingerprint(snapshot):
        rolled = seeked.copy_with(loadouts=loadouts, active_loadout_id=None)
    else:
        rolled = snapshot.copy_with(
            feature_log=seeked.feature_log,
            feature_log_cursor=seeked.feature_log_cursor,
            feature_log_sub_cursor=seeked.feature_log_sub_cursor,
            loadouts=loadouts,
            active_loadout_id=None,
        )

    design_state.set_design(rolled)
    report = validate_design(rolled)
    resp = _design_response_with_geometry(rolled, report)
    resp["return_loadout_id"] = return_id
    return resp


@router.post("/design/features/{index}/revert", status_code=200)
def revert_to_before_feature(index: int, sub_index: int | None = None) -> dict:
    """Restore the pre-state snapshot of feature_log[index] and TRUNCATE
    feature_log to [0..index-1].

    Valid for both ``SnapshotLogEntry`` (auto-op snapshots) and
    ``RoutingClusterLogEntry`` (Fine Routing clusters). Returns 410 GONE if
    the entry's snapshot bytes were evicted to free space.

    ``sub_index`` (optional, query param) reverts to just BEFORE a single
    sub-step inside a Fine Routing cluster: children[0..sub_index-1] are kept,
    and that sub-step plus everything after it (later children + later log
    entries) is dropped. ``sub_index == 0`` is equivalent to reverting the whole
    cluster.

    The pre-revert design is pushed onto the undo stack so the revert itself
    can be undone via ``POST /design/undo``.

    Truncation rationale: keeping later delta entries (deformation /
    cluster_op / overhang_rotation) against a pre-snapshot design silently
    corrupts data because their target IDs no longer exist after restore.
    Truncate is the safe default; user can Ctrl-Z if they regret it.
    """
    from backend.core.models import (
        RoutingClusterLogEntry as _RoutingClusterLogEntry,
        SnapshotLogEntry as _SnapshotLogEntry,
    )
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    log = list(design.feature_log)

    if index < 0 or index >= len(log):
        raise HTTPException(
            400,
            detail=f"Feature index {index} out of range (log has {len(log)} entries).",
        )

    entry = log[index]

    # Per-sub-step revert inside a Fine Routing cluster.
    if sub_index is not None:
        if not isinstance(entry, _RoutingClusterLogEntry):
            raise HTTPException(
                400, detail="sub_index is only valid for Fine Routing cluster entries."
            )
        return _revert_before_routing_child(design, log, index, entry, sub_index)

    # Delta entries (deformation / cluster_op / overhang_rotation) carry no
    # baked pre-state snapshot — their effect is reconstructed by replaying the
    # log. "Revert to before" such an entry therefore means: truncate the log to
    # [0..index-1] and re-seek to the end, which rebuilds the topology base from
    # the last surviving snapshot and re-derives the deformation / cluster /
    # overhang overlays WITHOUT this entry (and without every entry after it).
    # Same user-facing contract as snapshot revert; Ctrl-Z restores.
    if entry.feature_type in ("deformation", "cluster_op", "overhang_rotation"):
        truncated = design.copy_with(feature_log=log[:index])
        if log[:index]:
            restored = _seek_feature_log(truncated, -1)
        else:
            # Truncated to an empty log → no features active. _seek_feature_log's
            # empty-log fast path skips the overlay rebuild, leaving the now-
            # removed deformation in place, so seek to the -2 (no-features) state
            # which clears the deformation / cluster / overhang overlays, then
            # pin the cursor to -1 to match snapshot-revert-to-F0 semantics.
            restored = _seek_feature_log(truncated, -2).copy_with(feature_log_cursor=-1)
        design_state.set_design(restored)
        report = validate_design(restored)
        return _design_response_with_geometry(restored, report)

    # Pull pre-state bytes from whichever payload type this is.
    if isinstance(entry, _SnapshotLogEntry):
        pre_b64 = entry.design_snapshot_gz_b64
        label = entry.label
    elif isinstance(entry, _RoutingClusterLogEntry):
        pre_b64 = entry.pre_state_gz_b64
        label = entry.label
    else:
        raise HTTPException(
            400,
            detail=f"Feature at index {index} (type={entry.feature_type!r}) is not a payload-bearing "
            "entry. Only snapshot and routing-cluster entries support revert; use DELETE "
            "for delta entries.",
        )

    if entry.evicted or not pre_b64:
        raise HTTPException(
            410,
            detail=f"Snapshot for feature {index} ({label!r}) was evicted to save space and is no longer revertable.",
        )

    try:
        restored = design_state.decode_design_snapshot(pre_b64)
    except Exception as e:  # pragma: no cover - defensive
        raise HTTPException(
            500, detail=f"Failed to decode snapshot for feature {index}: {e}"
        )

    # Keep only entries strictly before this one — see truncation rationale above.
    truncated_log = log[:index]
    restored = restored.copy_with(feature_log=truncated_log, feature_log_cursor=-1)

    design_state.set_design(restored)
    report = validate_design(restored)
    return _design_response_with_geometry(restored, report)


def _revert_before_routing_child(
    design: "Design", log: list, index: int, entry, child_index: int
) -> dict:
    """Revert the design to the state just BEFORE ``entry.children[child_index]``
    of the Fine Routing cluster at log ``index``.

    Truncates the log to [0..index-1] plus the cluster holding only
    children[0..child_index-1] (post-state re-encoded). ``child_index == 0``
    drops the whole cluster (identical to a full-cluster revert). The pre-revert
    design is pushed to the undo stack.

    Caller guarantees ``entry`` is a routing-cluster.
    """
    from backend.core.validator import validate_design

    if entry.evicted or not entry.pre_state_gz_b64:
        raise HTTPException(
            410,
            detail=f"Fine Routing cluster {index} was evicted to save space and is no longer revertable.",
        )
    n_children = len(entry.children)
    if child_index < 0 or child_index >= n_children:
        raise HTTPException(
            400,
            detail=f"sub_index {child_index} out of range (cluster has {n_children} sub-steps).",
        )

    # Reconstruct the state just before child `child_index` by applying the
    # recorded diffs of children[0..child_index-1] forward (any op type; legacy
    # children fall back to replay). 410/422 raised inside on eviction/legacy.
    restored = _state_at_child_boundary(entry, child_index)

    if child_index == 0:
        # Reverting before the first child drops the entire cluster.
        truncated_log = log[:index]
    else:
        # Keep the cluster holding children[0..child_index-1] (their diffs intact)
        # and re-encode its post-state to the reconstructed boundary.
        post_b64, post_size = design_state.encode_design_snapshot(restored)
        kept_cluster = entry.model_copy(
            update={
                "children": list(entry.children[:child_index]),
                "post_state_gz_b64": post_b64,
                "post_state_size_bytes": post_size,
            }
        )
        truncated_log = log[:index] + [kept_cluster]

    restored = restored.copy_with(
        feature_log=truncated_log,
        feature_log_cursor=-1,
        feature_log_sub_cursor=None,
    )
    design_state.set_design(restored)
    report = validate_design(restored)
    return _design_response_with_geometry(restored, report)


def _rebase_joints_to_cts(design: "Design", new_cts: list) -> list:
    """Return ``design.cluster_joints`` unchanged.

    Joints now store their axes in the cluster's LOCAL frame
    (``local_axis_origin`` / ``local_axis_direction``); world-space is
    derived lazily from the current ``cluster_transforms[id]``. So when
    cluster transforms change (e.g. feature-log seek to identity), there
    is nothing to rebase — the joint storage is invariant under cluster
    transform changes.

    Function kept as a no-op so existing call sites (feature-log seek
    helpers) don't need to be touched right now; the inline call sites
    can be deleted in a follow-up cleanup.
    """
    return list(design.cluster_joints)


def _replay_minor_op(design: Design, op_subtype: str, params: dict) -> Design:
    """Replay one minor mutation against ``design`` and return the new design.

    Used by mid-cluster slider seek: when seeking to ``(position=K,
    sub_position=j)``, we hydrate the cluster's pre-state and then replay
    ``children[0..j]`` in order via this dispatcher.

    Each branch validates ``params`` against the original request model and
    calls the same ``_build_<op>`` pure builder used by the live endpoint.
    Raises ``NotImplementedError`` for subtypes whose builders haven't been
    extracted yet — the caller (``_seek_snapshot_base``) catches this and
    falls back to cluster post-state (no granular mid-cluster seek for those
    subtypes; deferred to v2).
    Raises ``HTTPException`` for genuine replay failures (target removed,
    invalid params).
    """
    if op_subtype == "nick":
        return _build_nick(design, NickRequest.model_validate(params))
    if op_subtype == "nick-batch":
        return _build_nick_batch(design, NickBatchRequest.model_validate(params))
    if op_subtype == "crossover-place":
        d, _x, _ligated = _build_place_crossover(
            design, PlaceCrossoverRequest.model_validate(params)
        )
        return d
    if op_subtype == "crossover-place-batch":
        d, _xs, _skipped = _build_place_crossover_batch(
            design, PlaceCrossoverBatchRequest.model_validate(params)
        )
        return d
    if op_subtype == "strand-end-resize":
        return _build_strand_end_resize(
            design, StrandEndResizeRequest.model_validate(params)
        )
    if op_subtype == "domain-shift":
        return _build_domain_shift(design, DomainShiftRequest.model_validate(params))
    if op_subtype == "strand-delete":
        return _build_delete_strand(design, params["strand_id"])
    if op_subtype == "strand-delete-batch":
        return _build_delete_strands_batch(
            design, StrandBatchDeleteRequest.model_validate(params)
        )
    if op_subtype == "domain-delete":
        return _build_delete_domain(design, params["strand_id"], params["domain_index"])
    if op_subtype == "helix-delete":
        out = design.model_copy(deep=True)
        idx = next(
            (i for i, h in enumerate(out.helices) if h.id == params["helix_id"]), None
        )
        if idx is None:
            raise HTTPException(
                404, detail=f"Helix {params['helix_id']!r} not found at replay."
            )
        out.helices.pop(idx)
        return out
    if op_subtype == "crossover-delete":
        cid = params["crossover_id"]
        xover = next((x for x in design.crossovers if x.id == cid), None)
        if xover is None:
            raise HTTPException(404, detail=f"Crossover {cid!r} missing at replay.")
        new_strands = _desplice_strands_for_crossover(
            design, xover.half_a, xover.half_b
        )
        out = design.model_copy(deep=True)
        out.crossovers = [x for x in out.crossovers if x.id != cid]
        out.strands = new_strands
        return out
    if op_subtype in ("joint-place", "joint-update", "joint-delete"):
        # Builders live in routes_cluster_joints.py (extracted). Import them
        # function-locally: that module imports _design_response back from this
        # one, so a top-level import would be circular.
        from backend.api.routes_cluster_joints import (
            _build_add_joint,
            _build_update_joint,
            _build_delete_joint,
        )

        if op_subtype == "joint-place":
            return _build_add_joint(design, params)
        if op_subtype == "joint-update":
            return _build_update_joint(design, params)
        return _build_delete_joint(design, params)

    # Subtype recognized but builder not yet extracted; treat as v2-deferred.
    # _seek_snapshot_base catches this and falls back to cluster post-state.
    raise NotImplementedError(
        f"Mid-cluster replay for op_subtype {op_subtype!r} is not implemented in v1. "
        "Falling back to cluster post-state."
    )


def _topology_substitute(design: Design, snap_design: Design) -> Design:
    """Substitute topology-bearing fields from ``snap_design`` into ``design``,
    leaving deformations/cluster_transforms to the delta-replay logic.

    ``overhangs`` is topology (each overhang owns a helix + strands), so its
    *membership* must come from the snapshot — seeking before an overhang-extrude
    has to drop that overhang, not just hide its helix/strands. The downstream
    seek logic only re-applies overhang *rotations* (a display-layer delta) onto
    whatever overhangs the snapshot restored; it never adds/removes them, so
    without restoring the list here a back-seek (or seek-to-empty) leaves a
    dangling ``overhangs`` entry whose helix/strands are already gone. That stale
    entry also poisons ``design_build_fingerprint`` (overhangs are in it), which is
    why a job-roll's seeked state failed to match the run-state fingerprint and the
    out-of-date flag never cleared. The snapshot bakes each overhang's rotation at
    op time (identity for a fresh extrude); the rotation delta-replay then overwrites
    it for any overhang with a rotation op in the active window, so this is safe.

    ``cluster_joints`` is restored for the same reason: a joint placement is a
    ``joint-place`` minor op snapshotted in its routing-cluster's pre/post state, so
    its *membership* must come from the snapshot — seeking before a joint's creation
    has to drop it, not leave it dangling (the prior ``_rebase_joints_to_cts`` no-op
    left joints present at every seek position, including the empty state). Joints
    store their axis in the cluster's LOCAL frame, so they are invariant under the
    cluster-transform delta-replay that runs afterwards — restoring the snapshot's
    list here is safe and complete (world axes are re-derived lazily from whatever
    ``cluster_transforms`` the delta logic lands on).

    ``flexible_segment_marks`` (+ the derived ``flexible_connections``) are restored on
    the same principle: a mark is added by a ``flexible-segment-mark`` snapshot op with
    no delta-replay path, so its *membership* must come from the snapshot — seeking
    before the mark has to drop it, not leave the ssDNA run rendering flexible. The
    connection cache is restored alongside its marks so the two stay consistent at every
    seek position.
    """
    return design.copy_with(
        helices=snap_design.helices,
        strands=snap_design.strands,
        crossovers=snap_design.crossovers,
        overhangs=snap_design.overhangs,
        overhang_connections=snap_design.overhang_connections,
        extensions=snap_design.extensions,
        photoproduct_junctions=snap_design.photoproduct_junctions,
        forced_ligations=snap_design.forced_ligations,
        cluster_joints=snap_design.cluster_joints,
        flexible_segment_marks=snap_design.flexible_segment_marks,
        flexible_connections=snap_design.flexible_connections,
    )


def _rebuild_deformed_continuations(design: Design) -> Design:
    """Re-run every ``extrude-deformed-continuation`` feature so its baked geometry
    reflects the CURRENT deformation set.

    Call this after a bend/twist is DELETED or EDITED. A deformed continuation
    (a primitive appended onto a BENT face) bakes the deformed cross-section frame
    into its new helices, so removing the upstream bend would otherwise leave the
    appended segment dangling at the old bent position. This forward-replays the
    log from the first deformed-continuation entry, threading a base design forward:

      * deformation deltas → folded into the evolving deformation overlay so each
        continuation's frame is recomputed against the right bends/twists;
      * deformed-continuation snapshots → re-run via the live builder (which now
        recomputes the frame from ``source_bp``), re-placing the segment and
        rewriting the entry's baked pre/post snapshots;
      * other replayable snapshots (extrude-segment/continuation, overhang-extrude)
        → re-run so segments stacked on top of a re-placed continuation follow it;
      * cluster_op / overhang_rotation deltas → skipped here (they're geometric
        overlays re-applied by the seek logic, not topology);
      * non-replayable snapshots (auto-*, circle-segment) → accept their baked
        post-state and continue (best-effort; they don't bake a deformed frame).

    Legacy continuations whose entry has no ``source_bp`` can't recompute a frame,
    so they re-run with their baked frame (no re-placement) — graceful degradation.

    Only the topology-bearing fields are swapped back into ``design``; its
    deformation / cluster / overhang overlays and cursor are preserved.
    """
    from backend.core.models import SnapshotLogEntry as _SnapshotLogEntry

    log = list(design.feature_log)
    dc_idxs = [
        i
        for i, e in enumerate(log)
        if isinstance(e, _SnapshotLogEntry)
        and e.op_kind == "extrude-deformed-continuation"
        and not e.evicted
        and e.design_snapshot_gz_b64
    ]
    if not dc_idxs:
        return design

    first = dc_idxs[0]
    # Base topology = the first continuation's stored PRE-state (base helices are
    # canonical; the bend was only ever an overlay). Override its deformation
    # overlay with the CURRENT active set up to that point so frames recompute
    # against the surviving bends/twists.
    state = design_state.decode_design_snapshot(log[first].design_snapshot_gz_b64)
    defs_before = [
        e.op_snapshot
        for e in log[:first]
        if e.feature_type == "deformation" and e.op_snapshot is not None
    ]
    state = state.copy_with(deformations=defs_before)

    new_log = list(log)
    for i in range(first, len(log)):
        e = log[i]
        if e.feature_type == "deformation":
            if e.op_snapshot is not None:
                state = state.copy_with(
                    deformations=list(state.deformations) + [e.op_snapshot]
                )
            continue
        if not isinstance(e, _SnapshotLogEntry):
            continue  # cluster_op / overhang_rotation deltas — overlays, not topology
        if e.evicted or not e.post_state_gz_b64:
            continue
        pre_b64, pre_size = design_state.encode_design_snapshot(state)
        try:
            new_post = _edit_dispatch_run(e.op_kind, state, e.params)
        except (HTTPException, ValidationError, ValueError):
            # Non-replayable (auto-*, circle-segment, schema drift) — keep its baked
            # post-state as the base for whatever follows and move on.
            state = _topology_substitute(
                state, design_state.decode_design_snapshot(e.post_state_gz_b64)
            )
            continue
        post_b64, post_size = design_state.encode_design_snapshot(new_post)
        new_log[i] = e.model_copy(
            update={
                "design_snapshot_gz_b64": pre_b64,
                "snapshot_size_bytes": pre_size,
                "post_state_gz_b64": post_b64,
                "post_state_size_bytes": post_size,
            }
        )
        state = new_post

    return _topology_substitute(design, state).copy_with(feature_log=new_log)


def _seek_snapshot_base(
    design: Design, position: int, sub_position: int | None = None
) -> Design:
    """Choose the design whose strand/helix/crossover topology represents the
    state at the requested feature-log position.

    Slider-seek is destructive — each call writes the result back to the
    active design — so we cannot rely on the live ``design.strands`` to
    represent the latest state after a back-seek. Instead we re-derive the
    topology from the appropriate snapshot every time.

    Strategy:
      * Find the largest index ``sj`` of a non-evicted PAYLOAD-BEARING entry
        (SnapshotLogEntry OR RoutingClusterLogEntry) with ``sj <= position``.
        - If found and the entry is a SnapshotLogEntry: substitute
          snapshot ``sj``'s POST-state (the state immediately after op
          ``sj`` ran).
        - If found and the entry is a RoutingClusterLogEntry:
          * ``sj < position`` OR ``sub_position is None`` → use cluster's
            POST-state (cluster fully active).
          * ``sj == position`` AND ``sub_position == -2`` → use cluster's
            PRE-state (seeking to before the cluster started).
          * ``sj == position`` AND ``0 <= sub_position < len(children)`` →
            use cluster's PRE-state, then replay children[0..sub_position]
            via :func:`_replay_minor_op`.
      * If no such ``sj`` exists but at least one later payload entry does:
        ``position`` precedes every payload entry — substitute the FIRST
        payload entry's PRE-state (the F0 baseline).
      * If the log has no payload-bearing entries at all, return ``design``
        unchanged (delta-only history; live topology is correct).

    Only topology-bearing fields are substituted; deformations,
    cluster_transforms, overhangs etc. are left to the existing delta-replay
    logic that runs after this helper.

    LIMITATION: assumes strands/helices/crossovers are mutated only by
    snapshot-emitting auto-ops or routing-cluster minor ops. The cluster
    children's replay relies on order-preserving, idempotent application
    via :func:`_replay_minor_op`; if a mid-cluster replay fails the helper
    surfaces the partial state with the failed sub_index logged separately.
    """
    from backend.core.models import (
        RoutingClusterLogEntry as _RoutingClusterLogEntry,
        SnapshotLogEntry as _SnapshotLogEntry,
    )

    log = list(design.feature_log)

    def _has_pre(e: object) -> bool:
        if isinstance(e, _SnapshotLogEntry):
            return not e.evicted and bool(e.design_snapshot_gz_b64)
        if isinstance(e, _RoutingClusterLogEntry):
            return not e.evicted and bool(e.pre_state_gz_b64)
        return False

    def _has_post(e: object) -> bool:
        if isinstance(e, _SnapshotLogEntry):
            return not e.evicted and bool(e.post_state_gz_b64)
        if isinstance(e, _RoutingClusterLogEntry):
            return not e.evicted and bool(e.post_state_gz_b64)
        return False

    pre_indices = [i for i, e in enumerate(log) if _has_pre(e)]
    post_indices = [i for i, e in enumerate(log) if _has_post(e)]
    if not pre_indices and not post_indices:
        return design

    # Determine the effective position for payload lookup.
    # -1 / overshoot ⇒ end-of-log.
    if position == -1 or position >= len(log) - 1:
        eff_position = len(log) - 1
    elif position == -2:
        eff_position = -1  # before everything
    else:
        eff_position = position

    # Largest non-evicted POST index <= eff_position.
    sj: int | None = None
    for s_idx in reversed(post_indices):
        if s_idx <= eff_position:
            sj = s_idx
            break

    if sj is None:
        # eff_position precedes every payload entry — fall back to the first
        # payload entry's PRE-state (= F0 baseline).
        if not pre_indices:
            return design
        first = log[pre_indices[0]]
        snap_design = design_state.decode_design_snapshot(
            first.design_snapshot_gz_b64
            if isinstance(first, _SnapshotLogEntry)
            else first.pre_state_gz_b64
        )
        return _topology_substitute(design, snap_design)

    payload_entry = log[sj]

    # Cluster + sub_position handling: only honored when seeking exactly INTO
    # the cluster (sj == eff_position) AND sub_position is specified.
    if (
        isinstance(payload_entry, _RoutingClusterLogEntry)
        and sj == eff_position
        and sub_position is not None
    ):
        # -2 = pre-cluster (no children active)
        if sub_position == -2 or sub_position < -1:
            snap_design = design_state.decode_design_snapshot(
                payload_entry.pre_state_gz_b64
            )
            return _topology_substitute(design, snap_design)
        # 0..M-1 = first sub_position+1 children active
        n_children = len(payload_entry.children)
        if 0 <= sub_position < n_children:
            from backend.core.design_diff import apply_child_diff_forward, is_diff_child

            try:
                snap_design = design_state.decode_design_snapshot(
                    payload_entry.pre_state_gz_b64
                )
                for child in payload_entry.children[: sub_position + 1]:
                    if is_diff_child(child):
                        # Diff-based: works for any op type, no replay needed.
                        snap_design, _w = apply_child_diff_forward(
                            snap_design,
                            child.diff_added_b64,
                            child.diff_removed_b64,
                            child.diff_modified_b64,
                        )
                    else:
                        snap_design = _replay_minor_op(
                            snap_design, child.op_subtype, child.params
                        )
                return _topology_substitute(design, snap_design)
            except NotImplementedError:
                # Legacy child with a non-replayable op AND no diff. Gracefully
                # fall back to the cluster's post-state (whole cluster active —
                # same as sub_position=None).
                pass
        # sub_position == -1 or out-of-range → fall through to post-state.

    # Default: use POST-state of the chosen payload entry.
    if isinstance(payload_entry, _SnapshotLogEntry):
        snap_design = design_state.decode_design_snapshot(
            payload_entry.post_state_gz_b64
        )
    else:
        snap_design = design_state.decode_design_snapshot(
            payload_entry.post_state_gz_b64
        )
    return _topology_substitute(design, snap_design)


def _seek_feature_log(
    design: Design, position: int, sub_position: int | None = None
) -> Design:
    """Replay feature_log[0..position] to compute effective deformations + cluster states.

    position = -1 means 'seek to end' (all entries active).
    sub_position is honored only when ``position`` indexes a
    RoutingClusterLogEntry; see :func:`_seek_snapshot_base` for the full rules.

    Deformations are reconstructed from op_snapshot (if present) or by looking up
    deformation_id in design.deformations (backward compat for old log entries).
    Cluster transforms are set to the last cluster_op state in the active window,
    or identity if no op exists for a cluster in the active range.

    Snapshot + routing-cluster entries are handled by :func:`_seek_snapshot_base`,
    which substitutes the topology-bearing fields (helices/strands/crossovers)
    so that seeking past an auto-op or mid-cluster rolls back the topology too
    — not just deformations and cluster states.
    """
    log = list(design.feature_log)

    # Substitute topology to match the requested position. Subsequent delta
    # logic operates on this topology-corrected base, so the existing
    # rebuild-from-log logic Just Works for snapshot-bearing histories.
    design = _seek_snapshot_base(design, position, sub_position)
    log = list(design.feature_log)

    if position == -2:
        # Seeking to empty state — no features active.
        # Reset cluster transforms for any cluster that has ops in the log.
        clusters_with_any_op = {
            e.cluster_id for e in log if e.feature_type == "cluster_op"
        }
        new_cts = [
            ct.model_copy(
                update={
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                }
            )
            if ct.id in clusters_with_any_op
            else ct
            for ct in design.cluster_transforms
        ]
        new_joints = _rebase_joints_to_cts(design, new_cts)
        # Reset overhang rotations + sub-domain (theta, phi) for any
        # overhang that has ops in the log.
        ovhgs_with_any_op: set = set()
        sd_pairs_with_any_op: set[tuple[str, str]] = set()
        for e in log:
            if e.feature_type != "overhang_rotation":
                continue
            sd_ids = e.sub_domain_ids
            for i, oid in enumerate(e.overhang_ids):
                sd_id_i = sd_ids[i] if i < len(sd_ids) else None
                if sd_id_i is None:
                    ovhgs_with_any_op.add(oid)
                else:
                    sd_pairs_with_any_op.add((oid, sd_id_i))
        new_overhangs = []
        for ovhg in design.overhangs:
            update: dict = {}
            if ovhg.id in ovhgs_with_any_op:
                update["rotation"] = [0.0, 0.0, 0.0, 1.0]
            sds_touched = {
                sd_id for (oid, sd_id) in sd_pairs_with_any_op if oid == ovhg.id
            }
            if sds_touched:
                update["sub_domains"] = [
                    sd.model_copy(
                        update={
                            "rotation_theta_deg": 0.0,
                            "rotation_phi_deg": 0.0,
                        }
                    )
                    if sd.id in sds_touched
                    else sd
                    for sd in ovhg.sub_domains
                ]
            new_overhangs.append(ovhg.model_copy(update=update) if update else ovhg)
        return design.copy_with(
            deformations=[],
            cluster_transforms=new_cts,
            cluster_joints=new_joints,
            overhangs=new_overhangs,
            feature_log_cursor=-2,
            feature_log_sub_cursor=None,
        )

    if not log:
        return design.copy_with(feature_log_cursor=-1, feature_log_sub_cursor=None)

    # When sub_position is provided, the cursor MUST be the explicit cluster
    # index (not -1 / end-of-log). Otherwise the slider thumb can't reflect
    # mid-cluster state and snaps to whichever notch happens to be at the
    # end of the array (which, for an expanded cluster, is the LAST
    # sub-notch — exactly the user-reported snap bug).
    if sub_position is not None and 0 <= position <= len(log) - 1:
        cursor_val = position
        active = log[: position + 1]
    elif position == -1 or position >= len(log) - 1:
        # Seeking to end — restore all deformations from log and latest cluster states.
        cursor_val = -1
        active = log
    else:
        cursor_val = position
        active = log[: position + 1]

    # Rebuild deformation list from active entries.
    deform_map = {d.id: d for d in design.deformations}
    new_deformations = []
    for entry in active:
        if entry.feature_type == "deformation":
            op = entry.op_snapshot or deform_map.get(entry.deformation_id)
            if op:
                new_deformations.append(op)

    # Rebuild cluster states: use the last cluster_op per cluster in the active window.
    cluster_last: dict[str, ClusterOpLogEntry] = {}
    for entry in active:
        if entry.feature_type == "cluster_op":
            cluster_last[entry.cluster_id] = entry

    # Collect cluster IDs that have ANY cluster_op anywhere in the full log.
    clusters_with_ops = {e.cluster_id for e in log if e.feature_type == "cluster_op"}

    new_cts = []
    for ct in design.cluster_transforms:
        if ct.id in cluster_last:
            op = cluster_last[ct.id]
            ct = ct.model_copy(
                update={
                    "translation": op.translation,
                    "rotation": op.rotation,
                    "pivot": op.pivot,
                }
            )
        elif ct.id in clusters_with_ops:
            # Cluster has ops in the log but none in the active window → identity.
            ct = ct.model_copy(
                update={
                    "translation": [0.0, 0.0, 0.0],
                    "rotation": [0.0, 0.0, 0.0, 1.0],
                }
            )
        new_cts.append(ct)

    new_joints = _rebase_joints_to_cts(design, new_cts)

    # Rebuild overhang rotations: last rotation per overhang_id in active window.
    # Phase 4 — also track per-sub-domain (theta, phi) state.
    ovhg_last_rot: dict = {}
    sd_last_angles: dict[tuple[str, str], tuple[float, float]] = {}
    ovhgs_with_ops: set = set()
    sd_pairs_with_ops: set[tuple[str, str]] = set()
    for entry in active:
        if entry.feature_type != "overhang_rotation":
            continue
        sd_ids = entry.sub_domain_ids
        thetas = entry.sub_domain_thetas_deg
        phis = entry.sub_domain_phis_deg
        for i, oid in enumerate(entry.overhang_ids):
            sd_id_i = sd_ids[i] if i < len(sd_ids) else None
            if sd_id_i is None:
                ovhg_last_rot[oid] = entry.rotations[i]
            else:
                sd_last_angles[(oid, sd_id_i)] = (float(thetas[i]), float(phis[i]))
    for e in log:
        if e.feature_type != "overhang_rotation":
            continue
        sd_ids = e.sub_domain_ids
        for i, oid in enumerate(e.overhang_ids):
            sd_id_i = sd_ids[i] if i < len(sd_ids) else None
            if sd_id_i is None:
                ovhgs_with_ops.add(oid)
            else:
                sd_pairs_with_ops.add((oid, sd_id_i))

    new_overhangs = []
    for ovhg in design.overhangs:
        if ovhg.id in ovhg_last_rot:
            ovhg = ovhg.model_copy(update={"rotation": ovhg_last_rot[ovhg.id]})
        elif ovhg.id in ovhgs_with_ops:
            ovhg = ovhg.model_copy(update={"rotation": [0.0, 0.0, 0.0, 1.0]})

        sub_doms_touched = [
            sd_id for (oid, sd_id) in sd_pairs_with_ops if oid == ovhg.id
        ]
        if sub_doms_touched:
            new_sds = []
            for sd in ovhg.sub_domains:
                key = (ovhg.id, sd.id)
                if key in sd_last_angles:
                    theta, phi = sd_last_angles[key]
                    sd = sd.model_copy(
                        update={
                            "rotation_theta_deg": theta,
                            "rotation_phi_deg": phi,
                        }
                    )
                elif sd.id in sub_doms_touched:
                    sd = sd.model_copy(
                        update={
                            "rotation_theta_deg": 0.0,
                            "rotation_phi_deg": 0.0,
                        }
                    )
                new_sds.append(sd)
            ovhg = ovhg.model_copy(update={"sub_domains": new_sds})

        new_overhangs.append(ovhg)

    return design.copy_with(
        deformations=new_deformations,
        cluster_transforms=new_cts,
        cluster_joints=new_joints,
        overhangs=new_overhangs,
        feature_log_cursor=cursor_val,
        feature_log_sub_cursor=sub_position,
    )


# ── Feature-log rollback helper ───────────────────────────────────────────────
# Used by the feature-log "revert last feature" path (NOT by any deformation
# route). It lived under the old "Deformation endpoints" banner only by
# adjacency; the bend/twist routes themselves were extracted to
# ``routes_deformation.py`` and their shared param/cluster-scope logic to
# ``backend/core/deformation.py``.


def _rollback_last_feature(design: Design) -> Design:
    """Remove the last non-checkpoint entry from feature_log and undo its effect.

    Checkpoints are removed only via delete_configuration; this function skips them.
    Returns the original design unchanged if there is nothing to roll back.
    """
    log = list(design.feature_log)
    idx = next(
        (i for i in range(len(log) - 1, -1, -1) if log[i].feature_type != "checkpoint"),
        None,
    )
    if idx is None:
        return design

    entry = log[idx]
    new_log = [e for e in log if e.id != entry.id]

    if entry.feature_type == "deformation":
        new_deformations = [
            d for d in design.deformations if d.id != entry.deformation_id
        ]
        return design.copy_with(deformations=new_deformations, feature_log=new_log)

    if entry.feature_type == "cluster_op":
        # Restore the previous absolute state of this cluster, or identity if none.
        prev = next(
            (
                e
                for e in reversed(log[:idx])
                if e.feature_type == "cluster_op" and e.cluster_id == entry.cluster_id
            ),
            None,
        )
        new_cts = []
        for ct in design.cluster_transforms:
            if ct.id == entry.cluster_id:
                if prev:
                    ct = ct.model_copy(
                        update={
                            "translation": prev.translation,
                            "rotation": prev.rotation,
                            "pivot": prev.pivot,
                        }
                    )
                else:
                    ct = ct.model_copy(
                        update={
                            "translation": [0.0, 0.0, 0.0],
                            "rotation": [0.0, 0.0, 0.0, 1.0],
                            "pivot": ct.pivot,
                        }
                    )
            new_cts.append(ct)
        return design.copy_with(cluster_transforms=new_cts, feature_log=new_log)

    if entry.feature_type == "overhang_rotation":
        # Restore the previous rotation per overhang AND per sub-domain.
        # Splits the entry's per-index slots into:
        #   - whole-overhang slots (sub_domain_ids[i] is None)
        #   - sub-domain slots     (sub_domain_ids[i] is UUID)
        # For each one, walk backwards through the log to find the
        # previous value, defaulting to identity / 0,0 if none.
        sd_ids_entry = entry.sub_domain_ids
        whole_ovhgs_in_entry: set[str] = set()
        sd_pairs_in_entry: set[tuple[str, str]] = set()
        for i, oid in enumerate(entry.overhang_ids):
            sd_i = sd_ids_entry[i] if i < len(sd_ids_entry) else None
            if sd_i is None:
                whole_ovhgs_in_entry.add(oid)
            else:
                sd_pairs_in_entry.add((oid, sd_i))

        new_overhangs = []
        for ovhg in design.overhangs:
            updates: dict = {}
            if ovhg.id in whole_ovhgs_in_entry:
                prev_rot = None
                for prev_entry in reversed(log[:idx]):
                    if prev_entry.feature_type != "overhang_rotation":
                        continue
                    if ovhg.id not in prev_entry.overhang_ids:
                        continue
                    prev_sd_ids = prev_entry.sub_domain_ids
                    # Find the most recent WHOLE-overhang slot for this ovhg.
                    for pi, poid in enumerate(prev_entry.overhang_ids):
                        if poid != ovhg.id:
                            continue
                        sd_pi = prev_sd_ids[pi] if pi < len(prev_sd_ids) else None
                        if sd_pi is None:
                            prev_rot = prev_entry.rotations[pi]
                            break
                    if prev_rot is not None:
                        break
                updates["rotation"] = (
                    prev_rot if prev_rot is not None else [0.0, 0.0, 0.0, 1.0]
                )

            sd_touched = {sd_id for (oid, sd_id) in sd_pairs_in_entry if oid == ovhg.id}
            if sd_touched:
                new_sds = []
                for sd in ovhg.sub_domains:
                    if sd.id not in sd_touched:
                        new_sds.append(sd)
                        continue
                    prev_theta: Optional[float] = None
                    prev_phi: Optional[float] = None
                    for prev_entry in reversed(log[:idx]):
                        if prev_entry.feature_type != "overhang_rotation":
                            continue
                        prev_sd_ids = prev_entry.sub_domain_ids
                        prev_thetas = prev_entry.sub_domain_thetas_deg
                        prev_phis = prev_entry.sub_domain_phis_deg
                        for pi, poid in enumerate(prev_entry.overhang_ids):
                            if poid != ovhg.id:
                                continue
                            sd_pi = prev_sd_ids[pi] if pi < len(prev_sd_ids) else None
                            if sd_pi == sd.id:
                                prev_theta = float(prev_thetas[pi])
                                prev_phi = float(prev_phis[pi])
                                break
                        if prev_theta is not None:
                            break
                    new_sds.append(
                        sd.model_copy(
                            update={
                                "rotation_theta_deg": prev_theta
                                if prev_theta is not None
                                else 0.0,
                                "rotation_phi_deg": prev_phi
                                if prev_phi is not None
                                else 0.0,
                            }
                        )
                    )
                updates["sub_domains"] = new_sds

            new_overhangs.append(ovhg.model_copy(update=updates) if updates else ovhg)
        return design.copy_with(overhangs=new_overhangs, feature_log=new_log)

    # Unknown type — just remove from log with no other side-effect.
    return design.copy_with(feature_log=new_log)


# ── Camera poses ─────────────────────────────────────────────────────────────
# Camera-pose route handlers were extracted to ``routes_camera_poses.py``
# in Refactor 13-B (same pattern as 10-F loop-skip extraction).


# ── Animations ───────────────────────────────────────────────────────────────
# Animation + keyframe route handlers were extracted to ``routes_animations.py``
# (same pattern as 13-B camera poses / 10-F loop-skip extraction).
#
# ``BindingDisplayPoseBody`` is retained here, NOT in the animations router,
# because it is the request model for two non-animation handlers that stay in
# this file: ``patch_connection_display_pose`` and ``patch_binding_display_pose``.


class BindingDisplayPoseBody(BaseModel):
    """Annotation-only: authored hinge angles for the animation player.

    Sets ONLY the display-pose fields. Never touches `bound`, `target_joint_id`,
    `locked_angle_deg`, joint min/max, or `prior_driven_topology`.
    """

    unbound_angle_deg: Optional[float] = None
    bound_angle_deg: Optional[float] = None


# ── Cluster rigid transforms → routes_clusters.py ─────────────────────────────
# POST/PATCH/DELETE /design/cluster moved to backend/api/routes_clusters.py
# (Refactor #28). The shared _ensure_default_cluster + _design_response helpers
# stay here and are imported back by that router.


# ── Cluster drag / undo-stack snapshot utilities ─────────────────────────────
#
# Flexible ssDNA segment routes (/design/flexible-*) were extracted to
# backend/api/routes_flexible_segments.py (carve-router Refactor #27). The two
# generic undo-stack helpers below stayed — they are not flexible-specific.


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
    design_state.get_or_404()
    design_state.snapshot()
    return {}


# ── ds-linker bridge refresh (Plan B companion) ───────────────────────────────


class RefreshBridgesBody(BaseModel):
    """Cluster IDs that just moved. The endpoint re-emits bridge nucs for every
    ds OverhangConnection whose anchor sits on a helix in any of those clusters.
    Pass an empty list (or omit) to refresh ALL bridges."""

    cluster_ids: List[str] = []


@router.post("/design/refresh-bridges", status_code=200)
def refresh_bridges(body: RefreshBridgesBody) -> dict:
    """Re-emit ds-linker bridge nucs without recomputing the full geometry.

    Plan B's cluster-commit fast path skips backend geometry refresh entirely.
    Bridge nucs (on synthetic ``__lnk__<conn>`` helices) are *derived* from
    live anchor positions in :func:`_emit_bridge_nucs`, so they go stale when
    one cluster moves and the other doesn't. This endpoint runs only the
    minimum work needed to recompute them — partial geometry for the OH
    helices involved in affected ds connections, then `_emit_bridge_nucs` —
    and returns just the bridge nucs.

    Response shape: ``{"bridge_nucs": [<nuc dict>, ...]}``. The frontend
    locates each existing bridge entry in its renderer state by
    ``(helix_id, bp_index, direction)`` and patches positions in place.
    """
    design = design_state.get_or_404()
    if not design.overhang_connections:
        return {"bridge_nucs": []}

    ds_conns = [c for c in design.overhang_connections if c.linker_type == "ds"]
    if not ds_conns:
        return {"bridge_nucs": []}

    # Filter to connections whose anchors sit on helices in the moved clusters.
    # An empty cluster_ids list is the explicit "refresh all" signal; a non-empty
    # list filters strictly — including the "no clusters matched" case, which
    # should yield zero affected connections (not silently refresh everything).
    affected_conns = ds_conns
    if body.cluster_ids:
        moved_helix_ids: set[str] = set()
        for ct in design.cluster_transforms:
            if ct.id in body.cluster_ids:
                moved_helix_ids.update(ct.helix_ids)
        ovhg_helix = {o.id: o.helix_id for o in design.overhangs}
        affected_conns = [
            c
            for c in ds_conns
            if ovhg_helix.get(c.overhang_a_id) in moved_helix_ids
            or ovhg_helix.get(c.overhang_b_id) in moved_helix_ids
        ]
        if not affected_conns:
            return {"bridge_nucs": []}

    # Determine the OH helix subset we need to compute geometry for.
    # _emit_bridge_nucs reads anchor positions from already-emitted nucs on
    # those OH helices via nucs_by_ovhg + nucs_by_strand, so we must include
    # every OH helix that any affected connection's anchor sits on.
    ovhg_helix = {o.id: o.helix_id for o in design.overhangs}
    needed_helix_ids: set[str] = set()
    for c in affected_conns:
        ha = ovhg_helix.get(c.overhang_a_id)
        hb = ovhg_helix.get(c.overhang_b_id)
        if ha:
            needed_helix_ids.add(ha)
        if hb:
            needed_helix_ids.add(hb)
    if not needed_helix_ids:
        return {"bridge_nucs": []}

    # Run partial geometry → _emit_bridge_nucs → filter to bridge nucs only.
    full = _geometry_for_helices(design, frozenset(needed_helix_ids))
    bridge_nucs = [n for n in full if (n.get("helix_id") or "").startswith("__lnk__")]
    return {"bridge_nucs": bridge_nucs}


# ── Cluster joint routes → routes_cluster_joints.py ───────────────────────────
# (POST /design/cluster/{id}/joint, PATCH+DELETE /design/joint/{id} + their
#  _build_add/update/delete_joint builders lifted to routes_cluster_joints.py,
#  Refactor #29. _replay_minor_op imports the builders back function-locally.)


# NOTE: The 5 loop/skip endpoints (insert / twist / bend / limits / DELETE
# clear-range) were extracted to ``backend/api/routes_loop_skip.py`` in
# Refactor 10-F. They are still mounted under the same URLs via
# ``app.include_router(...)`` in ``backend/api/main.py``. The
# ``clear-all`` and ``apply-deformations`` loop/skip endpoints below
# remain in crud.py for now.


@router.post("/design/loop-skip/clear-all", status_code=200)
def clear_all_loop_skips_endpoint() -> dict:
    """Remove every loop/skip from every helix in the design.

    Useful for cleaning up stale modifications from older files before
    re-running Update Routing.
    """
    from backend.core.loop_skip_calculator import clear_all_loop_skips

    design = design_state.get_or_404()
    updated = clear_all_loop_skips(design)
    updated, report = design_state.replace_with_reconcile(updated)
    return _design_response(updated, report)


@router.post("/design/loop-skip/apply-deformations", status_code=200)
def apply_loop_skips_from_deformations() -> dict:
    """Apply all DeformationOps on the design as loop/skip topology modifications.

    For each DeformationOp:
      - twist → call twist_loop_skips with computed target_twist_deg
      - bend  → convert curvature_deg_per_bp to radius_nm and call bend_loop_skips

    All modifications are merged and applied atomically via apply_loop_skips.
    Pushes to undo history.

    Requires that the design has at least one crossover placed (crossovers break the
    bundle into 7-bp cells which are required for loop/skip placement).
    """
    from backend.core.loop_skip_calculator import (
        apply_loop_skips,
        bend_loop_skips,
        clear_all_loop_skips,
        sq_lattice_periodic_skips,
        twist_loop_skips,
        _bend_params_to_radius_nm,
        CELL_BP_DEFAULT,
    )
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import LatticeType

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

    # Wipe all existing loop/skips so recomputed mods start from a clean slate.
    # This also removes any orphaned marks at positions no longer covered by strands.
    design = clear_all_loop_skips(design)

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
            mods = twist_loop_skips(
                affected, plane_a, plane_b, target_deg, design=design
            )
        else:  # bend
            p = op.params
            # Geometric radius from κ (matches deformation.py: R = RISE / radians(κ)).
            radius_nm = _bend_params_to_radius_nm(p.curvature_deg_per_bp)
            if math.isinf(radius_nm):
                continue  # κ ≈ 0 → infinite radius, no bend
            mods = bend_loop_skips(
                affected, plane_a, plane_b, radius_nm, p.direction_deg, design=design
            )

        for hid, ls_list in mods.items():
            all_mods.setdefault(hid, []).extend(ls_list)

    if not all_mods:
        raise HTTPException(400, detail="No loop/skip modifications were produced.")

    # Relocate any auto-placed mark off a crossover / strand end / margin to the nearest free
    # interior bp (preserving each helix's net count → twist/bend magnitude unchanged).  The
    # realizers (twist_loop_skips / bend_loop_skips / sq_lattice_periodic_skips) place on an even
    # cell grid and don't self-enforce this; a deletion on a crossover breaks CanDo
    # (feedback_loopskip_no_crossover_ends).  Manual context-menu placement never hits this path.
    from backend.core.loop_skip_calculator import relocate_marks_off_forbidden

    all_mods = relocate_marks_off_forbidden(all_mods, design)
    if not all_mods:
        raise HTTPException(400, detail="No loop/skip modifications were produced.")

    n_helices = len(all_mods)
    n_marks = sum(len(ls) for ls in all_mods.values())
    label = f"Add loops/skips ({n_marks} mark{'s' if n_marks != 1 else ''} on {n_helices} helix{'es' if n_helices != 1 else ''})"
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind="apply-loop-skips",
        label=label,
        params={
            "helix_count": n_helices,
            "mark_count": n_marks,
            "sq_periodic": design.lattice_type == LatticeType.SQUARE,
            "deformation_count": len(design.deformations),
        },
        fn=lambda d: apply_loop_skips(d, all_mods),
    )
    response = _design_response(updated, report)
    response["loop_skips"] = {hid: len(ls) for hid, ls in all_mods.items()}
    return response


# (Plate layout + per-region representation-override CRUD — both display-only
#  metadata — lifted to backend/api/routes_display_metadata.py; Strand-extension
#  CRUD lifted to backend/api/routes_extensions.py.)


# ── Atomistic model + PDB/PSF export (Phase AA) ───────────────────────────────

# (On-screen display geometry — GET /design/atomistic, GET /design/surface,
#  POST /design/surface/region — lifted to backend/api/routes_display_geometry.py
#  (render-feed JSON for the Three.js renderer). The 3D-print surface exports
#  /design/export/stl and /design/export/3mf live in routes_export_3dprint.py:
#  render feed vs printable-file download is a different reason to change.)


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
    helix_lengths = [h.length_bp for h in design.helices]
    all_lo = min(helix_bp_starts) if helix_bp_starts else 0
    all_hi = (
        max(b + l - 1 for b, l in zip(helix_bp_starts, helix_lengths))
        if helix_bp_starts
        else 0
    )

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
            {
                "id": h.id,
                "bp_start": h.bp_start,
                "length_bp": h.length_bp,
                "axis_start_z": round(h.axis_start.z, 4),
                "axis_end_z": round(h.axis_end.z, 4),
            }
            for h in design.helices
        ],
    }
