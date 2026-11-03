"""Job and stage labels must not discard usable trajectory snapshots."""
import asyncio
import queue
from types import SimpleNamespace

import pytest

from backend.core.md_job import MdStatus
from backend.core.oxdna_job import OxdnaStatus

STATUSES = sorted({s.value for cls in (MdStatus, OxdnaStatus) for s in cls})


@pytest.mark.parametrize('status', STATUSES)
def test_background_policy_covers_every_job_status(tmp_path, monkeypatch, status):
    from backend.core import trajectory_precompute as worker

    monkeypatch.delenv('NADOC_PRECOMPUTE_WORKER', raising=False)
    monkeypatch.setattr(worker, '_QUEUE', queue.Queue())
    monkeypatch.setattr(worker, '_PENDING', set())
    monkeypatch.setattr(worker, '_RECENT', {})
    monkeypatch.setattr(worker, '_THREAD', SimpleNamespace(is_alive=lambda: True))
    job = SimpleNamespace(status=SimpleNamespace(value=status), job_id='test', job_dir=lambda ws: tmp_path)
    worker.schedule(job, tmp_path, 'md')
    assert worker._QUEUE.qsize() == (0 if status in {'draft', 'preparing', 'running'} else 1)


@pytest.mark.parametrize('stage_status', ['pending', 'running', 'done', 'failed'])
def test_oxdna_metrics_and_flex_use_written_frames_regardless_of_stage_label(tmp_path, monkeypatch, stage_status):
    from backend.api import routes_oxdna as routes, routes_oxdna_metrics as metrics
    from backend.core import oxdna_health
    from backend.core.models import Design

    (tmp_path / 'design.json').write_text('{}')
    traj = tmp_path / 'trajectory.dat'
    traj.write_text('existing frames')
    design = object()
    job = SimpleNamespace(job_id='test', stages=[SimpleNamespace(kind='production', name='sample', status=stage_status)],
                          job_dir=lambda ws: tmp_path, stage_dir=lambda ws, name: tmp_path)
    monkeypatch.setattr(Design, 'from_json', lambda text: design)
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes, '_load_job', lambda jid: job)
    monkeypatch.setattr(routes, '_stage_trajectories', lambda directory: [traj])
    monkeypatch.setattr(metrics, '_stage_trajectories', lambda directory: [traj])
    monkeypatch.setattr(routes, '_design_ref_conf', lambda *a: tmp_path / 'ref.dat')
    monkeypatch.setattr(metrics, '_design_ref_conf', lambda *a: tmp_path / 'ref.dat')
    monkeypatch.setattr(routes, '_capture_bead_count', lambda j: 0)
    monkeypatch.setattr(routes, '_capture_strand_length', lambda j: 0)
    calls = []

    def rmsf(d, paths, ref, **kwargs):
        assert d is design
        calls.append(paths)
        return {'ready': True, 'n_frames': 2, 'positions': [], 'average_frame': {'test': 'mean'}}

    monkeypatch.setattr(oxdna_health, 'production_rmsf_cached', rmsf)
    assert metrics._job_inputs(job, tmp_path)[2] == [traj]
    assert routes._rmsf_average_frame(job)[1] == {'test': 'mean'}
    result = asyncio.run(routes.get_oxdna_rmsf('test'))
    assert result['ready']
    assert calls == [[traj], [traj]]
