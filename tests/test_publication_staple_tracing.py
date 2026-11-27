from pathlib import Path

import numpy as np
import pymupdf
import pytest

from backend.core.publication_lane_classification import classify_lanes, classify_point
from backend.core.publication_staple_tracing import trace_panel, classify_and_trace_page
from backend.core.publication_panel_registration import register_panels


def fixture(scaffold_color=(0,100,255)):
    rgb=np.full((160,240,3),255,dtype=np.uint8)
    centers=list(range(20,141,24))
    colors=[(0,180,0),(0,180,0),(220,0,0),(220,0,220),(0,100,255),(220,150,0)]
    for i,center in enumerate(centers):
        y=center+(-3 if i%2==0 else 3)
        rgb[y,20:221]=scaffold_color
        staple=center+(3 if i%2==0 else -3)
        left,right=(45,106) if i==0 else (105,156) if i==1 else (60,181)
        rgb[staple,left:right]=colors[i]
    rgb[23:42,105]=(0,180,0)
    return rgb,{'grid_pitch':4.,'row_pitch':24.,'row_centers':centers}


def test_classification_uses_layout_and_recurrence_not_fixed_blue_color():
    for color in ((0,100,255),(255,80,0)):
        rgb,grid=fixture(color)
        lanes=classify_lanes(rgb,grid)
        assert lanes['status']=='panel_pattern_supported'
        assert classify_point(17,lanes)[0]=='scaffold'
        assert classify_point(23,lanes)[0]=='staple'
        assert classify_point(119,lanes)[0]=='staple'  # blue staple is retained
        assert classify_point(113,lanes)[0]=='scaffold'


def test_connected_staple_trace_follows_visible_crossover_between_lanes():
    rgb,grid=fixture();result=trace_panel(rgb,grid)
    paths=[t for t in result['traces'] if t['kind']=='staple' and len(t['domains'])>=2]
    assert len(paths)==1
    assert {d['observed_row_index'] for d in paths[0]['domains']}=={0,1}
    assert paths[0]['status']=='unbranched_staple_trace'
    assert not paths[0]['terminal_markers_verified']
    assert not paths[0]['native_routing_resolved']


def test_missing_pixels_are_not_joined_by_proximity():
    rgb,grid=fixture();rgb[23,70:73]=255
    result=trace_panel(rgb,grid)
    for trace in result['traces']:
        if trace['kind']=='staple':
            points=trace['points_pixels']
            assert not (any(x<70 and y==23 for x,y in points) and any(x>72 and y==23 for x,y in points))


def test_distinct_color_crossing_preserves_staple_continuation():
    rgb,grid=fixture();rgb[8:38,75]=(220,0,220)
    result=trace_panel(rgb,grid)
    assert result['resolved_crossings']
    green=[t for t in result['traces'] if t['kind']=='staple' and len(t['domains'])>=2]
    assert green
    assert any(any(x==45 and y==23 for x,y in t['points_pixels']) for t in green)


def test_same_color_crossing_stays_ambiguous():
    rgb,grid=fixture();rgb[8:38,75]=(0,180,0)
    result=trace_panel(rgb,grid)
    assert result['unresolved_junction_count']>0
    assert any(t['status']=='staple_trace_fragment' for t in result['traces'])
    for trace in result['traces']:
        if trace['kind']=='staple':
            assert not (any(x<75 and y==23 for x,y in trace['points_pixels']) and any(x>75 and y==23 for x,y in trace['points_pixels']))


def test_uniform_two_lane_color_cannot_establish_scaffold_identity():
    rgb,grid=fixture();chromatic=rgb.min(2)<255;rgb[chromatic]=(0,100,255)
    assert classify_lanes(rgb,grid)['status']=='scaffold_lane_pattern_ambiguous'
    assert not trace_panel(rgb,grid)['traces']


def test_d014_false_positive_spans_are_classified_as_scaffold():
    source=Path('experiments/origami_publication_catalog/assets/sources/PMC6906287-41467_2019_13284_MOESM2_ESM.pdf')
    if not source.exists():pytest.skip('Optional local publication corpus')
    with pymupdf.open(source) as doc:
        page=doc[44];result=classify_and_trace_page(page,register_panels(page))
    flap=next(p for p in result['panels'] if p['placement_index']==1)
    # User-specified low-bp examples: visible helices 86 and 89.
    assert any(414<c['span_pdf'][0][0]<416 and 522<c['span_pdf'][0][1]<524
               for c in flap['partial_connectors']['candidates'])
    # User correction: helix 86's isolated pixel belongs to a bp-index label.
    assert not any(413<m['center_pdf'][0]<417 and 518<m['center_pdf'][1]<520
               for m in flap['offset_marker_annotations']['candidates'])
    # Coordinates are measured source-PDF evidence, not native helix identities.
    for placement,y in [(1,465.7193908691406),(1,525.8919799804687),(4,98.81572723388672)]:
        panel=next(p for p in result['panels'] if p['placement_index']==placement)
        candidates=[]
        for row in panel['lane_classification']['rows']:
            for side,lane in enumerate(row['lane_y_pdf']):
                candidates.append((abs(y-lane),side,row))
        distance,side,row=min(candidates,key=lambda v:v[0])
        assert distance <= row['tolerance_pdf']
        assert side == row['scaffold_side']
    assert any(t['kind']=='staple' and t['color_continuity_supported'] and
               len({d['observed_row_index'] for d in t['domains'] if d['kind']=='staple'})>=2
               for p in result['panels'] for t in p['traces'])
    from backend.core.publication_anchor_image_mapping import image_span_candidates
    mapped=image_span_candidates({'classified_tracing':result},{'minimum_length':12,'anchors':[]})
    assert mapped['excluded_scaffold_domains']>0
    for placement,y in [(1,465.7193908691406),(1,525.8919799804687),(4,98.81572723388672)]:
        assert not any(s['placement_index']==placement and abs(s['span_pdf'][0][1]-y)<.7 for s in mapped['spans'])


def test_tracing_uses_visible_composition_and_does_not_recover_occluded_strokes():
    import io
    from PIL import Image
    rgb,grid=fixture();image=io.BytesIO();Image.fromarray(rgb).save(image,format='PNG')
    with pymupdf.open() as doc:
        page=doc.new_page(width=240,height=160)
        xref=page.insert_image(page.rect,stream=image.getvalue())
        page.draw_rect(page.rect,fill=(1,1,1),color=(1,1,1),overlay=True)
        report=classify_and_trace_page(page,{'panels':[{'xref':xref,'width':240,'height':160,**grid}]})
        assert not report['panels'][0]['traces']
        assert report['panels'][0]['lane_classification']['status']=='paired_lanes_not_detected'


def test_truncated_graph_does_not_claim_unbranched_traces():
    rgb,grid=fixture()
    report=trace_panel(rgb,grid,maximum_edges=1)
    assert report['truncated']
    assert not any(t['status']=='unbranched_staple_trace' for t in report['traces'])


def test_local_color_contradiction_is_not_overridden_by_panel_phase():
    rgb,grid=fixture()
    rgb[65,20:121]=(220,0,0)  # expected scaffold side is only half blue
    rgb[71,60:181]=(0,100,255)  # opposite lane provides stronger conflicting evidence
    lanes=classify_lanes(rgb,grid)
    assert lanes['status']=='panel_pattern_supported'
    assert lanes['rows'][2]['local_phase_contradiction']
    assert lanes['rows'][2]['scaffold_side'] is None
    assert classify_point(65,lanes)[0]=='unclassified'


def test_staple_connector_drawing_is_retained_without_an_extra_domain():
    from skimage.draw import line
    rgb,grid=fixture()
    rgb[23,45:106]=255;rgb[23:42,105]=255
    points=[(45,23),(65,23),(69,29),(89,29),(93,23),(113,23)]
    for a,b in zip(points,points[1:]):
        yy,xx=line(a[1],a[0],b[1],b[0]);rgb[yy,xx]=(0,180,0)
    result=trace_panel(rgb,grid)
    connected=[t for t in result['traces'] if t['connector_annotations']]
    assert len(connected)==1
    assert connected[0]['kind']=='staple'
    assert len(connected[0]['domains'])==2
    assert all(d['kind']=='staple' for d in connected[0]['domains'])
    assert result['connector_drawing_count']==1


def test_dark_gray_staple_ink_is_retained_without_tracing_light_grid_lines():
    rgb,grid=fixture()
    green=(rgb[:,:,0]==0)&(rgb[:,:,1]==180)&(rgb[:,:,2]==0)
    rgb[green]=(140,140,140)
    rgb[5,:]=(215,215,215)  # light neutral grid/background remains excluded
    report=trace_panel(rgb,grid)
    assert any(t['kind']=='staple' and 12 in t['hue_bins'] and len(t['domains'])>=2 for t in report['traces'])
    assert not any(any(y==5 for x,y in t['points_pixels']) for t in report['traces'])
