"""Topological cut planning, before Corner's phase and bridge calculation.

The output retains source strand/domain ownership and 5′→3′ traversal. It is
not a Design and cannot be saved or exported as a structure. In particular,
bridge candidates are not ordinary lattice crossovers or forced ligations.
"""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class DuplexCut:
    helix_id: str
    incoming_last_bp: int
    outgoing_first_bp: int


@dataclass(frozen=True)
class RoutedDomain:
    source_domain_index: int
    helix_id: str
    side: Literal['incoming', 'outgoing', 'unchanged']
    start_bp: int
    end_bp: int
    direction: str


@dataclass(frozen=True)
class JunctionCandidate:
    strand_id: str
    strand_type: str
    exit_domain: int
    entry_domain: int


@dataclass(frozen=True)
class RoutedStrand:
    strand_id: str
    strand_type: str
    domains: tuple[RoutedDomain, ...]


@dataclass(frozen=True)
class CornerRoutingPlan:
    strands: tuple[RoutedStrand, ...]
    junctions: tuple[JunctionCandidate, ...]
    removed_strand_ids: tuple[str, ...]
    position_bp: int | None = None


def occupied_duplex_spans(strands):
    """Nominal station bounds actually present on each authored helix."""
    spans = {}
    for strand in strands:
        for domain in strand.domains:
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            previous = spans.get(domain.helix_id, (lo, hi))
            spans[domain.helix_id] = min(lo, previous[0]), max(hi, previous[1])
    return spans


def plan_corner_routes(strands, cuts, position_bp):
    """Clip wedge domains while retaining every unchanged external transition.

    The split is between position_bp-1 and position_bp. A domain spanning that
    split owns any locally added duplex bases up to its miter end. Trimming can
    remove entire local domains. A resulting transition is either an unchanged
    original connection or an explicit junction candidate requiring validation.
    No connectivity is inferred from geometric proximity.
    """
    if type(position_bp) is not int:
        raise ValueError('Corner split position must be an integer.')
    cuts = tuple(cuts)
    cut_map = {cut.helix_id: cut for cut in cuts}
    if not cuts or len(cut_map) != len(cuts):
        raise ValueError('Corner needs unique duplex cuts.')
    if any(type(bp) is not int for cut in cuts
           for bp in (cut.incoming_last_bp, cut.outgoing_first_bp)):
        raise ValueError('Miter endpoints must be integer nucleotide addresses.')
    strands = tuple(strands)
    if len({s.id for s in strands}) != len(strands):
        raise ValueError('Source strand identities must be unique.')
    owners = {}
    sources = {s.id: s for s in strands}
    for strand in strands:
        for index, domain in enumerate(strand.domains):
            if domain.helix_id not in cut_map:
                continue
            if domain.overhang_id or domain.binds_overhang_id:
                raise ValueError('A corner cut cannot reinterpret overhang or binding domains.')
            direction = getattr(domain.direction, 'value', domain.direction)
            if ((direction == 'FORWARD' and domain.start_bp > domain.end_bp)
                    or (direction == 'REVERSE' and domain.start_bp < domain.end_bp)):
                raise ValueError('Source domain traversal disagrees with its polarity.')
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            for side, bp in (('incoming', position_bp - 1), ('outgoing', position_bp)):
                if not lo <= bp <= hi:
                    continue
                key = (domain.helix_id, direction, side)
                if key in owners:
                    raise ValueError('The selected cut has overlapping strand occupancy.')
                owners[key] = (strand.id, index)
    if any((cut.helix_id, direction, side) not in owners
           for cut in cuts for direction in ('FORWARD', 'REVERSE')
           for side in ('incoming', 'outgoing')):
        raise ValueError('The selected plane crosses an unpaired region; '
                         'a local endpoint matching solution is required.')
    for cut in cuts:
        for direction in ('FORWARD', 'REVERSE'):
            incoming = owners[(cut.helix_id, direction, 'incoming')]
            outgoing = owners[(cut.helix_id, direction, 'outgoing')]
            if incoming == outgoing:
                continue
            # A true authored nick is two strand termini, not a crossover or
            # a gap in a domain list. Carry each terminus to its own miter tip,
            # preserving strand identity and the absent covalent connection.
            for (sid, index), side in ((incoming, 'incoming'), (outgoing, 'outgoing')):
                source = sources[sid]
                row = source.domains[index]
                at_three_prime = (side == 'incoming') == (direction == 'FORWARD')
                terminal_index = len(source.domains) - 1 if at_three_prime else 0
                endpoint = row.end_bp if at_three_prime else row.start_bp
                station = position_bp - 1 if side == 'incoming' else position_bp
                if index != terminal_index or endpoint != station:
                    raise ValueError('The selected plane crosses a crossover; '
                                     'a local endpoint matching solution is required.')

    planned, junctions, removed = [], [], []
    occupied = {}
    for strand in strands:
        rows = []
        for index, domain in enumerate(strand.domains):
            direction = getattr(domain.direction, 'value', domain.direction)
            cut = cut_map.get(domain.helix_id)
            if cut is None:
                rows.append(RoutedDomain(index, domain.helix_id, 'unchanged',
                                         domain.start_bp, domain.end_bp, direction))
                continue
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            pieces = []
            if lo < position_bp:
                owns_tip = owners[(domain.helix_id, direction, 'incoming')] == (strand.id, index)
                upper = cut.incoming_last_bp if owns_tip else min(hi, cut.incoming_last_bp)
                if lo <= upper:
                    pieces.append(('incoming', lo, upper))
            if hi >= position_bp:
                owns_tip = owners[(domain.helix_id, direction, 'outgoing')] == (strand.id, index)
                lower = cut.outgoing_first_bp if owns_tip else max(lo, cut.outgoing_first_bp)
                if lower <= hi:
                    pieces.append(('outgoing', lower, hi))
            if direction == 'REVERSE':
                pieces.reverse()
            for side, lower, upper in pieces:
                key = (domain.helix_id, side, direction)
                ranges = occupied.setdefault(key, [])
                if any(lower <= b and a <= upper for a, b in ranges):
                    raise ValueError('Miter extension would duplicate nucleotide occupancy.')
                ranges.append((lower, upper))
                first, last = (lower, upper) if direction == 'FORWARD' else (upper, lower)
                rows.append(RoutedDomain(index, domain.helix_id, side, first, last, direction))
        if not rows:
            removed.append(strand.id)
            continue
        for index, (a, b) in enumerate(zip(rows, rows[1:])):
            old_a, old_b = strand.domains[a.source_domain_index], strand.domains[b.source_domain_index]
            unchanged = (b.source_domain_index == a.source_domain_index + 1
                         and a.end_bp == old_a.end_bp and b.start_bp == old_b.start_bp)
            if not unchanged:
                junctions.append(JunctionCandidate(strand.id, strand.strand_type.value, index, index + 1))
        planned.append(RoutedStrand(strand.id, strand.strand_type.value, tuple(rows)))
    return CornerRoutingPlan(tuple(planned), tuple(junctions), tuple(removed), position_bp)
