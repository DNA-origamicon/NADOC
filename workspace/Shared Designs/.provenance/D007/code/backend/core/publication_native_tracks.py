"""Map independent source-row excursions to distinct ordinary native helices.

This is recipe preparation only. Molecular objects are built by recorded editor
commands; every source address is retained for independent comparison afterward.
"""
from copy import deepcopy


def prepare_native_tracks(classified, lattice, placement, unpaired):
    original = {tuple(site) for kind in ('scaf', 'stap')
                for path in classified[kind] for site in path['sites']}
    source_helices = {h for h, _ in original}
    if lattice['resolved']:
        return {'classified': classified, 'cells': lattice['cells'], 'native_cells': False,
                'sources': {h: {'source_helix': h} for h in lattice['cells']},
                'auxiliary_sites': set(), 'site_mapping': {}}
    if not placement.get('resolved') or not placement.get('segment_placements'):
        raise ValueError('Unresolved auxiliary lattice placement; native construction blocked')
    cells = dict(placement['inset_cells'])
    sources = {h: {'source_helix': h} for h in cells}
    mapping = {}; next_id = max(source_helices)+1
    for segment in placement['segment_placements']:
        h = segment['source_helix']
        start, end = segment['source_start'], segment['source_end']
        if start[0] != h or end[0] != h or h in cells:
            raise ValueError('Auxiliary source interval conflicts with inset placement')
        lo, hi = sorted((start[1], end[1]))
        selected = {(h, bp) for bp in range(lo, hi+1)} & original
        if not selected or selected & mapping.keys():
            raise ValueError('Empty or overlapping auxiliary source interval')
        for site in selected:
            mapping[site] = (next_id, site[1])
        if tuple(segment['cell']) in {tuple(c) for c in cells.values()}:
            raise ValueError('Auxiliary placement overlaps an occupied native cell')
        cells[next_id] = segment['cell']
        sources[next_id] = {'source_helix': h, 'source_start': start, 'source_end': end,
                            'native_viewer_label': len(cells)-1}
        next_id += 1
    if any(h not in lattice['cells'] and (h, bp) not in mapping for h, bp in original):
        raise ValueError('Auxiliary placement does not cover all source addresses')
    if not unpaired['resolved']:
        raise ValueError('Unsupported unpaired scaffold; native construction blocked')
    mapped = deepcopy(classified)
    for kind in ('scaf', 'stap'):
        for path in mapped[kind]:
            path['sites'] = [mapping.get(tuple(site), tuple(site)) for site in path['sites']]
    return {'classified': mapped, 'cells': cells, 'native_cells': True,
            'sources': sources, 'auxiliary_sites': set(mapping), 'site_mapping': mapping}
