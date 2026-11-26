"""Exact Pointer oracle, blind vector extraction and damaged-image rejection.

The reference is used only by the renderer/validator. Extraction functions see
only rendered PDF bytes, scaffold sequence and published oligos.
"""
import gzip
import json
from pathlib import Path

import pymupdf
import pytest

from backend.core.diagram_route_extraction import extract_routing, recover_vector_graph, orient_with_sequences
from backend.core.sequences import M13MP18_SEQUENCE
from tools.design_archive.pointer_image_benchmark import render_reference, compare_routing

FIXTURES=Path(__file__).parent/'fixtures'


@pytest.fixture(scope='module')
def pointer():
    source=json.loads(gzip.decompress((FIXTURES/'cadnano_dietz_pointer.json.gz').read_bytes()))
    staples=json.loads((FIXTURES/'dietz_pointer_2017_staples.json').read_text())['sequences']
    return source,staples


@pytest.mark.parametrize('scale,pitch,seed,fragment',[(3,24,19,True),(2.25,31,87,False),(4.7,20,1001,True)])
def test_exact_pointer_from_visible_diagram_at_varied_scales(pointer,scale,pitch,seed,fragment):
    source,staples=pointer
    data=render_reference(source,scale=scale,row_pitch=pitch,shuffle_seed=seed,fragment=fragment)
    result=extract_routing(data,M13MP18_SEQUENCE,staples)
    comparison=compare_routing(source,result)
    assert comparison['complete'],comparison
    assert comparison['expected_sites']==comparison['recovered_sites']==15240
    assert comparison['wrong_pointers']==comparison['missing_sites']==comparison['extra_sites']==0
    assert comparison['width_match']
    assert result['best']['matched_staples']==161
    assert result['best']['paired_bases_verified']==7249
    assert result['unknown_bases']==740
    assert result['hypotheses_tested']>1


def test_source_graph_is_not_consulted_by_extractor(pointer,monkeypatch):
    source,staples=pointer
    data=render_reference(source)
    # Deny reference-file reads after preparing the image and sequences.
    monkeypatch.setattr(Path,'read_bytes',lambda *a,**k: pytest.fail('Extractor attempted a file read'))
    monkeypatch.setattr(Path,'read_text',lambda *a,**k: pytest.fail('Extractor attempted a file read'))
    assert extract_routing(data,M13MP18_SEQUENCE,staples)['resolved']


def test_wrong_sequences_do_not_produce_a_directed_solution(pointer):
    source,_=pointer
    graph=recover_vector_graph(render_reference(source))
    result=orient_with_sequences(graph,M13MP18_SEQUENCE,['A'*40]*161)
    assert not result['resolved']
    assert 'directed_paths' not in result
    assert result['best']['matched_staples']==0


def test_missing_ruler_is_explicitly_unresolved(pointer):
    source,_=pointer
    with pymupdf.open(stream=render_reference(source),filetype='pdf') as doc:
        doc[0].add_redact_annot(pymupdf.Rect(0,0,doc[0].rect.width,45))
        doc[0].apply_redactions()
        damaged=doc.tobytes()
    with pytest.raises(ValueError,match='ruler'):
        recover_vector_graph(damaged)


def test_deleted_annotation_cannot_be_filled_from_reference(pointer):
    source,staples=pointer
    with pymupdf.open(stream=render_reference(source),filetype='pdf') as doc:
        # Remove only the visible red deletion X, leaving routes intact.
        for xref in doc[0].get_contents():
            stream=doc.xref_stream(xref)
            if b'.8 0 0 RG' in stream or b'0.8 0 0 RG' in stream:
                doc.update_stream(xref,b'')
        damaged=doc.tobytes()
    with pytest.raises(ValueError,match='7249'):
        extract_routing(damaged,M13MP18_SEQUENCE,staples)


def test_detect_designs_exposes_recovered_pointer_topology(pointer):
    import base64
    from backend.core.article_design_detection import detect_designs
    source,staples=pointer
    encode=lambda data,name: {'name':name,'data':base64.b64encode(data).decode()}
    report=detect_designs({'paper':encode(render_reference(source),'pointer-image.pdf'),
                           'staple_lists':[encode(json.dumps(staples).encode(),'staples.json')]})
    recovered=[p for d in report['designs'] for p in d['pairings'] if p.get('routing_recovered')]
    assert len(recovered)==1
    routing=recovered[0]['routing']
    assert len(routing['directed_paths']['stap'])==161
    assert len(routing['lattice'])==82
    assert routing['deletions']==[(36,126)]
    assert recovered[0]['direction_resolved']
    assert report['method']=='vector-graph-and-staple-hypotheses-v2'
