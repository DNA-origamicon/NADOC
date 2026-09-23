"""Authoring transaction checks, independent of native input transport."""
import math
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.models import Design


@pytest.fixture
def client():
    with TestClient(app) as client:
        state.set_design(Design())
        yield client
    state.set_design(Design())


def request(**kwargs):
    return dict(expected_design_id=state.get_or_404().id,
                expected_revision=state.revision(), cells=[[0,0],[0,1]],
                length_bp=21, plane='XY', **kwargs)


def test_commit_preflight_repeat_undo_redo(client):
    body=request(translation_nm=[12,-4,8], rotation_xyzw=[0,math.sin(.3),0,math.cos(.3)])
    before=state.get_or_404().to_json()
    assert client.post('/api/design/frame-extrusion/validate',json=body).json()['added_helices']==2
    assert state.get_or_404().to_json()==before
    response=client.post('/api/design/frame-extrusion',json=body)
    assert response.status_code==201,response.text
    result=response.json()['design']
    assert len(result['helices'])==2 and len(result['lattice_frames'])==1
    assert len(result['feature_log'])==1
    assert result['feature_log'][0]['op_kind']=='extrude-frame'
    cluster=result['cluster_transforms'][0]
    assert cluster['translation']==[12,-4,8]
    assert cluster['rotation']==body['rotation_xyzw']
    assert set(cluster['helix_ids'])=={h['id'] for h in result['helices']}
    committed=state.get_or_404().to_json()
    assert client.post('/api/design/frame-extrusion',json=body).status_code==409
    assert state.get_or_404().to_json()==committed
    assert client.post('/api/design/undo').status_code==200
    assert state.get_or_404().helices==[] and state.get_or_404().lattice_frames==[]
    assert client.post('/api/design/redo').status_code==200
    assert state.get_or_404().to_json()==committed


@pytest.mark.parametrize('patch',[
    {'expected_design_id':'other'}, {'expected_revision':0},
    {'cells':[[0,0],[0,0]]}, {'cells':[[0]]}, {'cells':[[True,0]]},
    {'length_bp':0}, {'rotation_xyzw':[0,0,0,2]},
    {'length_bp':200001}, {'plane':'oblique'},
])
def test_invalid_commit_preserves_document_and_revision(client,patch):
    body=request();body.update(patch)
    before=state.get_or_404().to_json();revision=state.revision()
    response=client.post('/api/design/frame-extrusion',json=body)
    assert response.status_code in (409,422),response.text
    assert state.get_or_404().to_json()==before
    assert state.revision()==revision


def test_existing_frame_transaction_and_rejected_placement(client):
    first = client.post('/api/design/frame-extrusion', json=request(translation_nm=[12,-4,8]))
    assert first.status_code == 201
    original = state.get_or_404().to_json()
    frame_id = state.get_or_404().lattice_frames[0].id
    body = request(source_frame_id=frame_id)
    body['cells'] = [[1,0]]
    for patch in ({'cells':[[0,0]]}, {'plane':'YZ'}, {'source_frame_id':'missing'},
                  {'translation_nm':[1,0,0]}, {'rotation_xyzw':[0,1,0,0]}):
        response = client.post('/api/design/frame-extrusion', json={**body, **patch})
        assert response.status_code == 422, response.text
        assert state.get_or_404().to_json() == original
    preflight = client.post('/api/design/frame-extrusion/validate', json=body)
    assert preflight.status_code == 200
    assert preflight.json()['added_helices'] == 1
    assert state.get_or_404().to_json() == original
    result = client.post('/api/design/frame-extrusion', json=body)
    assert result.status_code == 201, result.text
    updated = state.get_or_404()
    assert len(updated.lattice_frames) == 1
    assert len(updated.helices) == 3
    assert updated.helices[-1].lattice_frame_id == frame_id
    assert updated.cluster_transforms[0].translation == [12,-4,8]
    committed = updated.to_json()
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_or_404().to_json() == original
    assert client.post('/api/design/redo').status_code == 200
    assert state.get_or_404().to_json() == committed
