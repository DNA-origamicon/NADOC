import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import numpy as np

from backend.core.trajectory_cache import persistent_analysis


def test_cache_reuses_results_preserves_arrays_and_invalidates(tmp_path):
    (tmp_path / 'job.json').write_text('{}')
    trajectory = tmp_path / 'trajectory.dat'
    trajectory.write_text('first')
    calls = []

    @persistent_analysis
    def analyze(path, setting=1, on_frame=None):
        calls.append(1)
        return {'ready': True, 'average_frame': {(1, 2): np.array([setting, 2.0])}}

    first = analyze(trajectory)
    second = analyze(trajectory, on_frame=lambda: None)
    np.testing.assert_array_equal(first['average_frame'][1, 2], second['average_frame'][1, 2])
    assert len(calls) == 1
    analyze(trajectory, setting=2)
    assert len(calls) == 2
    trajectory.write_text('new frames')
    analyze(trajectory)
    assert len(calls) == 3


def test_corruption_rebuilds_and_not_ready_is_not_cached(tmp_path):
    (tmp_path / 'job.json').write_text('{}')
    trajectory = tmp_path / 'trajectory.dat'
    trajectory.touch()
    calls = []

    @persistent_analysis
    def analyze(path):
        calls.append(1)
        return {'ready': len(calls) > 1}

    assert not analyze(trajectory)['ready']
    assert analyze(trajectory)['ready']
    artifact = next((tmp_path / 'analysis_cache').glob('*.json'))
    artifact.write_text('{bad')
    assert analyze(trajectory)['ready']
    assert len(calls) == 3
    assert json.loads(artifact.read_text())


def test_concurrent_readers_only_compute_once(tmp_path):
    (tmp_path / 'job.json').write_text('{}')
    trajectory = tmp_path / 'trajectory.dat'
    trajectory.touch()
    calls = []
    barrier = threading.Barrier(2)

    @persistent_analysis
    def analyze(path):
        calls.append(1)
        time.sleep(.05)
        return {'ready': True}

    def read():
        barrier.wait()
        return analyze(trajectory)

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(read) for _ in range(2)]
        assert all(f.result()['ready'] for f in futures)
    assert len(calls) == 1


def test_changed_during_compute_is_not_published(tmp_path):
    (tmp_path / 'job.json').write_text('{}')
    trajectory = tmp_path / 'trajectory.dat'
    trajectory.touch()

    @persistent_analysis
    def analyze(path):
        path.write_text('changed')
        return {'ready': True}

    analyze(trajectory)
    assert not list((tmp_path / 'analysis_cache').glob('*.json'))


def test_prepared_marker_checks_sources_and_artifacts(tmp_path):
    from backend.core.trajectory_cache import VERSION
    from backend.core.trajectory_precompute import _prepared, _source_stamp

    source = tmp_path / 'job.json'
    source.write_text('{}')
    cache = tmp_path / 'analysis_cache'
    cache.mkdir()
    artifact = cache / 'metrics.json'
    artifact.write_text('{}')
    marker = cache / 'prepared.json'
    marker.write_text(json.dumps({'version': VERSION, 'sources': _source_stamp(tmp_path),
                                  'artifacts': [artifact.name]}))
    assert _prepared(tmp_path)
    artifact.unlink()
    assert not _prepared(tmp_path)
    artifact.write_text('{}')
    source.write_text('{"resumed": true}')
    assert not _prepared(tmp_path)


def test_schedule_coalesces_and_skips_prepared_jobs(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.core import trajectory_precompute as worker
    import queue

    monkeypatch.delenv('NADOC_PRECOMPUTE_WORKER', raising=False)
    monkeypatch.setattr(worker, '_QUEUE', queue.Queue())
    monkeypatch.setattr(worker, '_PENDING', set())
    monkeypatch.setattr(worker, '_RECENT', {})
    monkeypatch.setattr(worker, '_THREAD', SimpleNamespace(is_alive=lambda: True))
    job = SimpleNamespace(status=SimpleNamespace(value='completed'), job_id='test',
                          job_dir=lambda ws: tmp_path)
    worker.schedule(job, tmp_path, 'md')
    worker.schedule(job, tmp_path, 'md')
    assert worker._QUEUE.qsize() == 1
    worker._PENDING.clear()
    monkeypatch.setattr(worker, '_prepared', lambda directory: True)
    worker.schedule(job, tmp_path, 'md')
    assert worker._QUEUE.qsize() == 1


def test_background_prepare_reuses_completed_artifacts(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.core import trajectory_precompute as worker
    from backend.core.oxdna_job import OxdnaJob
    from backend.api import routes_oxdna, routes_oxdna_metrics as metrics

    (tmp_path / 'job.json').write_text('{}')
    job = SimpleNamespace(status=SimpleNamespace(value='completed'), job_id='test',
                          job_dir=lambda ws: tmp_path)
    monkeypatch.setattr(OxdnaJob, 'load', lambda *a: job)
    monkeypatch.setattr(metrics, '_job_inputs', lambda *a: ('design', 'ref', []))
    calls = []
    monkeypatch.setattr(routes_oxdna, '_rmsf_average_frame', lambda *a: calls.append('flex'))

    def compute(*args):
        calls.append('metrics')
        (tmp_path / 'analysis_cache' / 'result.json').write_text('{}')
        metrics._RUNS['precompute'] = {'state': 'done', 'result': {'ready': True}}

    monkeypatch.setattr(metrics, '_compute', compute)
    worker.prepare(tmp_path, 'oxdna', 'test')
    worker.prepare(tmp_path, 'oxdna', 'test')
    assert calls == ['flex', 'metrics']


def test_cache_survives_process_restart(tmp_path):
    import subprocess
    import sys

    (tmp_path / 'job.json').write_text('{}')
    trajectory = tmp_path / 'trajectory.dat'
    trajectory.touch()

    @persistent_analysis
    def analyze(path):
        return {'ready': True, 'value': 42}

    analyze(trajectory)
    script = '''
import sys
from pathlib import Path
from backend.core.trajectory_cache import persistent_analysis
@persistent_analysis
def analyze(path):
    raise AssertionError("warm cache must not read trajectory")
assert analyze(Path(sys.argv[1]))['value'] == 42
'''
    subprocess.run([sys.executable, '-c', script, str(trajectory)], check=True)


def test_live_trajectory_does_not_accumulate_disk_artifacts(tmp_path):
    (tmp_path / 'job.json').write_text('{"status": "running"}')
    trajectory = tmp_path / 'trajectory.dat'
    trajectory.touch()

    @persistent_analysis
    def analyze(path):
        return {'ready': True}

    assert analyze(trajectory)['ready']
    assert not (tmp_path / 'analysis_cache').exists()
    (tmp_path / 'job.json').write_text('{"status": "completed"}')
    assert analyze(trajectory)['ready']
    assert list((tmp_path / 'analysis_cache').glob('*.json'))
