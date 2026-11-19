"""Budgeted RunPod execution of the shared solver bundle; no automatic retries."""
import asyncio
import os
from pathlib import Path
import shlex
import tempfile
import threading
import math
import time

from backend.core import solver_cluster as shared
from backend.core.solver_cluster_config import SolverRunpodSettings

_ACTIVE = set()
_LOCK = threading.Lock()


def validate_request(engine, settings):
    from backend.api.routes_runpod import _SESSION
    from backend.core.runpod_api import resolve_api_key
    config = SolverRunpodSettings.model_validate(settings)
    if not _SESSION.is_connected() or not _SESSION.network_volume_id:
        raise ValueError("Connect RunPod and select a network volume in the Clusters card")
    # The independent watchdog must be able to authenticate after this process exits.
    if resolve_api_key(env={}).value != _SESSION.api_key:
        raise ValueError("Save the RunPod API key in ~/.runpod_key so the independent budget watchdog can authenticate outside the API process")
    if engine == 'mrdna' and (not config.arbd or Path(config.arbd).name != 'arbd'):
        raise ValueError("Set the installed ARBD path on the network volume; its filename must be arbd")
    return config


def start(job, workspace, engine):
    config = validate_request(engine, job.remote['settings'])
    key = (str(workspace), engine, job.job_id)
    with _LOCK:
        if key in _ACTIVE:
            return
        if job.remote.get('pod_id') or job.remote.get('provisioning'):
            raise ValueError("This job already owns a RunPod attempt. Check its status before creating another job.")
        _ACTIVE.add(key)
    job.status = type(job.status)('preparing')
    job.error = None
    job.remote.pop('last_error', None)
    job.remote['provisioning'] = True
    job.save(workspace)
    from backend.api.routes_runpod import _SESSION
    api_key, volume = _SESSION.api_key, _SESSION.network_volume_id
    def work():
        try:
            asyncio.run(run(engine, job.job_id, workspace, config, api_key, volume))
        finally:
            with _LOCK: _ACTIVE.discard(key)
    threading.Thread(target=work, daemon=True, name=f'{engine}-runpod-{job.job_id}').start()


async def run(engine, job_id, workspace, config, api_key, volume):
    from backend.core.runpod_api import RunpodClient, build_create_payload, termination_deadline
    from backend.core.runpod_conn import RunpodConnection
    from backend.core.runpod_identity import pod_name
    from backend.core.runpod_oxdna import CampaignLedger, budgeted_lifetime_s
    from backend.core.solver_runpod_stock import fetch_solver_stock
    from backend.core.runpod_watchdog import start_watchdog_service
    cls = shared.job_class(engine)
    job = cls.load(job_id, workspace)
    jd = job.job_dir(workspace)
    client = RunpodClient(api_key, audit_dir=jd)
    ledger = CampaignLedger(jd / 'runpod_spend.json', cap_usd=config.budget_usd)
    pod_id = None
    destroyed = False
    try:
        stock = (await fetch_solver_stock(api_key, volume, config.mem_gb, config.cores)).get(config.gpu_id, {})
        rate = float(stock.get('on_demand') or 0)
        if rate <= 0 or rate > config.quoted_rate or stock.get('stock', 'None').lower() == 'none':
            raise ValueError('RunPod has no matching capacity at the selected volume location, or its price changed. Refresh resources and choose another GPU; no pod was rented.')
        if engine == 'mrdna':
            from backend.core.mrdna_runner import _load_snapshot_design
            from backend.core.solver_resources import estimate_resources, check_snapshot_capacity
            check_snapshot_capacity(jd)
            design = _load_snapshot_design(jd)
            if design is None:
                raise ValueError('Missing solver snapshot; cannot verify GPU memory')
            need = estimate_resources(engine, design, job)
            del design  # Do not retain the local molecular snapshot for the remote job's lifetime.
            if need.gpu > float(stock.get('vram_gb') or 0) * 1e9 * .85:
                raise ValueError('Selected RunPod GPU has insufficient or unknown VRAM; choose a larger GPU')
        lifetime = budgeted_lifetime_s(ledger, rate, config.walltime_minutes * 60)
        # Leave one minute of billing headroom for shutdown/watchdog polling.
        if lifetime <= 360:
            raise ValueError('Budget needs at least six pod-minutes including shutdown headroom')
        deadline = termination_deadline(lifetime - 60)
        payload = build_create_payload(name=pod_name(engine, job_id), gpu_type_ids=[config.gpu_id],
            network_volume_id=volume, cloud_type='SECURE', terminate_after=deadline)
        payload['minMemoryInGb'] = math.ceil(config.mem_gb * 1024**3 / 1e9)
        payload['minVcpuCount'] = config.cores
        def created(info):
            nonlocal pod_id
            pod_id = info.id
            actual_rate = float(info.cost_per_hr or rate)
            ledger.open_pod(info.id, actual_rate, note=f'{engine} {job_id}')
            live = cls.load(job_id, workspace)
            live.remote.update(pod_id=info.id, rate_usd_per_hour=actual_rate, deadline=deadline,
                               volume_id=volume, scheduler_state='BOOTING', provisioning=False)
            live.save(workspace)
            start_watchdog_service(pod_id=info.id, owner_pid=os.getpid(), deadline=deadline,
                audit_dir=jd / 'watchdog', campaign_ledger=ledger.path, campaign_cap_usd=config.budget_usd)
            if actual_rate > config.quoted_rate:
                raise ValueError('Provider rate exceeds accepted quote')
        async with client.pod(payload, on_created=created, terminate_on_exit=True) as pod:
            key = Path.home() / '.ssh' / 'id_ed25519'
            conn = RunpodConnection(host=pod.public_ip, port=pod.ssh_port, pod_id=pod.id,
                                    client_keys=[str(key)] if key.is_file() else None)
            try:
                await conn.connect()
                from backend.core.solver_runpod_environment import ensure_environment
                job = cls.load(job_id, workspace)
                job.remote['scheduler_state'] = 'SETTING_UP_ENVIRONMENT'
                job.save(workspace)
                await ensure_environment(conn, engine, config)
                await shared.preflight(conn, engine, config)
                job = cls.load(job_id, workspace)
                remote = f'/workspace/nadoc-solvers/{engine}/{job_id}'
                job.remote.update(directory=remote, scheduler_state='STAGING')
                job.save(workspace)
                await conn.mkdir_p(remote)
                with tempfile.TemporaryDirectory(prefix='nadoc-runpod-solver-') as tmp:
                    archive = Path(tmp) / 'inputs.tar.gz'
                    shared.bundle_inputs(archive, engine, job, workspace)
                    await conn.sftp_put(str(archive), remote + '/inputs.tar.gz')
                    launch = Path(tmp) / 'run.sh'
                    q = shlex.quote
                    command = f'{q(config.python)} -m backend.core.solver_cluster_worker {engine} {q(remote + "/workspace")} {q(job_id)}'
                    launch.write_text('\n'.join(['#!/bin/bash', 'set -uo pipefail', f'cd {q(remote)}',
                        f'export OPENBLAS_NUM_THREADS={config.cores} OMP_NUM_THREADS={config.cores}',
                        f'export NADOC_HYDRO_MEM_GB={config.mem_gb * 1024**3 / 1e9 * .8}',
                        f'export PATH={q(str(Path(config.arbd).parent))}:$PATH' if config.arbd else ':',
                        'echo RUNNING > solver.status', command + ' > slurm.out 2>&1',
                        'rc=$?', 'echo "$rc" > solver.exit', 'echo FINISHED > solver.status', 'exit "$rc"', '']))
                    await conn.sftp_put(str(launch), remote + '/run.sh')
                extracted = await conn.run(f'cd {shlex.quote(remote)} && tar --no-same-owner -xzf inputs.tar.gz', timeout=120)
                if extracted.rc: raise RuntimeError((extracted.stderr or 'Remote input extraction failed')[-3000:])
                pid = await conn.launch_detached('run.sh', remote)
                job.status = type(job.status)('running'); job.remote['scheduler_state'] = 'RUNNING'; job.save(workspace)
                while True:
                    if cls.load(job_id, workspace).remote.get('cancel_requested'):
                        raise RuntimeError('RunPod cancellation requested')
                    from backend.core.solver_progress import sync_remote_progress
                    await sync_remote_progress(engine, cls.load(job_id, workspace), workspace, conn)
                    status = (await conn.read_file(remote + '/solver.status')).strip()
                    if status == 'FINISHED': break
                    if not await conn.pid_alive(pid):
                        # Re-read after the PID check: the process may have completed
                        # between observing RUNNING and probing liveness.
                        if (await conn.read_file(remote + '/solver.status')).strip() == 'FINISHED':
                            break
                        raise RuntimeError('Remote solver process exited without a completion receipt; outputs remain on the network volume')
                    await asyncio.sleep(5)
                code = (await conn.read_file(remote + '/solver.exit')).strip()
                await shared.collect(engine, cls.load(job_id, workspace), workspace, conn,
                                     'COMPLETED' if code == '0' else 'FAILED', '0:0' if code == '0' else code)
            finally:
                await conn.close()
    except Exception as exc:
        job = cls.load(job_id, workspace)
        job.status = type(job.status)('stopped' if job.remote.get('cancel_requested') else 'failed')
        job.error = ('RunPod capacity changed before rental. Refresh resources and choose an available GPU '
                     'at your network volume location; no pod was rented.'
                     if not pod_id and 'SUPPLY_CONSTRAINT' in str(exc) else str(exc))
        job.remote['last_error'] = job.error
        job.save(workspace)
    finally:
        if pod_id:
            try:
                await client.terminate_pod(pod_id)
                destroyed = True
            except Exception as exc:
                job = cls.load(job_id, workspace)
                job.remote['last_error'] = f'Pod termination not confirmed: {exc}. Independent watchdog remains responsible.'
                job.save(workspace)
            if destroyed: ledger.close_pod(pod_id)
        job = cls.load(job_id, workspace)
        job.remote.update(provisioning=False, downloading=False, pod_destroyed=destroyed,
                          spent_usd=ledger.spent_usd())
        job.save(workspace)
        await client.aclose()


def reconcile(job, workspace, engine):
    key = (str(workspace), engine, job.job_id)
    with _LOCK: active = key in _ACTIVE
    if not active and job.status.value in {'preparing', 'queued', 'running'}:
        job.status = type(job.status)('failed')
        job.error = 'RunPod controller interrupted. Check pod termination in Clusters; outputs remain on the selected network volume. No automatic resubmission.'
        job.save(workspace)
    if not active and job.remote.get('pod_id') and not job.remote.get('pod_destroyed'):
        if time.monotonic() - shared._LAST.get(key, 0) > 30:
            shared._background(engine, job.job_id, workspace, check_terminated)
    return job


async def cancel(job, workspace):
    from backend.api.routes_runpod import _SESSION
    if not job.remote.get('pod_id'):
        raise ValueError('Wait for the RunPod creation receipt before cancelling')
    job.remote['cancel_requested'] = True
    job.save(workspace)
    await _SESSION.require().terminate_pod(job.remote['pod_id'])
    job.remote['pod_destroyed'] = True
    job.status = type(job.status)('stopped')
    job.save(workspace)
    return {'ok': True, 'status': 'stopped'}


async def check_terminated(engine, job_id, workspace, _conn):
    """Reconcile a watchdog-destroyed pod after a controller/API restart."""
    from backend.core.runpod_api import RunpodClient, resolve_api_key
    from backend.core.runpod_oxdna import CampaignLedger
    key = resolve_api_key().value
    if not key:
        return
    cls = shared.job_class(engine)
    job = cls.load(job_id, workspace)
    client = RunpodClient(key)
    try:
        pods = await client.list_pods()
        pod = next((p for p in pods if p.id == job.remote.get('pod_id')), None)
        if pod is None or pod.is_destroyed:
            job.remote['pod_destroyed'] = True
            job.remote['provisioning'] = False
            job.remote['last_error'] = None
            job.save(workspace)
            ledger = CampaignLedger(job.job_dir(workspace) / 'runpod_spend.json',
                                    cap_usd=job.remote['settings']['budget_usd'])
            # Exact stop time was not observed; retain an upper-bound accounting receipt.
            ledger.close_pod(job.remote['pod_id'])
    finally:
        await client.aclose()
