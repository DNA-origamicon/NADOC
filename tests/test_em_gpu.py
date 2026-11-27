"""Optional native CUDA oracle plus backend selection/failure contracts."""
import builtins
import json
import os
import subprocess

import pytest

from backend.physics import em_gpu
from backend.physics.em_volume_archive import write_snapshots


def test_missing_gpu_dependency_fails_explicitly(monkeypatch):
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == 'cupy':
            raise ImportError('not installed')
        return original(name, *args, **kwargs)
    em_gpu.runtime.cache_clear()
    monkeypatch.setattr(builtins, '__import__', importing)
    with pytest.raises(RuntimeError, match='No CPU fallback'):
        em_gpu.runtime()


def test_backend_override_is_recorded_and_failure_preserved(tmp_path):
    seen = []
    def solver(payload, *, arrays):
        seen.append(payload)
        raise RuntimeError('GPU device unavailable')
    path = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='GPU device unavailable'):
        write_snapshots([json.dumps({'frame_index': 3, 'input': {'compute_backend': 'cpu'}})],
                        path, solver=solver, compute_backend='gpu')
    assert seen == [{'compute_backend': 'gpu'}]
    manifest = json.loads((path / 'manifest.json').read_text())
    assert manifest['status'] == 'failed' and manifest['frames'] == []
    with pytest.raises(ValueError, match='backend'):
        write_snapshots([], tmp_path / 'invalid', compute_backend='automatic')
    assert not (tmp_path / 'invalid').exists()


@pytest.mark.skipif(os.environ.get('NADOC_TEST_EM_GPU') != '1', reason='Optional CUDA qualification')
def test_native_gpu_vectors_and_shells():
    from backend.api.routes_em_analysis import ROOT, solver_python
    executable = solver_python()
    assert executable, 'GPU qualification requested but EM environment missing'
    process = subprocess.run([executable, 'tests/em_gpu_oracle.py'], cwd=ROOT,
        capture_output=True, text=True, timeout=90,
        env={**os.environ, 'PYTHONPATH': str(ROOT), 'OPENBLAS_NUM_THREADS': '1',
             'OMP_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1'})
    assert process.returncode == 0, process.stdout + process.stderr


@pytest.mark.skipif(os.environ.get('NADOC_TEST_EM_GPU') != '1', reason='Optional CUDA qualification')
def test_gpu_trajectory_cli_preserves_frames_and_stops_on_failure(tmp_path):
    from backend.api.routes_em_analysis import ROOT, solver_python
    from backend.physics.em_volume_archive import read_frame
    executable = solver_python()
    assert executable
    payload = {'particles': [{'id': 'optical', 'center_nm': [0, 0, 0], 'diameter_nm': 5}],
               'resolution': 25, 'shell': {'model': 'none'}, 'compute_backend': 'cpu'}
    entries = [{'frame_index': i, 'time_ps': i*.1, 'input': payload} for i in (5, 15)]
    entries += [{'frame_index': 25, 'input': {**payload, 'resolution': 500}}, entries[0]]
    destination = tmp_path / 'trajectory'
    process = subprocess.run([executable, '-m', 'backend.physics.em_volume_archive',
                              str(destination), '--compute-backend', 'gpu'], cwd=ROOT,
        input='\n'.join(map(json.dumps, entries)), capture_output=True, text=True, timeout=60,
        env={**os.environ, 'PYTHONPATH': str(ROOT), 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'})
    assert process.returncode == 1, process.stdout + process.stderr
    manifest = json.loads((destination/'manifest.json').read_text())
    assert manifest['status'] == 'failed'
    assert [f['frame_index'] for f in manifest['frames']] == [5, 15]
    first, second = (read_frame(destination, i) for i in (0, 1))
    assert first['compute_backend'] == first['inputs']['compute_backend'] == 'gpu'
    assert first['compute_device']['precision'] == 'float64/complex128'
    assert second['time_ps'] == 1.5
    assert first['intensity'].tobytes() == second['intensity'].tobytes()
    assert not list(destination.glob('*.tmp'))
