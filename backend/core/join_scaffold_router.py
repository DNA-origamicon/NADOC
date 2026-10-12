"""Route around authored Join bonds instead of freezing their entire strands.

A directed backbone graph preserves every original nucleotide and forced bond.
Lattice end turns may extend into ssDNA; interior crossovers are reciprocal seams.
A bounded integer solve chooses one connected path, with cuts excluding detached
cycles. No partial route is accepted or written back to the document.
"""

from collections import defaultdict
import time

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

from backend.core.models import Crossover, Direction, Domain, HalfCrossover
from backend.core.sequences import domain_bp_range
from backend.core.topology_integrity import forced_edge, slot
from backend.core.scaffold_safety import RoutingIntegrityError


def _route_component(design, result_type, *, seams=True):
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
    from backend.core.crossover_positions import (
        crossover_allowed,
        scaffold_seam_positions,
    )
    from backend.core.flexible_segments import derive_flexible_connections
    from backend.core.models import LatticeType
    from backend.core.scaffold_invariants import (
        _staple_coverage,
        _staple_clearance,
        scaffold_routing_invariants,
    )
    from backend.core.scaffold_reset import _set_helix_extent
    from backend.core.seamed_router import (
        _scaf_nb,
        _nick_bp,
        _HC_SCAF_BOW_RIGHT,
        _SQ_SCAF_BOW_RIGHT,
    )
    from backend.core.topology_integrity import junction_errors

    scaffolds = [s for s in design.scaffolds() if not s.is_reference]
    originals = {
        slot(d.helix_id, bp, d.direction): d
        for s in scaffolds
        for d in s.domains
        for bp in domain_bp_range(d)
    }
    fixed = {
        forced_edge(fl)
        for fl in design.forced_ligations
        if forced_edge(fl)[0] in originals
    }
    if not any(a[0].startswith("join_") or b[0].startswith("join_") for a, b in fixed):
        return None
    if any(a not in originals or b not in originals for a, b in fixed):
        raise RoutingIntegrityError("A Join bond is missing its scaffold attachment.")
    if (
        len(scaffolds) == 1
        and not scaffolds[0].routing_seed
        and any(xo.process_id == "auto_scaffold_join" for xo in design.crossovers)
        and (seams or not scaffold_seam_positions(design))
        and not junction_errors(design)
        and not scaffold_routing_invariants(design, require_seams=seams)
    ):
        return design, result_type(
            warnings=[
                "Existing joined scaffold route is complete; all Join bonds retained."
            ]
        )
    honeycomb = design.lattice_type == LatticeType.HONEYCOMB
    period = HC_CROSSOVER_PERIOD if honeycomb else SQ_CROSSOVER_PERIOD
    bow = _HC_SCAF_BOW_RIGHT if honeycomb else _SQ_SCAF_BOW_RIGHT
    staples = _staple_coverage(design)
    helices = {h.id: h for h in design.helices}
    owner = {}
    for c in sorted(
        design.cluster_transforms, key=lambda c: (-len(c.helix_ids), not c.is_default)
    ):
        for hid in c.helix_ids:
            owner[hid] = c.id
    ranges = defaultdict(list)
    for key in originals:
        ranges[key[0], key[2]].append(key[1])
    nodes = dict(originals)
    # At most one local crossover period of end extension. Disconnected sections
    # and authored connector helices are never filled or extended.
    for (hid, direction), bps in ranges.items():
        if helices[hid].grid_pos is None:
            continue
        lo, hi = min(bps), max(bps)
        for bp in [*range(lo - period - 3, lo), *range(hi + 1, hi + period + 4)]:
            nodes[hid, bp, direction] = Domain(
                helix_id=hid, start_bp=bp, end_bp=bp, direction=direction
            )
    edges, costs, junctions, edge_index = [], [], {}, {}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    fixed_out = {a: b for a, b in fixed}
    fixed_in = {b: a for a, b in fixed}

    if len(fixed_out) != len(fixed) or len(fixed_in) != len(fixed):
        raise RoutingIntegrityError(
            "Conflicting authored scaffold bonds cannot be routed."
        )

    def edge(a, b, cost=0, xo=None):
        if (
            a not in nodes
            or b not in nodes
            or fixed_out.get(a, b) != b
            or fixed_in.get(b, a) != a
        ):
            return None
        if (a, b) in edge_index:
            return edge_index[a, b]
        i = len(edges)
        edge_index[a, b] = i
        edges.append((a, b))
        costs.append(cost + (a not in originals) + (b not in originals))
        outgoing[a].append(i)
        incoming[b].append(i)
        if xo is not None:
            junctions[i] = xo
        return i

    for a in nodes:
        edge(a, (a[0], a[1] + (1 if a[2] == "FORWARD" else -1), a[2]))
    fixed_indices = [edge(a, b) for a, b in sorted(fixed)]
    pairs = {}
    grid = defaultdict(list)
    for hid, direction in ranges:
        h = helices[hid]
        if h.grid_pos is not None:
            grid[owner.get(hid), h.lattice_frame_id, tuple(h.grid_pos)].append(
                (hid, direction)
            )
    for a in nodes:
        h = helices[a[0]]
        if h.grid_pos is None or _nick_bp(a[1], Direction(a[2]), period, bow) != a[1]:
            continue
        nb = _scaf_nb(design, *h.grid_pos, a[1])
        for hid, direction in grid.get((owner.get(h.id), h.lattice_frame_id, nb), []):
            b = (hid, a[1], direction)
            if direction == a[2] or not crossover_allowed(design, a[0], b[0], a[1]):
                continue
            clear = all(
                _staple_clearance(k[1], staples.get(k[0], [])) >= 3 for k in (a, b)
            )
            if not clear and not seams:
                continue
            xo = Crossover(
                half_a=HalfCrossover(helix_id=a[0], index=a[1], strand=a[2]),
                half_b=HalfCrossover(helix_id=b[0], index=b[1], strand=b[2]),
                process_id="auto_scaffold_join",
            )
            i = edge(a, b, 10, xo)
            if i is not None:
                pairs[a[0], b[0], a[1]] = (i, clear)
    rows, lower, upper = [], [], []

    def constraint(coeff, lo, hi):
        rows.append(coeff)
        lower.append(lo)
        upper.append(hi)

    # Choose a buried nick on an ordinary backbone bond away from fixed anchors.
    nick = next(
        (
            (a, b)
            for a, b in edges
            if a in originals
            and b in originals
            and a[0] == b[0]
            and helices[a[0]].grid_pos is not None
            and a not in fixed_out
            and b not in fixed_in
            and a[1] == (min(ranges[a[0], a[2]]) + max(ranges[a[0], a[2]])) // 2
        ),
        None,
    )
    if nick is None:
        raise RoutingIntegrityError(
            "No ordinary scaffold bond is available for a routing nick."
        )
    tail, head = nick
    for node in nodes:
        ins, outs = incoming[node], outgoing[node]
        if node in originals:
            constraint(dict.fromkeys(ins, 1), int(node != head), int(node != head))
            constraint(dict.fromkeys(outs, 1), int(node != tail), int(node != tail))
        else:
            constraint({**dict.fromkeys(ins, 1), **dict.fromkeys(outs, -1)}, 0, 0)
            constraint(dict.fromkeys(ins, 1), 0, 1)
    for i in fixed_indices:
        constraint({i: 1}, 1, 1)
    seam_indices = []
    for (a, b, bp), (i, clear) in pairs.items():
        if not seams:
            # Seamless mode must not create reciprocal double crossovers even
            # in the unpaired end extensions.
            for adjacent in (bp - 1, bp + 1):
                partner = pairs.get((b, a, adjacent))
                if partner is not None:
                    constraint({i: 1, partner[0]: 1}, 0, 1)
        if clear:
            continue
        partner_bp = bp + (-1 if bp % period in bow else 1)
        partner = pairs.get((b, a, partner_bp))
        if partner is None:
            constraint({i: 1}, 0, 0)
        else:
            constraint({i: 1, partner[0]: -1}, 0, 0)
            seam_indices.append(i)
    if seams:
        constraint(dict.fromkeys(seam_indices, 1), 2, np.inf)
    deadline = time.monotonic() + 30
    while True:
        rr, cc, vv = [], [], []
        for r, row in enumerate(rows):
            for c, v in row.items():
                rr.append(r)
                cc.append(c)
                vv.append(v)
        matrix = coo_matrix((vv, (rr, cc)), shape=(len(rows), len(edges))).tocsc()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RoutingIntegrityError(
                "No complete route preserving every Join bond was found within 30 seconds."
            )
        solution = milp(
            np.array(costs, dtype=float),
            integrality=np.ones(len(edges)),
            bounds=Bounds(0, 1),
            constraints=LinearConstraint(matrix, lower, upper),
            options={"time_limit": remaining, "mip_rel_gap": 0.5},
        )
        if solution.x is None:
            raise RoutingIntegrityError(
                "No complete scaffold route preserving every Join bond was found."
            )
        selected = {i for i, value in enumerate(solution.x) if value > 0.5}
        successor = {edges[i][0]: edges[i][1] for i in selected}
        path, visited, node = [], set(), head
        while node is not None and node not in visited:
            path.append(node)
            visited.add(node)
            node = successor.get(node)
        if node is not None or path[-1] != tail:
            raise RoutingIntegrityError(
                "Joined scaffold routing produced an invalid open path."
            )
        unseen = set(successor) - visited
        if not unseen:
            break
        while unseen:
            cycle, node = set(), min(unseen)
            while node not in cycle:
                cycle.add(node)
                node = successor[node]
            unseen -= cycle
            # Mandatory-base cycles must connect to the route. Optional-only cycles
            # may instead disappear in the next solve.
            if cycle & originals.keys():
                constraint(
                    {
                        i: 1
                        for a in cycle
                        for i in outgoing[a]
                        if edges[i][1] not in cycle
                    },
                    1,
                    np.inf,
                )
            else:
                constraint(
                    {i: 1 for i in selected if edges[i][0] in cycle}, 0, len(cycle) - 1
                )
    if not originals.keys() <= visited:
        raise RoutingIntegrityError(
            "Joined routing omitted original scaffold nucleotides."
        )
    domains, locations = [], {}
    for key in path:
        dm = nodes[key]
        previous = domains[-1] if domains else None
        if (
            previous
            and previous.helix_id == key[0]
            and previous.direction.value == key[2]
            and previous.overhang_id == dm.overhang_id
            and previous.binds_overhang_id == dm.binds_overhang_id
            and previous.end_bp + (1 if key[2] == "FORWARD" else -1) == key[1]
        ):
            previous.end_bp = key[1]
        else:
            domains.append(
                dm.model_copy(update={"start_bp": key[1], "end_bp": key[1]}, deep=True)
            )
        locations[key] = len(domains) - 1
    strand = scaffolds[0].model_copy(
        update={
            "domains": domains,
            "routing_seed": [],
            "sequence": None,
            "custom_scaffold_length": None,
        },
        deep=True,
    )
    marks = []
    strands_by_id = {s.id: s for s in scaffolds}
    for mark in design.flexible_segment_marks:
        if mark.strand_id in strands_by_id:
            dm = strands_by_id[mark.strand_id].domains[mark.domain_index]
            mark = mark.model_copy(
                update={
                    "strand_id": strand.id,
                    "domain_index": locations[
                        slot(dm.helix_id, mark.bp_index, dm.direction)
                    ],
                }
            )
        marks.append(mark)
    extents = defaultdict(list)
    for hid, bp, _ in path:
        extents[hid].append(bp)
    out = design.copy_with(
        strands=[s for s in design.strands if not s.is_scaffold or s.is_reference]
        + [strand],
        helices=[
            _set_helix_extent(
                h,
                min(h.bp_start, min(extents[h.id])),
                max(h.bp_start + h.length_bp - 1, max(extents[h.id])),
            )
            if h.id in extents
            else h
            for h in design.helices
        ],
        crossovers=[
            xo
            for xo in design.crossovers
            if slot(xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand)
            not in originals
        ]
        + [junctions[i] for i in sorted(selected) if i in junctions],
        flexible_segment_marks=marks,
    )
    out.flexible_connections = derive_flexible_connections(out)
    errors = junction_errors(out) + scaffold_routing_invariants(
        out, require_seams=seams
    )
    if errors:
        raise RoutingIntegrityError("; ".join(errors[:3]))
    result = result_type(
        warnings=[
            f"Routed one scaffold preserving all {len(fixed)} authored Join/ligation bonds."
        ]
    )
    if hasattr(result, "seam_xovers"):
        result.seam_xovers = sum(i in selected for i in seam_indices)
        for i in selected & junctions.keys():
            if i in seam_indices:
                continue
            a, b = edges[i]
            if a[1] < min(ranges[a[0], a[2]]):
                result.near_end_xovers += 1
            else:
                result.far_end_xovers += 1
    if hasattr(result, "end_xovers"):
        result.end_xovers = len(selected & junctions.keys())
    return out, result


def route_joined_scaffold(design, result_type, runner, *, seams=True):
    """Route joined components atomically; unrelated components use the normal router."""
    from backend.core.crossover_positions import crossover_neighbor
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
    from backend.core.models import LatticeType

    if not any(
        fl.three_prime_helix_id.startswith("join_")
        or fl.five_prime_helix_id.startswith("join_")
        for fl in design.forced_ligations
    ):
        return None
    if any(c.domain_ids for c in design.cluster_transforms):
        raise RoutingIntegrityError(
            "Join routing currently requires whole-helix clusters; domain-level cluster membership was retained unchanged."
        )
    parent = {h.id: h.id for h in design.helices}

    def root(hid):
        while parent[hid] != hid:
            parent[hid] = parent[parent[hid]]
            hid = parent[hid]
        return hid

    def union(a, b):
        if a in parent and b in parent:
            parent[root(a)] = root(b)

    # Existing strands and authored bonds must stay together. Lattice routing
    # can add edges only within the same rigid cluster and lattice frame.
    for s in design.strands:
        for a, b in zip(s.domains, s.domains[1:]):
            union(a.helix_id, b.helix_id)
    for fl in design.forced_ligations:
        union(fl.three_prime_helix_id, fl.five_prime_helix_id)
    owner = {}
    for c in sorted(
        design.cluster_transforms, key=lambda c: (-len(c.helix_ids), not c.is_default)
    ):
        owner.update(dict.fromkeys(c.helix_ids, c.id))
    grid = defaultdict(list)
    for h in design.helices:
        if h.grid_pos is not None:
            grid[owner.get(h.id), h.lattice_frame_id, tuple(h.grid_pos)].append(h.id)
    period = (
        HC_CROSSOVER_PERIOD
        if design.lattice_type == LatticeType.HONEYCOMB
        else SQ_CROSSOVER_PERIOD
    )
    for h in design.helices:
        if h.grid_pos is None:
            continue
        for bp in range(period):
            nb = crossover_neighbor(
                design.lattice_type, *h.grid_pos, bp, is_scaffold=True
            )
            for hid in grid.get((owner.get(h.id), h.lattice_frame_id, nb), []):
                union(h.id, hid)
    groups = defaultdict(set)
    for hid in parent:
        groups[root(hid)].add(hid)
    if len(groups) == 1:
        return _route_component(design, result_type, seams=seams)
    outputs, result = [], result_type()
    for ids in groups.values():
        strand_ids = {
            s.id for s in design.strands if s.domains and s.domains[0].helix_id in ids
        }
        sub = design.copy_with(
            helices=[h for h in design.helices if h.id in ids],
            strands=[s for s in design.strands if s.id in strand_ids],
            crossovers=[x for x in design.crossovers if x.half_a.helix_id in ids],
            forced_ligations=[
                fl for fl in design.forced_ligations if fl.three_prime_helix_id in ids
            ],
            flexible_segment_marks=[
                m for m in design.flexible_segment_marks if m.strand_id in strand_ids
            ],
        )
        if not any(not s.is_reference for s in sub.scaffolds()):
            outputs.append(sub)
            continue
        routed = _route_component(sub, result_type, seams=seams)
        out, info = routed if routed is not None else runner(sub)
        if not info.valid:
            raise RoutingIntegrityError("; ".join(info.errors))
        outputs.append(out)
        result.warnings.extend(info.warnings)
        for attr in (
            "seam_xovers",
            "near_end_xovers",
            "far_end_xovers",
            "end_xovers",
            "bridge_xovers",
        ):
            if hasattr(result, attr):
                setattr(result, attr, getattr(result, attr) + getattr(info, attr))
    from backend.core.flexible_segments import derive_flexible_connections

    out = design.copy_with(
        **{
            attr: [item for d in outputs for item in getattr(d, attr)]
            for attr in (
                "helices",
                "strands",
                "crossovers",
                "forced_ligations",
                "flexible_segment_marks",
            )
        }
    )
    out.flexible_connections = derive_flexible_connections(out)
    return out, result
