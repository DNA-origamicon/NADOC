"""Behavioral safeguards for continuous staple construction and route selection."""
import pytest
from backend.core.publication_precursors import staple_precursors
from tools.design_archive.recorded_authoring import select_route
from experiments.recorded_review_process import ProcessRequired


def fixture(end=9, jump=9):
    scaffold = {'sites': [(0,b) for b in range(end+1)]}
    staple = {'sites': [(0,1),(0,0),(0,jump),(0,jump-1)]}
    def draw(a,b):
        return {'kind':'strand-add','label':'draw','params':{'domains':[{
            'helix_id':'h','start_bp':a,'end_bp':b,'direction':'REVERSE'}]},'evidence':[]}
    assign = lambda: {'kind':'strand-sequence','label':'seq','params':{'strand_id':'old'},'evidence':[]}
    ops = [draw(0,end),assign(),draw(1,0),draw(jump,jump-1),
           {'kind':'forced-ligation-create','label':'join','params':{},'evidence':[]},assign()]
    return ops,[scaffold,staple]


def test_end_wrap_requires_explicit_polymerization_confirmation():
    ops,paths=fixture()
    result,counts=staple_precursors(ops,paths,{0:'h'},str)
    assert counts['periodic_seams']==0
    assert not any(o['params'].get('is_periodic_seam') for o in result)
    ops,paths=fixture()
    result,counts=staple_precursors(ops,paths,{0:'h'},str,periodic_seams=True)
    assert counts['periodic_seams']==1
    assert counts['pen_strokes']==0
    assert sum(o['params'].get('is_periodic_seam',False) for o in result)==1


def test_internal_jump_is_not_reclassified_as_polymerization():
    ops,paths=fixture(end=12,jump=9)
    result,counts=staple_precursors(ops,paths,{0:'h'},str,periodic_seams=True)
    assert counts['periodic_seams']==0
    assert not any(o['params'].get('is_periodic_seam') for o in result)


def test_precursors_preserve_occupancy_gaps_and_published_terminal_nicks():
    paths = [{'sites': [(0,b) for b in range(8)]}]
    ops = []
    for start, end in ((0,7), (0,1), (2,3), (6,7)):
        ops.extend([
            {'kind':'strand-add','params':{'domains':[{'helix_id':'h',
             'start_bp':start,'end_bp':end,'direction':'FORWARD'}]}},
            {'kind':'strand-sequence','params':{'strand_id':'old'}},
        ])
        if (start,end) != (0,7):
            paths.append({'sites':[(0,b) for b in range(start,end+1)]})
    result, counts = staple_precursors(ops, paths, {0:'h'}, str)
    pens = [o['params']['domains'][0] for o in result
            if o.get('label') == 'Draw continuous staple precursor']
    assert [(d['start_bp'],d['end_bp']) for d in pens] == [(0,3),(6,7)]
    assert counts == {'pen_strokes':2,'endpoint_nicks':1,'periodic_seams':0}
    assert [o['params']['bp_index'] for o in result if o['kind']=='nick'] == [1]


def test_route_selection_requires_complete_directed_match():
    from types import SimpleNamespace as NS
    domain=NS(helix_id='h',start_bp=3,end_bp=0,direction=NS(value='REVERSE'))
    strand=NS(is_scaffold=False,id='s',domains=[domain])
    design=NS(strands=[strand])
    route=[['h',b] for b in (3,2,1,0)]
    assert select_route(design,route)=='s'
    for invalid in (route[:-1],list(reversed(route))):
        with pytest.raises(ProcessRequired):select_route(design,invalid)
    design.strands.append(strand)
    with pytest.raises(ProcessRequired):select_route(design,route)


def test_full_span_pen_removes_only_unobserved_gap_with_recorded_operations():
    paths=[{'sites':[(0,b) for b in range(12)]}];ops=[]
    for start,end in ((0,11),(0,3),(6,7),(10,11)):
        ops.extend([{'kind':'strand-add','params':{'domains':[{'helix_id':'h','start_bp':start,
                    'end_bp':end,'direction':'FORWARD'}]}},
                    {'kind':'strand-sequence','params':{'strand_id':'old'}}])
        if (start,end)!=(0,11):paths.append({'sites':[(0,b) for b in range(start,end+1)]})
    result,counts=staple_precursors(ops,paths,{0:'h'},str,span_gaps=True)
    pens=[o for o in result if o.get('label')=='Draw continuous staple precursor']
    assert counts['pen_strokes']==1
    assert pens[0]['params']['domains'][0]['end_bp']==11
    assert [o['select_route'] for o in result if o['kind']=='strand-delete-batch']==[
        [['h',4],['h',5]],[['h',8],['h',9]]]
    assert {o['params']['bp_index'] for o in result if o['kind']=='nick'}=={3,5,7,9}
