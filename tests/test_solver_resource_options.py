"""Count-only planning tests; no authored molecular artifacts or cloud jobs."""
from types import SimpleNamespace as NS
import pytest
from backend.core.solver_resource_options import resource_preview, alpine_choices
from backend.core.solver_resources import check_resources, MemoryBudgetExceeded


def design(n):
    return NS(strands=[NS(domains=[NS(start_bp=0, end_bp=n-1)])],
              extensions=[], crossovers=[], helices=[])


def test_fine_and_assembly_counts_raise_allocation_minima(tmp_path):
    coarse = resource_preview('mrdna', design(100000), NS(), tmp_path)
    fine = resource_preview('mrdna', design(100000), NS(fine_steps=10000), tmp_path)
    assembly = resource_preview('mrdna', design(1000000), NS(), tmp_path)
    assert coarse['min_ram_gib'] < fine['min_ram_gib'] < assembly['min_ram_gib']
    assert coarse['min_vram_gb'] < fine['min_vram_gb'] < assembly['min_vram_gb']
    assert fine['min_ram_gib'] * .8 >= fine['ram_gib']


def test_alpine_profile_limits_and_cuda(tmp_path):
    rows = {r['id']: r for r in alpine_choices(tmp_path)}
    assert rows['aa100']['vram_gb'] == 40
    assert not rows['ami100']['cuda']
    assert rows['ah200']['max_ram_gib'] == 1536
    assert all(q['name'].startswith('gpu-') for q in rows['aa100']['qos'])


@pytest.mark.parametrize('settings,error', [
    ({'partition': 'aa100', 'mem_gb': 64, 'cores': 1}, 'allocated host RAM'),
    ({'partition': 'ami100', 'mem_gb': 16, 'cores': 8}, 'CUDA'),
    ({'partition': 'aa100', 'mem_gb': 240, 'cores': 64}, 'GPU memory'),
])
def test_alpine_admission_rejects_ineligible_allocation(tmp_path, monkeypatch, settings, error):
    from backend.core import solver_resources as resources
    monkeypatch.setattr(resources, 'available_for_work', lambda: 1024**4)
    monkeypatch.setattr(resources, 'cgroup_available', lambda: 1024**4)
    monkeypatch.setattr(resources.shutil, 'disk_usage', lambda _: NS(free=1024**4))
    n = 2_100_000 if error == 'GPU memory' else 100
    with pytest.raises(MemoryBudgetExceeded, match=error):
        check_resources('mrdna', design(n), NS(execution_target='alpine', cluster_settings=settings), tmp_path)

@pytest.mark.parametrize('engine,model', [('snupi', 'CreateSnupiJobRequest'), ('mrdna', 'CreateMrdnaJobRequest')])
def test_estimate_route_uses_active_projection_without_creating_job(engine, model, monkeypatch, tmp_path):
    import importlib
    from unittest.mock import Mock
    routes = importlib.import_module(f'backend.api.routes_{engine}')
    monkeypatch.setattr(routes.design_state, 'get_or_404', lambda: design(100000))
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    create = Mock(side_effect=AssertionError('Estimate must not create a job'))
    monkeypatch.setattr(routes, f'new_{engine}_job', create)
    result = routes.resource_estimate(getattr(routes, model)())
    assert result['min_ram_gib'] > result['ram_gib']
    create.assert_not_called()
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('engine', ['snupi', 'mrdna'])
def test_runtime_preview_tracks_size_and_solver_options(tmp_path, engine):
    coarse = resource_preview(engine, design(2520), NS(nonlinear=False), tmp_path)['runtime']
    large = resource_preview(engine, design(25200), NS(nonlinear=False), tmp_path)['runtime']
    fine = resource_preview(engine, design(2520), NS(nonlinear=True, fine_steps=100000), tmp_path)['runtime']
    assert 0 < coarse['seconds'] < large['seconds']
    assert coarse['seconds'] < fine['seconds']
    assert 'reference' in coarse['basis']
    assert 'excluding queue' in coarse['note']


def test_runpod_options_can_show_unavailable_without_offering_them_in_old_picker(monkeypatch):
    import asyncio
    from backend.api import routes_solver_cluster, routes_runpod
    from backend.core import solver_runpod_stock
    monkeypatch.setattr(routes_runpod, '_SESSION', NS(is_connected=lambda: True, api_key='test', network_volume_id='volume'))
    async def stock(*args):
        return {'available': {'stock': 'Low', 'on_demand': 1},
                'missing': {'stock': 'None', 'on_demand': None}}
    monkeypatch.setattr(solver_runpod_stock, 'fetch_solver_stock', stock)
    ordinary = asyncio.run(routes_solver_cluster.runpod_options(64, 8, False))
    wizard = asyncio.run(routes_solver_cluster.runpod_options(64, 8, True))
    assert [r['id'] for r in ordinary['gpus']] == ['available']
    assert [r['id'] for r in wizard['gpus']] == ['available', 'missing']
