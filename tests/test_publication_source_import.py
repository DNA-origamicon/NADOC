import io
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image

from backend.core.publication_table_import import annotate_sequence, import_pdf_tables
from backend.core.publication_raster_tracing import trace_mask, register_and_trace


def test_chemistry_is_not_sequence_and_support_depends_on_location():
    row = annotate_sequence('/5Cy5/ACGTACGT/iCy3/TTTT', 'Pal+Lock LockToe Dye_handle')
    assert row['sequence'] == 'ACGTACGTTTTT'
    assert [m['status'] for m in row['modifications']] == [
        'supported_terminal_label_pending_route', 'unsupported_internal_modification', 'unsupported_lipid']
    assert row['modifications'][1]['offset'] == 8
    assert {o['label'] for o in row['overhang_annotations']} == {'handle','toehold'}
    assert annotate_sequence('/DYE/ACGT')['modifications'][0]['status'] == 'unsupported_modification'


def test_table_columns_continuations_and_bold_boundaries():
    doc = pymupdf.open()
    page = doc.new_page()
    for x,text in [(50,'Module'),(150,'Notes'),(250,'DNA Sequence')]:page.insert_text((x,70),text)
    for x,text in [(50,'Top_A'),(150,'LockToe'),(250,'AAAACCCC')]:page.insert_text((x,100),text)
    page = doc.new_page()
    page.insert_text((250,70),'GGGGTTTT',fontname='hebo')
    tables = import_pdf_tables(doc)
    assert len(tables)==1 and tables[0]['pages']==[1,2]
    assert tables[0]['rows'][1]['possible_continuation_of']==tables[0]['rows'][0]['id']
    assert tables[0]['rows'][1]['functional_spans']==[{'start':0,'end':8}]
    assert tables[0]['rows'][1]['sequence']=='GGGGTTTT'  # no silent concatenation
    doc.close()


def test_trace_preserves_branch_ambiguity_and_closed_cycles():
    mask = np.zeros((20,20),bool); mask[10,2:18]=True;mask[2:18,10]=True
    paths,nodes,truncated = trace_mask(mask)
    assert len(paths)==4 and not truncated
    assert ((10,10),4) in nodes
    mask[:]=False;mask[3,3:15]=True;mask[14,3:15]=True;mask[3:15,3]=True;mask[3:15,14]=True
    paths,_,_ = trace_mask(mask)
    assert len(paths)==1 and paths[0][0]==paths[0][-1]
    assert trace_mask(mask,max_edges=0)[2]


def test_visible_composite_and_rotated_page_registration():
    pixels=np.full((80,100,3),255,dtype=np.uint8);pixels[39:42,10:90]=[255,0,0]
    stream=io.BytesIO();Image.fromarray(pixels).save(stream,format='PNG')
    doc=pymupdf.open();page=doc.new_page(width=100,height=80)
    page.insert_image(page.rect,stream=stream.getvalue())
    page.draw_rect(pymupdf.Rect(45,0,55,80),color=None,fill=(1,1,1),overlay=True)
    page.set_rotation(90)
    result=register_and_trace(page)
    paths=[p for layer in result['layers'] for p in layer['paths_pdf']]
    assert len(paths)==2  # white overlay splits visible routing
    assert all(abs(y-40)<2 for path in paths for x,y in path)
    assert all(not (min(x for x,y in p)<45 and max(x for x,y in p)>55) for p in paths)
    doc.close()


def test_d014_real_table_retains_all_rows_and_modifications():
    source=Path('experiments/origami_publication_catalog/assets/sources/PMC6906287-41467_2019_13284_MOESM2_ESM.pdf')
    if not source.exists():pytest.skip('Optional publication fixture unavailable')
    with pymupdf.open(source) as doc:tables=import_pdf_tables(doc)
    table=next(t for t in tables if t['page']==46)
    assert table['pages']==[46,47,48,49]
    assert len(table['rows'])==270
    assert table['module_counts']['Top_A']==table['module_counts']['Top_B']==20
    assert sum(len([m for m in r['modifications'] if m.get('token')]) for r in table['rows'])==4
    base=[r for r in table['rows'] if r['module'] in ('Top_A','inner') or r['module'].startswith(('cyl','flap'))]
    assert len(base)==219


def test_source_package_retains_selected_rows_and_trace_limits():
    import base64, hashlib, json, zipfile
    from backend.core.article_native_reconstruction import reconstruct_package
    doc=pymupdf.open();page=doc.new_page(width=400,height=300)
    pixels=np.full((20,80,3),255,dtype=np.uint8);pixels[10,5:75]=[255,0,0]
    image=io.BytesIO();Image.fromarray(pixels).save(image,format='PNG')
    page.insert_image(pymupdf.Rect(20,20,100,40),stream=image.getvalue())
    page=doc.new_page()
    for x,text in [(50,'Module'),(150,'Notes'),(250,'DNA Sequence')]:page.insert_text((x,70),text)
    for x,text in [(50,'Top_A'),(150,'LockToe'),(250,'/5Cy5/AAAACCCC')]:page.insert_text((x,100),text)
    data=doc.tobytes();doc.close()
    choice={'source_sha256':hashlib.sha256(data).hexdigest(),'diagram_page':1,'table_page':2,'table_modules':['Top_A']}
    payload={'paper':{'name':'test.pdf','data':base64.b64encode(data).decode()},'selections':[choice]}
    with zipfile.ZipFile(io.BytesIO(reconstruct_package(payload))) as archive:
        report=json.loads(archive.read('Reconstructed-1-p1.reconstruction.json'))
        evidence=json.loads(archive.read(report['source_evidence']))
        assert evidence['selected_row_ids']==['p2-r1']
        assert evidence['raster_evidence']['path_count']>0
        assert evidence['annotations'][0]['overhangs'][0]['label']=='toehold'
        assert [p['minimum_domain'] for p in evidence['sequence_fallback']['passes']]==[8,6]
        assert not evidence['sequence_fallback']['native_routing_resolved']
        assert report['sequence_fallback_summary']['status']=='candidate_domains_only'
        assert report['classification']['output'] == 'report_only'
        issues = {issue['code']: issue for issue in report['classification']['issues']}
        assert issues['sequence_alignment_unresolved']['severity'] == 'blocking'
        assert issues['base_register_unresolved']['stage'] == 'diagram'
        assert issues['annotation_pending_route']['row_ids'] == ['p2-r1']
        assert 'anchors' in evidence['sequence_fallback']
        assert 'anchor_refinement' in evidence['sequence_fallback']
        assert not evidence['sequence_fallback']['image_anchor_candidates']['native_routing_resolved']
        assert 'refinement_summary' in report['sequence_fallback_summary']
        assert 'connector_hypotheses' in report['sequence_fallback_summary']['refinement_summary']
        assert 'offset_endpoint_markers' in report['sequence_fallback_summary']['refinement_summary']
        assert not any(n.endswith('.nadoc') for n in archive.namelist())
        assert any(n.endswith('source.pdf') for n in archive.namelist())


def test_raster_sampling_preserves_native_detail_and_reports_resource_cap():
    pixels=np.full((160,400,3),255,dtype=np.uint8);pixels[80,20:380]=[255,0,0]
    image=io.BytesIO();Image.fromarray(pixels).save(image,format='PNG')
    with pymupdf.open() as doc:
        page=doc.new_page(width=100,height=80)
        page.insert_image(pymupdf.Rect(0,0,100,40),stream=image.getvalue())
        result=register_and_trace(page)
        assert result['registration']['pixels_per_pdf_point']==4
        assert result['registration']['native_resolution_retained']
        capped=register_and_trace(page,max_dimension=200)
        assert capped['registration']['pixels_per_pdf_point']==2
        assert not capped['registration']['native_resolution_retained']


def test_large_selected_table_keeps_source_evidence_when_sequence_budget_is_exceeded(monkeypatch):
    import backend.core.publication_import_evidence as evidence
    rows=[{'id':f'r{i}','module':'base','sequence':'ACGTACGT','modifications':[],'overhang_annotations':[]} for i in range(501)]
    table={'page':1,'pages':[1],'rows':rows,'module_counts':{'base':501}}
    monkeypatch.setattr(evidence,'import_pdf_tables',lambda doc:[table])
    monkeypatch.setattr(evidence,'register_and_trace',lambda page:{'status':'test_raster'})
    with pymupdf.open() as doc:
        doc.new_page();data=doc.tobytes()
    result=evidence.extraction_evidence(data,{'diagram_page':1,'table_page':1,'table_modules':['base']})
    assert result['sequence_fallback']['status']=='row_budget_exceeded'
    assert len(result['selected_row_ids'])==501
    assert result['table_import']==table
