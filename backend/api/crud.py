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
import copy
import gzip
import math
import os
import threading
import time as _time
import uuid as _uuid

import numpy as np
from contextlib import contextmanager
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import Response, ORJSONResponse
from pydantic import BaseModel, Field, ValidationError


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
            safe = name.replace(' ', '_').replace(',', '_').replace(';', '_')
            parts.append(f"{safe};dur={dur:.1f}")
        return ", ".join(parts)

    def attach(self, response):
        if self._steps:
            response.headers["Server-Timing"] = self.header_value()
        return response

from backend.api import state as design_state
from backend.core.geometry import (
    nucleotide_positions,
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
from backend.core.deformation import (
    _apply_ovhg_rotations_to_axes,
    apply_overhang_rotation_if_needed,
    deformed_frame_at_bp,
    deformed_helix_axes,
    deformed_nucleotide_arrays,
    effective_helix_for_geometry,
    helices_crossing_planes,
)
from backend.core.models import (
    AnimationKeyframe,
    BendParams,
    ClusterJoint,
    ClusterOpLogEntry,
    Crossover,
    DesignAnimation,
    DeformationLogEntry,
    DeformationOp,
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
    OverhangSpec,
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

# ── GROMACS background export job store ───────────────────────────────────────
# { job_id: { status: "running"|"done"|"error", result: bytes|None, error: str|None, name: str } }
_gromacs_jobs: dict[str, dict] = {}
_gromacs_jobs_lock = threading.Lock()


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
        # NOTE: do NOT skip LINKER strands. Their complement domain lives on a
        # real overhang helix and we need the geometry pipeline to associate
        # the nucleotides at those positions with the linker strand so they
        # render. The bridge domain lives on a __lnk__ helix that is skipped
        # in the helix iteration, so it produces no positions to look up.
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
    """Return un-deformed helix axes using stored axis_start/axis_end positions.

    We use the stored positions rather than re-deriving from grid_pos via
    _normalize_helix_for_grid, because that would ignore re-centering applied
    at import time (e.g. _recenter_design for scadnano/cadnano designs).
    """
    result = []
    for h in design.helices:
        result.append({
            "helix_id": h.id,
            "start":    [h.axis_start.x, h.axis_start.y, h.axis_start.z],
            "end":      [h.axis_end.x,   h.axis_end.y,   h.axis_end.z],
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

        helix = design.find_helix(dom.helix_id)
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
        if helix.id.startswith("__lnk__"):
            continue   # virtual linker helices have no real geometry
        arrs = deformed_nucleotide_arrays(helix, design)
        arrs = apply_overhang_rotation_if_needed(arrs, helix, design)
        _emit_arrs(arrs, arrs['helix_id'])

        # Render nucleotides outside the physical helix span (ss-scaffold loops).
        # These must go through the same deformation / cluster transform pipeline
        # so they follow bend / twist / translate / rotate ops.
        from backend.core.deformation import deform_extended_arrays
        norm_helix = None  # lazy — only normalise once if either side needs it

        lo_bp = min_domain_bp.get(helix.id, helix.bp_start)
        if lo_bp < helix.bp_start:
            norm_helix = effective_helix_for_geometry(helix, design)
            extra_arrs = nucleotide_positions_arrays_extended(norm_helix, lo_bp)
            extra_arrs = deform_extended_arrays(extra_arrs, helix, design, edge_bp=helix.bp_start)
            _emit_arrs(extra_arrs, helix.id)

        hi_bp = max_domain_bp.get(helix.id, helix.bp_start + helix.length_bp - 1)
        helix_hi = helix.bp_start + helix.length_bp   # first bp past helix right edge
        if hi_bp >= helix_hi:
            if norm_helix is None:
                norm_helix = effective_helix_for_geometry(helix, design)
            extra_arrs = nucleotide_positions_arrays_extended_right(norm_helix, hi_bp)
            extra_arrs = deform_extended_arrays(extra_arrs, helix, design, edge_bp=helix_hi - 1)
            _emit_arrs(extra_arrs, helix.id)

    # Emit bridge nucs for ds linkers AFTER the regular helix loop so they
    # can read the live OH/complement positions (cluster transforms applied)
    # to derive their axis. Without this pass the bridge tube is JS-only —
    # not selectable, no real geometry payload, no slabs/cones in standard
    # rendering paths.
    _emit_bridge_nucs(design, nuc_info, result)

    if full_mode:
        if design.extensions:
            result.extend(_strand_extension_geometry(design, nuc_pos_map))
    return result


def _emit_bridge_nucs(design: Design, nuc_info: dict, result: list[dict]) -> None:
    """For each ds OverhangConnection, append nuc dicts for the bridge
    domain to *result*. Bridge positions are derived from the live anchors
    on each side (complement nuc on the OH helix at the OH's `attach`-end
    bp), with the bridge axis offset off the chord so the boundary beads
    sit at native B-DNA radius (HELIX_RADIUS_NM) AND colocalize with their
    anchors when the relax-target chord is reached.

    No-op when the design has no ds linkers, when the linker strand or its
    bridge domain can't be resolved, or when the OH/complement nucs aren't
    in *result* yet (e.g. partial geometry that didn't compute the OH helix).
    """
    import numpy as _np
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.linker_relax import (
        _oh_attach_nuc, _comp_first, bridge_axis_geometry,
        _BDNA_TWIST_RAD, _MINOR_GROOVE_RAD, _BRIDGE_PHASE_OFFSET,
    )

    ds_conns = [c for c in design.overhang_connections if c.linker_type == "ds"]
    if not ds_conns:
        return

    # Index already-emitted nucs for fast anchor lookup.
    nucs_by_strand: dict[str, list[dict]] = {}
    nucs_by_ovhg:   dict[str, list[dict]] = {}
    for n in result:
        sid = n.get("strand_id")
        if sid:
            nucs_by_strand.setdefault(sid, []).append(n)
        oid = n.get("overhang_id")
        if oid:
            nucs_by_ovhg.setdefault(oid, []).append(n)

    def _anchor_for(conn, side: str):
        """Live anchor (pos, base_normal) for one side: the complement nuc
        on the OH's helix at the OH's `attach`-end bp. Direct same-bp
        lookup — no "farthest from tip" heuristic. Mirrors
        backend.core.linker_relax._anchor_pos_and_normal."""
        ovhg_id   = conn.overhang_a_id if side == "a" else conn.overhang_b_id
        attach    = conn.overhang_a_attach if side == "a" else conn.overhang_b_attach
        strand_id = f"__lnk__{conn.id}__{side}"
        oh_nucs   = nucs_by_ovhg.get(ovhg_id, [])
        attach_nuc = _oh_attach_nuc(oh_nucs, attach)
        if attach_nuc is None:
            return None, None
        target_helix = attach_nuc.get("helix_id")
        target_bp    = attach_nuc.get("bp_index")
        comp = next((n for n in nucs_by_strand.get(strand_id, [])
                     if not (n.get("helix_id") or "").startswith("__lnk__")
                     and n.get("helix_id") == target_helix
                     and n.get("bp_index") == target_bp), None)
        if comp is None:
            return None, None
        pos = comp.get("backbone_position") or comp.get("base_position")
        bn  = comp.get("base_normal")
        return (_np.asarray(pos, dtype=float) if pos is not None else None,
                _np.asarray(bn,  dtype=float) if bn  is not None else None)

    for conn in ds_conns:
        bridge_helix_id = f"__lnk__{conn.id}"
        # Find the two bridge strands (one per side).
        side_strand: dict[str, "Strand"] = {}
        for side in ("a", "b"):
            sid = f"__lnk__{conn.id}__{side}"
            s = next((st for st in design.strands if st.id == sid), None)
            if s is not None:
                side_strand[side] = s
        if not side_strand:
            continue
        # Find the bridge domain on each strand (the one on the virtual helix).
        side_bridge: dict[str, tuple[int, "Domain"]] = {}
        for side, s in side_strand.items():
            for di, dom in enumerate(s.domains):
                if dom.helix_id == bridge_helix_id:
                    side_bridge[side] = (di, dom)
                    break
        if not side_bridge:
            continue

        pa, na = _anchor_for(conn, "a")
        pb, _  = _anchor_for(conn, "b")
        if pa is None or pb is None:
            continue

        any_dom = next(iter(side_bridge.values()))[1]
        L = abs(any_dom.end_bp - any_dom.start_bp) + 1
        cfa = _comp_first(conn.overhang_a_id, conn.overhang_a_attach)
        cfb = _comp_first(conn.overhang_b_id, conn.overhang_b_attach)
        g = bridge_axis_geometry(pa, na, pb, L, cfa, cfb)
        fx, fy, fz = g["fx"], g["fy"], g["fz"]
        axis_start = g["axis_start"]
        R = g["helix_radius"]

        # Per-side: emit one nuc per bp of the bridge domain. Side A's
        # strand uses FORWARD-style angles (radial = fx·cos+fy·sin) when
        # comp_first_a; REVERSE-style otherwise. Same per-side rule.
        for side, (dom_idx, dom) in side_bridge.items():
            strand = side_strand[side]
            first_dom = strand.domains[0]
            last_dom  = strand.domains[-1]
            five_prime_key  = (first_dom.helix_id, first_dom.start_bp, first_dom.direction)
            three_prime_key = (last_dom.helix_id,  last_dom.end_bp,    last_dom.direction)
            is_fwd = dom.direction == Direction.FORWARD
            for bp in range(min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp) + 1):
                axis_pt = axis_start + fz * (bp * BDNA_RISE_PER_BP)
                ang = bp * _BDNA_TWIST_RAD + (0.0 if is_fwd else _MINOR_GROOVE_RAD) + _BRIDGE_PHASE_OFFSET
                radial = fx * math.cos(ang) + fy * math.sin(ang)
                bb_pos   = axis_pt + radial * R
                base_pos = axis_pt - radial * R
                bn = -radial   # backbone → base = inward
                key = (bridge_helix_id, bp, dom.direction)
                sinfo = nuc_info.get(key, {
                    "strand_id":      strand.id,
                    "strand_type":    strand.strand_type.value,
                    "is_five_prime":  key == five_prime_key,
                    "is_three_prime": key == three_prime_key,
                    "domain_index":   dom_idx,
                    "overhang_id":    None,
                })
                result.append({
                    "helix_id":          bridge_helix_id,
                    "bp_index":          bp,
                    "direction":         dom.direction.value,
                    "backbone_position": bb_pos.tolist(),
                    "base_position":     base_pos.tolist(),
                    "base_normal":       bn.tolist(),
                    "axis_tangent":      fz.tolist(),
                    **sinfo,
                })


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


def _cluster_by_lattice_neighbors(design: Design) -> Design:
    """Assign helices to clusters in three phases.

    Phase 1 — exclusive-scaffold helices cluster by same-scaffold lattice adjacency:
      Among scaffold-bearing helices, those that appear in EXACTLY ONE scaffold
      strand ("exclusive" helices) form Phase-1 clusters.  Two exclusive helices
      are connected if they are lattice-adjacent AND belong to the same scaffold
      strand.  Scaffold-strand identity is the module boundary: helices from two
      different scaffold loops cannot be merged, even if physically adjacent.

      ForcedLigation-only edges (no canonical Crossover between that pair) are
      removed, treating the forced connection as a cluster/joint boundary.

      Fallback: if there are no scaffold strands, all helices are treated as
      exclusive to one pseudo-strand (plain lattice-adjacency clustering).

    Phase 2 — bridge helices form independent connector clusters:
      Helices shared between 2+ scaffold strands are never absorbed into a
      Phase-1 cluster.  They cluster among themselves by lattice adjacency,
      producing one or more "connector" clusters that can be moved/articulated
      independently.  FL-only edges are also removed here.

    Phase 3 — scaffold-less helices absorbed by crossover majority:
      Helices on NO scaffold strand are each assigned to the Phase-1 or Phase-2
      cluster with which they share the most canonical crossovers.  Helices with
      no qualifying crossovers group among themselves by lattice adjacency.

    Helices without grid_pos are skipped.
    Clusters are named "Cluster 1", "Cluster 2", … sorted by minimum helix ID.
    """
    from backend.core.models import ClusterRigidTransform, ForcedLigation  # noqa: F401
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD

    gridded = [h for h in design.helices if h.grid_pos is not None]
    if not gridded:
        return design

    cell_to_id: dict[tuple[int, int], str] = {
        (h.grid_pos[0], h.grid_pos[1]): h.id for h in gridded
    }
    period = HC_CROSSOVER_PERIOD if design.lattice_type == LatticeType.HONEYCOMB else SQ_CROSSOVER_PERIOD

    crossover_pairs: set[frozenset] = {
        frozenset({xo.half_a.helix_id, xo.half_b.helix_id})
        for xo in design.crossovers
    }
    fl_pairs: set[frozenset] = {
        frozenset({fl.three_prime_helix_id, fl.five_prime_helix_id})
        for fl in design.forced_ligations
    }

    def _lattice_adj(helix_ids: set[str]) -> dict[str, set[str]]:
        """Build lattice-adjacency graph restricted to helix_ids, removing FL-only edges."""
        adj: dict[str, set[str]] = {hid: set() for hid in helix_ids}
        for h in gridded:
            if h.id not in helix_ids:
                continue
            row, col = h.grid_pos
            for is_scaf in (False, True):
                for idx in range(period):
                    nb = crossover_neighbor(design.lattice_type, row, col, idx, is_scaffold=is_scaf)
                    if nb is not None and nb in cell_to_id:
                        nb_id = cell_to_id[nb]
                        if nb_id in helix_ids and nb_id != h.id:
                            pair = frozenset({h.id, nb_id})
                            if pair not in fl_pairs or pair in crossover_pairs:
                                adj[h.id].add(nb_id)
                                adj[nb_id].add(h.id)
        return adj

    def _connected_components(helix_ids: set[str], adj: dict[str, set[str]]) -> list[list[str]]:
        visited: set[str] = set()
        comps: list[list[str]] = []
        for hid in helix_ids:
            if hid in visited:
                continue
            comp: list[str] = []
            q = [hid]
            visited.add(hid)
            while q:
                cur = q.pop(0)
                comp.append(cur)
                for nb in adj[cur]:
                    if nb not in visited:
                        visited.add(nb)
                        q.append(nb)
            comps.append(comp)
        return comps

    # ── Phase 1: exclusive-scaffold lattice adjacency ─────────────────────────

    # Only scaffold strands that span at least this many distinct helices are
    # treated as "module scaffolds" — smaller fragments (overhangs, connectors,
    # cadnano import artefacts) are ignored for module-boundary purposes.
    _MIN_MODULE_HELICES = 3

    # Build per-helix set of *module* scaffold indices (ignoring tiny fragments).
    h_to_scaf: dict[str, set[int]] = {}
    for i, s in enumerate(design.strands):
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        unique_helices = {d.helix_id for d in s.domains}
        if len(unique_helices) < _MIN_MODULE_HELICES:
            continue  # tiny fragment — not a module boundary
        for hid in unique_helices:
            h_to_scaf.setdefault(hid, set()).add(i)

    if h_to_scaf:
        # Exclusive: helix on exactly one module scaffold strand.
        exclusive: dict[str, int] = {
            hid: next(iter(scafs))
            for hid, scafs in h_to_scaf.items()
            if len(scafs) == 1
        }
        phase1_ids: set[str] = set(exclusive.keys())
        bridge_ids: set[str] = {hid for hid, scafs in h_to_scaf.items() if len(scafs) > 1}
    else:
        # No module scaffold strands: treat all gridded helices as one pseudo-scaffold.
        exclusive = {h.id: 0 for h in gridded}
        phase1_ids = {h.id for h in gridded}
        bridge_ids = set()

    # Same-scaffold lattice adjacency only.
    p1_adj = _lattice_adj(phase1_ids)
    for hid in list(p1_adj.keys()):
        p1_adj[hid] = {nb for nb in p1_adj[hid] if exclusive.get(nb) == exclusive[hid]}

    components: list[list[str]] = _connected_components(phase1_ids, p1_adj)

    # ── Phase 2: domain-level assignment of bridge helices ────────────────────
    # Bridge helices are split between scaffold clusters at the bp boundary where
    # one module scaffold ends and the other begins.  Each domain on a bridge
    # helix is assigned to the Phase-1 cluster of the scaffold that covers the
    # majority of that domain's bp range.  No separate "connector" cluster is
    # created; instead domain_ids on the Phase-1 clusters carry the bridge refs.

    from backend.core.models import DomainRef as _DR

    # helix_to_comp: Phase-1 exclusive helices only (reused in Phase 3).
    helix_to_comp: dict[str, int] = {
        hid: i for i, comp in enumerate(components) for hid in comp
    }

    # scaf_cov[bridge_hid][scaf_idx] = (lo, hi) merged across all scaffold domains
    # of that module scaffold on that bridge helix.
    scaf_cov: dict[str, dict[int, tuple[int, int]]] = {}
    for i, s in enumerate(design.strands):
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        unique_h = {d.helix_id for d in s.domains}
        if len(unique_h) < _MIN_MODULE_HELICES:
            continue
        for d in s.domains:
            if d.helix_id not in bridge_ids:
                continue
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            sc = scaf_cov.setdefault(d.helix_id, {})
            if i in sc:
                old_lo, old_hi = sc[i]
                sc[i] = (min(lo, old_lo), max(hi, old_hi))
            else:
                sc[i] = (lo, hi)

    # scaf_to_cis[scaf_idx] = list of Phase-1 component indices that belong to
    # that module scaffold (usually exactly one).
    scaf_to_cis: dict[int, list[int]] = {}
    for hid, scaf_idx in exclusive.items():
        ci = helix_to_comp[hid]
        scaf_to_cis.setdefault(scaf_idx, [])
        if ci not in scaf_to_cis[scaf_idx]:
            scaf_to_cis[scaf_idx].append(ci)

    comp_domain_ids: dict[int, list] = {i: [] for i in range(len(components))}
    bridge_ci_map: dict[str, set[int]] = {}  # bridge_hid → comp indices that own it

    # Pre-build per-bridge-helix domain lookup to avoid O(n_strands) scan per bridge.
    bridge_domains: dict[str, list[tuple[int, int]]] = {hid: [] for hid in bridge_ids}
    for si, strand in enumerate(design.strands):
        for di, dom in enumerate(strand.domains):
            if dom.helix_id in bridge_ids:
                bridge_domains[dom.helix_id].append((si, di))

    for bridge_h in gridded:
        if bridge_h.id not in bridge_ids:
            continue
        cov = scaf_cov.get(bridge_h.id, {})
        if not cov:
            continue

        for si, di in bridge_domains[bridge_h.id]:
            strand = design.strands[si]
            dom = strand.domains[di]
            dom_lo = min(dom.start_bp, dom.end_bp)
            dom_hi = max(dom.start_bp, dom.end_bp)

            # Find the module scaffold covering the most of this domain's bp range.
            best_scaf, best_overlap = None, 0
            for scaf_idx, (clo, chi) in cov.items():
                overlap = max(0, min(dom_hi, chi) - max(dom_lo, clo))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_scaf = scaf_idx

            if best_scaf is None:
                continue

            # Map to Phase-1 component, using crossover count when ambiguous.
            ci_list = scaf_to_cis.get(best_scaf, [])
            if not ci_list:
                continue
            if len(ci_list) == 1:
                best_ci = ci_list[0]
            else:
                comp_xo: dict[int, int] = {}
                for xo in design.crossovers:
                    if xo.half_a.helix_id == bridge_h.id:
                        partner = xo.half_b.helix_id
                    elif xo.half_b.helix_id == bridge_h.id:
                        partner = xo.half_a.helix_id
                    else:
                        continue
                    if partner in helix_to_comp and helix_to_comp[partner] in ci_list:
                        cxo = helix_to_comp[partner]
                        comp_xo[cxo] = comp_xo.get(cxo, 0) + 1
                best_ci = (max(comp_xo, key=lambda c: comp_xo[c])
                           if comp_xo else ci_list[0])

            comp_domain_ids[best_ci].append(_DR(strand_id=strand.id, domain_index=di))
            bridge_ci_map.setdefault(bridge_h.id, set()).add(best_ci)

    # ── Phase 3: absorb scaffold-less helices by crossover majority ────────────
    # Only crossovers to Phase-1 exclusive helices are used; orphan helices with
    # no Phase-1 crossover partners are grouped by lattice adjacency.

    orphan_helices = [h for h in gridded if h.id not in phase1_ids and h.id not in bridge_ids]
    absorbed: dict[str, int] = {}
    unconnected: list = []

    for h in orphan_helices:
        comp_xo: dict[int, int] = {}
        for xo in design.crossovers:
            if xo.half_a.helix_id == h.id:
                partner = xo.half_b.helix_id
            elif xo.half_b.helix_id == h.id:
                partner = xo.half_a.helix_id
            else:
                continue
            if partner in helix_to_comp:
                ci = helix_to_comp[partner]
                comp_xo[ci] = comp_xo.get(ci, 0) + 1
        if comp_xo:
            absorbed[h.id] = max(comp_xo, key=lambda ci: comp_xo[ci])
        else:
            unconnected.append(h)

    # Unconnected orphans group among themselves by lattice adjacency.
    unconn_groups: list[list[str]] = []
    if unconnected:
        unconn_ids = {h.id for h in unconnected}
        u_adj = _lattice_adj(unconn_ids)
        unconn_groups = _connected_components(unconn_ids, u_adj)

    # ── Rebuild final components ───────────────────────────────────────────────

    comp_helices: dict[int, list[str]] = {i: list(comp) for i, comp in enumerate(components)}
    # Add bridge helix IDs to every cluster that has domain refs on them.
    for bridge_hid, ci_set in bridge_ci_map.items():
        for ci in ci_set:
            if bridge_hid not in comp_helices[ci]:
                comp_helices[ci].append(bridge_hid)
    for hid, ci in absorbed.items():
        comp_helices[ci].append(hid)
    offset = len(components)
    for i, grp in enumerate(unconn_groups):
        comp_helices[offset + i] = grp

    # Sort clusters by minimum helix id, preserving domain_ids pairing.
    indexed = [(ci, sorted(comp_helices[ci])) for ci in comp_helices]
    indexed.sort(key=lambda x: x[1][0] if x[1] else '')
    clusters = [
        ClusterRigidTransform(
            name=f"Cluster {n}",
            is_default=False,
            helix_ids=hids,
            domain_ids=comp_domain_ids.get(ci, []),
        )
        for n, (ci, hids) in enumerate(indexed, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _cluster_by_scaffold_routing(design: Design) -> Design:
    """Create one cluster per module scaffold strand (topology-based).

    Each cluster contains the scaffold strand's helices and all non-scaffold
    domains that pair with it, determined by bp-range overlap on the same helix.
    Bridge helices (shared by 2+ module scaffolds) are split at domain level via
    DomainRef entries so both clusters can coexist on the same helix.

    Orphan helices (not visited by any scaffold) are absorbed into the scaffold
    cluster with which they share the most canonical crossovers.

    Falls back to _cluster_by_lattice_neighbors when no module scaffold is
    detected (scaffold-less designs or all-tiny-fragment imports).
    """
    from backend.core.models import ClusterRigidTransform, DomainRef as _DR

    _MIN_MODULE_HELICES = 3

    gridded = [h for h in design.helices if h.grid_pos is not None]
    if not gridded:
        return design

    # ── Identify module scaffolds ─────────────────────────────────────────────
    module_scaffolds: list[int] = []
    for i, s in enumerate(design.strands):
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        if len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES:
            module_scaffolds.append(i)

    if not module_scaffolds:
        return design.copy_with(cluster_transforms=[])

    # ── Build bp coverage per scaffold per helix ──────────────────────────────
    scaf_cov: dict[int, dict[str, tuple[int, int]]] = {si: {} for si in module_scaffolds}
    scaf_helix_ids: dict[int, set[str]] = {si: set() for si in module_scaffolds}

    for si in module_scaffolds:
        s = design.strands[si]
        for d in s.domains:
            hid = d.helix_id
            scaf_helix_ids[si].add(hid)
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            if hid in scaf_cov[si]:
                olo, ohi = scaf_cov[si][hid]
                scaf_cov[si][hid] = (min(lo, olo), max(hi, ohi))
            else:
                scaf_cov[si][hid] = (lo, hi)

    # ── Classify helices as exclusive or bridge ───────────────────────────────
    h_to_scaf: dict[str, set[int]] = {}
    for si in module_scaffolds:
        for hid in scaf_helix_ids[si]:
            h_to_scaf.setdefault(hid, set()).add(si)

    bridge_ids: set[str] = {hid for hid, scafs in h_to_scaf.items() if len(scafs) > 1}

    # ── Initialize cluster structures ─────────────────────────────────────────
    cluster_helix_ids: dict[int, set[str]] = {si: set(scaf_helix_ids[si]) for si in module_scaffolds}
    cluster_domain_ids: dict[int, list] = {si: [] for si in module_scaffolds}

    # Scaffold's own domains on bridge helices need explicit DomainRef entries.
    for si in module_scaffolds:
        s = design.strands[si]
        for di, d in enumerate(s.domains):
            if d.helix_id in bridge_ids:
                cluster_domain_ids[si].append(_DR(strand_id=s.id, domain_index=di))

    # ── Assign non-scaffold domains by majority scaffold bp overlap ───────────
    for si2, strand in enumerate(design.strands):
        if strand.is_scaffold:
            continue
        for di, dom in enumerate(strand.domains):
            hid = dom.helix_id
            if hid not in h_to_scaf:
                continue  # helix not visited by any module scaffold
            dom_lo = min(dom.start_bp, dom.end_bp)
            dom_hi = max(dom.start_bp, dom.end_bp)

            best_si, best_overlap = None, 0
            for si_cand in h_to_scaf[hid]:
                cov = scaf_cov[si_cand].get(hid)
                if cov is None:
                    continue
                clo, chi = cov
                overlap = max(0, min(dom_hi, chi) - max(dom_lo, clo))
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_si = si_cand

            if best_si is None:
                continue

            if hid in bridge_ids:
                # Bridge helix: domain ref needed to disambiguate between clusters.
                cluster_domain_ids[best_si].append(_DR(strand_id=strand.id, domain_index=di))
            # Exclusive helix: implicitly covered by helix_ids — no DomainRef needed.

    # ── Absorb orphan helices (no scaffold) by crossover majority ─────────────
    for h in gridded:
        if h.id in h_to_scaf:
            continue
        xo_counts: dict[int, int] = {}
        for xo in design.crossovers:
            if xo.half_a.helix_id == h.id:
                partner = xo.half_b.helix_id
            elif xo.half_b.helix_id == h.id:
                partner = xo.half_a.helix_id
            else:
                continue
            for si in module_scaffolds:
                if partner in cluster_helix_ids[si]:
                    xo_counts[si] = xo_counts.get(si, 0) + 1
                    break
        if xo_counts:
            best_si = max(xo_counts, key=lambda si: xo_counts[si])
            cluster_helix_ids[best_si].add(h.id)

    # ── Build ClusterRigidTransform objects ───────────────────────────────────
    scaffolds_sorted = sorted(
        module_scaffolds,
        key=lambda si: sorted(cluster_helix_ids[si])[0] if cluster_helix_ids[si] else '',
    )
    clusters = [
        ClusterRigidTransform(
            name=f"Scaffold Cluster {n}",
            is_default=False,
            helix_ids=sorted(cluster_helix_ids[si]),
            domain_ids=cluster_domain_ids[si],
        )
        for n, si in enumerate(scaffolds_sorted, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _geometry_clusters_multi_scaffold(design: Design) -> Design:
    """Geometry clusters for designs with 2+ module scaffolds.

    One cluster per module scaffold.  Unlike scaffold clusters, bridge helices
    (shared by multiple scaffolds) are assigned WHOLE to whichever scaffold has
    the most bp coverage on them — no domain_ids split.  This keeps each scaffold's
    entire structural territory as one rigid-body geometry cluster.
    """
    from backend.core.models import ClusterRigidTransform

    _MIN_MODULE_HELICES = 3
    gridded = [h for h in design.helices if h.grid_pos is not None]

    module_scaffolds: list[int] = [
        i for i, s in enumerate(design.strands)
        if s.is_scaffold
        and len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES
    ]

    scaf_cov: dict[int, dict[str, tuple[int, int]]] = {si: {} for si in module_scaffolds}
    scaf_helix_ids: dict[int, set[str]] = {si: set() for si in module_scaffolds}
    for si in module_scaffolds:
        for d in design.strands[si].domains:
            hid = d.helix_id
            scaf_helix_ids[si].add(hid)
            lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
            if hid in scaf_cov[si]:
                olo, ohi = scaf_cov[si][hid]
                scaf_cov[si][hid] = (min(lo, olo), max(hi, ohi))
            else:
                scaf_cov[si][hid] = (lo, hi)

    h_to_scaf: dict[str, set[int]] = {}
    for si in module_scaffolds:
        for hid in scaf_helix_ids[si]:
            h_to_scaf.setdefault(hid, set()).add(si)

    bridge_ids: set[str] = {hid for hid, scafs in h_to_scaf.items() if len(scafs) > 1}

    # Start with each scaffold's exclusive helices only.
    cluster_helix_ids: dict[int, set[str]] = {
        si: {hid for hid in scaf_helix_ids[si] if hid not in bridge_ids}
        for si in module_scaffolds
    }

    # Assign each bridge helix WHOLE to the scaffold with the most bp coverage.
    for hid in bridge_ids:
        best_si, best_len = None, 0
        for si in h_to_scaf.get(hid, set()):
            cov = scaf_cov[si].get(hid)
            if cov:
                length = cov[1] - cov[0]
                if length > best_len:
                    best_len = length
                    best_si = si
        if best_si is not None:
            cluster_helix_ids[best_si].add(hid)

    # Absorb orphan helices (not visited by any module scaffold) by crossover majority.
    for h in gridded:
        if h.id in h_to_scaf:
            continue
        xo_counts: dict[int, int] = {}
        for xo in design.crossovers:
            if xo.half_a.helix_id == h.id:
                partner = xo.half_b.helix_id
            elif xo.half_b.helix_id == h.id:
                partner = xo.half_a.helix_id
            else:
                continue
            for si in module_scaffolds:
                if partner in cluster_helix_ids[si]:
                    xo_counts[si] = xo_counts.get(si, 0) + 1
                    break
        if xo_counts:
            best_si = max(xo_counts, key=lambda si: xo_counts[si])
            cluster_helix_ids[best_si].add(h.id)

    scaffolds_sorted = sorted(
        module_scaffolds,
        key=lambda si: sorted(cluster_helix_ids[si])[0] if cluster_helix_ids[si] else '',
    )
    clusters = [
        ClusterRigidTransform(
            name=f"Geometry Cluster {n}",
            is_default=False,
            helix_ids=sorted(cluster_helix_ids[si]),
            domain_ids=[],
        )
        for n, si in enumerate(scaffolds_sorted, start=1)
    ]
    return design.copy_with(cluster_transforms=clusters)


def _autodetect_clusters(design: Design) -> Design:
    """Produce both scaffold-routing clusters and geometry clusters.

    Scaffold clusters (one per module scaffold, with domain_ids for bridge helices)
    are named "Scaffold Cluster N".

    Geometry clusters are named "Geometry Cluster N" and use different rules
    depending on scaffold count:
      - 0 or 1 module scaffold: lattice-adjacency with FL-only edge removal
        (same rigid-body rules as the hinge — finds structural sub-segments).
      - 2+ module scaffolds: one cluster per scaffold, bridge helices assigned
        WHOLE to the scaffold with the most bp coverage (no domain_ids split).

    Both sets are always produced and combined into design.cluster_transforms.
    """
    _MIN_MODULE_HELICES = 3
    n_module_scaffolds = sum(
        1 for s in design.strands
        if s.is_scaffold
        and len({d.helix_id for d in s.domains}) >= _MIN_MODULE_HELICES
    )

    scaf_design = _cluster_by_scaffold_routing(design)
    scaffold_clusters = list(scaf_design.cluster_transforms)

    if n_module_scaffolds >= 2:
        geo_design = _geometry_clusters_multi_scaffold(design)
        geometry_clusters = list(geo_design.cluster_transforms)
    else:
        geo_design = _cluster_by_lattice_neighbors(design)
        geometry_clusters = [
            ct.model_copy(update={"name": f"Geometry Cluster {n}"})
            for n, ct in enumerate(geo_design.cluster_transforms, start=1)
        ]

    return design.copy_with(cluster_transforms=scaffold_clusters + geometry_clusters)


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
    return {
        "design":     design_dict,
        "validation": _validation_dict(report, design),
        # Crossovers whose two halves currently resolve to the same strand
        # (would form a circular strand on ligation, so _ligate_crossover
        # skipped them). Frontend renders a ⚠ marker on these. Recomputed
        # on every response, so the marker auto-clears when the user nicks
        # the strand to break the cycle.
        "unligated_crossover_ids": unligated_crossover_ids(design),
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
    cts = design_dict.get('cluster_transforms') or []
    if not cts:
        return
    ct_by_id = {ct.get('id'): ct for ct in cts if isinstance(ct, dict)}
    for j in design_dict.get('cluster_joints') or []:
        if not isinstance(j, dict):
            continue
        local_origin = j.get('local_axis_origin')
        local_dir    = j.get('local_axis_direction')
        if local_origin is None or local_dir is None:
            continue
        ct = ct_by_id.get(j.get('cluster_id'))
        world_origin, world_dir = _local_to_world_joint(local_origin, local_dir, ct)
        j['axis_origin']    = world_origin
        j['axis_direction'] = world_dir


def _compact_geometry_from_nucleotides(nucleotides: list[dict]) -> dict:
    """Convert a flat list of nucleotide dicts into the COMPACT
    per-helix-per-direction parallel-array form used by the
    ``nucleotides_compact`` wire format. See _compact_geometry_for_design
    for the rationale; this helper exists so callers that already have the
    nucleotide list (e.g. _design_response_with_geometry) don't recompute it.
    """
    out: dict = {}
    for n in nucleotides:
        helix = n.get("helix_id")
        if helix is None:
            continue
        direction = n.get("direction")
        helix_bucket = out.get(helix)
        if helix_bucket is None:
            helix_bucket = {}
            out[helix] = helix_bucket
        b = helix_bucket.get(direction)
        if b is None:
            b = {
                "bp": [], "bb": [], "bs": [], "bn": [], "at": [],
                "sid": [], "stype": [], "is5": [], "is3": [],
                "did": [], "ohid": [],
                # Sparse fields: appended lazily, so empty arrays don't ship.
                "extid": None, "ismod": None, "mod": None, "base": None,
            }
            helix_bucket[direction] = b
        b["bp"].append(n.get("bp_index"))
        b["bb"].append(n.get("backbone_position"))
        b["bs"].append(n.get("base_position"))
        b["bn"].append(n.get("base_normal"))
        b["at"].append(n.get("axis_tangent"))
        b["sid"].append(n.get("strand_id"))
        b["stype"].append(n.get("strand_type"))
        b["is5"].append(bool(n.get("is_five_prime")))
        b["is3"].append(bool(n.get("is_three_prime")))
        b["did"].append(n.get("domain_index", 0))
        b["ohid"].append(n.get("overhang_id"))
        # Sparse fields — only allocate the array when first non-default appears.
        ext_id = n.get("extension_id")
        if ext_id is not None:
            if b["extid"] is None: b["extid"] = [None] * (len(b["bp"]) - 1)
            b["extid"].append(ext_id)
        elif b["extid"] is not None:
            b["extid"].append(None)
        is_mod = bool(n.get("is_modification"))
        if is_mod:
            if b["ismod"] is None: b["ismod"] = [False] * (len(b["bp"]) - 1)
            b["ismod"].append(True)
        elif b["ismod"] is not None:
            b["ismod"].append(False)
        mod = n.get("modification")
        if mod is not None:
            if b["mod"] is None: b["mod"] = [None] * (len(b["bp"]) - 1)
            b["mod"].append(mod)
        elif b["mod"] is not None:
            b["mod"].append(None)
        base = n.get("nucleobase")
        if base is not None:
            if b["base"] is None: b["base"] = [None] * (len(b["bp"]) - 1)
            b["base"].append(base)
        elif b["base"] is not None:
            b["base"].append(None)
    # Drop sparse-field placeholders that never got populated, to keep the wire
    # tight when none of those fields apply.
    for helix_bucket in out.values():
        for b in helix_bucket.values():
            for k in ("extid", "ismod", "mod", "base"):
                if b.get(k) is None:
                    b.pop(k, None)
    return out


def _compact_geometry_for_design(design: 'Design') -> dict:
    """Compute full deformed geometry in COMPACT per-helix-per-direction
    parallel-arrays form. Wire size is ~50% of the equivalent dict-list
    ``nucleotides`` payload because field names don't repeat per nuc;
    JSON.parse on the frontend is roughly proportionally faster.
    """
    return _compact_geometry_from_nucleotides(_geometry_for_design(design))


def _design_response_with_geometry(
    design: Design,
    report: ValidationReport,
    changed_helix_ids: list[str] | None = None,
    *,
    embed_straight: bool | None = None,
    compact_deformed: bool = False,
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
            "helix_axes":          axes,
        }
    else:
        out = {
            **_design_response(design, report),
            "nucleotides": nucleotides,
            "helix_axes":  axes,
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
        straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
        straight_positions, straight_axes = _positions_for_design(straight)
        out["straight_positions_by_helix"] = straight_positions
        out["straight_helix_axes"]         = straight_axes
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
    populate_strands: bool = False   # if True, also adds a full-length scaffold + staple


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
    rest = strand_id[len(prefix):]
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
        dom.helix_id
        for s in new_strands
        for dom in s.domains
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
            lo <= bp <= hi
            for lo, hi in slot_cov.get(f"{helix_id}_{direction}", [])
        )

    new_crossovers = [
        xo for xo in design.crossovers
        if _covered(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
        and _covered(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
    ]

    return design.model_copy(update={
        "strands": new_strands,
        "overhangs": new_overhangs,
        "helices": new_helices,
        "crossovers": new_crossovers,
    })


def _delete_linker_connections_from_design(design: Design, conn_ids: set[str]) -> Design:
    """Delete linker connection records and all generated linker topology."""
    if not conn_ids:
        return design
    from backend.core.lattice import remove_linker_topology

    updated = design.model_copy(update={
        "overhang_connections": [
            conn for conn in design.overhang_connections
            if conn.id not in conn_ids
        ]
    })
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


class MdLoadRequest(BaseModel):
    topology_path: str   # abs path to .gro or .tpr file
    xtc_path: str        # abs path to .xtc trajectory


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


def _diff_is_cluster_only(prev: 'Design', new: 'Design') -> bool:
    """True iff prev and new differ ONLY in cluster_transforms' rotation /
    translation (no add/remove/structural/pivot change). Used by undo/redo
    to take a Plan-B-style fast path that avoids the full geometry recompute
    and the frontend scene rebuild.

    Cluster_joints are allowed to differ because they move with cluster
    transforms by design.

    Pivot equality is required because the frontend's delta-transform math
    (which composes the existing applyClusterTransform call to step from
    the OLD cluster transform's world position to the NEW one) only holds
    when the pivot is unchanged. If pivots differ, the math would need to
    re-resolve via the straight-position basis — fall back to the full
    geometry refetch path in that rare case.
    """
    structural = [
        'helices', 'strands', 'crossovers', 'forced_ligations',
        'deformations', 'extensions', 'overhangs', 'overhang_connections',
        'photoproduct_junctions',
    ]
    for f in structural:
        if getattr(prev, f) != getattr(new, f):
            return False
    if len(prev.cluster_transforms) != len(new.cluster_transforms):
        return False
    if prev.cluster_transforms == new.cluster_transforms:
        return False   # nothing changed at all — let the regular path handle it
    by_id_prev = {ct.id: ct for ct in prev.cluster_transforms}
    by_id_new  = {ct.id: ct for ct in new.cluster_transforms}
    if set(by_id_prev) != set(by_id_new):
        return False   # cluster added or removed
    for cid, p_ct in by_id_prev.items():
        n_ct = by_id_new[cid]
        if p_ct.helix_ids   != n_ct.helix_ids:   return False
        if p_ct.domain_ids  != n_ct.domain_ids:  return False
        if p_ct.name        != n_ct.name:        return False
        if p_ct.is_default  != n_ct.is_default:  return False
        if p_ct.pivot       != n_ct.pivot:       return False   # frontend delta math requires this
    return True


def _cluster_diff_payload(prev: 'Design', new: 'Design') -> list[dict]:
    """For each cluster whose translation / rotation / pivot changed
    between *prev* and *new*, emit a record the frontend can use to
    apply the delta to the renderer's bead/slab/cone/axis matrices
    in-place. Caller is responsible for ensuring `_diff_is_cluster_only`
    holds — this helper just emits the records.
    """
    by_id_prev = {ct.id: ct for ct in prev.cluster_transforms}
    out = []
    for n_ct in new.cluster_transforms:
        p_ct = by_id_prev.get(n_ct.id)
        if p_ct is None:
            continue
        if (p_ct.translation == n_ct.translation
                and p_ct.rotation == n_ct.rotation
                and p_ct.pivot == n_ct.pivot):
            continue
        out.append({
            "cluster_id": n_ct.id,
            "helix_ids":  list(n_ct.helix_ids),
            "old_translation": list(p_ct.translation),
            "old_rotation":    list(p_ct.rotation),
            "old_pivot":       list(p_ct.pivot),
            "new_translation": list(n_ct.translation),
            "new_rotation":    list(n_ct.rotation),
            "new_pivot":       list(n_ct.pivot),
        })
    return out


def _topology_unchanged(prev: 'Design', new: 'Design') -> bool:
    """True iff the renderer's structural inventory (mesh/cone/slab counts,
    axis-tube curvature, helix lengths) is invariant between prev and new.

    The frontend's ``positions_only`` fast path mutates per-nuc positions in
    place WITHOUT a full design_renderer rebuild, so anything that would force
    a rebuild must be excluded here:

      • Helix add/remove or axis change → mesh count / curvature change.
      • Strand domain change → which bps have nucs.
      • Crossover/extension/overhang change → adds or removes nucs.
      • DEFORMATION add/remove/edit → can flip a helix between straight and
        curved, which requires rebuilding the axis tube geometry.

    Cluster transforms ARE allowed to differ — they just translate/rotate
    existing meshes without changing topology or curvature.
    """
    return _topology_diff_field(prev, new) is None


def _topology_diff_field(prev: 'Design', new: 'Design') -> str | None:
    """If the topology check rejects, return the name of the field that
    differs. ``None`` means topology IS unchanged. Used to attach a more
    informative ``path:full_geometry(<reason>)`` tag to the perf trace so
    you can see at a glance why positions_only didn't fire."""
    if prev.helices != new.helices:           return "helices"
    if prev.strands != new.strands:           return "strands"
    if prev.crossovers != new.crossovers:     return "crossovers"
    if prev.extensions != new.extensions:     return "extensions"
    if prev.overhang_connections != new.overhang_connections: return "overhang_connections"
    if prev.overhangs != new.overhangs:       return "overhangs"
    if prev.forced_ligations != new.forced_ligations: return "forced_ligations"
    if prev.photoproduct_junctions != new.photoproduct_junctions: return "photoproduct_junctions"
    if prev.deformations != new.deformations: return "deformations"
    return None


def _positions_by_helix(nucleotides: list[dict]) -> dict:
    """Compact per-nuc-position payload for the ``positions_only`` diff,
    converted from a list-of-dicts. Used as a fallback when callers already
    have nucleotide dicts on hand. Hot paths should call
    :func:`_positions_for_design` instead, which emits parallel arrays
    directly from the numpy pipeline and skips the per-nuc dict allocation.
    """
    out: dict = {}
    for n in nucleotides:
        helix = n.get("helix_id")
        if helix is None:
            continue
        direction = n.get("direction")
        bucket = out.setdefault(helix, {}).setdefault(direction, None)
        if bucket is None:
            bucket = {"bp": [], "bb": [], "bs": [], "bn": [], "at": []}
            out[helix][direction] = bucket
        bucket["bp"].append(n.get("bp_index"))
        bucket["bb"].append(n.get("backbone_position"))
        bucket["bs"].append(n.get("base_position"))
        bucket["bn"].append(n.get("base_normal"))
        bucket["at"].append(n.get("axis_tangent"))
    return out


def _positions_for_design(design: 'Design') -> tuple[dict, list[dict]]:
    """Compute positions for *design* in compact per-helix-per-direction
    parallel arrays, **without** materialising per-nuc dicts for the bulk
    geometry. Used by the ``positions_only`` fast path.

    Returns ``(positions_by_helix, helix_axes)``.

    The numpy pipeline (``deformed_nucleotide_arrays`` + extension/loop
    helpers) is the same as ``_geometry_for_helices``; the saving comes
    from skipping the ~50K dict allocations + ``**sinfo`` spreads that
    dominate the full-geometry path's response-build time.

    ds-linker bridge nucs: ``_emit_bridge_nucs`` emits per-nuc dicts and
    needs anchor-nuc lookups by overhang_id. Bridges are a tiny fraction
    of total nucs (≤200 per design), so we build a thin dict list for
    JUST the OH-bearing helices and feed that through the existing helper,
    then fold the resulting bridge-nuc positions into ``positions_by_helix``.
    Bulk positions stay dict-free.
    """
    from backend.core.deformation import (
        deformed_nucleotide_arrays, deform_extended_arrays,
        effective_helix_for_geometry,
    )

    positions: dict = {}

    # Strand-domain bp range per helix (needed for ss-scaffold loop extensions).
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

    _DIR_NAMES = ("FORWARD", "REVERSE")

    def _emit_compact(arrs: dict, helix_id: str) -> None:
        M = len(arrs['bp_indices'])
        if M == 0:
            return
        bp_list   = arrs['bp_indices'].tolist()
        dir_arr   = arrs['directions']
        pos_list  = arrs['positions'].tolist()
        base_list = arrs['base_positions'].tolist()
        bn_list   = arrs['base_normals'].tolist()
        at_list   = arrs['axis_tangents'].tolist()
        helix_bucket = positions.get(helix_id)
        if helix_bucket is None:
            helix_bucket = {}
            positions[helix_id] = helix_bucket
        for i in range(M):
            dir_name = _DIR_NAMES[dir_arr[i]]
            dir_bucket = helix_bucket.get(dir_name)
            if dir_bucket is None:
                dir_bucket = {"bp": [], "bb": [], "bs": [], "bn": [], "at": []}
                helix_bucket[dir_name] = dir_bucket
            dir_bucket["bp"].append(bp_list[i])
            dir_bucket["bb"].append(pos_list[i])
            dir_bucket["bs"].append(base_list[i])
            dir_bucket["bn"].append(bn_list[i])
            dir_bucket["at"].append(at_list[i])

    for helix in design.helices:
        if helix.id.startswith("__lnk__"):
            continue   # virtual linker helix has no real geometry of its own

        arrs = deformed_nucleotide_arrays(helix, design)
        arrs = apply_overhang_rotation_if_needed(arrs, helix, design)
        _emit_compact(arrs, arrs['helix_id'])

        norm_helix = None
        lo_bp = min_domain_bp.get(helix.id, helix.bp_start)
        if lo_bp < helix.bp_start:
            norm_helix = effective_helix_for_geometry(helix, design)
            extra = nucleotide_positions_arrays_extended(norm_helix, lo_bp)
            extra = deform_extended_arrays(extra, helix, design, edge_bp=helix.bp_start)
            _emit_compact(extra, helix.id)

        hi_bp = max_domain_bp.get(helix.id, helix.bp_start + helix.length_bp - 1)
        helix_hi = helix.bp_start + helix.length_bp
        if hi_bp >= helix_hi:
            if norm_helix is None:
                norm_helix = effective_helix_for_geometry(helix, design)
            extra = nucleotide_positions_arrays_extended_right(norm_helix, hi_bp)
            extra = deform_extended_arrays(extra, helix, design, edge_bp=helix_hi - 1)
            _emit_compact(extra, helix.id)

    # Helix axes — same pipeline as the full-geometry path.
    axes = deformed_helix_axes(design)

    # Build the (helix_id, bp_index, direction) → backbone_position lookup
    # straight from positions_by_helix so _apply_ovhg_rotations_to_axes can
    # work without us materialising per-nuc dicts. Direction here uses
    # string form to match the dict-based legacy API.
    nuc_lookup: dict = {}
    from backend.core.models import Direction
    for hid, by_dir in positions.items():
        for dir_name, bucket in by_dir.items():
            d_enum = Direction.FORWARD if dir_name == "FORWARD" else Direction.REVERSE
            bp_arr = bucket["bp"]
            bb_arr = bucket["bb"]
            for i in range(len(bp_arr)):
                nuc_lookup[(hid, bp_arr[i], d_enum)] = bb_arr[i]
                # _apply_ovhg_rotations_to_axes' lookup uses the legacy
                # tuple form keyed by Direction enum; in older code the
                # tuple key uses the .value string. Cover both for safety.
                nuc_lookup[(hid, bp_arr[i], dir_name)] = bb_arr[i]
    _apply_ovhg_rotations_to_axes(design, axes, nuc_lookup=nuc_lookup)

    # Bridge nucs: build a thin dict list for OH-bearing helices and run
    # _emit_bridge_nucs. Bridge nucs are typically <200 per design — paying
    # the dict cost for them is fine. After emission, fold their positions
    # into positions_by_helix.
    if any(c.linker_type == "ds" for c in design.overhang_connections):
        nuc_info = _strand_nucleotide_info(design)
        # Identify helices that carry an overhang or a complement strand on
        # the OH side; that's the lookup _emit_bridge_nucs needs.
        oh_strand_ids = {o.strand_id for o in design.overhangs}
        anchor_dicts: list[dict] = []
        for hid, by_dir in positions.items():
            for dir_name, bucket in by_dir.items():
                d_enum = Direction.FORWARD if dir_name == "FORWARD" else Direction.REVERSE
                bp_arr   = bucket["bp"]
                bb_arr   = bucket["bb"]
                bs_arr   = bucket["bs"]
                bn_arr   = bucket["bn"]
                at_arr   = bucket["at"]
                for i in range(len(bp_arr)):
                    sinfo = nuc_info.get((hid, bp_arr[i], d_enum))
                    # We only need anchors whose strand has an overhang_id
                    # OR is a linker complement strand. Skip bulk-only nucs
                    # so the dict list stays small.
                    if not sinfo or (sinfo.get("overhang_id") is None
                                     and sinfo.get("strand_id") not in oh_strand_ids
                                     and not (sinfo.get("strand_id") or "").startswith("__lnk__")):
                        continue
                    anchor_dicts.append({
                        "helix_id":          hid,
                        "bp_index":          bp_arr[i],
                        "direction":         dir_name,
                        "backbone_position": bb_arr[i],
                        "base_position":     bs_arr[i],
                        "base_normal":       bn_arr[i],
                        "axis_tangent":      at_arr[i],
                        **sinfo,
                    })
        # _emit_bridge_nucs reads anchor_dicts (via nucs_by_strand /
        # nucs_by_ovhg) and APPENDS bridge nucs to it.
        before = len(anchor_dicts)
        _emit_bridge_nucs(design, {}, anchor_dicts)
        for n in anchor_dicts[before:]:
            hid = n.get("helix_id")
            if not hid:
                continue
            dir_name = n.get("direction")
            helix_bucket = positions.get(hid)
            if helix_bucket is None:
                helix_bucket = {}
                positions[hid] = helix_bucket
            dir_bucket = helix_bucket.get(dir_name)
            if dir_bucket is None:
                dir_bucket = {"bp": [], "bb": [], "bs": [], "bn": [], "at": []}
                helix_bucket[dir_name] = dir_bucket
            dir_bucket["bp"].append(n.get("bp_index"))
            dir_bucket["bb"].append(n.get("backbone_position"))
            dir_bucket["bs"].append(n.get("base_position"))
            dir_bucket["bn"].append(n.get("base_normal"))
            dir_bucket["at"].append(n.get("axis_tangent"))

    return positions, axes


def _design_replace_response(
    prev_design: 'Design',
    design: 'Design',
    report: 'ValidationReport',
    trace: '_TimingTrace | None' = None,
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
            "diff_kind":     "cluster_only",
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
            "diff_kind":          "positions_only",
            "positions_by_helix": positions,
            "helix_axes":         axes,
        }
    if trace is not None:
        # Tag with the rejecting field so the frontend perf log shows
        # why positions_only didn't fire (e.g. path:full_geometry_strands).
        trace._steps.append((f"path:full_geometry_{diff_field}", 0.0))
    # embed_straight=True bundles the straight (un-deformed) geometry into
    # the same response, so deform_view doesn't have to fire a second
    # ~5-second `/design/geometry?apply_deformations=false` round-trip
    # on every topology-changing seek / undo / redo / delete-feature.
    # compact_deformed=True ships the deformed geometry as parallel arrays
    # per helix per direction (instead of a list of per-nuc dicts), cutting
    # wire size and JSON.parse time roughly in half.
    return _design_response_with_geometry(
        design, report,
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


def _build_extrude_segment(d: Design, body: 'BundleSegmentRequest'):
    """Pure builder + cluster-membership report for a slice-plane extrude."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_bundle_segment, ligate_new_strands

    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_bundle_segment(
        d, cells, body.length_bp, body.plane, body.offset_nm, body.strand_filter,
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
        holder['mreport'] = mreport
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='extrude-segment',
        label=f'Extrude segment: {len(body.cells)} cells × {body.length_bp} bp',
        params=body.model_dump(mode='json'),
        fn=_fn,
    )
    return _design_response(updated, report)


def _build_extrude_continuation(d: Design, body: 'BundleContinuationRequest'):
    """Pure builder + cluster-membership report for a bundle-continuation extrude."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_bundle_continuation, ligate_new_strands

    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_bundle_continuation(
        d, cells, body.length_bp, body.plane, body.offset_nm, body.strand_filter,
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
        holder['mreport'] = mreport
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='extrude-continuation',
        label=f'Extrude continuation: {len(body.cells)} cells × {body.length_bp} bp',
        params=body.model_dump(mode='json'),
        fn=_fn,
    )
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


def _build_extrude_deformed_continuation(d: Design, body: 'BundleDeformedContinuationRequest'):
    """Pure builder + cluster-membership report for a deformed-continuation extrude."""
    from backend.core.cluster_reconcile import MutationReport
    from backend.core.lattice import make_bundle_deformed_continuation

    frame = {
        "grid_origin": body.grid_origin,
        "axis_dir":    body.axis_dir,
        "frame_right": body.frame_right,
        "frame_up":    body.frame_up,
    }
    axes = deformed_helix_axes(d)
    deformed_endpoints = {ax["helix_id"]: {"start": ax["start"], "end": ax["end"]} for ax in axes}
    cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
    updated = make_bundle_deformed_continuation(
        d, cells, body.length_bp, frame, deformed_endpoints, body.plane,
        ref_helix_id=body.ref_helix_id,
    )
    return updated, MutationReport(
        new_helix_origins=_origins_by_grid_pos(d, updated, fallback_origin=body.ref_helix_id),
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
        op_kind='extrude-deformed-continuation',
        label=f'Extrude (deformed): {len(body.cells)} cells × {body.length_bp} bp',
        params=body.model_dump(mode='json'),
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
        op_kind='bundle-create',
        label=f'Create bundle: {body.name}',
        params=body.model_dump(mode='json'),
        fn=lambda _d: _build_bundle(cells, body),
    )
    return _design_response(new_design, report)


def _build_bundle(cells, body: 'BundleRequest') -> Design:
    """Pure builder for a fresh bundle design — used by both the create-bundle
    endpoint and the edit-feature dispatcher."""
    from backend.core.lattice import make_bundle_design, ligate_new_strands

    new_design = make_bundle_design(
        cells, body.length_bp, body.name, body.plane,
        strand_filter=body.strand_filter, lattice_type=body.lattice_type,
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
    ids: frozenset[str] | None = (
        frozenset(helix_ids.split(",")) if helix_ids else None
    )
    if apply_deformations:
        with trace.step("nucleotides"):
            nucleotides = _geometry_for_helices(design, ids)
        with trace.step("helix_axes"):
            axes = deformed_helix_axes(design)
        with trace.step("ovhg_rotations"):
            _apply_ovhg_rotations_to_axes(design, axes, nucleotides)
        out = {
            "nucleotides": nucleotides,
            "helix_axes":  axes,
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
                    update={"deformations": [], "cluster_transforms": []})
            with trace.step("straight_positions_embed"):
                straight_positions, straight_axes = _positions_for_design(straight_design)
            out["straight_positions_by_helix"] = straight_positions
            out["straight_helix_axes"]         = straight_axes
    else:
        with trace.step("strip_deformations"):
            straight = design.model_copy(update={"deformations": [], "cluster_transforms": []})
        with trace.step("nucleotides_straight"):
            nucleotides = _geometry_for_helices(straight, ids)
        with trace.step("helix_axes_straight"):
            axes = _straight_helix_axes(design)
        out = {
            "nucleotides": nucleotides,
            "helix_axes":  axes,
        }
    if ids is not None:
        # Signal to the frontend that this is a partial response — only the
        # requested helices are present and the result should be merged rather
        # than replacing the full geometry (Fix B merge path in client.js).
        out["partial_geometry"]  = True
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
    from backend.core.lattice import migrate_split_staple_domains, reconcile_all_inline_overhangs
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
    design = reconcile_all_inline_overhangs(design)
    design = _fix_stale_ovhg_pivots(design)
    design = _backfill_sub_domains_if_empty(design)
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

    Like ``/design/load``, native .nadoc content preserves absolute positions —
    recentering is only applied to non-native imports.
    """
    from backend.core.lattice import migrate_split_staple_domains, reconcile_all_inline_overhangs
    from backend.core.validator import validate_design
    try:
        design = Design.from_json(body.content)
    except Exception as exc:
        raise HTTPException(400, detail=f"Failed to parse design: {exc}") from exc
    design = migrate_split_staple_domains(design)
    design = reconcile_all_inline_overhangs(design)
    design = _fix_stale_ovhg_pivots(design)
    design = _backfill_sub_domains_if_empty(design)
    design_state.clear_history()
    design_state.set_design(design)
    report = validate_design(design)
    return _design_response(design, report)


class CadnanoImportRequest(BaseModel):
    content: str   # raw caDNAno v2 JSON string sent by the browser


class ScadnanoImportRequest(BaseModel):
    content: str            # raw scadnano JSON string sent by the browser
    name: Optional[str] = None  # filename (without extension) from the browser — overrides embedded name


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
    strand_by_id  = {s.id: s for s in design.strands}

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
        junc_bp   = adj_dom.end_bp if adj_is_before else adj_dom.start_bp
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
        h.model_copy(update={
            "axis_start": Vec3(x=h.axis_start.x - cx, y=h.axis_start.y - cy, z=h.axis_start.z),
            "axis_end":   Vec3(x=h.axis_end.x   - cx, y=h.axis_end.y   - cy, z=h.axis_end.z),
        })
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
        ct.model_copy(update={"pivot": [ct.pivot[0] - cx, ct.pivot[1] - cy, ct.pivot[2]]})
        if list(ct.pivot) != _ZERO else ct
        for ct in design.cluster_transforms
    ]
    return design.model_copy(update={"helices": new_helices, "overhangs": new_overhangs, "cluster_transforms": new_clusters})


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
        design = design.model_copy(update={"metadata": design.metadata.model_copy(update={"name": body.name})})
    design = autodetect_all_overhangs(design)
    design = _backfill_overhang_sequences(design)
    # Capture sample positions before and after re-centering for debug info.
    _pre_recenter = [(h.id, round(h.axis_start.x, 4), round(h.axis_start.y, 4)) for h in design.helices[:5]]
    design = _recenter_design(design)
    _post_recenter = [(h.id, round(h.axis_start.x, 4), round(h.axis_start.y, 4)) for h in design.helices[:5]]
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
        "sample_axes_before": [{"id": hid, "x": x, "y": y} for hid, x, y in _pre_recenter],
        "sample_axes_after":  [{"id": hid, "x": x, "y": y} for hid, x, y in _post_recenter],
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
        rows.append({
            "id":           h.id,
            "grid_pos":     list(h.grid_pos) if h.grid_pos is not None else None,
            "axis_x":       round(h.axis_start.x, 4),
            "axis_y":       round(h.axis_start.y, 4),
            "normalized_x": round(hn.axis_start.x, 4),
            "normalized_y": round(hn.axis_start.y, 4),
            "match":        abs(h.axis_start.x - hn.axis_start.x) < 0.01 and
                            abs(h.axis_start.y - hn.axis_start.y) < 0.01,
        })
    return {"helix_count": len(rows), "helices": rows}


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

    def _apply(d: Design) -> None:
        d.helices.append(new_helix)

    label = f"Add helix · {new_helix.length_bp} bp"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='helix-add',
        label=label,
        params={**body.model_dump(mode='json'), '_helix_id': new_helix.id},
        fn=_apply,
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

    # When populate_strands is set, also add a full-length scaffold + staple
    # strand to the new helix (same convention as make_bundle_design: scaffold
    # runs in the lattice direction, staple runs opposite; start_bp is the 5′ end).
    if body.populate_strands:
        N = body.length_bp
        if direction == Direction.FORWARD:
            scaf_start, scaf_end = 0, N - 1
        else:
            scaf_start, scaf_end = N - 1, 0
        staple_dir = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
        if staple_dir == Direction.FORWARD:
            stpl_start, stpl_end = 0, N - 1
        else:
            stpl_start, stpl_end = N - 1, 0

        scaffold = Strand(
            domains=[Domain(helix_id=new_helix.id, start_bp=scaf_start, end_bp=scaf_end, direction=direction)],
            strand_type=StrandType.SCAFFOLD,
        )
        staple = Strand(
            domains=[Domain(helix_id=new_helix.id, start_bp=stpl_start, end_bp=stpl_end, direction=staple_dir)],
            strand_type=StrandType.STAPLE,
        )

        def _apply(d):
            d.helices.append(new_helix)
            d.strands.append(scaffold)
            d.strands.append(staple)
    else:
        def _apply(d):
            d.helices.append(new_helix)

    label = f"Add helix at ({body.row}, {body.col}) · {body.length_bp} bp"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='helix-add-at-cell',
        label=label,
        params={**body.model_dump(mode='json'), '_helix_id': new_helix.id},
        fn=_apply,
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

    label = f"Update helix {_helix_label(design_state.get_or_404(), helix_id)}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='helix-update',
        label=label,
        params={'helix_id': helix_id, **body.model_dump(mode='json')},
        fn=_apply,
    )
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

    label = f"Extend helix {_helix_label(design, helix_id)} · bp [{new_lo}, {new_hi}]"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='helix-extend',
        label=label,
        params={'helix_id': helix_id, **body.model_dump(mode='json')},
        fn=_apply,
    )
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

    label = f"Delete helix {_helix_label(design, helix_id)}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='helix-delete',
        label=label,
        params={'helix_id': helix_id},
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

    def _apply(d: Design) -> None:
        d.strands.append(new_strand)

    label = f"Scaffold paint · helix {_helix_label(design, body.helix_id)} bp [{lo}, {hi}]"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='scaffold-domain-paint',
        label=label,
        params={**body.model_dump(mode='json'), '_strand_id': new_strand.id},
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

    def _apply(d: Design) -> None:
        d.strands.append(new_strand)

    label = f"Add {body.strand_type.value} strand · {len(body.domains)} domain(s)"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='strand-add',
        label=label,
        params={**body.model_dump(mode='json'), '_strand_id': new_strand.id, '_color': color},
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
        op_subtype='strand-update',
        label=label,
        params={'strand_id': strand_id, **body.model_dump(mode='json')},
        fn=_apply,
    )
    return {
        "strand": replacement.model_dump(),
        **_design_response(design, report),
    }


def _build_strand_end_resize(d: Design, body: 'StrandEndResizeRequest') -> Design:
    """Pure builder for a strand end resize."""
    from backend.core.lattice import resize_strand_ends
    return resize_strand_ends(d, [entry.model_dump() for entry in body.entries])


@router.post("/design/strand-end-resize", status_code=200)
def strand_end_resize(body: StrandEndResizeRequest) -> dict:
    """Resize terminal strand domains from the 3D/cadnano drag handles."""
    try:
        n = len(body.entries)
        label = f"Resize {n} strand end{'s' if n != 1 else ''}"
        updated, report, _entry = design_state.mutate_with_minor_log(
            op_subtype='strand-end-resize',
            label=label,
            params=body.model_dump(mode='json'),
            fn=lambda d: _build_strand_end_resize(d, body),
        )
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "unknown"
        raise HTTPException(404, detail=f"Resize target not found: {missing!r}") from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return _design_response_with_geometry(updated, report)


def _build_domain_shift(d: Design, body: 'DomainShiftRequest') -> Design:
    """Pure builder for a domain-shift batch."""
    from backend.core.lattice import shift_domains
    return shift_domains(d, [entry.model_dump() for entry in body.entries])


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
            op_subtype='domain-shift',
            label=label,
            params=body.model_dump(mode='json'),
            fn=lambda d: _build_domain_shift(d, body),
        )
    except KeyError as exc:
        missing = exc.args[0] if exc.args else "unknown"
        raise HTTPException(404, detail=f"Domain-shift target not found: {missing!r}") from exc
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    return _design_response_with_geometry(updated, report)


def _build_delete_strands_batch(d: Design, body: 'StrandBatchDeleteRequest') -> Design:
    """Pure builder: remove specified strands (handling linker connections too)
    and re-detect overhangs on now-orphaned ends."""
    from backend.core.lattice import autodetect_all_overhangs

    id_set = set(body.strand_ids)
    missing = id_set - {s.id for s in d.strands}
    if missing:
        raise HTTPException(404, detail=f"Strand ID(s) not found: {sorted(missing)}")

    existing_conn_ids = {conn.id for conn in d.overhang_connections}
    linker_conn_ids = {
        conn_id for strand_id in id_set
        if (conn_id := _linker_conn_id_from_strand_id(strand_id)) in existing_conn_ids
    }
    linker_strand_ids = {
        s.id for s in d.strands
        if _linker_conn_id_from_strand_id(s.id) in linker_conn_ids
    }
    regular_ids = id_set - linker_strand_ids

    out = _delete_linker_connections_from_design(d, linker_conn_ids)
    out = _delete_regular_strands_from_design(out, regular_ids)
    return autodetect_all_overhangs(out)


@router.delete("/design/strands/batch", status_code=200)
def delete_strands_batch(body: StrandBatchDeleteRequest) -> dict:
    """Delete multiple strands by ID in one operation."""
    n = len(body.strand_ids)
    label = f"Delete {n} strand{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='strand-delete-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=lambda d: _build_delete_strands_batch(d, body),
    )
    return _design_response_with_geometry(design, report)


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
    label = f"Delete strand {strand_id}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='strand-delete',
        label=label,
        params={'strand_id': strand_id},
        fn=lambda d: _build_delete_strand(d, strand_id),
    )
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

    label = (
        f"Add domain · helix {_helix_label(design_state.get_or_404(), body.helix_id)} "
        f"bp [{body.start_bp}, {body.end_bp}] {body.direction.value}"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='domain-add',
        label=label,
        params={'strand_id': strand_id, **body.model_dump(mode='json')},
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
        op_subtype='domain-delete',
        label=label,
        params={'strand_id': strand_id, 'domain_index': domain_index},
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
        for (a, b) in ((ha, hb), (hb, ha)):
            sf = three_prime.get((a.helix_id, a.index, a.strand))
            st = five_prime.get((b.helix_id, b.index, b.strand))
            if sf is not None and st is not None and sf.id == st.id:
                out.append(x.id)
                break
    return out


class PlaceCrossoverRequest(BaseModel):
    half_a:     HalfCrossoverRequest
    half_b:     HalfCrossoverRequest
    nick_bp_a:  int
    nick_bp_b:  int
    process_id: Optional[str] = "manual"


def _nick_if_needed(d: "Design", helix_id: str, bp_index: int, direction: "Direction") -> "Design":
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
        return d   # no strand covers this position — no-op
    domain = strand.domains[domain_idx]
    n_doms = len(strand.domains)
    if bp_index == domain.end_bp and domain_idx < n_doms - 1:
        return d   # inter-domain boundary (crossover junction) — no-op
    # 1-nt left stub: nick at the strand's 5′ terminal nucleotide.
    if domain_idx == 0 and bp_index == domain.start_bp:
        return d
    # 1-nt right stub: nick one step inside the strand's 3′ terminal nucleotide.
    if domain_idx == n_doms - 1:
        three_prime_stub = (
            (direction == Direction.FORWARD and bp_index == domain.end_bp - 1) or
            (direction == Direction.REVERSE and bp_index == domain.end_bp + 1)
        )
        if three_prime_stub:
            return d
    try:
        return make_nick(d, helix_id, bp_index, direction)
    except ValueError as exc:
        if "terminus" in str(exc):
            return d   # already nicked — no-op
        raise


def _build_place_crossover(d: Design, body: 'PlaceCrossoverRequest') -> tuple[Design, 'Crossover', bool]:
    """Pure builder: nick + ligate + record one crossover.

    Returns (new design, xover, ligated). `ligated` is False iff the crossover's
    two halves resolved to the same strand (would close a cycle); the crossover
    is still recorded but the strands stay split. Caller can surface a
    placement_warning.

    CROSSOVER = nick + ligate + record. If changing this, ask user first.
    """
    from backend.core.crossover_positions import validate_crossover

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
    current = _nick_if_needed(d, body.half_a.helix_id, body.nick_bp_a, body.half_a.strand)
    current = _nick_if_needed(current, body.half_b.helix_id, body.nick_bp_b, body.half_b.strand)

    err = validate_crossover(current, half_a, half_b)
    if err:
        raise HTTPException(400, detail=err)

    xover = Crossover(half_a=half_a, half_b=half_b, process_id=body.process_id)
    # Build a new crossovers list so the snapshot reference in undo history
    # is not mutated (copy_with is shallow).
    current = current.copy_with(crossovers=list(current.crossovers) + [xover])
    current, ligated = _ligate_crossover(current, xover)
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
        holder['xover'] = xover
        holder['ligated'] = ligated
        return current

    _d = design_state.get_or_404()
    label = (
        f"Crossover h{_helix_label(_d, body.half_a.helix_id)} ↔ "
        f"h{_helix_label(_d, body.half_b.helix_id)} bp {body.half_a.index}"
    )
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-place',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_fn,
    )
    resp = {
        "crossover": holder['xover'].model_dump(),
        **_design_response_with_geometry(current, report),
    }
    if not holder.get('ligated'):
        x = holder['xover']
        resp["placement_warnings"] = [
            f"Crossover at h{_helix_label(current, x.half_a.helix_id)} ↔ "
            f"h{_helix_label(current, x.half_b.helix_id)} bp {x.half_a.index} "
            "left unligated to avoid circular strand. Nick the strand to ligate."
        ]
    return resp


class PlaceCrossoverBatchRequest(BaseModel):
    placements: list[PlaceCrossoverRequest]


def _build_place_crossover_batch(d: Design, body: 'PlaceCrossoverBatchRequest') -> tuple[Design, list, list]:
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
        holder['xovers'] = new_crossovers
        holder['skipped_ids'] = skipped_ids
        return current

    n = len(body.placements)
    label = f"Place {n} crossover{'s' if n != 1 else ''}"
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-place-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_fn,
    )
    resp = {
        "crossovers": [x.model_dump() for x in holder['xovers']],
        **_design_response_with_geometry(current, report),
    }
    skipped = holder.get('skipped_ids') or []
    if skipped:
        m = len(skipped)
        resp["placement_warnings"] = [
            f"Placed {n} crossover{'s' if n != 1 else ''} — {m} left unligated to "
            f"avoid circular strand{'s' if m != 1 else ''}. Nick the strand to ligate."
        ]
    return resp


# ── Near-ends creation ────────────────────────────────────────────────────────


class NearEndCrossoverSpec(BaseModel):
    helix_id_a: str
    helix_id_b: str
    face_bp:    int       # lo of the scaffold interval being connected (domain terminus)
    new_lo:     int       # target bp after extension (= xover_bp, may be < face_bp)
    xover_bp:   int       # crossover bp index
    strand_a:   Direction # FORWARD or REVERSE — coerced from string by Pydantic
    strand_b:   Direction
    nick_bp_a:  int
    nick_bp_b:  int


class CreateNearEndsRequest(BaseModel):
    crossovers: list[NearEndCrossoverSpec]


@router.post("/design/near-ends/create", status_code=201)
def create_near_ends(body: CreateNearEndsRequest) -> dict:
    """Extend helices at the near (-Z) face and place Holliday junctions there.

    For each spec: extends the helix geometry and the scaffold domain on
    helix_id_a and helix_id_b to new_lo, then places a crossover at xover_bp.
    All operations share a single undo checkpoint.
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.crossover_positions import validate_crossover

    design = design_state.get_or_404()

    current = design

    # 1. Collect per-helix minimum required lo_bp across all specs.
    helix_new_lo: dict[str, int] = {}
    for spec in body.crossovers:
        for hid in (spec.helix_id_a, spec.helix_id_b):
            if hid not in helix_new_lo or spec.new_lo < helix_new_lo[hid]:
                helix_new_lo[hid] = spec.new_lo

    # 2. Extend helix geometry for each affected helix.
    for helix_id, new_lo in helix_new_lo.items():
        helix = _find_helix(current, helix_id)
        h_lo = helix.bp_start
        if new_lo >= h_lo:
            continue
        extra_lo = h_lo - new_lo
        ax     = helix.axis_end.to_array() - helix.axis_start.to_array()
        ax_len = float(math.sqrt(float((ax * ax).sum())))
        unit   = ax / ax_len if ax_len > 1e-9 else helix.axis_start.to_array() * 0 + [0, 0, 1]
        new_axis_start = helix.axis_start.to_array() - extra_lo * BDNA_RISE_PER_BP * unit
        updated = helix.model_copy(update={
            "axis_start":   Vec3.from_array(new_axis_start),
            "length_bp":    helix.length_bp + extra_lo,
            "bp_start":     new_lo,
            "phase_offset": helix.phase_offset - extra_lo * helix.twist_per_bp_rad,
        })
        new_helices = list(current.helices)
        for i, h in enumerate(new_helices):
            if h.id == helix_id:
                new_helices[i] = updated
                break
        current = current.copy_with(helices=new_helices)

    # 3. Extend scaffold domains per spec. Use face_bp to identify the specific
    #    domain whose lo terminus equals face_bp — critical for helices with
    #    multiple intervals (e.g. outer helices in dumbbell designs).
    for spec in body.crossovers:
        for helix_id in (spec.helix_id_a, spec.helix_id_b):
            target_si = target_di = None
            for si, strand in enumerate(current.strands):
                if strand.strand_type != StrandType.SCAFFOLD:
                    continue
                for di, dom in enumerate(strand.domains):
                    if dom.helix_id != helix_id:
                        continue
                    if min(dom.start_bp, dom.end_bp) == spec.face_bp:
                        target_si, target_di = si, di
                        break
                if target_si is not None:
                    break
            if target_si is None:
                continue
            strand = current.strands[target_si]
            dom    = strand.domains[target_di]
            if min(dom.start_bp, dom.end_bp) <= spec.new_lo:
                continue
            if dom.direction == Direction.FORWARD:
                new_dom = dom.model_copy(update={"start_bp": spec.new_lo})
            else:
                new_dom = dom.model_copy(update={"end_bp": spec.new_lo})
            new_domains = list(strand.domains)
            new_domains[target_di] = new_dom
            new_strand = strand.model_copy(update={"domains": new_domains})
            new_strands = list(current.strands)
            new_strands[target_si] = new_strand
            current = current.copy_with(strands=new_strands)

    # 4. Place crossovers (same nick + ligate + record pattern as place-batch).
    new_crossovers = []
    try:
        for spec in body.crossovers:
            half_a = HalfCrossover(helix_id=spec.helix_id_a, index=spec.xover_bp, strand=spec.strand_a)
            half_b = HalfCrossover(helix_id=spec.helix_id_b, index=spec.xover_bp, strand=spec.strand_b)
            current = _nick_if_needed(current, spec.helix_id_a, spec.nick_bp_a, spec.strand_a)
            current = _nick_if_needed(current, spec.helix_id_b, spec.nick_bp_b, spec.strand_b)
            err = validate_crossover(current, half_a, half_b)
            if err:
                raise HTTPException(400, detail=err)
            xover   = Crossover(half_a=half_a, half_b=half_b, process_id="create_near_ends")
            current = current.copy_with(crossovers=list(current.crossovers) + [xover])
            current, _ligated = _ligate_crossover(current, xover)
            new_crossovers.append(xover)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    current, report, _entry = design_state.mutate_with_feature_log(
        op_kind='create-near-ends',
        label='Create near ends',
        params={'crossover_count': len(body.crossovers)},
        fn=lambda _d: current,
    )
    return {
        "crossovers": [x.model_dump() for x in new_crossovers],
        **_design_response_with_geometry(current, report),
    }


# ── Far-ends creation ─────────────────────────────────────────────────────────


class FarEndCrossoverSpec(BaseModel):
    helix_id_a: str
    helix_id_b: str
    face_bp:    int       # hi of the scaffold interval (domain terminus at far/+Z face)
    new_hi:     int       # target bp after extension (= xover_bp, > face_bp)
    xover_bp:   int
    strand_a:   Direction
    strand_b:   Direction
    nick_bp_a:  int
    nick_bp_b:  int


class CreateFarEndsRequest(BaseModel):
    crossovers: list[FarEndCrossoverSpec]


@router.post("/design/far-ends/create", status_code=201)
def create_far_ends(body: CreateFarEndsRequest) -> dict:
    """Extend helices at the far (+Z) face and place single crossovers there.

    Mirrors create_near_ends but extends axis_end instead of axis_start.
    All specs in one request share a single undo checkpoint.
    """
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.crossover_positions import validate_crossover

    design = design_state.get_or_404()

    current = design

    # 1. Collect per-helix maximum required hi_bp across all specs.
    helix_new_hi: dict[str, int] = {}
    for spec in body.crossovers:
        for hid in (spec.helix_id_a, spec.helix_id_b):
            if hid not in helix_new_hi or spec.new_hi > helix_new_hi[hid]:
                helix_new_hi[hid] = spec.new_hi

    # 2. Extend helix geometry at the hi (far/+Z) face.
    for helix_id, new_hi in helix_new_hi.items():
        helix = _find_helix(current, helix_id)
        h_hi = helix.bp_start + helix.length_bp - 1
        if new_hi <= h_hi:
            continue
        extra_hi = new_hi - h_hi
        ax     = helix.axis_end.to_array() - helix.axis_start.to_array()
        ax_len = float(math.sqrt(float((ax * ax).sum())))
        unit   = ax / ax_len if ax_len > 1e-9 else helix.axis_start.to_array() * 0 + [0, 0, 1]
        new_axis_end = helix.axis_end.to_array() + extra_hi * BDNA_RISE_PER_BP * unit
        updated = helix.model_copy(update={
            "axis_end":  Vec3.from_array(new_axis_end),
            "length_bp": helix.length_bp + extra_hi,
        })
        new_helices = list(current.helices)
        for i, h in enumerate(new_helices):
            if h.id == helix_id:
                new_helices[i] = updated
                break
        current = current.copy_with(helices=new_helices)

    # 3. Extend scaffold domains per spec. Use face_bp to find the domain whose
    #    hi terminus equals face_bp — critical for multi-interval helices.
    for spec in body.crossovers:
        for helix_id in (spec.helix_id_a, spec.helix_id_b):
            target_si = target_di = None
            for si, strand in enumerate(current.strands):
                if strand.strand_type != StrandType.SCAFFOLD:
                    continue
                for di, dom in enumerate(strand.domains):
                    if dom.helix_id != helix_id:
                        continue
                    if max(dom.start_bp, dom.end_bp) == spec.face_bp:
                        target_si, target_di = si, di
                        break
                if target_si is not None:
                    break
            if target_si is None:
                continue
            strand = current.strands[target_si]
            dom    = strand.domains[target_di]
            if max(dom.start_bp, dom.end_bp) >= spec.new_hi:
                continue
            if dom.direction == Direction.FORWARD:
                new_dom = dom.model_copy(update={"end_bp": spec.new_hi})
            else:
                new_dom = dom.model_copy(update={"start_bp": spec.new_hi})
            new_domains = list(strand.domains)
            new_domains[target_di] = new_dom
            new_strand = strand.model_copy(update={"domains": new_domains})
            new_strands = list(current.strands)
            new_strands[target_si] = new_strand
            current = current.copy_with(strands=new_strands)

    # 4. Place crossovers.
    new_crossovers = []
    try:
        for spec in body.crossovers:
            half_a = HalfCrossover(helix_id=spec.helix_id_a, index=spec.xover_bp, strand=spec.strand_a)
            half_b = HalfCrossover(helix_id=spec.helix_id_b, index=spec.xover_bp, strand=spec.strand_b)
            current = _nick_if_needed(current, spec.helix_id_a, spec.nick_bp_a, spec.strand_a)
            current = _nick_if_needed(current, spec.helix_id_b, spec.nick_bp_b, spec.strand_b)
            err = validate_crossover(current, half_a, half_b)
            if err:
                raise HTTPException(400, detail=err)
            xover   = Crossover(half_a=half_a, half_b=half_b, process_id="create_far_ends")
            current = current.copy_with(crossovers=list(current.crossovers) + [xover])
            current, _ligated = _ligate_crossover(current, xover)
            new_crossovers.append(xover)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    current, report, _entry = design_state.mutate_with_feature_log(
        op_kind='create-far-ends',
        label='Create far ends',
        params={'crossover_count': len(body.crossovers)},
        fn=lambda _d: current,
    )
    return {
        "crossovers": [x.model_dump() for x in new_crossovers],
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

        xover = Crossover(half_a=half_a, half_b=half_b, process_id="auto_crossover")
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

    current, report, _entry = design_state.mutate_with_feature_log(
        op_kind='auto-crossover',
        label='Auto-crossover',
        params={'sites_considered': len(sites), 'placed': placed},
        fn=lambda _d: current,
    )
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
    # (No explicit design_state.snapshot() — the mutate_with_minor_log wrapper
    # at the end handles undo bookkeeping in one place.)

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

    label = (
        f"Move crossover h{_helix_label(design, xover.half_a.helix_id)} ↔ "
        f"h{_helix_label(design, xover.half_b.helix_id)} · bp {old_index} → {new_index}"
    )
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-move',
        label=label,
        params=body.model_dump(mode='json'),
        fn=lambda _d: updated,
    )
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

    n = len(moves)
    label = f"Move {n} crossover{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-move-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_apply,
    )
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

    label = (
        f"Delete crossover h{_helix_label(design, xover.half_a.helix_id)} ↔ "
        f"h{_helix_label(design, xover.half_b.helix_id)} bp {xover.half_a.index}"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-delete',
        label=label,
        params={'crossover_id': crossover_id},
        fn=_apply,
    )
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

    n = len(ids_to_delete)
    label = f"Delete {n} crossover{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-delete-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_apply,
    )
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

    n = len(id_to_seq)
    label = f"Set extra bases on {n} crossover{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-extra-bases-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_apply,
    )
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

    label = f"Extra bases on crossover {crossover_id} · {seq or '(cleared)'}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='crossover-extra-bases',
        label=label,
        params={'crossover_id': crossover_id, **body.model_dump(mode='json')},
        fn=_apply,
    )
    return _design_response_with_geometry(design, report)


@router.patch("/design/forced-ligations/{fl_id}/extra-bases", status_code=200)
def patch_forced_ligation_extra_bases(fl_id: str, body: CrossoverExtraBasesRequest) -> dict:
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
        op_subtype='forced-ligation-extra-bases',
        label=label,
        params={'fl_id': fl_id, **body.model_dump(mode='json')},
        fn=_apply,
    )
    return _design_response_with_geometry(design, report)


def _build_nick(design: Design, body: 'NickRequest') -> Design:
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
        if (s.id not in original_ids
                and s.strand_type == StrandType.STAPLE
                and s.color is None):
            new_strands_list.append(s.model_copy(update={
                "color": STAPLE_PALETTE[palette_idx % len(STAPLE_PALETTE)]
            }))
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


def _label_nick(design: Design, body: 'NickRequest') -> str:
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
        nicked_strand, _ = _find_strand_at(design, body.helix_id, body.bp_index, body.direction)
    except ValueError:
        nicked_strand = None
    changed_hids = list({dom.helix_id for dom in nicked_strand.domains}) if nicked_strand else [body.helix_id]

    label = _label_nick(design, body)
    try:
        updated, report, _entry = design_state.mutate_with_minor_log(
            op_subtype='nick',
            label=label,
            params=body.model_dump(mode='json'),
            fn=lambda d: _build_nick(d, body),
        )
    except ValueError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

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
    design = design_state.get_or_404()

    helix_id  = body.helix_id
    bp_index  = body.bp_index
    direction = body.direction
    adj_bp    = bp_index + 1 if direction == Direction.FORWARD else bp_index - 1
    label = f"Ligate helix {_helix_label(design, helix_id)} bp {bp_index} {direction.value}"

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

                design, report, _entry = design_state.mutate_with_minor_log(
                    op_subtype='ligate',
                    label=label,
                    params=body.model_dump(mode='json'),
                    fn=_apply_merge,
                )
                return _design_response(design, report)

    # ── Cross-strand ligation ────────────────────────────────────────────────
    # Find strand A: 3′ terminus at bp_index
    strand_a: Strand | None = None
    idx_a: int = -1
    for i, s in enumerate(design.strands):
        if not s.domains:
            continue
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
        if not s.domains:
            continue
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

    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='ligate',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_apply,
    )
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

    label = (
        f"Forced ligation · h{_helix_label(design, three_dom.helix_id)}:{three_dom.end_bp} "
        f"→ h{_helix_label(design, five_dom.helix_id)}:{five_dom.start_bp}"
    )
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='forced-ligation-create',
        label=label,
        params={**body.model_dump(mode='json'), '_fl_id': fl.id},
        fn=lambda _d: current,
    )
    return _design_response_with_geometry(current, report)


@router.delete("/design/forced-ligations/{fl_id}", status_code=200)
def delete_forced_ligation(fl_id: str) -> dict:
    """Remove a forced ligation by ID.

    Splits the strand at the forced-ligation junction back into two fragments
    and removes the ForcedLigation record from the design.
    """

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

    label = (
        f"Delete forced ligation · h{_helix_label(design, fl.three_prime_helix_id)}:{fl.three_prime_bp} "
        f"→ h{_helix_label(design, fl.five_prime_helix_id)}:{fl.five_prime_bp}"
    )
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='forced-ligation-delete',
        label=label,
        params={'fl_id': fl_id},
        fn=_apply,
    )
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

    n = len(ids_to_delete)
    label = f"Delete {n} forced ligation{'s' if n != 1 else ''}"
    design, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='forced-ligation-delete-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_apply,
    )
    return _design_response_with_geometry(design, report)


def _build_nick_batch(d: Design, body: 'NickBatchRequest') -> Design:
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
            nicked_strand, _ = _find_strand_at(design, nick.helix_id, nick.bp_index, nick.direction)
            all_changed.update(dom.helix_id for dom in nicked_strand.domains)
        except ValueError:
            all_changed.add(nick.helix_id)

    n = len(body.nicks)
    label = f"{n} nick{'s' if n != 1 else ''} (batch)"
    current, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='nick-batch',
        label=label,
        params=body.model_dump(mode='json'),
        fn=lambda d: _build_nick_batch(d, body),
    )
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


def _build_overhang_extrude(d: Design, body: 'OverhangExtrudeRequest') -> tuple[Design, 'MutationReport']:
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
    from backend.core.lattice import make_overhang_extrude

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
        op_kind='overhang-extrude',
        label=f'Overhang extrude: {body.length_bp} bp',
        params=body.model_dump(mode='json'),
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
    rotation: list[float] | None = None  # unit quaternion [qx, qy, qz, qw]; None = no change


def _build_overhang_patch(design: Design, overhang_id: str, body: 'OverhangPatchRequest') -> tuple[Design, dict, OverhangSpec]:
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
    inline_end: str | None = overhang_id.rsplit("_", 1)[-1] if is_inline else None  # "5p" or "3p"

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
            raise HTTPException(422, detail="rotation must be a length-4 quaternion [qx, qy, qz, qw].")
        import math as _math_rot
        mag = _math_rot.sqrt(sum(x * x for x in body.rotation))
        if abs(mag) < 1e-9:
            raise HTTPException(422, detail="rotation quaternion must not be zero-length.")
        # Normalise to unit quaternion in case of minor floating-point drift.
        spec_updates["rotation"] = [x / mag for x in body.rotation]

    # ── Sub-domain override conflict guard ──────────────────────────────────
    # A whole-overhang sequence write is incompatible with sub-domain
    # overrides because the override slices would be silently overwritten.
    # Require the user to clear them first (Phase 1 design contract).
    if sequence_was_set and body.sequence is not None:
        conflicting = [
            sd.id for sd in (spec.sub_domains or [])
            if sd.sequence_override is not None
        ]
        if conflicting:
            raise HTTPException(409, detail={
                "detail": "Sub-domain overrides conflict with whole-overhang sequence write",
                "sub_domain_ids": conflicting,
            })

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
            sub_doms_sorted = sorted(spec.sub_domains, key=lambda sd: sd.start_bp_offset)
            last = sub_doms_sorted[-1]
            new_last_len = last.length_bp + delta
            if new_last_len < 1:
                raise HTTPException(422, detail=(
                    f"Shrink would reduce sub-domain {last.name!r} ({last.id}) "
                    f"below 1 bp; delete it (or another sub-domain) first."
                ))
            if last.sequence_override is not None and new_last_len < len(last.sequence_override):
                raise HTTPException(422, detail=(
                    f"Shrink would shorten sub-domain {last.name!r} ({last.id}) "
                    f"below its locked override length ({len(last.sequence_override)} bp); "
                    f"clear the override first."
                ))
            new_sub_doms = [sd for sd in sub_doms_sorted[:-1]]
            new_sub_doms.append(last.model_copy(update={
                "length_bp": new_last_len,
                # Annotation caches are stale once length changes.
                "tm_celsius": None,
                "gc_percent": None,
                "hairpin_warning": False,
                "dimer_warning": False,
            }))
            spec_updates["sub_domains"] = new_sub_doms
    elif new_length_bp is not None and not spec.sub_domains:
        # Edge case: backfill validator hasn't run (shouldn't happen post-load
        # because validators are always invoked). Insert a single whole-overhang
        # sub-domain matching the new length.
        from backend.core.models import SubDomain as _SubDomain, NADOC_SUBDOMAIN_NS as _NS
        import uuid as _uuid_local
        spec_updates["sub_domains"] = [_SubDomain(
            id=str(_uuid_local.uuid5(_NS, f"{spec.id}:whole")),
            name="a",
            start_bp_offset=0,
            length_bp=new_length_bp,
        )]

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
                ax_len = _math.sqrt(ax[0]**2 + ax[1]**2 + ax[2]**2)
                if ax_len < 1e-9:
                    break
                unit = ax / ax_len
                if extrude_junction_bp is None:
                    # Fall back to legacy +Z behaviour if no crossover record.
                    new_len_nm = new_length_bp * BDNA_RISE_PER_BP
                    new_end = helix.axis_start.to_array() + unit * new_len_nm
                    new_helices[hi] = helix.model_copy(update={
                        "length_bp": new_length_bp,
                        "axis_end":  Vec3(x=float(new_end[0]), y=float(new_end[1]), z=float(new_end[2])),
                    })
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
                junction_world = helix.axis_start.to_array() + local_junc_old * BDNA_RISE_PER_BP * unit
                # New axis_start = junction_world − (junction_local_new) * RISE * unit.
                local_junc_new = extrude_junction_bp - new_bp_start
                new_axis_start = junction_world - local_junc_new * BDNA_RISE_PER_BP * unit
                new_axis_end = new_axis_start + new_length_bp * BDNA_RISE_PER_BP * unit
                new_helices[hi] = helix.model_copy(update={
                    "length_bp":  new_length_bp,
                    "bp_start":   new_bp_start,
                    "axis_start": Vec3(x=float(new_axis_start[0]), y=float(new_axis_start[1]), z=float(new_axis_start[2])),
                    "axis_end":   Vec3(x=float(new_axis_end[0]),   y=float(new_axis_end[1]),   z=float(new_axis_end[2])),
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
                    # Extrude-style: keep the junction bp fixed; move only the
                    # tip endpoint of the domain. The tip is whichever endpoint
                    # is NOT the junction. Works for +Z and −Z extrudes.
                    if extrude_junction_bp is None:
                        # Legacy fallback (no crossover record found).
                        if is_fwd:
                            new_domain = domain.model_copy(update={"end_bp": domain.start_bp + new_length_bp - 1})
                        else:
                            new_domain = domain.model_copy(update={"start_bp": domain.end_bp + new_length_bp - 1})
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
                new_strands[si] = strand.model_copy(update={"domains": new_domains, "sequence": None})
                break

    updated = design.model_copy(update={
        "helices":   new_helices,
        "strands":   new_strands,
        "overhangs": new_overhangs,
    })

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

    # Append rotation to feature log when rotation was changed.
    if body.rotation is not None:
        from backend.core.models import OverhangRotationLogEntry
        log = list(updated.feature_log)
        if updated.feature_log_cursor == -2:
            log = []
        elif updated.feature_log_cursor >= 0:
            log = log[:updated.feature_log_cursor + 1]
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
    rotation_only = (
        body.rotation is not None
        and "sequence" not in body.model_fields_set
        and body.label is None
    )
    if rotation_only:
        # Full geometry (no partial flag) forces a complete scene rebuild on the
        # frontend so backbone positions and slab normals are read fresh from the
        # server-computed arrays rather than relying on the in-memory preview state.
        return _design_response_with_geometry(updated, report)
    return _design_response(updated, report)


class OverhangRotationBatchItem(BaseModel):
    overhang_id: str
    rotation: List[float]   # [qx, qy, qz, qw]


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
            raise HTTPException(422, detail="rotation must be a length-4 quaternion [qx, qy, qz, qw].")
        mag = _math_b.sqrt(sum(x * x for x in item.rotation))
        if abs(mag) < 1e-9:
            raise HTTPException(422, detail="rotation quaternion must not be zero-length.")
        normalised.append(OverhangRotationBatchItem(
            overhang_id=item.overhang_id,
            rotation=[x / mag for x in item.rotation],
        ))

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
        log = log[:design.feature_log_cursor + 1]

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
    phi_deg:   float
    commit:    bool = False


def _validate_sd_angles(theta_deg: float, phi_deg: float) -> None:
    import math as _math
    if not _math.isfinite(float(theta_deg)) or not _math.isfinite(float(phi_deg)):
        raise HTTPException(422, detail="theta_deg and phi_deg must be finite.")
    if not (-180.0 <= float(theta_deg) <= 180.0):
        raise HTTPException(422, detail=f"theta_deg out of range [-180, 180]: {theta_deg}")
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
        raise HTTPException(404, detail=(
            f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))
    new_sd = sd.model_copy(update={
        'rotation_theta_deg': float(theta_deg),
        'rotation_phi_deg':   float(phi_deg),
    })
    new_sds = [new_sd if s.id == sub_domain_id else s for s in spec.sub_domains]
    new_spec = spec.model_copy(update={'sub_domains': new_sds})
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
    if last.feature_type != 'overhang_rotation':
        return False
    if len(last.overhang_ids) != 1:
        return False
    if last.overhang_ids[0] != overhang_id:
        return False
    sd_ids = last.sub_domain_ids
    if len(sd_ids) != 1 or sd_ids[0] != sub_domain_id:
        return False

    import datetime as _dt
    ts = getattr(last, 'timestamp', '') or ''
    now = _dt.datetime.now(_dt.timezone.utc)
    try:
        prev_ts = _dt.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if (now - prev_ts).total_seconds() > _SUBDOMAIN_COALESCE_WINDOW_S:
        return False

    # Update in place.
    last.sub_domain_thetas_deg[0] = float(theta_deg)
    last.sub_domain_phis_deg[0]   = float(phi_deg)
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
        raise HTTPException(404, detail=(
            f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))

    updated = _set_subdomain_angles(
        design, overhang_id, sub_domain_id, body.theta_deg, body.phi_deg,
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
        log = log[:updated.feature_log_cursor + 1]

    label = spec.label
    if not _try_coalesce_subdomain_rotation_entry(
        log, overhang_id, sub_domain_id, body.theta_deg, body.phi_deg, label,
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
            entry.__dict__['timestamp'] = _dt.datetime.now(_dt.timezone.utc).isoformat()
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
    phi_deg:   float


class SubDomainRotationBatchBody(BaseModel):
    ops: List[SubDomainRotationBatchOp]
    commit: bool = False


@router.patch(
    "/design/overhang/{overhang_id}/sub-domains/rotations-batch",
    status_code=200,
)
def patch_sub_domain_rotations_batch(
    overhang_id: str, body: SubDomainRotationBatchBody,
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
            raise HTTPException(422, detail=(
                f"Duplicate sub_domain_id in batch: {op.sub_domain_id!r}."
            ))
        seen.add(op.sub_domain_id)
        if op.sub_domain_id not in sd_by_id:
            raise HTTPException(404, detail=(
                f"Sub-domain {op.sub_domain_id!r} not found on overhang "
                f"{overhang_id!r}."
            ))
        _validate_sd_angles(op.theta_deg, op.phi_deg)

    updated = design
    for op in body.ops:
        updated = _set_subdomain_angles(
            updated, overhang_id, op.sub_domain_id, op.theta_deg, op.phi_deg,
        )

    if not body.commit:
        design_state.set_design_silent(updated)
        report = validate_design(updated)
        return _design_response_with_geometry(updated, report)

    log = list(updated.feature_log)
    if updated.feature_log_cursor == -2:
        log = []
    elif updated.feature_log_cursor >= 0:
        log = log[:updated.feature_log_cursor + 1]

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
        entry.__dict__['timestamp'] = _dt.datetime.now(_dt.timezone.utc).isoformat()
    except Exception:
        pass
    updated = updated.copy_with(
        feature_log=log + [entry], feature_log_cursor=-1,
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
        raise HTTPException(404, detail=(
            f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))

    # Find the overhang's backing domain.
    strand = next((s for s in design.strands if s.id == spec.strand_id), None)
    if strand is None:
        raise HTTPException(409, detail=(
            f"Overhang {overhang_id!r} has no backing strand."
        ))
    dom_idx = next(
        (i for i, d in enumerate(strand.domains) if d.overhang_id == overhang_id),
        None,
    )
    if dom_idx is None:
        raise HTTPException(409, detail=(
            f"Overhang {overhang_id!r} backing domain missing."
        ))
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
        raise HTTPException(409, detail=(
            f"Helix {spec.helix_id!r} not found for overhang {overhang_id!r}."
        ))

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
    mask = (arrs['bp_indices'] == junction_side_bp) & (arrs['directions'] == dir_int)
    if not mask.any():
        raise HTTPException(409, detail=(
            f"Could not locate pivot bp {junction_side_bp} on helix "
            f"{spec.helix_id!r}; design may need geometry rebuild."
        ))

    pivot = arrs['positions'][mask][0].astype(float)
    pa    = arrs['axis_tangents'][mask][0].astype(float)
    pa_norm = float(_np.linalg.norm(pa))
    if pa_norm < 1e-9:
        pa = _np.array([0.0, 0.0, 1.0])
    else:
        pa = pa / pa_norm
    pr = _default_phi_ref(pa)

    return {
        "pivot":       [float(pivot[0]), float(pivot[1]), float(pivot[2])],
        "parent_axis": [float(pa[0]),    float(pa[1]),    float(pa[2])],
        "phi_ref":     [float(pr[0]),    float(pr[1]),    float(pr[2])],
    }


_IDENTITY_QUAT_LIST = [0.0, 0.0, 0.0, 1.0]


class StrandPatchRequest(BaseModel):
    notes: str | None = None
    color: str | None = None   # "#RRGGBB" hex string, or None to reset to palette
    sequence: str | None = None  # Only null is accepted (to clear the assembled sequence)


@router.patch("/design/strand/{strand_id}", status_code=200)
def patch_strand(strand_id: str, body: StrandPatchRequest) -> dict:
    """Update editable metadata on a strand (notes, color, and/or sequence).

    Pass ``sequence: null`` to clear an assembled strand sequence back to
    the unsequenced state (displayed as N×length in the spreadsheet).

    Pushes an undo snapshot before modifying so the change can be reverted.
    """

    design = design_state.get_or_404()
    strand = design.find_strand(strand_id)
    if strand is None:
        raise HTTPException(404, detail=f"Strand {strand_id!r} not found.")

    patch: dict = {}
    if body.notes is not None or "notes" in body.model_fields_set:
        patch["notes"] = body.notes
    if body.color is not None or "color" in body.model_fields_set:
        patch["color"] = body.color
    if "sequence" in body.model_fields_set and body.sequence is None:
        patch["sequence"] = None

    new_strands = [
        s.model_copy(update=patch) if s.id == strand_id else s
        for s in design.strands
    ]
    new_overhangs = design.overhangs
    if "sequence" in patch:
        strand_overhang_ids = {d.overhang_id for d in strand.domains if d.overhang_id is not None}
        if strand_overhang_ids:
            new_overhangs = [
                o.model_copy(update={"sequence": None}) if o.id in strand_overhang_ids else o
                for o in design.overhangs
            ]
    updated = design.model_copy(update={"strands": new_strands, "overhangs": new_overhangs})

    bits = []
    if 'color' in patch:    bits.append(f"color={patch['color']}")
    if 'notes' in patch:    bits.append('notes')
    if 'sequence' in patch: bits.append('seq cleared')
    label = f"Patch strand {strand_id}" + (f" · {', '.join(bits)}" if bits else "")
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='strand-patch',
        label=label,
        params={'strand_id': strand_id, **body.model_dump(mode='json', exclude_unset=True)},
        fn=lambda _d: updated,
    )
    return _design_response(updated, report)


class BulkColorRequest(BaseModel):
    strand_ids: list[str]
    color: str | None = None   # "#RRGGBB" hex string, or None to reset to palette


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
    label = f"Color {n} strand{'s' if n != 1 else ''} · {body.color or '(palette reset)'}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='strands-color-bulk',
        label=label,
        params=body.model_dump(mode='json'),
        fn=lambda _d: updated,
    )
    return _design_response(updated, report)


# ── Autostaple: autobreak + auto-merge ────────────────────────────────────────


@router.post("/design/auto-break", status_code=200)
def auto_break(payload: dict | None = Body(None)) -> dict:
    """Nick all non-scaffold strands at major tick marks (every 7 bp HC / 8 bp SQ),
    producing segments as long as possible without exceeding 60 nt.
    The sandwich rule (no long-short-long domain pattern) overrides the length
    preference.  Apply after auto-crossover.

    Emits a ``snapshot`` feature-log entry so the operation can be reverted
    even after a browser refresh (POST ``/design/features/{index}/revert``).
    """
    from backend.core.lattice import make_autobreak, make_nicks_for_autostaple

    algo = (payload or {}).get('algorithm', 'basic')
    if algo in ('basic', 'advanced'):
        # Advanced thermodynamic optimizer disabled — too slow.  Falls back to basic.
        run = make_nicks_for_autostaple
    else:
        run = make_autobreak

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='auto-break',
        label='Autobreak',
        params={'algorithm': algo},
        fn=lambda d: run(d),
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
        op_kind='auto-merge',
        label='Auto-merge staples',
        params={},
        fn=lambda d: make_merge_short_staples(d),
    )
    return _design_response(updated, report)


# ── Sequence assignment endpoints ─────────────────────────────────────────────


class _ScaffoldSeqBody(BaseModel):
    scaffold_name: str = "M13mp18"
    custom_sequence: Optional[str] = None  # if set, overrides scaffold_name
    strand_id: Optional[str] = None        # target strand (multi-scaffold support)


class _AutoScaffoldBody(BaseModel):
    seam_tol: int = 5
    end_tol: int = 5
    preserve_manual: bool = True
    max_backtracks: int = 100_000


def _run_auto_scaffold_with_feature_log(
    op_kind: str,
    label: str,
    params: dict,
    runner,
):
    """Shared helper: run an auto-scaffold variant under mutate_with_feature_log,
    threading the algorithm's `result` object back out via a closure.

    `runner(design)` must return ``(updated_design, result)``. If ``result.valid``
    is False, raises HTTPException 422.
    """
    holder: dict = {}

    def _fn(d):
        try:
            updated, result = runner(d)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        if hasattr(result, 'valid') and not result.valid:
            raise HTTPException(status_code=422, detail="; ".join(result.errors))
        holder['result'] = result
        return updated

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind=op_kind, label=label, params=params, fn=_fn,
    )
    return updated, report, holder['result']


@router.post("/design/auto-scaffold", status_code=200)
def auto_scaffold_endpoint(body: _AutoScaffoldBody = _AutoScaffoldBody()) -> dict:
    """Route scaffold through all helices using constraint-satisfaction search.

    Finds a Hamiltonian path through all scaffold domains with alternating
    seam/end crossovers.  Returns the updated design and a list of warnings.

    Body fields:
    - ``seam_tol``: bp tolerance for seam classification (default 5).
    - ``end_tol``: bp tolerance for end classification (default 5).
    - ``preserve_manual``: prefer existing scaffold crossovers (default true).
    - ``max_backtracks``: CSP search budget (default 100 000).
    """
    from backend.core.scaffold_router import auto_scaffold

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind='auto-scaffold',
        label='Auto-scaffold',
        params=body.model_dump(),
        runner=lambda d: auto_scaffold(
            d,
            seam_tol=body.seam_tol,
            end_tol=body.end_tol,
            preserve_manual=body.preserve_manual,
            max_backtracks=body.max_backtracks,
        ),
    )
    resp = _design_response(updated, report)
    resp["warnings"] = result.warnings
    return resp


@router.post("/design/auto-scaffold-seamed", status_code=200)
def auto_scaffold_seamed_endpoint() -> dict:
    """Seamed scaffold routing: Create Seam + Create Near Ends + Create Far Ends atomically.

    Computes the Hamiltonian path through scaffold helices, places Holliday-junction
    seam crossovers at interior pairs, extends and connects the near (-lo) face, then
    extends and connects the far (+hi) face.  All three phases share one snapshot.
    """
    from backend.core.seamed_router import auto_scaffold_seamed

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind='auto-scaffold-seamed',
        label='Auto-scaffold (seamed)',
        params={},
        runner=lambda d: auto_scaffold_seamed(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"]         = result.warnings
    resp["seam_xovers"]      = result.seam_xovers
    resp["near_end_xovers"]  = result.near_end_xovers
    resp["far_end_xovers"]   = result.far_end_xovers
    return resp


@router.post("/design/auto-scaffold-advanced-seamed", status_code=200)
def auto_scaffold_advanced_seamed_endpoint() -> dict:
    """Experimental seamed scaffold routing with manual scaffold anchors."""
    from backend.core.seamed_router import auto_scaffold_advanced_seamed

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind='auto-scaffold-seamed',
        label='Auto-scaffold (advanced seamed)',
        params={'advanced': True},
        runner=lambda d: auto_scaffold_advanced_seamed(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"]         = result.warnings
    resp["seam_xovers"]      = result.seam_xovers
    resp["near_end_xovers"]  = result.near_end_xovers
    resp["far_end_xovers"]   = result.far_end_xovers
    resp["advanced_bridge_xovers"] = result.advanced_bridge_xovers
    resp["advanced"]         = True
    return resp


@router.post("/design/auto-scaffold-seamless", status_code=200)
def auto_scaffold_seamless_endpoint() -> dict:
    """Seamless scaffold routing: one end crossover per helix pair (zig-zag).

    Computes a Hamiltonian path through scaffold helices, places HJ bridges
    between coverage-signature groups (multi-section designs like dumbbells),
    then places a single end crossover per within-group adjacent pair,
    alternating hi/lo face based on helix parity.
    """
    from backend.core.seamless_router import auto_scaffold_seamless

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind='auto-scaffold-seamless',
        label='Auto-scaffold (seamless)',
        params={},
        runner=lambda d: auto_scaffold_seamless(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"]      = result.warnings
    resp["end_xovers"]    = result.end_xovers
    resp["bridge_xovers"] = result.bridge_xovers
    return resp


@router.post("/design/auto-scaffold-advanced-seamless", status_code=200)
def auto_scaffold_advanced_seamless_endpoint() -> dict:
    """Experimental seamless scaffold routing entry point.

    Currently delegates to the production seamless router so advanced UI flows
    can be tested before the experimental planner lands.
    """
    from backend.core.seamless_router import auto_scaffold_seamless

    updated, report, result = _run_auto_scaffold_with_feature_log(
        op_kind='auto-scaffold-seamless',
        label='Auto-scaffold (advanced seamless)',
        params={'advanced': True},
        runner=lambda d: auto_scaffold_seamless(d),
    )
    resp = _design_response_with_geometry(updated, report)
    resp["warnings"]      = result.warnings
    resp["end_xovers"]    = result.end_xovers
    resp["bridge_xovers"] = result.bridge_xovers
    resp["advanced"]      = True
    return resp


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
    updated, report = design_state.set_design_silent_reconciled(updated, design)
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
    from fastapi import HTTPException

    design = design_state.get_or_404()
    design_state.snapshot()
    if design.overhangs:
        cleared_overhangs = [o.model_copy(update={"sequence": None}) for o in design.overhangs]
        design = design.model_copy(update={"overhangs": cleared_overhangs})
    try:
        updated = assign_staple_sequences(design)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    updated, report = design_state.set_design_silent_reconciled(updated, design)
    return _design_response(updated, report)


# ── Overhang random-sequence generation ───────────────────────────────────────



def _ovhg_domain_lengths(design) -> dict:
    """Return {overhang_id: domain_length_bp} for every overhang domain.

    Uses abs() because REVERSE-direction domains have start_bp > end_bp.
    """
    result = {}
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id is not None:
                result[domain.overhang_id] = abs(domain.end_bp - domain.start_bp) + 1
    return result


def _resplice_overhang_in_strand(design, overhang_id: str, strand_id: str):
    """Re-derive and update the sequence for only the strand that owns the overhang.

    If the strand already has an assembled sequence (from assign_staple_sequences)
    this re-derives it using the updated overhang spec so the new random sequence
    appears in the correct position while the rest of the strand is preserved.
    Silently no-ops when the strand has no sequence or there is no scaffold sequence.
    """
    from backend.core.sequences import assign_staple_sequences

    strand = design.find_strand(strand_id)
    if strand is None or strand.sequence is None:
        return design

    scaffold = design.scaffold()
    if scaffold is None or scaffold.sequence is None:
        return design

    try:
        re_derived = assign_staple_sequences(design)
    except Exception:
        return design

    new_seq = next((s.sequence for s in re_derived.strands if s.id == strand_id), None)
    if new_seq is None:
        return design

    new_strands = [
        s.model_copy(update={"sequence": new_seq}) if s.id == strand_id else s
        for s in design.strands
    ]
    return design.model_copy(update={"strands": new_strands})


@router.delete("/design/overhangs", status_code=200)
def clear_all_overhangs() -> dict:
    """Remove all OverhangSpec objects and clear overhang_id on all domains.

    Emits a ``snapshot`` feature-log entry so the bulk delete can be reverted
    even after a browser refresh.
    """
    def _build(d: Design) -> Design:
        new_strands = [
            s.model_copy(update={"domains": [
                dm.model_copy(update={"overhang_id": None}) for dm in s.domains
            ]}) for s in d.strands
        ]
        return d.model_copy(update={"strands": new_strands, "overhangs": []})

    overhang_count = len(design_state.get_or_404().overhangs)
    design, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
        label='Clear all overhangs',
        params={'overhang_count_before': overhang_count, 'action': 'clear-all'},
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

    labels = [
        (o.label or o.id)
        for o in design.overhangs
        if o.id in expanded_ids
    ]

    def _build(d: Design) -> Design:
        conn_ids = {
            c.id for c in d.overhang_connections
            if c.overhang_a_id in expanded_ids or c.overhang_b_id in expanded_ids
        }
        out = _delete_linker_connections_from_design(d, conn_ids)
        remove_binding_ids = {
            b.id for b in out.overhang_bindings
            if b.overhang_a_id in expanded_ids or b.overhang_b_id in expanded_ids
        }
        bindings = list(out.overhang_bindings)
        affected_joint_ids = {
            b.target_joint_id for b in bindings
            if b.id in remove_binding_ids and b.target_joint_id is not None
        }
        fallback_windows: dict[str, tuple[float, float]] = {}
        for jid in affected_joint_ids:
            removed = [
                b for b in bindings
                if b.id in remove_binding_ids and b.target_joint_id == jid
            ]
            removed.sort(key=lambda b: (b.created_at, b.id))
            snapshot_src = next(
                (
                    b for b in removed
                    if b.prior_min_angle_deg is not None and b.prior_max_angle_deg is not None
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
                b for b in bindings
                if b.id not in remove_binding_ids and b.target_joint_id == jid
            ]
            heirs.sort(key=lambda b: (b.created_at, b.id))
            if heirs:
                heir = heirs[0]
                if heir.prior_min_angle_deg is None and heir.prior_max_angle_deg is None:
                    new_heir = heir.model_copy(update={
                        "prior_min_angle_deg": snapshot_src.prior_min_angle_deg,
                        "prior_max_angle_deg": snapshot_src.prior_max_angle_deg,
                    })
                    bindings = [new_heir if b.id == heir.id else b for b in bindings]

        def _domain_len(dm: Domain) -> int:
            return abs(int(dm.end_bp) - int(dm.start_bp)) + 1

        new_strands = []
        for strand in out.strands:
            new_domains = []
            seq_parts: list[str] = []
            seq_offset = 0
            has_exact_sequence = strand.sequence is not None and len(strand.sequence) == sum(
                _domain_len(dm) for dm in strand.domains
            )
            for dm in strand.domains:
                n = _domain_len(dm)
                if dm.overhang_id in expanded_ids:
                    seq_offset += n
                    continue
                new_domains.append(dm)
                if has_exact_sequence:
                    seq_parts.append(strand.sequence[seq_offset:seq_offset + n])
                seq_offset += n
            if not new_domains:
                continue
            updates: dict = {"domains": new_domains}
            if has_exact_sequence:
                updates["sequence"] = "".join(seq_parts)
            new_strands.append(strand.model_copy(update=updates))

        covered_helix_ids = {
            dm.helix_id
            for strand in new_strands
            for dm in strand.domains
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
                lo <= bp <= hi
                for lo, hi in slot_cov.get(f"{helix_id}_{direction}", [])
            )

        new_crossovers = [
            xo for xo in out.crossovers
            if _covered(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
            and _covered(xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
        ]

        new_bindings = [
            b for b in bindings
            if b.id not in remove_binding_ids
        ]
        new_overhangs = [o for o in out.overhangs if o.id not in expanded_ids]
        out = out.model_copy(update={
            "strands": new_strands,
            "helices": new_helices,
            "crossovers": new_crossovers,
            "overhangs": new_overhangs,
            "overhang_bindings": new_bindings,
        })
        for jid in affected_joint_ids:
            out = _apply_driver_to_joint(out, jid)
            if _select_driver_for_joint(out, jid) is None and _first_claimant_for_joint(out, jid) is None:
                fallback = fallback_windows.get(jid)
                if fallback is not None:
                    min_angle, max_angle = fallback
                    out = out.model_copy(update={
                        "cluster_joints": [
                            j.model_copy(update={
                                "min_angle_deg": min_angle,
                                "max_angle_deg": max_angle,
                            }) if j.id == jid else j
                            for j in out.cluster_joints
                        ],
                    })
        return out

    n = len(expanded_ids)
    label = f"Delete {n} overhang{'s' if n != 1 else ''}"
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
        label=label,
        params={
            'action': 'delete-selected',
            'overhang_ids': sorted(expanded_ids),
            'labels': labels,
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
        s.sequence for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]
    seq = generate_overhang_sequences(
        scaffold_seq, staple_seqs, length=body.length, count=1,
    )[0]
    return {"sequence": seq}


@router.post("/design/overhang/{overhang_id}/generate-random", status_code=200)
def generate_overhang_random_sequence(overhang_id: str) -> dict:
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
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    lengths = _ovhg_domain_lengths(design)
    domain_len = lengths.get(overhang_id)
    if domain_len is None:
        raise HTTPException(404, detail=f"No domain references overhang {overhang_id!r}.")

    scaffold = design.scaffold()
    scaffold_seq = scaffold.sequence if scaffold and scaffold.sequence else ""
    staple_seqs = [
        s.sequence for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]
    # Honour locked sub-domain overrides: only re-roll the unlocked slices.
    sub_doms = list(spec.sub_domains or [])
    if sub_doms and any(sd.sequence_override for sd in sub_doms):
        seq = generate_overhang_sequence_with_overrides(scaffold_seq, staple_seqs, sub_doms)
    else:
        seq = generate_overhang_sequences(scaffold_seq, staple_seqs, length=domain_len, count=1)[0]
    new_overhangs = [
        spec.model_copy(update={"sequence": seq}) if o.id == overhang_id else o
        for o in design.overhangs
    ]
    updated = design.model_copy(update={"overhangs": new_overhangs})

    # Splice new overhang sequence into the strand's assembled sequence (if present),
    # leaving all non-overhang bases unchanged.
    updated = _resplice_overhang_in_strand(updated, overhang_id, spec.strand_id)

    # Phase 3: rescan boundaries for hairpins spanning adjacent sub-domains
    # (the generator already filters per-sub-domain hairpins, but a junction
    # window can still form one).
    updated = _apply_boundary_hairpin_warnings(updated, overhang_id)

    design_state.set_design(updated)
    report = validate_design(updated)
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
        s.sequence for s in design.strands
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
                scaffold_seq, staple_seqs + extra_seqs, sub_doms,
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
            new_overhangs.append(spec.model_copy(update={"sequence": generated[spec.id]}))
            affected_strand_ids.add(spec.strand_id)
            count += 1
        else:
            new_overhangs.append(spec)

    updated = design.model_copy(update={"overhangs": new_overhangs})

    # Re-derive assembled sequences for affected strands (only if scaffold is sequenced).
    scaffold = updated.scaffold()
    if scaffold is not None and scaffold.sequence is not None:
        strands_with_seq = {s.id for s in design.strands if s.sequence is not None}
        to_update = affected_strand_ids & strands_with_seq
        if to_update:
            try:
                re_derived = assign_staple_sequences(updated)
                re_seq_map = {s.id: s.sequence for s in re_derived.strands if s.id in to_update}
                new_strands = [
                    s.model_copy(update={"sequence": re_seq_map[s.id]}) if s.id in re_seq_map else s
                    for s in updated.strands
                ]
                updated = updated.model_copy(update={"strands": new_strands})
            except Exception:
                pass

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
        label='Generate overhang sequences',
        params={'generated_count': count, 'action': 'generate-sequences'},
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


def _ovhg_backing_length(design: Design, overhang_id: str) -> Optional[int]:
    """Resolve the backing-domain length for a given overhang id.

    Returns None when no domain references the overhang (e.g. orphaned spec).
    Mirrors the convention used by ``_ovhg_domain_lengths``.
    """
    for strand in design.strands:
        for domain in strand.domains:
            if domain.overhang_id == overhang_id:
                return abs(domain.end_bp - domain.start_bp) + 1
    return None


def _validate_sub_domain_tiling(design: Design, overhang_id: str) -> None:
    """Raise HTTP 422 if the overhang's sub-domain tiling is broken.

    Invariants enforced:
      • Σ length_bp == backing domain length.
      • Offsets contiguous (each sd.start_bp_offset == previous end).
      • Every length_bp ≥ 1.
      • Each ``sequence_override`` (if set) has length == length_bp and bases
        in ACGTN.

    Designed to run after every mutating sub-domain endpoint.
    """
    ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
    if ovhg is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    sub_doms = sorted(ovhg.sub_domains, key=lambda sd: sd.start_bp_offset)
    if not sub_doms:
        raise HTTPException(422, detail=f"Overhang {overhang_id!r} has no sub-domains.")

    expected_offset = 0
    for sd in sub_doms:
        if sd.length_bp < 1:
            raise HTTPException(422, detail=(
                f"Sub-domain {sd.name!r} ({sd.id}) has length_bp < 1."
            ))
        if sd.start_bp_offset != expected_offset:
            raise HTTPException(422, detail=(
                f"Sub-domains on overhang {overhang_id!r} are not gap-less "
                f"(sub-domain {sd.name!r} starts at {sd.start_bp_offset}, "
                f"expected {expected_offset})."
            ))
        if sd.sequence_override is not None:
            if len(sd.sequence_override) != sd.length_bp:
                raise HTTPException(422, detail=(
                    f"Sub-domain {sd.name!r} ({sd.id}) sequence_override length "
                    f"({len(sd.sequence_override)}) != length_bp ({sd.length_bp})."
                ))
            if any(b not in _DNA_BASES for b in sd.sequence_override.upper()):
                raise HTTPException(422, detail=(
                    f"Sub-domain {sd.name!r} ({sd.id}) sequence_override contains "
                    f"non-ACGTN bases."
                ))
        expected_offset += sd.length_bp

    backing = _ovhg_backing_length(design, overhang_id)
    if backing is not None and expected_offset != backing:
        raise HTTPException(422, detail=(
            f"Sub-domain tiling sum ({expected_offset}) != backing domain length "
            f"({backing}) for overhang {overhang_id!r}."
        ))


def _resolve_sub_domain_sequence(ovhg, sub_dom) -> Optional[str]:
    """Return the effective 5'→3' sequence for *sub_dom* (override or parent slice).

    Returns ``None`` when neither the sub-domain nor the parent overhang has a
    sequence (Tm/GC/structure annotations are undefined in that case).
    """
    if sub_dom.sequence_override:
        return sub_dom.sequence_override.upper()
    parent = ovhg.sequence
    if not parent:
        return None
    start = sub_dom.start_bp_offset
    end = start + sub_dom.length_bp
    slice_ = parent.upper()[start:end]
    if len(slice_) < sub_dom.length_bp:
        return None
    return slice_


def _compute_sub_domain_annotations(seq: Optional[str], na_mM: float, conc_nM: float) -> dict:
    """Return the annotation cache dict for *seq*; safely handles None / 'N's."""
    from backend.core.overhang_generator import has_hairpin, has_dimer
    from backend.core.thermo import tm_nn, gc_content
    if not seq:
        return {
            "tm_celsius": None,
            "gc_percent": None,
            "hairpin_warning": False,
            "dimer_warning": False,
        }
    tm = tm_nn(seq, na_mM=na_mM, conc_nM=conc_nM)
    gc = gc_content(seq) if all(b in "ACGT" for b in seq) else None
    # has_hairpin / has_dimer are robust to short sequences.
    try:
        hp = has_hairpin(seq) if all(b in "ACGT" for b in seq) else False
    except Exception:
        hp = False
    try:
        dm = has_dimer(seq) if all(b in "ACGT" for b in seq) else False
    except Exception:
        dm = False
    return {
        "tm_celsius": tm,
        "gc_percent": gc,
        "hairpin_warning": hp,
        "dimer_warning": dm,
    }


def _apply_boundary_hairpin_warnings(design: Design, overhang_id: str) -> Design:
    """Toggle ``hairpin_warning`` on sub-domains based on boundary-hairpin scan.

    Phase 3 (overhang revamp): after any sub-domain sequence change, scan every
    pair of adjacent sub-domains for a hairpin spanning their junction
    (see ``backend.core.overhang_generator.detect_boundary_hairpins``). Both
    sub-domains touching a flagged boundary get ``hairpin_warning=True`` *added*;
    sub-domains that previously had a warning solely from a boundary that no
    longer reports get it cleared.

    The detector flags BOUNDARIES, not sub-domains. We translate by collecting
    every sub-domain id that touches at least one flagged boundary into a "warn"
    set, and clearing the flag on everyone else (so user fixes propagate
    immediately).

    Note: this does NOT clobber per-sub-domain hairpin warnings flagged by the
    inner-sequence scan (``_compute_sub_domain_annotations``). Callers always
    invoke the inner scan first (which sets ``hairpin_warning`` from the inner
    bases), so when the boundary scan then unions in boundary-driven warnings,
    the existing inner-warning bit is preserved via the explicit ``or``.
    """
    from backend.core.overhang_generator import detect_boundary_hairpins
    ovhg = next((o for o in design.overhangs if o.id == overhang_id), None)
    if ovhg is None or not ovhg.sub_domains:
        return design
    reports = detect_boundary_hairpins(ovhg)
    boundary_warn_ids: set[str] = set()
    for r in reports:
        boundary_warn_ids.add(r["sub_domain_a_id"])
        boundary_warn_ids.add(r["sub_domain_b_id"])

    # Re-evaluate inner-sequence hairpin status per sub-domain so a stale boundary
    # warning clears when the actual inner sequence has no hairpin AND the
    # boundary no longer fires. This keeps user-visible warnings honest.
    new_sub_doms = []
    changed = False
    for sd in ovhg.sub_domains:
        seq = _resolve_sub_domain_sequence(ovhg, sd)
        ann = _compute_sub_domain_annotations(
            seq, na_mM=design.tm_settings.na_mM, conc_nM=design.tm_settings.conc_nM
        )
        inner_hp = bool(ann.get("hairpin_warning"))
        bdy_hp   = sd.id in boundary_warn_ids
        new_hp   = inner_hp or bdy_hp
        if new_hp != sd.hairpin_warning:
            changed = True
            new_sub_doms.append(sd.model_copy(update={"hairpin_warning": new_hp}))
        else:
            new_sub_doms.append(sd)
    if not changed:
        return design
    new_ovhg = ovhg.model_copy(update={"sub_domains": new_sub_doms})
    return _replace_ovhg(design, new_ovhg)


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
                    new_overhangs.append(ovhg.model_copy(update={"sub_domains": [new_solo]}))
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


def _next_sub_domain_name(existing: list) -> str:
    """Lowest unused single lowercase letter ("a","b",…), then "ab","ac",… ."""
    taken = {sd.name for sd in existing}
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if letter not in taken:
            return letter
    # Two-letter fallback (very unlikely to be hit in practice).
    for a in "abcdefghijklmnopqrstuvwxyz":
        for b in "abcdefghijklmnopqrstuvwxyz":
            name = a + b
            if name not in taken:
                return name
    return _uuid.uuid4().hex[:6]


def _find_ovhg_or_404(design: Design, overhang_id: str):
    spec = next((o for o in design.overhangs if o.id == overhang_id), None)
    if spec is None:
        raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
    return spec


def _replace_ovhg(design: Design, new_spec) -> Design:
    new_overhangs = [new_spec if o.id == new_spec.id else o for o in design.overhangs]
    return design.model_copy(update={"overhangs": new_overhangs})


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
def resize_overhang_free_end(overhang_id: str, body: OverhangResizeFreeEndRequest) -> dict:
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
            (i for i, d in enumerate(domains)
             if d.helix_id == spec.helix_id and d.overhang_id is not None),
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
    is_last  = dom_idx == len(domains) - 1
    free_end: str
    if is_first and not is_last: free_end = "5p"
    elif is_last and not is_first: free_end = "3p"
    elif is_first and is_last:     free_end = "5p"   # whole-strand: arbitrary
    else: raise HTTPException(409, detail="Overhang is sandwiched between domains; resize unsupported.")

    if body.end != free_end:
        raise HTTPException(422, detail=f"Requested end {body.end!r} is the root, not the free end ({free_end!r}).")

    # Sub-domain length change matches |Δ length of overhang|. We resolve the
    # signed Δ from the backing domain length change, NOT from delta_bp (which
    # is signed in global-bp space; for REVERSE strands the polarity flips).
    backing = domains[dom_idx]
    old_len = abs(backing.end_bp - backing.start_bp) + 1

    if not spec.sub_domains:
        raise HTTPException(409, detail="Overhang has no sub-domains; legacy state — open it once to migrate.")
    last_sd = spec.sub_domains[-1]
    # Predict the new sub-domain length so we can fail BEFORE mutating state.
    # The resize moves the free end by `delta_bp` in global bp. For the FREE
    # end, the strand-domain length change equals (delta_bp * sign) where sign
    # depends on whether free is 5' (which contracts when delta_bp > 0 on a
    # FORWARD strand) or 3'. We compute the predicted new length empirically:
    #   new_start = start_bp + delta_bp if end == '5p' else start_bp
    #   new_end   = end_bp   + delta_bp if end == '3p' else end_bp
    new_start = backing.start_bp + (body.delta_bp if free_end == "5p" else 0)
    new_end   = backing.end_bp   + (body.delta_bp if free_end == "3p" else 0)
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
        d2 = _resize_strand_ends(d, [{
            "strand_id": spec.strand_id,
            "helix_id":  spec.helix_id,
            "end":       body.end,
            "delta_bp":  body.delta_bp,
        }])
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
        adjusted_last = last_after.model_copy(update={
            "length_bp":        new_last_len_inner,
            "sequence_override": new_override,
            # Tm/GC/warning caches invalidate when the slice length changes.
            "tm_celsius":       None,
            "gc_percent":       None,
            "hairpin_warning":  False,
            "dimer_warning":    False,
        })
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
        raise HTTPException(404, detail=f"Resize target not found: {missing!r}") from exc
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
        "sub_domains": [sd.model_dump() for sd in sorted(spec.sub_domains, key=lambda sd: sd.start_bp_offset)],
    }


class SubDomainSplitRequest(BaseModel):
    sub_domain_id: str
    split_at_offset: int   # offset within the parent overhang (0-based, strict interior)


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
        raise HTTPException(404, detail=(
            f"Sub-domain {body.sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))

    # ``split_at_offset`` is the absolute overhang offset (5'→3'). Translate to
    # a within-sub-domain offset and require strict interior.
    rel = body.split_at_offset - target.start_bp_offset
    if rel <= 0 or rel >= target.length_bp:
        raise HTTPException(422, detail=(
            f"split_at_offset {body.split_at_offset} is not strictly interior "
            f"to sub-domain {target.name!r} "
            f"(offset {target.start_bp_offset}, length {target.length_bp})."
        ))

    # Phase 5: a sub-domain that is the endpoint of an OverhangBinding can't
    # be split without invalidating that binding's identity. Reject with 409
    # listing the offending binding ids.
    referencing = [
        bb.id for bb in design.overhang_bindings
        if target.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
    ]
    if referencing:
        raise HTTPException(409, detail={
            "error": "sub_domain_referenced_by_binding",
            "binding_ids": referencing,
        })

    from backend.core.models import SubDomain as _SD

    override_5p = target.sequence_override[:rel] if target.sequence_override else None
    override_3p = target.sequence_override[rel:] if target.sequence_override else None

    new_5p = target.model_copy(update={
        "length_bp": rel,
        "sequence_override": override_5p,
        # Annotation caches must be re-derived after a split.
        "tm_celsius": None, "gc_percent": None,
        "hairpin_warning": False, "dimer_warning": False,
    })
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
        op_kind='overhang-bulk',
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
        raise HTTPException(404, detail=(
            f"One or both sub-domains not found on overhang {overhang_id!r}."
        ))
    if a.id == b.id:
        raise HTTPException(422, detail="Cannot merge a sub-domain with itself.")

    # Order 5'→3'; require adjacency.
    if a.start_bp_offset > b.start_bp_offset:
        a, b = b, a
    if a.start_bp_offset + a.length_bp != b.start_bp_offset:
        raise HTTPException(422, detail=(
            f"Sub-domains {a.name!r} and {b.name!r} are not adjacent "
            f"(a ends at {a.start_bp_offset + a.length_bp}, "
            f"b starts at {b.start_bp_offset})."
        ))

    # Phase 5: a sub-domain that is the endpoint of an OverhangBinding can't
    # disappear without orphaning that binding. Reject the merge with 409 and
    # list the offending binding ids so the UI can offer to remove them.
    _bound: set[str] = (
        {bb.sub_domain_a_id for bb in design.overhang_bindings}
        | {bb.sub_domain_b_id for bb in design.overhang_bindings}
    )
    referencing = [
        bb.id for bb in design.overhang_bindings
        if a.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
        or b.id in (bb.sub_domain_a_id, bb.sub_domain_b_id)
    ]
    if (a.id in _bound or b.id in _bound) and referencing:
        raise HTTPException(409, detail={
            "error": "sub_domain_referenced_by_binding",
            "binding_ids": referencing,
        })

    if a.sequence_override is not None or b.sequence_override is not None:
        # Fill missing side with 'N'×length to keep the override length valid.
        seq_a = a.sequence_override or ("N" * a.length_bp)
        seq_b = b.sequence_override or ("N" * b.length_bp)
        merged_override: Optional[str] = (seq_a + seq_b).upper()
    else:
        merged_override = None

    survivor = a.model_copy(update={
        "length_bp": a.length_bp + b.length_bp,
        "sequence_override": merged_override,
        "notes": (a.notes + (" + " + b.notes if b.notes else "")) if a.notes else b.notes,
        "tm_celsius": None, "gc_percent": None,
        "hairpin_warning": False, "dimer_warning": False,
    })

    new_sub_doms = [survivor if sd.id == a.id else sd for sd in spec.sub_domains if sd.id != b.id]
    new_sub_doms.sort(key=lambda sd: sd.start_bp_offset)

    def _fn(d: Design) -> Design:
        cur = next((o for o in d.overhangs if o.id == overhang_id), None)
        if cur is None:
            raise HTTPException(404, detail=f"Overhang {overhang_id!r} not found.")
        return _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
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
    color: Optional[str] = None              # "#RRGGBB" or empty-string / null to clear
    sequence_override: Optional[str] = None  # ACGTN of length == length_bp; empty/null clears
    rotation_theta_deg: Optional[float] = None
    rotation_phi_deg: Optional[float] = None
    notes: Optional[str] = None


@router.patch("/design/overhang/{overhang_id}/sub-domains/{sub_domain_id}", status_code=200)
def patch_sub_domain(overhang_id: str, sub_domain_id: str, body: SubDomainPatchRequest) -> dict:
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
        raise HTTPException(404, detail=(
            f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))

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
                raise HTTPException(422, detail=(
                    f"sequence_override length ({len(override)}) must equal "
                    f"length_bp ({sd.length_bp})."
                ))
            if any(b not in _DNA_BASES for b in override):
                raise HTTPException(422, detail=(
                    "sequence_override must contain only ACGTN bases."
                ))
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
        updates.update({
            "tm_celsius": None, "gc_percent": None,
            "hairpin_warning": False, "dimer_warning": False,
        })

    new_sd = sd.model_copy(update=updates)

    if sequence_override_changed:
        # Recompute annotations from the new resolved sequence.
        new_seq = (new_sd.sequence_override
                   if new_sd.sequence_override is not None
                   else _resolve_sub_domain_sequence(spec, new_sd))
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
        op_kind='overhang-bulk',
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
        raise HTTPException(404, detail=(
            f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))

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
        op_kind='overhang-bulk',
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
    cur_sd = next((s for s in (cur_ovhg.sub_domains if cur_ovhg else [])
                   if s.id == sub_domain_id), None)
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
        raise HTTPException(404, detail=(
            f"Sub-domain {sub_domain_id!r} not found on overhang {overhang_id!r}."
        ))

    # 1. Block on existing warnings — user should fix those first.
    if sd.hairpin_warning or sd.dimer_warning:
        raise HTTPException(422, detail=(
            f"Sub-domain {sd.name!r} has an active hairpin/dimer warning; "
            f"resolve it before regenerating."
        ))

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
        s.sequence for s in design.strands
        if s.strand_type != StrandType.SCAFFOLD and s.sequence
    ]

    # 4. Call the override-aware generator. It returns the FULL overhang
    #    sequence with the locked overrides verbatim and the target slot
    #    filled with a freshly generated piece.
    full_seq = generate_overhang_sequence_with_overrides(
        scaffold_seq, staple_seqs, temp_sub_doms,
    )

    # 5. Slice out the target sub-domain's segment.
    start = sd.start_bp_offset
    end = start + sd.length_bp
    new_override = full_seq[start:end]
    if len(new_override) != sd.length_bp:
        raise HTTPException(500, detail=(
            f"Sub-domain generator returned wrong length "
            f"({len(new_override)} vs {sd.length_bp})."
        ))

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
        updated_ = _replace_ovhg(d, cur.model_copy(update={"sub_domains": new_sub_doms}))
        # Re-splice into the assembled strand sequence so downstream consumers
        # (atomistic, CSV export, etc.) see the new bases.
        updated_ = _resplice_overhang_in_strand(updated_, overhang_id, cur.strand_id)
        return updated_

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
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
    cur_sd = next((s for s in (cur_ovhg.sub_domains if cur_ovhg else [])
                   if s.id == sub_domain_id), None)
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
    new_conc = design.tm_settings.conc_nM if body.conc_nM is None else float(body.conc_nM)
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
        new_sub_doms = [sd.model_copy(update={"tm_celsius": None}) for sd in ovhg.sub_domains]
        new_overhangs.append(ovhg.model_copy(update={"sub_domains": new_sub_doms}))

    def _fn(d: Design) -> Design:
        return d.model_copy(update={
            "tm_settings": new_settings,
            "overhangs":   new_overhangs,
        })

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
        label=f"Tm settings: Na+ {new_na:g} mM, oligo {new_conc:g} nM",
        params={
            "na_mM": new_na, "conc_nM": new_conc,
            "action": "tm-settings-update",
        },
        fn=_fn,
    )
    return _design_response(updated, report)


# ── Overhang connections (metadata-only linker records) ───────────────────────


def _overhang_end(ovhg_id: str) -> Optional[str]:
    """Parse `_5p` / `_3p` suffix from an overhang id, or None if absent."""
    if ovhg_id.endswith("_5p"): return "5p"
    if ovhg_id.endswith("_3p"): return "3p"
    return None


def _used_overhang_ends(
    design: Design, exclude_conn_id: Optional[str] = None,
) -> set[tuple[str, str]]:
    """Collect every (overhang_id, attach) tuple already in use, optionally
    excluding a single connection (e.g. the one being patched in place)."""
    used: set[tuple[str, str]] = set()
    for c in design.overhang_connections:
        if exclude_conn_id is not None and c.id == exclude_conn_id:
            continue
        used.add((c.overhang_a_id, c.overhang_a_attach))
        used.add((c.overhang_b_id, c.overhang_b_attach))
    return used


def _comp_first_polarity(end_type: Optional[str], attach: str) -> Optional[bool]:
    """Side polarity for linker topology / pairing.

    "Comp-first" means the linker strand on this side traverses
    [complement, bridge] (5' → 3'); the bridge attaches at the complement's
    3' end, which lands at:
      • OH's free_tip when the OH is 5' (since 5p OH's free_tip is at start_bp,
        and complement 3' lands at start_bp);
      • OH's root when the OH is 3' (3p OH's root is at start_bp).

    Returns True (comp-first), False (bridge-first), or None when the end type
    is unknown (synthetic fixtures with no _5p/_3p suffix).
    """
    if end_type is None:
        return None
    if end_type == "5p":
        return attach == "free_end"
    if end_type == "3p":
        return attach == "root"
    return None


def _check_linker_compatibility(
    end_a: Optional[str],
    end_b: Optional[str],
    attach_a: str,
    attach_b: str,
    linker_type: str,
) -> Optional[str]:
    """Return an error message if the combination is physically invalid, else None.

    The rule is one Watson-Crick polarity test applied across all four end-pair
    categories (5p+5p, 3p+3p, 5p+3p, 3p+5p). Define each side's polarity:

        comp_first := (5p AND free_end) OR (3p AND root)

    A dsDNA linker requires `comp_first(A) == comp_first(B)` so the two bridge
    halves on the virtual `__lnk__` helix run antiparallel and form a real
    duplex. The mixed-polarity case puts both halves in the same 5'→3'
    direction along `__lnk__` — non-physical.

    A ssDNA linker is the inverse: the single strand traverses
    [complement_a, bridge, complement_b] (5'→3'), so the boundary at A is at
    complement_a's 3' (comp-first) and at B is at complement_b's 5'
    (bridge-first). Therefore the two sides MUST disagree on polarity:
    `comp_first(A) != comp_first(B)`.

    Both rules collapse to a single check; only the desired equality flips
    between the two linker types.
    """
    cfa = _comp_first_polarity(end_a, attach_a)
    cfb = _comp_first_polarity(end_b, attach_b)
    if cfa is None or cfb is None:
        # Unknown polarity for one or both sides — let caller proceed (matches
        # legacy fixture-friendly behaviour). Real designs always have _5p/_3p
        # tags, so this only covers synthetic OverhangSpec records in tests.
        return None
    if linker_type == "ds":
        if cfa == cfb:
            return None
        return _ds_polarity_message(end_a, end_b, attach_a, attach_b)
    if linker_type == "ss":
        if cfa != cfb:
            return None
        return _ss_polarity_message(end_a, end_b, attach_a, attach_b)
    return None


def _ds_polarity_message(end_a: str, end_b: str, attach_a: str, attach_b: str) -> str:
    if end_a == end_b:
        return (
            f"dsDNA linker between two {end_a} ends needs matching attach "
            f"(both root or both free end) so the two bridge halves pair antiparallel."
        )
    return (
        f"dsDNA linker between a {end_a} and a {end_b} end needs OPPOSITE "
        f"attach (one root, one free end) so the two bridge halves pair antiparallel."
    )


def _ss_polarity_message(end_a: str, end_b: str, attach_a: str, attach_b: str) -> str:
    if end_a == end_b:
        return (
            f"ssDNA linker between two {end_a} ends needs OPPOSITE attach "
            f"(one root, one free end) so the bridge can be one continuous 5'→3' strand."
        )
    return (
        f"ssDNA linker between a {end_a} and a {end_b} end needs matching attach "
        f"(both root or both free end) so the bridge can be one continuous 5'→3' strand."
    )


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
        nxt = d.model_copy(update={
            "overhang_connections": [*d.overhang_connections, conn]
        })
        nxt = assign_overhang_connection_names(nxt)
        nxt = generate_linker_topology(nxt, conn)
        # The virtual __lnk__ bridge helix is invisible to clustering — orphan it
        # so the reconciler doesn't pull it into a cluster via lattice proximity.
        return nxt, MutationReport(new_helix_origins={bridge_id: None})

    a_label = next((o.label for o in design.overhangs if o.id == body.overhang_a_id), body.overhang_a_id[:10])
    b_label = next((o.label for o in design.overhangs if o.id == body.overhang_b_id), body.overhang_b_id[:10])
    label = f"Linker {body.linker_type} {a_label}↔{b_label} ({body.length_value:g} {body.length_unit})"

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='linker-add',
        label=label,
        params=body.model_dump(mode='json'),
        fn=_fn,
    )
    return _design_response(updated, report)


@router.patch("/design/overhang-connections/{conn_id}", status_code=200)
def patch_overhang_connection(conn_id: str, body: OverhangConnectionPatchRequest) -> dict:
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
            (c for c in design.overhang_connections if c.id != conn_id and c.name == new_name),
            None,
        )
        if clash is not None:
            raise HTTPException(400, detail=f"Connection name {new_name!r} is already in use.")
        patch["name"] = new_name
    if "length_value" in patch and patch["length_value"] is not None and patch["length_value"] < 0:
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

    new_target = target.model_copy(update={k: v for k, v in patch.items() if v is not None})
    if bridge_clear:
        new_target = new_target.model_copy(update={"bridge_sequence": None})
    new_list = [new_target if c.id == conn_id else c for c in design.overhang_connections]
    updated = design.model_copy(update={"overhang_connections": new_list})

    # Auto-rebuild the linker topology if length changed (length_value or unit).
    length_changed = (
        ("length_value" in patch and new_target.length_value != target.length_value)
        or ("length_unit" in patch and new_target.length_unit != target.length_unit)
    )
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
            if not strand.id.startswith(bridge_helix_id + "__"): continue
            comps = [
                {"helix_id": d.helix_id, "start_bp": d.start_bp,
                 "end_bp":   d.end_bp,   "direction": d.direction}
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
                    s = snap_by_helix.get(d.helix_id) if d.helix_id != bridge_helix_id else None
                    if s is not None:
                        patched_doms.append(d.model_copy(update={
                            "start_bp": s["start_bp"],
                            "end_bp":   s["end_bp"],
                            "direction": s["direction"],
                        }))
                    else:
                        patched_doms.append(d)
                new_strands.append(strand.model_copy(update={
                    "domains": patched_doms,
                    "sequence": None,         # length may have changed; clear
                }))
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

    a_label = next((o.label for o in design.overhangs if o.id == conn.overhang_a_id), conn.overhang_a_id[:10])
    b_label = next((o.label for o in design.overhangs if o.id == conn.overhang_b_id), conn.overhang_b_id[:10])
    label = f"Delete linker {conn.name or conn.id[:8]} ({a_label}↔{b_label})"

    def _fn(d: Design) -> Design:
        new_list = [c for c in d.overhang_connections if c.id != conn_id]
        nxt = d.model_copy(update={"overhang_connections": new_list})
        return remove_linker_topology(nxt, conn_id)

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='linker-delete',
        label=label,
        params={"conn_id": conn_id, "linker_type": conn.linker_type,
                "overhang_a_id": conn.overhang_a_id,
                "overhang_b_id": conn.overhang_b_id},
        fn=_fn,
    )
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
        prev   = design.model_copy(deep=True)
    conn = next((c for c in design.overhang_connections if c.id == conn_id), None)
    if conn is None:
        raise HTTPException(404, detail=f"Overhang connection {conn_id!r} not found.")

    selected = body.joint_ids if (body and body.joint_ids) else None

    if selected is None:
        with trace.step("dof_topology"):
            topo = dof_topology(design, conn)
        if topo["status"] != "ok" or topo["n_dof"] != 1:
            raise HTTPException(400, detail=topo["reason"] or "Relax requires exactly 1 DOF.")

    try:
        with trace.step("relax_linker"):
            if conn.linker_type == "ss":
                bin_index   = body.bin_index   if body is not None else None
                r_ee_min_nm = body.r_ee_min_nm if body is not None else None
                r_ee_max_nm = body.r_ee_max_nm if body is not None else None
                updated, info = relax_ss_linker(
                    design, conn, selected,
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
    "crossover":   0.13,   # tight nuc-to-nuc gap (was 0.67 = B-DNA backbone bond)
    "ligation":    0.0,    # the two endpoints should coincide
    "linker_arc":  0.67,   # bridge boundary → anchor gap
    "strand_arc":  0.67,   # generic cross-helix backbone bond
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
        if n.get("helix_id") != endpoint.helix_id:           continue
        if n.get("bp_index") != endpoint.bp_index:           continue
        if n.get("direction") != endpoint.direction:         continue
        if endpoint.strand_id and n.get("strand_id") != endpoint.strand_id:
            continue
        match = n
        break
    if match is None:
        raise HTTPException(422, detail=(
            f"relax_bond: no nucleotide found at helix={endpoint.helix_id!r}, "
            f"bp={endpoint.bp_index}, direction={endpoint.direction}"
        ))
    pos = match.get("backbone_position") or match.get("base_position")
    if pos is None:
        raise HTTPException(422, detail=(
            "relax_bond: nucleotide has no backbone position."
        ))
    return np.asarray(pos, dtype=float)


def _cluster_id_for_helix(design: Design, helix_id: str) -> Optional[str]:
    """Return the (helix-level) cluster id containing *helix_id*. Falls back
    to None if the helix is orphaned (no cluster owns it)."""
    for ct in design.cluster_transforms:
        if helix_id in ct.helix_ids:
            return ct.id
    return None


def _cluster_pair_for_bond_relax(
    design: Design, helix_a: str, helix_b: str,
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
            raise HTTPException(404, detail=(
                f"crossover {body.bond_id!r} not found."
            ))
        side_a = RelaxBondEndpoint(
            helix_id=xo.half_a.helix_id, bp_index=xo.half_a.index,
            direction=xo.half_a.strand.value,
        )
        side_b = RelaxBondEndpoint(
            helix_id=xo.half_b.helix_id, bp_index=xo.half_b.index,
            direction=xo.half_b.strand.value,
        )
    elif body.bond_type == "ligation" and body.bond_id:
        fl = next((f for f in design.forced_ligations if f.id == body.bond_id), None)
        if fl is None:
            raise HTTPException(404, detail=(
                f"forced ligation {body.bond_id!r} not found."
            ))
        side_a = RelaxBondEndpoint(
            helix_id=fl.three_prime_helix_id, bp_index=fl.three_prime_bp,
            direction=fl.three_prime_direction.value,
        )
        side_b = RelaxBondEndpoint(
            helix_id=fl.five_prime_helix_id, bp_index=fl.five_prime_bp,
            direction=fl.five_prime_direction.value,
        )
    elif body.bond_type == "linker_arc" and body.bond_id:
        # linker_arc identifies a SINGLE connector arc: (conn_id, side a|b).
        # Side "a" = OH-A anchor ↔ bridge boundary on the ``__lnk__/__a``
        # complement; side "b" symmetric for OH-B. We resolve to the two
        # nuc endpoints of that single arc.
        if body.linker_side not in ("a", "b"):
            raise HTTPException(422, detail=(
                "relax_bond: linker_arc requires linker_side='a' or 'b'."
            ))
        conn = next(
            (c for c in design.overhang_connections if c.id == body.bond_id),
            None,
        )
        if conn is None:
            raise HTTPException(404, detail=(
                f"overhang connection {body.bond_id!r} not found."
            ))
        side_a, side_b = _resolve_linker_arc_endpoints(design, conn, body.linker_side, geometry)
    else:
        # Half-edge addressing.
        if body.side_a is None or body.side_b is None:
            raise HTTPException(422, detail=(
                "relax_bond: must provide either bond_id (with linker_side "
                "for linker_arc) or side_a + side_b half-edge endpoints."
            ))
        side_a = body.side_a
        side_b = body.side_b

    anchor_a = _resolve_bond_anchor_from_endpoint(geometry, side_a)
    anchor_b = _resolve_bond_anchor_from_endpoint(geometry, side_b)

    cluster_a_id, cluster_b_id = _cluster_pair_for_bond_relax(
        design, side_a.helix_id, side_b.helix_id,
    )
    if cluster_a_id is None or cluster_b_id is None:
        raise HTTPException(422, detail=(
            "relax_bond: one or both endpoint helices are not in a cluster."
        ))

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
        (o for o in design.overhangs if o.id == (
            conn.overhang_a_id if linker_side == "a" else conn.overhang_b_id
        )),
        None,
    )
    if oh is None:
        raise HTTPException(422, detail=(
            f"relax_bond: linker_arc side {linker_side!r} OH not found."
        ))
    attach = conn.overhang_a_attach if linker_side == "a" else conn.overhang_b_attach
    oh_domain = _find_overhang_domain(design, oh.id)
    if oh_domain is None:
        raise HTTPException(422, detail=(
            f"relax_bond: linker_arc side {linker_side!r} OH domain not found."
        ))
    # OH-end attach bp = the attach-side end of the OH's domain.
    if attach == "root":
        attach_bp = oh_domain.start_bp
    else:
        attach_bp = oh_domain.end_bp
    oh_endpoint = RelaxBondEndpoint(
        helix_id=oh_domain.helix_id, bp_index=attach_bp,
        direction=oh_domain.direction.value,
    )

    # Bridge-boundary endpoint: the first/last bp of the linker bridge
    # strand on the virtual ``__lnk__`` helix (or its ss equivalent).
    # We scan geometry for the bridge nuc whose strand_id matches the
    # linker strand for this side.
    suffix = "a" if linker_side == "a" else ("b" if conn.linker_type == "ds" else "s")
    bridge_strand_id = f"__lnk__{conn.id}__{suffix}"
    bridge_nucs = [
        n for n in geometry
        if n.get("strand_id") == bridge_strand_id
        and n.get("helix_id", "").startswith(f"__lnk__{conn.id}")
    ]
    if not bridge_nucs:
        raise HTTPException(422, detail=(
            f"relax_bond: no bridge nucleotides found for linker "
            f"{conn.id!r} side {linker_side!r}."
        ))
    # Side "a" arc reaches the bridge bp closest to side A — the lowest bp
    # on a ds bridge with comp-first-a (linker strand traverses
    # [complement_a, bridge_forward]). The opposite side is bp L-1. Pick
    # by linker_side: a → min bp, b → max bp.
    bridge_nucs.sort(key=lambda n: n.get("bp_index", 0))
    bridge_nuc = bridge_nucs[0] if linker_side == "a" else bridge_nucs[-1]
    bridge_endpoint = RelaxBondEndpoint(
        helix_id=bridge_nuc["helix_id"], bp_index=bridge_nuc["bp_index"],
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
    (anchor_a, anchor_b, cluster_a_id, cluster_b_id,
     target_nm, source_tag) = _resolve_relax_bond_request(design, body, geometry)

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


def _select_driver_for_joint(design: Design, joint_id: str) -> Optional[OverhangBinding]:
    """Return the bound binding currently driving *joint_id*.

    Driver selection: latest ``created_at`` among bound bindings targeting
    this joint. Tiebreak: lexicographic id.
    """
    candidates = [
        b for b in design.overhang_bindings
        if b.bound and b.target_joint_id == joint_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda b: (b.created_at, b.id))
    return candidates[-1]


def _first_claimant_for_joint(design: Design, joint_id: str) -> Optional[OverhangBinding]:
    """Return the earliest-created binding (bound OR unbound) targeting *joint_id*.

    Used to locate the snapshot of the joint's pre-binding angle window so
    the window can be restored when the last bound claimant releases.
    """
    candidates = [
        b for b in design.overhang_bindings
        if b.target_joint_id == joint_id
    ]
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
            new_joints.append(j.model_copy(update={
                "min_angle_deg": driver.locked_angle_deg,
                "max_angle_deg": driver.locked_angle_deg,
            }))
        else:
            # No driver — restore prior window if first claimant snapshotted it.
            first = _first_claimant_for_joint(design, joint_id)
            if (first is not None
                    and first.prior_min_angle_deg is not None
                    and first.prior_max_angle_deg is not None):
                new_joints.append(j.model_copy(update={
                    "min_angle_deg": first.prior_min_angle_deg,
                    "max_angle_deg": first.prior_max_angle_deg,
                }))
            else:
                # Nothing to restore; leave as-is.
                new_joints.append(j)
    return design.model_copy(update={"cluster_joints": new_joints})


def _binding_response(design: Design, report: ValidationReport, binding_id: Optional[str] = None) -> dict:
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
    binding_mode: Literal['duplex', 'toehold'] = 'duplex'
    target_joint_id: Optional[str] = None
    allow_n_wildcard: bool = True


def _resolve_sd_for_binding(
    design: Design, sub_domain_id: str,
) -> tuple[Optional['OverhangSpec'], Optional['SubDomain']]:
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
        raise HTTPException(422, detail="sub_domain_a_id and sub_domain_b_id must differ.")

    ovhg_a, sd_a = _resolve_sd_for_binding(design, body.sub_domain_a_id)
    ovhg_b, sd_b = _resolve_sd_for_binding(design, body.sub_domain_b_id)
    if ovhg_a is None or sd_a is None:
        raise HTTPException(404, detail=f"sub_domain_a_id {body.sub_domain_a_id!r} not found.")
    if ovhg_b is None or sd_b is None:
        raise HTTPException(404, detail=f"sub_domain_b_id {body.sub_domain_b_id!r} not found.")

    if sd_a.length_bp != sd_b.length_bp:
        raise HTTPException(422, detail=(
            f"sub-domain lengths must match ({sd_a.length_bp} vs {sd_b.length_bp})."
        ))

    seq_a = _resolve_sub_domain_sequence(ovhg_a, sd_a)
    seq_b = _resolve_sub_domain_sequence(ovhg_b, sd_b)
    if seq_a is None or seq_b is None:
        raise HTTPException(422, detail=(
            "Both sub-domain sequences must be resolvable (override or parent slice) "
            "before a binding can be created."
        ))
    if not _is_wc(seq_a, seq_b, allow_n=body.allow_n_wildcard):
        raise HTTPException(422, detail=(
            f"sequences are not Watson-Crick complementary "
            f"(allow_n_wildcard={body.allow_n_wildcard})."
        ))

    pair_key = frozenset({body.sub_domain_a_id, body.sub_domain_b_id})
    if pair_key in _binding_pair_keys(design):
        raise HTTPException(409, detail=(
            "sub-domain pair is already claimed by another linker or binding."
        ))

    if body.target_joint_id is not None:
        joint_ids = {j.id for j in design.cluster_joints}
        if body.target_joint_id not in joint_ids:
            raise HTTPException(404, detail=(
                f"target_joint_id {body.target_joint_id!r} not found."
            ))

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
        return d.model_copy(update={
            "overhang_bindings": [*d.overhang_bindings, binding],
        })

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
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
    binding_mode: Optional[Literal['duplex', 'toehold']] = None
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
        compute_locked_angle,
        revert_bind_topology,
    )

    design = design_state.get_or_404()
    target = next((b for b in design.overhang_bindings if b.id == binding_id), None)
    if target is None:
        raise HTTPException(404, detail=f"Overhang binding {binding_id!r} not found.")

    patch = body.model_dump(exclude_unset=True)

    if 'name' in patch:
        new_name = (patch['name'] or '').strip()
        if not new_name:
            raise HTTPException(422, detail="name must be non-empty.")
        clash = next(
            (b for b in design.overhang_bindings if b.id != binding_id and b.name == new_name),
            None,
        )
        if clash is not None:
            raise HTTPException(422, detail=f"binding name {new_name!r} is already in use.")
        patch['name'] = new_name

    if 'target_joint_id' in patch and patch['target_joint_id'] is not None:
        joint_ids = {j.id for j in design.cluster_joints}
        if patch['target_joint_id'] not in joint_ids:
            raise HTTPException(404, detail=(
                f"target_joint_id {patch['target_joint_id']!r} not found."
            ))

    # Compute next binding state pieces. We resolve transitions explicitly
    # so all topology + joint mutations sit inside one mutate_with_feature_log atomic.
    prev_bound = target.bound
    prev_joint = target.target_joint_id
    next_joint = patch.get('target_joint_id', prev_joint) if 'target_joint_id' in patch else prev_joint
    next_bound = patch.get('bound', prev_bound) if 'bound' in patch else prev_bound

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
        try:
            topology = compute_bind_topology(design, target)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(422, detail=f"compute_bind_topology failed: {exc!r}")
        # Snapshot for unbind restoration.
        patch['prior_driven_topology'] = topology.snapshot
        # Resolve the auto-pick joint id (when exactly one joint connects
        # the two clusters and the user didn't pin target_joint_id).
        if next_joint is None:
            from backend.core.linker_relax import _overhang_owning_cluster_id as _own
            cluster_a = _own(design, target.overhang_a_id)
            cluster_b = _own(design, target.overhang_b_id)
            cands = [
                j for j in design.cluster_joints
                if j.cluster_id == cluster_a or j.cluster_id == cluster_b
            ]
            if len(cands) == 1:
                next_joint = cands[0].id
                patch['target_joint_id'] = next_joint
        # locked_angle_deg is computed post-relocation inside _fn (see below).
        # Leave it None here; _fn writes the real value before _apply_driver_to_joint
        # reads it.
        patch['locked_angle_deg'] = None
        patch['bound'] = True
    elif prev_bound and not next_bound:
        # Going BOUND -> UNBOUND: clear locked_angle_deg + plan to restore
        # the topology snapshot taken at bind time (if any).
        patch['locked_angle_deg'] = None
        patch['bound'] = False
        restore_snapshot = target.prior_driven_topology
        patch['prior_driven_topology'] = None

    updated_target = target.model_copy(update={
        k: v for k, v in patch.items() if k in OverhangBinding.model_fields
    })

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
                joint = next((j for j in nxt.cluster_joints if j.id == next_joint), None)
                if joint is not None:
                    new_first = first.model_copy(update={
                        "prior_min_angle_deg": joint.min_angle_deg,
                        "prior_max_angle_deg": joint.max_angle_deg,
                    })
                    nxt = nxt.model_copy(update={
                        "overhang_bindings": [
                            new_first if bb.id == first.id else bb
                            for bb in nxt.overhang_bindings
                        ],
                    })

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
                    new_first = first.model_copy(update={
                        "prior_min_angle_deg": None,
                        "prior_max_angle_deg": None,
                    })
                    nxt = nxt.model_copy(update={
                        "overhang_bindings": [
                            new_first if bb.id == first.id else bb
                            for bb in nxt.overhang_bindings
                        ],
                    })
        return nxt

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
        label=f"Patch binding {target.name}",
        params={
            "binding_id": binding_id,
            "fields": sorted(patch.keys()),
            "action": "overhang-binding-patch",
        },
        fn=_fn,
    )
    return _binding_response(updated, report, binding_id=binding_id)


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
                b for b in bindings
                if b.target_joint_id == joint_id and b.id != binding_id
            ]
            others.sort(key=lambda b: (b.created_at, b.id))
            if others:
                heir = others[0]
                # Migrate snapshot onto heir (only if heir has no snapshot yet).
                if heir.prior_min_angle_deg is None and heir.prior_max_angle_deg is None:
                    new_heir = heir.model_copy(update={
                        "prior_min_angle_deg": target.prior_min_angle_deg,
                        "prior_max_angle_deg": target.prior_max_angle_deg,
                    })
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
            if not heir_migrated and fallback_min is not None and fallback_max is not None:
                # Check whether driver-apply already restored (it would only
                # do so if a remaining claimant carried a snapshot — i.e.,
                # heir_migrated case).
                driver_after = _select_driver_for_joint(nxt, joint_id)
                if driver_after is None:
                    new_joints = []
                    for j in nxt.cluster_joints:
                        if j.id == joint_id:
                            new_joints.append(j.model_copy(update={
                                "min_angle_deg": fallback_min,
                                "max_angle_deg": fallback_max,
                            }))
                        else:
                            new_joints.append(j)
                    nxt = nxt.model_copy(update={"cluster_joints": new_joints})
        return nxt

    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='overhang-bulk',
        label=f"Delete binding {target.name}",
        params={
            "binding_id": binding_id,
            "name": target.name,
            "action": "overhang-binding-delete",
        },
        fn=_fn,
    )
    return _design_response_with_geometry(updated, report)


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
        color = "#29B6F6" if strand.is_scaffold else _PALETTE[row_idx % len(_PALETTE)]
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

    # If the deleted entry was a routing-cluster that placed / updated / deleted
    # joints, _seek_feature_log doesn't replay cluster_joints from log entries
    # (joints are only mutated by minor ops nested inside routing-clusters), so
    # the orphaned indicators would stay on screen. Use the entry's stored
    # pre/post snapshots to invert this routing-cluster's joint delta on the
    # live cluster_joints. Without pre/post payload (evicted) we can't recover
    # the delta; the indicators stay until a manual joint-delete.
    if entry.feature_type == 'routing-cluster' and entry.pre_state_gz_b64 and entry.post_state_gz_b64:
        try:
            pre_design  = design_state.decode_design_snapshot(entry.pre_state_gz_b64)
            post_design = design_state.decode_design_snapshot(entry.post_state_gz_b64)
        except Exception:
            pre_design = None
            post_design = None
        if pre_design is not None and post_design is not None:
            pre_joints  = {j.id: j for j in pre_design.cluster_joints}
            post_joints = {j.id: j for j in post_design.cluster_joints}
            created_ids = post_joints.keys() - pre_joints.keys()
            deleted_ids = pre_joints.keys() - post_joints.keys()
            updated_ids = {
                jid for jid in pre_joints.keys() & post_joints.keys()
                if pre_joints[jid] != post_joints[jid]
            }
            if created_ids or deleted_ids or updated_ids:
                new_joints = []
                seen = set()
                for j in temp.cluster_joints:
                    if j.id in created_ids:
                        continue
                    if j.id in updated_ids:
                        new_joints.append(pre_joints[j.id])
                    else:
                        new_joints.append(j)
                    seen.add(j.id)
                for jid in deleted_ids:
                    if jid not in seen:
                        new_joints.append(pre_joints[jid])
                temp = temp.copy_with(cluster_joints=new_joints)

    updated = _seek_feature_log(temp, new_cursor)
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


def _save_active_loadout_snapshot(design: Design, loadouts: list[DesignLoadout], active_id: str) -> list[DesignLoadout]:
    payload, size = _encode_loadout_design_snapshot(design)
    return [
        l.model_copy(update={
            "design_snapshot_gz_b64": payload,
            "snapshot_size_bytes": size,
        }) if l.id == active_id else l
        for l in loadouts
    ]


@router.post("/design/loadouts", status_code=200)
def create_loadout(body: LoadoutCreateBody) -> dict:
    """Create a new branch by copying the current design + feature-log cursor."""
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    loadouts, active_id = _ensure_loadouts(current)
    loadouts = _save_active_loadout_snapshot(current, loadouts, active_id)

    n = len(loadouts) + 1
    name = (body.name or "").strip() or f"Loadout {n}"
    new_id = str(_uuid.uuid4())
    payload, size = _encode_loadout_design_snapshot(current)
    loadouts.append(DesignLoadout(
        id=new_id,
        name=name,
        design_snapshot_gz_b64=payload,
        snapshot_size_bytes=size,
    ))

    updated = current.copy_with(loadouts=loadouts, active_loadout_id=new_id)
    design_state.set_design(updated)
    report = validate_design(updated)
    return _design_response_with_geometry(updated, report)


@router.post("/design/loadouts/{loadout_id}/select", status_code=200)
def select_loadout(loadout_id: str) -> dict:
    """Save the current branch and restore the selected branch snapshot."""
    from backend.core.validator import validate_design

    current = design_state.get_or_404()
    loadouts, active_id = _ensure_loadouts(current)
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
            restored = _decode_loadout_design_snapshot(remaining[0].design_snapshot_gz_b64)
        except Exception as exc:
            raise HTTPException(500, detail=f"Failed to restore next loadout: {exc}") from exc
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
    if op_kind == 'bundle-create':
        body = BundleRequest.model_validate(params)
        cells = [tuple(c) for c in body.cells]  # type: ignore[misc]
        return _build_bundle(cells, body)
    if op_kind == 'extrude-segment':
        body = BundleSegmentRequest.model_validate(params)
        updated, _ = _build_extrude_segment(pre_state, body)
        return updated
    if op_kind == 'extrude-continuation':
        body = BundleContinuationRequest.model_validate(params)
        updated, _ = _build_extrude_continuation(pre_state, body)
        return updated
    if op_kind == 'extrude-deformed-continuation':
        body = BundleDeformedContinuationRequest.model_validate(params)
        updated, _ = _build_extrude_deformed_continuation(pre_state, body)
        return updated
    if op_kind == 'overhang-extrude':
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
    entry: 'ClusterOpLogEntry',
    body: EditFeatureBody,
    log: list,
    design: Design,
) -> dict:
    """Edit branch for ``edit_feature`` when the target is a ClusterOpLogEntry.

    ``body.params`` accepts ``translation``, ``rotation``, ``pivot`` — the
    new ABSOLUTE transform for ``entry.cluster_id``. Updates both the
    ClusterTransform record in ``design.cluster_transforms`` AND the log
    entry's stored fields, so the seek-replay reproduces the new transform.

    Editing is only meaningful for the LAST cluster_op of a given cluster
    (otherwise the cumulative effect of later cluster_ops would be ambiguous).
    The endpoint enforces this — earlier entries return 409.
    """
    p = body.params or {}
    for f in ('translation', 'rotation', 'pivot'):
        if f not in p:
            raise HTTPException(400, detail=f"cluster_op edit requires '{f}'.")

    later = [
        e for e in log[index + 1:]
        if e.feature_type == 'cluster_op' and e.cluster_id == entry.cluster_id
    ]
    if later:
        raise HTTPException(
            409,
            detail=(
                f"Cannot edit cluster_op {index}: {len(later)} later cluster_op "
                f"entries exist for cluster {entry.cluster_id!r}. Edit the latest "
                "one instead."
            ),
        )

    cts = list(design.cluster_transforms)
    ct_idx = next((i for i, c in enumerate(cts) if c.id == entry.cluster_id), None)
    if ct_idx is None:
        raise HTTPException(404, detail=f"Cluster {entry.cluster_id!r} no longer exists.")
    cts[ct_idx] = cts[ct_idx].model_copy(update={
        'translation': list(p['translation']),
        'rotation':    list(p['rotation']),
        'pivot':       list(p['pivot']),
    })

    new_log = list(log)
    new_log[index] = entry.model_copy(update={
        'translation': list(p['translation']),
        'rotation':    list(p['rotation']),
        'pivot':       list(p['pivot']),
    })

    from backend.core.validator import validate_design as _validate_design
    updated = design.copy_with(cluster_transforms=cts, feature_log=new_log)
    design_state.set_design(updated)
    report = _validate_design(updated)
    # Cluster-only diff: design differs from prev only in cluster_transforms,
    # so this typically lands in the lean cluster_only fast path. Frontend
    # applies the delta in place — no full geometry recompute.
    return _design_replace_response(design, updated, report)


def _edit_deformation_feature(
    index: int,
    entry: 'DeformationLogEntry',
    body: EditFeatureBody,
    log: list,
    design: Design,
) -> dict:
    """Edit branch for ``edit_feature`` when the target is a DeformationLogEntry.

    ``body.params`` accepts the same fields as the ``AddDeformationBody``
    request: ``type``, ``plane_a_bp``, ``plane_b_bp``, ``params``, optional
    ``affected_helix_ids``, optional ``cluster_ids``. Updates the existing
    DeformationOp in design.deformations and refreshes the entry's
    op_snapshot — does NOT append a new log entry. Pushes the prior state
    to the undo stack.
    """
    p = body.params or {}
    op_type = p.get('type', entry.op_snapshot.type if entry.op_snapshot else None)
    if op_type not in ('twist', 'bend'):
        raise HTTPException(400, detail=f"deformation 'type' must be 'twist' or 'bend' (got {op_type!r}).")
    if 'plane_a_bp' not in p or 'plane_b_bp' not in p:
        raise HTTPException(400, detail="deformation edit requires plane_a_bp and plane_b_bp.")
    if 'params' not in p:
        raise HTTPException(400, detail="deformation edit requires nested params.")

    new_params = _parse_params(op_type, p['params'])

    helix_ids = p.get('affected_helix_ids') or helices_crossing_planes(
        design, p['plane_a_bp'], p['plane_b_bp']
    )
    resolved = _resolve_cluster_scope(design, p.get('cluster_ids') or [], helix_ids)
    helix_ids = resolved["helix_ids"]
    cluster_ids = resolved["cluster_ids"]

    # Locate the existing DeformationOp by deformation_id; replace its fields.
    ops = list(design.deformations)
    op_idx = next((i for i, op in enumerate(ops) if op.id == entry.deformation_id), None)
    if op_idx is None:
        raise HTTPException(404, detail=f"Deformation op {entry.deformation_id!r} not found in design.")
    new_op = ops[op_idx].model_copy(update={
        'type':               op_type,
        'plane_a_bp':         p['plane_a_bp'],
        'plane_b_bp':         p['plane_b_bp'],
        'affected_helix_ids': helix_ids,
        'cluster_ids':        cluster_ids,
        'params':             new_params,
    })
    ops[op_idx] = new_op

    # Refresh the entry's op_snapshot so seek replays match the new params.
    new_log = list(log)
    new_log[index] = entry.model_copy(update={'op_snapshot': new_op})

    from backend.core.validator import validate_design as _validate_design
    updated = design.copy_with(deformations=ops, feature_log=new_log)
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
        raise HTTPException(400, detail=f"Feature index {index} out of range (log has {len(log)} entries).")

    entry = log[index]

    # ── Deformation edit branch ───────────────────────────────────────────────
    if isinstance(entry, _DeformationLogEntry):
        return _edit_deformation_feature(index, entry, body, log, design)

    # ── Cluster_op edit branch ────────────────────────────────────────────────
    from backend.core.models import ClusterOpLogEntry as _ClusterOpLogEntry
    if isinstance(entry, _ClusterOpLogEntry):
        return _edit_cluster_op_feature(index, entry, body, log, design)

    if not isinstance(entry, _SnapshotLogEntry):
        raise HTTPException(400, detail=f"Feature at index {index} is not editable (type {entry.feature_type!r}).")
    if entry.evicted or not entry.design_snapshot_gz_b64:
        raise HTTPException(
            410,
            detail=f"Snapshot for feature {index} ({entry.label!r}) was evicted; cannot replay.",
        )

    later_snapshots = [
        i for i, e in enumerate(log[index + 1:], start=index + 1)
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
        raise HTTPException(400, detail=f"Invalid params for {entry.op_kind}: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    # Re-encode pre/post so size + payload reflect the new operation outcome.
    new_pre_b64, new_pre_size = design_state.encode_design_snapshot(pre_state)
    new_post_b64, new_post_size = design_state.encode_design_snapshot(new_post)

    updated_entry = entry.model_copy(update={
        'params': body.params,
        'design_snapshot_gz_b64': new_pre_b64,
        'snapshot_size_bytes': new_pre_size,
        'post_state_gz_b64': new_post_b64,
        'post_state_size_bytes': new_post_size,
    })
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


@router.post("/design/features/{index}/revert", status_code=200)
def revert_to_before_feature(index: int) -> dict:
    """Restore the pre-state snapshot of feature_log[index] and TRUNCATE
    feature_log to [0..index-1].

    Valid for both ``SnapshotLogEntry`` (auto-op snapshots) and
    ``RoutingClusterLogEntry`` (Fine Routing clusters). Returns 410 GONE if
    the entry's snapshot bytes were evicted to free space.

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
        raise HTTPException(400, detail=f"Feature index {index} out of range (log has {len(log)} entries).")

    entry = log[index]

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
        raise HTTPException(500, detail=f"Failed to decode snapshot for feature {index}: {e}")

    # Keep only entries strictly before this one — see truncation rationale above.
    truncated_log = log[:index]
    restored = restored.copy_with(feature_log=truncated_log, feature_log_cursor=-1)

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
    if op_subtype == 'nick':
        return _build_nick(design, NickRequest.model_validate(params))
    if op_subtype == 'nick-batch':
        return _build_nick_batch(design, NickBatchRequest.model_validate(params))
    if op_subtype == 'crossover-place':
        d, _x, _ligated = _build_place_crossover(design, PlaceCrossoverRequest.model_validate(params))
        return d
    if op_subtype == 'crossover-place-batch':
        d, _xs, _skipped = _build_place_crossover_batch(design, PlaceCrossoverBatchRequest.model_validate(params))
        return d
    if op_subtype == 'strand-end-resize':
        return _build_strand_end_resize(design, StrandEndResizeRequest.model_validate(params))
    if op_subtype == 'domain-shift':
        return _build_domain_shift(design, DomainShiftRequest.model_validate(params))
    if op_subtype == 'strand-delete':
        return _build_delete_strand(design, params['strand_id'])
    if op_subtype == 'strand-delete-batch':
        return _build_delete_strands_batch(design, StrandBatchDeleteRequest.model_validate(params))
    if op_subtype == 'domain-delete':
        return _build_delete_domain(design, params['strand_id'], params['domain_index'])
    if op_subtype == 'helix-delete':
        out = design.model_copy(deep=True)
        idx = next((i for i, h in enumerate(out.helices) if h.id == params['helix_id']), None)
        if idx is None:
            raise HTTPException(404, detail=f"Helix {params['helix_id']!r} not found at replay.")
        out.helices.pop(idx)
        return out
    if op_subtype == 'crossover-delete':
        cid = params['crossover_id']
        xover = next((x for x in design.crossovers if x.id == cid), None)
        if xover is None:
            raise HTTPException(404, detail=f"Crossover {cid!r} missing at replay.")
        new_strands = _desplice_strands_for_crossover(design, xover.half_a, xover.half_b)
        out = design.model_copy(deep=True)
        out.crossovers = [x for x in out.crossovers if x.id != cid]
        out.strands = new_strands
        return out
    if op_subtype == 'joint-place':
        return _build_add_joint(design, params)
    if op_subtype == 'joint-update':
        return _build_update_joint(design, params)
    if op_subtype == 'joint-delete':
        return _build_delete_joint(design, params)

    # Subtype recognized but builder not yet extracted; treat as v2-deferred.
    # _seek_snapshot_base catches this and falls back to cluster post-state.
    raise NotImplementedError(
        f"Mid-cluster replay for op_subtype {op_subtype!r} is not implemented in v1. "
        "Falling back to cluster post-state."
    )


def _topology_substitute(design: Design, snap_design: Design) -> Design:
    """Substitute topology-bearing fields from ``snap_design`` into ``design``,
    leaving deformations/cluster_transforms/overhangs to the delta-replay logic.
    """
    return design.copy_with(
        helices=snap_design.helices,
        strands=snap_design.strands,
        crossovers=snap_design.crossovers,
        overhang_connections=snap_design.overhang_connections,
        extensions=snap_design.extensions,
        photoproduct_junctions=snap_design.photoproduct_junctions,
        forced_ligations=snap_design.forced_ligations,
    )


def _seek_snapshot_base(design: Design, position: int, sub_position: int | None = None) -> Design:
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

    pre_indices  = [i for i, e in enumerate(log) if _has_pre(e)]
    post_indices = [i for i, e in enumerate(log) if _has_post(e)]
    if not pre_indices and not post_indices:
        return design

    # Determine the effective position for payload lookup.
    # -1 / overshoot ⇒ end-of-log.
    if position == -1 or position >= len(log) - 1:
        eff_position = len(log) - 1
    elif position == -2:
        eff_position = -1   # before everything
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
            first.design_snapshot_gz_b64 if isinstance(first, _SnapshotLogEntry)
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
            snap_design = design_state.decode_design_snapshot(payload_entry.pre_state_gz_b64)
            return _topology_substitute(design, snap_design)
        # 0..M-1 = first sub_position+1 children active
        n_children = len(payload_entry.children)
        if 0 <= sub_position < n_children:
            try:
                snap_design = design_state.decode_design_snapshot(payload_entry.pre_state_gz_b64)
                for child in payload_entry.children[: sub_position + 1]:
                    snap_design = _replay_minor_op(snap_design, child.op_subtype, child.params)
                return _topology_substitute(design, snap_design)
            except NotImplementedError:
                # v1 limitation: some op_subtypes don't have replay builders yet.
                # Gracefully fall back to cluster's post-state (treat the whole
                # cluster as active — same as sub_position=None).
                pass
        # sub_position == -1 or out-of-range → fall through to post-state.

    # Default: use POST-state of the chosen payload entry.
    if isinstance(payload_entry, _SnapshotLogEntry):
        snap_design = design_state.decode_design_snapshot(payload_entry.post_state_gz_b64)
    else:
        snap_design = design_state.decode_design_snapshot(payload_entry.post_state_gz_b64)
    return _topology_substitute(design, snap_design)


def _seek_feature_log(design: Design, position: int, sub_position: int | None = None) -> Design:
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
        clusters_with_any_op = {e.cluster_id for e in log if e.feature_type == 'cluster_op'}
        new_cts = [
            ct.model_copy(update={'translation': [0.0, 0.0, 0.0], 'rotation': [0.0, 0.0, 0.0, 1.0]})
            if ct.id in clusters_with_any_op else ct
            for ct in design.cluster_transforms
        ]
        new_joints = _rebase_joints_to_cts(design, new_cts)
        # Reset overhang rotations + sub-domain (theta, phi) for any
        # overhang that has ops in the log.
        ovhgs_with_any_op: set = set()
        sd_pairs_with_any_op: set[tuple[str, str]] = set()
        for e in log:
            if e.feature_type != 'overhang_rotation':
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
                update['rotation'] = [0.0, 0.0, 0.0, 1.0]
            sds_touched = {sd_id for (oid, sd_id) in sd_pairs_with_any_op if oid == ovhg.id}
            if sds_touched:
                update['sub_domains'] = [
                    sd.model_copy(update={
                        'rotation_theta_deg': 0.0,
                        'rotation_phi_deg':   0.0,
                    }) if sd.id in sds_touched else sd
                    for sd in ovhg.sub_domains
                ]
            new_overhangs.append(ovhg.model_copy(update=update) if update else ovhg)
        return design.copy_with(
            deformations=[], cluster_transforms=new_cts,
            cluster_joints=new_joints, overhangs=new_overhangs,
            feature_log_cursor=-2, feature_log_sub_cursor=None,
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
        active = log[:position + 1]
    elif position == -1 or position >= len(log) - 1:
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

    # Rebuild overhang rotations: last rotation per overhang_id in active window.
    # Phase 4 — also track per-sub-domain (theta, phi) state.
    ovhg_last_rot: dict = {}
    sd_last_angles: dict[tuple[str, str], tuple[float, float]] = {}
    ovhgs_with_ops: set = set()
    sd_pairs_with_ops: set[tuple[str, str]] = set()
    for entry in active:
        if entry.feature_type != 'overhang_rotation':
            continue
        sd_ids = entry.sub_domain_ids
        thetas = entry.sub_domain_thetas_deg
        phis   = entry.sub_domain_phis_deg
        for i, oid in enumerate(entry.overhang_ids):
            sd_id_i = sd_ids[i] if i < len(sd_ids) else None
            if sd_id_i is None:
                ovhg_last_rot[oid] = entry.rotations[i]
            else:
                sd_last_angles[(oid, sd_id_i)] = (float(thetas[i]), float(phis[i]))
    for e in log:
        if e.feature_type != 'overhang_rotation':
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
            ovhg = ovhg.model_copy(update={'rotation': ovhg_last_rot[ovhg.id]})
        elif ovhg.id in ovhgs_with_ops:
            ovhg = ovhg.model_copy(update={'rotation': [0.0, 0.0, 0.0, 1.0]})

        sub_doms_touched = [
            sd_id for (oid, sd_id) in sd_pairs_with_ops if oid == ovhg.id
        ]
        if sub_doms_touched:
            new_sds = []
            for sd in ovhg.sub_domains:
                key = (ovhg.id, sd.id)
                if key in sd_last_angles:
                    theta, phi = sd_last_angles[key]
                    sd = sd.model_copy(update={
                        'rotation_theta_deg': theta,
                        'rotation_phi_deg':   phi,
                    })
                elif sd.id in sub_doms_touched:
                    sd = sd.model_copy(update={
                        'rotation_theta_deg': 0.0,
                        'rotation_phi_deg':   0.0,
                    })
                new_sds.append(sd)
            ovhg = ovhg.model_copy(update={'sub_domains': new_sds})

        new_overhangs.append(ovhg)

    return design.copy_with(
        deformations=new_deformations,
        cluster_transforms=new_cts,
        cluster_joints=new_joints,
        overhangs=new_overhangs,
        feature_log_cursor=cursor_val,
        feature_log_sub_cursor=sub_position,
    )


class SeekFeaturesBody(BaseModel):
    position: int   # -2 = empty (no features); -1 = end (all active); ≥0 = index of last active entry
    sub_position: Optional[int] = None
    """Mid-cluster sub-position. None → cluster's post-state (all children active).
    -2 → cluster's pre-state (no children active). 0..M-1 → first sub_position+1
    children active. Honored only when ``position`` indexes a RoutingClusterLogEntry."""


@router.post("/design/features/seek", status_code=200)
def seek_features(body: SeekFeaturesBody):
    """Replay the feature log up to the given position, updating derived geometry fields.

    Pushes to the undo stack so seek can be undone via Ctrl+Z.
    position = -1 means seek to end (restore all features).

    Response shape mirrors undo/redo:
      • cluster-only diff_kind when the seek changes only cluster_transforms
        (common when slider-scrubbing through cluster_op entries) — frontend
        applies a delta in-place via _applyClusterUndoRedoDeltas, no backend
        geometry recompute beyond what _seek_feature_log already did.
      • Embedded full-geometry response otherwise — saves the legacy
        getGeometry() second round-trip the slider previously paid on every
        click.

    Per-step wall-clock is exposed in the ``Server-Timing`` response header
    so the frontend (`_request` in client.js) can log it next to the network
    round-trip time.
    """
    from backend.core.validator import validate_design

    trace = _TimingTrace()
    with trace.step("clone_prev"):
        prev = design_state.get_or_404().model_copy(deep=True)
    with trace.step("seek_log"):
        updated = _seek_feature_log(prev, body.position, body.sub_position)
    with trace.step("commit_state"):
        design_state.set_design(updated)
    with trace.step("validate"):
        report = validate_design(updated)
    with trace.step("response"):
        payload = _design_replace_response(prev, updated, report, trace=trace)
    return trace.attach(ORJSONResponse(payload))


class GeometryBatchBody(BaseModel):
    positions: list[int]   # e.g. [-2, 0, 1, -1]; duplicates ignored


@router.post("/design/features/geometry-batch", status_code=200)
def geometry_batch(body: GeometryBatchBody) -> dict:
    """Return pre-computed geometry for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake keyframe states before playback so that
    all geometry interpolation is client-side and frame-accurate.

    Geometry is shipped in COMPACT per-helix-per-direction parallel-array form
    (``nucleotides_compact``) — ~50% smaller wire and ~50% faster to parse than
    the legacy per-nuc dict list. Frontend ``animation_player`` re-materialises
    the lookup maps it actually needs (posMap / bnMap / strandSet / helixSet).

    Returns: { "<position>": { nucleotides_compact, helix_axes }, ... }
    """
    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        result[str(position)] = {
            "nucleotides_compact": _compact_geometry_for_design(d),
            "helix_axes":          deformed_helix_axes(d),
        }
    return result


@router.post("/design/features/atomistic-batch", status_code=200)
def atomistic_batch(body: GeometryBatchBody) -> dict:
    """Return flat atom-position arrays for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake atomistic states before playback.

    Returns: { "<position>": [x0,y0,z0, x1,y1,z1, ...], ... }
    Positions are indexed by atom serial (same order as GET /design/atomistic).
    """
    from backend.core.atomistic import build_atomistic_model, atomistic_positions_flat

    design = design_state.get_or_404()
    result: dict[str, list] = {}
    for position in set(body.positions):
        d = _seek_feature_log(design, position)
        model = build_atomistic_model(d)
        result[str(position)] = atomistic_positions_flat(model)
    return result


class SurfaceBatchBody(BaseModel):
    positions:    list[int]
    color_mode:   str   = "strand"
    probe_radius: float = 0.28
    grid_spacing: float = 0.20


@router.post("/design/features/surface-batch", status_code=200)
def surface_batch(body: SurfaceBatchBody) -> dict:
    """Return full mesh data for multiple feature-log positions in one call.

    Stateless — does NOT change the active design cursor or push to the undo stack.
    Used by the animation player to pre-bake surface states before playback.

    Returns { "<position>": { vertices: [x,y,z, ...], faces: [i,j,k, ...] }, ... }.
    Both vertices and faces are included because different feature-log positions can
    produce different marching-cubes topologies (different vertex counts), so the
    frontend needs to rebuild the geometry buffer when topology changes mid-animation.
    """
    from backend.core.atomistic import build_atomistic_model
    from backend.core.surface import compute_surface

    design = design_state.get_or_404()
    result: dict[str, dict] = {}
    for position in set(body.positions):
        d     = _seek_feature_log(design, position)
        model = build_atomistic_model(d)
        mesh  = compute_surface(model.atoms,
                                grid_spacing=body.grid_spacing,
                                probe_radius=body.probe_radius)
        verts = [round(float(v), 5) for v in mesh.vertices.ravel()]
        faces = [int(f) for f in mesh.faces.ravel()]
        result[str(position)] = {
            "vertices": verts,
            "faces":    faces,
        }
    return result


# ── Deformation endpoints ─────────────────────────────────────────────────────


class AddDeformationBody(BaseModel):
    type: str           # 'twist' | 'bend'
    plane_a_bp: int
    plane_b_bp: int
    affected_helix_ids: list[str] = []
    # When non-empty, restrict affected helices to the union of these clusters' helix_ids.
    # Empty list = unscoped (apply to all helices crossing the planes).
    cluster_ids: list[str] = []
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


def _resolve_cluster_scope(design: Design, cluster_ids: list[str], helix_ids: list[str]) -> dict:
    """Filter helix_ids to the union of the named clusters' helix_ids.

    Drops cluster ids that don't exist in the design. Returns
    ``{"cluster_ids": [...], "helix_ids": [...]}``. When the resolved cluster
    list is empty (none provided, or all missing), helix_ids is returned
    unchanged — the deformation is unscoped.
    """
    by_id = {c.id: c for c in design.cluster_transforms}
    resolved = [cid for cid in (cluster_ids or []) if cid in by_id]
    if not resolved:
        return {"cluster_ids": [], "helix_ids": helix_ids}
    allowed: set[str] = set()
    for cid in resolved:
        allowed.update(by_id[cid].helix_ids)
    return {
        "cluster_ids": resolved,
        "helix_ids":   [h for h in helix_ids if h in allowed],
    }


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

    if entry.feature_type == 'overhang_rotation':
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
                    if prev_entry.feature_type != 'overhang_rotation':
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
                updates['rotation'] = prev_rot if prev_rot is not None else [0.0, 0.0, 0.0, 1.0]

            sd_touched = {sd_id for (oid, sd_id) in sd_pairs_in_entry if oid == ovhg.id}
            if sd_touched:
                new_sds = []
                for sd in ovhg.sub_domains:
                    if sd.id not in sd_touched:
                        new_sds.append(sd)
                        continue
                    prev_theta: Optional[float] = None
                    prev_phi:   Optional[float] = None
                    for prev_entry in reversed(log[:idx]):
                        if prev_entry.feature_type != 'overhang_rotation':
                            continue
                        prev_sd_ids = prev_entry.sub_domain_ids
                        prev_thetas = prev_entry.sub_domain_thetas_deg
                        prev_phis   = prev_entry.sub_domain_phis_deg
                        for pi, poid in enumerate(prev_entry.overhang_ids):
                            if poid != ovhg.id:
                                continue
                            sd_pi = prev_sd_ids[pi] if pi < len(prev_sd_ids) else None
                            if sd_pi == sd.id:
                                prev_theta = float(prev_thetas[pi])
                                prev_phi   = float(prev_phis[pi])
                                break
                        if prev_theta is not None:
                            break
                    new_sds.append(sd.model_copy(update={
                        'rotation_theta_deg': prev_theta if prev_theta is not None else 0.0,
                        'rotation_phi_deg':   prev_phi   if prev_phi   is not None else 0.0,
                    }))
                updates['sub_domains'] = new_sds

            new_overhangs.append(ovhg.model_copy(update=updates) if updates else ovhg)
        return design.copy_with(overhangs=new_overhangs, feature_log=new_log)

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

    # When clusters are specified, restrict affected helices to the union of those
    # clusters' helix_ids. Drops cluster ids that no longer exist in the design.
    resolved_cluster_ids = _resolve_cluster_scope(design, body.cluster_ids, helix_ids)
    helix_ids = resolved_cluster_ids["helix_ids"]
    cluster_ids = resolved_cluster_ids["cluster_ids"]

    op = DeformationOp(
        type=body.type,
        plane_a_bp=body.plane_a_bp,
        plane_b_bp=body.plane_b_bp,
        affected_helix_ids=helix_ids,
        cluster_ids=cluster_ids,
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
            "cluster_ids":       list(op.cluster_ids),
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
# Camera-pose route handlers were extracted to ``routes_camera_poses.py``
# in Refactor 13-B (same pattern as 10-F loop-skip extraction).


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
    spin_axis: Optional[str] = None
    spin_rotations: float = 0.0
    spin_invert: bool = False
    text: str = ""
    text_font_family: str = "sans-serif"
    text_font_size_px: int = 24
    text_color: str = "#ffffff"
    text_bold: bool = False
    text_italic: bool = False
    text_align: str = "center"


class PatchKeyframeBody(BaseModel):
    name: Optional[str] = None
    camera_pose_id: Optional[str] = None
    feature_log_index: Optional[int] = None
    hold_duration_s: Optional[float] = None
    transition_duration_s: Optional[float] = None
    easing: Optional[str] = None
    spin_axis: Optional[str] = None
    spin_rotations: Optional[float] = None
    spin_invert: Optional[bool] = None
    text: Optional[str] = None
    text_font_family: Optional[str] = None
    text_font_size_px: Optional[int] = None
    text_color: Optional[str] = None
    text_bold: Optional[bool] = None
    text_italic: Optional[bool] = None
    text_align: Optional[str] = None


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
        spin_axis=body.spin_axis,
        spin_rotations=body.spin_rotations,
        spin_invert=body.spin_invert,
        text=body.text,
        text_font_family=body.text_font_family,
        text_font_size_px=body.text_font_size_px,
        text_color=body.text_color,
        text_bold=body.text_bold,
        text_italic=body.text_italic,
        text_align=body.text_align,
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

    # Use model_fields_set so explicit nulls (e.g. spin_axis=null when clearing
    # spin) propagate. Skipping None values would make the field un-clearable
    # via the API once set — same convention as update_assembly_keyframe.
    patch = body.model_dump(include=body.model_fields_set)
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

    Only the auto-created default catch-all cluster (is_default=True) surrenders
    helices to the new cluster.  All intentional clusters — user-created or
    imported (is_default=False, e.g. scaffold clusters from a multi-scaffold
    import) — are left completely untouched so they cannot be overridden.

    If no clusters exist at all, auto-creates the default cluster first so the
    remainder always has a home.
    """
    from backend.core.models import ClusterRigidTransform, DomainRef
    from backend.core.validator import validate_design

    design = design_state.get_or_404()
    # Ensure a default cluster exists before splitting so the remainder lands somewhere.
    # This is a no-op when intentional clusters (e.g. scaffold clusters) already exist.
    design = _ensure_default_cluster(design)

    new_helix_set = set(body.helix_ids)

    # Strip the new cluster's helices ONLY from the default catch-all cluster.
    # Non-default clusters (scaffold-imported, user-created) are preserved intact.
    surviving = []
    for c in design.cluster_transforms:
        if c.is_default:
            remaining = [h for h in c.helix_ids if h not in new_helix_set]
            if remaining:
                surviving.append(c.model_copy(update={"helix_ids": remaining}))
            # Default cluster with no remaining helices is silently dropped.
        else:
            surviving.append(c)

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

    # Joints are stored in the cluster's LOCAL frame, so a cluster transform
    # change leaves cluster_joints invariant — world-space axes are derived
    # lazily from cluster_transforms[id] at read time. The legacy world-space
    # update math (J_new = R_delta @ (J - D_old) + D_new) accumulated
    # floating-point drift across many commits and is no longer needed.
    updated_joints = list(design.cluster_joints)

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
            c for c in ds_conns
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
        if ha: needed_helix_ids.add(ha)
        if hb: needed_helix_ids.add(hb)
    if not needed_helix_ids:
        return {"bridge_nucs": []}

    # Run partial geometry → _emit_bridge_nucs → filter to bridge nucs only.
    full = _geometry_for_helices(design, frozenset(needed_helix_ids))
    bridge_nucs = [n for n in full if (n.get("helix_id") or "").startswith("__lnk__")]
    return {"bridge_nucs": bridge_nucs}


# ── Cluster joint routes ───────────────────────────────────────────────────────


class AddJointBody(BaseModel):
    axis_origin: List[float]       # [x, y, z] nm world-space
    axis_direction: List[float]    # unit vector (normalised by backend)
    surface_detail: int = 6        # lateral face count used in surface approximation
    name: str = "Joint"
    min_angle_deg: float = -180.0  # mechanical lower limit (degrees)
    max_angle_deg: float =  180.0  # mechanical upper limit (degrees)


class PatchJointBody(BaseModel):
    axis_origin: Optional[List[float]] = None
    axis_direction: Optional[List[float]] = None
    surface_detail: Optional[int] = None
    name: Optional[str] = None
    min_angle_deg: Optional[float] = None
    max_angle_deg: Optional[float] = None


def _build_add_joint(design: Design, params: dict) -> Design:
    """Pure builder for the joint-place op.

    *params* keys: cluster_id, joint_id, name, surface_detail,
    local_axis_origin, local_axis_direction.

    Stored axis is already in the cluster's local frame; world-space inputs
    are converted at the endpoint before this builder is called so the
    feature-log params are deterministic across replays (the local-frame
    axis is invariant under subsequent cluster transforms).
    """
    cluster_id = params['cluster_id']
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cluster is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")
    joint = ClusterJoint(
        id=params['joint_id'],
        cluster_id=cluster_id,
        name=params.get('name', 'Joint'),
        local_axis_origin=list(params['local_axis_origin']),
        local_axis_direction=list(params['local_axis_direction']),
        surface_detail=int(params.get('surface_detail', 6)),
        min_angle_deg=float(params.get('min_angle_deg', -180.0)),
        max_angle_deg=float(params.get('max_angle_deg',  180.0)),
    )
    # Each cluster has at most one joint — replace any existing one.
    existing = [j for j in design.cluster_joints if j.cluster_id != cluster_id]
    return design.copy_with(cluster_joints=existing + [joint])


def _build_update_joint(design: Design, params: dict) -> Design:
    """Pure builder for the joint-update op.

    *params* keys: joint_id and any subset of name, surface_detail,
    local_axis_origin, local_axis_direction. The endpoint resolves
    world→local and stores the local-frame fields directly, so replay is
    deterministic regardless of intervening cluster transforms.
    """
    joint_id = params['joint_id']
    joints = list(design.cluster_joints)
    idx = next((i for i, j in enumerate(joints) if j.id == joint_id), None)
    if idx is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")
    fields: dict = {}
    if 'name' in params:
        fields['name'] = params['name']
    if 'surface_detail' in params:
        fields['surface_detail'] = int(params['surface_detail'])
    if 'local_axis_origin' in params:
        fields['local_axis_origin'] = list(params['local_axis_origin'])
    if 'local_axis_direction' in params:
        fields['local_axis_direction'] = list(params['local_axis_direction'])
    if 'min_angle_deg' in params:
        fields['min_angle_deg'] = float(params['min_angle_deg'])
    if 'max_angle_deg' in params:
        fields['max_angle_deg'] = float(params['max_angle_deg'])
    # Pydantic re-runs the model validator on `model_copy(update=…)`, so an
    # update that would invert min/max is caught here rather than silently
    # accepted.
    cur = joints[idx]
    new_min = fields.get('min_angle_deg', cur.min_angle_deg)
    new_max = fields.get('max_angle_deg', cur.max_angle_deg)
    if new_max < new_min:
        raise HTTPException(
            400,
            detail=f"max_angle_deg ({new_max}) must be >= min_angle_deg ({new_min}).",
        )
    joints[idx] = joints[idx].model_copy(update=fields)
    return design.copy_with(cluster_joints=joints)


def _build_delete_joint(design: Design, params: dict) -> Design:
    """Pure builder for the joint-delete op."""
    joint_id = params['joint_id']
    joints = [j for j in design.cluster_joints if j.id != joint_id]
    if len(joints) == len(design.cluster_joints):
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")
    return design.copy_with(cluster_joints=joints)


@router.post("/design/cluster/{cluster_id}/joint", status_code=200)
def add_joint(cluster_id: str, body: AddJointBody) -> dict:
    """Create a revolute joint on a cluster.

    The frontend computes the axis as the face-normal of the cluster's
    hull approximation in WORLD space (where the user clicked) and sends
    it here. The backend normalises the direction and converts to the
    cluster's LOCAL frame for storage so the axis stays drift-free under
    subsequent cluster transforms. Logged as a 'joint-place' minor op
    under the open Fine Routing cluster (or opens a new one).
    """
    import math as _math
    import uuid as _uuid
    from backend.core.models import _world_to_local_joint

    design = design_state.get_or_404()
    cluster = next((c for c in design.cluster_transforms if c.id == cluster_id), None)
    if cluster is None:
        raise HTTPException(404, detail=f"Cluster {cluster_id!r} not found.")

    dx, dy, dz = body.axis_direction[0], body.axis_direction[1], body.axis_direction[2]
    length = _math.sqrt(dx * dx + dy * dy + dz * dz)
    if length < 1e-9:
        raise HTTPException(400, detail="axis_direction must be a non-zero vector.")
    world_direction = [dx / length, dy / length, dz / length]

    ct_dict = {
        'rotation':    list(cluster.rotation),
        'translation': list(cluster.translation),
        'pivot':       list(cluster.pivot),
    }
    local_origin, local_dir = _world_to_local_joint(
        list(body.axis_origin), world_direction, ct_dict,
    )

    if body.max_angle_deg < body.min_angle_deg:
        raise HTTPException(
            400,
            detail=f"max_angle_deg ({body.max_angle_deg}) must be >= "
                   f"min_angle_deg ({body.min_angle_deg}).",
        )
    params = {
        'cluster_id':           cluster_id,
        'joint_id':             str(_uuid.uuid4()),
        'name':                 body.name,
        'surface_detail':       body.surface_detail,
        'local_axis_origin':    local_origin,
        'local_axis_direction': local_dir,
        'min_angle_deg':        body.min_angle_deg,
        'max_angle_deg':        body.max_angle_deg,
    }
    label = f"Place joint {body.name!r} on cluster {cluster_id}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='joint-place',
        label=label,
        params=params,
        fn=lambda d: _build_add_joint(d, params),
    )
    return _design_response(updated, report)


@router.patch("/design/joint/{joint_id}", status_code=200)
def update_joint(joint_id: str, body: PatchJointBody) -> dict:
    """Update joint properties.

    Body's axis_origin / axis_direction are interpreted as WORLD-space
    (matching the create endpoint's input convention). They're converted
    to the cluster's local frame before storage. Logged as a 'joint-update'
    minor op.
    """
    import math as _math
    from backend.core.models import _world_to_local_joint, _local_to_world_joint

    design = design_state.get_or_404()
    joint  = next((j for j in design.cluster_joints if j.id == joint_id), None)
    if joint is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")
    cluster = next((c for c in design.cluster_transforms if c.id == joint.cluster_id), None)
    ct_dict = None if cluster is None else {
        'rotation':    list(cluster.rotation),
        'translation': list(cluster.translation),
        'pivot':       list(cluster.pivot),
    }

    params: dict = {'joint_id': joint_id}
    if body.name is not None:
        params['name'] = body.name
    if body.surface_detail is not None:
        params['surface_detail'] = int(body.surface_detail)
    if body.axis_origin is not None or body.axis_direction is not None:
        cur_world_origin, cur_world_dir = _local_to_world_joint(
            joint.local_axis_origin, joint.local_axis_direction, cluster,
        )
        new_world_origin = list(body.axis_origin) if body.axis_origin is not None else cur_world_origin
        if body.axis_direction is not None:
            dx, dy, dz = body.axis_direction[0], body.axis_direction[1], body.axis_direction[2]
            length = _math.sqrt(dx * dx + dy * dy + dz * dz)
            if length < 1e-9:
                raise HTTPException(400, detail="axis_direction must be a non-zero vector.")
            new_world_dir = [dx / length, dy / length, dz / length]
        else:
            new_world_dir = cur_world_dir
        local_origin, local_dir = _world_to_local_joint(new_world_origin, new_world_dir, ct_dict)
        params['local_axis_origin']    = local_origin
        params['local_axis_direction'] = local_dir
    if body.min_angle_deg is not None:
        params['min_angle_deg'] = float(body.min_angle_deg)
    if body.max_angle_deg is not None:
        params['max_angle_deg'] = float(body.max_angle_deg)
    new_min = params.get('min_angle_deg', joint.min_angle_deg)
    new_max = params.get('max_angle_deg', joint.max_angle_deg)
    if new_max < new_min:
        raise HTTPException(
            400,
            detail=f"max_angle_deg ({new_max}) must be >= min_angle_deg ({new_min}).",
        )

    label = f"Update joint {joint.name!r}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='joint-update',
        label=label,
        params=params,
        fn=lambda d: _build_update_joint(d, params),
    )
    return _design_response(updated, report)


@router.delete("/design/joint/{joint_id}", status_code=200)
def delete_joint(joint_id: str) -> dict:
    """Delete a joint. Logged as a 'joint-delete' minor op."""
    design = design_state.get_or_404()
    joint  = next((j for j in design.cluster_joints if j.id == joint_id), None)
    if joint is None:
        raise HTTPException(404, detail=f"Joint {joint_id!r} not found.")

    params = {'joint_id': joint_id}
    label = f"Delete joint {joint.name!r}"
    updated, report, _entry = design_state.mutate_with_minor_log(
        op_subtype='joint-delete',
        label=label,
        params=params,
        fn=lambda d: _build_delete_joint(d, params),
    )
    return _design_response(updated, report)


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
        clear_all_loop_skips,
        sq_lattice_periodic_skips,
        twist_loop_skips,
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

    n_helices = len(all_mods)
    n_marks = sum(len(ls) for ls in all_mods.values())
    label = f"Add loops/skips ({n_marks} mark{'s' if n_marks != 1 else ''} on {n_helices} helix{'es' if n_helices != 1 else ''})"
    updated, report, _entry = design_state.mutate_with_feature_log(
        op_kind='apply-loop-skips',
        label=label,
        params={
            'helix_count':       n_helices,
            'mark_count':        n_marks,
            'sq_periodic':       design.lattice_type == LatticeType.SQUARE,
            'deformation_count': len(design.deformations),
        },
        fn=lambda d: apply_loop_skips(d, all_mods),
    )
    response = _design_response(updated, report)
    response["loop_skips"] = {hid: len(ls) for hid, ls in all_mods.items()}
    return response



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

    design, report = design_state.mutate_with_reconcile(_apply)
    return _design_response(design, report)


@router.post("/design/extensions", status_code=201)
def add_strand_extension(body: StrandExtensionRequest) -> dict:
    """Add a terminal extension (sequence and/or modification) to a strand's 5′ or 3′ end."""
    import re

    design = design_state.get_or_404()

    strand = design.find_strand(body.strand_id)
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

    design, report = design_state.mutate_with_reconcile(_apply)
    updated = next(x for x in design.extensions if x.id == ext_id)
    return {"extension": updated.model_dump(), **_design_response(design, report)}


@router.delete("/design/extensions/{ext_id}")
def delete_strand_extension(ext_id: str) -> dict:
    """Remove a strand extension."""
    design = design_state.get_or_404()
    if not any(x.id == ext_id for x in design.extensions):
        raise HTTPException(404, detail=f"StrandExtension {ext_id!r} not found.")

    design, report = design_state.mutate_with_reconcile(
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


@router.get("/design/debug/mrdna-roundtrip")
def debug_mrdna_roundtrip() -> Response:
    """Run a zero-step mrdna round-trip test on the active design.

    Builds the mrdna coarse model (dry_run=True, no simulation), reconstructs
    atomistic positions via nuc_pos_override_from_mrdna_coarse, and returns a
    zip archive containing:
      - before.pdb  — direct NADOC → atomistic path
      - after.pdb   — NADOC → mrdna CG → override → atomistic path
      - stats.txt   — P-atom RMSD, mean/max displacement, atom counts
    """
    import io
    import math
    import tempfile
    import zipfile
    import numpy as np
    import MDAnalysis as mda

    from backend.core.gromacs_package import _build_gromacs_input_pdb, _find_top_dir, _pick_ff
    from backend.core.mrdna_bridge import (
        mrdna_model_from_nadoc,
        nuc_pos_override_from_mrdna_coarse,
    )

    design = design_state.get_or_404()
    ff = _pick_ff(_find_top_dir())

    # ── Direct path: NADOC → atomistic (GROMACS CHARMM36 PDB) ────────────────
    before_pdb = _build_gromacs_input_pdb(design, ff)

    # ── mrdna path: dry_run → coarse PDB → override → atomistic ──────────────
    with tempfile.TemporaryDirectory(prefix="nadoc_roundtrip_") as tmpdir:
        import pathlib
        model = mrdna_model_from_nadoc(design)
        model.simulate(
            "roundtrip",
            directory=tmpdir,
            output_directory="output",
            dry_run=True,
            num_steps=0,
        )

        psf = pathlib.Path(tmpdir) / "roundtrip.psf"
        pdb = pathlib.Path(tmpdir) / "roundtrip.pdb"
        if not psf.exists():
            psf = pathlib.Path(tmpdir) / "roundtrip-0.psf"
            pdb = pathlib.Path(tmpdir) / "roundtrip-0.pdb"

        # Synthetic single-frame DCD from initial PDB
        dcd = pathlib.Path(tmpdir) / "roundtrip_frame0.dcd"
        u = mda.Universe(str(psf), str(pdb))
        with mda.Writer(str(dcd), n_atoms=u.atoms.n_atoms) as w:
            for _ in u.trajectory:
                w.write(u.atoms)

        override = nuc_pos_override_from_mrdna_coarse(
            design, str(psf), str(dcd), frame=0, sigma_nt=0.0
        )

    after_pdb = _build_gromacs_input_pdb(design, ff, nuc_pos_override=override)

    # ── Compute P-atom RMSD (parse both PDBs consistently) ───────────────────
    def _parse_pdb_atoms(pdb_text: str) -> dict:
        atoms = {}
        for line in pdb_text.splitlines():
            if line.startswith(("ATOM", "HETATM")):
                aname  = line[12:16].strip()
                chain  = line[21]
                resnum = line[22:26].strip()
                x      = float(line[30:38])
                y      = float(line[38:46])
                z      = float(line[46:54])
                atoms[(chain, resnum, aname)] = np.array([x, y, z])
        return atoms

    before_atoms = _parse_pdb_atoms(before_pdb)
    after_atoms  = _parse_pdb_atoms(after_pdb)

    p_disp: list[float] = []
    all_disp: list[float] = []
    common = set(before_atoms) & set(after_atoms)
    for k in common:
        d = float(np.linalg.norm(before_atoms[k] - after_atoms[k]))
        all_disp.append(d)
        if k[2] == "P":
            p_disp.append(d)

    rmsd_p   = math.sqrt(sum(x**2 for x in p_disp)   / len(p_disp))   if p_disp   else float("nan")
    rmsd_all = math.sqrt(sum(x**2 for x in all_disp) / len(all_disp)) if all_disp else float("nan")
    mean_p   = sum(p_disp) / len(p_disp) if p_disp else float("nan")
    max_p    = max(p_disp) if p_disp else float("nan")

    passed = rmsd_p < 2.0
    stats_txt = (
        f"NADOC mrdna Zero-Step Round-Trip Test\n"
        f"{'=' * 42}\n"
        f"Design:            {design.metadata.name or 'unnamed'}\n"
        f"Atoms in common:   {len(common)}\n"
        f"\n"
        f"RMSD all atoms:    {rmsd_all:.3f} Å\n"
        f"RMSD P atoms:      {rmsd_p:.3f} Å  ← primary metric\n"
        f"Mean P displace:   {mean_p:.3f} Å\n"
        f"Max  P displace:   {max_p:.3f} Å\n"
        f"\n"
        f"Threshold:         2.0 Å\n"
        f"Result:            {'PASS ✓' if passed else 'FAIL ✗'}\n"
        f"\n"
        f"Files\n"
        f"-----\n"
        f"before.pdb  — direct NADOC → atomistic\n"
        f"after.pdb   — NADOC → mrdna CG (0 steps) → atomistic\n"
        f"stats.txt   — this file\n"
    )

    name = (design.metadata.name or "design").replace(" ", "_")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{name}_roundtrip_before.pdb", before_pdb)
        zf.writestr(f"{name}_roundtrip_after.pdb",  after_pdb)
        zf.writestr("roundtrip_stats.txt", stats_txt)
    buf.seek(0)

    return Response(
        content    = buf.read(),
        media_type = "application/zip",
        headers    = {"Content-Disposition": f'attachment; filename="{name}_roundtrip.zip"'},
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


@router.get("/design/export/gromacs-complete")
def export_gromacs_complete() -> Response:
    """
    Complete GROMACS simulation package — ready to run on a fresh Ubuntu machine.

    Runs pdb2gmx + editconf server-side (GROMACS must be installed on the NADOC
    server) and returns a self-contained ZIP containing the topology, initial
    structure, bundled force-field files, MDP files, and a one-click launch script.
    """
    from backend.core.gromacs_package import build_gromacs_package

    design    = design_state.get_or_404()
    name      = (design.metadata.name or "design").replace(" ", "_")
    try:
        zip_bytes = build_gromacs_package(design)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(
        content    = zip_bytes,
        media_type = "application/zip",
        headers    = {"Content-Disposition": f'attachment; filename="{name}_gromacs.zip"'},
    )


@router.get("/design/export/gromacs-probe")
def probe_gromacs_installation() -> dict:
    """Return GROMACS availability and chosen force-field on this server."""
    from backend.core.gromacs_package import probe_gromacs
    return probe_gromacs()


@router.post("/design/export/gromacs-start")
def start_gromacs_export(
    package_name: str | None = None,
    use_deformed: bool = False,
    nvt_steps: int | None = None,
    solvate: bool = False,
    ion_conc_mM: float = 10.0,
):
    """
    Snapshot the current design and start building the GROMACS package in a
    background thread.  Returns a job_id; poll /gromacs-status/{job_id} to
    check progress, then fetch /gromacs-result/{job_id} to download the ZIP.

    Parameters
    ----------
    package_name : override the ZIP directory/file prefix (default: design name)
    use_deformed : if True, apply active deformation to helix positions
    nvt_steps    : override nsteps in nvt.mdp (default: 25 000 vacuum / 50 000 solvated)
    solvate      : add TIP3P water + MgCl2 ions
    ion_conc_mM  : MgCl2 concentration in mM (default: 10.0)
    """
    from backend.core.gromacs_package import build_gromacs_package

    design   = design_state.get_or_404()
    snapshot = copy.deepcopy(design)
    name     = (package_name or design.metadata.name or "design").replace(" ", "_")
    job_id   = str(_uuid.uuid4())

    with _gromacs_jobs_lock:
        _gromacs_jobs[job_id] = {
            "status": "running",
            "result": None,
            "error":  None,
            "name":   name,
        }

    def _run() -> None:
        try:
            data = build_gromacs_package(
                snapshot,
                package_name=name,
                use_deformed=use_deformed,
                nvt_steps=nvt_steps,
                solvate=solvate,
                ion_conc_mM=ion_conc_mM,
            )
            with _gromacs_jobs_lock:
                _gromacs_jobs[job_id]["status"] = "done"
                _gromacs_jobs[job_id]["result"] = data
        except Exception as exc:
            with _gromacs_jobs_lock:
                _gromacs_jobs[job_id]["status"] = "error"
                _gromacs_jobs[job_id]["error"]  = str(exc)

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@router.post("/design/export/gromacs-cg-start")
def start_gromacs_cg_export(
    package_name: str | None = None,
    nvt_steps: int | None = None,
    solvate: bool = False,
    ion_conc_mM: float = 10.0,
    oxdna_steps: int = 50_000,
):
    """
    oxDNA-pre-relaxed GROMACS export.

    Runs a short oxDNA energy minimisation on the current design, then
    uses the relaxed backbone positions as the starting structure for the
    GROMACS package.  Crossover terminal atom clashes (O5'/O1P at ~0.05 nm)
    are resolved by oxDNA before GROMACS EM, so EM converges in ~1000 steps
    instead of ~12000 and avoids the 10¹² kJ/mol LJ spike.

    Requires oxDNA to be installed (set OXDNA_BIN env var if not on PATH).
    Falls back gracefully: if oxDNA is unavailable the job fails with a clear
    error message; use /design/export/gromacs-start for the ideal-B-DNA path.

    Returns job_id; poll /design/export/gromacs-status/{job_id} then fetch
    /design/export/gromacs-result/{job_id} when done.
    """
    import os
    import tempfile as _tempfile
    import pathlib as _pathlib

    from backend.physics.oxdna_interface import (
        write_topology,
        write_configuration,
        write_oxdna_input,
        run_oxdna,
        read_configuration,
    )

    design   = design_state.get_or_404()
    snapshot = copy.deepcopy(design)
    geometry = _geometry_for_design(design)
    name     = (package_name or design.metadata.name or "design").replace(" ", "_")
    job_id   = str(_uuid.uuid4())

    with _gromacs_jobs_lock:
        _gromacs_jobs[job_id] = {
            "status": "running",
            "result": None,
            "error":  None,
            "name":   name,
        }

    def _run() -> None:
        try:
            oxdna_bin = os.environ.get("OXDNA_BIN", "oxDNA")
            with _tempfile.TemporaryDirectory() as tmpdir:
                p = _pathlib.Path(tmpdir)
                write_topology(snapshot, p / "topology.top")
                write_configuration(snapshot, geometry, p / "conf.dat")
                write_oxdna_input(
                    p / "topology.top", p / "conf.dat", p / "input.txt",
                    steps=oxdna_steps,
                    relaxation_steps=min(oxdna_steps // 10, 5000),
                )
                ret = run_oxdna(p / "input.txt", oxdna_bin=oxdna_bin, timeout=300)
                if ret is None:
                    raise RuntimeError(
                        f"oxDNA binary not found (tried: {oxdna_bin!r}). "
                        "Install with: conda install -c bioconda oxdna  "
                        "or set OXDNA_BIN env var.  "
                        "Use /design/export/gromacs-start for the ideal-B-DNA path."
                    )
                if ret != 0:
                    raise RuntimeError(
                        f"oxDNA exited with code {ret}. "
                        "Check design topology for disconnected strands."
                    )
                last_conf = p / "last_conf.dat"
                if not last_conf.exists():
                    raise RuntimeError("oxDNA finished but produced no last_conf.dat.")

                from backend.core.cg_to_atomistic import _smooth_cg_positions_per_domain
                cg_positions = read_configuration(last_conf, snapshot)
                nuc_pos_override = _smooth_cg_positions_per_domain(snapshot, cg_positions)

            from backend.core.gromacs_package import build_gromacs_package
            data = build_gromacs_package(
                snapshot,
                package_name=name,
                nuc_pos_override=nuc_pos_override,
                nvt_steps=nvt_steps,
                solvate=solvate,
                ion_conc_mM=ion_conc_mM,
            )
            with _gromacs_jobs_lock:
                _gromacs_jobs[job_id]["status"] = "done"
                _gromacs_jobs[job_id]["result"] = data
        except Exception as exc:
            with _gromacs_jobs_lock:
                _gromacs_jobs[job_id]["status"] = "error"
                _gromacs_jobs[job_id]["error"]  = str(exc)

    threading.Thread(target=_run, daemon=True).start()
    return {"job_id": job_id}


@router.get("/design/export/gromacs-status/{job_id}")
def gromacs_export_status(job_id: str) -> dict:
    """Poll for job status.  Returns {status, error, name}."""
    with _gromacs_jobs_lock:
        job = _gromacs_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"status": job["status"], "error": job.get("error"), "name": job["name"]}


@router.get("/design/export/gromacs-result/{job_id}")
def gromacs_export_result(job_id: str) -> Response:
    """
    Download the completed GROMACS ZIP.  Deletes the job from the store after
    returning so memory is freed immediately.
    """
    with _gromacs_jobs_lock:
        job = _gromacs_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job status: {job['status']}")
    result = job["result"]
    name   = job["name"]
    with _gromacs_jobs_lock:
        _gromacs_jobs.pop(job_id, None)
    return Response(
        content    = result,
        media_type = "application/zip",
        headers    = {"Content-Disposition": f'attachment; filename="{name}_gromacs.zip"'},
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


# ── Molecular Dynamics load ────────────────────────────────────────────────────


@router.post("/md/load")
def md_load(body: MdLoadRequest) -> dict:
    """
    Load a GROMACS trajectory by explicit topology and XTC paths and return metadata.

    Validates that the directory contains a NADOC-generated run (input_nadoc.pdb
    must exist alongside the topology file) and that the chain map matches the
    currently loaded design.
    Does not stream any trajectory data — use /ws/md-run for frame access.
    """
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.atomistic_to_nadoc import build_chain_map, build_p_gro_order
    from backend.core.md_metrics import count_frames, derive_total_ns, parse_log_metrics

    warnings: list[str] = []

    try:
        topology_path = Path(body.topology_path)
        xtc_path      = Path(body.xtc_path)
        run_dir       = topology_path.parent

        # Require input_nadoc.pdb in the same directory as the topology file
        input_pdb = run_dir / "input_nadoc.pdb"
        if not input_pdb.exists():
            return {"ok": False, "error": f"input_nadoc.pdb not found in {run_dir}", "warnings": []}

        # Find a log file: preferred names first, then most-recently-modified .log
        log_path = None
        for name in ("prod.log", "nvt.log", "npt.log", "em.log"):
            candidate = run_dir / name
            if candidate.exists():
                log_path = candidate
                break
        if log_path is None:
            log_files = sorted(run_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if log_files:
                log_path = log_files[0]

        # Build chain map from current design
        design    = design_state.get_or_404()
        model     = build_atomistic_model(design)
        chain_map = build_chain_map(model)
        try:
            pdb_text  = input_pdb.read_text(errors="replace")
            p_order   = build_p_gro_order(pdb_text, chain_map)
        except Exception as exc:
            warnings.append(f"Chain map build failed: {exc}")
        n_p_atoms = len(chain_map)

        metrics  = parse_log_metrics(log_path) if log_path else None
        warnings.extend(metrics.warnings if metrics else [])

        n_frames = count_frames(xtc_path, topology_path)
        total_ns = derive_total_ns(metrics, n_frames) if metrics else None

        return {
            "ok":            True,
            "n_frames":      n_frames,
            "total_ns":      total_ns,
            "ns_per_day":    metrics.ns_per_day    if metrics else None,
            "temperature_k": metrics.temperature_k if metrics else None,
            "dt_ps":         metrics.dt_ps         if metrics else None,
            "nstxout_comp":  metrics.nstxout_comp  if metrics else None,
            "xtc_path":      str(xtc_path),
            "topology_path": str(topology_path),
            "input_pdb":     str(input_pdb),
            "n_p_atoms":     n_p_atoms,
            "warnings":      warnings,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "warnings": []}


@router.get("/md/browse")
def md_browse(dir: str = "", ext: str = "") -> dict:
    """
    List server-side filesystem entries for the MD file picker.

    Parameters
    ----------
    dir : absolute directory path to list (empty → user home directory)
    ext : comma-separated extensions to filter files (e.g. ".gro,.tpr")
          Empty = show all non-hidden files
    """
    from pathlib import Path

    base = Path(dir).resolve() if dir else Path.home()
    exts = {e.strip().lower() for e in ext.split(",") if e.strip()} if ext else set()

    entries: list[dict] = []

    # Parent navigation
    parent = base.parent
    if parent != base:
        entries.append({"name": "..", "path": str(parent), "type": "dir", "size": 0})

    try:
        items = sorted(base.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except PermissionError:
        return {"path": str(base), "entries": entries}

    for p in items:
        if p.name.startswith("."):
            continue
        try:
            if p.is_dir():
                entries.append({"name": p.name, "path": str(p), "type": "dir", "size": 0})
            elif not exts or p.suffix.lower() in exts:
                entries.append({
                    "name": p.name,
                    "path": str(p),
                    "type": "file",
                    "size": p.stat().st_size,
                })
        except (PermissionError, OSError):
            continue

    return {"path": str(base), "entries": entries}
