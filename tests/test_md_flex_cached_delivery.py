"""VR and desktop flex requests share a warm, nonblocking artifact delivery path."""
import asyncio
import threading

import pytest

from backend.core.trajectory_cache import persistent_analysis


@pytest.mark.parametrize('analysis', ['md_rmsf', 'md_rmsf_atomistic', 'md_rmsf_surface'])
def test_warm_flex_skips_worker_and_changed_input_uses_normal_worker(tmp_path, monkeypatch, analysis):
    from backend.api import routes_md as routes
    from backend.core import md_trajectory

    (tmp_path / 'job.json').write_text('{"status":"completed"}')
    path = tmp_path / 'trajectory.dcd'
    path.write_text('original frames')
    calls = []

    @persistent_analysis
    def measure(path, *, include_model=False):
        calls.append(1)
        return {'ready': True, 'model': include_model, 'positions': [[1, 2, 3]]}

    monkeypatch.setattr(md_trajectory, analysis, measure)
    options = {'include_model': True} if analysis == 'md_rmsf_atomistic' else {}
    expected = measure(path, **options)
    read_threads = []
    reader = measure.read_cached

    def observed(*args, **kwargs):
        read_threads.append(threading.get_ident())
        return reader(*args, **kwargs)

    measure.read_cached = observed
    workers = []

    async def worker(*args, **kwargs):
        workers.append(args)
        return {'ready': True, 'normal_worker': True}

    monkeypatch.setattr(routes, '_run_md_analysis', worker)
    result = asyncio.run(routes._run_md_flex(None, 'job', 'flex', analysis, (path,)))
    assert result == expected
    assert len(calls) == 1
    assert not workers
    assert all(t != threading.get_ident() for t in read_threads)
    path.write_text('resumed trajectory frames')
    assert asyncio.run(routes._run_md_flex(None, 'job', 'flex', analysis, (path,)))['normal_worker']
    assert len(workers) == 1
