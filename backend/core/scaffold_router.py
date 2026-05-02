"""
Scaffold router — constraint-satisfaction scaffold routing for NADOC.

Algorithm overview:
  1. Extract RouterDomains from scaffold strands (merge nicked, split gapped).
  2. BCC decomposition: classify helices as core or bulge.
  3. Build candidate crossover graph from lattice lookup tables (seam/end tagged).
  4. Validate pre-conditions (V1–V8).
  5. CSP backtracking search (MCV heuristic, alternation, steric exclusion).
  6. Bulge subroutine (recursive).
  7. Atomic Design update: replace scaffold strands.

Three-Layer Law: this module ONLY modifies topology (strand graph). No geometry
or physics is touched.

Domain convention (NADOC):
  start_bp = 5′ end, end_bp = 3′ end regardless of direction.
  FORWARD: start_bp < end_bp (low → high)
  REVERSE: start_bp > end_bp (high → low)
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

import networkx as nx

from backend.core.constants import (
    HC_CROSSOVER_PERIOD,
    HC_SCAFFOLD_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_PERIOD,
    SQ_SCAFFOLD_CROSSOVER_OFFSETS,
)
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    HalfCrossover,
    Helix,
    LatticeType,
    Strand,
    StrandType,
)

# ── Data structures ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RouterDomain:
    """A contiguous scaffold segment used as the unit of routing decisions.

    start_bp = 5′ end, end_bp = 3′ end (NADOC convention).
    FORWARD: start_bp < end_bp.  REVERSE: start_bp > end_bp.

    seam_side: which bp end is the seam split boundary (None = full domain).
      "lo" — seam boundary is at lo_bp (right half-domains: FORWARD [seam→hi],
              REVERSE [hi→seam]).  Physical helix end is at hi_bp.
      "hi" — seam boundary is at hi_bp (left half-domains: FORWARD [lo→seam],
              REVERSE [seam→lo]).  Physical helix end is at lo_bp.
    """

    id: str
    helix_id: str
    start_bp: int           # 5′ end
    end_bp: int             # 3′ end
    direction: Direction
    seam_side: Optional[str] = None   # "lo" | "hi" | None

    @property
    def lo_bp(self) -> int:
        return min(self.start_bp, self.end_bp)

    @property
    def hi_bp(self) -> int:
        return max(self.start_bp, self.end_bp)

    @property
    def length(self) -> int:
        return self.hi_bp - self.lo_bp + 1

    @property
    def midpoint(self) -> float:
        return (self.lo_bp + self.hi_bp) / 2.0

    @property
    def five_prime_bp(self) -> int:
        return self.start_bp

    @property
    def three_prime_bp(self) -> int:
        return self.end_bp

    @property
    def seam_boundary_bp(self) -> Optional[int]:
        """The bp at the seam split, or None for full domains."""
        if self.seam_side == "lo":
            return self.lo_bp
        if self.seam_side == "hi":
            return self.hi_bp
        return None

    @property
    def physical_end_bp(self) -> Optional[int]:
        """The physical helix end for half-domains; None for full domains."""
        if self.seam_side == "lo":
            return self.hi_bp   # physical end is at hi
        if self.seam_side == "hi":
            return self.lo_bp   # physical end is at lo
        return None


@dataclass(frozen=True)
class CandidateXover:
    """A candidate scaffold crossover between two RouterDomains at a shared bp.

    dom_a_id / dom_b_id are unordered (either domain can be 3′ or 5′ depending
    on traversal direction).  tag is "seam" (near midpoint of both domains) or
    "end" (near extremum of both domains).
    """

    id: str
    dom_a_id: str
    dom_b_id: str
    bp: int
    tag: str        # "seam" | "end"


@dataclass
class Routing:
    """Successful scaffold routing result."""

    domains: list[RouterDomain]
    xovers: list[CandidateXover]      # chosen crossovers (subset of candidates)
    path_order: list[str]             # domain IDs in 5′→3′ traversal order


@dataclass
class ValidationResult:
    """Pre-condition check result."""

    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Lattice helpers ────────────────────────────────────────────────────────────


def _helix_is_forward(helix: Helix) -> Optional[bool]:
    """Return True if helix has even parity (FORWARD scaffold), False if odd.

    Returns None if grid_pos is absent and helix.direction is also None.
    """
    if helix.grid_pos is not None:
        row, col = helix.grid_pos
        return (row + col) % 2 == 0
    if helix.direction is not None:
        return helix.direction == Direction.FORWARD
    return None


def _helix_direction(helix: Helix) -> Optional[Direction]:
    fwd = _helix_is_forward(helix)
    if fwd is None:
        return None
    return Direction.FORWARD if fwd else Direction.REVERSE


# ── Domain extraction ──────────────────────────────────────────────────────────


def _merge_helix_segments(
    segs: list[tuple[int, int]],
    direction: Direction,
    helix_id: str,
) -> list[RouterDomain]:
    """Merge adjacent scaffold segments on one helix into RouterDomains.

    Segments with a 1-bp gap (nick, no missing bp) are merged.
    Segments with ≥2-bp gap remain separate.

    NADOC adjacency: FORWARD → prev.end_bp + 1 == next.start_bp
                     REVERSE → prev.end_bp - 1 == next.start_bp
    """
    if not segs:
        return []

    is_fwd = direction == Direction.FORWARD

    # Sort so we traverse in 5′→3′ order (ascending bp for FWD, descending for REV)
    if is_fwd:
        sorted_segs = sorted(segs, key=lambda s: s[0])
    else:
        sorted_segs = sorted(segs, key=lambda s: s[0], reverse=True)

    adj_delta = +1 if is_fwd else -1
    merged: list[tuple[int, int]] = [sorted_segs[0]]
    for start, end in sorted_segs[1:]:
        prev_start, prev_end = merged[-1]
        if prev_end + adj_delta == start or prev_end == start:
            merged[-1] = (prev_start, end)
        else:
            merged.append((start, end))

    return [
        RouterDomain(
            id=f"rd_{helix_id}_{s}_{e}",
            helix_id=helix_id,
            start_bp=s,
            end_bp=e,
            direction=direction,
        )
        for s, e in merged
    ]


def _split_domain_at_seam(
    dom: RouterDomain,
) -> tuple[RouterDomain, RouterDomain]:
    """Split a full RouterDomain at its midpoint into two half-domains.

    The split point S = (lo_bp + hi_bp + 1) // 2 lies between the two halves.
    Both halves share bp S as their seam boundary.

    Returns (left_half, right_half).
      left_half:  lo_bp → S  (seam_side="hi": seam at hi=S, physical end at lo)
      right_half: S → hi_bp  (seam_side="lo": seam at lo=S, physical end at hi)
    """
    lo, hi = dom.lo_bp, dom.hi_bp
    seam = (lo + hi + 1) // 2   # e.g. (0+83+1)//2 = 42

    if dom.direction == Direction.FORWARD:
        left = RouterDomain(
            id=f"{dom.id}_L",
            helix_id=dom.helix_id,
            start_bp=lo,
            end_bp=seam,
            direction=Direction.FORWARD,
            seam_side="hi",
        )
        right = RouterDomain(
            id=f"{dom.id}_R",
            helix_id=dom.helix_id,
            start_bp=seam,
            end_bp=hi,
            direction=Direction.FORWARD,
            seam_side="lo",
        )
    else:  # REVERSE: 5′ at hi, 3′ at lo
        right = RouterDomain(
            id=f"{dom.id}_R",
            helix_id=dom.helix_id,
            start_bp=hi,
            end_bp=seam,
            direction=Direction.REVERSE,
            seam_side="lo",
        )
        left = RouterDomain(
            id=f"{dom.id}_L",
            helix_id=dom.helix_id,
            start_bp=seam,
            end_bp=lo,
            direction=Direction.REVERSE,
            seam_side="hi",
        )
    return left, right


def extract_router_domains(
    design: Design,
    min_split_length: int = 42,
) -> tuple[list[RouterDomain], dict[str, RouterDomain]]:
    """Extract RouterDomains from all scaffold strands in the design.

    Adjacent (nicked) segments on the same helix are merged.  Segments with
    a real bp gap remain separate.

    If a domain's length >= min_split_length it is split into two half-domains
    at its midpoint so the router can achieve full helix coverage.  Set
    min_split_length=0 to split everything or a large value to disable splitting.

    Returns (domains_list, domain_by_id).
    """
    helix_by_id: dict[str, Helix] = {h.id: h for h in design.helices}

    # Group scaffold domains by helix_id
    by_helix: dict[str, list[tuple[int, int]]] = defaultdict(list)
    dir_by_helix: dict[str, Direction] = {}

    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in strand.domains:
            if dom.overhang_id is not None:
                continue
            by_helix[dom.helix_id].append((dom.start_bp, dom.end_bp))
            dir_by_helix[dom.helix_id] = dom.direction

    merged_domains: list[RouterDomain] = []
    for helix_id, segs in by_helix.items():
        helix = helix_by_id.get(helix_id)
        direction = dir_by_helix[helix_id]
        # Prefer lattice-derived direction when available
        if helix is not None:
            lattice_dir = _helix_direction(helix)
            if lattice_dir is not None:
                direction = lattice_dir
        merged_domains.extend(_merge_helix_segments(segs, direction, helix_id))

    domains: list[RouterDomain] = []
    for dom in merged_domains:
        if dom.length > min_split_length:
            left, right = _split_domain_at_seam(dom)
            domains.extend([left, right])
        else:
            domains.append(dom)

    domain_by_id = {d.id: d for d in domains}
    return domains, domain_by_id


# ── Crossover candidate builder ────────────────────────────────────────────────


def _scaffold_xover_bps_at_direction(
    is_forward: bool,
    drow: int,
    dcol: int,
    lo: int,
    hi: int,
    lattice_type: LatticeType,
) -> list[int]:
    """Return bp positions in [lo, hi] where a scaffold crossover to neighbor
    (row+drow, col+dcol) is lattice-valid for a cell with given parity."""
    if lattice_type == LatticeType.HONEYCOMB:
        offsets = HC_SCAFFOLD_CROSSOVER_OFFSETS
        period = HC_CROSSOVER_PERIOD
    else:
        offsets = SQ_SCAFFOLD_CROSSOVER_OFFSETS
        period = SQ_CROSSOVER_PERIOD

    valid_mods = frozenset(
        bp_mod
        for (fwd, bp_mod), (dr, dc) in offsets.items()
        if fwd == is_forward and dr == drow and dc == dcol
    )
    return [bp for bp in range(lo, hi + 1) if bp % period in valid_mods]


def _near_seam(bp: int, dom: RouterDomain, seam_tol: int) -> bool:
    """True if bp is near dom's seam boundary (midpoint for full domains)."""
    ref = float(dom.seam_boundary_bp) if dom.seam_side is not None else dom.midpoint
    return abs(bp - ref) <= seam_tol


def _near_phys_end(
    bp: int, dom: RouterDomain, end_tol: int, min_dist: int
) -> bool:
    """True if bp is within end_tol of dom's physical end AND >= min_dist from it.

    For full domains (seam_side=None) both extrema are treated as physical ends
    and min_dist is not enforced (preserves legacy behaviour).
    """
    phys = dom.physical_end_bp
    if phys is None:
        # Full domain: either extremum counts, no min_dist constraint
        return (
            abs(bp - dom.lo_bp) <= end_tol
            or abs(bp - dom.hi_bp) <= end_tol
        )
    return abs(bp - phys) <= end_tol and abs(bp - phys) >= min_dist


def _tag_xover(
    bp: int,
    dom1: RouterDomain,
    dom2: RouterDomain,
    seam_tol: int,
    end_tol: int,
    min_end_dist: int = 3,
) -> Optional[str]:
    """Classify a crossover bp as "seam", "end", or None (unclassifiable).

    For half-domains (seam_side set):
      seam: bp near the seam boundary of BOTH domains.
      end:  bp near the physical helix end of BOTH domains, >= min_end_dist away.

    For full domains (seam_side=None, legacy behaviour):
      seam: bp near the midpoint of BOTH domains.
      end:  bp near either extremum of BOTH domains (no min_dist).
    """
    if _near_seam(bp, dom1, seam_tol) and _near_seam(bp, dom2, seam_tol):
        return "seam"

    if (
        _near_phys_end(bp, dom1, end_tol, min_end_dist)
        and _near_phys_end(bp, dom2, end_tol, min_end_dist)
    ):
        return "end"

    return None


def build_candidate_graph(
    domains: list[RouterDomain],
    design: Design,
    seam_tol: int = 5,
    end_tol: int = 5,
) -> dict[str, list[CandidateXover]]:
    """Build {domain_id: [CandidateXover, ...]} adjacency map.

    For every pair of domains on lattice-adjacent helices, enumerate all valid
    scaffold crossover bp positions and tag each as seam or end.  Only seam/end
    positions are included; unclassifiable ones are dropped.
    """
    helix_by_id: dict[str, Helix] = {h.id: h for h in design.helices}
    lattice = design.lattice_type

    # Map helix_id → domain(s)
    doms_by_helix: dict[str, list[RouterDomain]] = defaultdict(list)
    for d in domains:
        doms_by_helix[d.helix_id].append(d)

    candidates_by_dom: dict[str, list[CandidateXover]] = defaultdict(list)
    seen_pairs: set[frozenset[str]] = set()  # avoid duplicate pairs

    helix_ids = list(doms_by_helix.keys())
    for i, hid_a in enumerate(helix_ids):
        ha = helix_by_id.get(hid_a)
        if ha is None or ha.grid_pos is None:
            continue
        ra, ca = ha.grid_pos
        is_fwd_a = (ra + ca) % 2 == 0

        for hid_b in helix_ids[i + 1:]:
            pair_key = frozenset([hid_a, hid_b])
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            hb = helix_by_id.get(hid_b)
            if hb is None or hb.grid_pos is None:
                continue
            rb, cb = hb.grid_pos

            drow, dcol = rb - ra, cb - ca

            for dom_a in doms_by_helix[hid_a]:
                for dom_b in doms_by_helix[hid_b]:
                    # bp range overlap: crossover bp must be in both domains
                    lo = max(dom_a.lo_bp, dom_b.lo_bp)
                    hi = min(dom_a.hi_bp, dom_b.hi_bp)
                    if lo > hi:
                        continue

                    valid_bps = _scaffold_xover_bps_at_direction(
                        is_fwd_a, drow, dcol, lo, hi, lattice
                    )
                    for bp in valid_bps:
                        tag = _tag_xover(bp, dom_a, dom_b, seam_tol, end_tol)
                        if tag is None:
                            continue
                        xid = f"cx_{dom_a.id}_{dom_b.id}_{bp}"
                        xover = CandidateXover(
                            id=xid,
                            dom_a_id=dom_a.id,
                            dom_b_id=dom_b.id,
                            bp=bp,
                            tag=tag,
                        )
                        candidates_by_dom[dom_a.id].append(xover)
                        candidates_by_dom[dom_b.id].append(xover)

    return dict(candidates_by_dom)


# ── Existing fixed crossovers ──────────────────────────────────────────────────


def _existing_scaffold_xover_set(design: Design) -> set[tuple[str, str, int]]:
    """Return scaffold crossovers as (helix_id_a, helix_id_b, bp) triples.

    Used to tag which crossovers are already present so the router can try to
    preserve them.
    """
    scaffold_strand_ids: set[str] = {
        s.id for s in design.strands if s.strand_type == StrandType.SCAFFOLD
    }
    # Map (helix_id, index, direction) → strand_id for scaffold half-crossovers
    slot_to_strand: dict[tuple[str, int, str], str] = {}
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in strand.domains:
            # Register both endpoints as potential crossover slots
            for bp in (dom.start_bp, dom.end_bp):
                slot_to_strand[(dom.helix_id, bp, dom.direction.value)] = strand.id

    result: set[tuple[str, str, int]] = set()
    for xover in design.crossovers:
        ha, hb = xover.half_a, xover.half_b
        key_a = (ha.helix_id, ha.index, ha.strand.value)
        key_b = (hb.helix_id, hb.index, hb.strand.value)
        if key_a in slot_to_strand or key_b in slot_to_strand:
            # At least one half is on a scaffold strand — treat as scaffold xover
            pair = tuple(sorted([ha.helix_id, hb.helix_id]))
            result.add((pair[0], pair[1], ha.index))
    return result


# ── BCC decomposition ──────────────────────────────────────────────────────────


def build_helix_adjacency_graph(
    domains: list[RouterDomain],
    design: Design,
    seam_tol: int = 5,
    end_tol: int = 5,
) -> nx.Graph:
    """Return undirected graph of helices connected by scaffold crossover candidates.

    Nodes are helix IDs.  Edges carry a list of CandidateXover objects.
    """
    candidates_by_dom = build_candidate_graph(domains, design, seam_tol, end_tol)
    G: nx.Graph = nx.Graph()

    helix_by_id = {h.id: h for h in design.helices}
    for dom in domains:
        if dom.helix_id in helix_by_id:
            G.add_node(dom.helix_id)

    seen: set[str] = set()
    for xovers in candidates_by_dom.values():
        for xover in xovers:
            if xover.id in seen:
                continue
            seen.add(xover.id)
            da_id, db_id = xover.dom_a_id, xover.dom_b_id
            # Need to go from domain id to helix id
            pass  # We'll add edges below

    # Build domain-to-helix lookup
    dom_to_helix = {d.id: d.helix_id for d in domains}

    seen.clear()
    for xovers in candidates_by_dom.values():
        for xover in xovers:
            if xover.id in seen:
                continue
            seen.add(xover.id)
            ha_id = dom_to_helix.get(xover.dom_a_id)
            hb_id = dom_to_helix.get(xover.dom_b_id)
            if ha_id is None or hb_id is None or ha_id == hb_id:
                continue
            if G.has_edge(ha_id, hb_id):
                G[ha_id][hb_id]["xovers"].append(xover)
            else:
                G.add_edge(ha_id, hb_id, xovers=[xover])

    return G


def decompose_core_bulges(
    design: Design,
    domains: list[RouterDomain],
    seam_tol: int = 5,
    end_tol: int = 5,
) -> tuple[set[str], dict[str, str]]:
    """Biconnected-component decomposition of the helix adjacency graph.

    Returns:
        core_helices: helix IDs in the biconnected core (non-leaf BCCs).
        bulge_gateway: helix_id → core_helix_id for leaf-BCC gateway helices.

    Leaf BCCs (attached to the core via exactly one cut vertex) are bulges.
    The cut vertex is the gateway helix.
    """
    G = build_helix_adjacency_graph(domains, design, seam_tol, end_tol)

    if len(G.nodes) == 0:
        return set(), {}

    # Find biconnected components and articulation points
    bccs = list(nx.biconnected_components(G))
    art_points = set(nx.articulation_points(G))

    # A leaf BCC has exactly one articulation point among its nodes
    core_helices: set[str] = set()
    bulge_gateway: dict[str, str] = {}

    for bcc in bccs:
        bcc_arts = bcc & art_points
        if len(bcc_arts) == 1:
            # Leaf BCC — bulge
            gateway = next(iter(bcc_arts))
            for h in bcc:
                if h != gateway:
                    bulge_gateway[h] = gateway
        else:
            # Part of the core
            core_helices.update(bcc)

    # If the whole graph is a single BCC with no articulation points, all are core
    if not core_helices:
        core_helices.update(G.nodes)

    return core_helices, bulge_gateway


# ── Validator ─────────────────────────────────────────────────────────────────


def validate_routing(
    design: Design,
    domains: list[RouterDomain],
    candidates_by_dom: dict[str, list[CandidateXover]],
) -> ValidationResult:
    """Check pre-conditions for scaffold routing (V1–V8).

    V1: At least 2 domains exist.
    V2: All domains are on helices present in the design.
    V3: All helices have a valid grid_pos (required for crossover lookup).
    V4: All helices have determinable direction.
    V5: Lattice type is HC or SQ (recognised).
    V6: Each non-isolated domain has ≥1 candidate crossover.
    V7: The domain adjacency graph is connected (single component) OR has
        isolated domains (warning only).
    V8: Degree feasibility — each domain needs ≤2 crossovers; at least two
        endpoint domains (degree≤1) exist for a valid path.
    """
    errors: list[str] = []
    warnings: list[str] = []
    helix_by_id = {h.id: h for h in design.helices}

    # V1
    if len(domains) < 1:
        errors.append("V1: No scaffold domains found — nothing to route.")
        return ValidationResult(valid=False, errors=errors, warnings=warnings)

    if len(domains) == 1:
        warnings.append("V1: Only one domain — no crossovers can be added.")

    # V2
    missing_helices = [d.helix_id for d in domains if d.helix_id not in helix_by_id]
    if missing_helices:
        errors.append(f"V2: Domains reference unknown helix IDs: {missing_helices[:5]}")

    # V3 + V4
    no_grid = [
        h.id for h in design.helices
        if h.id in {d.helix_id for d in domains}
        and h.grid_pos is None
    ]
    if no_grid:
        warnings.append(
            f"V3: {len(no_grid)} helix(es) lack grid_pos — crossovers may be unavailable."
        )

    no_dir = [
        h.id for h in design.helices
        if h.id in {d.helix_id for d in domains}
        and _helix_direction(h) is None
    ]
    if no_dir:
        errors.append(
            f"V4: {len(no_dir)} helix(es) have no determinable direction: {no_dir[:5]}"
        )

    # V5
    if design.lattice_type not in (LatticeType.HONEYCOMB, LatticeType.SQUARE):
        errors.append(f"V5: Unrecognised lattice type: {design.lattice_type!r}")

    # V6
    isolated = [d.id for d in domains if d.id not in candidates_by_dom]
    if len(isolated) > 0 and len(isolated) == len(domains):
        errors.append("V6: No candidate crossovers found — are helices lattice-adjacent?")
    elif isolated:
        warnings.append(
            f"V6: {len(isolated)} isolated domain(s) with no crossover candidates."
        )

    # V7: connectivity via candidate graph
    G: nx.Graph = nx.Graph()
    for dom in domains:
        G.add_node(dom.id)
    seen: set[str] = set()
    for xovers in candidates_by_dom.values():
        for xover in xovers:
            if xover.id not in seen:
                seen.add(xover.id)
                G.add_edge(xover.dom_a_id, xover.dom_b_id)

    n_components = nx.number_connected_components(G)
    if n_components > 1:
        warnings.append(
            f"V7: Domain adjacency graph has {n_components} connected components — "
            "components will be routed independently; components that cannot be "
            "routed will be preserved unchanged."
        )

    # V8: degree feasibility
    max_degree = max(
        (len(xovers) for xovers in candidates_by_dom.values()), default=0
    )
    if max_degree == 0 and len(domains) > 1:
        errors.append("V8: No candidate crossovers — degree constraint cannot be satisfied.")

    return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)


# ── CSP backtracking solver ────────────────────────────────────────────────────


def _opposite_tag(tag: str) -> str:
    return "end" if tag == "seam" else "seam"


def _csp_backtrack(
    path: list[str],             # current path of domain IDs
    last_xover_tag: Optional[str],   # tag of the last crossover added (None = start)
    visited: set[str],           # set of visited domain IDs
    xover_path: list[CandidateXover],  # crossovers used so far
    steric_bps: dict[str, set[int]],   # helix_id → used bp positions
    domain_by_id: dict[str, RouterDomain],
    candidates_by_dom: dict[str, list[CandidateXover]],
    n_domains: int,
    max_backtracks: int,
    backtracks: list[int],        # mutable counter [bt_count]
) -> Optional[tuple[list[str], list[CandidateXover]]]:
    """Recursive CSP backtracking for a Hamiltonian path with alternation.

    Returns (path_order, xovers_used) or None if no solution found within budget.
    """
    if len(path) == n_domains:
        return path[:], xover_path[:]

    current_id = path[-1]
    candidates = candidates_by_dom.get(current_id, [])

    # Filter candidates by:
    # 1. Other domain not yet visited
    # 2. Alternation: tag must differ from last_xover_tag (if set)
    # 3. Steric exclusion: bp not already used on either helix
    # 4. MCV heuristic ordering (fewest forward options first)
    valid_next: list[tuple[CandidateXover, str]] = []  # (xover, next_dom_id)

    required_tag = _opposite_tag(last_xover_tag) if last_xover_tag else None
    curr_dom = domain_by_id[current_id]

    # Entry bp for the current domain (5' end if path start, else last xover bp).
    entry_for_curr: int = (
        xover_path[-1].bp if xover_path else curr_dom.five_prime_bp
    )

    for xover in candidates:
        # Determine which end is the "next" domain
        next_id = xover.dom_b_id if xover.dom_a_id == current_id else xover.dom_a_id
        if next_id in visited:
            continue
        if required_tag is not None and xover.tag != required_tag:
            continue

        bp = xover.bp
        next_dom = domain_by_id[next_id]

        # Steric check: bp must be free on BOTH helices
        if bp in steric_bps.get(curr_dom.helix_id, set()):
            continue
        if bp in steric_bps.get(next_dom.helix_id, set()):
            continue

        # Direction consistency — the scaffold must travel in the correct direction
        # through the current domain:
        #   FORWARD (5'→3' = increasing bp): exit_bp must be > entry_bp
        #   REVERSE (5'→3' = decreasing bp): exit_bp must be < entry_bp
        # This prevents 5'→5' or 3'→3' junctions at crossovers.
        if curr_dom.direction == Direction.FORWARD:
            if bp <= entry_for_curr:
                continue
        else:
            if bp >= entry_for_curr:
                continue

        # The next domain must have room to be traversed after entering at bp:
        #   FORWARD next: bp must be below the domain's high end (room to go up)
        #   REVERSE next: bp must be above the domain's low end (room to go down)
        if next_dom.direction == Direction.FORWARD:
            if bp >= next_dom.hi_bp:
                continue
        else:
            if bp <= next_dom.lo_bp:
                continue

        valid_next.append((xover, next_id))

    if not valid_next:
        backtracks[0] += 1
        if backtracks[0] > max_backtracks:
            return None
        return None

    # MCV: sort by number of forward options the next domain has
    def _mcv_key(item: tuple[CandidateXover, str]) -> int:
        _, nid = item
        next_cands = candidates_by_dom.get(nid, [])
        # Count valid extensions from next domain (rough estimate)
        return sum(
            1 for xov in next_cands
            if (xov.dom_a_id == nid and xov.dom_b_id not in visited)
            or (xov.dom_b_id == nid and xov.dom_a_id not in visited)
        )

    valid_next.sort(key=_mcv_key)

    for xover, next_id in valid_next:
        bp = xover.bp
        next_dom = domain_by_id[next_id]

        # Commit
        path.append(next_id)
        visited.add(next_id)
        xover_path.append(xover)
        steric_bps[curr_dom.helix_id].add(bp)
        steric_bps[next_dom.helix_id].add(bp)

        result = _csp_backtrack(
            path, xover.tag, visited, xover_path,
            steric_bps, domain_by_id, candidates_by_dom,
            n_domains, max_backtracks, backtracks,
        )
        if result is not None:
            return result

        if backtracks[0] > max_backtracks:
            # Undo and propagate timeout
            path.pop()
            visited.discard(next_id)
            xover_path.pop()
            steric_bps[curr_dom.helix_id].discard(bp)
            steric_bps[next_dom.helix_id].discard(bp)
            return None

        # Undo
        path.pop()
        visited.discard(next_id)
        xover_path.pop()
        steric_bps[curr_dom.helix_id].discard(bp)
        steric_bps[next_dom.helix_id].discard(bp)

    backtracks[0] += 1
    return None


def _solve_routing(
    domains: list[RouterDomain],
    candidates_by_dom: dict[str, list[CandidateXover]],
    fixed_xovers: set[tuple[str, str, int]],
    max_backtracks: int = 100_000,
) -> Optional[Routing]:
    """Run the CSP to find a valid scaffold routing.

    Tries each domain as a starting point, both seam-first and end-first.
    Returns the first valid Routing found, or None.

    NOTE: Does not implement bulge subroutine yet — handled separately in
    auto_scaffold() for designs with BCC bulge structure.
    """
    if not domains:
        return None

    domain_by_id = {d.id: d for d in domains}
    n = len(domains)

    # Special case: single domain, no crossovers needed
    if n == 1:
        return Routing(domains=domains, xovers=[], path_order=[domains[0].id])

    # Try each domain as start; try both alternation starting tags
    for start_dom in domains:
        for first_tag_hint in (None,):  # None = accept any first tag
            path: list[str] = [start_dom.id]
            visited: set[str] = {start_dom.id}
            xover_path: list[CandidateXover] = []
            steric_bps: dict[str, set[int]] = defaultdict(set)
            backtracks = [0]

            result = _csp_backtrack(
                path, first_tag_hint, visited, xover_path,
                steric_bps, domain_by_id, candidates_by_dom,
                n, max_backtracks, backtracks,
            )
            if result is not None:
                path_order, xovers = result
                return Routing(
                    domains=domains,
                    xovers=xovers,
                    path_order=path_order,
                )
            if backtracks[0] > max_backtracks:
                break  # timeout — try next start

    return None


# ── Bulge subroutine ───────────────────────────────────────────────────────────


def _route_bulge(
    bulge_helix_ids: set[str],
    gateway_helix_id: str,
    gateway_domain: RouterDomain,
    domains: list[RouterDomain],
    candidates_by_dom: dict[str, list[CandidateXover]],
    seam_tol: int,
    end_tol: int,
    depth: int = 0,
    max_depth: int = 10,
) -> Optional[tuple[list[str], list[CandidateXover], int, int]]:
    """Route a bulge sub-graph starting and ending on the gateway domain.

    The scaffold enters the bulge from the core helix X via a crossover to
    gateway helix A at position P, traverses the bulge recursively, and re-enters
    the core via the adjacent crossover at P+7 (or valid nearby position).

    Returns:
        (path_order, xovers, entry_bp, exit_bp) where entry/exit are the bp
        positions on the gateway domain used to enter/exit the bulge.

    NOTE: This is a simplified implementation. Full recursive bulge routing
    would need to handle nested bulges recursively (depth tracking provided).
    """
    if depth > max_depth:
        return None

    bulge_domains = [d for d in domains if d.helix_id in bulge_helix_ids]
    if not bulge_domains:
        return None

    bulge_candidates = {
        d.id: [
            x for x in candidates_by_dom.get(d.id, [])
            if x.dom_a_id in {bd.id for bd in bulge_domains} or
               x.dom_b_id in {bd.id for bd in bulge_domains}
        ]
        for d in bulge_domains
    }

    result = _solve_routing(
        bulge_domains, bulge_candidates, set(), max_backtracks=10_000
    )
    if result is None:
        return None

    # Find entry and exit crossovers (connections to gateway domain)
    gateway_id = gateway_domain.id
    entry_xover = next(
        (x for x in candidates_by_dom.get(gateway_id, [])
         if x.dom_a_id in {d.id for d in bulge_domains}
         or x.dom_b_id in {d.id for d in bulge_domains}),
        None,
    )
    if entry_xover is None:
        return None

    entry_bp = entry_xover.bp
    # Look for adjacent (P+7) exit bp on the gateway helix
    adj_bps = entry_bp + 7, entry_bp - 7
    exit_xover = None
    for bp_try in adj_bps:
        exit_xover = next(
            (x for x in candidates_by_dom.get(gateway_id, [])
             if x.bp == bp_try and x.id != entry_xover.id),
            None,
        )
        if exit_xover is not None:
            break

    if exit_xover is None:
        return None

    all_xovers = [entry_xover] + result.xovers + [exit_xover]
    return result.path_order, all_xovers, entry_bp, exit_xover.bp


# ── Path assembly — build NADOC strand objects from routing ───────────────────


def _domain_segment(
    router_dom: RouterDomain,
    entry_bp: Optional[int],
    exit_bp: Optional[int],
    end_tol: int = 5,
    seam_tol: int = 5,
) -> tuple[int, int]:
    """Return (start_bp, end_bp) for the scaffold segment on this domain.

    entry_bp: bp where scaffold enters (from previous crossover), or None if
              this is the path start (use domain's 5' end).
    exit_bp:  bp where scaffold exits (to next crossover), or None if this is
              the path end (use domain's 3' end).

    For half-domains two extensions are applied:
      - Physical-end extension: if the crossover nearest the physical helix end
        is within end_tol of it, extend the segment to the physical end (ssDNA
        scaffold loop).
      - Seam-boundary extension: if the crossover nearest the seam split is
        within seam_tol of the seam boundary, extend the segment to cover the
        full half-domain (ensures bp 0..seam or seam..hi are fully covered).
    """
    seg_start = entry_bp if entry_bp is not None else router_dom.five_prime_bp
    seg_end = exit_bp if exit_bp is not None else router_dom.three_prime_bp

    phys = router_dom.physical_end_bp
    if phys is not None:
        if phys == router_dom.five_prime_bp:
            # Physical end is the entry side; extend seg_start
            if entry_bp is not None and abs(entry_bp - phys) <= end_tol:
                seg_start = router_dom.five_prime_bp
        else:
            # Physical end is the exit side; extend seg_end
            if exit_bp is not None and abs(exit_bp - phys) <= end_tol:
                seg_end = router_dom.three_prime_bp

    seam = router_dom.seam_boundary_bp
    if seam is not None:
        if seam == router_dom.three_prime_bp:
            # Seam boundary is the exit side; extend seg_end to cover full half
            if exit_bp is not None and abs(exit_bp - seam) <= seam_tol:
                seg_end = router_dom.three_prime_bp
        else:
            # Seam boundary is the entry side (five_prime); extend seg_start
            if entry_bp is not None and abs(entry_bp - seam) <= seam_tol:
                seg_start = router_dom.five_prime_bp

    return seg_start, seg_end


def build_scaffold_strand(
    routing: Routing,
    domain_by_id: dict[str, RouterDomain],
    end_tol: int = 5,
    seam_tol: int = 5,
) -> Strand:
    """Construct a single NADOC Strand from a Routing result.

    Traverses path_order and builds Domain objects for each segment visited,
    connecting them via the chosen crossover bps.
    """
    path = routing.path_order
    xovers = routing.xovers  # xovers[i] connects path[i] to path[i+1]

    # Map (dom_id_a, dom_id_b) → xover bp for each path step
    xover_bps: list[int] = [x.bp for x in xovers]

    nadoc_domains: list[Domain] = []

    for i, dom_id in enumerate(path):
        dom = domain_by_id[dom_id]
        entry_bp = xover_bps[i - 1] if i > 0 else None
        exit_bp = xover_bps[i] if i < len(xovers) else None

        seg_start, seg_end = _domain_segment(dom, entry_bp, exit_bp, end_tol, seam_tol)

        nadoc_domains.append(
            Domain(
                helix_id=dom.helix_id,
                start_bp=seg_start,
                end_bp=seg_end,
                direction=dom.direction,
            )
        )

    return Strand(
        id=str(uuid.uuid4()),
        domains=nadoc_domains,
        strand_type=StrandType.SCAFFOLD,
    )


def _build_crossover_objects(
    routing: Routing,
    domain_by_id: dict[str, RouterDomain],
    scaffold_strand: Strand,
) -> list[Crossover]:
    """Build NADOC Crossover model objects from a Routing.

    Each CandidateXover in the routing becomes a Crossover record.
    The half_a/half_b strand directions are derived from the domain directions.
    """
    path = routing.path_order
    crossovers: list[Crossover] = []

    for i, xover in enumerate(routing.xovers):
        dom_a = domain_by_id[xover.dom_a_id]
        dom_b = domain_by_id[xover.dom_b_id]
        bp = xover.bp

        crossovers.append(
            Crossover(
                id=str(uuid.uuid4()),
                half_a=HalfCrossover(
                    helix_id=dom_a.helix_id,
                    index=bp,
                    strand=dom_a.direction,
                ),
                half_b=HalfCrossover(
                    helix_id=dom_b.helix_id,
                    index=bp,
                    strand=dom_b.direction,
                ),
            )
        )

    return crossovers


# ── Apply routing to design ────────────────────────────────────────────────────


def apply_routing_to_design(
    routing: Routing, design: Design, end_tol: int = 5, seam_tol: int = 5
) -> Design:
    """Atomically replace scaffold strands and crossovers in the design.

    All existing scaffold strands are removed and replaced with the new routed
    strand.  Non-scaffold strands (staples) are preserved.  Existing crossovers
    involving scaffold strands are replaced with the new routing's crossovers.

    ASSUMPTION: The new routing covers a subset of the helices.  Scaffold
    strands on helices not included in the routing are left untouched.
    """
    domain_by_id = {d.id: d for d in routing.domains}
    routed_helix_ids = {d.helix_id for d in routing.domains}

    new_scaffold = build_scaffold_strand(routing, domain_by_id, end_tol, seam_tol)
    new_xovers = _build_crossover_objects(routing, domain_by_id, new_scaffold)

    # Keep staple strands and scaffold strands on unrouted helices
    kept_strands: list[Strand] = []
    for s in design.strands:
        if s.strand_type == StrandType.STAPLE:
            kept_strands.append(s)
        elif s.strand_type == StrandType.SCAFFOLD:
            # Keep only if this scaffold strand is entirely on unrouted helices
            if all(d.helix_id not in routed_helix_ids for d in s.domains):
                kept_strands.append(s)

    kept_strands.append(new_scaffold)

    # Keep crossovers not involving routed helices, replace scaffold xovers
    kept_xovers: list[Crossover] = [
        x for x in design.crossovers
        if x.half_a.helix_id not in routed_helix_ids
        and x.half_b.helix_id not in routed_helix_ids
    ]
    kept_xovers.extend(new_xovers)

    return design.copy_with(strands=kept_strands, crossovers=kept_xovers)


def _manual_ligation_domain_ids(
    design: Design,
    domains: list[RouterDomain],
) -> set[str]:
    """Return router-domain IDs touched by manual scaffold forced ligations."""
    if not design.forced_ligations:
        return set()

    protected: set[str] = set()
    scaffold_slots = _scaffold_slots(design)
    for ligation in design.forced_ligations:
        endpoints = (
            (
                ligation.three_prime_helix_id,
                ligation.three_prime_bp,
                ligation.three_prime_direction,
            ),
            (
                ligation.five_prime_helix_id,
                ligation.five_prime_bp,
                ligation.five_prime_direction,
            ),
        )
        for helix_id, bp, direction in endpoints:
            if (helix_id, bp, direction) not in scaffold_slots:
                continue
            for dom in domains:
                if (
                    dom.helix_id == helix_id
                    and dom.direction == direction
                    and dom.lo_bp <= bp <= dom.hi_bp
                ):
                    protected.add(dom.id)
    return protected


def _strand_intervals_by_helix(strand: Strand) -> dict[str, list[tuple[int, int]]]:
    intervals: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for dom in strand.domains:
        intervals[dom.helix_id].append(tuple(sorted((dom.start_bp, dom.end_bp))))
    return dict(intervals)


def _intervals_overlap(
    a: dict[str, list[tuple[int, int]]],
    b: dict[str, list[tuple[int, int]]],
) -> bool:
    for helix_id, spans_a in a.items():
        spans_b = b.get(helix_id, [])
        for a_lo, a_hi in spans_a:
            for b_lo, b_hi in spans_b:
                if a_lo <= b_hi and b_lo <= a_hi:
                    return True
    return False


def _merge_interval_maps(
    target: dict[str, list[tuple[int, int]]],
    source: dict[str, list[tuple[int, int]]],
) -> dict[str, list[tuple[int, int]]]:
    merged = {helix_id: list(spans) for helix_id, spans in target.items()}
    for helix_id, spans in source.items():
        merged.setdefault(helix_id, []).extend(spans)
    out: dict[str, list[tuple[int, int]]] = {}
    for helix_id, spans in merged.items():
        spans = sorted(spans)
        helix_out: list[tuple[int, int]] = []
        for lo, hi in spans:
            if not helix_out or lo > helix_out[-1][1] + 1:
                helix_out.append((lo, hi))
            else:
                helix_out[-1] = (helix_out[-1][0], max(helix_out[-1][1], hi))
        out[helix_id] = helix_out
    return out


def _subtract_intervals(
    lo: int,
    hi: int,
    cuts: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    remaining = [(lo, hi)]
    for cut_lo, cut_hi in cuts:
        next_remaining: list[tuple[int, int]] = []
        for seg_lo, seg_hi in remaining:
            if cut_hi < seg_lo or cut_lo > seg_hi:
                next_remaining.append((seg_lo, seg_hi))
                continue
            if seg_lo < cut_lo:
                next_remaining.append((seg_lo, cut_lo - 1))
            if cut_hi < seg_hi:
                next_remaining.append((cut_hi + 1, seg_hi))
        remaining = next_remaining
    return remaining


def _preserve_unrouted_scaffold_fragments(
    design: Design,
    routed_intervals: dict[str, list[tuple[int, int]]],
) -> list[Strand]:
    """Keep original scaffold coverage outside intervals replaced by routing."""
    preserved: list[Strand] = []
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            preserved.append(strand)
            continue

        fragments: list[Domain] = []
        changed = False
        for dom in strand.domains:
            cuts = routed_intervals.get(dom.helix_id, [])
            if not cuts:
                fragments.append(dom)
                continue

            lo, hi = sorted((dom.start_bp, dom.end_bp))
            kept_spans = _subtract_intervals(lo, hi, cuts)
            if kept_spans != [(lo, hi)]:
                changed = True

            for kept_lo, kept_hi in kept_spans:
                if dom.direction == Direction.FORWARD:
                    start_bp, end_bp = kept_lo, kept_hi
                else:
                    start_bp, end_bp = kept_hi, kept_lo
                fragments.append(
                    Domain(
                        helix_id=dom.helix_id,
                        start_bp=start_bp,
                        end_bp=end_bp,
                        direction=dom.direction,
                        overhang_id=dom.overhang_id,
                    )
                )

        if not fragments:
            continue
        if not changed:
            preserved.append(strand)
        else:
            # Splitting a strand can invalidate sequence offsets, so leave
            # sequence unassigned for the preserved remainder.
            preserved.append(
                strand.model_copy(
                    update={
                        "id": str(uuid.uuid4()),
                        "domains": fragments,
                        "sequence": None,
                    }
                )
            )
    return preserved


def _scaffold_slots(design: Design) -> set[tuple[str, int, Direction]]:
    slots: set[tuple[str, int, Direction]] = set()
    for strand in design.strands:
        if strand.strand_type != StrandType.SCAFFOLD:
            continue
        for dom in strand.domains:
            slots.add((dom.helix_id, dom.start_bp, dom.direction))
            slots.add((dom.helix_id, dom.end_bp, dom.direction))
    return slots


def _is_scaffold_crossover(
    xover: Crossover,
    scaffold_slots: set[tuple[str, int, Direction]],
) -> bool:
    return (
        (xover.half_a.helix_id, xover.half_a.index, xover.half_a.strand)
        in scaffold_slots
        or (xover.half_b.helix_id, xover.half_b.index, xover.half_b.strand)
        in scaffold_slots
    )


def _bp_in_routed_intervals(
    helix_id: str,
    bp: int,
    routed_intervals: dict[str, list[tuple[int, int]]],
) -> bool:
    return any(lo <= bp <= hi for lo, hi in routed_intervals.get(helix_id, []))


# ── Top-level entry point ─────────────────────────────────────────────────────


def auto_scaffold(
    design: Design,
    seam_tol: int = 5,
    end_tol: int = 5,
    preserve_manual: bool = True,
    max_backtracks: int = 100_000,
    min_split_length: int = 42,
) -> tuple[Design, ValidationResult]:
    """Route scaffold through all helices and return (updated_design, validation).

    Algorithm:
      1. Extract router domains from existing scaffold strands.
      2. Build candidate crossover graph.
      3. Validate (V1–V8); return early if hard errors.
      4. BCC decompose: route core, then recurse into bulges.
      5. CSP search for Hamiltonian path with alternation.
      6. Apply routing atomically.

    Returns the original design unchanged if routing fails.

    NOTE: Bulge routing is currently a best-effort stub.  Core routing is
    full CSP.  Disconnected components are routed independently with a warning.
    """
    domains, domain_by_id = extract_router_domains(design, min_split_length)
    candidates_by_dom = build_candidate_graph(domains, design, seam_tol, end_tol)
    validation = validate_routing(design, domains, candidates_by_dom)

    if not validation.valid:
        return design, validation

    if len(domains) == 1:
        # Nothing to connect.  Preserve the user's existing scaffold strand
        # verbatim instead of replacing it with a new UUID/domain object.
        return design, validation

    # Decompose into connected components and route each
    G: nx.Graph = nx.Graph()
    for dom in domains:
        G.add_node(dom.id)
    seen: set[str] = set()
    for xovers in candidates_by_dom.values():
        for xover in xovers:
            if xover.id not in seen:
                seen.add(xover.id)
                G.add_edge(xover.dom_a_id, xover.dom_b_id)

    components = list(nx.connected_components(G))
    # Also add isolated domains as their own component
    for dom in domains:
        if not any(dom.id in c for c in components):
            components.append({dom.id})

    fixed_xovers = _existing_scaffold_xover_set(design) if preserve_manual else set()
    protected_domain_ids = (
        _manual_ligation_domain_ids(design, domains) if preserve_manual else set()
    )

    routing_candidates: list[Routing] = []
    unrouted_warnings: list[str] = []

    for component in components:
        comp_domains = [d for d in domains if d.id in component]
        comp_candidates = {
            did: xovers
            for did, xovers in candidates_by_dom.items()
            if did in component
        }

        protected_in_component = protected_domain_ids & set(component)
        if protected_in_component:
            unrouted_warnings.append(
                f"Routing incomplete due to manual scaffold connection(s) in "
                f"component of {len(comp_domains)} domain(s) — preserving unchanged."
            )
            continue

        if len(comp_domains) == 1:
            unrouted_warnings.append(
                "Isolated scaffold domain with no crossover candidates — preserving unchanged."
            )
            continue

        result = _solve_routing(
            comp_domains, comp_candidates, fixed_xovers, max_backtracks
        )
        if result is None:
            unrouted_warnings.append(
                f"CSP timeout or no solution for component of "
                f"{len(comp_domains)} domain(s) — skipping."
            )
        else:
            routing_candidates.append(result)

    if unrouted_warnings:
        validation.warnings.extend(unrouted_warnings)

    if not routing_candidates:
        validation.errors.append("No components could be routed.")
        validation.valid = False
        return design, validation

    # Build all new scaffold strands from the ORIGINAL design before any apply.
    # Sequential apply_routing_to_design would destroy earlier routings when later
    # components share helix IDs (e.g. L-half routing covers h1, then R-half routing
    # also covers h1 and wipes out the L-half strand).  Atomic apply avoids this.
    all_new_scaffolds: list[Strand] = []
    all_new_xovers: list[Crossover] = []
    routed_intervals: dict[str, list[tuple[int, int]]] = {}

    for routing in routing_candidates:
        domain_by_id = {d.id: d for d in routing.domains}
        new_scaffold = build_scaffold_strand(routing, domain_by_id, end_tol, seam_tol)
        new_intervals = _strand_intervals_by_helix(new_scaffold)
        if _intervals_overlap(new_intervals, routed_intervals):
            validation.warnings.append(
                f"Routing incomplete because component of {len(routing.domains)} "
                "domain(s) overlaps an already routed scaffold segment — preserving unchanged."
            )
            continue
        new_xovers_for_routing = _build_crossover_objects(routing, domain_by_id, new_scaffold)
        all_new_scaffolds.append(new_scaffold)
        all_new_xovers.extend(new_xovers_for_routing)
        routed_intervals = _merge_interval_maps(routed_intervals, new_intervals)

    if not all_new_scaffolds:
        validation.errors.append("No components could be routed.")
        validation.valid = False
        return design, validation

    kept_strands = _preserve_unrouted_scaffold_fragments(design, routed_intervals)
    kept_strands.extend(all_new_scaffolds)

    scaffold_slots = _scaffold_slots(design)
    kept_xovers: list[Crossover] = []
    for xover in design.crossovers:
        if not _is_scaffold_crossover(xover, scaffold_slots):
            kept_xovers.append(xover)
            continue
        if (
            _bp_in_routed_intervals(xover.half_a.helix_id, xover.half_a.index, routed_intervals)
            or _bp_in_routed_intervals(xover.half_b.helix_id, xover.half_b.index, routed_intervals)
        ):
            continue
        kept_xovers.append(xover)
    kept_xovers.extend(all_new_xovers)

    updated = design.copy_with(strands=kept_strands, crossovers=kept_xovers)
    return updated, validation
