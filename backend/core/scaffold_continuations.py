"""Route connected helix segments through a temporary continuous-track view.

The saved helix IDs, lattice frames and deformations remain authoritative. Only
the routing problem is contracted: an authored longitudinal backbone connection
is internal to a track, never an end at which to extend or turn the scaffold.
"""

from __future__ import annotations

from backend.core.backbone_continuations import backbone_continuation_edges
from backend.core.models import Direction


def route_continuations(design, runner, *, close_cycle=True):
    """Return a routed design, or None when there are no segment continuations.

    Explicit forced-ligation records on these edges are retained verbatim. Their
    contraction is only a solver representation, not deletion of authored bonds.
    Other forced ligations remain constraints for the underlying router.
    """
    from backend.core.scaffold_reset import _set_helix_extent
    from backend.core.scaffold_safety import RoutingIntegrityError, _has_backbone_edge
    from backend.core.topology_integrity import forced_edge, junction_errors, slot

    edges = backbone_continuation_edges(design)
    scaffold_edges = {
        (slot(a.helix_id, a.end_bp, a.direction), slot(b.helix_id, b.start_bp, b.direction))
        for s in design.scaffolds() if not s.is_reference
        for a, b in zip(s.domains, s.domains[1:])
    } & edges
    scaffold_helices = {dm.helix_id for s in design.scaffolds() if not s.is_reference for dm in s.domains}
    if not any(a[0] in scaffold_helices and b[0] in scaffold_helices for a, b in edges):
        return None

    # Every longitudinal segment has at most one predecessor and successor.
    following, preceding = {}, {}
    for a, b in edges:
        low, high = (a, b) if a[1] < b[1] else (b, a)
        link = high[0], high[1]
        if (low[0] in following and following[low[0]] != link
                or high[0] in preceding and preceding[high[0]] != low[0]):
            raise RoutingIntegrityError("Ambiguous branching helix continuation; original connections retained.")
        following[low[0]] = link
        preceding[high[0]] = low[0]

    helix_map = {h.id: h for h in design.helices}
    tracks, track_for = {}, {}
    for h in design.helices:
        if h.id in preceding:
            continue
        members, cuts = [h.id], []
        while members[-1] in following:
            next_id, boundary = following[members[-1]]
            if next_id in members or cuts and boundary <= cuts[-1]:
                raise RoutingIntegrityError("Cyclic or out-of-order helix continuation.")
            members.append(next_id)
            cuts.append(boundary)
        tracks[h.id] = members, cuts
        track_for.update({hid: h.id for hid in members})
    if len(track_for) != len(helix_map):
        raise RoutingIntegrityError("Helix continuations do not form linear tracks.")
    for members, cuts in tracks.values():
        for low, high, boundary in zip(members, members[1:], cuts):
            if (helix_map[low].bp_start + helix_map[low].length_bp != boundary
                    or helix_map[high].bp_start != boundary):
                raise RoutingIntegrityError("A continuation does not join the ends of its helix segments.")

    def merge_domains(strand):
        domains = []
        for dm in strand.domains:
            mapped = dm.model_copy(update={"helix_id": track_for.get(dm.helix_id, dm.helix_id)})
            previous = domains[-1] if domains else None
            if (previous and previous.helix_id == mapped.helix_id
                    and previous.direction == mapped.direction
                    and previous.end_bp + (1 if mapped.direction == Direction.FORWARD else -1) == mapped.start_bp
                    and previous.overhang_id == mapped.overhang_id
                    and previous.binds_overhang_id == mapped.binds_overhang_id):
                domains[-1] = previous.model_copy(update={"end_bp": mapped.end_bp})
            else:
                domains.append(mapped)
        return strand.model_copy(update={"domains": domains})

    virtual_helices = []
    for tid, (members, _cuts) in tracks.items():
        first, last = helix_map[members[0]], helix_map[members[-1]]
        virtual_helices.append(_set_helix_extent(first, first.bp_start, last.bp_start + last.length_bp - 1)
                               .model_copy(update={"loop_skips": sorted(
                                   [mark for hid in members for mark in helix_map[hid].loop_skips],
                                   key=lambda mark: mark.bp_index)}))

    def map_half(half):
        return half.model_copy(update={"helix_id": track_for.get(half.helix_id, half.helix_id)})

    virtual_forced = []
    for fl in design.forced_ligations:
        a, b = forced_edge(fl)
        ta, tb = track_for.get(a[0], a[0]), track_for.get(b[0], b[0])
        if ta == tb and a[0] != b[0]:
            if fl.extra_bases or (a, b) not in edges:
                raise RoutingIntegrityError("A helix continuation contains an inserted or nonconsecutive forced junction.")
            continue
        virtual_forced.append(fl.model_copy(update={"three_prime_helix_id": ta, "five_prime_helix_id": tb}))

    virtual = design.copy_with(
        helices=virtual_helices,
        strands=[merge_domains(s) for s in design.strands],
        crossovers=[xo.model_copy(update={"half_a": map_half(xo.half_a), "half_b": map_half(xo.half_b)})
                    for xo in design.crossovers],
        forced_ligations=virtual_forced,
        # These belong to the real segment records, not the solver's tracks.
        deformations=[],
    )
    # A nick on one strand does not turn a continuing duplex into two tracks.
    # Join free scaffold termini only at the certified segment boundaries;
    # arbitrary same-cell ends elsewhere are not inferred to be connected.
    from backend.core.lattice import _ligate

    for tid, (_members, cuts) in tracks.items():
        for boundary in cuts:
            for direction, last, first in ((Direction.FORWARD, boundary - 1, boundary),
                                           (Direction.REVERSE, boundary, boundary - 1)):
                tail = next((s for s in virtual.scaffolds() if not s.is_reference and s.domains
                             and slot(s.domains[-1].helix_id, s.domains[-1].end_bp, s.domains[-1].direction)
                             == slot(tid, last, direction)), None)
                head = next((s for s in virtual.scaffolds() if not s.is_reference and s.domains
                             and slot(s.domains[0].helix_id, s.domains[0].start_bp, s.domains[0].direction)
                             == slot(tid, first, direction)), None)
                if tail is not None and head is not None and tail.id != head.id:
                    virtual = _ligate(virtual, tail, head)
    routed, result = runner(virtual)
    if not result.valid:
        return design, result

    from backend.core.seamed_router import scaffold_strand_clusters

    for component in scaffold_strand_clusters(virtual):
        routes = [s for s in routed.scaffolds() if not s.is_reference
                  and any(dm.helix_id in component for dm in s.domains)]
        if len(routes) != 1:
            raise RoutingIntegrityError("No single scaffold preserving all helix continuations was found.")
    from backend.core.constants import HC_CROSSOVER_PERIOD, SQ_CROSSOVER_PERIOD
    from backend.core.models import LatticeType

    period = HC_CROSSOVER_PERIOD if design.lattice_type == LatticeType.HONEYCOMB else SQ_CROSSOVER_PERIOD
    before_helices = {h.id: h for h in virtual.helices}
    for h in routed.helices:
        before = before_helices[h.id]
        if (h.bp_start < before.bp_start - period
                or h.bp_start + h.length_bp > before.bp_start + before.length_bp + period):
            raise RoutingIntegrityError("Routing would extend a track past its local end-turn window.")

    def real_helix(tid, bp):
        members, cuts = tracks[tid]
        return members[sum(bp >= boundary for boundary in cuts)]

    def split_domains(strand):
        domains = []
        for dm in strand.domains:
            if dm.helix_id not in tracks:
                domains.append(dm)
                continue
            members, cuts = tracks[dm.helix_id]
            lo, hi = sorted((dm.start_bp, dm.end_bp))
            starts = [lo, *[boundary for boundary in cuts if lo < boundary <= hi]]
            ends = [start - 1 for start in starts[1:]] + [hi]
            pieces = list(zip(starts, ends))
            if dm.direction == Direction.REVERSE:
                pieces.reverse()
            for first, last in pieces:
                start, end = (first, last) if dm.direction == Direction.FORWARD else (last, first)
                domains.append(dm.model_copy(update={"helix_id": real_helix(dm.helix_id, first),
                                                      "start_bp": start, "end_bp": end}))
        return strand.model_copy(update={"domains": domains})

    routed_helices = {h.id: h for h in routed.helices}
    helices = []
    for h in design.helices:
        tid = track_for[h.id]
        members, cuts = tracks[tid]
        index = members.index(h.id)
        vh = routed_helices[tid]
        lo = cuts[index - 1] if index else vh.bp_start
        hi = cuts[index] - 1 if index < len(cuts) else vh.bp_start + vh.length_bp - 1
        helices.append(_set_helix_extent(h, lo, hi))

    def restore_half(half):
        return half.model_copy(update={"helix_id": real_helix(half.helix_id, half.index)})

    out = design.copy_with(
        helices=helices,
        strands=[s for s in design.strands if not s.is_scaffold or s.is_reference]
                + [split_domains(s) for s in routed.scaffolds() if not s.is_reference],
        crossovers=[xo.model_copy(update={"half_a": restore_half(xo.half_a), "half_b": restore_half(xo.half_b)})
                    for xo in routed.crossovers],
    )
    for edge in scaffold_edges:
        if not _has_backbone_edge(out, edge):
            raise RoutingIntegrityError("Routing would interrupt an existing helix continuation.")
    problems = junction_errors(out)
    if problems:
        raise RoutingIntegrityError(problems[0])
    from backend.core.crossover_positions import scaffold_seam_positions
    from backend.core.scaffold_invariants import scaffold_routing_invariants

    seamed = hasattr(result, "seam_xovers")
    problems = scaffold_routing_invariants(out, require_seams=seamed)
    if not seamed and scaffold_seam_positions(out):
        problems.append("No seamless route preserving the track ends was found.")
    if close_cycle:
        for strand in out.scaffolds():
            if strand.is_reference or not strand.domains:
                continue
            first, last = strand.domains[0], strand.domains[-1]
            step = 1 if first.direction == Direction.FORWARD else -1
            if (first.helix_id != last.helix_id or first.direction != last.direction
                    or last.end_bp + step != first.start_bp):
                problems.append("Routing did not close the scaffold with a buried nick.")
    if problems:
        raise RoutingIntegrityError(problems[0])
    return out, result
