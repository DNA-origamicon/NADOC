"""Prefer strand-owned loops for evidenced multi-base scaffold-only insertions."""


def insertion_plan(insertions, classified, site_mapping):
    scaffold = [tuple(s) for s in classified['scaf'][0]['sites']]
    staples = {tuple(s) for p in classified['stap'] for s in p['sites']}
    duplex, loops = [], []
    for h, bp, count in insertions['counts']:
        site = (h, bp)
        if count <= 1 or site in staples:
            duplex.append((h, bp, count))
            continue
        indices = [i for i, s in enumerate(scaffold) if s == site]
        if len(indices) != 1 or indices[0] == len(scaffold) - 1:
            raise ValueError('Scaffold insertion loop needs one anchor and a following nucleotide')
        i = indices[0]
        # At a domain boundary use the incoming segment to establish polarity.
        neighbors = [(scaffold[j], sign) for j, sign in ((i + 1, 1), (i - 1, -1))
                     if 0 <= j < len(scaffold)]
        directions = {('FORWARD' if (s[1] - bp) * sign > 0 else 'REVERSE')
                      for s, sign in neighbors if s[0] == h and abs(s[1] - bp) == 1}
        if len(directions) != 1:
            raise ValueError('Scaffold insertion loop anchor has unresolved polarity')
        native_h, native_bp = site_mapping.get(site, site)
        loops.append({'source_helix': h, 'source_bp': bp, 'helix': native_h,
                      'bp_index': native_bp, 'direction': directions.pop(), 'length': count,
                      'basis': 'Multi-base insertion supported by source annotation and sequence; no staple occupies its anchor'})
    return {'duplex_insertions': duplex, 'scaffold_loops': loops,
            'method': 'strand-loop-set for multi-base scaffold-only insertions; legacy loop-skip for paired or single-base insertions',
            'limitation': 'Strand-owned loops support native NADOC persistence and display; simulation and cadnano/scadnano export are not yet supported.' if loops else None}
