"""Analytic/symmetry oracles and the stateless EM API contract."""
import json
import os
import subprocess

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_em_analysis as routes
from backend.physics.em_analysis import analysis_geometry, gold_permittivity


def particle(center=(0, 0, 0), diameter=20):
    return {'id': 'test-optical-sphere', 'center_nm': list(center), 'diameter_nm': diameter}


def test_optical_constants_and_frame():
    eps = gold_permittivity()
    assert eps.real < 0 < eps.imag
    geometry = analysis_geometry([particle((1, 2, 3)), particle((1, 2, 45))])
    _, _, origin, basis, local, _, _, gaps = geometry
    np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=1e-12)
    np.testing.assert_allclose(origin + local @ basis, [[1, 2, 3], [1, 2, 45]])
    assert gaps == [22.]


@pytest.mark.parametrize('particles', [[], [particle(), particle((20, 0, 0))],
    [particle((float('nan'), 0, 0))], [particle(diameter=500)]])
def test_reject_unsupported_geometry(particles):
    with pytest.raises(ValueError):
        analysis_geometry(particles)


def test_api_schema_and_no_document_dependency(monkeypatch):
    app = FastAPI(); app.include_router(routes.router)
    async def fake(payload, request):
        return {'received': payload}
    monkeypatch.setattr(routes, 'run_solver', fake)
    with TestClient(app) as client:
        assert client.post('/em-analysis/solve', json={'particles': [particle()]}).json()['received']['resolution'] == 33
        assert client.post('/em-analysis/solve', json={'particles': [particle()], 'resolution': 500}).status_code == 422
        assert client.post('/em-analysis/solve', json={'particles': [particle()], 'polarization': 'arbitrary'}).status_code == 422
        assert client.post('/em-analysis/solve', json={'particles': [particle()], 'wavelength_nm': 600}).json()['received']['wavelength_nm'] == 600
        for wavelength in [0, 187.8, 1938]:
            assert client.post('/em-analysis/solve', json={'particles': [particle()], 'wavelength_nm': wavelength}).status_code == 422


@pytest.mark.parametrize('wavelength', [520, 650])
def test_single_small_sphere_matches_electrostatic_limit_and_symmetry(wavelength):
    executable = routes.solver_python()
    if not executable:
        pytest.skip('Optional isolated EM engine not installed')
    payload = {'particles': [particle(diameter=5)], 'resolution': 25, 'polarization': 'parallel', 'wavelength_nm': wavelength}
    process = subprocess.run([executable, '-m', 'backend.physics.em_analysis'],
        input=json.dumps(payload), capture_output=True, text=True, timeout=90,
        env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1'})
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(process.stdout)
    values = np.array(result['intensity']).reshape(result['shape'])
    assert np.isfinite(values).all()
    # On the polarization axis at x=5.2083 nm (outside radius 2.5 nm).
    x = result['lower_nm'][0] + 17 * (result['upper_nm'][0] - result['lower_nm'][0]) / 24
    eps_b = 1.333 ** 2
    beta = (gold_permittivity(wavelength) - eps_b) / (gold_permittivity(wavelength) + 2 * eps_b)
    expected = abs(1 + 2 * beta * (2.5 / x) ** 3) ** 2
    assert values[17, 12, 12] == pytest.approx(expected, rel=.04)
    assert values[7, 12, 12] == pytest.approx(values[17, 12, 12], rel=1e-5)
    assert result['outside'][12 * 25 * 25 + 12 * 25 + 12] is False
    assert result['probe_relative_error'] < .01
    assert result['wavelength_nm'] == wavelength
    assert result['gold_epsilon'] == pytest.approx([gold_permittivity(wavelength).real,gold_permittivity(wavelength).imag])
    assert result['inputs'] == payload
    assert len(result['source_sha256']) == 64


def test_worker_cancel_terminates_process(monkeypatch):
    import asyncio
    class Process:
        returncode = None
        killed = False
        async def communicate(self, body):
            await asyncio.sleep(10)
            return b'{}', None
        def kill(self):
            self.killed = True
            self.returncode = -9
        async def wait(self):
            return self.returncode
    class Disconnected:
        async def is_disconnected(self):
            return True
    process = Process()
    async def create(*args, **kwargs):
        return process
    monkeypatch.setattr(routes, 'solver_python', lambda: '/example/python')
    monkeypatch.setattr(routes.asyncio, 'create_subprocess_exec', create)
    monkeypatch.setattr(routes, '_lock', asyncio.Lock())
    with pytest.raises(routes.HTTPException) as error:
        asyncio.run(routes.run_solver({'particles': [particle()]}, Disconnected()))
    assert error.value.status_code == 499
    assert process.killed
    assert not routes._lock.locked()


def test_unavailable_engine_is_explicit(monkeypatch):
    import asyncio
    monkeypatch.setattr(routes, 'solver_python', lambda: None)
    with pytest.raises(routes.HTTPException) as error:
        asyncio.run(routes.run_solver({}, None))
    assert error.value.status_code == 503


def test_optimized_evaluator_matches_independent_miepy_vectors():
    executable = routes.solver_python()
    if not executable:
        pytest.skip('Optional isolated EM engine not installed')
    process = subprocess.run([executable, 'tests/em_evaluator_oracle.py'],
        capture_output=True, text=True, timeout=90,
        env={**os.environ, 'PYTHONPATH': str(routes.ROOT), 'OPENBLAS_NUM_THREADS': '1',
             'OMP_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1'})
    assert process.returncode == 0, process.stdout + process.stderr


def test_stream_is_ordered_and_stops_on_invalid_frame():
    executable = routes.solver_python()
    if not executable:
        pytest.skip('Optional isolated EM engine not installed')
    payload = {'particles': [particle(diameter=5)], 'resolution': 25, 'polarization': 'parallel', 'wavelength_nm': 520}
    moved = {**payload, 'particles': [particle((1, 2, 3), diameter=5)]}
    process = subprocess.run([executable, '-m', 'backend.physics.em_analysis', '--stream'],
        input='\n'.join(json.dumps(p) for p in [payload, moved, {**payload, 'resolution': 500}, payload]),
        capture_output=True, text=True, timeout=90,
        env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1'})
    records = [json.loads(line) for line in process.stdout.splitlines()]
    assert process.returncode == 1
    assert len(records) == 3
    assert records[0]['inputs'] == payload
    assert records[1]['inputs'] == moved
    assert records[0]['intensity'] == records[1]['intensity']
    np.testing.assert_allclose(np.array(records[1]['peak_position_nm']) - records[0]['peak_position_nm'], [1, 2, 3])
    assert records[0]['source_sha256'] != records[1]['source_sha256']
    assert 'Grid resolution' in records[2]['error']


def test_volume_cli_retains_unrounded_solver_output(tmp_path):
    from backend.physics.em_volume_archive import read_frame
    executable = routes.solver_python()
    if not executable:
        pytest.skip('Optional isolated EM engine not installed')
    payload = {'particles': [particle(diameter=5)], 'resolution': 25, 'polarization': 'parallel', 'wavelength_nm': 520}
    destination = tmp_path / 'fields'
    process = subprocess.run([executable, '-m', 'backend.physics.em_volume_archive', str(destination)],
        input=json.dumps({'frame_index': 25, 'time_ps': 1.5, 'input': payload}) + '\n',
        capture_output=True, text=True, timeout=30,
        env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1'})
    assert process.returncode == 0, process.stderr
    assert json.loads(process.stdout) == {'status': 'complete', 'frames': 1}
    result = read_frame(destination, 0)
    # Automatic trajectory execution records the concrete backend it selected.
    assert result['inputs'] == {**payload, 'compute_backend': result['compute_backend']}
    assert result['frame_index'] == 25 and result['time_ps'] == 1.5
    assert result['intensity'].max() == result['peak_intensity']
    assert np.any(result['intensity'] != np.round(result['intensity'], 6))
    assert result['outside'].dtype == bool
