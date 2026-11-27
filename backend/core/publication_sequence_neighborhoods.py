"""Bounded joint reassignment of unresolved staples and their occupancy blockers."""
from collections import Counter

from backend.core.publication_domain_optimization import DomainOccupancy
from backend.core.publication_sequence_anchors import assignment_pairs


def refine_neighborhoods(search, incumbent, scaffold_length, *, maximum_neighborhoods=4,
                         maximum_rows=32, time_limit=1):
    if not 1 <= maximum_neighborhoods <= 16 or not 2 <= maximum_rows <= 100:
        raise ValueError('Neighborhood bounds exceeded.')
    if not incumbent or not incumbent.get('assignments'):
        return {'status':'no_incumbent', 'compatibility':incumbent, 'attempts':[]}
    model = DomainOccupancy(search, scaffold_length)
    rows = {r['row_id']:r for r in search['rows']}
    current = incumbent
    attempted = set(); attempts = []
    for _ in range(maximum_neighborhoods):
        chosen = {a['row_id']:a['candidate_index'] for a in current['assignments']}
        mapping = assignment_pairs(search, current['assignments'], scaffold_length)
        owners = {site:row for (row,_),site in mapping.items()}
        potential = []
        for row_id,row in rows.items():
            selected = chosen.get(row_id)
            paired = row['candidates'][selected]['paired_bases'] if selected is not None else 0
            gain = max((c['paired_bases'] for c in row['candidates']), default=0)-paired
            if gain > 0 and row_id not in attempted:
                potential.append((-gain,row_id))
        if not potential:
            break
        _, seed = min(potential); attempted.add(seed)
        blockers = Counter()
        for col,(i,_) in enumerate(model.options):
            if model.rows[i]['row_id'] == seed:
                blockers.update(owners[s] for s in model.pair_maps[col].values() if s in owners and owners[s] != seed)
        neighborhood = {seed, *[row for row,_ in sorted(blockers.items(),key=lambda p:(-p[1],p[0]))[:maximum_rows-1]]}
        excluded=[];baseline_cost=0
        for col,(i,j) in enumerate(model.options):
            row_id=model.rows[i]['row_id']
            if j == chosen.get(row_id):
                baseline_cost += model.costs[col]
            if row_id not in neighborhood and j != chosen.get(row_id):
                excluded.append(col)
        result=model.solve(time_limit,excluded=excluded,cost_ceiling=baseline_cost+.01)
        before=len(mapping)
        record={'seed_row':seed,'movable_rows':sorted(neighborhood),'fixed_rows':len(rows)-len(neighborhood),
                'solver_status':int(result.status),'before_paired_bases':before,
                'status':'inconclusive_budget'}
        if result.x is not None:
            assignments=model.assignments(result)
            after=len(assignment_pairs(search,assignments,scaffold_length))
            # Objective ceiling preserves pairing count, then domain count.
            current={'status':'neighborhood_refined_incumbent','assignments':assignments,'paired_bases':after,
                     'candidate_pool_complete':all(r['search_complete_within_bounds'] for r in search['rows']),
                     'native_routing_resolved':False,
                     'limitation':'Only reported neighborhoods optimized; neither global uniqueness nor native routing established.'}
            record.update(after_paired_bases=after,status='improved' if after>before else 'no_pairing_gain')
        attempts.append(record)
    return {'method':'occupancy-blocker-neighborhood-v1','compatibility':current,'attempts':attempts,
            'time_limit_seconds_per_neighborhood':time_limit,'native_routing_resolved':False}


def residual_scaffold_intervals(search, compatibility, scaffold_length):
    """Circular unassigned intervals with neighboring table-row identities."""
    if not compatibility or not compatibility.get('assignments'):
        return {'status':'no_incumbent','intervals':[]}
    mapping=assignment_pairs(search,compatibility['assignments'],scaffold_length)
    owners={site:row for (row,_),site in mapping.items()}
    intervals=[]
    if not owners:
        intervals=[{'scaffold_start':0,'length':scaffold_length,'before_row':None,'after_row':None}]
    else:
        for start in range(scaffold_length):
            if start in owners or (start-1)%scaffold_length not in owners:
                continue
            length=1
            while (start+length)%scaffold_length not in owners:
                length+=1
            intervals.append({'scaffold_start':start,'length':length,
                              'before_row':owners[(start-1)%scaffold_length],
                              'after_row':owners[(start+length)%scaffold_length]})
    return {'status':'unassigned_not_classified','paired_bases':len(owners),
            'unassigned_bases':scaffold_length-len(owners),'intervals':intervals,
            'limitation':'Unassigned sequence is not evidence of a scaffold loop. Missing staple pairing, functional domains and routing ambiguity remain possible.'}
