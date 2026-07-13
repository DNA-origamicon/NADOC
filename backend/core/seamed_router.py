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
    HalfCrossover,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)

# Bow-right offset sets for scaffold crossovers (bp % period ∈ set → bow-right).
_HC_SCAF_BOW_RIGHT: frozenset[int] = frozenset({2, 5, 9, 12, 16, 19})
_SQ_SCAF_BOW_RIGHT: frozenset[int] = frozenset({0, 3, 5, 8, 11, 13, 16, 19, 21, 24, 27, 29})


# ── Low-level helpers ─────────────────────────────────────────────────────────

def _active_scaffolds(design: Design) -> list[Strand]:
    """Non-reference scaffold strands. Reference geometry is excluded from routing."""
    return [s for s in design.scaffolds() if not s.is_reference]


def _scaffold_coverage(design: Design) -> dict[str, list[dict]]:
    """Build per-helix scaffold coverage: helix_id → sorted merged [{lo, hi}]."""
    raw: dict[str, list[tuple[int, int]]] = {}
    for s in design.strands:
        if s.strand_type != StrandType.SCAFFOLD or s.is_reference:
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
            if strand.strand_type != StrandType.SCAFFOLD or strand.is_reference:
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
        if (s.strand_type != StrandType.SCAFFOLD or s.is_reference
                or s.id in excluded_strand_ids):
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


# Visit-count ceiling for Hamiltonian-path DFS.  Pruning makes graphs that admit
# a path terminate far below this; the cap guarantees we never hang on graphs
# that admit NO Hamiltonian path (e.g. a closed-tube cross-section), where the
# naive search tree is exponential.  At ~25 us/visit this caps a hopeless search
# at roughly 25 s rather than forever.
_HAM_PATH_BUDGET = 1_000_000


def _ham_path_search(
    ids: list[str],
    adj: dict[str, set[str]],
    neighbor_key,
    starters: list[str],
    budget: list[int] | None = None,
) -> list[str] | None:
    """Budgeted, connectivity/degree-pruned Hamiltonian-path DFS.

    `neighbor_key(n)` orders the neighbours explored at each step (callers pick
    ascending- or descending-degree heuristics).  `starters` is the ordered list
    of start nodes to try; `budget` (a single-element list) is shared across
    calls so a multi-start search has one combined ceiling.

    Returns the first complete path found, or ``None`` if no Hamiltonian path
    exists OR the visit budget is exhausted — a graceful give-up instead of an
    unbounded recursion.  The pruning is *admissible* (it only cuts branches that
    provably cannot complete), so for solvable graphs the first path returned is
    identical to the un-pruned search; it just skips the dead sub-trees.
    """
    id_set = set(ids)
    n = len(id_set)
    vis: set[str] = set()
    path: list[str] = []
    if budget is None:
        budget = [_HAM_PATH_BUDGET]

    def _can_complete(node: str) -> bool:
        """True iff the unvisited remainder could still extend `node` to a path."""
        rem = id_set - vis
        if not rem:
            return True
        frontier = [nb for nb in adj[node] if nb in rem]
        if not frontier:
            return False  # current end is boxed in
        # remaining subgraph must be connected AND reachable from the current end
        seen = {frontier[0]}
        stack = [frontier[0]]
        while stack:
            x = stack.pop()
            for nb in adj[x]:
                if nb in rem and nb not in seen:
                    seen.add(nb); stack.append(nb)
        if seen != rem:
            return False
        if len(rem) == 1:
            return True  # last node just has to attach to the current end (it does)
        # a Hamiltonian path has at most 2 endpoints, so at most 2 remaining
        # nodes may have a single unvisited neighbour; an isolated one is fatal
        ends = 0
        for x in rem:
            deg = sum(1 for nb in adj[x] if nb in rem)
            if deg == 0:
                return False
            if deg == 1:
                ends += 1
                if ends > 2:
                    return False
        return True

    def dfs(node: str) -> bool:
        budget[0] -= 1
        if budget[0] <= 0:
            return False
        vis.add(node); path.append(node)
        if len(path) == n:
            return True
        if _can_complete(node):
            for nb in sorted(adj[node] - vis, key=neighbor_key):
                if budget[0] <= 0:
                    break
                if dfs(nb):
                    return True
        vis.discard(node); path.pop()
        return False

    for s in starters:
        if budget[0] <= 0:
            break
        vis.clear(); path.clear()
        if dfs(s):
            return list(path)
    return None


def _hamiltonian_path(
    ids: list[str],
    adj: dict[str, set[str]],
    start_from: str | None = None,
) -> list[str] | None:
    """DFS Hamiltonian path with degree-ascending neighbor ordering.

    Budgeted + pruned (see `_ham_path_search`): returns ``None`` instead of
    hanging when the graph admits no Hamiltonian path.
    """
    # Degree-ascending order with a lexicographic `n` tiebreaker so that
    # equal-degree nodes have a stable order independent of set-iteration
    # (hash-seed) order — otherwise the Hamiltonian path, and therefore the
    # emitted scaffold-strand count, varies run-to-run.  Mirrors the
    # `(len(adj[n]), n)` key in seamless_router._ham_path_ending.  Must be
    # applied to BOTH the starter sort and the neighbor key.  TOPOLOGY-SENSITIVE.
    key = lambda n: (len(adj[n]), n)  # noqa: E731
    ordered = sorted(ids, key=key)
    starters = ([start_from] + [n for n in ordered if n != start_from]
                if start_from is not None else ordered)
    return _ham_path_search(ids, adj, key, starters)


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
        if strand.strand_type != StrandType.SCAFFOLD or strand.is_reference:
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
        if strand.strand_type != StrandType.SCAFFOLD or strand.is_reference:
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

def _auto_scaffold_seamed_impl(
    design: Design, *, matched_ends: bool = False, bounded_ends: bool = False
) -> tuple[Design, SeamedResult]:
    """Shared seamed pipeline body (Seam → Near Ends → Far Ends).

    All phases share one atomic Design update; no undo checkpointing here
    (the caller in crud.py handles snapshot/set_design_silent).

    When ``matched_ends`` is False this is the classic seamed router: the far
    face skips the lowest-helix pair to park the scaffold's open terminus, and
    each far crossover is searched independently of the near face.

    When ``matched_ends`` is True the far face is made an exact translate of the
    near face for blunt-end end-to-end polymerization: every near pair is also
    capped at the far face at ``near_xover_bp + P`` (P a whole multiple of the
    lattice crossover period, so the translate stays lattice-valid and the two
    blunt faces sit in integer-turn helical register), and a single interior
    nick per component reopens the resulting circular scaffold into one linear
    strand with its 5'/3' buried mid-bundle.  See the "matched ends" plan.

    When ``bounded_ends`` is True (classic only — the section router routes its
    WINDOW sub-bundles with it) the near/far end-turn search starts AT the section
    face instead of ``lo-3``/``hi+3``: it takes the nearest valid crossover site
    at-or-past each face rather than the first one ``≥3`` bp out.  Valid sites for
    a specific helix pair recur one crossover-period apart, so the ``±3`` floor
    skips the face-aligned site and lands a full period out (+32 on SQ) — which
    for a segmented WINDOW pokes scaffold deep into the physical inter-tooth gaps.
    Starting at the face keeps the turn-around bounded to ≲ one helical turn (the
    reference hand-route's pattern: mostly +0, ≤10 where faces stay ragged), so
    adjacent teeth never overlap.  Default-off leaves uniform-prism + matched-ends
    routing byte-identical.

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

        if len(groups) == 1 or bounded_ends:
            # Bounded mode routes one WINDOW sub-bundle whose ragged faces give each
            # helix a distinct coverage signature; its grid adjacency is still full
            # (the helices overlap heavily), so route it as a single Hamiltonian
            # serpentine rather than splitting it by signature.
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

        # Each near pair turns at ONE crossover near the lo face.  In the default
        # (uniform / squared) routing the pair shares an exact lo face and the search
        # runs from lo-3 outward.  In bounded mode (section-router WINDOWs, ragged
        # faces) the two helices may co-terminate at DIFFERENT bp; pairing them at the
        # deeper face (min lo) and extending the shallower helix down to the turn keeps
        # each tooth's turn-around at its OWN face — the ≤ one-turn extension stays out
        # of the inter-tooth gaps instead of being dragged to a common squared face.
        if bounded_ends:
            # The near turn sits at the bundle's lo end, so pair each helix's
            # LOWEST section (the seam phase split each domain in two; only the
            # lower halves carry the near face).  One turn per pair, at the deeper
            # of the two ragged lo faces.
            turn_items = []
            if covA and covB:
                secA = min(covA, key=lambda s: s["lo"])
                secB = min(covB, key=lambda s: s["lo"])
                if secA["lo"] <= secB["hi"] and secB["lo"] <= secA["hi"]:
                    turn_items = [(secA["lo"], secB["lo"], min(secA["lo"], secB["lo"]))]
        else:
            turn_items = [
                (iv["lo"], iv["lo"], iv["lo"])
                for iv in _intersect(covA, covB)
                if any(c["lo"] == iv["lo"] for c in covA)
                and any(c["lo"] == iv["lo"] for c in covB)
            ]

        for face_a, face_b, face in turn_items:
            near_floor = face if bounded_ends else face - 3
            xover_bp = next(
                (bp for bp in range(near_floor, face - period - 1, -1)
                 if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)),
                None,
            )
            if xover_bp is None:
                result.warnings.append(
                    f"[NearEnds] No xover found for {hA_id}↔{hB_id} near lo={face}"
                )
                continue
            # Matched-ends: land every near turn on its BOW-RIGHT site so all three
            # honeycomb bond directions are bow-consistent.  Each bond's legal xover
            # sites come in adjacent bow pairs (bow-left at bp, bow-right at bp+1);
            # the descending search from face-3 can land on the bow-LEFT member when
            # the pair straddles the floor (the vertical/row-differing bond does this),
            # putting that copy's seam crossover on the wrong strand of the junction.
            # Snapping to the adjacent bow-right site (when legal) makes the far-end
            # translate + bow-right −1 normalisation treat every pair uniformly, so the
            # far face is a single clean period translate of the near face.
            if (
                matched_ends
                and (xover_bp % period) not in bow_right
                and ((xover_bp + 1) % period) in bow_right
                and _scaf_nb(current, rowA, colA, xover_bp + 1) == tuple(hB.grid_pos)
            ):
                xover_bp += 1
            near_specs.append({
                "hA_id": hA_id, "hB_id": hB_id,
                "face_a": face_a, "face_b": face_b,
                "new_lo": xover_bp, "xover_bp": xover_bp,
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
        current = _extend_scaf_domain_lo(current, sp["hA_id"], sp["face_a"], sp["new_lo"])
        current = _extend_scaf_domain_lo(current, sp["hB_id"], sp["face_b"], sp["new_lo"])
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

    # Derive far-end pairs from near-end crossovers just placed.  Capture each
    # pair's near xover bp position(s) (ascending) so matched-ends mode can
    # mirror them to the far face as exact translates.
    pair_seen: set[tuple[str, str]] = set()
    far_end_pairs: list[tuple[str, str]] = []
    near_xover_by_pair: dict[tuple[str, str], list[int]] = {}
    for xo in current.crossovers:
        if xo.process_id != "create_near_ends":
            continue
        key: tuple[str, str] = tuple(sorted([xo.half_a.helix_id, xo.half_b.helix_id]))  # type: ignore[assignment]
        near_xover_by_pair.setdefault(key, []).append(xo.half_a.index)
        if key not in pair_seen:
            pair_seen.add(key)
            far_end_pairs.append((xo.half_a.helix_id, xo.half_b.helix_id))
    for lst in near_xover_by_pair.values():
        lst.sort()

    # Classic mode: skip the pair with the lowest-indexed helix (parks the open
    # scaffold terminus there).  Matched mode caps every pair (no open face) and
    # reopens the resulting circle with one interior nick later.
    # Classic mode parks the open terminus by skipping the lowest-helix far pair.
    # Bounded mode (section-router WINDOWs) must cap EVERY far pair so the window
    # closes into a cycle for the 2-opt splice — like matched mode, but the cap
    # sits at the nearest valid site (bounded_ends) instead of a one-period translate.
    skip_id: str | None = None
    if not matched_ends and not bounded_ends:
        helix_array_idx = {h.id: i for i, h in enumerate(current.helices)}
        lowest = float("inf")
        for ha_id, hb_id in far_end_pairs:
            mi = min(helix_array_idx.get(ha_id, 0), helix_array_idx.get(hb_id, 0))
            if mi < lowest:
                lowest = mi
                skip_id = ha_id if helix_array_idx.get(ha_id, 0) <= helix_array_idx.get(hb_id, 0) else hb_id

    # Matched mode: one repeat period P = smallest whole multiple of the lattice
    # crossover period that spans the bundle, so far_xover = near_xover + P stays
    # lattice-valid (validity is bp % period) and the two blunt faces land in
    # integer-turn helical register.
    P = 0
    if matched_ends:
        all_near = [bp for lst in near_xover_by_pair.values() for bp in lst]
        all_hi = [iv["hi"] for ivs in coverage.values() for iv in ivs]
        if all_near and all_hi:
            min_near, max_hi = min(all_near), max(all_hi)
            P = math.ceil((max_hi - min_near + 1) / period) * period
        else:
            result.warnings.append(
                "[MatchedEnds] No near-end crossovers to mirror; far ends unmatched."
            )

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

        # Mirror of the near phase: each far pair turns at one crossover near the hi
        # face.  Bounded mode (ragged WINDOWs) pairs at the deeper face (max hi) and
        # extends the shorter helix UP to the turn, keeping the turn-around at each
        # tooth's own hi face rather than a common squared face.
        if bounded_ends:
            # Mirror of near: pair each helix's HIGHEST section (the upper halves
            # carry the hi face) for one far turn at the deeper of the two hi faces.
            far_items = []
            if covA and covB:
                secA = max(covA, key=lambda s: s["hi"])
                secB = max(covB, key=lambda s: s["hi"])
                if secA["lo"] <= secB["hi"] and secB["lo"] <= secA["hi"]:
                    far_items = [(secA["hi"], secB["hi"], max(secA["hi"], secB["hi"]))]
        else:
            far_items = [
                (iv["hi"], iv["hi"], iv["hi"])
                for iv in _intersect(covA, covB)
                if any(c["hi"] == iv["hi"] for c in covA)
                and any(c["hi"] == iv["hi"] for c in covB)
            ]
        near_list = near_xover_by_pair.get(tuple(sorted([ha_id, hb_id])), [])  # type: ignore[arg-type]
        if matched_ends and P and len(far_items) != len(near_list):
            result.warnings.append(
                f"[MatchedEnds] {ha_id}↔{hb_id}: {len(near_list)} near vs "
                f"{len(far_items)} far interval(s); ends may not match exactly."
            )

        for idx, (face_a, face_b, hi) in enumerate(far_items):
            xover_bp: int | None
            if matched_ends and P and idx < len(near_list):
                # Exact translate of the matching near crossover.
                xover_bp = near_list[idx] + P
                if _scaf_nb(current, rowA, colA, xover_bp) != tuple(hB.grid_pos):
                    # Translate unexpectedly invalid → fall back to a local search.
                    # Flag it: the far face is no longer an exact translate of the
                    # near face here, so ends are not cleanly matched (the seamed
                    # default reads this to fall back to classic routing).
                    result.warnings.append(
                        f"[MatchedEnds] {ha_id}↔{hb_id}: translate near+P="
                        f"{near_list[idx] + P} off-lattice; used local far search."
                    )
                    xover_bp = next(
                        (bp for bp in range(hi + 3, hi + period + 1)
                         if _scaf_nb(current, rowA, colA, bp) == tuple(hB.grid_pos)),
                        None,
                    )
                # Put every far crossover on the LEFT side of its junction: a
                # bow-right site is the right member of the bow, so step to its
                # left partner (bp-1); non-bow-right sites already sit on the
                # left.  This makes copy N's far crossover and copy N+1's near
                # crossover an adjacent (bp-1, bp) HJ pair at the polymer seam.
                if xover_bp is not None and (xover_bp % period) in bow_right:
                    xover_bp -= 1
            else:
                far_floor = hi if bounded_ends else hi + 3
                xover_bp = next(
                    (bp for bp in range(far_floor, hi + period + 1)
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
                "face_a": face_a, "face_b": face_b,
                "new_hi": xover_bp, "xover_bp": xover_bp,
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
        current = _extend_scaf_domain_hi(current, sp["hA_id"], sp["face_a"], sp["new_hi"])
        current = _extend_scaf_domain_hi(current, sp["hB_id"], sp["face_b"], sp["new_hi"])
        ha = HalfCrossover(helix_id=sp["hA_id"], index=sp["xover_bp"], strand=sp["strand_a"])
        hb = HalfCrossover(helix_id=sp["hB_id"], index=sp["xover_bp"], strand=sp["strand_b"])
        current, xo = _place_xover(
            current, ha, hb, sp["nick_a"], sp["nick_b"],
            "create_far_ends", result.warnings,
        )
        if xo:
            result.far_end_xovers += 1

    # End-of-router retry: parallel HJ siblings (the second crossover of a
    # bp/bp+1 pair) can initially look like cycles when their no-op nicks
    # don't split the merged strand, but downstream nick placements often
    # break those cycles. Run a final retry-ligate pass so the marker only
    # fires for genuine, unfixable circularizations.
    from backend.core.lattice import retry_all_pending_ligations
    current = retry_all_pending_ligations(current)

    # A scaffold that closes into a circle (its 5'/3' termini joined by a
    # crossover) has no free end for sequence assignment and trips the circular
    # warning.  Reopen any such loop with one buried, non-crossover nick near the
    # structure's middle (see _linearize_circular_scaffolds).  Runs for every
    # routing mode, not just matched ends — the NADOC model cannot store a truly
    # circular strand, so the loop is a linear strand whose ends a crossover joins.
    current = _linearize_circular_scaffolds(current, result)

    append_single_strand_warning(current, result)
    return current, result


def scaffold_strand_clusters(design: Design) -> list[set[str]]:
    """Connected components of scaffold helices under valid scaffold-crossover
    adjacency — the 'separate cluster' definition (helix groups that share no
    valid scaffold crossover site).  Each connected cluster should route to a
    single scaffold strand; genuinely disconnected clusters route to one strand
    each.
    """
    coverage = _scaffold_coverage(design)
    adj = _build_adj(design, coverage)
    visited: set[str] = set()
    comps: list[set[str]] = []
    for hid in adj:
        if hid in visited:
            continue
        comp: set[str] = set()
        stack = [hid]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            comp.add(n)
            stack.extend(adj[n] - visited)
        comps.append(comp)
    return comps


def append_single_strand_warning(design: Design, result) -> None:
    """Warn when a connected cluster fragmented into more than one scaffold strand.

    A single connected cluster should route to one scaffold strand.  Automatic
    consolidation of irregular multi-section designs into one strand is not yet
    implemented: adding crossovers at valid mid-strand sites re-partitions the
    linear pieces (proven: a single crossover splits, a double crossover swaps —
    neither merges), so merging needs end-joining / 2-opt cycle reconnection.
    This surfaces the gap instead of silently shipping fragments.  ``result``
    is any router result object exposing a ``warnings`` list.
    """
    clusters = scaffold_strand_clusters(design)
    scaf = [
        s for s in design.strands
        if s.is_scaffold and not getattr(s, "is_reference", False)
    ]
    if len(scaf) > len(clusters):
        result.warnings.append(
            f"Scaffold routed into {len(scaf)} strands across {len(clusters)} "
            f"connected cluster(s); each connected cluster should be a single "
            f"strand.  Automatic single-strand consolidation for irregular "
            f"multi-section designs is not yet implemented — join the extra "
            f"pieces manually (forced ligation) or re-route."
        )


def _scaffold_end_join_xover(design: Design, strand: Strand) -> Crossover | None:
    """Return the crossover joining ``strand``'s 3' terminus to its own 5' terminus.

    The NADOC model cannot store a truly circular strand, so a routed loop is a
    linear strand whose first-domain 5' and last-domain 3' sit on a shared
    crossover (which ``_ligate_xover`` left unligated to avoid self-circularizing).
    Its presence is exactly the 'circular scaffold' condition the UI warns about.
    """
    if len(strand.domains) < 2:
        return None
    f, l = strand.domains[0], strand.domains[-1]
    target = {(f.helix_id, f.start_bp), (l.helix_id, l.end_bp)}
    for xo in design.crossovers:
        ends = {(xo.half_a.helix_id, xo.half_a.index),
                (xo.half_b.helix_id, xo.half_b.index)}
        if ends == target:
            return xo
    return None


def _choose_buried_nick(design: Design, strand: Strand) -> tuple[str, int, Direction] | None:
    """Pick a buried, non-crossover interior bp on ``strand`` nearest the structure's
    bp-center — the spot to reopen a circular scaffold so its 5'/3' land mid-bundle.

    Returns ``(helix_id, bp_index, direction)`` or ``None`` if no safe site exists
    (e.g. every domain is too short or fully occupied by crossover sites).
    """
    all_bp = [bp for dm in strand.domains for bp in (dm.start_bp, dm.end_bp)]
    center = (min(all_bp) + max(all_bp)) / 2.0
    xover_bp: dict[str, set[int]] = {}
    for xo in design.crossovers:
        xover_bp.setdefault(xo.half_a.helix_id, set()).add(xo.half_a.index)
        xover_bp.setdefault(xo.half_b.helix_id, set()).add(xo.half_b.index)
    best: tuple[str, int, Direction] | None = None
    best_d: float | None = None
    for dm in strand.domains:
        lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
        # interior bps with >=2 margin from each domain end (clear of termini/stubs)
        interior = [bp for bp in range(lo + 2, hi - 1)
                    if bp not in xover_bp.get(dm.helix_id, ())]
        if not interior:
            continue
        bp = min(interior, key=lambda b: abs(b - center))
        d = abs(bp - center)
        if best_d is None or d < best_d:
            best_d, best = d, (dm.helix_id, bp, dm.direction)
    return best


def _linearize_circular_scaffolds(design: Design, result: SeamedResult) -> Design:
    """Open any circular scaffold into one linear strand with a buried, mid-structure nick.

    The loop's 5'/3' are joined by a crossover (see _scaffold_end_join_xover).  We nick
    at a non-crossover interior bp near the bundle's middle (_choose_buried_nick); that
    splits the strand into two fragments, then ligating the closing crossover re-merges
    them into one strand re-rooted at the nick — so the open 5'/3' end up buried
    mid-bundle instead of on the (often surface) closing crossover.
    """
    from backend.core.lattice import make_nick
    for strand in [s for s in design.strands if s.is_scaffold and not s.is_reference]:
        xo = _scaffold_end_join_xover(design, strand)
        if xo is None:
            continue
        pick = _choose_buried_nick(design, strand)
        if pick is None:
            result.warnings.append(
                "Scaffold is circular but no buried non-crossover nick site was found; "
                "add a nick manually to open the loop."
            )
            continue
        helix_id, bp_index, direction = pick
        try:
            design = make_nick(design, helix_id, bp_index, direction)
        except ValueError:
            result.warnings.append(
                "Scaffold is circular; automatic mid-structure nick hit a terminus guard "
                "and was skipped — add a nick manually to open the loop."
            )
            continue
        design = _ligate_xover(design, xo)
    return design


def _matched_ends_feasible(result: SeamedResult) -> bool:
    """True when a matched-ends run produced a clean, fully-matched far face.

    Matched ends require every far crossover to be an exact one-period translate
    of its near partner.  The matched pipeline emits a ``[MatchedEnds]`` warning
    whenever it cannot do that for a pair (no near crossovers to mirror, count
    mismatch, or an off-lattice translate that fell back to a local search), so
    the absence of any such warning — with far ends actually placed — means the
    geometry admitted clean matched ends.
    """
    if result.far_end_xovers <= 0:
        return False
    return not any(w.startswith("[MatchedEnds]") for w in result.warnings)


def seamed_routability_errors(design: Design) -> list[str]:
    """Precondition guard for the *seamed/matched* endpoints (empty == routable).

    The seamed router threads one Hamiltonian path through each connected group of
    the scaffold-crossover adjacency graph, then chains consecutive path helices in
    steps of two (``_auto_scaffold_seamed_impl``: seam pairs ``(1,2),(3,4)…`` + near
    pairs ``(0,1),(2,3)…``).  Two shapes silently fragment that into a disjoint
    scaffold instead of one strand:

    * **Odd helix group** — the step-2 pairing chains ``path[0..n-2]``; when the group
      has an *odd* number of helices ``path[n-1]`` is never placed in any pair and is
      left as its own single-helix scaffold (e.g. a 3×3 → 8+1, an L → 6+1).
    * **No Hamiltonian path** — some connected cross-sections (e.g. a staircase
      triangle) admit no single path through the crossover graph at all, so the whole
      group is skipped and *every* helix stays its own scaffold.

    Rather than emit a silently-broken scaffold (which then feeds garbage duplex
    coverage to downstream FEM / audits), the endpoints refuse with these messages so
    the UI can toast them.  The guard is scoped to the *classic per-group* path only:
    forced-ligation (hinge) and multi-section (dumbbell/teeth) designs route through
    their own routers and are out of scope here — they are returned as routable.

    Seamless routing pairs helices differently (zig-zag) and handles odd groups, so
    this guard is deliberately NOT applied to the seamless endpoint.
    """
    if design.forced_ligations:
        return []  # hinge router path — out of scope for this guard

    coverage = _scaffold_coverage(design)
    if not coverage:
        return []  # nothing to route; the router reports its own "no scaffold" warning

    from backend.core.section_router import has_multisection_helix
    if has_multisection_helix(coverage):
        return []  # section router path — out of scope for this guard

    adj = _build_adj(design, coverage)

    # Connected components of the crossover-adjacency graph (mirrors the impl).
    visited: set[str] = set()
    components: list[list[str]] = []
    for hid in adj:
        if hid in visited:
            continue
        comp, stack = [], [hid]
        while stack:
            nid = stack.pop()
            if nid in visited:
                continue
            visited.add(nid); comp.append(nid)
            stack.extend(adj[nid] - visited)
        components.append(comp)

    errors: list[str] = []
    for comp in components:
        if len(comp) < 4:
            continue  # the impl already warns on tiny groups; not this guard's job
        path = _hamiltonian_path(comp, adj)
        if not path or len(path) < len(comp):
            errors.append(
                f"Seamed autoscaffold can't thread a single scaffold path through all "
                f"{len(comp)} helices of this cross-section (no continuous crossover "
                f"path exists for this shape). Try Seamless routing, or adjust the "
                f"cross-section."
            )
        elif len(path) % 2 == 1:
            errors.append(
                f"Seamed autoscaffold needs an even number of helices per connected "
                f"group; this design has a group of {len(path)} helices (odd), which "
                f"would leave one helix unrouted. Try Seamless routing, which handles "
                f"odd helix counts."
            )
    return errors


def auto_scaffold_seamed(design: Design) -> tuple[Design, SeamedResult]:
    """Seamed scaffold pipeline (Seam → Near Ends → Far Ends).

    Produces **matched ends by default**: the far (+hi) face is routed as an
    exact translate of the near (−lo) face so identical copies stack blunt-end
    end-to-end (the same routing as ``auto_scaffold_matched``).  When the
    geometry cannot be cleanly matched (non-uniform helix spans, dumbbells,
    multi-section designs), this falls back to the classic seamed route, which
    skips the lowest-helix far pair to park the scaffold's open 5'/3' terminus
    and routes the two ends independently.

    Each attempt runs on its own deep copy so the discarded matched attempt can
    never leak crossovers into the classic fallback.

    Irregular multi-section designs (teeth, dumbbells) — any helix whose scaffold
    coverage spans more than one section — are routed to a single strand by the
    section router, which keeps each tooth's end-turns at its own faces so the
    inter-tooth gaps stay clear (the per-helix seamed path over-extends tooth far
    faces a full crossover-period into the gaps).  The section router falls back to
    ``None`` for anything it cannot cleanly route, so this drops through to the
    classic seamed pipeline below; designs with manual forced ligations are never
    overridden.  See backend/core/section_router.py.
    ISSUE-9: a prior auto-route is RESET to the staple-defined structural seed first,
    so routing an already-routed design is idempotent (N calls == 1 call).  Without
    this the router reads its own previous output as the face to extend from and
    ratchets the helices outward on every call.  See ``scaffold_reset``.  The reset
    must run BEFORE the multi-section probe below, which reads scaffold coverage.
    """
    from backend.core.scaffold_reset import reset_scaffold_to_structure
    design, reset_warnings = reset_scaffold_to_structure(design)

    if design.forced_ligations:
        # Forced-ligation hinge designs (cross-gap scaffold bridges): route one
        # SEAMED, compliant strand through the bridges.  route_hinge is self-gated
        # against the scaffold-routing invariants and returns None for anything it
        # cannot route compliantly (incl. genuine one-off manual anchors), which
        # falls through to the classic preserve-the-anchor pipeline — no regression.
        from backend.core.hinge_router import route_hinge
        hinged = route_hinge(design.model_copy(deep=True))
        if hinged is not None:
            hinged[1].warnings.extend(reset_warnings)
            return hinged
    else:
        coverage = _scaffold_coverage(design)
        from backend.core.section_router import has_multisection_helix, route_sections
        if has_multisection_helix(coverage):
            sectioned = route_sections(design.model_copy(deep=True))
            if sectioned is not None:
                sectioned[1].warnings.extend(reset_warnings)
                return sectioned

    matched_design, matched_result = _auto_scaffold_seamed_impl(
        design.model_copy(deep=True), matched_ends=True
    )
    if _matched_ends_feasible(matched_result):
        matched_result.warnings.extend(reset_warnings)
        return matched_design, matched_result

    classic_design, classic_result = _auto_scaffold_seamed_impl(
        design.model_copy(deep=True), matched_ends=False
    )
    classic_result.warnings.insert(
        0, "Matched ends not feasible for this geometry; used classic seamed routing."
    )
    classic_result.warnings.extend(reset_warnings)
    return classic_design, classic_result


def auto_scaffold_seamed_bounded(design: Design) -> tuple[Design, SeamedResult]:
    """Classic seamed route with bounded end-turns (no matched-ends attempt).

    Used by the section router for WINDOW sub-bundles: places each near/far
    end-turn at the nearest valid crossover at-or-past its section face so the
    turn-around never extends a full crossover-period into the inter-tooth gaps.
    See ``_auto_scaffold_seamed_impl``'s ``bounded_ends`` for the rationale.
    """
    return _auto_scaffold_seamed_impl(
        design.model_copy(deep=True), matched_ends=False, bounded_ends=True
    )


def auto_scaffold_matched(design: Design) -> tuple[Design, SeamedResult]:
    """Matched-ends scaffold pipeline for blunt-end end-to-end polymerization.

    Routes so the far (hi-bp) face is an exact translate of the near (lo-bp)
    face by one repeat period P (a whole multiple of the lattice crossover
    period): every helix's far cap lands on the next copy's near cap, so
    identical copies stack end-to-end.  Seam marking + sequence assignment stay
    with the existing periodic tools.

    Like the advanced variants, a prior auto-scaffold route is cleared and
    re-seeded first (so this can be applied to an already-routed design); manual
    forced-ligation routes are preserved (with a warning).
    """
    from backend.core.scaffold_reset import reset_scaffold_to_structure

    result = SeamedResult()
    # ISSUE-9: retract to the staple-defined seed first.  _clear_auto_scaffold_route_
    # for_seamed only re-seeds STRANDS and drops crossovers — it never retracts the
    # helices the previous route extended, so on its own it does not stop the ratchet.
    design, reset_warnings = reset_scaffold_to_structure(design)
    result.warnings.extend(reset_warnings)
    seed = _clear_auto_scaffold_route_for_seamed(design, result)
    current, matched = _auto_scaffold_seamed_impl(seed, matched_ends=True)
    result.warnings.extend(matched.warnings)
    result.seam_xovers += matched.seam_xovers
    result.near_end_xovers += matched.near_end_xovers
    result.far_end_xovers += matched.far_end_xovers
    return current, result


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
        if strand.is_reference:
            new_strands.append(strand)  # reference geometry is never re-seeded
            continue
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
