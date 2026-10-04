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


def test_legacy_plane_preflight_commit_and_undo(client):
    from backend.core.lattice import make_bundle_design
    from backend.core.models import ClusterRigidTransform
    design = make_bundle_design([(4, 4), (4, 5)], 21)
    design.cluster_transforms = [ClusterRigidTransform(is_default=True,
        helix_ids=[h.id for h in design.helices], translation=[3, 2, 1])]
    state.set_design(design)
    original = state.get_or_404().to_json()
    old_helices = [h.model_dump() for h in state.get_or_404().helices]
    body = request(source_legacy_plane=True)
    assert client.post('/api/design/frame-extrusion/validate', json=body).status_code == 200
    assert state.get_or_404().to_json() == original
    result = client.post('/api/design/frame-extrusion', json=body)
    assert result.status_code == 201, result.text
    assert [h.model_dump() for h in state.get_or_404().helices[:2]] == old_helices
    assert len(state.get_or_404().helices) == 4
    assert client.post('/api/design/frame-extrusion', json=body).status_code == 409
    assert client.post('/api/design/undo').status_code == 200
    assert state.get_or_404().to_json() == original


@pytest.mark.parametrize('invalid', ['occupied', 'plane', 'origins', 'placement'])
def test_legacy_plane_refuses_ambiguous_or_occupied_source(client, invalid):
    from backend.core.lattice import make_bundle_design
    design = make_bundle_design([(4, 4), (4, 5)], 21)
    body = {'source_legacy_plane': True}
    if invalid == 'origins':
        design.helices[1].axis_start.x += 2
        design.helices[1].axis_end.x += 2
    state.set_design(design)
    body = request(**body)
    if invalid == 'occupied': body['cells'] = [[4, 4]]
    if invalid == 'plane': body['plane'] = 'YZ'
    if invalid == 'placement': body['translation_nm'] = [1, 0, 0]
    original = state.get_or_404().to_json()
    for path in ['frame-extrusion/validate', 'frame-extrusion']:
        response = client.post('/api/design/'+path, json=body)
        assert response.status_code == 422, response.text
        assert state.get_or_404().to_json() == original


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('lattice', ['HONEYCOMB', 'SQUARE'])
@pytest.mark.parametrize('length', [-24, 24])
def test_legacy_source_preserves_origin_and_pose(plane, lattice, length):
    from backend.core.lattice import make_bundle_design, _lattice_position
    from backend.core.legacy_plane_extrusion import append_legacy_plane_bundle
    from backend.core.models import ClusterRigidTransform, LatticeType
    design = make_bundle_design([(4, 4)], 24, plane=plane, lattice_type=LatticeType(lattice))
    # The legacy builder omits addresses for non-XY bundles; this fixture
    # explicitly carries the source-cell metadata required by the adapter.
    design.helices[0].grid_pos = (4, 4)
    axes = {'XY': ('x', 'y'), 'XZ': ('x', 'z'), 'YZ': ('y', 'z')}[plane]
    for endpoint in [design.helices[0].axis_start, design.helices[0].axis_end]:
        for axis, delta in zip(axes, [12, -7]):
            setattr(endpoint, axis, getattr(endpoint, axis)+delta)
    design.cluster_transforms = [ClusterRigidTransform(helix_ids=[design.helices[0].id],
        translation=[3, 2, 1], rotation=[0, math.sin(.3), 0, math.cos(.3)])]
    original = design.to_json()
    result = append_legacy_plane_bundle(design, [[0, 0]], length, plane=plane)
    assert design.to_json() == original
    assert result.helices[0] == design.helices[0]
    assert result.strands[:len(design.strands)] == design.strands
    expected = _lattice_position(0, 0, design.lattice_type)
    for axis, coordinate, delta in zip(axes, expected, [12, -7]):
        assert getattr(result.helices[-1].axis_start, axis) == pytest.approx(coordinate+delta)
    assert result.cluster_transforms[0].rotation == design.cluster_transforms[0].rotation
    assert result.cluster_transforms[0].translation == design.cluster_transforms[0].translation
    assert result.helices[-1].id in result.cluster_transforms[0].helix_ids
