"""Scheduler-specific preparation allocations; no molecular policy lives here."""
from __future__ import annotations

import asyncio
import json
import hashlib
import tarfile
from pathlib import Path
import shlex
import time
from types import SimpleNamespace

from backend.core.alpine_transfer_state import atomic_json
from backend.core.md_preparation_bundle import bootstrap_command, digest, import_result


class RemotePreparationDetached(RuntimeError):
    """Durable remote work is awaiting reconnection, not a failed build."""


def state_path(job_dir):
    return Path(job_dir) / '.preparation' / 'remote.json'


def read_state(job_dir):
    try:
        return json.loads(state_path(job_dir).read_text())
    except FileNotFoundError:
        return {}


async def _put_text(conn, local_dir, remote, text):
    path = Path(local_dir) / 'upload.txt'
    path.write_text(text)
    try:
        await conn.sftp_put(str(path), remote)
    finally:
        path.unlink(missing_ok=True)


def alpine_script(remote, plan):
    return ('#!/bin/bash\n'
            f'#SBATCH --job-name=nadoc-prepare\n#SBATCH --partition={plan["partition"]}\n'
            f'#SBATCH --qos={plan["qos"]}\n#SBATCH --nodes=1\n#SBATCH --ntasks=1\n'
            f'#SBATCH --cpus-per-task={plan["cores"]}\n#SBATCH --mem={plan["mem_gb"]}G\n'
            f'#SBATCH --time={plan["walltime"]}\n#SBATCH --output=prepare-%j.log\n'
            f'cd {shlex.quote(remote)}\n' + bootstrap_command(max(30, plan['mem_gb'] * 2)))


async def _stage(conn, remote, archive, archive_digest, local_dir):
    await conn.mkdir_p(remote)
    await conn.sftp_put(str(archive), f'{remote}/bundle.tar.gz')
    check = f'{archive_digest}  bundle.tar.gz\n'
    result = await conn.run(f'cd {shlex.quote(remote)} && printf %s {shlex.quote(check)} | sha256sum -c -', timeout=180)
    if result.rc:
        raise RuntimeError(f'Preparation staging failed: {result.stderr or result.stdout}')


async def _collect(conn, remote, job_dir, status):
    archive = Path(job_dir) / '.preparation' / 'result.tar.gz'
    try:
        await conn.sftp_get(f'{remote}/result.tar.gz', str(archive))
        if await asyncio.to_thread(digest, archive) != status['archive_sha256']:
            raise ValueError('Transferred preparation archive hash mismatch')
        def verified_import():
            state = read_state(job_dir)
            with tarfile.open(state['archive']) as frozen:
                expected = hashlib.sha256(frozen.extractfile('inputs.json').read()).hexdigest()
            return import_result(archive, job_dir, expected_input_manifest=expected)
        result = await asyncio.to_thread(verified_import)
        atomic_json(Path(job_dir) / '.preparation' / 'result.json', result)
        return result['package_subdir'], result['name_stem'], [SimpleNamespace(**s) for s in result['segments']]
    finally:
        archive.unlink(missing_ok=True)


async def _poll(conn, remote, job, workspace, report, *, alive=None, deadline=None):
    from backend.core.md_job import MdJob
    terminal_checks = 0
    while True:
        if MdJob.load(job.job_id, workspace).user_stopped:
            raise RuntimeError('Preparation stopped by user')
        result = await conn.run(f'cd {shlex.quote(remote)} && cat status.json 2>/dev/null; echo; cat progress.json 2>/dev/null')
        # Both files are atomically replaced single-line JSON; never parse half a write.
        records = []
        for line in result.stdout.splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
        status = next((r for r in records if r.get('state')), {})
        if status.get('state') == 'failed':
            log = await conn.run(f'cd {shlex.quote(remote)} && tail -25 prepare-*.log nadoc_chain.out 2>/dev/null')
            raise RuntimeError(status.get('error', 'Remote preparation failed') + '\n' + log.stdout[-4000:])
        if status.get('state') == 'complete':
            return status
        progress = next((r for r in records if r.get('phase')), {})
        if progress:
            report(progress['phase'], progress.get('fraction'), progress.get('message'))
        if alive and not await alive():
            terminal_checks += 1
            if terminal_checks < 3:
                await asyncio.sleep(5)
                continue  # Allow shared-filesystem completion records to become visible.
            log = await conn.run(f'cd {shlex.quote(remote)} && tail -30 prepare-*.log nadoc_chain.out 2>/dev/null')
            raise RuntimeError(f'Remote preparation allocation ended before completion: {log.stdout[-5000:]}')
        if deadline and time.time() >= deadline:
            raise RuntimeError('Preparation reached its allocated lifetime')
        await asyncio.sleep(5)


async def prepare_alpine(job, workspace, plan, archive, archive_digest, report):
    from backend.core.cluster_ssh import ClusterSSHError
    try:
        return await _prepare_alpine(job, workspace, plan, archive, archive_digest, report)
    except (ClusterSSHError, TimeoutError, ConnectionError) as exc:
        raise RemotePreparationDetached('Alpine preparation is waiting for reconnection') from exc


async def _prepare_alpine(job, workspace, plan, archive, archive_digest, report):
    from backend.core import cluster_config, cluster_ssh
    from backend.core.md_executor import parse_sbatch_job_id
    conn = cluster_ssh.get_manager()
    if not conn.is_connected():
        if read_state(job.job_dir(workspace)).get('slurm_job_id'):
            raise RemotePreparationDetached('Alpine preparation is waiting for reconnection')
        raise RuntimeError('Connect to Alpine to prepare this job remotely')
    profile = cluster_config.load_profiles(workspace)[job.cluster_name or 'alpine']
    remote = cluster_config.resolve_paths(profile, conn.user, job.job_id + '-prepare')['scratch_dir']
    remote += '/' + archive_digest[:16]
    local_dir = archive.parent
    state = read_state(job.job_dir(workspace))
    if state.get('archive_sha256') != archive_digest or state.get('phase') in ('failed', 'cancelled'):
        import uuid
        remote += '-' + uuid.uuid4().hex[:8]
        state = dict(target='alpine', remote=remote, archive_sha256=archive_digest, phase='staging', plan=plan, archive=str(archive))
        atomic_json(state_path(job.job_dir(workspace)), state)
        report('topology', 0, 'Sending preparation inputs to Alpine…')
        await _stage(conn, remote, archive, archive_digest, local_dir)
        await _put_text(conn, local_dir, f'{remote}/prepare.sbatch', alpine_script(remote, plan))
        # A receipt on scratch closes the lost-submit-response window on reconnect.
        result = await conn.run(f'cd {shlex.quote(remote)} && sbatch --parsable prepare.sbatch | tee allocation.txt')
        slurm_id = result.stdout.strip().split(';')[0]
        if result.rc or not slurm_id.isdigit():
            slurm_id = parse_sbatch_job_id(result.stdout)
        if not slurm_id:
            raise RuntimeError(f'Alpine preparation submission failed: {result.stderr or result.stdout}')
        state.update(slurm_job_id=slurm_id, phase='running')
        atomic_json(state_path(job.job_dir(workspace)), state)
    else:
        remote = state['remote']
        if not state.get('slurm_job_id'):
            result = await conn.run(f'cat {shlex.quote(remote + "/allocation.txt")}')
            value = result.stdout.strip().split(';')[0]
            if result.rc or not value.isdigit():
                raise RuntimeError('Preparation submission was interrupted; no allocation receipt is available')
            state.update(slurm_job_id=value, phase='running')
            atomic_json(state_path(job.job_dir(workspace)), state)
    if not str(state['slurm_job_id']).isdigit():
        raise ValueError('Invalid preparation allocation identifier')
    async def alive():
        result = await conn.run(f'sacct -j {state["slurm_job_id"]} --format=State -n -P')
        states = result.stdout.splitlines()
        return not states or any(x in ('PENDING', 'RUNNING', 'CONFIGURING', 'COMPLETING') for x in states)
    try:
        report('topology', 0, f'Preparing on Alpine ({plan["mem_gb"]} GiB RAM); waiting for compute allocation…')
        status = await _poll(conn, remote, job, workspace, report, alive=alive)
        state['phase'] = 'fetching'
        atomic_json(state_path(job.job_dir(workspace)), state)
        report('finalize', None, 'Downloading and verifying the prepared package…')
        result = await _collect(conn, remote, job.job_dir(workspace), status)
        state['phase'] = 'complete'
        atomic_json(state_path(job.job_dir(workspace)), state)
        return result
    except asyncio.CancelledError:
        # Keep durable Slurm work for the next server to adopt.
        raise
    except (cluster_ssh.ClusterSSHError, TimeoutError, ConnectionError):
        raise
    except Exception:
        await conn.run(f'scancel {state["slurm_job_id"]}')
        state['phase'] = 'failed'
        atomic_json(state_path(job.job_dir(workspace)), state)
        raise


async def prepare_runpod(job, workspace, plan, archive, archive_digest, report):
    from backend.api import routes_runpod
    from backend.api.routes_md import _runpod_client_keys
    from backend.core.runpod_api import build_create_payload, termination_deadline, ssh_endpoint
    from backend.core.runpod_conn import RunpodConnection
    from backend.core.runpod_identity import installation_id, pod_name
    from backend.core.runpod_script import GPU_TYPES, DEFAULT_BUDGET_USD, DEFAULT_MAX_USD_PER_HOUR, lifetime_for_budget
    from backend.core.md_job import MdJob, start_runpod_billing, finish_runpod_billing
    from backend.core.runpod_watchdog import start_watchdog_service
    import os
    client = routes_runpod._SESSION.require()
    budget = DEFAULT_BUDGET_USD if job.runpod_budget_usd is None else float(job.runpod_budget_usd)
    if budget <= 0:
        raise ValueError("RunPod preparation budget must be positive")
    if not _runpod_client_keys():
        raise RuntimeError("RunPod SSH credentials are unavailable")
    candidates = sorted((gpu for gpu in GPU_TYPES if gpu.usd_per_hour <= DEFAULT_MAX_USD_PER_HOUR), key=lambda gpu: gpu.usd_per_hour)
    payloads = []
    for gpu in candidates:
        seconds = min(7200, lifetime_for_budget(budget, max(DEFAULT_MAX_USD_PER_HOUR, gpu.usd_per_hour)))
        payload = build_create_payload(name=pod_name(job.design_name + '-prepare', job.job_id),
                    gpu_type_ids=[gpu.key], network_volume_id=None, cloud_type='SECURE',
                    container_disk_gb=max(30, int(plan['mem_gb'] * 2)),
                    terminate_after=termination_deadline(seconds))
        payload.update(minMemoryInGb=plan['mem_gb'], minVcpuCount=plan['cores'])
        payloads.append(payload)
    pod = None
    conn = None
    remote = '/workspace/nadoc-preparation/' + job.job_id
    state = dict(target='runpod', remote=remote, archive_sha256=archive_digest, phase='provisioning', plan=plan, archive=str(archive))
    atomic_json(state_path(job.job_dir(workspace)), state)
    try:
        report('topology', 0, 'Allocating preparation memory on RunPod…')
        pod = await client.create_pod_first_available(payloads)
        job = MdJob.load(job.job_id, workspace)
        job.runpod_pod_id = pod.id
        job.runpod_owner_id = installation_id()
        job.runpod_terminate_after = min(p['terminateAfter'] for p in payloads)
        start_runpod_billing(job, pod.id, pod.cost_per_hr)
        job.save(workspace)
        state.update(pod_id=pod.id, phase='running')
        atomic_json(state_path(job.job_dir(workspace)), state)
        await asyncio.to_thread(start_watchdog_service, pod_id=pod.id, owner_pid=os.getpid(),
                  deadline=job.runpod_terminate_after, audit_dir=workspace,
                  campaign_ledger=None, campaign_cap_usd=budget)
        if job.user_stopped:
            raise RuntimeError("Preparation stopped by user")
        report('topology', 0, 'RunPod capacity reserved; waiting for worker startup…')
        pod = await client.wait_for_ssh(pod.id)
        host, port = ssh_endpoint(pod)
        conn = RunpodConnection(host=host, port=port, pod_id=pod.id, client_keys=_runpod_client_keys())
        await conn.connect()
        report('topology', 0, 'Sending preparation inputs to RunPod…')
        await _stage(conn, remote, archive, archive_digest, archive.parent)
        await _put_text(conn, archive.parent, f'{remote}/prepare.sh', '#!/bin/bash\n' + bootstrap_command(max(30, plan['mem_gb'] * 2)))
        pid = await conn.launch_detached(f'{remote}/prepare.sh', remote)
        state['pid'] = pid
        atomic_json(state_path(job.job_dir(workspace)), state)
        status = await _poll(conn, remote, job, workspace, report,
                             alive=lambda: conn.pid_alive(pid), deadline=time.time()+7200)
        report('finalize', None, 'Downloading and verifying the prepared package…')
        result = await _collect(conn, remote, job.job_dir(workspace), status)
        state['phase'] = 'complete'
        atomic_json(state_path(job.job_dir(workspace)), state)
        return result
    except BaseException:
        state['phase'] = 'cancel_pending' if pod else 'failed'
        atomic_json(state_path(job.job_dir(workspace)), state)
        raise
    finally:
        if conn:
            try:
                await conn.close()
            except Exception:
                pass  # Connection cleanup must never skip paid allocation cleanup.
        if pod:
            try:
                await client.terminate_pod(pod.id, reason='preparation_finished_or_interrupted')
            except Exception:
                state['phase'] = 'cancel_pending'
                atomic_json(state_path(job.job_dir(workspace)), state)
                raise
            current = MdJob.load(job.job_id, workspace)
            finish_runpod_billing(current, pod.id)
            current.runpod_pod_id = None
            current.save(workspace)
            if state['phase'] == 'cancel_pending':
                state['phase'] = 'failed'
                atomic_json(state_path(job.job_dir(workspace)), state)
