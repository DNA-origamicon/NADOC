"""Capture/duplicate are atomic, undoable presentation edits, never geometry edits."""
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app


@pytest.mark.parametrize('host', ['design', 'assembly'])
def test_capture_duplicate_and_undo(host):
    client = TestClient(app)
    doc = client.post(f'/api/{host}', json={'name': '__e2e__capture'}).json()[host]
    animation = client.post(f'/api/{host}/animations', json={'name': 'Sequence'}).json()[host]['animations'][-1]
    base = f'/api/{host}/animations/{animation["id"]}/keyframes'
    for name in ['First', 'Second']:
        response = client.post(base, json={'name': name, 'text': 'Text', 'hold_duration_s': 2})
    frames = response.json()[host]['animations'][-1]['keyframes']
    first = frames[0]['id']
    body = {'pose': {'name': 'Captured pose', 'position': [1, 2, 3], 'target': [4, 5, 6], 'up': [0, 1, 0], 'fov': 40},
            'annotation_ids': ['a'], 'view_volume_ids': ['v'], 'zoom_volume_ids': ['z'], 'feature_log_index': -2}
    result = client.post(f'{base}/{first}/capture', json=body)
    assert result.status_code == 200, result.text
    captured = result.json()[host]
    assert set(captured) == ({'id', 'animations', 'camera_poses', 'configurations'} if host == 'assembly' else {'id', 'animations', 'camera_poses'})
    original = captured['animations'][-1]['keyframes'][0]
    assert original['camera_pose_id'] == captured['camera_poses'][-1]['id']
    assert captured['camera_poses'][-1]['position'] == [1, 2, 3]
    assert original['annotation_ids'] == ['a']
    assert original['view_volume_ids'] == ['v']
    assert original['zoom_volume_ids'] == ['z']
    assert original['text'] == 'Text' and original['hold_duration_s'] == 2
    if host == 'assembly':
        assert original['configuration_id'] == captured['configurations'][-1]['id']
    else:
        assert original['feature_log_index'] == -2
    result = client.post(f'{base}/{first}/duplicate').json()[host]
    copies = result['animations'][-1]['keyframes']
    assert [k['name'] for k in copies] == ['First', 'First', 'Second']
    assert copies[0]['id'] != copies[1]['id']
    assert {k: v for k, v in copies[0].items() if k != 'id'} == {k: v for k, v in copies[1].items() if k != 'id'}
    # Recapture the duplicate: the source retains its pose and visibility selection.
    second_capture = client.post(f'{base}/{copies[1]["id"]}/capture', json={**body, 'zoom_volume_ids': []}).json()[host]
    assert second_capture['animations'][-1]['keyframes'][0] == original
    assert second_capture['animations'][-1]['keyframes'][1]['camera_pose_id'] != original['camera_pose_id']
    assert client.post(f'/api/{host}/undo').status_code == 200
    undone = client.post(f'/api/{host}/undo').json()[host]
    assert [k['id'] for k in undone['animations'][-1]['keyframes']] == [k['id'] for k in frames]
    assert client.post(f'{base}/missing/capture', json=body).status_code == 404
    assert client.get(f'/api/{host}').json()[host].get('feature_log') == doc.get('feature_log')
