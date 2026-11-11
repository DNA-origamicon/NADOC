"""Deletion preserves undo while the editor receives only animation metadata."""
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app


@pytest.mark.parametrize('host', ['design', 'assembly'])
def test_compact_keyframe_delete_skips_full_response_and_preserves_undo(host, monkeypatch):
    from backend.api import routes_animations, routes_assembly_animations
    client = TestClient(app)
    assert client.post(f'/api/{host}', json={'name': '__e2e__delete-metadata'}).status_code in (200, 201)
    result = client.post(f'/api/{host}/animations', json={'name': 'Deletion'})
    animation = result.json()[host]['animations'][-1]
    base = f'/api/{host}/animations/{animation["id"]}/keyframes'
    result = client.post(base, json={'is_trajectory': True, 'trajectory_job_id': 'retained-job'})
    frame = result.json()[host]['animations'][-1]['keyframes'][-1]
    module = routes_animations if host == 'design' else routes_assembly_animations
    def reject_full_response(*args, **kwargs):
        raise AssertionError('Deletion must not serialize the molecular document')
    monkeypatch.setattr(module, f'_{host}_response', reject_full_response)
    result = client.delete(f'{base}/{frame["id"]}?metadata_only=true')
    assert result.status_code == 200, result.text
    assert set(result.json()[host]) == {'id', 'animations'}
    assert result.json()[host]['animations'][-1]['keyframes'] == []
    assert isinstance(result.json()['revision'], int)
    restored = client.post(f'/api/{host}/undo')
    assert restored.status_code == 200, restored.text
    assert restored.json()[host]['animations'][-1]['keyframes'][-1]['id'] == frame['id']
    assert restored.json()[host]['animations'][-1]['keyframes'][-1] == frame
