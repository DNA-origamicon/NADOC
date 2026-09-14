from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from backend.api import routes_namd_setup_presets as routes


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, 'directory', lambda: tmp_path / 'presets')
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def payload(name='Brush screening'):
    return {'name': name, 'settings': {'schema': 'nadoc.namd_setup.v1',
            'controls': {'md-screening-charge': {'type': 'number', 'value': '-0.02'}},
            'peg': {'enabled': True, 'spec': {'repeat_units': 40}}}}


def test_persistent_crud_and_revision_conflicts(client):
    created = client.post('/md/setup-presets', json=payload())
    assert created.status_code == 201
    record = created.json()
    assert client.get('/md/setup-presets').json() == [record]
    assert client.post('/md/setup-presets', json=payload()).status_code == 409
    path = f"/md/setup-presets/{record['id']}"
    changed = payload()
    changed['revision'] = 1
    changed['settings']['peg']['spec']['repeat_units'] = 80
    assert client.put(path, json=changed).json()['revision'] == 2
    assert client.put(path, json=changed).status_code == 409
    assert client.delete(path, params={'revision': 1}).status_code == 409
    assert client.get('/md/setup-presets').json()[0]['settings']['peg']['spec']['repeat_units'] == 80
    assert client.delete(path, params={'revision': 2}).status_code == 200
    assert client.get('/md/setup-presets').json() == []
    assert client.delete(path, params={'revision': 2}).status_code == 404


def test_invalid_records_cannot_create_files(client):
    assert client.post('/md/setup-presets', json=payload(' ')).status_code == 422
    assert client.post('/md/setup-presets', json={'name': 'x', 'settings': {}}).status_code == 422
    assert client.delete('/md/setup-presets/not-a-uuid', params={'revision': 1}).status_code == 422
    assert client.get('/md/setup-presets').json() == []
