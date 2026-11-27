"""Expand candidates around provisional anchors without freezing their assignments."""
from collections import defaultdict

from backend.core.publication_sequence_anchors import merge_candidate_pools, identify_stable_anchors
from backend.core.publication_sequence_domains import align_domains, scaffold_seed_index, select_compatible_domains


def expand_anchor_candidates(rows, scaffold, trials, anchor_report, *, maximum_rows=24,
                             beam_width=32, max_transitions=100000, time_limit=2):
    if not 1 <= maximum_rows <= 100:
        raise ValueError('Invalid anchor refinement row budget.')
    grouped = defaultdict(list)
    for anchor in anchor_report['anchors']:
        if anchor['status'] == 'provisional_sequence_anchor':
            grouped[anchor['row_id']].append(anchor)
    source = {r['id']: r for r in rows}
    ranked = sorted(grouped, key=lambda row: (-sum(a['length'] for a in grouped[row]), row))[:maximum_rows]
    reference, index = scaffold_seed_index(scaffold, 6)
    expanded = []
    for row_id in ranked:
        required = {a['oligo_start'] + k: (a['scaffold_start'] - k) % len(scaffold)
                    for a in grouped[row_id] for k in range(a['length'])}
        result = align_domains(source[row_id]['sequence'], reference, index, minimum_domain=6,
                               beam_width=beam_width, max_transitions=max_transitions, required_pairs=required)
        expanded.append({'row_id': row_id, **result})
    initial = merge_candidate_pools(trials)
    merged = merge_candidate_pools([{'alignment': initial}, {'alignment': {'rows': expanded}}])
    before = sum(len(r['candidates']) for r in initial['rows'])
    added = sum(len(r['candidates']) for r in merged['rows']) - before
    compatibility = select_compatible_domains(merged, len(scaffold), time_limit=time_limit) if added else None
    solver_attempt = compatibility
    compatibility = preserve_best_incumbent(merged, compatibility, trials)
    from backend.core.publication_sequence_neighborhoods import refine_neighborhoods, residual_scaffold_intervals
    neighborhoods=refine_neighborhoods(merged,compatibility,len(scaffold),maximum_neighborhoods=2,time_limit=min(time_limit,1))
    compatibility=neighborhoods['compatibility']
    residual=residual_scaffold_intervals(merged,compatibility,len(scaffold))
    recheck = identify_stable_anchors(rows, scaffold, [*trials, {'name':'anchor-expanded', 'alignment':merged, 'compatibility':compatibility}]) if compatibility and compatibility.get('assignments') else None
    return {'neighborhoods':neighborhoods,'residual_scaffold':residual,'anchor_recheck': recheck, 'method': 'anchor-conditioned-candidate-expansion-v1', 'expanded_row_ids': ranked,
            'eligible_rows': len(grouped), 'row_budget': maximum_rows, 'added_candidates': added,
            'conditional_searches': expanded, 'alignment': merged, 'compatibility': compatibility,
            'solver_attempt': solver_attempt,
            'native_routing_resolved': False,
            'limitation': 'Anchors guide additional candidate generation only. Original alternatives remain selectable; no anchor is frozen and no unassigned base is declared a loop or overhang.'}


def preserve_best_incumbent(merged, attempt, trials):
    """A timed-out larger search must never replace a better feasible incumbent."""
    merged_rows = {r['row_id']: r for r in merged['rows']}
    def score(search, result):
        by_id = {r['row_id']: r for r in search['rows']}
        domains = sum(by_id[a['row_id']]['candidates'][a['candidate_index']]['domain_count']
                      for a in result.get('assignments', []) if a['candidate_index'] is not None)
        return result.get('paired_bases', 0), -domains
    best = attempt
    for trial in trials:
        prior = trial['compatibility']
        if not prior.get('assignments') or (best and score(trial['alignment'], prior) <= score(merged, best)):
            continue
        source_rows = {r['row_id']: r for r in trial['alignment']['rows']}
        assignments = {r['row_id']: None for r in merged['rows']}
        for a in prior['assignments']:
            if a['candidate_index'] is None:
                continue
            candidate = source_rows[a['row_id']]['candidates'][a['candidate_index']]
            assignments[a['row_id']] = next(i for i,c in enumerate(merged_rows[a['row_id']]['candidates'])
                                              if c['domains'] == candidate['domains'])
        best = {'status':'preserved_feasible_incumbent', 'paired_bases':prior['paired_bases'],
                'assignments':[{'row_id':r, 'candidate_index':i} for r,i in assignments.items()],
                'candidate_pool_complete':all(r['search_complete_within_bounds'] for r in merged['rows']),
                'native_routing_resolved':False, 'source_trial':trial.get('name', 'earlier_pass'),
                'limitation':'Larger-pool solver did not improve the earlier feasible solution within its budget.'}
    return best
