import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.models import Design
from backend.core.lattice_frames import append_independent_bundle, append_frame_cell


@pytest.mark.parametrize('plane',['XY','XZ','YZ'])
def test_add_cell_retains_only_its_frame_pose(plane):
    d=append_independent_bundle(Design(),[[0,0]],42,plane=plane,translation_nm=[20,0,0])
    d=append_independent_bundle(d,[[0,0]],21,translation_nm=[-20,0,0])
    frame=d.lattice_frames[0]
    result,h=append_frame_cell(d,frame.id,0,1)
    assert h.length_bp==42 and h.lattice_frame_id==frame.id
    assert not any(domain.helix_id==h.id for strand in result.strands for domain in strand.domains)
    assert h.id in result.cluster_transforms[0].helix_ids
    assert h.id not in result.cluster_transforms[1].helix_ids
    assert len(d.helices)==2
    with pytest.raises(ValueError):append_frame_cell(result,frame.id,0,1)


@pytest.mark.parametrize('col',[1,10])
def test_frame_cell_api_is_undoable_and_does_not_touch_other_frame(col):
    d=append_independent_bundle(Design(),[[0,0]],21)
    d=append_independent_bundle(d,[[0,0]],42,translation_nm=[20,0,0])
    state.set_design(d)
    try:
        with TestClient(app) as client:
            state.set_design(d)
            response=client.post('/api/design/helix-at-cell',json={'row':0,'col':col,'lattice_frame_id':d.lattice_frames[1].id})
            assert response.status_code==201,response.text
            result=response.json()['design']
            assert len(result['helices'])==3
            h=result['helices'][-1]
            assert h['lattice_frame_id']==d.lattice_frames[1].id and h['length_bp']==42
            assert h['id'] not in result['cluster_transforms'][0]['helix_ids']
            assert h['id'] in result['cluster_transforms'][1]['helix_ids']
            assert client.post('/api/design/undo').status_code==200
            assert len(client.get('/api/design').json()['design']['helices'])==2
    finally:state.set_design(Design())
