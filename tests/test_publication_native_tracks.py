import pytest
from backend.core.publication_native_tracks import prepare_native_tracks


def inputs():
    c={'scaf':[{'sites':[(0,0),(3,8),(3,7),(0,1),(3,4),(3,3),(0,2)]}],
       'stap':[{'sites':[(3,7),(3,8)]},{'sites':[(3,3),(3,4)]}],'unresolved':[]}
    lattice={'resolved':False,'cells':{0:[0,0]},'missing_helices':[3]}
    placement={'resolved':True,'inset_cells':{0:[0,0]},'segment_placements':[
        {'source_helix':3,'source_start':(3,8),'source_end':(3,7),'cell':[0,1]},
        {'source_helix':3,'source_start':(3,4),'source_end':(3,3),'cell':[-1,0]}]}
    return c,lattice,placement,{'resolved':True}


def test_split_row_is_bijective_preserves_order_and_does_not_mutate_source():
    args=inputs();result=prepare_native_tracks(*args)
    assert len(result['cells'])==3
    inverse={h:s['source_helix'] for h,s in result['sources'].items()}
    for kind in ('scaf','stap'):
        for old,new in zip(args[0][kind],result['classified'][kind]):
            assert [(inverse[h],b) for h,b in new['sites']]==old['sites']
    assert args[0]['scaf'][0]['sites'][1]==(3,8)
    assert len(result['auxiliary_sites'])==4
    assert result['site_mapping'][(3,7)]==(4,7)
    assert result['site_mapping'][(3,3)]==(5,3)


@pytest.mark.parametrize('defect',['collision','overlap','missing','unresolved'])
def test_invalid_segment_mapping_cannot_be_authored(defect):
    args=inputs();p=args[2]
    if defect=='collision':p['segment_placements'][1]['cell']=[0,1]
    elif defect=='overlap':p['segment_placements'][1]['source_start']=(3,8)
    elif defect=='missing':p['segment_placements'].pop()
    else:p['resolved']=False
    with pytest.raises(ValueError):prepare_native_tracks(*args)
