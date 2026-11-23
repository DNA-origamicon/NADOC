"""Recover durable preparation allocations without submitting duplicate work."""
from __future__ import annotations

import asyncio
import logging
import json
from types import SimpleNamespace
from pathlib import Path
import time

from backend.core.md_preparation_remote import read_state, state_path
from backend.core.alpine_transfer_state import atomic_json
from backend.core.md_preparation_ownership import preparation_owned, recover_owned

log = logging.getLogger(__name__)
_TASKS = set()


def owns_preparation(job, workspace):
    if preparation_owned(job, workspace):
        return True
    state = read_state(job.job_dir(workspace))
    return state.get('phase') in ('staging', 'provisioning', 'running', 'fetching', 'cancel_pending', 'complete') and bool(state.get('archive'))


async def cancel_preparation(job, workspace):
    """Cancel only the allocation recorded by preparation, never a NAMD allocation."""
    from backend.core import cluster_ssh
    from backend.core.md_job import MdStatus, finish_runpod_billing
    state = read_state(job.job_dir(workspace))
    if not state or state.get('phase') in ('failed', 'cancelled', 'complete'):
        return None
    job.user_stopped = True
    job.status = MdStatus.stopped
    job.save(workspace)
    state['phase'] = 'cancel_pending'
    atomic_json(state_path(job.job_dir(workspace)), state)
    if state['target'] == 'alpine':
        conn = cluster_ssh.get_manager()
        if not conn.is_connected():
            return {'ok': True, 'status': 'stopped', 'pending_scancel': True}
        allocation = state.get('slurm_job_id')
        if allocation:
            if not str(allocation).isdigit():
                raise ValueError('Invalid preparation allocation')
            result = await conn.run(f'scancel {allocation}')
            if result.rc:
                raise RuntimeError(result.stderr or 'Preparation cancellation failed')
        else:
            # A submit may still be in flight. The owning task checks user_stopped
            # immediately after it obtains the durable allocation receipt.
            return {'ok': True, 'status': 'stopped', 'pending_scancel': True}
    else:
        from backend.api.routes_runpod import _SESSION
        if not _SESSION.is_connected():
            return {'ok': True, 'status': 'stopped', 'warning': 'Reconnect RunPod to confirm preparation cancellation; the lifetime watchdog remains active.'}
        if state.get('pod_id'):
            await _SESSION.require().terminate_pod(state['pod_id'], reason='preparation_cancelled')
            finish_runpod_billing(job, state['pod_id'])
            job.runpod_pod_id = None
            job.save(workspace)
        else:
            return {'ok': True, 'status': 'stopped', 'pending_cancel': True}
    state['phase'] = 'cancelled'
    atomic_json(state_path(job.job_dir(workspace)), state)
    return {'ok': True, 'status': 'stopped'}


async def _recover(job, workspace, state):
    from backend.api.routes_md import _complete_prepared_job, _write_prep_heartbeat
    from backend.api.md_request_models import CreateJobRequest
    from backend.core.md_job import MdJob, MdStatus
    from backend.core.md_prep_progress import PrepTracker, build_prep_phases, clear_prep_progress
    from backend.core.md_preparation_remote import prepare_alpine
    from backend.core.md_preparation_bundle import digest
    from backend.core.namd_input_provenance import capture
    tracker = PrepTracker(build_prep_phases(seeded=False), clock=time.monotonic)
    directory = job.job_dir(workspace)
    heartbeat = asyncio.create_task(_write_prep_heartbeat(directory, tracker))
    try:
        archive = Path(state['archive'])
        if not archive.is_relative_to(directory / '.preparation') or await asyncio.to_thread(digest, archive) != state['archive_sha256']:
            raise ValueError('Frozen preparation bundle is missing or changed')
        if state['phase'] == 'complete':
            record = json.loads((directory / '.preparation/result.json').read_text())
            for relative, expected in record['files'].items():
                path = (directory / relative).resolve()
                if not path.is_relative_to(directory.resolve()) or await asyncio.to_thread(digest, path) != expected:
                    raise ValueError('Prepared package changed before recovery')
            result = record['package_subdir'], record['name_stem'], [SimpleNamespace(**s) for s in record['segments']]
        else:
            result = await prepare_alpine(job, workspace, state['plan'], archive, state['archive_sha256'], tracker.report)
        receipt = MdJob.load(job.job_id, workspace)
        receipt.package_subdir = result[0]
        await asyncio.to_thread(capture, receipt, workspace)
        await _complete_prepared_job(job.job_id, CreateJobRequest.model_validate(job.prep_params), result, workspace)
    except Exception as exc:
        from backend.core.md_preparation_remote import RemotePreparationDetached
        if isinstance(exc, RemotePreparationDetached):
            return
        current = MdJob.load(job.job_id, workspace)
        current.status = MdStatus.stopped if current.user_stopped else MdStatus.failed
        current.error = str(exc)
        current.save(workspace)
        log.exception('Preparation recovery failed for %s', job.job_id)
    finally:
        heartbeat.cancel()
        clear_prep_progress(directory)


async def resume_preparations(workspace):
    from backend.core import cluster_ssh
    from backend.core.md_job import MdJob, MdStatus
    from backend.core.md_prep_progress import is_active_preparation, register_active_preparation, unregister_active_preparation
    for job in await asyncio.to_thread(MdJob.list_jobs, workspace):
        if is_active_preparation(job.job_id) or preparation_owned(job, workspace):
            continue
        state = read_state(job.job_dir(workspace))
        if state.get('phase') == 'cancel_pending':
            await cancel_preparation(job, workspace)
            continue
        if job.status != MdStatus.preparing or not owns_preparation(job, workspace):
            continue
        if state['target'] == 'runpod' and state['phase'] != 'complete':
            # The independent watchdog terminates a preparation pod after owner loss.
            # Confirm cleanup before exposing a retry; never silently rent twice.
            result = await cancel_preparation(job, workspace)
            if result and not result.get('warning') and not result.get('pending_cancel'):
                job = MdJob.load(job.job_id, workspace)
                job.status = MdStatus.failed
                job.error = 'RunPod preparation was interrupted; its allocation has been released. Retry preparation.'
                job.save(workspace)
            continue
        if state['phase'] != 'complete' and not cluster_ssh.get_manager().is_connected():
            continue
        register_active_preparation(job.job_id)
        task = asyncio.create_task(recover_owned(_recover, job, workspace, state))
        _TASKS.add(task)
        def done(task, job_id=job.job_id):
            _TASKS.discard(task)
            unregister_active_preparation(job_id)
        task.add_done_callback(done)
