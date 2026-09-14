"""Setup contracts only: no engine, particle build, workspace or job creation."""
from copy import deepcopy

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api.routes_peg_setup import router

app = FastAPI()
app.include_router(router, prefix="/api")
client = TestClient(app)


def payload():
    return {
        "surface": {"dir": [0, 1, 0], "position_nm": -7, "stiff": 100},
        "surface_strands": {"material": "PEG", "shape": "square", "sizeNm": 12,
                            "densityPerUm2": 27778, "segments": 8, "seed": 17},
    }


def test_setup_is_engine_independent_and_deterministic(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Setup review must not resolve or prepare an engine")
    monkeypatch.setattr("backend.physics.oxdna_peg.find_peg_oxdna", forbidden)
    monkeypatch.setattr("backend.core.oxdna_runner.prepare_oxdna_job", forbidden)
    request = payload()
    before = deepcopy(request)
    response = client.post('/api/oxdna/peg/setup', json=request)
    assert response.status_code == 200
    result = response.json()
    assert result == client.post('/api/oxdna/peg/setup', json=request).json()
    assert request == before
    assert result['status'] == 'setup_only' and result['launch_ready'] is False
    assert result['summary'] == {'requested_chains': 4, 'beads_per_chain': 9, 'requested_beads': 36}
    fragment = result['job_request_fragment']
    assert fragment['autostart'] is False
    assert fragment['surface_strands']['subjectToField'] is False
    assert fragment['surface_strands']['seed'] == 17
    assert {b['code'] for b in result['barriers']} == {
        'model_validation', 'geometry_preflight', 'engine_preflight', 'namd_mapping',
    }


@pytest.mark.parametrize('field,value', [
    ('segments', 1), ('segments', 65), ('segments', 2.5),
    ('bondLengthNm', 0), ('beadDiameterNm', 1.1), ('terminalChargeE', 3),
    ('shape', 'triangle'), ('sizeNm', -1), ('densityPerUm2', 0),
    ('densityPerUm2', 1), ('densityPerUm2', 1e12),
    ('seed', -1), ('seed', 1.5), ('seed', 2**32),
    ('offsetXNm', 'NaN'), ('offsetYNm', 'Infinity'), ('enabled', False),
    ('material', 'DNA'), ('subjectToField', True), ('built', {}),
])
def test_invalid_coating_rejected(field, value):
    request = payload()
    request['surface_strands'][field] = value
    assert client.post('/api/oxdna/peg/setup', json=request).status_code == 422


@pytest.mark.parametrize('change', [
    {'surface': None}, {'surface': {'dir': [0, 0, 0], 'position_nm': 0}},
    {'surface': {'dir': [0, 1, 0], 'position_nm': 0, 'stiff': -1}},
    {'execution_target': 'alpine'}, {'interaction_type': 'DNA1'},
    {'backend': 'NAMD'}, {'autostart': True},
])
def test_unsupported_setup_rejected(change):
    assert client.post('/api/oxdna/peg/setup', json={**payload(), **change}).status_code == 422


def test_circle_counts_and_fractional_terminal_charge():
    request = payload()
    request['surface_strands'].update(shape='circle', terminalChargeE=-.5)
    result = client.post('/api/oxdna/peg/setup', json=request).json()
    assert result['summary']['requested_chains'] == 3
    assert result['summary']['requested_beads'] == 27
    assert 'terminal_field' in {b['code'] for b in result['barriers']}
