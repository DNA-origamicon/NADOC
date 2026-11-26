import copy
from pathlib import Path
import random

import pytest

from backend.core.publication_loop_search import search_loop_candidates
from backend.core.publication_sequence_search import search_declared_scaffold, search_scaffold_register


def loop_fixture(lengths=(3,4), discrepancy=1):
    rng=random.Random(195)
    sites=[(0,i) for i in range(30)]
    locations=[(0,8),(0,19)]
    counts=dict(zip(locations,lengths))
    sequence=''.join(rng.choice('ACGT') for _ in range(len(sites)+sum(lengths)+discrepancy))
    complement=sequence.translate(str.maketrans('ACGT','TGCA'))
    blocks={};cursor=0
    for site in sites:
        blocks[site]=list(range(cursor,cursor+1+counts.get(site,0)));cursor+=1+counts.get(site,0)
    staples=[]
    for start,end in [(0,8),(9,19),(20,29)]:
        path=sites[start:end][::-1]
        seq=''.join(complement[i%len(sequence)] for s in path for i in blocks[s][::-1])
        staples.append({'sites':path,'table_row':{'sequence':seq,'length':len(seq)}})
    classified={'scaf':[{'sites':sites}],'stap':staples}
    insertions={'counts':[],'unresolved':locations}
    return classified,insertions,sequence


def test_loops_recovered_with_penalized_one_base_candidate_without_mutation():
    c,i,seq=loop_fixture();before=copy.deepcopy((c,i))
    result=search_declared_scaffold(c,i,{'rows':[{}, {}, {}]},custom_sequence=seq)
    assert (c,i)==before
    assert result['sequence_supported'] and not result['resolved']
    assert result['length_discrepancy']==1
    assert result['best']['mismatches']==0 and result['best_ties']==1
    assert result['insertion_hypothesis']['counts']==[[0,8,3],[0,19,4]]
    assert result['status']=='supported_with_length_discrepancy'
    assert result['confidence']['score']==90
    assert result['confidence']['penalties']==[{'reason':'one-base scaffold length discrepancy','points':10.0}]


def test_exact_length_loops_are_not_penalized_as_errors():
    c,i,seq=loop_fixture(discrepancy=0)
    result=search_declared_scaffold(c,i,{'rows':[{}, {}, {}]},custom_sequence=seq)
    assert result['resolved'] and result['length_discrepancy']==0
    assert result['insertion_hypothesis']['counts']==[[0,8,3],[0,19,4]]
    assert result['confidence']['score']==100 and not result['confidence']['penalties']


def test_loop_ties_do_not_promote_a_hypothesis():
    c,i,seq=loop_fixture();seq='A'*len(seq)
    for p in c['stap']:p['table_row']['sequence']='T'*p['table_row']['length']
    result=search_declared_scaffold(c,i,{'rows':[{}, {}, {}]},custom_sequence=seq)
    assert not result['sequence_supported'] and not result['resolved']
    assert not result['insertion_hypothesis']['sequence_supported']
    assert result['best_ties']>1


def test_bounds_and_paired_unknown_loops_are_explicit():
    c,i,seq=loop_fixture()
    i['unresolved']=[(0,1)]
    with pytest.raises(ValueError,match='scaffold-only'):search_loop_candidates(c,i,seq)
    c,i,seq=loop_fixture()
    with pytest.raises(ValueError,match='bounds'):search_loop_candidates(c,i,'ACGT'*1000)


def test_plus_and_minus_one_are_hypotheses_not_silent_sequence_edits():
    c,i,seq=loop_fixture();counts={'counts':[[0,8,3],[0,19,4]],'unresolved':[]}
    with pytest.raises(ValueError,match='length'):search_scaffold_register(c,counts,seq)
    plus=search_scaffold_register(c,counts,seq,allow_length_discrepancy=True)
    assert plus['length_discrepancy']==1 and plus['unrepresented_sequence_indices']==[37]
    c,i,seq=loop_fixture(discrepancy=-1)
    minus=search_scaffold_register(c,counts,seq,allow_length_discrepancy=True)
    assert minus['length_discrepancy']==-1 and minus['unassigned_image_addresses']==[[0,29,0]]
    with pytest.raises(ValueError,match='length'):search_scaffold_register(c,counts,seq[:-1],allow_length_discrepancy=True)


@pytest.mark.skipif(not Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf').exists(),reason='Local publication corpus not installed')
def test_d009_loops_and_length_discrepancy_recovered_from_pdf_only():
    import pymupdf
    from backend.core.publication_routing import extract_publication_paths, staple_tables, pair_endpoint_table, classify_scaffold, resolve_insertions
    with pymupdf.open('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf') as doc:
        table=next(t for t in staple_tables(doc) if t['page']==14)
        pairing=pair_endpoint_table(extract_publication_paths(doc[5]),table)
    c=classify_scaffold(pairing);i=resolve_insertions(pairing,c,table)
    r=search_declared_scaffold(c,i,table)
    assert r['scaffold_name']=='p7704' and r['sequence_supported'] and not r['resolved']
    assert sorted(r['insertion_hypothesis']['counts'])==[[30,119,39],[42,119,39]]
    assert r['represented_length']==7703 and r['length_discrepancy']==1
    assert r['best']['mismatches']==0 and r['best']['compared_bases']==6686
    assert r['best']['unknown_bases']==276 and r['unmatched_table_rows']==10
    assert r['confidence']['score']==80.96
    exact=[c for c in r['loop_search']['alternatives'] if c['length_discrepancy']==0]
    assert exact[0]['mismatches']==408


def test_loop_search_handles_reverse_traversal_and_nonzero_register():
    c,i,seq=loop_fixture()
    c['scaf'][0]['sites']=c['scaf'][0]['sites'][::-1]
    r=search_declared_scaffold(c,i,{'rows':[{}, {}, {}]},custom_sequence=seq[5:]+seq[:5])
    assert r['sequence_supported'] and r['best']['reverse']
    assert r['best']['offset']==len(seq)-5
    assert sorted(r['insertion_hypothesis']['counts'])==[[0,8,3],[0,19,4]]


def test_unobserved_middle_segment_keeps_loop_partition_ambiguous():
    c,i,seq=loop_fixture(discrepancy=0)
    c['stap'].pop(1)
    r=search_declared_scaffold(c,i,{'rows':[{}, {}]},custom_sequence=seq)
    assert not r['sequence_supported'] and r['best_ties']>1


def test_one_base_discrepancy_never_hides_a_paired_base_mismatch():
    c,i,seq=loop_fixture()
    raw=c['stap'][0]['table_row']['sequence']
    c['stap'][0]['table_row']['sequence']=('A' if raw[0]!='A' else 'C')+raw[1:]
    r=search_declared_scaffold(c,i,{'rows':[{}, {}, {}]},custom_sequence=seq)
    assert r['best']['mismatches']==1
    assert not r['sequence_supported'] and not r['resolved']
    assert not r['insertion_hypothesis']['sequence_supported']
