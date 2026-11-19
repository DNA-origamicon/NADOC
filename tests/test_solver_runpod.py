"""Budgeted provider lifecycle tests; never create a real pod."""
import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from backend.core import solver_runpod
from backend.core.solver_cluster_config import SolverRunpodSettings
from tests.test_solver_cluster import job_at


@pytest.mark.parametrize('engine,failure', [
    (engine, failure)
    for engine in ['snupi', 'mrdna']
    for failure in ['stale_quote', 'watchdog', 'software', 'process', 'none', 'vram', 'capacity', 'supply_race']
    if failure != 'vram' or engine == 'mrdna'
])
def test_run_destroys_exact_pod_and_preserves_receipt(tmp_path, monkeypatch, engine, failure):
    from backend.core import runpod_api, runpod_conn, solver_runpod_stock, runpod_watchdog
    if engine == 'mrdna':
        from tests.test_solver_resources import design
        monkeypatch.setattr('backend.core.mrdna_runner._load_snapshot_design', lambda _: design())
    job = job_at(tmp_path, engine)
    job.execution_target = 'runpod'
    job.remote = {'settings': {}, 'provisioning': True}
    job.save(tmp_path)
    events = []
    class Client:
        def __init__(self, *a, **kw): pass
        @asynccontextmanager
        async def pod(self, payload, on_created, **kw):
            events.append(('create', payload))
            if failure == 'supply_race': raise runpod_api.RunpodError('SUPPLY_CONSTRAINT')
            try:
                on_created(SimpleNamespace(id='owned-pod', cost_per_hr=1))
                yield SimpleNamespace(id='owned-pod', public_ip='127.0.0.1', ssh_port=22)
            finally:
                await self.terminate_pod('owned-pod')
        async def terminate_pod(self, pod_id): events.append(('terminate', pod_id))
        async def aclose(self): events.append(('close', None))
    class Conn:
        def __init__(self, **kw): pass
        async def connect(self): pass
        async def close(self): pass
        async def mkdir_p(self, path): pass
        async def sftp_put(self, source, target): pass
        async def run(self, command, **kw):
            events.append(('command', command))
            return SimpleNamespace(rc=0)
        async def launch_detached(self, script, directory): return 123
        async def pid_alive(self, pid): return False
        async def read_file(self, path):
            return '0' if path.endswith('solver.exit') else 'RUNNING' if failure == 'process' else 'FINISHED' 
    async def stock(*a): return {'gpu': {'on_demand': 2 if failure == 'stale_quote' else 1, 'stock': 'None' if failure == 'capacity' else 'High', 'vram_gb': None if failure == 'vram' else 48}}
    def watchdog(**kw):
        events.append(('watchdog', kw['pod_id']))
        if failure == 'watchdog': raise RuntimeError('watchdog unavailable')
    async def preflight(*a):
        if failure == 'software': raise RuntimeError('solver environment missing')
    async def collect(engine, job, workspace, *args):
        job.status = type(job.status)('completed')
        job.remote['results_collected'] = True
        job.save(workspace)
    monkeypatch.setattr(solver_runpod.shared, 'bundle_inputs', lambda *a: None)
    monkeypatch.setattr(solver_runpod.shared, 'collect', collect)
    monkeypatch.setattr(runpod_api, 'RunpodClient', Client)
    monkeypatch.setattr(solver_runpod_stock, 'fetch_solver_stock', stock)
    monkeypatch.setattr(runpod_watchdog, 'start_watchdog_service', watchdog)
    monkeypatch.setattr(runpod_conn, 'RunpodConnection', Conn)
    monkeypatch.setattr(solver_runpod.shared, 'preflight', preflight)
    config = SolverRunpodSettings(gpu_id='gpu', quoted_rate=1, budget_usd=5)
    asyncio.run(solver_runpod.run(engine, job.job_id, tmp_path, config, 'test-key', 'volume'))
    live = solver_runpod.shared.job_class(engine).load(job.job_id, tmp_path)
    assert live.status.value == ('completed' if failure == 'none' else 'failed')
    if failure == 'none':
        assert live.remote['results_collected']
        assert any('tar --no-same-owner -xzf inputs.tar.gz' in str(e[1]) for e in events if e[0] == 'command')
    if failure == 'process': assert 'without a completion receipt' in live.error
    if failure in ('stale_quote', 'vram', 'capacity'):
        assert not any(e[0] == 'create' for e in events)
    elif failure == 'supply_race':
        assert 'no pod was rented' in live.error
        assert len([e for e in events if e[0] == 'create']) == 1
        assert not any(e[0] == 'terminate' for e in events)
    else:
        payload = next(e[1] for e in events if e[0] == 'create')
        assert payload['minMemoryInGb'] == 69
        assert payload['terminateAfter']
        assert ('terminate', 'owned-pod') in events
        assert live.remote['pod_destroyed']
        assert live.remote['pod_id'] == 'owned-pod'
        assert live.remote['spent_usd'] >= 0


def test_interrupted_controller_never_relaunches(tmp_path, monkeypatch):
    monkeypatch.setattr(solver_runpod.shared, '_background', lambda *args: None)
    job = job_at(tmp_path, 'snupi')
    job.execution_target = 'runpod'; job.status = type(job.status)('running')
    job.remote = {'pod_id': 'existing'}; job.save(tmp_path)
    result = solver_runpod.reconcile(job, tmp_path, 'snupi')
    assert result.status.value == 'failed'
    assert result.remote['pod_id'] == 'existing'
    assert 'No automatic resubmission' in result.error
