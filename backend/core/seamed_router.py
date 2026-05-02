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


def _forced_scaffold_strand_ids(design: Design) -> set[str]:
    """Return scaffold strands that contain a recorded forced ligation edge."""
    if not design.forced_ligations:
        return set()

    protected: set[str] = set()
    for fl in design.forced_ligations:
        for strand in design.strands:
            if strand.strand_type != StrandType.SCAFFOLD:
                continue
            for i in range(len(strand.domains) - 1):
                a = strand.domains[i]
                b = strand.domains[i + 1]
                if (
                    a.helix_id == fl.three_prime_helix_id
                    and a.end_bp == fl.three_prime_bp
                    and a.direction == fl.three_prime_direction
                    and b.helix_id == fl.five_prime_helix_id
                    and b.start_bp == fl.five_prime_bp
                    and b.direction == fl.five_prime_direction
                ):
                    protected.add(strand.id)
    return protected


def _scaffold_coverage_excluding(
    design: Design,
    excluded_strand_ids: set[str],
) -> dict[str, list[dict]]:
    """Build scaffold coverage, omitting user-anchored scaffold strands."""
    if not excluded_strand_ids:
        return _scaffold_coverage(design)

    raw: dict[str, list[tuple[int, int]]] = {}
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or s.id in excluded_strand_ids:
            continue
        for dom in s.domains:
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            raw.setdefault(dom.helix_id, []).append((lo, hi))

    merged: dict[str, list[dict]] = {}
    for hid, ivs in raw.items():
        srt = sorted(ivs)
        if not srt:
            continue
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
    advanced_bridge_xovers: int = 0


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
    protected_scaffold_ids = _forced_scaffold_strand_ids(design)
    if protected_scaffold_ids:
        result.warnings.append(
            f"Preserved {len(protected_scaffold_ids)} scaffold strand(s) with "
            "manual forced ligation anchor(s); routing remaining scaffold regions."
        )

    coverage = _scaffold_coverage_excluding(design, protected_scaffold_ids)
    if not coverage:
        result.warnings.append("No routable scaffold strands found.")
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
    coverage = _scaffold_coverage_excluding(current, protected_scaffold_ids)  # rebuild after seam splits

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
    coverage = _scaffold_coverage_excluding(current, protected_scaffold_ids)

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


def _strand_nt(strand) -> int:
    return sum(abs(dom.end_bp - dom.start_bp) + 1 for dom in strand.domains)


def _can_extend_three_prime(dom: Domain, bp: int) -> bool:
    return bp >= dom.end_bp if dom.direction == Direction.FORWARD else bp <= dom.end_bp


def _can_extend_five_prime(dom: Domain, bp: int) -> bool:
    return bp <= dom.start_bp if dom.direction == Direction.FORWARD else bp >= dom.start_bp


def _terminal_extension_cost(dom: Domain, bp: int, end: str) -> int:
    ref = dom.end_bp if end == "three" else dom.start_bp
    return abs(bp - ref)


def _advanced_bridge_edge(
    design: Design,
    helix_by_id: dict,
    strand_from,
    strand_to,
    search_bp: int = 80,
) -> dict | None:
    """Find the cheapest legal 3′→5′ scaffold bridge between two strand blocks."""
    if not strand_from.domains or not strand_to.domains:
        return None
    src = strand_from.domains[-1]
    dst = strand_to.domains[0]
    h_src = helix_by_id.get(src.helix_id)
    h_dst = helix_by_id.get(dst.helix_id)
    if h_src is None or h_dst is None or h_src.grid_pos is None or h_dst.grid_pos is None:
        return None

    lo = min(src.end_bp, dst.start_bp) - search_bp
    hi = max(src.end_bp, dst.start_bp) + search_bp
    best: dict | None = None
    for bp in range(lo, hi + 1):
        if not _can_extend_three_prime(src, bp):
            continue
        if not _can_extend_five_prime(dst, bp):
            continue
        if _scaf_nb(design, h_src.grid_pos[0], h_src.grid_pos[1], bp) != tuple(h_dst.grid_pos):
            continue
        cost = (
            _terminal_extension_cost(src, bp, "three")
            + _terminal_extension_cost(dst, bp, "five")
        )
        candidate = {
            "from_id": strand_from.id,
            "to_id": strand_to.id,
            "bp": bp,
            "cost": cost,
        }
        if best is None or (cost, bp) < (best["cost"], best["bp"]):
            best = candidate
    return best


def _advanced_bridge_graph(design: Design) -> dict[str, list[dict]]:
    helix_by_id = {h.id: h for h in design.helices}
    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    graph: dict[str, list[dict]] = {s.id: [] for s in scaffolds}
    for strand_from in scaffolds:
        for strand_to in scaffolds:
            if strand_from.id == strand_to.id:
                continue
            edge = _advanced_bridge_edge(design, helix_by_id, strand_from, strand_to)
            if edge is not None:
                graph[strand_from.id].append(edge)
    for edges in graph.values():
        edges.sort(key=lambda e: (e["cost"], e["bp"], e["to_id"]))
    return graph


def _advanced_hamiltonian_path(design: Design, graph: dict[str, list[dict]]) -> list[str] | None:
    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    strand_by_id = {s.id: s for s in scaffolds}
    n = len(scaffolds)
    if n <= 1:
        return [s.id for s in scaffolds]

    incoming: dict[str, int] = {s.id: 0 for s in scaffolds}
    for edges in graph.values():
        for edge in edges:
            incoming[edge["to_id"]] += 1

    starts = sorted(
        (s.id for s in scaffolds),
        key=lambda sid: (
            incoming[sid],
            len(graph.get(sid, [])),
            -_strand_nt(strand_by_id[sid]),
            sid,
        ),
    )

    def dfs(path: list[str], used: set[str]) -> list[str] | None:
        if len(path) == n:
            return path
        current = path[-1]

        def edge_key(edge: dict) -> tuple[int, int, int, str]:
            next_id = edge["to_id"]
            onward = sum(1 for e in graph.get(next_id, []) if e["to_id"] not in used)
            return (onward, edge["cost"], -_strand_nt(strand_by_id[next_id]), next_id)

        for edge in sorted(graph.get(current, []), key=edge_key):
            next_id = edge["to_id"]
            if next_id in used:
                continue
            found = dfs(path + [next_id], used | {next_id})
            if found is not None:
                return found
        return None

    for start in starts:
        found = dfs([start], {start})
        if found is not None:
            return found
    return None


def _find_scaffold_strand(design: Design, strand_id: str):
    for strand in design.strands:
        if strand.id == strand_id and strand.strand_type == StrandType.SCAFFOLD:
            return strand
    return None


def _extend_terminal_domain(
    design: Design,
    helix_by_id: dict,
    strand_id: str,
    end: str,
    bp: int,
) -> Design:
    strand = _find_scaffold_strand(design, strand_id)
    if strand is None or not strand.domains:
        return design
    dom_index = 0 if end == "five" else len(strand.domains) - 1
    dom = strand.domains[dom_index]

    helix = helix_by_id.get(dom.helix_id)
    if helix is not None:
        hi = helix.bp_start + helix.length_bp - 1
        if bp < helix.bp_start:
            design = _extend_helix_lo(design, helix_by_id, dom.helix_id, bp)
        elif bp > hi:
            design = _extend_helix_hi(design, helix_by_id, dom.helix_id, bp)

    strand = _find_scaffold_strand(design, strand_id)
    if strand is None or not strand.domains:
        return design
    dom = strand.domains[dom_index]
    if end == "five":
        if not _can_extend_five_prime(dom, bp):
            return design
        new_dom = dom.model_copy(update={"start_bp": bp})
    else:
        if not _can_extend_three_prime(dom, bp):
            return design
        new_dom = dom.model_copy(update={"end_bp": bp})

    new_domains = list(strand.domains)
    new_domains[dom_index] = new_dom
    new_strand = strand.model_copy(update={"domains": new_domains, "sequence": None})
    return design.copy_with(
        strands=[new_strand if s.id == strand_id else s for s in design.strands]
    )


def _advanced_connect_scaffold_blocks(
    design: Design,
    path: list[str],
    result: SeamedResult,
) -> Design:
    current = design
    helix_by_id = {h.id: h for h in current.helices}
    if len(path) <= 1:
        return current

    head_id = path[0]
    for next_id in path[1:]:
        head = _find_scaffold_strand(current, head_id)
        nxt = _find_scaffold_strand(current, next_id)
        if head is None or nxt is None:
            result.warnings.append(
                f"[AdvancedSeamed] Missing scaffold block while connecting {head_id}→{next_id}."
            )
            continue
        edge = _advanced_bridge_edge(current, helix_by_id, head, nxt)
        if edge is None:
            result.warnings.append(
                f"[AdvancedSeamed] No legal bridge found for {head.id}→{nxt.id}; routing incomplete."
            )
            continue

        bp = edge["bp"]
        current = _extend_terminal_domain(current, helix_by_id, head.id, "three", bp)
        current = _extend_terminal_domain(current, helix_by_id, nxt.id, "five", bp)
        head = _find_scaffold_strand(current, head_id)
        nxt = _find_scaffold_strand(current, next_id)
        if head is None or nxt is None:
            continue
        src = head.domains[-1]
        dst = nxt.domains[0]
        ha = HalfCrossover(helix_id=src.helix_id, index=bp, strand=src.direction)
        hb = HalfCrossover(helix_id=dst.helix_id, index=bp, strand=dst.direction)
        current, xo = _place_xover(
            current,
            ha,
            hb,
            bp,
            bp,
            "auto_scaffold_advanced_seamed:bridge",
            result.warnings,
        )
        if xo is not None:
            result.advanced_bridge_xovers += 1
        else:
            result.warnings.append(
                f"[AdvancedSeamed] Bridge validation failed for {head.id}→{nxt.id} at bp={bp}."
            )
    return current


def _advanced_scaffold_strands(design: Design) -> list:
    return [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]


def _advanced_seam_candidates(
    design: Design,
    reference_coverage: dict[str, list[dict]],
) -> list[dict]:
    """Return true Holliday-junction seam candidates near original domain middles."""
    candidates: list[dict] = []
    helices = [
        h for h in design.helices
        if h.id in reference_coverage and h.grid_pos is not None
    ]
    for i, h_a in enumerate(helices):
        row_a, col_a = h_a.grid_pos
        fwd = _is_forward(row_a, col_a)
        strand_a = Direction.FORWARD if fwd else Direction.REVERSE
        strand_b = Direction.REVERSE if fwd else Direction.FORWARD
        for h_b in helices[i + 1:]:
            if h_b.grid_pos is None:
                continue
            if not any(
                _scaf_nb(design, row_a, col_a, bp) == tuple(h_b.grid_pos)
                for iv in _intersect(
                    reference_coverage.get(h_a.id, []),
                    reference_coverage.get(h_b.id, []),
                )
                for bp in range(iv["lo"], iv["hi"] + 1)
            ):
                continue
            for iv in _intersect(
                reference_coverage.get(h_a.id, []),
                reference_coverage.get(h_b.id, []),
            ):
                lo, hi = iv["lo"], iv["hi"]
                mid = (lo + hi) / 2
                valid_bps = [
                    bp for bp in range(lo, hi + 1)
                    if _scaf_nb(design, row_a, col_a, bp) == tuple(h_b.grid_pos)
                ]
                for bp_a, bp_b in zip(valid_bps, valid_bps[1:]):
                    if bp_b != bp_a + 1:
                        continue
                    candidates.append({
                        "hA_id": h_a.id,
                        "hB_id": h_b.id,
                        "bp_a": bp_a,
                        "bp_b": bp_b,
                        "strand_a": strand_a,
                        "strand_b": strand_b,
                        "mid_distance": abs(((bp_a + bp_b) / 2) - mid),
                        "interval_len": hi - lo + 1,
                    })
    candidates.sort(
        key=lambda c: (
            c["mid_distance"],
            -c["interval_len"],
            c["bp_a"],
            c["hA_id"],
            c["hB_id"],
        )
    )
    return candidates


def _advanced_place_seam_pair(
    design: Design,
    candidate: dict,
    warnings: list[str],
) -> tuple[Design, int]:
    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow_right = _HC_SCAF_BOW_RIGHT if is_hc else _SQ_SCAF_BOW_RIGHT
    current = design
    placed = 0
    for bp in (candidate["bp_a"], candidate["bp_b"]):
        ha = HalfCrossover(
            helix_id=candidate["hA_id"],
            index=bp,
            strand=candidate["strand_a"],
        )
        hb = HalfCrossover(
            helix_id=candidate["hB_id"],
            index=bp,
            strand=candidate["strand_b"],
        )
        nick_a = _nick_bp(bp, candidate["strand_a"], period, bow_right)
        nick_b = _nick_bp(bp, candidate["strand_b"], period, bow_right)
        current, xo = _place_xover(
            current,
            ha,
            hb,
            nick_a,
            nick_b,
            "auto_scaffold_advanced_seamed:seam",
            warnings,
        )
        if xo is not None:
            placed += 1
    return current, placed


def _advanced_rejoin_scaffold_pieces(
    design: Design,
    result: SeamedResult,
    *,
    search_bp: int = 300,
) -> Design | None:
    scaffolds = _advanced_scaffold_strands(design)
    if len(scaffolds) != 2:
        return design if len(scaffolds) == 1 else None

    helix_by_id = {h.id: h for h in design.helices}
    edges: list[tuple[int, str, str, dict]] = []
    for a in scaffolds:
        for b in scaffolds:
            if a.id == b.id:
                continue
            edge = _advanced_bridge_edge(design, helix_by_id, a, b, search_bp=search_bp)
            if edge is not None:
                edges.append((edge["cost"], a.id, b.id, edge))
    if not edges:
        return None

    _, from_id, to_id, edge = min(edges, key=lambda e: (e[0], e[1], e[2], e[3]["bp"]))
    bp = edge["bp"]
    current = _extend_terminal_domain(design, helix_by_id, from_id, "three", bp)
    current = _extend_terminal_domain(current, helix_by_id, to_id, "five", bp)
    strand_from = _find_scaffold_strand(current, from_id)
    strand_to = _find_scaffold_strand(current, to_id)
    if strand_from is None or strand_to is None:
        return None

    src = strand_from.domains[-1]
    dst = strand_to.domains[0]
    ha = HalfCrossover(helix_id=src.helix_id, index=bp, strand=src.direction)
    hb = HalfCrossover(helix_id=dst.helix_id, index=bp, strand=dst.direction)
    current, xo = _place_xover(
        current,
        ha,
        hb,
        bp,
        bp,
        "auto_scaffold_advanced_seamed:bridge",
        result.warnings,
    )
    if xo is None:
        return None
    result.advanced_bridge_xovers += 1
    return current


def _advanced_add_holliday_seam(
    design: Design,
    reference_coverage: dict[str, list[dict]],
    result: SeamedResult,
) -> Design:
    if len(_advanced_scaffold_strands(design)) != 1:
        result.warnings.append(
            "[AdvancedSeamed] Skipped seam placement because the scaffold route is incomplete."
        )
        return design

    for candidate in _advanced_seam_candidates(design, reference_coverage):
        local_warnings: list[str] = []
        with_seam, placed = _advanced_place_seam_pair(design, candidate, local_warnings)
        if placed != 2:
            continue
        trial_result = SeamedResult()
        rejoined = _advanced_rejoin_scaffold_pieces(with_seam, trial_result)
        if rejoined is None or len(_advanced_scaffold_strands(rejoined)) != 1:
            continue
        result.advanced_bridge_xovers += trial_result.advanced_bridge_xovers
        result.seam_xovers += placed
        return rejoined

    result.warnings.append(
        "[AdvancedSeamed] Could not place a complete Holliday-junction seam pair "
        "and rejoin the scaffold route."
    )
    return design


def _auto_scaffold_process_id(process_id: str | None) -> bool:
    return bool(process_id and process_id.startswith("auto_scaffold_"))


def _clear_auto_scaffold_route_for_seamed(design: Design, result: SeamedResult) -> Design:
    """Remove prior auto scaffold routing so advanced seamed can reroute cleanly.

    Designs with forced ligations are left intact because splitting their scaffold
    strands can destroy the manual fixed-edge topology the user requested.
    """
    auto_xovers = [xo for xo in design.crossovers if _auto_scaffold_process_id(xo.process_id)]
    if not auto_xovers:
        return design
    if design.forced_ligations:
        result.warnings.append(
            "Existing auto scaffold crossovers were preserved because manual forced "
            "scaffold ligations are present; clear prior auto-routing before rerouting "
            "if a full rebuild is intended."
        )
        return design

    new_strands = []
    split_count = 0
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            new_strands.append(strand)
            continue
        if len(strand.domains) <= 1:
            new_strands.append(strand)
            continue
        for i, dom in enumerate(strand.domains):
            new_strands.append(
                strand.model_copy(
                    update={
                        "id": f"{strand.id}_advanced_seed_{i}",
                        "domains": [dom],
                        "sequence": None,
                    }
                )
            )
            split_count += 1

    kept_xovers = [
        xo for xo in design.crossovers
        if not _auto_scaffold_process_id(xo.process_id)
    ]
    result.warnings.append(
        f"Cleared {len(auto_xovers)} existing auto scaffold crossover(s) and "
        f"split routed scaffold strands into {split_count} domain seed(s) before "
        "advanced seam rerouting."
    )
    return design.copy_with(strands=new_strands, crossovers=kept_xovers)


def auto_scaffold_advanced_seamed(design: Design) -> tuple[Design, SeamedResult]:
    """Experimental seamed router with incomplete-route warnings.

    This branch prioritizes true seamed topology: central Holliday-junction
    seam pairs plus mirrored end crossovers. Manual scaffold crossovers are
    treated as fixed constraints; when those constraints prevent one-strand
    consolidation the best seamed route is returned with a warning.
    """
    result = SeamedResult()
    seed = _clear_auto_scaffold_route_for_seamed(design, result)
    current, seamed_result = auto_scaffold_seamed(seed)
    result.warnings.extend(seamed_result.warnings)
    result.seam_xovers += seamed_result.seam_xovers
    result.near_end_xovers += seamed_result.near_end_xovers
    result.far_end_xovers += seamed_result.far_end_xovers

    scaffolds = [s for s in current.strands if s.strand_type == StrandType.SCAFFOLD]
    if len(scaffolds) != 1:
        result.warnings.append(
            "Advanced seam routing incomplete: fixed/manual route constraints or "
            f"missing legal scaffold crossover sites left {len(scaffolds)} scaffold "
            "strand(s). The best valid seamed route was applied."
        )
    return current, result
