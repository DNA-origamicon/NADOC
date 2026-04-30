"""
Seamed scaffold router — Create Seam + Create Near Ends + Create Far Ends
as one atomic pipeline.

Phase 1 (Seam): place Holliday junctions at interior helix pairs from the
  Hamiltonian path (path[1,2], path[3,4], …).
Phase 2 (Near Ends): extend helices at the lo face and place scaffold
  crossovers (path[0,1], path[2,3], …).
Phase 3 (Far Ends): extend helices at the hi face and place scaffold
  crossovers using the same pairs as Near Ends (minus one open end).

Three-Layer Law: only topology is modified. No geometry or physics is touched
except for the helix axis_start/axis_end extension that creates physical room
for the added nucleotides.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HC_CROSSOVER_PERIOD,
    SQ_CROSSOVER_PERIOD,
)
from backend.core.crossover_positions import crossover_neighbor, validate_crossover
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    HalfCrossover,
    LatticeType,
    StrandType,
    Vec3,
)

# Bow-right offset sets for scaffold crossovers (bp % period ∈ set → bow-right).
_HC_SCAF_BOW_RIGHT: frozenset[int] = frozenset({2, 5, 9, 12, 16, 19})
_SQ_SCAF_BOW_RIGHT: frozenset[int] = frozenset({0, 3, 5, 8, 11, 13, 16, 19, 21, 24, 27, 29})


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _scaffold_coverage(design: Design) -> dict[str, list[dict]]:
    """Build per-helix scaffold coverage: helix_id → sorted merged [{lo, hi}]."""
    raw: dict[str, list[tuple[int, int]]] = {}
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in s.domains:
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            raw.setdefault(dom.helix_id, []).append((lo, hi))
    merged: dict[str, list[dict]] = {}
    for hid, ivs in raw.items():
        srt = sorted(ivs)
        m = [{"lo": srt[0][0], "hi": srt[0][1]}]
        for lo, hi in srt[1:]:
            if lo <= m[-1]["hi"] + 1:
                m[-1]["hi"] = max(m[-1]["hi"], hi)
            else:
                m.append({"lo": lo, "hi": hi})
        merged[hid] = m
    return merged


def _intersect(cA: list[dict], cB: list[dict]) -> list[dict]:
    return [
        {"lo": max(a["lo"], b["lo"]), "hi": min(a["hi"], b["hi"])}
        for a in cA for b in cB
        if max(a["lo"], b["lo"]) <= min(a["hi"], b["hi"])
    ]


def _is_forward(row: int, col: int) -> bool:
    return (row + col) % 2 == 0


def _scaf_nb(design: Design, row: int, col: int, bp: int) -> tuple[int, int] | None:
    return crossover_neighbor(design.lattice_type, row, col, bp, is_scaffold=True)


def _nick_bp(
    xover_bp: int,
    direction: Direction,
    period: int,
    bow_right: frozenset[int],
) -> int:
    mod = xover_bp % period
    lower = xover_bp - 1 if mod in bow_right else xover_bp
    return lower if direction == Direction.FORWARD else lower + 1


def _build_adj(
    design: Design,
    coverage: dict[str, list[dict]],
) -> dict[str, set[str]]:
    """Undirected scaffold adjacency: edge when a valid scaffold xover bp exists."""
    scaf_helices = [
        h for h in design.helices
        if h.id in coverage and h.grid_pos is not None
    ]
    adj: dict[str, set[str]] = {h.id: set() for h in scaf_helices}
    for i, hA in enumerate(scaf_helices):
        rowA, colA = hA.grid_pos
        covA = coverage[hA.id]
        for j in range(i + 1, len(scaf_helices)):
            hB = scaf_helices[j]
            covB = coverage[hB.id]
            nb_target = tuple(hB.grid_pos)
            found = any(
                _scaf_nb(design, rowA, colA, bp) == nb_target
                for iv in _intersect(covA, covB)
                for bp in range(iv["lo"], iv["hi"] + 1)
            )
            if found:
                adj[hA.id].add(hB.id)
                adj[hB.id].add(hA.id)
    return adj


def _hamiltonian_path(
    ids: list[str],
    adj: dict[str, set[str]],
    start_from: str | None = None,
) -> list[str] | None:
    """DFS Hamiltonian path with degree-ascending neighbor ordering."""
    vis: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        vis.add(node); path.append(node)
        if len(path) == len(ids):
            return True
        for nb in sorted(adj[node] - vis, key=lambda n: len(adj[n])):
            if dfs(nb):
                return True
        vis.discard(node); path.pop()
        return False

    ordered = sorted(ids, key=lambda n: len(adj[n]))
    starters = ([start_from] + [n for n in ordered if n != start_from]
                if start_from is not None else ordered)
    for s in starters:
        vis.clear(); path.clear()
        if dfs(s):
            return path
    return None


def _nick_if_needed(
    design: Design, helix_id: str, bp_index: int, direction: Direction
) -> Design:
    """Nick guard — mirrors crud._nick_if_needed including terminal-stub guards."""
    from backend.core.lattice import _find_strand_at, make_nick
    try:
        strand, di = _find_strand_at(design, helix_id, bp_index, direction)
    except ValueError:
        return design
    dom = strand.domains[di]
    n = len(strand.domains)
    if bp_index == dom.end_bp and di < n - 1:
        return design  # inter-domain boundary
    if di == 0 and bp_index == dom.start_bp:
        return design  # 1-nt left stub guard
    if di == n - 1:
        stub = (
            (direction == Direction.FORWARD and bp_index == dom.end_bp - 1) or
            (direction == Direction.REVERSE and bp_index == dom.end_bp + 1)
        )
        if stub:
            return design  # 1-nt right stub guard
    try:
        return make_nick(design, helix_id, bp_index, direction)
    except ValueError as exc:
        if "terminus" in str(exc):
            return design
        raise


def _ligate_xover(design: Design, xover: Crossover) -> Design:
    """Find the two strand fragments at the crossover and join them."""
    from backend.core.lattice import _ligate
    ha, hb = xover.half_a, xover.half_b
    three_p: dict = {}
    five_p: dict = {}
    for s in design.strands:
        if not s.domains:
            continue
        ld = s.domains[-1]
        three_p[(ld.helix_id, ld.end_bp, ld.direction)] = s
        fd = s.domains[0]
        five_p[(fd.helix_id, fd.start_bp, fd.direction)] = s
    for from_half, to_half in ((ha, hb), (hb, ha)):
        s_from = three_p.get((from_half.helix_id, from_half.index, from_half.strand))
        s_to = five_p.get((to_half.helix_id, to_half.index, to_half.strand))
        if s_from and s_to and s_from.id != s_to.id:
            return _ligate(design, s_from, s_to)
    return design


def _place_xover(
    design: Design,
    ha: HalfCrossover,
    hb: HalfCrossover,
    nick_a: int,
    nick_b: int,
    process_id: str,
    warnings: list[str],
) -> tuple[Design, Crossover | None]:
    """Nick + validate + record + ligate one scaffold crossover."""
    design = _nick_if_needed(design, ha.helix_id, nick_a, ha.strand)
    design = _nick_if_needed(design, hb.helix_id, nick_b, hb.strand)
    err = validate_crossover(design, ha, hb)
    if err:
        warnings.append(f"skip {ha.helix_id}↔{hb.helix_id} bp={ha.index}: {err}")
        return design, None
    xo = Crossover(half_a=ha, half_b=hb, process_id=process_id)
    design = design.copy_with(crossovers=list(design.crossovers) + [xo])
    design = _ligate_xover(design, xo)
    return design, xo


def _extend_helix_lo(
    design: Design,
    helix_by_id: dict,
    hid: str,
    new_lo: int,
) -> Design:
    helix = helix_by_id[hid]
    if new_lo >= helix.bp_start:
        return design
    extra = helix.bp_start - new_lo
    ax = helix.axis_end.to_array() - helix.axis_start.to_array()
    ax_len = float(math.sqrt(float((ax * ax).sum())))
    unit = ax / ax_len if ax_len > 1e-9 else [0.0, 0.0, 1.0]
    updated = helix.model_copy(update={
        "axis_start":   Vec3.from_array(helix.axis_start.to_array() - extra * BDNA_RISE_PER_BP * unit),
        "length_bp":    helix.length_bp + extra,
        "bp_start":     new_lo,
        "phase_offset": helix.phase_offset - extra * helix.twist_per_bp_rad,
    })
    helix_by_id[hid] = updated
    return design.copy_with(helices=[updated if h.id == hid else h for h in design.helices])


def _extend_helix_hi(
    design: Design,
    helix_by_id: dict,
    hid: str,
    new_hi: int,
) -> Design:
    helix = helix_by_id[hid]
    h_hi = helix.bp_start + helix.length_bp - 1
    if new_hi <= h_hi:
        return design
    extra = new_hi - h_hi
    ax = helix.axis_end.to_array() - helix.axis_start.to_array()
    ax_len = float(math.sqrt(float((ax * ax).sum())))
    unit = ax / ax_len if ax_len > 1e-9 else [0.0, 0.0, 1.0]
    updated = helix.model_copy(update={
        "axis_end":  Vec3.from_array(helix.axis_end.to_array() + extra * BDNA_RISE_PER_BP * unit),
        "length_bp": helix.length_bp + extra,
    })
    helix_by_id[hid] = updated
    return design.copy_with(helices=[updated if h.id == hid else h for h in design.helices])


def _extend_scaf_domain_lo(
    design: Design, hid: str, face_bp: int, new_lo: int
) -> Design:
    """Extend the scaffold domain on hid whose lo terminus is face_bp to new_lo."""
    for si, strand in enumerate(design.strands):
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for di, dom in enumerate(strand.domains):
            if dom.helix_id != hid or min(dom.start_bp, dom.end_bp) != face_bp:
                continue
            if min(dom.start_bp, dom.end_bp) <= new_lo:
                return design
            new_dom = (dom.model_copy(update={"start_bp": new_lo})
                       if dom.direction == Direction.FORWARD
                       else dom.model_copy(update={"end_bp": new_lo}))
            new_doms = list(strand.domains)
            new_doms[di] = new_dom
            new_strand = strand.model_copy(update={"domains": new_doms})
            new_strands = list(design.strands)
            new_strands[si] = new_strand
            return design.copy_with(strands=new_strands)
    return design


def _extend_scaf_domain_hi(
    design: Design, hid: str, face_bp: int, new_hi: int
) -> Design:
    """Extend the scaffold domain on hid whose hi terminus is face_bp to new_hi."""
    for si, strand in enumerate(design.strands):
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for di, dom in enumerate(strand.domains):
            if dom.helix_id != hid or max(dom.start_bp, dom.end_bp) != face_bp:
                continue
            if max(dom.start_bp, dom.end_bp) >= new_hi:
                return design
            new_dom = (dom.model_copy(update={"end_bp": new_hi})
                       if dom.direction == Direction.FORWARD
                       else dom.model_copy(update={"start_bp": new_hi}))
            new_doms = list(strand.domains)
            new_doms[di] = new_dom
            new_strand = strand.model_copy(update={"domains": new_doms})
            new_strands = list(design.strands)
            new_strands[si] = new_strand
            return design.copy_with(strands=new_strands)
    return design


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class SeamedResult:
    warnings: list[str] = field(default_factory=list)
    seam_xovers: int = 0
    near_end_xovers: int = 0
    far_end_xovers: int = 0


# ── Main entry point ──────────────────────────────────────────────────────────

def auto_scaffold_seamed(design: Design) -> tuple[Design, SeamedResult]:
    """Run the full seamed scaffold pipeline (Seam → Near Ends → Far Ends).

    All three phases share one atomic Design update; no undo checkpointing here
    (the caller in crud.py handles snapshot/set_design_silent).

    Returns (updated_design, result).  result.warnings lists any placements that
    were skipped due to validation errors or missing crossover sites.
    """
    result = SeamedResult()
    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow_right = _HC_SCAF_BOW_RIGHT if is_hc else _SQ_SCAF_BOW_RIGHT

    # ── Build coverage and adjacency ─────────────────────────────────────────
    coverage = _scaffold_coverage(design)
    if not coverage:
        result.warnings.append("No scaffold strands found.")
        return design, result

    helix_by_id: dict = {h.id: h for h in design.helices}
    adj = _build_adj(design, coverage)

    # ── Connected components ─────────────────────────────────────────────────
    visited: set[str] = set()
    components: list[list[str]] = []
    for hid in adj:
        if hid in visited:
            continue
        comp: list[str] = []
        stack = [hid]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid); comp.append(nid)
            stack.extend(adj[nid] - visited)
        components.append(comp)

    # ── Build seam and near-end pairs from Hamiltonian path ──────────────────
    seam_pairs:     list[tuple[str, str]] = []
    near_end_pairs: list[tuple[str, str]] = []

    for comp in components:
        if len(comp) < 4:
            result.warnings.append(
                f"Component of {len(comp)} helices skipped (minimum 4 required)."
            )
            continue

        def cov_sig(hid: str) -> str:
            ivs = sorted(coverage[hid], key=lambda iv: iv["lo"])
            return "|".join(f'{iv["lo"]}:{iv["hi"]}' for iv in ivs)

        sig_map: dict[str, list[str]] = {}
        for hid in comp:
            sig_map.setdefault(cov_sig(hid), []).append(hid)
        groups = list(sig_map.values())

        if len(groups) == 1:
            path = _hamiltonian_path(comp, adj)
        else:
            # Multi-section (dumbbell etc.): sort groups by total bp ascending.
            def grp_bp(g: list[str]) -> int:
                return sum(iv["hi"] - iv["lo"] + 1 for iv in coverage[g[0]])

            groups.sort(key=grp_bp)
            local_adjs = [
                {gid: adj[gid] & set(grp) for gid in grp}
                for grp in groups
            ]
            path = _hamiltonian_path(groups[0], local_adjs[0]) or list(groups[0])
            for gi in range(1, len(groups)):
                nxt_ids = groups[gi]
                nxt_set = set(nxt_ids)
                if (not any(nb in nxt_set for nb in adj[path[-1]])
                        and any(nb in nxt_set for nb in adj[path[0]])):
                    path.reverse()
                bridge = next(
                    (nb for nb in adj[path[-1]] if nb in nxt_set), None
                )
                if bridge:
                    nxt = (
                        _hamiltonian_path(nxt_ids, local_adjs[gi], bridge)
                        or _hamiltonian_path(nxt_ids, local_adjs[gi])
                        or nxt_ids
                    )
                    if nxt and nxt[0] != bridge:
                        nxt = list(reversed(nxt))
                    path = path + nxt
                else:
                    path = path + (_hamiltonian_path(nxt_ids, local_adjs[gi]) or nxt_ids)

        if not path or len(path) < 4:
            result.warnings.append(
                f"No Hamiltonian path found for component of {len(comp)} helices."
            )
            continue

        # Interior pairs (step 2 from index 1): seam Holliday junctions
        for i in range(1, len(path) - 2, 2):
            seam_pairs.append((path[i], path[i + 1]))
        # Exterior pairs (step 2 from index 0): near/far-end crossovers
        for i in range(0, len(path) - 1, 2):
            near_end_pairs.append((path[i], path[i + 1]))

    current = design

    # =========================================================================
    # Phase 1 — Create Seam
    # =========================================================================
    for hA_id, hB_id in seam_pairs:
        hA = helix_by_id.get(hA_id)
        hB = helix_by_id.get(hB_id)
        if not hA or not hB or hA.grid_pos is None or hB.grid_pos is None:
            continue
        rowA, colA = hA.grid_pos
        fwd = _is_forward(rowA, colA)
        strand_a = Direction.FORWARD if fwd else Direction.REVERSE
        strand_b = Direction.REVERSE if fwd else Direction.FORWARD

        for iv in _intersect(coverage.get(hA_id, []), coverage.get(hB_id, [])):
            lo, hi = iv["lo"], iv["hi"]
            mid = (lo + hi) / 2

            valid_bps = [
                bp for bp in range(lo, hi + 1)
                if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)
            ]
            if len(valid_bps) < 2:
                continue

            # Find the adjacent pair of valid bps closest to the interval midpoint.
            bp1 = bp2 = None
            best = float("inf")
            for j in range(len(valid_bps) - 1):
                if valid_bps[j + 1] == valid_bps[j] + 1:
                    d = abs((valid_bps[j] + valid_bps[j + 1]) / 2 - mid)
                    if d < best:
                        best = d; bp1, bp2 = valid_bps[j], valid_bps[j + 1]
            if bp1 is None:
                continue

            for xover_bp in (bp1, bp2):
                ha = HalfCrossover(helix_id=hA_id, index=xover_bp, strand=strand_a)
                hb = HalfCrossover(helix_id=hB_id, index=xover_bp, strand=strand_b)
                nick_a = _nick_bp(xover_bp, strand_a, period, bow_right)
                nick_b = _nick_bp(xover_bp, strand_b, period, bow_right)
                current, xo = _place_xover(
                    current, ha, hb, nick_a, nick_b,
                    "auto_scaffold_seamed:seam", result.warnings,
                )
                if xo:
                    result.seam_xovers += 1

    # =========================================================================
    # Phase 2 — Create Near Ends
    # =========================================================================
    coverage = _scaffold_coverage(current)  # rebuild after seam splits

    # Collect all near-end placements before mutating.
    near_specs: list[dict] = []
    for hA_id, hB_id in near_end_pairs:
        hA = helix_by_id.get(hA_id)
        hB = helix_by_id.get(hB_id)
        if not hA or not hB or hA.grid_pos is None or hB.grid_pos is None:
            continue
        rowA, colA = hA.grid_pos
        fwd = _is_forward(rowA, colA)
        strand_a = Direction.FORWARD if fwd else Direction.REVERSE
        strand_b = Direction.REVERSE if fwd else Direction.FORWARD
        covA, covB = coverage.get(hA_id, []), coverage.get(hB_id, [])

        for iv in _intersect(covA, covB):
            lo = iv["lo"]
            if (not any(c["lo"] == lo for c in covA)
                    or not any(c["lo"] == lo for c in covB)):
                continue
            xover_bp = next(
                (bp for bp in range(lo - 3, lo - period - 1, -1)
                 if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)),
                None,
            )
            if xover_bp is None:
                result.warnings.append(
                    f"[NearEnds] No xover found for {hA_id}↔{hB_id} near lo={lo}"
                )
                continue
            near_specs.append({
                "hA_id": hA_id, "hB_id": hB_id,
                "face_bp": lo, "new_lo": xover_bp, "xover_bp": xover_bp,
                "strand_a": strand_a, "strand_b": strand_b,
                "nick_a": _nick_bp(xover_bp, strand_a, period, bow_right),
                "nick_b": _nick_bp(xover_bp, strand_b, period, bow_right),
            })

    # Extend helix geometry (gather minimums first).
    helix_new_lo: dict[str, int] = {}
    for sp in near_specs:
        for hid in (sp["hA_id"], sp["hB_id"]):
            v = sp["new_lo"]
            if hid not in helix_new_lo or v < helix_new_lo[hid]:
                helix_new_lo[hid] = v
    for hid, new_lo in helix_new_lo.items():
        current = _extend_helix_lo(current, helix_by_id, hid, new_lo)

    # Extend scaffold domains, then place crossovers.
    for sp in near_specs:
        for hid in (sp["hA_id"], sp["hB_id"]):
            current = _extend_scaf_domain_lo(current, hid, sp["face_bp"], sp["new_lo"])
        ha = HalfCrossover(helix_id=sp["hA_id"], index=sp["xover_bp"], strand=sp["strand_a"])
        hb = HalfCrossover(helix_id=sp["hB_id"], index=sp["xover_bp"], strand=sp["strand_b"])
        current, xo = _place_xover(
            current, ha, hb, sp["nick_a"], sp["nick_b"],
            "create_near_ends", result.warnings,
        )
        if xo:
            result.near_end_xovers += 1

    # =========================================================================
    # Phase 3 — Create Far Ends
    # =========================================================================
    coverage = _scaffold_coverage(current)

    # Derive far-end pairs from near-end crossovers just placed.
    pair_seen: set[tuple[str, str]] = set()
    far_end_pairs: list[tuple[str, str]] = []
    for xo in current.crossovers:
        if xo.process_id != "create_near_ends":
            continue
        key: tuple[str, str] = tuple(sorted([xo.half_a.helix_id, xo.half_b.helix_id]))  # type: ignore[assignment]
        if key not in pair_seen:
            pair_seen.add(key)
            far_end_pairs.append((xo.half_a.helix_id, xo.half_b.helix_id))

    # Skip the pair that includes the lowest-indexed helix (open scaffold end).
    helix_array_idx = {h.id: i for i, h in enumerate(current.helices)}
    skip_id: str | None = None
    lowest = float("inf")
    for ha_id, hb_id in far_end_pairs:
        mi = min(helix_array_idx.get(ha_id, 0), helix_array_idx.get(hb_id, 0))
        if mi < lowest:
            lowest = mi
            skip_id = ha_id if helix_array_idx.get(ha_id, 0) <= helix_array_idx.get(hb_id, 0) else hb_id

    far_specs: list[dict] = []
    for ha_id, hb_id in far_end_pairs:
        if ha_id == skip_id or hb_id == skip_id:
            continue
        hA = helix_by_id.get(ha_id)
        hB = helix_by_id.get(hb_id)
        if not hA or not hB or hA.grid_pos is None or hB.grid_pos is None:
            continue
        rowA, colA = hA.grid_pos
        fwd = _is_forward(rowA, colA)
        strand_a = Direction.FORWARD if fwd else Direction.REVERSE
        strand_b = Direction.REVERSE if fwd else Direction.FORWARD
        covA, covB = coverage.get(ha_id, []), coverage.get(hb_id, [])

        for iv in _intersect(covA, covB):
            hi = iv["hi"]
            if (not any(c["hi"] == hi for c in covA)
                    or not any(c["hi"] == hi for c in covB)):
                continue
            xover_bp = next(
                (bp for bp in range(hi + 3, hi + period + 1)
                 if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)),
                None,
            )
            if xover_bp is None:
                result.warnings.append(
                    f"[FarEnds] No xover found for {ha_id}↔{hb_id} near hi={hi}"
                )
                continue
            far_specs.append({
                "hA_id": ha_id, "hB_id": hb_id,
                "face_bp": hi, "new_hi": xover_bp, "xover_bp": xover_bp,
                "strand_a": strand_a, "strand_b": strand_b,
                "nick_a": _nick_bp(xover_bp, strand_a, period, bow_right),
                "nick_b": _nick_bp(xover_bp, strand_b, period, bow_right),
            })

    # Extend helix geometry at hi face.
    helix_new_hi: dict[str, int] = {}
    for sp in far_specs:
        for hid in (sp["hA_id"], sp["hB_id"]):
            v = sp["new_hi"]
            if hid not in helix_new_hi or v > helix_new_hi[hid]:
                helix_new_hi[hid] = v
    for hid, new_hi in helix_new_hi.items():
        current = _extend_helix_hi(current, helix_by_id, hid, new_hi)

    # Extend scaffold domains, then place crossovers.
    for sp in far_specs:
        for hid in (sp["hA_id"], sp["hB_id"]):
            current = _extend_scaf_domain_hi(current, hid, sp["face_bp"], sp["new_hi"])
        ha = HalfCrossover(helix_id=sp["hA_id"], index=sp["xover_bp"], strand=sp["strand_a"])
        hb = HalfCrossover(helix_id=sp["hB_id"], index=sp["xover_bp"], strand=sp["strand_b"])
        current, xo = _place_xover(
            current, ha, hb, sp["nick_a"], sp["nick_b"],
            "create_far_ends", result.warnings,
        )
        if xo:
            result.far_end_xovers += 1

    return current, result
