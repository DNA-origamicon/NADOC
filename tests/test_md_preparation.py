"""Preparation placement, allocation floors and verified package transfer."""
import json
from pathlib import Path
import tarfile
from types import SimpleNamespace

import pytest

from backend.core.md_preparation_plan import choose_preparation
from backend.core.md_preparation_bundle import digest, import_result
from backend.core.md_preparation_remote import alpine_script
from backend.core.md_resource_floors import alpine_memory_floor, runpod_memory_floor


def profile():
    from backend.core.cluster_config import load_profiles
    return load_profiles(Path('/nonexistent-nadoc-test'))['alpine']


@pytest.mark.parametrize('target', ['local', 'alpine', 'runpod'])
def test_capacity_keeps_preparation_local(target):
    plan = choose_preparation(5000, 6000, target)
    assert plan['ready'] and plan['location'] == 'local'


def test_desktop_shortage_moves_remote_without_lowering_budget():
    p = profile()
    plan = choose_preparation(14906, 7828, 'alpine', profile=p)
    assert plan['ready'] and plan['location'] == 'alpine'
    assert plan['mem_gb'] * 1024 >= 14906 + 4096 + 1024
    partition = p.partition(plan['partition'])
    assert plan['cores'] * partition.mem_per_core_gb >= plan['mem_gb']
    script = alpine_script('/scratch/test preparation', plan)
    assert f"#SBATCH --mem={plan['mem_gb']}G" in script
    assert f"#SBATCH --cpus-per-task={plan['cores']}" in script
    assert "cd '/scratch/test preparation'" in script


def test_no_cpu_capacity_is_not_certified():
    assert not choose_preparation(10000, 1000, 'alpine', profile=SimpleNamespace(partitions=[]))['ready']


def test_local_capacity_failure_is_actionable():
    result = choose_preparation(10000, 1000, 'local')
    assert not result['ready'] and 'Alpine or RunPod' in result['detail']


@pytest.mark.parametrize('required', [0, -1, float('inf'), float('nan')])
def test_invalid_estimate_fails_closed(required):
    with pytest.raises(ValueError):
        choose_preparation(required, 1000, 'local')


def make_result(tmp_path, *, corrupt=False):
    source = tmp_path / 'source'
    package = source / 'package'
    package.mkdir(parents=True)
    conf = package / 'run.conf'
    conf.write_text('native unchanged configuration')
    result = dict(package_subdir='package', name_stem='run', segments=[], files={'package/run.conf': digest(conf)})
    (source / 'result.json').write_text(json.dumps(result))
    if corrupt:
        conf.write_text('modified')
    archive = tmp_path / 'result.tar.gz'
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(package, arcname='package')
        tar.add(source / 'result.json', arcname='result.json')
    dest = tmp_path / 'job'
    dest.mkdir()
    return archive, dest


def test_verified_result_import_is_idempotent(tmp_path):
    archive, dest = make_result(tmp_path)
    first = import_result(archive, dest)
    assert import_result(archive, dest) == first
    assert (dest / 'package/run.conf').read_text() == 'native unchanged configuration'


def test_changed_transfer_is_rejected_before_publication(tmp_path):
    archive, dest = make_result(tmp_path, corrupt=True)
    with pytest.raises(ValueError, match='hash mismatch'):
        import_result(archive, dest)
    assert not (dest / 'package').exists()


def test_existing_different_package_is_preserved(tmp_path):
    archive, dest = make_result(tmp_path)
    (dest / 'package').mkdir()
    (dest / 'package/run.conf').write_text('original')
    with pytest.raises(ValueError, match='refusing to replace'):
        import_result(archive, dest)
    assert (dest / 'package/run.conf').read_text() == 'original'


def test_sparse_override_cannot_underallocate_ram_or_required_cores():
    result = alpine_memory_floor(dict(partition='acpu', mem_gb=1, cores=1), dict(mem_gb=20), profile())
    assert result['mem_gb'] == 20 and isinstance(result['mem_gb'], int)
    assert result['cores'] * profile().partition('acpu').mem_per_core_gb >= 20


def test_runpod_payload_requests_host_ram_and_cpu():
    payload = runpod_memory_floor([{}], 5_000_000, resident=True)[0]
    assert payload['minMemoryInGb'] > 8 and payload['minVcpuCount'] >= 4


def test_cancel_uses_preparation_allocation_not_namd(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from backend.core import cluster_ssh
    from backend.core.md_preparation_recovery import cancel_preparation
    from backend.core.alpine_transfer_state import atomic_json
    from backend.core.md_preparation_remote import state_path, read_state
    conn = SimpleNamespace(is_connected=lambda: True, run=AsyncMock(return_value=SimpleNamespace(rc=0)))
    monkeypatch.setattr(cluster_ssh, 'get_manager', lambda: conn)
    job = SimpleNamespace(job_dir=lambda _: tmp_path, slurm_job_id='999', save=lambda _: None)
    atomic_json(state_path(tmp_path), dict(target='alpine', phase='running', slurm_job_id='123'))
    result = asyncio.run(cancel_preparation(job, tmp_path))
    assert result['status'] == 'stopped'
    conn.run.assert_awaited_once_with('scancel 123')
    assert read_state(tmp_path)['phase'] == 'cancelled'
    assert job.slurm_job_id == '999'


def test_disconnected_cancel_keeps_pending_allocation(tmp_path, monkeypatch):
    import asyncio
    from backend.core import cluster_ssh
    from backend.core.md_preparation_recovery import cancel_preparation
    from backend.core.alpine_transfer_state import atomic_json
    from backend.core.md_preparation_remote import state_path, read_state
    monkeypatch.setattr(cluster_ssh, 'get_manager', lambda: SimpleNamespace(is_connected=lambda: False))
    job = SimpleNamespace(job_dir=lambda _: tmp_path, save=lambda _: None)
    atomic_json(state_path(tmp_path), dict(target='alpine', phase='running', slurm_job_id='123'))
    result = asyncio.run(cancel_preparation(job, tmp_path))
    assert result['pending_scancel']
    assert read_state(tmp_path)['slurm_job_id'] == '123'
    assert read_state(tmp_path)['phase'] == 'cancel_pending'


def test_alpine_reconnect_adopts_receipt_without_sbatch(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from backend.core import cluster_ssh, cluster_config
    from backend.core import md_preparation_remote as remote
    from backend.core.alpine_transfer_state import atomic_json
    archive = tmp_path / '.preparation/bundle.tar.gz'
    archive.parent.mkdir()
    archive.write_bytes(b'placeholder')
    job = SimpleNamespace(job_id='test', cluster_name='alpine', job_dir=lambda _: tmp_path)
    state = dict(target='alpine', phase='running', remote='/scratch/frozen', archive_sha256='abc', slurm_job_id='123')
    atomic_json(remote.state_path(tmp_path), state)
    conn = SimpleNamespace(user='test', is_connected=lambda: True, run=AsyncMock())
    monkeypatch.setattr(cluster_ssh, 'get_manager', lambda: conn)
    saved_profile = profile()
    monkeypatch.setattr(cluster_config, 'load_profiles', lambda _: {'alpine': saved_profile})
    monkeypatch.setattr(remote, '_poll', AsyncMock(return_value={'state':'complete'}))
    monkeypatch.setattr(remote, '_collect', AsyncMock(return_value=('package','run',[])))
    result = asyncio.run(remote.prepare_alpine(job,tmp_path,{'mem_gb':20},archive,'abc',lambda *args:None))
    assert result == ('package','run',[])
    conn.run.assert_not_awaited()
    assert remote.read_state(tmp_path)['phase'] == 'complete'


def test_second_controller_cannot_recover_owned_preparation(tmp_path):
    import asyncio
    from unittest.mock import AsyncMock
    from backend.core import simulation_runtime
    from backend.core.md_preparation_ownership import recover_owned
    job = SimpleNamespace(job_dir=lambda _: tmp_path)
    operation = AsyncMock()
    owner = simulation_runtime.claim(tmp_path / '.preparation')
    try:
        asyncio.run(recover_owned(operation, job, tmp_path, {}))
        operation.assert_not_awaited()
    finally:
        owner.close()
    asyncio.run(recover_owned(operation, job, tmp_path, {}))
    operation.assert_awaited_once()


def test_copied_draft_plans_from_frozen_design_not_active_tab(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from backend.api import routes_md
    from backend.core import md_preparation
    frozen = SimpleNamespace(without_reference_geometry=lambda: 'frozen-design')
    monkeypatch.setattr(routes_md, '_load_job', lambda _: object())
    monkeypatch.setattr(routes_md, '_md_snapshot_design', lambda _: frozen)
    def wrong_tab():
        raise AssertionError('The active tab does not own this copied draft')
    monkeypatch.setattr(routes_md.design_state, 'get_or_404', wrong_tab)
    plan = AsyncMock(return_value={'ready': True})
    monkeypatch.setattr(md_preparation, 'preparation_plan', plan)
    body = routes_md.CreateJobRequest()
    assert asyncio.run(routes_md.md_preparation_plan(body, job_id='draft'))['ready']
    assert plan.await_args.args[0] == 'frozen-design'


def test_output_from_other_inputs_is_rejected_before_publication(tmp_path):
    archive, dest = make_result(tmp_path)
    with pytest.raises(ValueError, match='different frozen inputs'):
        import_result(archive, dest, expected_input_manifest='expected-inputs')
    assert not (dest / 'package').exists()


@pytest.mark.parametrize("minimum_free_gb", [1, 10**9])
def test_bootstrap_failure_reports_status_and_cleans_node_scratch(tmp_path, minimum_free_gb):
    import os
    import subprocess
    from backend.core.md_preparation_bundle import bootstrap_command
    source = tmp_path / 'source'
    source.mkdir()
    uv = source / 'uv'
    uv.write_text('#!/bin/sh\nexit 17\n')
    uv.chmod(0o755)
    work = tmp_path / 'work'
    work.mkdir()
    scratch = tmp_path / 'scratch'
    scratch.mkdir()
    with tarfile.open(work / 'bundle.tar.gz', 'w:gz') as archive:
        archive.add(uv, arcname='uv')
    # Ensure both scratch and fallback paths can execute the intentionally failing tool.
    (work / 'uv').write_bytes(uv.read_bytes())
    (work / 'uv').chmod(0o755)
    result = subprocess.run(['bash', '-c', bootstrap_command(minimum_free_gb)], cwd=work,
        env={**os.environ, 'TMPDIR':str(scratch)}, capture_output=True, text=True)
    assert result.returncode == 17
    status = json.loads((work / 'status.json').read_text())
    assert status['state'] == 'failed' and '17' in status['error']
    assert list(scratch.iterdir()) == []


def test_runpod_preparation_uses_detached_launch_and_releases_pod(tmp_path, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock
    from backend.api import routes_md, routes_runpod
    from backend.core import md_preparation_remote as remote, runpod_conn, runpod_watchdog
    from backend.core.md_job import new_job, MdJob
    from backend.core.runpod_api import PodInfo
    job = new_job(design_name='test', protocol='equilibrium_aware_namd', name_stem='run', package_subdir='package')
    job.runpod_budget_usd = 1
    job.save(tmp_path)
    pod = PodInfo(id='test-pod', desired_status='RUNNING', public_ip='127.0.0.1', ssh_port=22, cost_per_hr=0.5, raw={})
    client = SimpleNamespace(create_pod_first_available=AsyncMock(return_value=pod), wait_for_ssh=AsyncMock(return_value=pod), terminate_pod=AsyncMock())
    conn = SimpleNamespace(connect=AsyncMock(), close=AsyncMock(), launch_detached=AsyncMock(return_value=123), pid_alive=AsyncMock(return_value=True))
    monkeypatch.setattr(routes_runpod, '_SESSION', SimpleNamespace(require=lambda:client))
    monkeypatch.setattr(routes_md, '_runpod_client_keys', lambda:['test-key'])
    monkeypatch.setattr(runpod_conn, 'RunpodConnection', lambda **kwargs:conn)
    monkeypatch.setattr(runpod_watchdog, 'start_watchdog_service', lambda **kwargs:'test-watchdog')
    monkeypatch.setattr(remote, '_stage', AsyncMock())
    monkeypatch.setattr(remote, '_put_text', AsyncMock())
    monkeypatch.setattr(remote, '_poll', AsyncMock(return_value={'state':'complete'}))
    monkeypatch.setattr(remote, '_collect', AsyncMock(return_value=('package','run',[])))
    archive = tmp_path / 'bundle.tar.gz'
    result = asyncio.run(remote.prepare_runpod(job,tmp_path,{'mem_gb':20,'cores':4},archive,'abc',lambda *args:None))
    assert result == ('package','run',[])
    conn.launch_detached.assert_awaited_once_with(f'/workspace/nadoc-preparation/{job.job_id}/prepare.sh', f'/workspace/nadoc-preparation/{job.job_id}')
    payloads = client.create_pod_first_available.await_args.args[0]
    assert all(p['minMemoryInGb'] == 20 and p['minVcpuCount'] == 4 for p in payloads)
    client.terminate_pod.assert_awaited_once_with('test-pod', reason='preparation_finished_or_interrupted')
    assert MdJob.load(job.job_id,tmp_path).runpod_pod_id is None
    conn.close.assert_awaited_once()


def test_preparation_spend_is_inside_execution_budget(tmp_path):
    from backend.core.md_resource_floors import runpod_budget_after_preparation
    from backend.core.md_preparation_remote import state_path
    from backend.core.alpine_transfer_state import atomic_json
    job = SimpleNamespace(job_dir=lambda _:tmp_path, runpod_billing_sessions=[
        {'pod_id':'prepare','cost_usd':0.25}, {'pod_id':'old-simulation','cost_usd':2}])
    atomic_json(state_path(tmp_path), {'target':'runpod','pod_id':'prepare','phase':'complete'})
    assert runpod_budget_after_preparation(job,tmp_path,1) == 0.75
    assert runpod_budget_after_preparation(job,tmp_path,0.1) == 0


def test_prepared_stage_host_ram_and_gpu_capacity_drive_runpod_request(tmp_path):
    from backend.core.namd_planning import memory_plan, prepared_stages
    from backend.core.runpod_script import GPU_TYPES
    import math
    manifest = {'minimization':{'name':'min','steps':100},'box_ang':[300,300,300]}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    (tmp_path/'min.conf').write_text('GPUresident off\npairlistdist 18\nPMEGridSpacing 1.0\nmargin 5\nminimize 100\n')
    memory = memory_plan(1_000_000, resident=True, stages=prepared_stages(tmp_path,manifest), box_nm=[30,30,30])
    largest = max(GPU_TYPES, key=lambda g:g.vram_mb)
    result = runpod_memory_floor([{'gpuTypeIds':[largest.key]}],1_000_000,resident=True,package=tmp_path)
    assert result[0]['minMemoryInGb'] >= math.ceil((memory['workflow_ram_mib']+512)/1024)
    with pytest.raises(ValueError,match='No eligible RunPod GPU'):
        runpod_memory_floor([{'gpuTypeIds':['unknown-small-device']}],1_000_000,resident=True,package=tmp_path)


def test_worker_returns_exact_package_from_node_scratch(tmp_path, monkeypatch):
    import cloudpickle
    from dataclasses import dataclass
    from backend.core import md_preparation_worker as worker, md_preparation_finalize
    @dataclass
    class Segment:
        name: str = 'run'
        stage: str = 'test'
        percent: int = 100
        steps: int = 1
    def prepare(design, directory, **kwargs):
        package = directory / 'package'
        package.mkdir()
        (package / 'run.conf').write_text('unchanged native input bytes\n')
        return 'package', 'run', [Segment()]
    prepare.__module__ = 'backend.core.md_protocols'
    monkeypatch.setattr(md_preparation_finalize, 'finalize_package', lambda *args: None)
    scratch, output, destination = [tmp_path/name for name in ('scratch','output','job')]
    for path in (scratch,output,destination):
        path.mkdir()
    request = scratch/'request.pkl'
    request.write_bytes(cloudpickle.dumps(dict(prepare=prepare, design={}, kwargs={}, bounded=False, body={}, graphene=None)))
    (scratch/'inputs.json').write_text(json.dumps({'request.pkl':digest(request)}))
    monkeypatch.chdir(scratch)
    monkeypatch.setenv('NADOC_PREP_OUTPUT_DIR', str(output))
    worker.main()
    status = json.loads((output/'status.json').read_text())
    assert status['state'] == 'complete'
    assert status['archive_sha256'] == digest(output/'result.tar.gz')
    result = import_result(output/'result.tar.gz',destination,expected_input_manifest=digest(scratch/'inputs.json'))
    assert result['segments'][0]['name'] == 'run'
    assert (destination/'package/run.conf').read_text() == 'unchanged native input bytes\n'
    request.write_bytes(b'changed request')
    with pytest.raises(ValueError,match='input hash mismatch'):
        worker.main()
    assert json.loads((output/'status.json').read_text())['state'] == 'failed'
