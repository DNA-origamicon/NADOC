from copy import deepcopy
from backend.core.publication_staple_overhangs import classify_staple_overhangs,apply_overhang_evidence


def fixture():
    return {'scaf':[{'sites':[(0,0),(0,1)]}], 'stap':[{'path_id':4,
        'sites':[(0,3),(0,2),(0,1),(0,0)],'table_row':{'sequence':'ACGT'}}]}


def test_absent_image_uses_exact_table_subsequence_without_changing_routing():
    c=fixture();original=deepcopy(c)
    r=classify_staple_overhangs(c,{'counts':[]})
    assert c==original and r['resolved'] and r['accepted_bases']==2
    assert r['table_fallback_bases']==2 and r['image_verified_bases']==0
    assert r['runs'][0]['sequence']=='AC' and r['runs'][0]['position']=='five_prime'


def test_image_conflict_is_noted_and_resolved_by_preference_without_changing_sources():
    labels=[{'helix':0,'bp':3,'direction':-1,'base':'T'},
            {'helix':0,'bp':2,'direction':-1,'base':'C'}]
    r=classify_staple_overhangs(fixture(),{'counts':[]},labels)
    assert r['conflicting_bases']==1 and r['resolved'] and r['accepted_bases']==2
    assert r['runs'][0]['sequence']=='TC' and r['runs'][0]['table_sequence']=='AC'
    assert r['conflicts'][0]['selected_base']=='T'
    assert r['conflicts'][0]['severity']=='notice'
    assert r['conflicts'][0]['selection_reason']=='preference_tie_break'
    assert r['runs'][0]['classification']=='on_helix_overhang'


def test_registration_and_readable_partial_image():
    r=classify_staple_overhangs(fixture(),{'counts':[]},
        [{'helix':0,'bp':0,'direction':-1,'base':'A'}],base_index_offset=3)
    assert r['resolved'] and r['image_verified_bases']==r['table_fallback_bases']==1


def test_internal_unpaired_segment_is_on_helix_not_a_terminal_extension():
    c=fixture();c['scaf'][0]['sites']=[(0,3),(0,0)]
    r=classify_staple_overhangs(c,{'counts':[]})
    assert r['runs'][0]['sequence']=='CG' and r['runs'][0]['position']=='internal'


def test_bad_length_and_ambiguous_polarity_remain_unresolved():
    c=fixture();c['stap'][0]['table_row']['sequence']='ACG'
    assert not classify_staple_overhangs(c,{'counts':[]})['resolved']
    c=fixture();c['stap'][0]['sites']=[(0,3),(0,2),(0,0),(0,1)]
    assert not classify_staple_overhangs(c,{'counts':[]})['resolved']


def test_fallback_does_not_inflate_independent_matches_or_clear_other_blockers():
    search={'best':{'unknown_bases':2,'compared_bases':2,'mismatches':0,'exact_staples':0},
            'best_ties':1,'invalid_staple_rows':[],'matched_rows':1,'table_rows':2,
            'unmatched_table_rows':1,'length_discrepancy':1,'resolved':False}
    r=apply_overhang_evidence(search,classify_staple_overhangs(fixture(),{'counts':[]}))
    assert r['assigned_overhang_bases']==2 and r['unresolved_partner_bases']==0
    assert r['best']==search['best'] and not r['resolved']
    assert len(r['confidence']['penalties'])==2


def test_visible_base_glyphs_ignore_damaged_unicode_map():
    import pymupdf
    from backend.core.publication_base_labels import extract_base_labels
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((40,100),'ACGT',fontsize=20,fontname='cour')
        class DamagedTextMap:
            def get_texttrace(self):
                spans=deepcopy(page.get_texttrace())
                for span in spans:
                    span['chars']=tuple((ord(chr(c[0]).translate(str.maketrans('ACGT','TACG'))),*c[1:]) for c in span['chars'])
                return spans
            def get_pixmap(self,**kwargs):return page.get_pixmap(**kwargs)
        damaged=DamagedTextMap()
        assert ''.join(chr(c[0]) for c in damaged.get_texttrace()[0]['chars'])=='TACG'
        labels=extract_base_labels(damaged,{'origin_x':0,'points_per_base':12,'row_centers':{0:100,1:140}})
    assert ''.join(l['base'] or '?' for l in labels)=='ACGT'


def test_d009_real_glyphs_classify_overhangs_and_retain_conflicts():
    import json
    from pathlib import Path
    import pytest
    import pymupdf
    from backend.core.publication_routing import extract_publication_paths,staple_tables,pair_endpoint_table,classify_scaffold
    pdf=Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf')
    if not pdf.exists():pytest.skip('Local publication corpus absent')
    with pymupdf.open(pdf) as doc:
        graph=extract_publication_paths(doc[5]);table=next(t for t in staple_tables(doc) if t['page']==14)
    pairing=pair_endpoint_table(graph,table);classified=classify_scaffold(pairing)
    before=json.dumps(classified,sort_keys=True)
    result=classify_staple_overhangs(classified,{'counts':[]},graph['base_labels'],base_index_offset=pairing['base_index_offset'])
    assert json.dumps(classified,sort_keys=True)==before
    assert result['bases']==276 and result['conflicting_bases']==2
    conflicts=[b for run in result['runs'] for b in run['bases'] if b['status']=='conflict']
    assert {tuple(b['site']) for b in conflicts}=={(8,117),(9,118)}
    assert all(b['image_base']=='A' and b['table_base']=='T' for b in conflicts)
    assert result['accepted_bases']==276 and result['resolved']
    assert all(b['selected_base']=='T' for b in conflicts)
    if Path('/usr/share/fonts/truetype/noto/NotoSansMono-Regular.ttf').exists():
        assert result['image_verified_bases']==266 and result['table_fallback_bases']==8


def test_paired_insertions_shift_table_offset_of_forward_three_prime_overhang():
    c={'scaf':[{'sites':[(0,0),(0,1)]}], 'stap':[{'path_id':0,
       'sites':[(0,0),(0,1),(0,2),(0,3)],'table_row':{'sequence':'GGGACT'}}]}
    result=classify_staple_overhangs(c,{'counts':[(0,0,2)]})
    run=result['runs'][0]
    assert run['sequence']=='CT' and run['table_start']==4 and run['table_end_exclusive']==6
    assert run['position']=='three_prime' and run['direction']==1
