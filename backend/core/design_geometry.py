"""Per-nucleotide display-geometry kernel (carve-up service push #46).

Pure compute: a ``Design`` in → a list of per-nucleotide geometry dicts out
(``backbone_position`` / ``base_position`` / ``base_normal`` / ``axis_tangent``
plus strand metadata). This is the geometry feed for every renderer and exporter
path — ``_design_response_with_geometry``, the assembly geometry routes, the
oxDNA/PDB/PSF exporters, the feature-log preview routes, etc.

These functions were marooned in ``backend/api/crud.py``'s "Internal helpers"
block; they touch no api-layer state (no ``design_state``, no ``HTTPException``),
so they belong in ``backend/core``. ``crud.py`` re-exports them under their
original underscore names, so the ~15 cross-file callers that do
``from backend.api.crud import _geometry_for_design`` keep working unchanged.

One reason to change: how NADOC turns topology + B-DNA constants into the
per-bead display geometry streamed to the Three.js renderer.

``backend/core`` must never import ``backend/api`` (L4) — the only api-ish
dependency, the live ``Design`` resolution, stays on the api side; here every
function takes the design as an explicit argument.
"""

from __future__ import annotations

import math

from backend.core.models import (
    Design,
    Direction,
    Domain,  # noqa: F401  (string annotation in _emit_bridge_nucs)
    Strand,  # noqa: F401  (string annotation in _emit_bridge_nucs)
    StrandType,
)
from backend.core.geometry import (
    nucleotide_positions_arrays_extended,
    nucleotide_positions_arrays_extended_right,
)
from backend.core.deformation import (
    _apply_ovhg_rotations_to_axes,
    apply_overhang_rotation_if_needed,
    deformed_helix_axes,
    deformed_nucleotide_arrays,
    effective_helix_for_geometry,
)


def _strand_nucleotide_info(design: Design, helix_ids: frozenset[str] | None = None) -> dict:
    """(helix_id, bp_index, Direction) → strand metadata dict.

    If *helix_ids* is given, only nucleotides whose domain is on one of those
    helices are included.  Used by partial geometry to avoid iterating all strands.
    """
    info: dict = {}
    # Display-only flexible-segment flag → per-bead (flows through `**sinfo`,
    # exactly like is_reference). Keyed by (strand_id, domain_index, bp, dir).
    # Driven by DERIVED connections, NOT raw marks: a bead is excluded from rigid
    # rendering (and drawn on the bowed arc instead) only when its marked run
    # actually formed a FlexibleConnection between two clusters. A mark that yields
    # no connection (e.g. an in-cluster ssDNA run) leaves its bead rigid-rendered,
    # so marking can never silently delete geometry.
    flex_marks = {
        (a.strand_id, a.domain_index, a.bp_index, a.direction)
        for conn in design.flexible_connections
        for a in conn.segment_bead_keys
    }
    # Unpaired (ssDNA) beads — gates the flexible-segment right-click menu on the
    # frontend. (helix_id, bp, direction) with no Watson-Crick partner.
    from backend.core.flexible_segments import unpaired_bead_keys
    _unpaired = unpaired_bead_keys(design)
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
                    "is_reference":   strand.is_reference,
                    "is_flexible_segment": (strand.id, di, bp, domain.direction) in flex_marks,
                    "is_unpaired":    (domain.helix_id, bp, domain.direction) in _unpaired,
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
    include_linker_helices: bool = False,
    compact_skips: bool = False,
) -> list[dict]:
    """Compute nucleotide geometry for *design*.

    If *helix_ids* is given, only nucleotides on those helices are returned.
    This is the partial-update fast path for Fix B: callers that know which
    helices changed pass that set to skip the other 90 % of geometry work.

    Extensions are only appended in full mode (helix_ids is None) — they depend
    on positions from arbitrary helices and must be returned together with the
    full geometry.

    *include_linker_helices*: per-design rendering skips ``__lnk__`` virtual
    bridge helices and emits their bridge nucs via ``_emit_bridge_nucs`` (which
    reads ``design.overhang_connections``). The cross-part assembly path has the
    bridge baked into a real world-space ``__lnk__`` helix but no
    ``overhang_connections`` on its synthetic design, so it sets this True to
    render the bridge helix directly through the normal per-helix pipeline.
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
        if helix.id.startswith("__lnk__") and not include_linker_helices:
            continue   # virtual linker helices have no real geometry (per-design:
                       # bridge nucs come from _emit_bridge_nucs below instead)
        arrs = deformed_nucleotide_arrays(helix, design, compact_skips=compact_skips)
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


def _geometry_for_design(
    design: Design,
    include_linker_helices: bool = False,
    compact_skips: bool = False,
) -> list[dict]:
    return _geometry_for_helices(
        design, include_linker_helices=include_linker_helices, compact_skips=compact_skips)


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
        deform_extended_arrays,
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
