"""Real-process tests for interactive takeover, cancellation and cache publication."""
import os
import subprocess
import sys
import time

import pytest

from backend.core import trajectory_priority as priority
from backend.core.trajectory_cache import persistent_analysis


@pytest.fixture
def demand_dir(tmp_path, monkeypatch):
    directory = tmp_path / 'demand'
    directory.mkdir()
    monkeypatch.setattr(priority, '_directory', lambda: directory)
    monkeypatch.delenv('NADOC_PRECOMPUTE_WORKER', raising=False)
    return directory


def _wait_for(path, child):
    deadline = time.monotonic() + 10
    while not path.exists():
        assert child.poll() is None, child.stderr.read()
        assert time.monotonic() < deadline, 'child did not reach calculation'
        time.sleep(.01)


@pytest.mark.parametrize("same_artifact", [True, False])
def test_click_preempts_background_lock_and_persists(tmp_path, demand_dir, same_artifact):
    job = tmp_path / 'job'
    job.mkdir()
    (job / 'job.json').write_text('{"status":"completed"}')
    trajectory = job / 'trajectory.dat'
    trajectory.touch()
    started = tmp_path / 'started'
    script = '''
import sys, time
from pathlib import Path
from backend.core import trajectory_priority as priority
from backend.core.trajectory_cache import persistent_analysis
priority._directory = lambda: Path(sys.argv[2])
@persistent_analysis
def analyze(path):
    Path(sys.argv[3]).touch()
    time.sleep(60)
    return {'ready': True, 'source': 'background'}
priority.BACKFILL_PROCESS = True
analyze(Path(sys.argv[1]))
'''
    child = subprocess.Popen(
        [sys.executable, '-c', script, str(trajectory), str(demand_dir), str(started)],
        env=dict(os.environ, NADOC_PRECOMPUTE_WORKER='1'), stderr=subprocess.PIPE,
    )
    selected = trajectory if same_artifact else job / 'another-trajectory.dat'
    if not same_artifact:
        selected.touch()
    calls = []

    @persistent_analysis
    def analyze(path):
        calls.append(1)
        if not same_artifact:
            # Hold an actual foreground calculation open while backfill yields.
            assert child.wait(timeout=3) == priority.PREEMPTED
        return {'ready': True, 'source': 'foreground'}

    try:
        _wait_for(started, child)
        start = time.monotonic()
        assert analyze(selected)['source'] == 'foreground'
        assert time.monotonic() - start < 5
        assert child.wait(timeout=5) == priority.PREEMPTED
        assert not priority.foreground_active()
        assert analyze(selected)['source'] == 'foreground'
        assert len(calls) == 1
        assert list((job / 'analysis_cache').glob('*.json'))
        if same_artifact:
            # Resumed backfill consumes the foreground artifact without repeating
            # the long calculation; its fake cold computation would take 60 seconds.
            resumed = subprocess.run(
                [sys.executable, '-c', script, str(trajectory), str(demand_dir), str(started)],
                env=dict(os.environ, NADOC_PRECOMPUTE_WORKER='1'),
                capture_output=True, timeout=5,
            )
            assert resumed.returncode == 0, resumed.stderr
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_cancelled_foreground_does_not_block_backfill(tmp_path, demand_dir):
    started = tmp_path / 'started'
    script = '''
import sys, time
from pathlib import Path
from backend.core import trajectory_priority as priority
priority._directory = lambda: Path(sys.argv[1])
with priority.foreground_work():
    Path(sys.argv[2]).touch()
    time.sleep(60)
'''
    child = subprocess.Popen(
        [sys.executable, '-c', script, str(demand_dir), str(started)], stderr=subprocess.PIPE,
    )
    try:
        _wait_for(started, child)
        assert priority.foreground_active()
        child.kill()
        child.wait(timeout=5)
        assert not priority.foreground_active()
        assert not list(demand_dir.glob('request-*'))
    finally:
        if child.poll() is None:
            child.kill()
        child.wait()


def test_warm_read_does_not_advertise_foreground_demand(tmp_path, demand_dir, monkeypatch):
    (tmp_path / 'job.json').write_text('{"status":"completed"}')
    path = tmp_path / 'trajectory.dat'
    path.touch()

    @persistent_analysis
    def analyze(path):
        return {'ready': True}

    analyze(path)

    def unexpected():
        raise AssertionError('warm cache must not interrupt backfill')

    monkeypatch.setattr(priority, 'foreground_work', unexpected)
    assert analyze(path)['ready']


def test_exception_releases_foreground_demand(tmp_path, demand_dir):
    (tmp_path / 'job.json').write_text('{"status":"completed"}')
    path = tmp_path / 'trajectory.dat'
    path.touch()

    @persistent_analysis
    def analyze(path):
        assert priority.foreground_active()
        raise RuntimeError('failed computation')

    with pytest.raises(RuntimeError, match='failed computation'):
        analyze(path)
    assert not priority.foreground_active()
    assert not list((tmp_path / 'analysis_cache').glob('*.json'))


def test_preempted_backfill_requeues_after_foreground_finishes(monkeypatch):
    import queue
    from types import SimpleNamespace
    from backend.core import trajectory_precompute as worker

    class Finished(Exception):
        pass

    class WorkQueue(queue.Queue):
        reads = 0

        def get(self, *args, **kwargs):
            self.reads += 1
            if self.reads > 2:
                raise Finished
            return super().get(*args, **kwargs)

    work = WorkQueue()
    key = ('/workspace', 'md', 'job')
    work.put(key)
    monkeypatch.setattr(worker, '_QUEUE', work)
    monkeypatch.setattr(worker, '_PENDING', {key})
    monkeypatch.setattr(worker, '_RECENT', {})
    demand = iter([True, False, False])
    monkeypatch.setattr(priority, 'foreground_active', lambda: next(demand))
    sleeps = []
    monkeypatch.setattr(worker.time, 'sleep', sleeps.append)
    exits = iter([priority.PREEMPTED, 0])
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=next(exits), stderr=b'')

    monkeypatch.setattr(worker.subprocess, 'run', run)
    with pytest.raises(Finished):
        worker._drain()
    assert len(calls) == 2
    assert sleeps == [.1]
    assert not worker._PENDING
    assert key in worker._RECENT
    assert work.unfinished_tasks == 0
