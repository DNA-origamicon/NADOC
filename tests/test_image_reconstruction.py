"""Independent oracles for stage-two evidence and exact reference discrepancies."""
import pytest
import pymupdf
from backend.core.image_reconstruction import calibrated_index, cadnano_summary, compare_cadnano, extract_page_evidence


def simple_design():
    return {'vstrands':[{'num':0,'row':0,'col':0,
        'scaf':[[-1,-1,0,1],[0,0,0,2],[0,1,-1,-1]],
        'stap':[[-1]*4 for _ in range(3)],'loop':[0,2,0],'skip':[0,0,0]}]}


def test_piecewise_stretched_region_does_not_add_bases():
    anchors = [(10,13),(20,20),(30,27),(50,34)]
    assert calibrated_index(40, anchors) == 30.5
    assert calibrated_index(50, anchors) == 34
    with pytest.raises(ValueError, match='Outside'): calibrated_index(51, anchors)
    assert calibrated_index(15, [(10,34),(20,27)]) == 30.5


@pytest.mark.parametrize('anchors', [[(0,0)],[(0,0),(0,7)],[(0,0),(1,7),(2,6)],[(0,0),(1,float('nan'))]])
def test_calibration_rejects_ambiguous_anchors(anchors):
    with pytest.raises(ValueError): calibrated_index(.5, anchors)


def test_reference_counts_insertions_and_reports_broken_connectivity():
    d = simple_design()
    assert cadnano_summary(d)['counts']['scaf_nucleotides'] == 5
    assert cadnano_summary(d)['connectivity_problems'] == []
    d['vstrands'][0]['scaf'][1][0] = 99
    assert cadnano_summary(d)['connectivity_problems']


def test_nick_changes_are_not_silently_filled():
    original = simple_design(); observed = simple_design()
    observed['vstrands'][0]['scaf'][1][2:] = [-1,-1]
    observed['vstrands'][0]['scaf'][2] = [-1]*4
    result = compare_cadnano(observed, original)
    assert result['termini']['observed_only'] == [('scaf',0,1,'next')]
    assert result['termini']['reference_only'] == [('scaf',0,2,'next')]


def test_rotated_fragmented_paths_preserved_without_inferred_direction():
    with pymupdf.open() as doc:
        p = doc.new_page()
        p.draw_line((20,20),(20,100),color=(0,0,1))
        p.draw_bezier((20,100),(30,110),(40,110),(50,100),color=(0,0,1))
        result = extract_page_evidence(p)
    assert len(result['paths']) == 2
    assert result['paths'][1]['primitives'][0]['kind'] == 'bezier'
    assert result['status'] == 'uncalibrated evidence'
    assert all('direction' not in path for path in result['paths'])


def reviewed_route():
    return {'directions_reviewed':True,'termini_reviewed':True,'indels_reviewed':True,
            'registration_source':'image-reviewed','source_sha256':'a'*64,'evidence_ids':['path-7'],
            'lattice':'honeycomb','helices':[{'num':0,'row':0,'col':0},{'num':1,'row':0,'col':1}],
            'routes':[{'kind':'scaf','sites':[[0,0],[0,1],[1,1],[1,0]]}], 'indels':[]}


def test_compiler_preserves_single_branch_and_termini():
    from backend.core.image_reconstruction import compile_reviewed_routes
    result = compile_reviewed_routes(reviewed_route())
    assert result['audit']['crossovers'] == [['scaf',0,1,1,1]]
    assert len(result['audit']['termini']) == 2
    assert result['cadnano']['vstrands'][0]['stap'] == [[-1]*4 for _ in range(21)]
    assert result['cadnano']['vstrands'][1]['scaf'][1] == [0,1,1,0]


def test_compiler_refuses_to_guess_direction_or_fill_gaps():
    from backend.core.image_reconstruction import compile_reviewed_routes
    r = reviewed_route();r.pop('directions_reviewed')
    with pytest.raises(ValueError,match='directions_reviewed'):compile_reviewed_routes(r)
    r = reviewed_route();r['routes'][0]['sites'][1]=[0,3]
    with pytest.raises(ValueError,match='gaps'):compile_reviewed_routes(r)


def test_compiler_rejects_duplicate_sites_and_keeps_explicit_indels():
    from backend.core.image_reconstruction import compile_reviewed_routes
    r=reviewed_route();r['routes']*=2
    with pytest.raises(ValueError,match='Overlapping'):compile_reviewed_routes(r)
    r=reviewed_route();r['indels']=[{'helix':0,'bp':1,'delta':2}]
    assert compile_reviewed_routes(r)['audit']['counts']['scaf_nucleotides']==6


def test_same_counts_do_not_hide_shifted_insertion():
    original = simple_design(); observed = simple_design()
    observed['vstrands'][0]['loop'] = [2,0,0]
    result=compare_cadnano(observed,original)
    assert result['counts_observed'] == result['counts_reference']
    assert result['indels']['observed_only'] == [('scaf',0,0,2)]
    assert result['indels']['reference_only'] == [('scaf',0,1,2)]


def test_image_landmarks_expand_stretched_spans_and_single_junction():
    from backend.core.image_reconstruction import expand_reviewed_trace
    anchors={'0':[(10,0),(20,2),(40,4)],'1':[(10,0),(20,2),(40,4)]}
    trace=[{'helix':0,'x':10},{'helix':0,'x':40},{'helix':1,'x':40},{'helix':1,'x':20}]
    assert expand_reviewed_trace(trace,anchors,order='5prime-to-3prime') == [[0,0],[0,1],[0,2],[0,3],[0,4],[1,4],[1,3],[1,2]]
    with pytest.raises(ValueError,match='integer bp'):
        expand_reviewed_trace([{'helix':0,'x':15.5}],anchors,order='5prime-to-3prime')
    with pytest.raises(ValueError,match='Explicit'):
        expand_reviewed_trace(trace,anchors,order='PDF-path-order')
