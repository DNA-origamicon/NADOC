from pathlib import Path

import pytest

from backend.core.publication_sequence_search import search_scaffold_register, search_declared_scaffold


def fixture(sequence='ACGTTAGCATGCCGAT', shift=5, reverse=False):
    sites=[(0,i) for i in range(len(sequence))]
    order=sites[::-1] if reverse else sites
    bases={s:sequence[(i+shift)%len(sequence)].translate(str.maketrans('ACGT','TGCA')) for i,s in enumerate(order)}
    path=sites[::-1]
    return {'scaf':[{'sites':sites}], 'stap':[{'sites':path,'table_row':{'sequence':''.join(bases[s] for s in path)}}]}, {'counts':[],'unresolved':[]}


@pytest.mark.parametrize('reverse',[False,True])
def test_exhaustive_nonzero_shift_in_both_directions(reverse):
    c,i=fixture(reverse=reverse)
    r=search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')
    assert r['resolved'] and r['candidates_tested']==32
    assert r['best']['offset']==5 and r['best']['reverse']==reverse
    assert r['best']['mismatches']==0 and r['runner_up_mismatches']>0


def test_ties_and_wrong_staples_are_not_successes():
    c,i=fixture(sequence='AAAAAAAAAAAAAAAA')
    r=search_scaffold_register(c,i,'AAAAAAAAAAAAAAAA')
    assert not r['resolved'] and r['best_ties']==32
    c,i=fixture();c['stap'][0]['table_row']['sequence']='A'*16
    assert not search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')['resolved']


def test_unpaired_bases_and_invalid_lengths_remain_explicit():
    c,i=fixture();c['stap'][0]['sites'].append((5,100));c['stap'][0]['table_row']['sequence']+='A'
    r=search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')
    assert r['best']['unknown_bases']==1 and not r['resolved']
    c['stap'][0]['table_row']['sequence']+='A'
    with pytest.raises(ValueError,match='No comparable'):search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')
    assert not search_declared_scaffold(c,i,{'context':'p9999 scaffold'})['resolved']


@pytest.mark.skipif(not Path('experiments/origami_publication_catalog/assets/sources/twist-supp.pdf').exists(),reason='Local publication corpus not installed')
def test_d005_all_staples_exact_without_native_reference():
    import pymupdf
    from backend.core.publication_routing import extract_publication_paths, staple_tables, pair_endpoint_table, classify_scaffold, resolve_insertions
    with pymupdf.open('experiments/origami_publication_catalog/assets/sources/twist-supp.pdf') as doc:
        table=next(t for t in staple_tables(doc) if t['page']==37)
        pairing=pair_endpoint_table(extract_publication_paths(doc[18]),table)
    classified=classify_scaffold(pairing)
    insertions=resolve_insertions(pairing,classified,table)
    r=search_declared_scaffold(classified,insertions,table)
    assert r['resolved'] and r['candidates_tested']==16128
    assert r['best']['exact_staples']==217 and r['best']['compared_bases']==7919
    assert r['best']['mismatches']==0 and r['best_ties']==1
    assert r['best']['unpaired_scaffold_bases']==145
    assert r['runner_up_mismatches']==5551
    assert r['best']['sequence_origin_address']==[1,97,0]


def test_insertion_partner_order_is_antiparallel():
    sequence='ACGTTAGCATGCCGAT'
    sites=[(0,i) for i in range(14)]
    raw=sequence.translate(str.maketrans('ACGT','TGCA'))[::-1]
    c={'scaf':[{'sites':sites}], 'stap':[{'sites':sites[::-1],'table_row':{'sequence':raw}}]}
    r=search_scaffold_register(c,{'counts':[[0,4,2]],'unresolved':[]},sequence)
    assert r['resolved'] and r['best']['offset']==0 and r['best']['compared_bases']==16


def test_explicit_unknown_scaffold_does_not_fall_back_to_length_match():
    c,i=fixture()
    assert search_declared_scaffold(c,i,{'context':'pEGFP scaffold'})['status']=='unsupported_scaffold'
    assert search_declared_scaffold(c,i,{'context':'(p9999)'})['status']=='unsupported_scaffold'


def test_duplicate_sites_and_annotations_fail_instead_of_inflating_evidence():
    import copy
    c,i=fixture(); c['stap'].append(copy.deepcopy(c['stap'][0]))
    with pytest.raises(ValueError,match='Repeated staple sites'):
        search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')
    c,i=fixture();i['counts']=[[0,4,1],[0,4,1]]
    with pytest.raises(ValueError,match='Duplicate'):
        search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')


def test_custom_sequence_overrides_name_and_unmatched_rows_block_complete_validation():
    c,i=fixture()
    table={'context':'p8064 scaffold','rows':[{},{}]}
    r=search_declared_scaffold(c,i,table,custom_sequence='ACGTTAGCATGCCGAT')
    assert r['scaffold_name']=='custom' and r['alignment_resolved']
    assert not r['resolved'] and r['unmatched_table_rows']==1
    assert r['selection_basis']=='user-supplied sequence'


def test_single_mutation_is_localized_and_never_certified():
    c,i=fixture()
    original=c['stap'][0]['table_row']['sequence']
    changed=('A' if original[3]!='A' else 'C')
    c['stap'][0]['table_row']['sequence']=original[:3]+changed+original[4:]
    r=search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')
    assert not r['resolved'] and r['best']['mismatches']==1 and r['best']['offset']==5
    assert r['mismatch_details']==[{'staple_row':0,'paired_base_index':3,
                                   'scaffold_address':[0,12,0],'observed':changed,'expected':original[3]}]


def test_sequence_asset_is_pinned_and_length_correct():
    import hashlib,json
    from backend.core.sequences import P7704_SEQUENCE
    manifest=json.loads(Path('backend/core/p7704.source.json').read_text())
    assert len(P7704_SEQUENCE)==7704 and set(P7704_SEQUENCE)==set('ACGT')
    assert hashlib.sha256(P7704_SEQUENCE.encode()).hexdigest()==manifest['sequence_sha256']
    assert manifest['upstream_commit']=='76644f36595b649583f31937150f78d33ac8b7ba'


@pytest.mark.skipif(not Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf').exists(),reason='Local publication corpus not installed')
def test_five_publication_sequence_searches():
    from tools.design_archive.publication_sequence_benchmark import run_audit
    results=run_audit(Path('experiments/origami_publication_catalog/assets'))['designs']
    assert [r['sequence_search']['resolved'] for r in results]==[True,True,True,True,False]
    assert [r['sequence_search']['best']['compared_bases'] for r in results[:4]]==[7919,7658,5880,4977]
    assert [r['sequence_search']['runner_up_mismatches'] for r in results[:4]]==[5551,5366,4120,3483]
    assert all(r['sequence_search']['best']['mismatches']==0 for r in results[:4])
    assert 'hypotheses' in results[2]['sequence_search']['selection_basis']
    assert results[4]['sequence_search']['status']=='supported_with_length_discrepancy'
    assert results[4]['sequence_search']['sequence_supported']
    assert sorted(results[4]['sequence_search']['insertion_hypothesis']['counts'])==[[30,119,39],[42,119,39]]
    assert results[4]['unresolved_insertions']==[(30,119),(42,119)]


@pytest.mark.skipif(not Path('experiments/origami_publication_catalog/assets/sources/twist-supp.pdf').exists(),reason='Local publication corpus not installed')
def test_d005_virtual_nick_rotation_and_staple_reordering():
    import copy
    import pymupdf
    from backend.core.publication_routing import extract_publication_paths, staple_tables, pair_endpoint_table, classify_scaffold, resolve_insertions
    from backend.core.sequences import P8064_SEQUENCE
    with pymupdf.open('experiments/origami_publication_catalog/assets/sources/twist-supp.pdf') as doc:
        table=next(t for t in staple_tables(doc) if t['page']==37)
        pairing=pair_endpoint_table(extract_publication_paths(doc[18]),table)
    classified=classify_scaffold(pairing);insertions=resolve_insertions(pairing,classified,table)
    sites=classified['scaf'][0]['sites'];cut=157
    counts={(h,b):n for h,b,n in insertions['counts']}
    expected_offset=sum(1+counts.get(tuple(s),0) for s in sites[:cut])
    modified=copy.deepcopy(classified)
    modified['scaf'][0]['sites']=(sites[cut:]+sites[:cut])[::-1]
    modified['stap']=modified['stap'][::-1]
    before=copy.deepcopy(modified)
    r=search_scaffold_register(modified,insertions,P8064_SEQUENCE)
    assert r['resolved'] and r['best']['offset']==expected_offset
    assert r['best']['reverse'] and r['best']['exact_staples']==217
    assert r['best']['sequence_origin_address']==[1,97,0]
    assert modified==before  # Search never relocates the actual nick or changes input routing.


def test_equally_supported_library_sequences_remain_ambiguous(monkeypatch):
    import backend.core.sequences as library
    seq='ACGTTAGCATGCCGAT'
    monkeypatch.setattr(library,'SCAFFOLD_LIBRARY',[('variantA',16,seq),('variantB',16,seq)])
    c,i=fixture();r=search_declared_scaffold(c,i,{'context':'unlabelled diagram'})
    assert not r['resolved'] and r['best_ties']==2
    assert r['candidates_tested']==64 and r['runner_up_mismatches']==0
    assert len(r['scaffolds_tested'])==2


@pytest.mark.parametrize('shift',[127,128,268])
@pytest.mark.parametrize('reverse',[False,True])
def test_offsets_across_batch_boundaries(shift,reverse):
    import random
    rng=random.Random(512)
    sequence=''.join(rng.choice('ACGT') for _ in range(269))
    c,i=fixture(sequence=sequence,shift=shift,reverse=reverse)
    r=search_scaffold_register(c,i,sequence)
    assert r['resolved'] and r['candidates_tested']==538
    assert r['best']['offset']==shift and r['best']['reverse']==reverse


def test_bad_declared_staple_length_prevents_validation():
    c,i=fixture();c['stap'][0]['table_row']['length']=17
    with pytest.raises(ValueError,match='No comparable'):
        search_scaffold_register(c,i,'ACGTTAGCATGCCGAT')


def test_supported_loop_handoff_preserves_sources_and_refuses_unsupported_hypotheses():
    from copy import deepcopy
    from backend.core.publication_sequence_search import apply_supported_insertions
    raw={'counts':[],'unresolved':[(30,119),(42,119)]}
    search={'sequence_supported':True,'represented_length':7703,'length_discrepancy':1,
            'insertion_hypothesis':{'sequence_supported':True,'counts':[[30,119,39],[42,119,39]],'unresolved':[]}}
    before=deepcopy((raw,search))
    result=apply_supported_insertions(raw,search)
    assert result['counts']==[[30,119,39],[42,119,39]] and not result['unresolved']
    result['counts'][0][2]=99
    assert (raw,search)==before
    search['sequence_supported']=False
    assert apply_supported_insertions(raw,search)==raw
    search['sequence_supported']=True;search['insertion_hypothesis']['sequence_supported']=False
    assert apply_supported_insertions(raw,search)==raw
