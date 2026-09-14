"""Native NAMD PEG drafts are durable specifications, never engine jobs."""
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import routes_namd_peg_surfaces as routes
from backend.core.namd_peg_surface import NamdPegSurface, review_surface


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(routes, '_directory', lambda: tmp_path / 'namd_surfaces')
    return TestClient(app)


def test_direct_create_reopen_and_update_without_design_or_oxdna(client, tmp_path):
    response = client.post('/api/md/peg-surfaces', json={'name': 'Direct PEG'})
    assert response.status_code == 201, response.text
    saved = response.json()
    assert saved['engine'] == 'NAMD' and saved['origin'] == 'direct'
    assert not saved['launch_ready']
    assert saved['summary']['chains'] == 20
    assert client.get('/api/md/peg-surfaces').json()[0] == saved
    spec = {**saved['spec'], 'size_nm': 30, 'material': 'graphene', 'pore_diameter_nm': 4}
    changed = client.put(f"/api/md/peg-surfaces/{saved['id']}", json=spec).json()
    assert changed['id'] == saved['id'] and changed['spec']['size_nm'] == 30
    files = list(tmp_path.rglob('*'))
    assert len([p for p in files if p.suffix == '.json']) == 1
    assert not any(p.suffix == '.tmp' or 'jobs' in p.name for p in files)
    assert not client.get('/api/md/peg-surfaces').json()[0]['launch_ready']


@pytest.mark.parametrize('body', [{'name': '  '}, {'density_per_nm2': 0}, {'size_nm': 1},
    {'material': 'graphene', 'pore_diameter_nm': 20}, {'pore_diameter_nm': 1},
    {'layers': 2}, {'density_per_nm2': 10, 'size_nm': 100}, {'segments': 1},
    {'normal_axis': 'z'}, {'oxdna_job_id': 'unknown'}, {'repeat_units': 1.5}])
def test_invalid_specs_never_persist(client, tmp_path, body):
    assert client.post('/api/md/peg-surfaces', json=body).status_code == 422
    assert not list(tmp_path.rglob('*.json'))


def test_review_uses_shared_plane_and_excludes_pore(client, tmp_path):
    spec = {'material': 'graphene', 'shape': 'circle', 'pore_diameter_nm': 10,
            'normal_axis': '-y', 'position_nm': 3, 'density_per_nm2': .2}
    a = client.post('/api/md/peg-surfaces/review', json=spec).json()
    b = client.post('/api/md/peg-surfaces/review', json=spec).json()
    assert a == b
    points = np.array(a['preview']['graft_sites_nm'])
    assert np.allclose(points[:, 1], 3)
    radii = np.linalg.norm(a['preview']['local_sites_nm'], axis=1)
    assert np.all(radii >= 5) and np.all(radii <= 10)
    assert a['surface']['dir'] == [0, -1, 0]
    assert not list(tmp_path.rglob('*.json'))


def test_asset_notes_cannot_claim_readiness():
    result = review_surface(NamdPegSurface(topology_reference='/tmp/peg.psf',
                            parameter_reference='approved.prm', end_groups='OH / tether'))
    assert not result['launch_ready']
    assert 'target_assets' in {b['code'] for b in result['barriers']}


def test_disk_readiness_is_recomputed(client, tmp_path):
    saved = client.post('/api/md/peg-surfaces', json={}).json()
    path = tmp_path / 'namd_surfaces' / f"{saved['id']}.json"
    saved['launch_ready'] = True
    path.write_text(json.dumps(saved))
    assert not client.get('/api/md/peg-surfaces').json()[0]['launch_ready']
