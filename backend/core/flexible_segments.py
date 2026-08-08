"""Flexible ssDNA segments — derivation + inter-cluster gate.

Layer-3 / display only. NEVER mutates topology (strands/domains/crossovers).

The user marks contiguous runs of UNPAIRED beads as flexible. Each marked run
that bridges two EXISTING rigid clusters becomes a ``FlexibleConnection`` (a
fixed-contour-length tether). The rigid arms are the user's own clusters — there
is NO auto-cut and NO new clusters. A flexible run does not need its own helix:
mid-helix unpaired runs are fully supported (the run's beads are a per-bead
display overlay, excluded from rigid rendering and drawn on an arc instead).

This replaces the earlier auto-cut "ball joint" approach.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from backend.core.constants import SSDNA_RISE_PER_BASE_NM
from backend.core.models import (
    Design,
    Direction,
    FlexibleAnchor,
    FlexibleConnection,
)


def _domain_bead_bps(domain) -> range:
    """bp indices of a domain's beads in 5'→3' order (start_bp is 5')."""
    step = 1 if domain.end_bp >= domain.start_bp else -1
    return range(domain.start_bp, domain.end_bp + step, step)


def unpaired_bead_keys(design: Design) -> set[tuple[str, int, Direction]]:
    """Set of (helix_id, bp, direction) beads with NO Watson-Crick partner.

    A bead is single-stranded (ssDNA) iff the opposite-direction slot at the same
    (helix_id, bp) is unoccupied. Broader than ``overhang_id`` — catches unpaired
    scaffold runs at a hinge (the mini_hinge tethers).
    """
    occupied: set[tuple[str, int, Direction]] = set()
    for s in design.strands:
        for d in s.domains:
            for bp in _domain_bead_bps(d):
                occupied.add((d.helix_id, bp, d.direction))
    unpaired = set()
    for h, bp, dr in occupied:
        other = Direction.REVERSE if dr == Direction.FORWARD else Direction.FORWARD
        if (h, bp, other) not in occupied:
            unpaired.add((h, bp, dr))
    return unpaired


def _build_bead_graph(design: Design):
    """Return (adj, bead_domain).

    adj: bead_key -> set of neighbour bead_keys (backbone + forced-ligation +
    crossover edges — the realized rigid connectivity). bead_key = (helix_id, bp,
    Direction). bead_domain: bead_key -> (strand_id, domain_index).
    """
    adj: dict[tuple, set] = defaultdict(set)
    bead_domain: dict[tuple, tuple[str, int]] = {}

    for s in design.strands:
        seq: list[tuple] = []
        for di, d in enumerate(s.domains):
            for bp in _domain_bead_bps(d):
                key = (d.helix_id, bp, d.direction)
                bead_domain[key] = (s.id, di)
                seq.append(key)
        for a, b in zip(seq, seq[1:]):
            adj[a].add(b)
            adj[b].add(a)

    for fl in design.forced_ligations:
        a = (fl.three_prime_helix_id, fl.three_prime_bp, fl.three_prime_direction)
        b = (fl.five_prime_helix_id, fl.five_prime_bp, fl.five_prime_direction)
        if a in bead_domain and b in bead_domain:
            adj[a].add(b)
            adj[b].add(a)

    for xo in design.crossovers:
        a = (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
        b = (xo.half_b.helix_id, xo.half_b.index, xo.half_b.strand)
        if a in bead_domain and b in bead_domain:
            adj[a].add(b)
            adj[b].add(a)

    return adj, bead_domain


def _owning_cluster_id(design: Design, bead_key, sd) -> str | None:
    """Which existing cluster owns this bead. Prefers a domain-level match over a
    helix-level one, a non-default cluster over the default catch-all, and — when a
    helix belongs to several overlapping clusters — the MORE SPECIFIC (fewer-helix)
    one.

    The specificity tie-break matters for imported / auto-detected designs, where a
    large scaffold-spanning cluster overlaps the smaller geometry clusters that are
    the real rigid arms. Without it, both ends of a flexible run collapse onto the
    shared spanning cluster (first in the list wins the tie) → no inter-cluster
    bridge → no connection → the run's beads are excluded from rigid rendering with
    nothing drawn in their place ("marked segment disappears"). Preferring the
    smaller cluster resolves each end to its own geometry arm so a tether forms.
    """
    helix = bead_key[0]
    best = None
    best_key: tuple[int, int] | None = None  # (score, -helix_count); higher wins
    for c in design.cluster_transforms:
        score = -1
        if c.domain_ids:
            if sd is not None and any(
                dr.strand_id == sd[0] and dr.domain_index == sd[1]
                for dr in c.domain_ids
            ):
                score = 2
        elif helix in c.helix_ids:
            score = 1
        if score < 0:
            continue
        if c.is_default:
            score = 0
        # Among equal-score matches, prefer the cluster with the fewest helices
        # (the most specific rigid body) over a broad spanning cluster.
        key = (score, -len(c.helix_ids))
        if best_key is None or key > best_key:
            best_key, best = key, c.id
    return best


def _owner_fn(design: Design, bead_domain):
    cache: dict[tuple, str | None] = {}

    def owner(k):
        if k in cache:
            return cache[k]
        o = _owning_cluster_id(design, k, bead_domain.get(k))
        cache[k] = o
        return o

    return owner


def _marked_bead_keys(design: Design, bead_domain) -> set[tuple]:
    """Resolve flexible_segment_marks → live bead keys (helix, bp, direction)."""
    strands_by_id = {s.id: s for s in design.strands}
    marked: set[tuple] = set()
    for m in design.flexible_segment_marks:
        s = strands_by_id.get(m.strand_id)
        if s is None or m.domain_index >= len(s.domains):
            continue
        d = s.domains[m.domain_index]
        lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
        if not (lo <= m.bp_index <= hi):
            continue
        key = (d.helix_id, m.bp_index, d.direction)
        if key in bead_domain:
            marked.add(key)
    return marked


def _anchor(key, bead_domain) -> FlexibleAnchor:
    sd = bead_domain[key]
    return FlexibleAnchor(
        strand_id=sd[0], domain_index=sd[1], bp_index=key[1], direction=key[2]
    )


def _order_component(comp: list, adj: dict, start) -> list:
    """Order a marked component as a path starting from the bead nearest `start`."""
    compset = set(comp)
    # seed = the comp bead adjacent to `start` if any, else comp[0].
    seed = next((b for b in comp if start in adj[b]), comp[0])
    order, seen, q = [], {seed}, [seed]
    while q:
        cur = q.pop(0)
        order.append(cur)
        for nb in adj[cur]:
            if nb in compset and nb not in seen:
                seen.add(nb)
                q.append(nb)
    return order


def derive_flexible_connections(design: Design) -> list[FlexibleConnection]:
    """Marked unpaired runs that bridge two EXISTING clusters → connections.

    A marked run whose rigid neighbours all belong to one cluster (an in-cluster
    ssDNA loop / end overhang) yields no connection.
    """
    if not design.flexible_segment_marks:
        return []
    adj, bead_domain = _build_bead_graph(design)
    marked = _marked_bead_keys(design, bead_domain)
    if not marked:
        return []
    owner = _owner_fn(design, bead_domain)

    conns: list[FlexibleConnection] = []
    seen: set[tuple] = set()
    for start in marked:
        if start in seen:
            continue
        # Marked component = maximal set of marked beads connected through marked beads.
        comp: list[tuple] = []
        q = [start]
        seen.add(start)
        while q:
            cur = q.pop()
            comp.append(cur)
            for nb in adj[cur]:
                if nb in marked and nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        # Rigid neighbours of the component, grouped by owning cluster (first bead each).
        rigid_nb: dict[str, tuple] = {}
        for b in comp:
            for nb in adj[b]:
                if nb in marked:
                    continue
                cl = owner(nb)
                if cl is not None and cl not in rigid_nb:
                    rigid_nb[cl] = nb
        if len(rigid_nb) < 2:
            continue  # in-cluster ssDNA (e.g. end overhang) — not a tether
        (ca, ba), (cb, bb) = list(rigid_nb.items())[:2]
        ordered = _order_component(comp, adj, ba)
        sig = ";".join(sorted(f"{k[0]}:{k[1]}:{k[2].value}" for k in comp))
        conns.append(
            FlexibleConnection(
                id="flx_" + hashlib.sha1(sig.encode()).hexdigest()[:12],
                cluster_a_id=ca,
                cluster_b_id=cb,
                anchor_a=_anchor(ba, bead_domain),
                anchor_b=_anchor(bb, bead_domain),
                n_ss_bases=len(comp),
                contour_length_nm=len(comp) * SSDNA_RISE_PER_BASE_NM,
                segment_bead_keys=[_anchor(k, bead_domain) for k in ordered],
            )
        )
    return conns


def _gate(cluster_id, adj, bead_domain, marked, owner, duplex_ids=frozenset()) -> dict:
    crossings = 0
    rigid_blocking: list[dict] = []
    seen_edges: set = set()
    for u in adj:
        if owner(u) != cluster_id:
            continue
        for v in adj[u]:
            ov = owner(v)
            if ov is None or ov == cluster_id:
                continue
            # An overhang-DUPLEX child cluster is a movable connector that rides with its
            # parts (it has its own free-until-taut "Constrained (taut bonds)" mode), NOT a
            # rigid pin. Treat it as transparent to the ssDNA gate — skip the overhang-junction
            # crossing entirely so materializing a duplex doesn't disable a parent cluster's
            # "ssDNA constrained" option. (Before duplex clusters existed, these overhang beads
            # belonged to the parent and the junction was intra-cluster.)
            if ov in duplex_ids or cluster_id in duplex_ids:
                continue
            ekey = frozenset((u, v))
            if ekey in seen_edges:
                continue
            seen_edges.add(ekey)
            crossings += 1
            if not (u in marked or v in marked):
                # Direct rigid bond between the two clusters — blocks free motion.
                rigid_blocking.append(
                    {
                        "a": _anchor(u, bead_domain).model_dump(),
                        "b": _anchor(v, bead_domain).model_dump(),
                    }
                )
    return {
        "cluster_id": cluster_id,
        "gate": crossings > 0 and not rigid_blocking,
        "n_crossings": crossings,
        "rigid_blocking": rigid_blocking,
    }


def _duplex_cluster_ids(design: Design) -> frozenset:
    """Cluster ids that are overhang-duplex children (movable connectors, not rigid pins)."""
    return frozenset(
        c.id for c in design.cluster_transforms if c.overhang_duplex_driver_id
    )


def cluster_flexible_gate(design: Design, cluster_id: str) -> dict:
    """Is the move/rotate 'ssDNA constrained' mode available for this cluster?

    True iff it has ≥1 inter-cluster connection and EVERY inter-cluster crossing
    passes through a marked flexible segment (no direct rigid bond to another
    cluster).
    """
    adj, bead_domain = _build_bead_graph(design)
    marked = _marked_bead_keys(design, bead_domain)
    owner = _owner_fn(design, bead_domain)
    return _gate(
        cluster_id, adj, bead_domain, marked, owner, _duplex_cluster_ids(design)
    )


def all_cluster_gates(design: Design) -> dict[str, dict]:
    """Gate result for every cluster (single graph build)."""
    adj, bead_domain = _build_bead_graph(design)
    marked = _marked_bead_keys(design, bead_domain)
    owner = _owner_fn(design, bead_domain)
    duplex_ids = _duplex_cluster_ids(design)
    return {
        c.id: _gate(c.id, adj, bead_domain, marked, owner, duplex_ids)
        for c in design.cluster_transforms
    }


def apply_marks(design: Design) -> Design:
    """Return a copy with ``flexible_connections`` recomputed from the marks.

    Never mutates clusters or topology — only the derived connection list.
    """
    return design.copy_with(flexible_connections=derive_flexible_connections(design))
