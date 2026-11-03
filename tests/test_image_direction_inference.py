"""Image direction evidence must retain reversal freedom and reject contradictions."""
import pytest
from backend.core.image_direction_inference import propagate_directions, track_hypotheses, crossover_corroboration


def test_crossovers_without_anchor_leave_global_reversal():
    c=propagate_directions(['a','b','c'],[('a','b'),('b','c')],{})[0]
    assert c['status']=='global reversal unresolved'
    assert c['hypotheses']==[{'a':-1,'b':1,'c':-1},{'a':1,'b':-1,'c':1}]


def test_image_anchor_propagates_and_disconnected_tracks_remain_free():
    c=propagate_directions(['a','b','c'],[('a','b')],{'a':-1})
    assert c[0]['hypotheses']==[{'a':-1,'b':1}]
    assert len(c[1]['hypotheses'])==2


@pytest.mark.parametrize('edges,anchors', [([('a','b'),('b','c'),('c','a')],{}),([('a','b')],{'a':1,'b':1})])
def test_conflicts_do_not_get_majority_vote_direction(edges,anchors):
    c=propagate_directions(['a','b','c'],edges,anchors)
    assert c[0]['status']=='inconsistent'
    assert c[0]['hypotheses']==[]


def line(pid,y,color):
    return {'id':pid,'color':color,'flags':[],'closed':False,'primitives':[{'kind':'line','points':[[0,y],[20,y]]}]}


def test_scaffold_above_and_below_staple_have_opposite_directions():
    e={'paths':[line(0,10,[0,.4,.8]),line(1,11,[1,0,0]),line(2,31,[0,.4,.8]),line(3,30,[1,0,0])]}
    h=track_hypotheses(e)
    assert [t['signed_track_offset'] for t in h['tracks']]==[1,-1]
    assert [t['opposite_orientation_sign'] for t in h['tracks']]==[-1,1]
    assert crossover_corroboration(e,h)['opposite']==0


def test_equal_nearby_tracks_are_conflicting_not_resolved_by_reference():
    e={'paths':[line(0,10,[0,.4,.8]),line(1,11,[1,0,0]),line(2,9,[1,0,0])]}
    assert track_hypotheses(e)['tracks'][0]['signed_track_offset'] is None


def test_grid_color_is_not_staple_evidence():
    e={'paths':[line(0,10,[0,.4,.8]),line(1,11,[.8,.8,.8])]}
    assert track_hypotheses(e)['tracks']==[]


def test_isolated_junction_uses_attachment_endpoints_not_control_points():
    e={'paths':[line(0,10,[0,.4,.8]),line(1,11,[1,0,0]),line(2,31,[0,.4,.8]),line(3,30,[1,0,0])]}
    points=[[[20,10],[21,10]],[[21,10],[21,9]],[[21,9],[200,100],[200,100],[21,32]],[[21,32],[21,31]],[[21,31],[20,31]]]
    e['paths'].append({'id':4,'color':[0,.4,.8],'flags':[],'closed':False,'primitives':[{'kind':'bezier' if i==2 else 'line','points':p} for i,p in enumerate(points)]})
    check=crossover_corroboration(e,track_hypotheses(e))
    assert check['opposite']==1 and check['conflicting']==0
