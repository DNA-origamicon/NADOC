"""Published-source regression tests; extraction never consumes native files."""
import base64
from pathlib import Path

import pymupdf
import pytest

from backend.core.publication_diagram_labels import numeric_labels
from backend.core.publication_routing import pair_endpoint_table, classify_scaffold, staple_tables

ASSETS=Path('experiments/origami_publication_catalog/assets')


def test_endpoint_registration_and_independent_directions():
    paths=[{'sites':[(h,b) for b in range(4)],'path_id':h} for h in range(3)]
    table={'rows':[{'start':[h,7], 'end':[h,4], 'length':4,'sequence':'ACGT'} for h in range(3)]}
    result=pair_endpoint_table({'paths':paths},table)
    assert result['offset_resolved'] and result['base_index_offset']==4
    assert result['all_table_endpoints_matched']
    assert all(p['sites'][0]==(h,7) for h,p in enumerate(result['matched']))
    ambiguous={'rows':table['rows']+[dict(r,start=[h,17],end=[h,14]) for h,r in enumerate(table['rows'])]}
    assert not pair_endpoint_table({'paths':paths},ambiguous)['offset_resolved']


def test_nonlocal_edges_do_not_vote_as_backbone_direction():
    pairing={'matched':[{'sites':[(0,b) for b in range(8)]}],
             'unmatched_paths':[{'sites':[(0,b) for b in range(7,-1,-1)]+[(0,20)]}]}
    result=classify_scaffold(pairing)
    assert len(result['scaf'])==1 and not result['unresolved']
    assert result['scaf'][0]['sites'][-1]==(0,20)


def test_table_keeps_length_disagreements_explicit():
    with pymupdf.open() as doc:
        p=doc.new_page();p.insert_text((40,40),'Start End Sequence Length Color\n0[4] 1[8] ACGTACGTACGT 14 #aabbcc')
        tables=staple_tables(doc)
    assert len(tables)==1
    assert not tables[0]['sequence_lengths_valid']
    assert tables[0]['rows'][0]['sequence']=='ACGTACGTACGT'


def test_digits_are_decoded_from_visible_shapes_even_with_wrong_digit_mapping():
    with pymupdf.open() as doc:
        page=doc.new_page();page.insert_text((50,50),'0123456789',fontsize=20)
        font=page.get_fonts()[0][0]
        xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
        mappings='\n'.join(f'<{48+i:02x}> <{48+(i+3)%10:04x}>' for i in range(10))
        doc.update_stream(xref,('begincmap\n1 begincodespacerange\n<00> <ff>\nendcodespacerange\n10 beginbfchar\n'+mappings+'\nendbfchar\nendcmap').encode())
        doc.xref_set_key(font,'ToUnicode',f'{xref} 0 R')
        # Separate spans, each under the short-label bound.
        for i in range(10):page.insert_text((50+i*30,100+i*20),str(i),fontsize=20)
        data=doc.tobytes()
    with pymupdf.open(stream=data,filetype='pdf') as doc:
        result=numeric_labels(doc[0])
    assert [r['value'] for r in result]==list(range(10))


@pytest.mark.skipif(not (ASSETS/'sources/shapes-supp.pdf').exists(),reason='Local publication corpus not installed')
def test_original_publication_corpus_against_independent_references():
    from tools.design_archive.publication_routing_benchmark import audit
    report=audit(ASSETS)
    rows=report['designs']
    assert [r['matched_staples'] for r in rows]==[144,148,187,217,209]
    assert [r['routing_exact'] for r in rows]==[False,False,False,True,True]
    assert all(r['comparison']['scaf']['missing_sites']==0 for r in rows)
    assert all(c['wrong_pointers']==0 and c['extra_sites']==0 for r in rows for c in r['comparison'].values())
    assert rows[0]['comparison']['stap']['missing_sites']==1680
    assert rows[1]['base_index_offset']==4
    assert rows[0]['lattice_mismatches']==0
    assert [r['reference_topology_recovered'] for r in rows]==[False,False,False,True,False]
    assert rows[3]['insertions_exact'] and rows[3]['lattice_mismatches']==0
    assert [0,70,144] in rows[3]['insertion_solution']['counts']


@pytest.mark.skipif(not (ASSETS/'sources/twist-supp.pdf').exists(),reason='Local publication corpus not installed')
def test_original_publication_detection_uses_pdf_only(monkeypatch):
    from backend.core.article_design_detection import detect_designs
    with pymupdf.open(ASSETS/'sources/twist-supp.pdf') as source, pymupdf.open() as doc:
        for page in (18,19,36,38):doc.insert_pdf(source,from_page=page,to_page=page)
        data=doc.tobytes()
    def denied(*args,**kwargs):
        raise AssertionError('Extraction attempted to read a reference file')
    monkeypatch.setattr(Path,'read_bytes',denied)
    monkeypatch.setattr(Path,'read_text',denied)
    report=detect_designs({'paper':{'name':'publication.pdf','data':base64.b64encode(data).decode()}})
    observed=[p['publication_evidence']['matched_staples'] for d in report['designs'] for p in d['pairings'] if 'publication_evidence' in p]
    assert 217 in observed and 209 in observed
    assert not report['can_reconstruct']


def test_scaffold_mass_balance_resolves_only_one_observed_unknown_loop():
    from backend.core.publication_routing import resolve_insertions
    pairing={'unit_insertions':[(0,0)],'unresolved_insertions':[(0,1)],'matched':[]}
    classified={'scaf':[{'sites':[(0,b) for b in range(10)]}]}
    result=resolve_insertions(pairing,classified,{'context':'bundle (p25 scaffold)'})
    assert result['counts']==[[0,0,1],[0,1,14]]
    assert not result['unresolved']
    pairing['unresolved_insertions'].append((0,2))
    result=resolve_insertions(pairing,classified,{'context':'bundle (p25 scaffold)'})
    assert result['unresolved']==[(0,1),(0,2)]
    assert result['counts']==[[0,0,1]]
