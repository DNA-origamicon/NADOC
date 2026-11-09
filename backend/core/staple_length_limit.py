"""Hard oligo-length limit, using the editor's existing nick operation."""
from backend.core.models import StrandType
from backend.core.sequences import _build_loop_skip_map, strand_sequence_length


def staple_lengths(design):
    """Sequence bases, including terminal extensions and junction inserts."""
    ls_map = _build_loop_skip_map(design)
    extensions = {}
    for ext in design.extensions:
        extensions[ext.strand_id] = extensions.get(ext.strand_id, 0) + len(ext.sequence or '')
    lengths = {}
    special = set(extensions)
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or s.is_reference:
            continue
        ends = {(d.helix_id, bp, d.direction) for d in s.domains for bp in (d.start_bp, d.end_bp)}
        inserts = 0
        for x in design.crossovers:
            if x.extra_bases and all((h.helix_id, h.index, h.strand) in ends for h in (x.half_a, x.half_b)):
                inserts += len(x.extra_bases)
        for f in design.forced_ligations:
            if f.extra_bases and (f.three_prime_helix_id, f.three_prime_bp, f.three_prime_direction) in ends:
                inserts += len(f.extra_bases)
        if inserts:
            special.add(s.id)
        lengths[s.id] = strand_sequence_length(design, s, loop_skip_map=ls_map) + extensions.get(s.id, 0) + inserts
    return lengths, special


def enforce_staple_maximum(design, maximum, *, kept_ids=frozenset(), minimum=21):
    """Partition long staples without cutting crossovers or protected strands.

    The minimum is a preference; every new fragment must contain at least seven
    nucleotides. Nicks stay seven lattice bases from each domain end. Dynamic
    programming avoids a greedy last fragment exceeding the maximum. Old logs
    omit this policy entirely, preserving their original routing semantics.
    """
    from backend.api.routes_assign_sequences import _locked_and_overhang_staple_ids
    from backend.core.lattice import make_nick
    from backend.core.sequences import domain_bp_range

    lengths, special = staple_lengths(design)
    locked, overhang = _locked_and_overhang_staple_ids(design)
    protected = locked | overhang | special
    ls_map = _build_loop_skip_map(design)
    plans = []
    for strand in design.strands:
        if strand.id not in lengths or strand.id in kept_ids or lengths[strand.id] <= maximum:
            continue
        if strand.id in protected:
            raise ValueError(f'Staple {strand.id} is protected and has {lengths[strand.id]} nt, above the {maximum} nt maximum. Increase the maximum or edit the protected staple.')
        # Candidate cuts are strictly inside ordinary domains; crossover records
        # and their traversals therefore survive unchanged.
        candidates = [(0, None)]
        total = 0
        for d in strand.domains:
            positions = list(domain_bp_range(d))
            for i, bp in enumerate(positions):
                weight = max(0, 1 + ls_map.get((d.helix_id, bp), 0))
                total += weight
                if weight and 7 <= i + 1 <= len(positions) - 7:
                    candidates.append((total, (d.helix_id, bp, d.direction)))
        candidates.append((total, None))
        # Cost: prefer the requested minimum, then fewer fragments, then balance.
        best = {0: ((0, 0, 0), None)}
        for j in range(1, len(candidates)):
            for i in range(j - 1, -1, -1):
                length = candidates[j][0] - candidates[i][0]
                if length > maximum:
                    break
                if length < 7 or i not in best:
                    continue
                previous = best[i][0]
                cost = (previous[0] + max(0, minimum - length), previous[1] + 1,
                        previous[2] + length * length)
                if j not in best or cost < best[j][0]:
                    best[j] = (cost, i)
        j = len(candidates) - 1
        if j not in best:
            raise ValueError(f'Cannot meet the {maximum} nt maximum for staple {strand.id} without cutting a protected junction or creating a fragment shorter than 7 nt. Increase the maximum.')
        cuts = []
        while best[j][1] is not None:
            j = best[j][1]
            if j:
                cuts.append(candidates[j][1])
        plans.append((strand.id, cuts))
    # Apply only after every strand has a feasible plan, in reverse traversal
    # order so the original id always identifies the next fragment to nick.
    result = design
    for strand_id, cuts in plans:
        for helix, bp, direction in cuts:
            result = make_nick(result, helix, bp, direction, predicate=lambda s, sid=strand_id: s.id == sid)
    final, _ = staple_lengths(result)
    routed = [n for sid, n in final.items() if sid not in kept_ids]
    if any(n > maximum for n in routed):
        raise ValueError('Staple maximum could not be satisfied; routing was not applied.')
    return result, {'maximum_nt': maximum, 'longest_nt': max(routed, default=0),
                    'added_nicks': sum(len(cuts) for _, cuts in plans),
                    'excluded_staples': len(kept_ids)}
