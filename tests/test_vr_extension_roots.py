"""Full-view root connectivity, including native extension index direction."""
from types import SimpleNamespace as NS
from copy import deepcopy
import pytest
from backend.core.vr_extension_roots import extension_root_anchors, is_extension_root_pair
from backend.core.vr_scene_projection import strand_nucleotide_order_key

@pytest.mark.parametrize('direction',['FORWARD','REVERSE'])
@pytest.mark.parametrize('end',['five_prime','three_prime'])
@pytest.mark.parametrize('length',[1,4])
def test_recorded_root_and_order(direction,end,length):
    five=end=='five_prime'
    start,stop=(-5,-1) if direction=='FORWARD' else (-1,-5)
    design=NS(strands=[NS(id='s',domains=[NS(helix_id='h',start_bp=start,end_bp=stop,direction=direction)])],
              extensions=[NS(id='e',strand_id='s',end=end)])
    host=dict(strand_id='s',helix_id='h',bp_index=start if five else stop,direction=direction,domain_index=0)
    tail=[dict(strand_id='s',helix_id='__ext_e',extension_id='e',bp_index=k,direction=direction,domain_index=-1 if five else 1) for k in range(length)]
    original=deepcopy([host,*tail]); anchors=extension_root_anchors(design)
    ordered=sorted([host,*tail],key=strand_nucleotide_order_key)
    root=[(a,b) for a,b in zip(ordered,ordered[1:]) if is_extension_root_pair(a,b,anchors)]
    assert len(root)==1
    assert root[0] == ((tail[0],host) if five else (host,tail[0]))
    assert [n['bp_index'] for n in ordered if n.get('extension_id')] == list(range(length))[::-1 if five else 1]
    assert not is_extension_root_pair({**tail[0],'is_modification':True},host,anchors)
    assert not is_extension_root_pair(tail[0],{**host,'strand_id':'other'},anchors)
    assert not is_extension_root_pair(tail[0],{**host,'bp_index':123},anchors)
    assert not is_extension_root_pair(tail[0],{**host,'helix_id':'other'},anchors)
    assert not is_extension_root_pair(tail[0],{**host,'direction':'REVERSE' if direction=='FORWARD' else 'FORWARD'},anchors)
    assert [host,*tail]==original

@pytest.mark.parametrize('end',['five_prime','three_prime'])
def test_full_export_contains_root_with_endpoint_owners(end):
    from tests.test_vr_routes import _serialize_fixture_scene
    from backend.core.vr_scene_contract import parse_scene_contract
    five=end=='five_prime'
    design=NS(strands=[NS(id='s',domains=[NS(helix_id='h',start_bp=0,end_bp=0,direction='FORWARD')],is_scaffold=False,color='#123456',sequence='A')],
        extensions=[NS(id='e',strand_id='s',end=end)],crossovers=[],forced_ligations=[],cluster_transforms=[])
    common=dict(strand_id='s',direction='FORWARD',base_normal=[1,0,0],axis_tangent=[0,0,1],base='A')
    host=dict(common,helix_id='h',bp_index=0,domain_index=0,backbone_position=[0,0,0],base_position=[.3,0,0])
    tail=dict(common,helix_id='__ext_e',extension_id='e',is_modification=False,bp_index=0,domain_index=-1 if five else 1,
        backbone_position=[0,0,.7],base_position=[.3,0,.7],slab_position=[.3,0,.7],slab_quaternion=[0,0,0,1])
    text=_serialize_fixture_scene(design,[host,tail],[],atomistic_model=NS(atoms=[],bonds=[]))
    bonds=[p for p in parse_scene_contract(text)['full'].values() if p.identity.startswith('backbone:')]
    assert len(bonds)==1
    assert set(bonds[0].values[:6]) == {0.,.7}
    assert len(bonds[0].owner_aliases)>=3
