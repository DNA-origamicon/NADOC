"""Cut Sweep/source graph connections using the ordinary nick operation."""


def detach_sweep_source(design, sweep_ids, source_ids):
    from backend.core.lattice import make_nick

    def crosses(a, b):
        return ((a in sweep_ids and b in source_ids)
                or (b in sweep_ids and a in source_ids))

    while True:
        junction = next(((s, a) for s in design.strands
                         for a, b in zip(s.domains, s.domains[1:])
                         if crosses(a.helix_id, b.helix_id)), None)
        if junction is None:
            break
        strand, domain = junction
        design = make_nick(design, domain.helix_id, domain.end_bp, domain.direction,
                           predicate=lambda s: s.id == strand.id)
    return design.copy_with(
        crossovers=[x for x in design.crossovers if not crosses(x.half_a.helix_id, x.half_b.helix_id)],
        forced_ligations=[f for f in design.forced_ligations
                          if not crosses(f.three_prime_helix_id, f.five_prime_helix_id)],
    )
