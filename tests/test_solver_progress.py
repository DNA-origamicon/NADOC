"""Progress transport and actual dynamics counters without native computation."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.core.solver_progress import dynamics_progress, load_receipt, sync_remote_progress
from tests.test_solver_cluster import job_at


def job():
    return SimpleNamespace(status=SimpleNamespace(value='running'), remote={})


def test_step_counter_not_weighted_fraction_or_static_load_steps():
    p = dynamics_progress(job(), {'phase': 'trajectory', 'fraction': .55,
        'step': 30000, 'n_steps': 60000, 'steps_per_s': 100})
    assert p['overall'] == .5
    assert p['current_step'] == 30000
    assert p['total_steps'] == 60000
    assert p['eta_seconds'] == 300
    assert not p['progress_indeterminate']


@pytest.mark.parametrize('sample', [{}, {'phase': 'mesh', 'fraction': .12},
    {'phase': 'Calculating stable dynamics timestep', 'step': 0, 'n_steps': 60000}])
def test_setup_never_invents_percent_or_eta(sample):
    p = dynamics_progress(job(), sample)
    assert p['overall'] == 0
    assert p['progress_indeterminate']
    assert p['total_steps'] == 60000
    assert p['eta_seconds'] is None


def test_retry_can_reset_and_finished_steps_remain_distinct_from_completed_job():
    p = dynamics_progress(job(), {'phase': 'trajectory', 'step': 500, 'n_steps': 60000, 'attempt': 1})
    assert p['overall'] == 500 / 60000
    assert p['attempt'] == 1
    p = dynamics_progress(job(), {'phase': 'Analyzing dynamics trajectory', 'step': 60000, 'n_steps': 60000})
    assert p['overall'] == 1
    assert p['status'] == 'running'
    assert p['eta_seconds'] is None


def test_stale_transport_retains_counter_but_never_projects_it():
    receipt = {'retrieved_at': 100, 'sample': {'phase': 'trajectory', 'step': 15000,
        'n_steps': 60000, 'steps_per_s': 100, 'at': 10}}
    fresh = dynamics_progress(job(), receipt, remote=True, now=110)
    stale = dynamics_progress(job(), receipt, remote=True, now=150)
    assert fresh['overall'] == stale['overall'] == .25
    assert not fresh['progress_last_known']  # an old phase timestamp isn't a lost connection
    assert stale['progress_last_known']
    assert fresh['eta_seconds'] == 450
    assert stale['eta_seconds'] is None


def test_completed_and_malformed_values():
    j = job(); j.status.value = 'completed'
    assert dynamics_progress(j, {})['overall'] == 1
    p = dynamics_progress(job(), {'step': float('nan'), 'n_steps': float('inf')})
    assert p['current_step'] is None and p['total_steps'] == 60000


def test_bounded_remote_sync_preserves_last_sample_and_job_ownership(tmp_path):
    j = job_at(tmp_path, 'snupi')
    j.remote['directory'] = '/workspace/a path'
    j.save(tmp_path)
    manifest = (j.job_dir(tmp_path) / 'job.json').read_bytes()
    sample = {'phase': 'trajectory', 'step': 12000, 'n_steps': 60000}
    class Conn:
        content = json.dumps(sample)
        async def run(self, command, timeout):
            assert 'head -c 16385' in command and timeout == 10
            assert "'/workspace/a path/" in command
            return SimpleNamespace(rc=0, stdout=self.content)
    conn = Conn()
    assert asyncio.run(sync_remote_progress('snupi', j, tmp_path, conn))
    before = load_receipt(j.job_dir(tmp_path), remote=True)
    assert before['sample'] == sample
    for payload in ['{', 'x' * 17000, '[]', '{}']:
        conn.content = payload
        assert not asyncio.run(sync_remote_progress('snupi', j, tmp_path, conn))
        assert load_receipt(j.job_dir(tmp_path), remote=True) == before
    assert (j.job_dir(tmp_path) / 'job.json').read_bytes() == manifest


def test_route_lists_actual_dynamics_counters(tmp_path, monkeypatch):
    import time
    from backend.api import routes_snupi
    j = job_at(tmp_path, 'snupi'); j.dynamics = True
    j.status = type(j.status)('running'); j.n_steps = 20
    j.save(tmp_path)
    (j.job_dir(tmp_path) / 'remote-progress.json').write_text(json.dumps({
        'retrieved_at': time.time(), 'sample': {'phase': 'trajectory', 'step': 30000,
            'n_steps': 60000, 'steps_per_s': 100}}))
    monkeypatch.setattr(routes_snupi, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_snupi, '_current_fingerprint', lambda: None)
    monkeypatch.setattr(routes_snupi, 'reconcile_snupi_status', lambda j, ws: j)
    rows, _ = routes_snupi._list_snupi_jobs()
    assert rows[0]['current_step'] == 30000
    assert rows[0]['total_steps'] == 60000
    assert rows[0]['progress_fraction'] == .5
    assert rows[0]['eta_seconds'] == 300


def test_worker_reports_retry_counts_and_excludes_setup_from_rate(tmp_path, monkeypatch):
    from backend.core import snupi_runner as runner
    from backend.physics import fem_solver
    j = job_at(tmp_path, 'snupi'); j.dynamics = True; j.remote = None
    clock = [0.0]
    observed = []
    def predict(design, progress_cb, **kw):
        clock[0] = 1000  # expensive setup must not depress trajectory throughput
        progress_cb(0, 'Calculating stable dynamics timestep', {'step': 0, 'n_steps': 60000})
        progress_cb(.1, 'trajectory', {'step': 0, 'n_steps': 60000, 'attempt': 0})
        clock[0] = 1010
        progress_cb(.55, 'trajectory', {'step': 30000, 'n_steps': 60000, 'attempt': 0})
        observed.append(runner.read_progress(j.job_dir(tmp_path)))
        progress_cb(.1, 'trajectory (restarted: dt halved after divergence)', {'step': 0, 'n_steps': 60000, 'attempt': 1})
        clock[0] = 1020
        progress_cb(.1075, 'trajectory', {'step': 500, 'n_steps': 60000, 'attempt': 1})
        observed.append(runner.read_progress(j.job_dir(tmp_path)))
        return {}
    monkeypatch.setattr(runner, '_load_snapshot_design', lambda _: object())
    monkeypatch.setattr(runner, '_cache_fem_analysis', lambda *a: None)
    monkeypatch.setattr(runner.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(fem_solver, 'predict_shape', predict)
    runner.solve_and_cache(j, tmp_path)
    assert observed[0]['steps_per_s'] == 3000
    assert observed[0]['eta_s'] == 10
    assert observed[1]['step'] == 500 and observed[1]['attempt'] == 1
    assert observed[1]['steps_per_s'] == 50
    assert runner.job_progress(j, tmp_path)['overall'] == 1


def test_integrator_counter_counts_finished_updates_and_final_partial_interval():
    import numpy as np
    from backend.physics.snupi_dynamics import gjf_integrate
    counters = []
    gjf_integrate(lambda q: -q, np.zeros(1), np.ones(1), np.ones(1),
        n_steps=503, n_equil=0, sample_every=100, dt=.01,
        progress_cb=lambda f, step: counters.append((f, step)))
    assert counters[0] == (1 / 503, 1)
    assert counters[-1] == (1, 503)
