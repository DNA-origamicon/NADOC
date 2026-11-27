import random
from backend.core.publication_sequence_domains import align_domains,scaffold_seed_index


def test_split_alignment_recovers_nonmonotonic_domains_and_unassigned_tail():
    rng=random.Random(53);scaffold=''.join(rng.choices('ACGT',k=300))
    reference,index=scaffold_seed_index(scaffold,8)
    seq=reference[140:156]+reference[32:44]+'NN'
    # Literal non-DNA is rejected, rather than quietly discarded.
    import pytest
    with pytest.raises(ValueError):align_domains(seq,reference,index)
    result=align_domains(seq[:-2]+'AA',reference,index)
    best=result['candidates'][0]
    assert best['paired_bases']==28
    assert best['domain_count']==2
    expected=[{'oligo_start':0,'length':16,'scaffold_start':159,'scaffold_step':-1},
                             {'oligo_start':16,'length':12,'scaffold_start':267,'scaffold_step':-1}]
    assert any(c['domains']==expected for c in result['candidates'])
    assert result['best_ties_retained']>=2  # shared boundary base admits more than one split
    assert best['unassigned_offsets']==[28,29]
    assert not result['search_complete_within_bounds']


def test_circular_origin_and_repeated_sequences_retain_alternatives():
    reference,index=scaffold_seed_index('AAAACCCCGGGGTTTT'*3,8)
    seq=reference[-4:]+reference[:8]
    result=align_domains(seq,reference,index,max_domains=1)
    assert result['candidates'][0]['paired_bases']==12
    assert result['best_ties_retained']>=3
    assert any(c['domains'][0]['scaffold_start']==3 for c in result['candidates'])


def test_same_scaffold_base_is_never_claimed_twice_in_one_oligo():
    scaffold='ACGCGATTCCGATATGCCGA'
    reference,index=scaffold_seed_index(scaffold,8)
    sequence=reference[3:13]*2
    result=align_domains(sequence,reference,index)
    for candidate in result['candidates']:
        sites=[(d['scaffold_start']-i)%len(scaffold) for d in candidate['domains'] for i in range(d['length'])]
        assert len(sites)==len(set(sites))
    assert result['candidates'][0]['paired_bases']<len(sequence)


def test_transition_budget_is_reported_and_does_not_claim_complete_search():
    reference,index=scaffold_seed_index('ACGT'*10,4)
    result=align_domains('ACGT'*5,reference,index,minimum_domain=4,max_transitions=10)
    assert result['budget_exhausted']
    assert not result['search_complete_within_bounds']
    assert result['status']=='budget_exhausted'


def test_global_compatibility_excludes_double_claims_and_finds_tied_solution():
    from backend.core.publication_sequence_domains import select_compatible_domains
    candidate={'paired_bases':4,'domain_count':1,'domains':[{'oligo_start':0,'scaffold_start':3,'scaffold_step':-1,'length':4}],'unassigned_offsets':[]}
    search={'rows':[{'row_id':name,'candidates':[candidate],'search_complete_within_bounds':True} for name in ('a','b')]}
    result=select_compatible_domains(search,10,time_limit=2)
    assert result['paired_bases']==4  # not eight; only one oligo may occupy these bases
    assert sum(a['candidate_index'] is not None for a in result['assignments'])==1
    assert result['alternative_search']['equal_score_witness']
    assert not result['native_routing_resolved']


def test_no_matches_do_not_create_duplicate_empty_assignment_alternatives():
    from backend.core.publication_sequence_domains import align_table,select_compatible_domains
    search=align_table([{'id':'x','sequence':'AAAAAAAA'}],'AAAAAAAAAA',minimum_domain=8)
    result=select_compatible_domains(search,10,time_limit=2)
    assert result['paired_bases']==0
    assert not result['alternative_search']['equal_score_witness']
