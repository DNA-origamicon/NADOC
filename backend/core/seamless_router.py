"""
Seamless scaffold router — zig-zag end crossovers only, no seam HJ.

Each helix in the Hamiltonian path is visited ONCE.  Adjacent pairs receive a
single end crossover at the hi face (if hA is FORWARD) or the lo face (if hA
is REVERSE).  Consecutive HC helices alternate parity, so faces alternate
naturally: hi / lo / hi / lo …

For multi-section designs (dumbbell, teeth): helices are grouped by coverage
signature; within each group the zig-zag is applied independently.  Between
groups a Holliday-junction bridge (identical to the seamed Phase 1 algorithm)
connects the last helix of one group to the first helix of the next.

Three-Layer Law: only topology is modified.  Helix axis_start / axis_end are
extended solely to create physical room for the added nucleotides.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
from backend.core.models import (
    Design,
    Direction,
    HalfCrossover,
    LatticeType,
)
from backend.core.seamed_router import (
    _HC_SCAF_BOW_RIGHT,
    _SQ_SCAF_BOW_RIGHT,
    _build_adj,
    _extend_helix_hi,
    _extend_helix_lo,
    _extend_scaf_domain_hi,
    _extend_scaf_domain_lo,
    _hamiltonian_path,
    _intersect,
    _is_forward,
    _nick_bp,
    _place_xover,
    _scaffold_coverage,
    _scaf_nb,
)


# ── Local helpers ─────────────────────────────────────────────────────────────

def _ham_path_ending(
    ids: list[str],
    adj: dict[str, set[str]],
    target_end: str,
    start_from: str | None = None,
) -> list[str] | None:
    """Hamiltonian path that deterministically ends at target_end.

    Uses descending-degree neighbor ordering so that low-degree vertices
    (like a degree-2 bridge helix) are explored last and naturally end up
    at path[-1].  A secondary lexicographic sort makes the result reproducible
    across Python runs regardless of set-iteration order.
    """
    vis: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> bool:
        vis.add(node); path.append(node)
        if len(path) == len(ids):
            return True
        for nb in sorted(adj[node] - vis, key=lambda n: (-len(adj[n]), n)):
            if dfs(nb):
                return True
        vis.discard(node); path.pop()
        return False

    starters = (
        [start_from] + [n for n in sorted(ids, key=lambda n: (len(adj[n]), n))
                        if n != start_from]
        if start_from is not None
        else sorted(ids, key=lambda n: (len(adj[n]), n))
    )
    for s in starters:
        vis.clear(); path.clear()
        if dfs(s) and path[-1] == target_end:
            return path
    return None


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class SeamlessResult:
    warnings: list[str] = field(default_factory=list)
    end_xovers: int = 0      # zig-zag crossovers placed within sections
    bridge_xovers: int = 0   # HJ bridge crossovers placed between sections


# ── Main entry point ──────────────────────────────────────────────────────────

def auto_scaffold_seamless(design: Design) -> tuple[Design, SeamlessResult]:
    """Run the seamless scaffold pipeline.

    Phase 1 (Bridge HJs): place Holliday junctions between coverage-signature
      groups for multi-section designs (dumbbell, teeth).
    Phase 2 (Zig-Zag): place one end crossover per within-group adjacent pair,
      at the hi face for FORWARD helices and the lo face for REVERSE helices.

    Returns (updated_design, result).
    """
    result = SeamlessResult()
    is_hc = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if is_hc else SQ_CROSSOVER_PERIOD
    bow_right = _HC_SCAF_BOW_RIGHT if is_hc else _SQ_SCAF_BOW_RIGHT

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
            visited.add(nid)
            comp.append(nid)
            stack.extend(adj[nid] - visited)
        components.append(comp)

    # ── Build bridge and zig pairs from Hamiltonian paths ────────────────────
    bridge_pairs: list[tuple[str, str]] = []
    zig_pairs:    list[tuple[str, str]] = []

    for comp in components:
        if len(comp) < 2:
            result.warnings.append(
                f"Component of {len(comp)} helix skipped (minimum 2 required)."
            )
            continue

        def cov_sig(hid: str) -> str:
            # Single-interval helices: sub-group by bucketed total length so that
            # dumbbell arm helices (short) separate from core helices (long).
            # Multi-interval helices: group purely by count — teeth helices have
            # slightly different exact lengths due to geometry offsets, so any
            # length-based bucket would split them incorrectly.
            covs = coverage[hid]
            n = len(covs)
            if n == 1:
                total = covs[0]["hi"] - covs[0]["lo"] + 1
                return f"1:{round(total / period) * period}"
            return str(n)

        sig_map: dict[str, list[str]] = {}
        for hid in comp:
            sig_map.setdefault(cov_sig(hid), []).append(hid)
        groups = list(sig_map.values())

        if len(groups) == 1:
            path = _hamiltonian_path(comp, adj) or comp
            if len(path) < 2:
                continue
            for i in range(len(path) - 1):
                zig_pairs.append((path[i], path[i + 1]))

        else:
            # Multi-section: sort groups by total bp ascending (arms first),
            # chain with bridge, track group-boundary indices.
            def grp_bp(g: list[str]) -> int:
                return sum(iv["hi"] - iv["lo"] + 1 for iv in coverage[g[0]])

            groups.sort(key=grp_bp)
            local_adjs = [
                {gid: adj[gid] & set(grp) for gid in grp}
                for grp in groups
            ]
            # Build group-0 path ending at the bridge helix so that:
            # (a) path[-1] is a spine-adjacent helix (FORWARD preferred) — the
            #     bridge pair connects it to the next section.
            # (b) path[0] is adjacent to path[-1] — enabling a closing-zig
            #     crossover that is safe because the bridge HJ breaks circularity.
            # Uses _ham_path_ending (descending-degree + lexicographic ordering)
            # so that the low-degree bridge candidate is deterministically last.
            nxt_set_0 = set(groups[1])
            spine_adj_0 = [
                hid for hid in groups[0]
                if any(nb in nxt_set_0 for nb in adj[hid])
            ]
            spine_adj_0.sort(key=lambda h: (not _is_forward(*helix_by_id[h].grid_pos)))
            path = None
            for cand in spine_adj_0:
                for start in sorted(local_adjs[0].get(cand, set()),
                                    key=lambda n: (-len(local_adjs[0][n]), n)):
                    raw0 = _ham_path_ending(groups[0], local_adjs[0], cand, start)
                    if raw0 and raw0[-1] == cand:
                        path = raw0
                        break
                if path is not None:
                    break
            if path is None:
                path = _hamiltonian_path(groups[0], local_adjs[0]) or list(groups[0])
            group_boundaries: list[int] = []

            for gi in range(1, len(groups)):
                nxt_ids = groups[gi]
                nxt_set = set(nxt_ids)
                if (not any(nb in nxt_set for nb in adj[path[-1]])
                        and any(nb in nxt_set for nb in adj[path[0]])):
                    path.reverse()
                bridge = next(
                    (nb for nb in adj[path[-1]] if nb in nxt_set), None
                )
                boundary_idx = len(path) - 1  # index of last element before extending
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
                    path = path + (
                        _hamiltonian_path(nxt_ids, local_adjs[gi]) or nxt_ids
                    )
                group_boundaries.append(boundary_idx)

            boundary_set = set(group_boundaries)
            for i in range(len(path) - 1):
                if i in boundary_set:
                    bridge_pairs.append((path[i], path[i + 1]))
                else:
                    zig_pairs.append((path[i], path[i + 1]))

            # Closing zig: for every group that has an outgoing bridge (all
            # except the last), the bridge HJ breaks circularity, so we can
            # safely connect the group's first and last helices if they are
            # scaffold-adjacent.  Always use the FORWARD (even-parity) helix
            # as hA so the crossover sits at the hi face (outward end).
            group_starts = [0] + [b + 1 for b in group_boundaries]
            for gi in range(len(groups) - 1):
                first_hid = path[group_starts[gi]]
                last_hid  = path[group_boundaries[gi]]
                if first_hid in adj.get(last_hid, set()):
                    h_fwd = (first_hid
                             if _is_forward(*helix_by_id[first_hid].grid_pos)
                             else last_hid)
                    h_rev = last_hid if h_fwd == first_hid else first_hid
                    zig_pairs.append((h_fwd, h_rev))

    current = design

    # =========================================================================
    # Phase 1 — Bridge Holliday Junctions (multi-section designs only)
    # Identical algorithm to seamed Phase 1; operates on bridge_pairs only.
    # =========================================================================
    for hA_id, hB_id in bridge_pairs:
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

            bp1 = bp2 = None
            best = float("inf")
            for j in range(len(valid_bps) - 1):
                if valid_bps[j + 1] == valid_bps[j] + 1:
                    d = abs((valid_bps[j] + valid_bps[j + 1]) / 2 - mid)
                    if d < best:
                        best = d
                        bp1, bp2 = valid_bps[j], valid_bps[j + 1]
            if bp1 is None:
                continue

            for xover_bp in (bp1, bp2):
                ha = HalfCrossover(helix_id=hA_id, index=xover_bp, strand=strand_a)
                hb = HalfCrossover(helix_id=hB_id, index=xover_bp, strand=strand_b)
                nick_a = _nick_bp(xover_bp, strand_a, period, bow_right)
                nick_b = _nick_bp(xover_bp, strand_b, period, bow_right)
                current, xo = _place_xover(
                    current, ha, hb, nick_a, nick_b,
                    "auto_scaffold_seamless:bridge", result.warnings,
                )
                if xo:
                    result.bridge_xovers += 1

    # =========================================================================
    # Phase 2 — Zig-Zag End Crossovers
    # One crossover per zig pair: hi face for FORWARD hA, lo face for REVERSE hA.
    # =========================================================================
    coverage = _scaffold_coverage(current)  # rebuild after Phase 1

    zig_specs: list[dict] = []
    for hA_id, hB_id in zig_pairs:
        hA = helix_by_id.get(hA_id)
        hB = helix_by_id.get(hB_id)
        if not hA or not hB or hA.grid_pos is None or hB.grid_pos is None:
            continue
        rowA, colA = hA.grid_pos
        fwd = _is_forward(rowA, colA)
        strand_a = Direction.FORWARD if fwd else Direction.REVERSE
        strand_b = Direction.REVERSE if fwd else Direction.FORWARD
        face = "hi" if fwd else "lo"
        covA = coverage.get(hA_id, [])
        covB = coverage.get(hB_id, [])

        for iv in _intersect(covA, covB):
            if face == "hi":
                face_val = iv["hi"]
                if not (any(c["lo"] <= face_val <= c["hi"] for c in covA)
                        and any(c["lo"] <= face_val <= c["hi"] for c in covB)):
                    continue
                xover_bp = next(
                    (bp for bp in range(face_val + 3, face_val + period + 1)
                     if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)),
                    None,
                )
            else:
                face_val = iv["lo"]
                if not (any(c["lo"] <= face_val <= c["hi"] for c in covA)
                        and any(c["lo"] <= face_val <= c["hi"] for c in covB)):
                    continue
                xover_bp = next(
                    (bp for bp in range(face_val - 3, face_val - period - 1, -1)
                     if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)),
                    None,
                )

            if xover_bp is None:
                result.warnings.append(
                    f"[Seamless] No xover found for {hA_id}↔{hB_id} at {face}={face_val}"
                )
                continue
            zig_specs.append({
                "hA_id": hA_id, "hB_id": hB_id,
                "face": face, "face_val": face_val,
                "xover_bp": xover_bp,
                "strand_a": strand_a, "strand_b": strand_b,
                "nick_a": _nick_bp(xover_bp, strand_a, period, bow_right),
                "nick_b": _nick_bp(xover_bp, strand_b, period, bow_right),
            })

    # Extend helix geometry (gather per-helix extremes first).
    helix_new_lo: dict[str, int] = {}
    helix_new_hi: dict[str, int] = {}
    for sp in zig_specs:
        if sp["face"] == "lo":
            for hid in (sp["hA_id"], sp["hB_id"]):
                v = sp["xover_bp"]
                if hid not in helix_new_lo or v < helix_new_lo[hid]:
                    helix_new_lo[hid] = v
        else:
            for hid in (sp["hA_id"], sp["hB_id"]):
                v = sp["xover_bp"]
                if hid not in helix_new_hi or v > helix_new_hi[hid]:
                    helix_new_hi[hid] = v

    for hid, new_lo in helix_new_lo.items():
        current = _extend_helix_lo(current, helix_by_id, hid, new_lo)
    for hid, new_hi in helix_new_hi.items():
        current = _extend_helix_hi(current, helix_by_id, hid, new_hi)

    # Extend scaffold domains, then place crossovers.
    for sp in zig_specs:
        if sp["face"] == "lo":
            for hid in (sp["hA_id"], sp["hB_id"]):
                current = _extend_scaf_domain_lo(
                    current, hid, sp["face_val"], sp["xover_bp"]
                )
        else:
            for hid in (sp["hA_id"], sp["hB_id"]):
                current = _extend_scaf_domain_hi(
                    current, hid, sp["face_val"], sp["xover_bp"]
                )
        ha = HalfCrossover(
            helix_id=sp["hA_id"], index=sp["xover_bp"], strand=sp["strand_a"]
        )
        hb = HalfCrossover(
            helix_id=sp["hB_id"], index=sp["xover_bp"], strand=sp["strand_b"]
        )
        current, xo = _place_xover(
            current, ha, hb, sp["nick_a"], sp["nick_b"],
            "auto_scaffold_seamless:zig", result.warnings,
        )
        if xo:
            result.end_xovers += 1

    return current, result
