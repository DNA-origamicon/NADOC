"""Plan staple pen strokes, then native nicks and crossovers from directed evidence."""
from collections import defaultdict


def staple_precursors(operations, paths, helix_ids, identity, *, periodic_seams=False, span_gaps=False):
    """Replace domain-by-domain staple drawing with occupied-interval pen strokes.

    The user-authorized end-wrap rule applies only to same-helix
    joins between the two extreme occupied scaffold bases qualify; internal loops
    are never classified as periodic by their length alone.
    """
    bounds = defaultdict(list)
    for h, bp in paths[0]['sites']:
        bounds[h].append(bp)
    bounds = {h: {min(bps), max(bps)} for h, bps in bounds.items()}
    groups, prefix, group = [], [], []
    started = False
    for op in operations:
        started |= op['kind'] == 'strand-add'
        if not started:
            prefix.append(op)
            continue
        group.append(op)
        if op['kind'] == 'strand-sequence':
            groups.append(group)
            group = []
    if group or len(groups) != len(paths):
        raise ValueError('Incomplete strand recipe')
    ordinary, reserved = [], []
    seam_count = 0
    for number, (path, ops) in enumerate(zip(paths[1:], groups[1:]), 1):
        seams = {(tuple(a), tuple(b)) for a, b in zip(path['sites'], path['sites'][1:])
                 if a[0] == b[0] and abs(a[1]-b[1]) > 1
                 and {a[1], b[1]} == bounds[a[0]]}
        # Preserve any explicit nonlocal strand as its own construction. This
        # also supports callers that disable the periodic interpretation.
        if any(op['kind'] == 'forced-ligation-create' for op in ops):
            # Domain draws and joins are ordered together in the original recipe.
            draws = [op for op in ops if op['kind'] == 'strand-add']
            joins = [op for op in ops if op['kind'] in ('crossover-place', 'forced-ligation-create')]
            for i, op in enumerate(joins):
                a, b = draws[i]['params']['domains'][0], draws[i+1]['params']['domains'][0]
                if periodic_seams and op['kind'] == 'forced-ligation-create' and any(
                    helix_ids[x[0]] == a['helix_id'] and x[1] == a['end_bp']
                    and helix_ids[y[0]] == b['helix_id'] and y[1] == b['start_bp'] for x, y in seams
                ):
                    op['params']['is_periodic_seam'] = True
                    op['label'] = f'Polymerization seam, Staple {number}'
                    op['evidence'].append('End-to-end same-helix scaffold-extrema join; user-authorized polymerization classification rule')
                    seam_count += 1
            reserved.extend(ops)
        else:
            ordinary.append((number, path, ops))

    occupied = defaultdict(set)
    directions = {}
    for _, _, ops in ordinary:
        for op in ops:
            if op['kind'] != 'strand-add':
                continue
            d = op['params']['domains'][0]
            h, direction = d['helix_id'], d['direction']
            if h in directions and directions[h] != direction:
                raise ValueError('Inconsistent precursor polarity')
            directions[h] = direction
            for bp in range(min(d['start_bp'], d['end_bp']), max(d['start_bp'], d['end_bp'])+1):
                if bp in occupied[h]:
                    raise ValueError('Overlapping staple evidence')
                occupied[h].add(bp)

    pens, nicks, joins, assignments = [], [], [], []
    gap_deletions = []
    original_occupied = {h:set(bps) for h,bps in occupied.items()}
    if span_gaps:
        reserved_sites = defaultdict(set)
        for op in reserved:
            if op['kind']=='strand-add':
                d=op['params']['domains'][0]
                reserved_sites[d['helix_id']].update(range(min(d['start_bp'],d['end_bp']),max(d['start_bp'],d['end_bp'])+1))
        for h,bps in occupied.items():
            occupied[h] = set(range(min(bps),max(bps)+1))-reserved_sites[h]
        for h,bps in occupied.items():
            extra=bps-original_occupied[h]; step=1 if directions[h]=='FORWARD' else -1
            for start in sorted(b for b in extra if b-1 not in extra):
                end=start
                while end+1 in extra:end+=1
                a,b=(start,end) if step==1 else (end,start)
                for cut in (a-step,b):
                    if cut in bps and cut+step in bps:
                        nicks.append({'kind':'nick','label':'Separate unsupported precursor interval',
                            'params':{'helix_id':h,'bp_index':cut,'direction':directions[h]},
                            'evidence':['Initial full-span fine routing; remove bases with no accepted staple route']})
                gap_deletions.append({'kind':'strand-delete-batch','label':'Remove unsupported precursor interval',
                    'params':{},'select_route':[[h,bp] for bp in range(a,b+step,step)],
                    'evidence':['No accepted staple route occupies this interval; left empty for manual completion']})
    for h, bps in occupied.items():
        for start in sorted(bp for bp in bps if bp-1 not in bps):
            end = start
            while end+1 in bps:
                end += 1
            a, b = (start, end) if directions[h] == 'FORWARD' else (end, start)
            pens.append({'kind': 'strand-add', 'label': 'Draw continuous staple precursor',
                         'params': {'_strand_id': identity(f'precursor:{h}:{start}'), 'strand_type': 'staple',
                                    'domains': [{'helix_id': h, 'start_bp': a, 'end_bp': b,
                                                 'direction': directions[h]}]},
                         'evidence': ['Accepted staple occupancy from drawn paths and uniquely constrained table routes; separately authored nonlocal staples excluded']})
    for number, path, ops in ordinary:
        h, bp = path['sites'][-1]
        hid = helix_ids[h]
        direction = directions[hid]
        step = 1 if direction == 'FORWARD' else -1
        if bp+step in original_occupied[hid]:
            nicks.append({'kind': 'nick', 'label': f'Nick at Staple {number} 3′ end',
                          'params': {'helix_id': hid, 'bp_index': bp, 'direction': direction},
                          'evidence': ['Published staple endpoint; prevents precursor cycles']})
        for op in ops:
            if op['kind'] == 'crossover-place':
                joins.append(op)
            elif op['kind'] == 'forced-ligation-create':
                raise ValueError('Nonperiodic staple ligation requires an explicit precursor endpoint selection')
            elif op['kind'] == 'strand-sequence':
                op['params'].pop('strand_id')
                op['select_route'] = [[helix_ids[h], bp] for h, bp in path['sites']]
                assignments.append(op)
    return (prefix + groups[0] + pens + nicks + gap_deletions + joins + assignments + reserved,
            {'pen_strokes': len(pens), 'endpoint_nicks': len(nicks), 'periodic_seams': seam_count})
