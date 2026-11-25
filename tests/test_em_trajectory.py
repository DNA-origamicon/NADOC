"""Resource policy, bounded scheduling, ordering, and real CPU trajectory execution."""
from concurrent.futures import Future
import json
import os
import subprocess

import numpy as np
import pytest

from backend.physics import em_trajectory as trajectory
from backend.physics.em_volume_archive import read_frame


def resources(safe=False, workers=2):
    return {'cpu_workers': workers, 'gpu': {'safe': safe, 'reason': 'test'}}


class InlinePool:
    capacities = []
    shutdowns = 0
    def __init__(self, *, max_workers, **kwargs):
        self.capacities.append(max_workers)
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def shutdown(self, **kwargs):
        type(self).shutdowns += 1
    def submit(self, fn, *args):
        future = Future()
        try:
            future.set_result(fn(*args))
        except Exception as exc:
            future.set_exception(exc)
        return future


def result(payload, backend):
    if payload.get('bad'):
        raise ValueError('invalid frame')
    return {'shape': [1, 1, 1], 'outside': np.ones(1, bool), 'intensity': np.array([payload['value']], float),
            'compute_backend': backend, 'inputs': {**payload, 'compute_backend': backend}}


def lines(n=5):
    return [json.dumps({'frame_index': i*10, 'time_ps': float(i), 'input': {'value': i}}) for i in range(n)]


@pytest.fixture(autouse=True)
def worker(monkeypatch):
    InlinePool.capacities = []
    InlinePool.shutdowns = 0
    monkeypatch.setattr(trajectory, 'solve_frame', result)


def test_busy_gpu_is_never_probed_and_parallel_cpu_order_is_preserved(tmp_path, monkeypatch):
    calls = []
    def solve(payload, backend):
        calls.append(backend)
        assert backend == 'cpu'
        return result(payload, backend)
    monkeypatch.setattr(trajectory, 'solve_frame', solve)
    manifest = trajectory.write_trajectory(lines(), tmp_path/'out', workers=4,
        resource_probe=lambda: resources(False, 2), executor_factory=InlinePool)
    assert calls == ['cpu'] * 5
    assert InlinePool.capacities == [2]
    assert manifest['status'] == 'complete'
    assert [f['frame_index'] for f in manifest['frames']] == [0, 10, 20, 30, 40]
    assert manifest['processing']['decisions'][0]['gpu_pilot_seconds'] is None
    assert read_frame(tmp_path/'out', 4)['intensity'].item() == 4


def test_idle_gpu_pilot_selection_and_new_simulation_switch(tmp_path, monkeypatch):
    probes = iter([resources(True), resources(True), resources(True), resources(False)])
    monkeypatch.setattr(trajectory, 'choose', lambda *args: 'gpu')
    manifest = trajectory.write_trajectory(lines(4), tmp_path/'out',
        resource_probe=lambda: next(probes, resources(False)), executor_factory=InlinePool)
    assert [read_frame(tmp_path/'out', i)['compute_backend'] for i in range(4)] == ['gpu', 'gpu', 'cpu', 'cpu']
    assert [r['backend'] for r in manifest['processing']['decisions']] == ['gpu', 'cpu']
    assert InlinePool.shutdowns == 1


def test_unavailable_gpu_pilot_falls_back_with_reason(tmp_path, monkeypatch):
    def solve(payload, backend):
        if backend == 'gpu':
            raise RuntimeError('CuPy missing')
        return result(payload, backend)
    monkeypatch.setattr(trajectory, 'solve_frame', solve)
    manifest = trajectory.write_trajectory(lines(2), tmp_path/'out',
        resource_probe=lambda: resources(True), executor_factory=InlinePool)
    decision = manifest['processing']['decisions'][0]
    assert decision['backend'] == 'cpu' and 'CuPy missing' in decision['gpu_pilot_error']
    assert len(manifest['frames']) == 2
    assert InlinePool.shutdowns == 1


def test_failure_preserves_completed_prefix(tmp_path):
    entries = lines(5)
    entries[2] = json.dumps({'frame_index': 20, 'input': {'bad': True}})
    with pytest.raises(ValueError, match='invalid frame'):
        trajectory.write_trajectory(entries, tmp_path/'out', compute_backend='cpu',
            resource_probe=lambda: resources(), executor_factory=InlinePool)
    manifest = json.loads((tmp_path/'out'/'manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [f['frame_index'] for f in manifest['frames']] == [0, 10]
    assert not list((tmp_path/'out').glob('*.tmp'))


def test_explicit_gpu_busy_requires_override_and_worker_validation(tmp_path):
    with pytest.raises(RuntimeError, match='GPU is busy'):
        trajectory.write_trajectory(lines(1), tmp_path/'out', compute_backend='gpu',
            resource_probe=lambda: resources(), executor_factory=InlinePool)
    with pytest.raises(ValueError, match='workers'):
        trajectory.write_trajectory([], tmp_path/'bad', workers=8)
    assert not (tmp_path/'bad').exists()


def test_cpu_budget_can_shrink_between_batches(tmp_path):
    probes = iter([resources(workers=2), resources(workers=1)])
    manifest = trajectory.write_trajectory(lines(), tmp_path/'out', compute_backend='cpu',
        resource_probe=lambda: next(probes, resources(workers=1)), executor_factory=InlinePool)
    assert [d['workers'] for d in manifest['processing']['decisions']] == [2, 1]


def test_memory_pressure_stops_before_starting_workers(tmp_path):
    with pytest.raises(RuntimeError, match='memory headroom'):
        trajectory.write_trajectory(lines(), tmp_path/'out',
            resource_probe=lambda: resources(workers=0), executor_factory=InlinePool)
    assert InlinePool.capacities == []
    assert json.loads((tmp_path/'out'/'manifest.json').read_text())['status'] == 'failed'


def test_selection_compares_parallel_cpu_and_requires_margin():
    assert trajectory.choose(4, 1, 2) == 'gpu'
    assert trajectory.choose(4, 1, 4) == 'cpu'
    assert trajectory.choose(4, None, 2) == 'cpu'


def test_real_cpu_pool_cli_and_auto_busy_policy(tmp_path):
    from backend.api.routes_em_analysis import ROOT, solver_python
    executable = solver_python()
    if not executable:
        pytest.skip('Optional isolated EM environment missing')
    payload = {'particles': [{'id': 'optical', 'center_nm': [0, 0, 0], 'diameter_nm': 5}],
               'resolution': 25, 'shell': {'model': 'none'}}
    entries = [json.dumps({'frame_index': i, 'input': payload}) for i in (2, 4, 8)]
    destination = tmp_path/'real'
    process = subprocess.run([executable, '-m', 'backend.physics.em_volume_archive', str(destination),
                              '--compute-backend', 'cpu', '--workers', '2'], cwd=ROOT,
        input='\n'.join(entries), capture_output=True, text=True, timeout=60,
        env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
    assert process.returncode == 0, process.stdout+process.stderr
    manifest = json.loads((destination/'manifest.json').read_text())
    assert manifest['status'] == 'complete'
    assert manifest['processing']['decisions'][0]['workers'] <= 2
    first = read_frame(destination, 0)
    for i in (1, 2):
        assert first['intensity'].tobytes() == read_frame(destination, i)['intensity'].tobytes()
    assert [r['frame_index'] for r in manifest['frames']] == [2, 4, 8]
