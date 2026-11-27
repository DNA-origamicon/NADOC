"""Provisional sequence anchors with explicit counterexample and pruning evidence.

An anchor is an oligo-offset → scaffold-offset core, not a molecular placement.
Agreement in bounded searches never establishes a unique native route.
"""
from collections import Counter
from copy import deepcopy

from backend.core.publication_domain_optimization import DomainOccupancy


LIMITATION = ('Sequence anchors are conditional on scaffold identity and retained candidates. '
              'Pruning can hide alternatives; image lane, polarity and crossover assignments '
              'are not established. Support counts are not probabilities.')


def candidate_pairs(candidate, scaffold_length):
    pairs = {}
    if candidate:
        for domain in candidate['domains']:
            for k in range(domain['length']):
                pos = domain['oligo_start'] + k
                if pos in pairs:
                    raise ValueError('Overlapping oligo domains.')
                pairs[pos] = (domain['scaffold_start'] + domain['scaffold_step'] * k) % scaffold_length
    if len(set(pairs.values())) != len(pairs):
        raise ValueError('Repeated scaffold occupancy within a staple.')
    return pairs


def assignment_pairs(search, assignments, scaffold_length):
    rows = {r['row_id']: r for r in search['rows']}
    if len({a['row_id'] for a in assignments}) != len(assignments):
        raise ValueError('Duplicate row assignment.')
    result = {}
    for item in assignments:
        index = item['candidate_index']
        candidate = rows[item['row_id']]['candidates'][index] if index is not None else None
        result.update({(item['row_id'], p): s for p, s in candidate_pairs(candidate, scaffold_length).items()})
    if len(set(result.values())) != len(result):
        raise ValueError('Assignments conflict on scaffold occupancy.')
    return result


def merge_candidate_pools(trials):
    """Union without discarding lower-ranked candidates, preserving row identity."""
    merged, seen = {}, {}
    for trial in trials:
        for row in trial['alignment']['rows']:
            key = row['row_id']
            if key not in merged:
                merged[key] = {'row_id': key, 'candidates': [], 'search_complete_within_bounds': True}
                seen[key] = set()
            merged[key]['search_complete_within_bounds'] &= row['search_complete_within_bounds']
            for c in row['candidates']:
                identity = tuple((d['oligo_start'], d['scaffold_start'], d['scaffold_step'], d['length']) for d in c['domains'])
                if identity not in seen[key]:
                    seen[key].add(identity); merged[key]['candidates'].append(deepcopy(c))
    return {'rows': list(merged.values()), 'native_routing_resolved': False}


def identify_stable_anchors(rows, scaffold, trials, *, minimum_length=12):
    """Intersect base mappings, so a shifted domain boundary retains its stable core.

    Every solution includes unassigned staples as missing support. Occurrences are
    counted against the entire circular scaffold, independently of candidate pruning.
    """
    if not 2 <= minimum_length <= len(scaffold):
        raise ValueError('Invalid anchor length.')
    sequences = {r['id']: r['sequence'].upper() for r in rows}
    if len(sequences) != len(rows):
        raise ValueError('Table row identifiers must be unique.')
    scaffold = scaffold.upper()
    complement = str.maketrans('ACGT', 'TGCA')
    if not scaffold or set(scaffold) - set('ACGT'):
        raise ValueError('Invalid scaffold sequence.')
    maps, sources = [], []
    for i, trial in enumerate(trials):
        compatibility = trial['compatibility']
        solutions = [('primary', compatibility.get('assignments', [])),
                     ('alternative', compatibility.get('alternative_search', {}).get('assignments', []))]
        for kind, assignments in solutions:
            if not assignments:
                continue
            mapping = assignment_pairs(trial['alignment'], assignments, len(scaffold))
            for (row, pos), site in mapping.items():
                if pos < 0 or pos >= len(sequences[row]) or sequences[row][pos] != scaffold[site].translate(complement):
                    raise ValueError('Assignment does not complement the source sequence.')
            maps.append(mapping)
            sources.append({'trial': trial.get('name', str(i)), 'solution': kind,
                            'solver_status': compatibility.get('status'), 'paired_bases': len(mapping)})
    common = {k: v for k, v in maps[0].items() if all(m.get(k) == v for m in maps[1:])} if maps else {}
    rc = scaffold.translate(complement)[::-1]
    anchors = []
    for (row, pos), site in sorted(common.items()):
        if common.get((row, pos - 1)) == (site + 1) % len(scaffold):
            continue
        length = 1
        while common.get((row, pos + length)) == (site - length) % len(scaffold):
            length += 1
        if length < minimum_length:
            continue
        sequence = sequences[row][pos:pos + length]
        circle = (rc * (2 + length // len(rc)))[:len(rc) + length - 1]
        occurrences = sum(circle.startswith(sequence, start) for start in range(len(rc)))
        anchors.append({'row_id': row, 'oligo_start': pos, 'scaffold_start': site,
                        'scaffold_step': -1, 'length': length, 'sequence': sequence,
                        'circular_occurrences': occurrences, 'support_count': len(maps),
                        'status': 'provisional_sequence_anchor' if len(maps) >= 2 and occurrences == 1 else 'insufficient_support',
                        'challenge': {'status': 'not_tested'}})
    anchors.sort(key=lambda a: (-a['length'], a['row_id'], a['oligo_start']))
    return {'method': 'cross-solution-exact-core-v1', 'anchors': anchors,
            'solution_count': len(maps), 'sources': sources, 'minimum_length': minimum_length,
            'shared_paired_bases': len(common), 'candidate_pool_complete': all(
                r['search_complete_within_bounds'] for t in trials for r in t['alignment']['rows']),
            'native_routing_resolved': False, 'limitation': LIMITATION}


def challenge_anchors(report, trials, scaffold_length, *, maximum_probes=12, time_limit=1, paired_slack=4):
    """Seek a near-score solution omitting an entire anchor core.

    Every other staple can move or become unassigned. Infeasibility establishes
    necessity only in the union of retained pools and stated objective window.
    Feasible counterexamples are retained even if optimization times out.
    """
    if not 0 <= maximum_probes <= 64 or not 0 <= paired_slack <= 100:
        raise ValueError('Anchor challenge bounds exceeded.')
    search = merge_candidate_pools(trials)
    model = DomainOccupancy(search, scaffold_length)
    baselines = []
    for t in trials:
        assignments = t['compatibility'].get('assignments', [])
        if not assignments:
            continue
        mapping = assignment_pairs(t['alignment'], assignments, scaffold_length)
        row_map = {r['row_id']: r for r in t['alignment']['rows']}
        domains = sum(row_map[a['row_id']]['candidates'][a['candidate_index']]['domain_count']
                      for a in assignments if a['candidate_index'] is not None)
        baselines.append(-len(mapping) * model.weight + domains)
    if not baselines:
        return {**report, 'challenge_status': 'no_baseline'}
    ceiling = min(baselines) + paired_slack * model.weight
    witnesses, probed = [], 0
    for anchor in report['anchors']:
        if anchor['status'] != 'provisional_sequence_anchor' or probed >= maximum_probes:
            continue
        columns = model.anchor_columns(anchor)
        result = model.solve(time_limit, excluded=columns, cost_ceiling=ceiling)
        status = 'counterexample_found' if result.x is not None else 'required_in_retained_pool' if result.status == 2 else 'inconclusive_budget'
        anchor['challenge'] = {'status': status, 'solver_status': int(result.status)}
        if result.x is not None:
            assignments = model.assignments(result)
            mapping = assignment_pairs(search, assignments, scaffold_length)
            witnesses.append({'anchor_row': anchor['row_id'], 'anchor_oligo_start': anchor['oligo_start'],
                              'assignments': assignments, 'paired_bases': len(mapping)})
        probed += 1
    # A witness to one challenge may disprove other sampled consensus cores too.
    for witness in witnesses:
        mapping = assignment_pairs(search, witness['assignments'], scaffold_length)
        for anchor in report['anchors']:
            if any(mapping.get((anchor['row_id'], anchor['oligo_start'] + k)) !=
                   (anchor['scaffold_start'] - k) % scaffold_length for k in range(anchor['length'])):
                anchor['status'] = 'counterexample_found'
    report['challenge_summary'] = {'probes': probed, 'maximum_probes': maximum_probes,
                                  'time_limit_seconds_per_probe': time_limit, 'paired_slack': paired_slack,
                                  'cost_ceiling': ceiling, 'objective_weight': model.weight,
                                  'status_counts': dict(Counter(a['challenge']['status'] for a in report['anchors']))}
    report['counterexamples'] = witnesses
    report['challenge_candidate_pool'] = search
    return report
