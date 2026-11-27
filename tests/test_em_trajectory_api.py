"""Read-only trajectory job API: native CPU/auto worker, progress, random access, cleanup."""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes_em_analysis import router, solver_python


def test_trajectory_job_schema_rejects_duplicate_frames():
    app = FastAPI(); app.include_router(router)
    payload = {'particles': [{'id': 'gold', 'center_nm': [0, 0, 0], 'diameter_nm': 5}], 'resolution': 25}
    with TestClient(app) as client:
        response = client.post('/em-analysis/trajectories', json={'frames': [dict(frame_index=1, input=payload)]*2})
        assert response.status_code == 422


def test_native_trajectory_progress_frame_and_delete(tmp_path, monkeypatch):
    if not solver_python():
        pytest.skip('Optional EM engine missing')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    app = FastAPI(); app.include_router(router)
    payload = {'particles': [{'id': 'gold', 'center_nm': [0, 0, 0], 'diameter_nm': 5}],
               'resolution': 25, 'sampling': 'adaptive', 'shell': {'model': 'none'}}
    identity = None
    with TestClient(app) as client:
        try:
            response = client.post('/em-analysis/trajectories', json={'frames': [dict(frame_index=17, input=payload)]})
            assert response.status_code == 200, response.text
            identity = response.json()['id']
            deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                progress = client.get(f'/em-analysis/trajectories/{identity}').json()
                if progress['status'] != 'running':
                    break
                time.sleep(.1)
            assert progress['status'] == 'complete', progress
            assert progress['frames'] == [17] and progress['completed'] == 1
            frame = client.get(f'/em-analysis/trajectories/{identity}/frames/0')
            assert frame.status_code == 200
            data = frame.json()
            assert data['frame_index'] == 17
            assert data['display_tetrahedra']
            assert {i for tet in data['display_tetrahedra'] for i in tet} == set(range(len(data['intensity'])))
            assert data['inputs']['particles'] == payload['particles']
            assert client.get(f'/em-analysis/trajectories/{identity}/frames/1').status_code == 404
        finally:
            if identity:
                assert client.delete(f'/em-analysis/trajectories/{identity}').status_code == 200
    assert not list(tmp_path.iterdir())


def test_cancelling_job_releases_workers_and_scratch(tmp_path, monkeypatch):
    if not solver_python():
        pytest.skip('Optional EM engine missing')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    app = FastAPI(); app.include_router(router)
    payload = {'particles': [{'id': 'gold', 'center_nm': [0, 0, 0], 'diameter_nm': 20}], 'resolution': 49}
    with TestClient(app) as client:
        response = client.post('/em-analysis/trajectories', json={'frames': [dict(frame_index=i, input=payload) for i in range(3)]})
        assert response.status_code == 200, response.text
        identity = response.json()['id']
        assert client.delete(f'/em-analysis/trajectories/{identity}').status_code == 200
        assert client.get(f'/em-analysis/trajectories/{identity}').status_code == 404
        assert not client.get('/em-analysis/status').json()['busy']
    assert not list(tmp_path.iterdir())


def test_unavailable_scratch_releases_shared_lock(tmp_path, monkeypatch):
    if not solver_python():
        pytest.skip('Optional EM engine missing')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path / 'missing'))
    app = FastAPI(); app.include_router(router)
    payload = {'particles': [{'id': 'gold', 'center_nm': [0, 0, 0], 'diameter_nm': 5}], 'resolution': 25}
    with TestClient(app) as client:
        response = client.post('/em-analysis/trajectories', json={'frames': [dict(frame_index=0, input=payload)]})
        assert response.status_code == 507
        assert not client.get('/em-analysis/status').json()['busy']


def test_server_shutdown_cancels_job_and_removes_scratch(tmp_path, monkeypatch):
    if not solver_python():
        pytest.skip('Optional EM engine missing')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    app = FastAPI(); app.include_router(router)
    payload = {'particles': [{'id': 'gold', 'center_nm': [0, 0, 0], 'diameter_nm': 20}], 'resolution': 49}
    with TestClient(app) as client:
        response = client.post('/em-analysis/trajectories', json={'frames': [dict(frame_index=0, input=payload)]})
        assert response.status_code == 200
    assert not list(tmp_path.iterdir())


def test_numpy_frame_serialization_retains_float64_values(monkeypatch):
    import json
    import numpy as np
    from backend.api import em_trajectory_jobs
    values = np.array([1.123456789012345, 2.987654321098765])
    result = {'intensity': values, 'outside': np.array([True, False]),
              'sample_positions_nm': np.array([[1., 2., 3.], [4., 5., 6.]]),
              'frame_index': 17}
    monkeypatch.setattr(em_trajectory_jobs, 'read_frame', lambda *_: result)
    decoded = json.loads(em_trajectory_jobs.encode_frame('unused', 0))
    assert decoded['intensity'] == values.tolist()
    assert decoded['outside'] == [True, False]
    assert decoded['sample_positions_nm'] == [[1., 2., 3.], [4., 5., 6.]]
    assert decoded['frame_index'] == 17
