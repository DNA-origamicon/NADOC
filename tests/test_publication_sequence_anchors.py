import random

import pytest

from backend.core.publication_sequence_anchors import identify_stable_anchors, challenge_anchors, merge_candidate_pools
from backend.core.publication_sequence_domains import scaffold_seed_index


def candidate(pos, site, length, total=24):
    return {'domains': [{'oligo_start': pos, 'scaffold_start': site, 'scaffold_step': -1, 'length': length}],
            'domain_count': 1, 'paired_bases': length,
            'unassigned_offsets': [i for i in range(total) if not pos <= i < pos + length]}


def trial(candidates, selected=0, complete=False, name='trial'):
    return {'name': name, 'alignment': {'rows': [{'row_id': 'x', 'candidates': candidates,
                                               'search_complete_within_bounds': complete}]},
            'compatibility': {'assignments': [{'row_id': 'x', 'candidate_index': selected}],
                              'status': 'incumbent_not_proven_optimal'}}


def fixture():
    rng = random.Random(97)
    scaffold = ''.join(rng.choices('ACGT', k=100))
    rc, _ = scaffold_seed_index(scaffold, 8)
    return scaffold, [{'id': 'x', 'sequence': rc[20:44]}]


def test_stable_core_survives_shifted_boundaries_without_claiming_global_certainty():
    scaffold, rows = fixture()
    trials = [trial([candidate(0, 79, 24)], name='wide'), trial([candidate(2, 77, 20)], name='narrow')]
    report = identify_stable_anchors(rows, scaffold, trials)
    assert report['shared_paired_bases'] == 20
    anchor = report['anchors'][0]
    assert (anchor['oligo_start'], anchor['scaffold_start'], anchor['length']) == (2, 77, 20)
    assert anchor['circular_occurrences'] == 1
    assert anchor['status'] == 'provisional_sequence_anchor'
    assert not report['candidate_pool_complete']
    assert not report['native_routing_resolved']
    checked = challenge_anchors(report, trials, 100, maximum_probes=1, paired_slack=0)
    assert checked['anchors'][0]['challenge']['status'] == 'required_in_retained_pool'


def test_omitted_staple_is_missing_support_not_silently_dropped():
    scaffold, rows = fixture()
    report = identify_stable_anchors(rows, scaffold, [trial([candidate(0, 79, 24)]), trial([], None)])
    assert not report['anchors']


def test_repeated_circular_sequence_is_not_unique_even_if_pool_hides_repeat():
    scaffold = 'AAAACCCCGGGGTTTT' * 3
    rc, _ = scaffold_seed_index(scaffold, 8)
    rows = [{'id': 'x', 'sequence': rc[-4:] + rc[:12]}]
    trials = [trial([candidate(0, 3, 16)], name=name) for name in ('a', 'b')]
    report = identify_stable_anchors(rows, scaffold, trials)
    assert report['anchors'][0]['circular_occurrences'] == 3
    assert report['anchors'][0]['status'] == 'insufficient_support'


def test_exclusion_finds_alternative_that_changes_one_core_base():
    scaffold, rows = fixture()
    trials = [trial([candidate(0, 79, 24), candidate(1, 78, 23)], name=n) for n in ('a', 'b')]
    report = challenge_anchors(identify_stable_anchors(rows, scaffold, trials), trials, 100,
                               maximum_probes=1, paired_slack=1)
    assert report['anchors'][0]['status'] == 'counterexample_found'
    assert report['counterexamples'][0]['paired_bases'] == 23
    assert len(merge_candidate_pools(trials)['rows'][0]['candidates']) == 2


def test_false_complement_and_single_solution_cannot_be_promoted():
    scaffold, rows = fixture()
    with pytest.raises(ValueError, match='complement'):
        identify_stable_anchors(rows, scaffold, [trial([candidate(0, 35, 24)])])
    report = identify_stable_anchors(rows, scaffold, [trial([candidate(0, 79, 24)])])
    assert report['anchors'][0]['status'] == 'insufficient_support'


def test_budget_leaves_anchor_inconclusive(monkeypatch):
    from types import SimpleNamespace
    from backend.core.publication_domain_optimization import DomainOccupancy
    scaffold, rows = fixture()
    trials = [trial([candidate(0, 79, 24)], name=n) for n in ('a', 'b')]
    monkeypatch.setattr(DomainOccupancy, 'solve', lambda *a, **kw: SimpleNamespace(x=None, status=1))
    report = challenge_anchors(identify_stable_anchors(rows, scaffold, trials), trials, 100)
    assert report['anchors'][0]['challenge']['status'] == 'inconclusive_budget'


def test_anchor_guides_expansion_without_removing_original_alternatives():
    from backend.core.publication_sequence_refinement import expand_anchor_candidates
    scaffold, rows = fixture()
    trials = [trial([candidate(2, 77, 20)], name=n) for n in ('a', 'b')]
    report = identify_stable_anchors(rows, scaffold, trials)
    result = expand_anchor_candidates(rows, scaffold, trials, report, maximum_rows=1, time_limit=1)
    assert result['added_candidates'] > 0
    assert result['compatibility']['paired_bases'] == 24
    assert candidate(2, 77, 20) in result['alignment']['rows'][0]['candidates']
    for c in result['conditional_searches'][0]['candidates']:
        from backend.core.publication_sequence_anchors import candidate_pairs
        pairs = candidate_pairs(c, len(scaffold))
        assert all(pairs.get(k) == 79-k for k in range(2, 22))
    assert not result['native_routing_resolved']


def test_anchor_constrained_budget_exhaustion_never_returns_noncompliant_partial_candidate():
    from backend.core.publication_sequence_domains import align_domains
    scaffold, rows = fixture()
    reference, index = scaffold_seed_index(scaffold, 6)
    result = align_domains(rows[0]['sequence'], reference, index, minimum_domain=6,
                           required_pairs={23: 56}, max_transitions=1)
    assert result['budget_exhausted']
    assert result['candidates'] == []


def test_larger_pool_timeout_preserves_better_existing_incumbent():
    from backend.core.publication_sequence_refinement import preserve_best_incumbent
    t = trial([candidate(0, 79, 24)], name='prior')
    t['compatibility']['paired_bases'] = 24
    poorer = {'paired_bases':0,'assignments':[{'row_id':'x','candidate_index':None}]}
    result = preserve_best_incumbent(t['alignment'],poorer,[t])
    assert result['paired_bases'] == 24
    assert result['status'] == 'preserved_feasible_incumbent'


def test_neighborhood_releases_blocker_and_never_claims_global_optimum():
    from backend.core.publication_sequence_neighborhoods import refine_neighborhoods, residual_scaffold_intervals
    search={'rows':[{'row_id':'a','candidates':[candidate(0,3,4)],'search_complete_within_bounds':True},
                    {'row_id':'b','candidates':[candidate(0,5,6)],'search_complete_within_bounds':True}]}
    baseline={'paired_bases':4,'assignments':[{'row_id':'a','candidate_index':0},{'row_id':'b','candidate_index':None}]}
    result=refine_neighborhoods(search,baseline,10,maximum_neighborhoods=1,maximum_rows=2)
    assert result['compatibility']['paired_bases']==6
    assert result['attempts'][0]['movable_rows']==['a','b']
    gaps=residual_scaffold_intervals(search,result['compatibility'],10)
    assert gaps['intervals']==[{'scaffold_start':6,'length':4,'before_row':'b','after_row':'b'}]
    assert not result['native_routing_resolved']


def test_image_screen_requires_classified_staple_trace_and_retains_direction_ambiguity():
    from backend.core.publication_anchor_image_mapping import image_span_candidates
    def trace(kind, index):
        return {'trace_id':index,'kind':kind,'status':'unbranched_staple_trace' if kind=='staple' else 'scaffold_trace',
                'color_continuity_supported':True,'hue_bins':[7],
                'domains':[{'kind':kind,'observed_row_index':0,'span_pdf':[[20,10],[70,10]],'approximate_cells':26}]}
    raster={'classified_tracing':{'panels':[{'placement_index':0,'xref':1,'traces':[trace('scaffold',0),trace('staple',1)]}]}}
    anchors={'minimum_length':12,'anchors':[{'row_id':'x','oligo_start':3,'length':15,'status':'provisional_sequence_anchor'}]}
    result=image_span_candidates(raster,anchors)
    assert len(result['spans'])==1
    assert result['excluded_scaffold_domains']==1
    assert result['spans'][0]['trace_id']==1
    match=result['anchors'][0]
    assert match['status']=='classified_staple_length_only'
    assert match['candidates'][0]['directions']==[-1,1]
    assert match['candidates'][0]['possible_start_cells']>1
    assert not result['native_routing_resolved']
    missing=image_span_candidates({},anchors)
    assert not missing['classification_available']
    assert not missing['spans']
