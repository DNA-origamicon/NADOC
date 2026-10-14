"""UI polling must respect a headless native runner in a different process.

Only the numeric FEM solve is replaced with a controllable callback; snapshots,
CanDo runner threads, manifests, route start/stop/reconcile and kernel ownership
are the production implementations. No GPU or long simulation is required.
"""
from __future__ import annotations

import asyncio
import json
import multiprocessing
import time
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.core import simulation_runtime as runtime


def _until(predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.02)
    raise AssertionError('Timed out waiting for simulation lifecycle condition')


def _headless_cando(workspace, job_id, ready):
    from backend.api import routes_cando
    from backend.core import cando_runner
    from backend.physics import fem_solver

    def predict(design, *, progress_cb, **kwargs):
        ready.set()
        while True:
            progress_cb('solve', .25)
            time.sleep(.02)

    fem_solver.predict_shape = predict
    with runtime.use_workspace(workspace):
        asyncio.run(routes_cando.start_cando_job(job_id))
        _until(lambda: not runtime.is_owned(Path(workspace) / 'cando_jobs' / job_id), 25)
    # Native runner has consumed stop and persisted its own terminal status.
    assert not cando_runner.is_running(job_id)


def _client(monkeypatch, workspace):
    from backend.api import routes_cando

    monkeypatch.setattr(routes_cando, '_WORKSPACE_DIR', workspace)
    monkeypatch.setattr(routes_cando, '_current_fingerprint', lambda: None)
    app = FastAPI()
    app.include_router(routes_cando.router, prefix='/api')
    return TestClient(app)


def _make_job(workspace):
    from backend.core import cando_runner
    from backend.core.cando_job import new_cando_job
    from backend.core.models import Design

    job = new_cando_job('cross-process ownership', nonlinear=False, with_rmsf=False)
    job.save(workspace)
    cando_runner.prepare_cando_job(Design(name='owner-test'), job, workspace)
    return job


def test_ui_polling_stop_and_resume_headless_cando(tmp_path, monkeypatch):
    from backend.api import routes_cando
    from backend.core import cando_runner
    from backend.core.cando_job import CandoJob, CandoStatus
    from backend.physics import fem_solver

    job = _make_job(tmp_path)
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    owner = ctx.Process(target=_headless_cando, args=(str(tmp_path), job.job_id, ready))
    owner.start()
    try:
        assert ready.wait(15)
        directory = job.job_dir(tmp_path)
        before = (directory / 'job.json').read_bytes()
        first_generation = json.loads((directory / '.runtime.json').read_text())['generation']
        with _client(monkeypatch, tmp_path) as client:
            for _ in range(3):
                response = client.get(f'/api/cando/jobs/{job.job_id}')
                assert response.status_code == 200
                assert response.json()['status'] == 'running'
                assert (directory / 'job.json').read_bytes() == before
            duplicate = client.post(f'/api/cando/jobs/{job.job_id}/start')
            assert duplicate.status_code == 200
            assert duplicate.json()['message'] == 'Job already running'
            assert (directory / 'job.json').read_bytes() == before
            assert client.post(f'/api/cando/jobs/{job.job_id}/stop').status_code == 200
            owner.join(10)
            assert owner.exitcode == 0
            assert CandoJob.load(job.job_id, tmp_path).status == CandoStatus.stopped

            # The previous generation's stop message must not cancel a resume.
            def predict(design, **kwargs):
                return {'solver': 'controlled', 'axis': [], 'positions': []}

            monkeypatch.setattr(fem_solver, 'predict_shape', predict)
            monkeypatch.setattr(cando_runner, '_cache_fem_analysis', lambda *args: None)
            assert client.post(f'/api/cando/jobs/{job.job_id}/start').status_code == 200
            _until(lambda: not runtime.is_owned(directory))
            assert CandoJob.load(job.job_id, tmp_path).status == CandoStatus.completed
            assert json.loads((directory / '.runtime.json').read_text())['generation'] != first_generation
            assert routes_cando._WORKSPACE_DIR == tmp_path
    finally:
        if owner.is_alive():
            owner.kill()
        owner.join(5)


def test_ui_recovers_actual_dead_headless_owner(tmp_path, monkeypatch):
    from backend.core.cando_job import CandoJob, CandoStatus

    job = _make_job(tmp_path)
    ctx = multiprocessing.get_context('spawn')
    ready = ctx.Event()
    owner = ctx.Process(target=_headless_cando, args=(str(tmp_path), job.job_id, ready))
    owner.start()
    try:
        assert ready.wait(15)
        owner.kill()
        owner.join(5)
        assert not runtime.is_owned(job.job_dir(tmp_path))
        with _client(monkeypatch, tmp_path) as client:
            response = client.get(f'/api/cando/jobs/{job.job_id}')
            assert response.status_code == 200
            assert response.json()['status'] == 'stopped'
        assert CandoJob.load(job.job_id, tmp_path).status == CandoStatus.stopped
    finally:
        if owner.is_alive():
            owner.kill()
        owner.join(5)


def test_start_request_releases_rejection_and_transfers_only_once(tmp_path):
    from dataclasses import dataclass
    import threading

    directory = tmp_path / 'jobs' / 'same'
    entered = threading.Event()
    leave = threading.Event()
    registry = {}

    @dataclass
    class Handle:
        thread: threading.Thread

    @runtime.start_request(lambda: tmp_path, 'jobs')
    async def start(job_id):
        assert not runtime.is_owned(directory)  # own request may inspect idle state
        assert runtime.launch_thread(directory, job_id, lambda: (entered.set(), leave.wait(5)),
                                     registry, Handle, lambda: leave.set(), name='reserved-test')
        assert not runtime.launch_thread(directory, job_id, lambda: None,
                                         registry, Handle, lambda: None, name='duplicate-test')
        return {'ok': True}

    try:
        assert asyncio.run(start('same')) == {'ok': True}
        assert entered.wait(2)
        assert asyncio.run(start('same'))['message'] == 'Job already running'
        assert runtime.is_owned(directory)
    finally:
        leave.set()
        registry['same'].thread.join(5)
    assert not runtime.is_owned(directory)

    @runtime.start_request(lambda: tmp_path, 'jobs')
    async def rejected(job_id):
        raise HTTPException(400, 'not ready')

    state = (directory / '.runtime.json').read_bytes()
    with pytest.raises(HTTPException):
        asyncio.run(rejected('same'))
    assert (directory / '.runtime.json').read_bytes() == state
    assert not runtime.is_owned(directory)


def test_workspace_override_is_context_local_and_registries_are_scoped(tmp_path):
    registry = runtime.Registry()
    first, second = tmp_path / 'a', tmp_path / 'b'

    async def caller(path, value):
        with runtime.use_workspace(path):
            registry['copied-job'] = value
            await asyncio.sleep(0)
            assert runtime.workspace(tmp_path) == path
            assert registry['copied-job'] == value

    async def both():
        await asyncio.gather(caller(first, 'a'), caller(second, 'b'))

    asyncio.run(both())
    assert runtime.workspace(tmp_path) == tmp_path
    assert registry.get('copied-job') is None  # ambiguous bare-ID inspection
    assert sorted(registry.values()) == ['a', 'b']
    with runtime.use_workspace(first):
        assert sorted(registry.values()) == ['a', 'b']


def test_job_read_coalescing_keeps_context_workspaces_separate(tmp_path, monkeypatch):
    from backend.api import state
    from backend.api.startup_cache import coalesce_job_reads

    monkeypatch.setattr(state, 'revision', lambda: 1)
    calls = []
    @coalesce_job_reads
    async def listing():
        calls.append(runtime.workspace(tmp_path))
        await asyncio.sleep(.01)
        return str(runtime.workspace(tmp_path))

    async def caller(path):
        with runtime.use_workspace(path):
            return await listing()

    async def both():
        return await asyncio.gather(caller(tmp_path / 'a'), caller(tmp_path / 'b'))

    assert asyncio.run(both()) == [str(tmp_path / 'a'), str(tmp_path / 'b')]
    assert len(calls) == 2


def test_headless_terminal_wait_uses_requested_workspace(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from backend.api import headless_oxdna_build as headless
    from backend.core import oxdna_runner
    from backend.core.oxdna_job import new_oxdna_job, OxdnaStatus

    target, foreign = tmp_path / 'target', tmp_path / 'foreign'
    job = new_oxdna_job('terminal', [])
    job.status = OxdnaStatus.completed
    job.save(target)
    registry = runtime.Registry()
    with runtime.use_workspace(foreign):
        registry[job.job_id] = SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True))
    monkeypatch.setattr(oxdna_runner, '_RUNNING', registry)
    def unexpected_wait(_seconds):
        raise AssertionError('Terminal wait borrowed a handle from another workspace')
    monkeypatch.setattr(headless.time, 'sleep', unexpected_wait)
    assert headless.wait_for_terminal(job.job_id, target).status == OxdnaStatus.completed


def test_reconcile_refreshes_finished_owner_before_writing(tmp_path):
    from backend.core import cando_runner
    from backend.core.cando_job import CandoJob, CandoStatus

    job = _make_job(tmp_path)
    job.status = CandoStatus.running
    job.save(tmp_path)
    stale = CandoJob.load(job.job_id, tmp_path)
    lease = runtime.claim(job.job_dir(tmp_path))
    try:
        job.status = CandoStatus.completed
        job.sim_seconds = 12.25
        job.n_nodes = 321
        job.stages[0].status = 'done'
        job.save(tmp_path)
    finally:
        lease.close()
    before = (job.job_dir(tmp_path) / 'job.json').read_bytes()
    result = cando_runner.reconcile_cando_status(stale, tmp_path)
    assert result.status == CandoStatus.completed
    assert result.sim_seconds == 12.25
    assert result.n_nodes == 321
    assert (job.job_dir(tmp_path) / 'job.json').read_bytes() == before


@pytest.mark.parametrize('engine', ['snupi', 'blade'])
def test_detached_stop_does_not_overwrite_restart_after_worker_exit(tmp_path, monkeypatch, engine):
    import importlib

    runner = importlib.import_module(f'backend.core.{engine}_runner')
    models = importlib.import_module(f'backend.core.{engine}_job')
    job = getattr(models, f'new_{engine}_job')('restart race')
    status_type = type(job.status)
    job.status = status_type('running')
    job.save(tmp_path)
    directory = job.job_dir(tmp_path)
    old_owner = runtime.claim(directory)
    old_owner.identify('worker')
    restarted = []

    def kill_then_restart(_pid):
        old_owner.close()
        replacement = runtime.claim(directory)
        assert replacement is not None
        restarted.append(replacement)
        fresh = type(job).load(job.job_id, tmp_path)
        fresh.status = status_type('running')
        fresh.error = 'new execution sentinel'
        fresh.save(tmp_path)

    monkeypatch.setattr(runner, '_kill_pid', kill_then_restart)
    try:
        assert runner.stop_job(job.job_id, tmp_path)
        fresh = type(job).load(job.job_id, tmp_path)
        assert fresh.status == status_type('running')
        assert fresh.error == 'new execution sentinel'
        assert runtime.generation(directory) == restarted[0].generation
        assert not restarted[0].stop_requested()
    finally:
        old_owner.close()
        for lease in restarted:
            lease.close()


def test_orphan_stop_holds_ownership_until_manifest_is_saved(tmp_path, monkeypatch):
    from backend.core import lammps_runner
    from backend.core.lammps_job import new_lammps_job, LammpsJob, LammpsStatus

    job = new_lammps_job('orphan stop')
    job.status = LammpsStatus.running
    job.lammps_pid = 4242
    job.save(tmp_path)
    attempts = []
    def kill(_pid):
        # A competing start cannot reset state while this stop finalizes.
        claim = runtime.claim(job.job_dir(tmp_path))
        attempts.append(claim)
        if claim is not None:
            claim.close()
    monkeypatch.setattr(lammps_runner, '_pid_is_lammps', lambda pid: True)
    monkeypatch.setattr(lammps_runner, '_kill_process_group', kill)
    assert lammps_runner.stop_job(job.job_id, tmp_path)
    assert attempts == [None]
    assert LammpsJob.load(job.job_id, tmp_path).status == LammpsStatus.stopped
    assert not runtime.is_owned(job.job_dir(tmp_path))


def test_stop_route_does_not_save_its_stale_snapshot_after_native_stop(tmp_path, monkeypatch):
    from backend.api import routes_cando
    from backend.core.cando_job import CandoJob, CandoStatus

    job = _make_job(tmp_path)
    job.status = CandoStatus.running
    job.save(tmp_path)
    stale = CandoJob.load(job.job_id, tmp_path)
    restarted = []
    def finished_stop_then_restart(job_id, workspace):
        replacement = runtime.claim(job.job_dir(workspace))
        restarted.append(replacement)
        fresh = CandoJob.load(job_id, workspace)
        fresh.status = CandoStatus.running
        fresh.error = 'new execution sentinel'
        fresh.save(workspace)
        return False
    monkeypatch.setattr(routes_cando, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(routes_cando, '_load_job', lambda job_id: stale)
    monkeypatch.setattr(routes_cando, 'stop_job', finished_stop_then_restart)
    try:
        assert asyncio.run(routes_cando.stop_cando_job(job.job_id))['ok']
        fresh = CandoJob.load(job.job_id, tmp_path)
        assert fresh.status == CandoStatus.running
        assert fresh.error == 'new execution sentinel'
    finally:
        for lease in restarted:
            lease.close()


def test_legacy_completed_reconciliation_does_not_create_runtime_files(tmp_path):
    from backend.core import namd_runner
    from backend.core.md_job import MdStatus, new_job

    job = new_job('read-only completed', 'equilibrium_aware_namd', 'demo', 'pkg')
    job.status = MdStatus.completed
    job.save(tmp_path)
    before = {path.relative_to(tmp_path): path.read_bytes()
              for path in tmp_path.rglob('*') if path.is_file()}
    assert namd_runner.reconcile_job_status(job, tmp_path).status == MdStatus.completed
    after = {path.relative_to(tmp_path): path.read_bytes()
             for path in tmp_path.rglob('*') if path.is_file()}
    assert after == before
