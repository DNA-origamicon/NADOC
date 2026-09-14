"""Detached transfer lifetime and recovery, using a local fake Alpine transport."""
import asyncio

import pytest

from backend.core.alpine_worker import Worker, WorkerClient
from backend.core.alpine_transfer_state import atomic_json, state_path, recover_downloads
from backend.core.md_job import MdJob, MdStatus, new_job
from backend.core import md_executor


def make_job(workspace):
    job = new_job(design_name='worker', protocol='test', name_stem='worker', package_subdir='namd')
    job.execution_target = 'alpine'
    job.remote_scratch_dir = '/scratch/job'
    job.status = MdStatus.stopped
    job.save(workspace)
    return job


class FakeConnection:
    def status(self):
        return {'state': 'connected', 'host': 'fake', 'who': 'user@fake',
                'last_error': None, 'error_kind': None}

    def is_connected(self):
        return True


async def serve(directory, connection):
    worker = Worker(directory, connection)
    task = asyncio.create_task(worker.serve())
    for _ in range(100):
        if (directory / 'worker.sock').exists():
            return worker, task
        await asyncio.sleep(.01)
    raise AssertionError('worker failed to listen')


def test_download_outlives_client_and_new_client_reattaches(tmp_path, monkeypatch):
    async def scenario():
        ws = tmp_path / 'workspace'
        job = make_job(ws)
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []

        async def fetch(job, workspace, *, conn):
            calls.append(job.job_id)
            job.download_status = {'state': 'downloading', 'transferred_bytes': 12}
            job.save(workspace)
            started.set()
            await finish.wait()
            output = job.package_dir(workspace) / 'output' / 'result.log'
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b'finished')
            job.download_status = {'state': 'verified', 'verified_bytes': 8}
            job.save(workspace)
            return True

        monkeypatch.setattr(md_executor, '_fetch_outputs_locked', fetch)
        directory = tmp_path / 'worker'
        worker, server = await serve(directory, FakeConnection())
        try:
            first = asyncio.create_task(WorkerClient(directory).fetch_outputs(job, ws))
            await started.wait()
            first.cancel()  # the API connection vanishes, as on uvicorn death
            with pytest.raises(asyncio.CancelledError):
                await first
            assert not next(iter(worker.transfers.values())).done()
            stale = MdJob.load(job.job_id, ws)
            stale.error = 'user edit during transfer'
            stale.save(ws)
            second = asyncio.create_task(WorkerClient(directory).fetch_outputs(stale, ws))
            await asyncio.sleep(.02)
            finish.set()
            assert await second
            assert calls == [job.job_id]
            loaded = MdJob.load(job.job_id, ws)
            assert loaded.download_status['state'] == 'verified'
            assert loaded.error == 'user edit during transfer'
            assert (loaded.package_dir(ws) / 'output/result.log').read_bytes() == b'finished'
        finally:
            server.cancel()
            await asyncio.gather(server, return_exceptions=True)
    asyncio.run(scenario())


def test_worker_progress_survives_stale_job_save(tmp_path):
    job = make_job(tmp_path)
    atomic_json(state_path(job, tmp_path), {
        'id': 'one', 'done': True,
        'download_status': {'state': 'verified', 'verified_bytes': 123, 'worker_transfer_id': 'one'},
    })
    job.save(tmp_path)
    loaded = MdJob.load(job.job_id, tmp_path)
    assert loaded.download_status['verified_bytes'] == 123
    loaded.download_status.update(state='processing')
    loaded.save(tmp_path)
    assert MdJob.load(job.job_id, tmp_path).download_status['state'] == 'processing'


def test_stopped_snapshot_recovers_without_slurm_handle(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    job.restart_snapshot = True
    job.save(tmp_path)
    atomic_json(state_path(job, tmp_path), {
        'id': 'one', 'done': False, 'download_status': {'state': 'downloading'},
    })
    seen = []
    async def fetch(job, workspace, *, conn):
        seen.append(job.job_id)
    monkeypatch.setattr(md_executor, 'fetch_outputs', fetch)
    asyncio.run(recover_downloads(tmp_path, FakeConnection()))
    assert seen == [job.job_id]


def test_verified_worker_result_finalizes_offline_only_once(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    job.slurm_state = 'COMPLETED'
    job.save(tmp_path)
    atomic_json(state_path(job, tmp_path), {
        'id': 'one', 'done': True,
        'download_status': {'state': 'verified', 'worker_transfer_id': 'one'},
    })
    seen = []
    monkeypatch.setattr(md_executor, '_finalize_local_bookkeeping', lambda j, w: seen.append(j.job_id))
    monkeypatch.setattr(md_executor, '_record_learned_throughput', lambda *args: None)
    assert asyncio.run(md_executor.resume_local_processing_jobs(tmp_path)) == [job.job_id]
    assert asyncio.run(md_executor.resume_local_processing_jobs(tmp_path)) == []
    assert seen == [job.job_id]


def test_dead_worker_status_expires(tmp_path):
    atomic_json(tmp_path / 'status.json', {'state': 'connected', 'heartbeat': 1})
    assert not WorkerClient(tmp_path).is_connected()


def test_cancelled_waiter_does_not_unlock_other_process_transfer(tmp_path, monkeypatch):
    import fcntl
    async def scenario():
        job = make_job(tmp_path)
        lockfile = (job.job_dir(tmp_path) / '.download.lock').open('a+b')
        fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            task = asyncio.create_task(md_executor.fetch_outputs(job, tmp_path, conn=FakeConnection()))
            await asyncio.sleep(.02)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with (job.job_dir(tmp_path) / '.download.lock').open('a+b') as other:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            lockfile.close()
    asyncio.run(scenario())


def test_transfer_keeps_running_after_api_process_is_killed(tmp_path):
    """Real OS-process boundary, without touching the running app or Alpine."""
    import subprocess
    import sys
    import time
    from backend.core.alpine_worker import ROOT

    ws = tmp_path / 'workspace'
    job = make_job(ws)
    directory = tmp_path / 'w'
    script = tmp_path / 'worker_fixture.py'
    script.write_text('''
import asyncio, sys
from pathlib import Path
from backend.core.alpine_worker import Worker
from backend.core import md_executor
class Conn:
    def status(self): return {'state': 'connected', 'host': 'fake', 'who': 'user@fake'}
    def is_connected(self): return True
async def fetch(job, workspace, *, conn):
    job.download_status = {'state': 'downloading'}
    job.save(workspace)
    (workspace / 'started').touch()
    await asyncio.sleep(.7)
    (workspace / 'bytes-finished').write_bytes(b'complete result')
    job.download_status = {'state': 'verified'}
    job.save(workspace)
    return True
md_executor._fetch_outputs_locked = fetch
asyncio.run(Worker(Path(sys.argv[1]), Conn()).serve())
''')
    import os
    env = {**os.environ, 'PYTHONPATH': str(ROOT)}
    worker = subprocess.Popen([sys.executable, str(script), str(directory)], env=env,
                              start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    client = None
    def until(check):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if check():
                return
            time.sleep(.02)
        raise AssertionError('Timed out waiting for subprocess fixture')
    try:
        until(lambda: (directory / 'worker.sock').exists())
        client_code = '''
import asyncio, sys
from pathlib import Path
from backend.core.alpine_worker import WorkerClient
from backend.core.md_job import MdJob
ws=Path(sys.argv[2])
asyncio.run(WorkerClient(Path(sys.argv[1])).fetch_outputs(MdJob.load(sys.argv[3],ws),ws))
'''
        client = subprocess.Popen([sys.executable, '-c', client_code, str(directory), str(ws), job.job_id], env=env)
        until(lambda: (ws / 'started').exists())
        client.kill()
        client.wait(timeout=3)
        until(lambda: MdJob.load(job.job_id, ws).download_status.get('state') == 'verified')
        assert worker.poll() is None
        assert (ws / 'bytes-finished').read_bytes() == b'complete result'
        assert WorkerClient(directory).is_connected()
    finally:
        if client is not None and client.poll() is None:
            client.kill()
            client.wait(timeout=3)
        worker.terminate()
        worker.communicate(timeout=3)


def test_explicit_disconnect_interrupts_transfer_and_retains_recovery_state(tmp_path, monkeypatch):
    class Connection(FakeConnection):
        async def disconnect(self):
            self.closed = True
    async def scenario():
        job = make_job(tmp_path)
        started = asyncio.Event()
        async def fetch(job, workspace, *, conn):
            job.download_status = {'state': 'downloading', 'transferred_bytes': 10}
            job.save(workspace)
            started.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(md_executor, '_fetch_outputs_locked', fetch)
        worker = Worker(tmp_path / 'worker', Connection())
        task = asyncio.create_task(worker.dispatch('fetch_outputs', {'job_id': job.job_id, 'workspace': str(tmp_path)}))
        await started.wait()
        await worker.dispatch('disconnect', {})
        with pytest.raises(asyncio.CancelledError):
            await task
        assert worker.conn.closed
        loaded = MdJob.load(job.job_id, tmp_path)
        assert loaded.download_status['state'] == 'interrupted'
        assert loaded.download_status['transferred_bytes'] == 10
    asyncio.run(scenario())
