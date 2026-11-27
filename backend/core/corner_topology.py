"""Materialize a resolved Corner route into native topology components.

No Design or history entry is created here. The native Corner command owns the
transaction, helix placement, reference remapping and publication. Seam inserts
use NADOC's existing explicit non-lattice ligation representation. Ordinary
lattice connections are never reclassified to make a route pass.
"""

from dataclasses import dataclass
import hashlib
import re

from backend.core.models import ForcedLigation, Strand


def corner_output_id(operation_id, role, source_id):
    if not isinstance(operation_id, str) or not 1 <= len(operation_id) <= 128:
        raise ValueError('Corner requires a bounded stable operation identity.')
    digest = hashlib.sha256(source_id.encode('utf-8')).hexdigest()[:24]
    return f'{operation_id}:{role}:{digest}'


@dataclass(frozen=True)
class CornerTopology:
    strands: tuple[Strand, ...]
    seam_connections: tuple[ForcedLigation, ...]
    # Original nucleotide endpoints which survive, with their new helix address.
    endpoint_map: dict[tuple[str, int, str], tuple[str, int, str]]
    # Original domain → all resulting domain indices (including local splits).
    domain_map: dict[tuple[str, int], tuple[int, ...]]
    removed_strand_ids: tuple[str, ...]


def _sequence_fragments(strand, loop_skips):
    """Keep the repository's domain-sequence convention, including loop copies.

    Explicit junction insert sequences live on their connection records, not in
    Strand.sequence. Bases created by extending a duplex receive N, never a
    guessed scaffold base or silently shifted downstream sequence.
    """
    if strand.sequence is None:
        return None
    offset, fragments = 0, []
    for domain in strand.domains:
        step = 1 if domain.end_bp >= domain.start_bp else -1
        bases = {}
        for bp in range(domain.start_bp, domain.end_bp + step, step):
            delta = 0 if domain.overhang_id or domain.binds_overhang_id else loop_skips.get((domain.helix_id, bp), 0)
            count = max(0, 1 + delta)
            bases[bp] = strand.sequence[offset:offset + count]
            if len(bases[bp]) != count:
                raise ValueError('Source sequence length does not match its strand path.')
            offset += count
        fragments.append(bases)
    if offset != len(strand.sequence):
        raise ValueError('Source sequence length does not match its strand path.')
    return fragments


def materialize_corner_topology(source_strands, plan, *, operation_id,
                                outgoing_helix_ids, bridge_sequences,
                                loop_skips=None, new_tip_sequences=False):
    """Build both strand types from a plan and explicitly resolved seam sequences.

    bridge_sequences is keyed by (source strand id, exit-domain index in the
    plan). The geometric evaluator must supply every sequence, including an
    explicit empty string for a zero-insert seam. This function does not guess
    bridge lengths from cylinder-axis distances.
    """
    corner_output_id(operation_id, 'check', '')
    source_strands = tuple(source_strands)
    loop_skips = loop_skips or {}
    if new_tip_sequences and plan.position_bp is None:
        raise ValueError('Sequence ownership requires the recorded split position.')
    sources = {s.id: s for s in source_strands}
    if len(sources) != len(source_strands):
        raise ValueError('Source strand identities must be unique.')
    planned_ids = [s.strand_id for s in plan.strands]
    if (len(set(planned_ids)) != len(planned_ids)
            or set(planned_ids) & set(plan.removed_strand_ids)
            or set(planned_ids) | set(plan.removed_strand_ids) != sources.keys()):
        raise ValueError('Corner plan does not account for every source strand.')
    outputs = list(outgoing_helix_ids.values())
    if (len(outputs) != len(set(outputs)) or any(not identity for identity in outputs)
            or set(outputs) & {d.helix_id for s in source_strands for d in s.domains}):
        raise ValueError('Outgoing wedge helices need distinct new identities.')
    expected = {(j.strand_id, j.exit_domain) for j in plan.junctions}
    if set(bridge_sequences) != expected or len(expected) != len(plan.junctions):
        raise ValueError('Every planned junction needs exactly one resolved bridge sequence.')
    if any(not isinstance(seq, str) or re.fullmatch('[ACGTN]*', seq) is None
           for seq in bridge_sequences.values()):
        raise ValueError('Bridge sequences must be explicit uppercase DNA sequences.')

    strands, endpoint_map, domain_map = [], {}, {}
    for routed in plan.strands:
        source = sources[routed.strand_id]
        if source.strand_type.value != routed.strand_type:
            raise ValueError('Corner cannot change a strand from scaffold to staple or vice versa.')
        fragments = _sequence_fragments(source, loop_skips)
        domains, sequence = [], []
        for index, row in enumerate(routed.domains):
            old = source.domains[row.source_domain_index]
            if old.helix_id != row.helix_id or old.direction.value != row.direction:
                raise ValueError('Corner plan changed source domain ownership or polarity.')
            helix_id = row.helix_id
            if row.side == 'outgoing':
                if helix_id not in outgoing_helix_ids:
                    raise ValueError('Corner plan has no outgoing helix identity.')
                helix_id = outgoing_helix_ids[helix_id]
            domains.append(old.model_copy(update={'helix_id': helix_id,
                                                  'start_bp': row.start_bp, 'end_bp': row.end_bp}))
            key = (source.id, row.source_domain_index)
            domain_map[key] = (*domain_map.get(key, ()), index)
            # Endpoint remapping only covers truly retained addresses. A clipped
            # old crossover must be resolved explicitly, never moved silently.
            for bp in (old.start_bp, old.end_bp):
                if plan.position_bp is not None and row.side != 'unchanged':
                    original_side = 'incoming' if bp < plan.position_bp else 'outgoing'
                    if row.side != original_side:
                        continue  # The other wedge's extended copy is a new nucleotide.
                if min(row.start_bp, row.end_bp) <= bp <= max(row.start_bp, row.end_bp):
                    old_key = (old.helix_id, bp, old.direction.value)
                    new_key = (helix_id, bp, old.direction.value)
                    if old_key in endpoint_map and endpoint_map[old_key] != new_key:
                        raise ValueError('An original domain endpoint has ambiguous wedge ownership.')
                    endpoint_map[old_key] = new_key
            if fragments is not None:
                step = 1 if row.end_bp >= row.start_bp else -1
                for bp in range(row.start_bp, row.end_bp + step, step):
                    count = max(0, 1 + loop_skips.get((row.helix_id, bp), 0))
                    is_new_tip = new_tip_sequences and (
                        (row.side == 'incoming' and bp >= plan.position_bp)
                        or (row.side == 'outgoing' and bp < plan.position_bp))
                    sequence.append('N' * count if is_new_tip else
                                    fragments[row.source_domain_index].get(bp, 'N' * count))
        changed = domains != source.domains
        strands.append(source.model_copy(update={
            'domains': domains,
            'sequence': ''.join(sequence) if fragments is not None else None,
            'routing_seed': [] if changed else source.routing_seed,
        }))

    by_id = {s.id: s for s in strands}
    routed_by_id = {s.strand_id: s for s in plan.strands}
    seams = []
    for junction in plan.junctions:
        if junction.entry_domain != junction.exit_domain + 1:
            raise ValueError('Corner seam must connect consecutive domains in 5′→3′ order.')
        rows = routed_by_id[junction.strand_id].domains
        sides = {rows[junction.exit_domain].side, rows[junction.entry_domain].side}
        if sides != {'incoming', 'outgoing'}:
            raise ValueError('A changed within-wedge connection requires lattice rerouting; '
                             'Corner cannot replace it with a forced ligation.')
        strand = by_id[junction.strand_id]
        a, b = strand.domains[junction.exit_domain:junction.entry_domain + 1]
        seams.append(ForcedLigation(
            id=corner_output_id(operation_id, 'seam', f'{strand.id}:{junction.exit_domain}'),
            three_prime_helix_id=a.helix_id, three_prime_bp=a.end_bp,
            three_prime_direction=a.direction,
            five_prime_helix_id=b.helix_id, five_prime_bp=b.start_bp,
            five_prime_direction=b.direction,
            extra_bases=bridge_sequences[(strand.id, junction.exit_domain)] or None,
        ))
    return CornerTopology(tuple(strands), tuple(seams), endpoint_map, domain_map,
                          plan.removed_strand_ids)
