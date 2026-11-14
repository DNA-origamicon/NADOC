"""Residue identities only; reuse export threading without constructing any atoms."""
from types import SimpleNamespace

from backend.core.chain_ids import alphabetic_chain_id


def thread_synthetic_residues(design, chain_map):
    from backend.core.atomistic import _thread_inserts_inline

    records = []
    for (chain, seq), key in chain_map.items():
        records.append(SimpleNamespace(chain_id=chain, seq_num=seq,
                       helix_id=key[0], bp_index=key[1], direction=key[2], key=key))
    chains = {s.id: alphabetic_chain_id(i) for i, s in enumerate(design.strands)}
    ends = {(d.helix_id, d.end_bp, d.direction.value): s.id
            for s in design.strands for d in s.domains}
    junctions = [(x.id, x.extra_bases,
                  (x.half_a.helix_id, x.half_a.index, x.half_a.strand.value),
                  (x.half_b.helix_id, x.half_b.index, x.half_b.strand.value))
                 for x in design.crossovers if x.extra_bases]
    junctions += [(x.id, x.extra_bases,
                   (x.three_prime_helix_id, x.three_prime_bp, x.three_prime_direction.value),
                   (x.five_prime_helix_id, x.five_prime_bp, x.five_prime_direction.value))
                  for x in design.forced_ligations if x.extra_bases]
    # This is the same ownership rule as _build_extra_base_atoms. Actual residue
    # numbering is delegated to the exporter's threading routine below.
    for xid, bases, a, b in junctions:
        source = a if a in ends else b
        if source not in ends:
            raise ValueError(f'No strand owns inserted residues at {xid}')
        for k in range(len(bases)):
            records.append(SimpleNamespace(chain_id=chains[ends[source]], seq_num=0,
                           helix_id=source[0], bp_index=source[1], direction=source[2],
                           crossover_id=xid, extra_base_k=k, key=('__xb__', xid, k)))
    strands = {s.id: s for s in design.strands}
    for ext in design.extensions:
        if not ext.sequence:
            continue
        strand = strands.get(ext.strand_id)
        if strand is None or not strand.domains:
            raise ValueError(f'No strand owns extension {ext.id}')
        dom = strand.domains[0] if ext.end == 'five_prime' else strand.domains[-1]
        for k in range(len(ext.sequence)):
            records.append(SimpleNamespace(chain_id=chains[strand.id], seq_num=0,
                           helix_id=dom.helix_id, bp_index=dom.start_bp if ext.end == 'five_prime' else dom.end_bp,
                           direction=dom.direction.value, extension_id=ext.id, ext_k=k,
                           key=('__ext_' + ext.id, k, dom.direction.value)))
    _thread_inserts_inline(records, design)
    return {(r.chain_id, r.seq_num): r.key for r in records}
