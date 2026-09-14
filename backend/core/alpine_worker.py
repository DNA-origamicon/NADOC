"""Detached Alpine session and transfer owner; private local Unix-socket RPC.

The API is a client, never the owner of the SSH transport or download tasks.
Credentials cross the owner-only socket once and are never written to disk.
"""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from backend.core.alpine_transfer_state import atomic_json, state_path

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 64 * 1024 * 1024


def runtime_dir() -> Path:
    suffix = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    path = Path('/tmp') / f'nadoc-alpine-worker-{os.getuid()}-{suffix}'
    path.mkdir(mode=0o700, exist_ok=True)
    stat = path.lstat()
    if path.is_symlink() or stat.st_uid != os.getuid() or stat.st_mode & 0o077:
        raise PermissionError('Alpine worker directory must be private to this user')
    return path


class WorkerClient:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or runtime_dir()

    def status(self):
        try:
            data = json.loads((self.directory / 'status.json').read_text())
            if time.time() - data.pop('heartbeat', 0) < 10:
                return data
        except (OSError, ValueError):
            pass
        return {'state': 'disconnected', 'who': None, 'host': None,
                'last_error': None, 'error_kind': None}

    @property
    def user(self):
        return (self.status().get('who') or '').split('@')[0]

    @property
    def host(self):
        return self.status().get('host') or ''

    def is_connected(self):
        return self.status()['state'] == 'connected'

    async def _rpc(self, method, **args):
        from backend.core.cluster_ssh import ClusterSSHError
        try:
            reader, writer = await asyncio.open_unix_connection(
                str(self.directory / 'worker.sock'), limit=LIMIT)
        except OSError as exc:
            raise ClusterSSHError('Alpine worker unavailable; reconnect to Alpine') from exc
        try:
            writer.write(json.dumps({'method': method, 'args': args}).encode() + b'\n')
            await writer.drain()
            line = await reader.readline()
            if not line:
                raise ClusterSSHError('Alpine worker stopped; partial downloads are retained')
            response = json.loads(line)
            if 'error' in response:
                raise ClusterSSHError(response['error'], kind=response.get('kind'))
            return response['result']
        finally:
            writer.close()
            await writer.wait_closed()

    async def _ensure(self):
        try:
            await self._rpc('ping')
            return
        except Exception:
            pass
        with (self.directory / 'worker.log').open('ab') as log:
            process = subprocess.Popen(
                [sys.executable, '-m', 'backend.core.alpine_worker', str(self.directory)],
                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                start_new_session=True, close_fds=True)
        # Reap when possible without making the subprocess a child task of uvicorn.
        async def reap():
            while process.poll() is None:
                await asyncio.sleep(2)
        asyncio.create_task(reap())
        for _ in range(100):
            await asyncio.sleep(.1)
            try:
                await self._rpc('ping')
                return
            except Exception:
                pass
        raise RuntimeError('Alpine worker did not start; inspect ' + str(self.directory / 'worker.log'))

    async def connect(self, host, user, password, duo_method='push'):
        await self._ensure()
        await self._rpc('connect', host=host, user=user, password=password, duo_method=duo_method)

    async def disconnect(self):
        if (self.directory / 'worker.sock').exists():
            await self._rpc('disconnect')

    async def run(self, cmd, timeout=60.0):
        from backend.core.cluster_ssh import RunResult
        return RunResult(**await self._rpc('run', cmd=cmd, timeout=timeout))

    async def mkdir_p(self, remote_dir):
        await self._rpc('mkdir_p', remote_dir=remote_dir)

    async def sftp_put(self, local_path, remote_path):
        await self._rpc('sftp_put', local_path=local_path, remote_path=remote_path)

    async def sftp_get(self, remote_path, local_path, on_progress=None):
        await self._rpc('sftp_get', remote_path=remote_path, local_path=local_path)
        if on_progress:
            size = Path(local_path).stat().st_size
            on_progress(size, size)

    async def mirror(self, src, dst):
        from backend.core.cluster_ssh import RunResult
        return RunResult(**await self._rpc('mirror', src=src, dst=dst))

    async def fetch_outputs(self, job, workspace):
        from backend.core.alpine_transfer_state import apply_transfer_state
        # Persist intent before RPC so even death before the worker accepts is recoverable.
        from backend.core.alpine_transfer_state import read_state
        if not read_state(job, workspace):
            atomic_json(state_path(job, workspace), {
                'id': uuid.uuid4().hex, 'done': False,
                'download_status': {'state': 'downloading'},
            })
        result = await self._rpc('fetch_outputs', job_id=job.job_id,
                                 workspace=str(Path(workspace).resolve()))
        from backend.core.md_job import MdJob
        latest = MdJob.load(job.job_id, workspace)
        job.__dict__.update(latest.__dict__)
        apply_transfer_state(job, workspace)
        job.save(workspace)
        return result


class Worker:
    def __init__(self, directory, conn):
        self.directory, self.conn = directory, conn
        self.transfers = {}
        self.requests = set()

    def publish(self):
        atomic_json(self.directory / 'status.json',
                    {**self.conn.status(), 'heartbeat': time.time()})

    async def transfer(self, job_id, workspace):
        from backend.core.md_job import MdJob
        from backend.core.md_executor import fetch_outputs
        workspace = Path(workspace)
        job = MdJob.load(job_id, workspace)
        transfer_id = uuid.uuid4().hex
        record = {'id': transfer_id, 'done': False}

        def save_transfer(_workspace):
            status = dict(job.download_status or {})
            status['worker_transfer_id'] = transfer_id
            record['download_status'] = status
            atomic_json(state_path(job, workspace), record)

        # Only write transfer-owned state. Never race the API's job.json writer.
        job.save = save_transfer
        try:
            result = await fetch_outputs(job, workspace, conn=self.conn)
            return result
        except BaseException:
            job.download_status = {**(job.download_status or {}), 'state': 'interrupted'}
            raise
        finally:
            record['done'] = True
            save_transfer(workspace)

    async def dispatch(self, method, args):
        from dataclasses import asdict
        if method == 'ping':
            return True
        if method == 'fetch_outputs':
            key = (str(Path(args['workspace']).resolve()), args['job_id'])
            task = self.transfers.get(key)
            if task is None or task.done():
                task = asyncio.create_task(self.transfer(**args))
                self.transfers[key] = task
            return await asyncio.shield(task)
        if method == 'connect':
            if (self.conn.is_connected() and self.conn.host == args['host']
                    and self.conn.user == args['user']):
                return None
            if any(not task.done() for task in self.transfers.values()):
                raise ValueError('A download is active; disconnect before changing Alpine accounts')
            await self.conn.disconnect()
        if method == 'disconnect':
            for task in self.transfers.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self.transfers.values(), return_exceptions=True)
        if method not in {'connect', 'disconnect', 'run', 'mkdir_p', 'sftp_put', 'sftp_get', 'mirror'}:
            raise ValueError('Unknown Alpine worker operation')
        try:
            value = await getattr(self.conn, method)(**args)
            return asdict(value) if method in {'run', 'mirror'} else value
        finally:
            self.publish()

    async def handle(self, reader, writer):
        try:
            request = json.loads(await reader.readline())
            # Retain task independently of this client/socket, even after API death.
            task = asyncio.create_task(self.dispatch(request['method'], request['args']))
            self.requests.add(task)
            task.add_done_callback(self.requests.discard)
            del request
            try:
                result = {'result': await asyncio.shield(task)}
            except Exception as exc:
                result = {'error': str(exc), 'kind': getattr(exc, 'kind', None)}
            writer.write(json.dumps(result).encode() + b'\n')
            await writer.drain()
        except (ConnectionError, ValueError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def serve(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.directory / 'worker.lock').open('a+b') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return
            socket = self.directory / 'worker.sock'
            socket.unlink(missing_ok=True)
            server = await asyncio.start_unix_server(self.handle, path=str(socket), limit=LIMIT)
            os.chmod(socket, 0o600)
            try:
                async with server:
                    while True:
                        self.publish()
                        await asyncio.sleep(2)
            finally:
                socket.unlink(missing_ok=True)
                (self.directory / 'status.json').unlink(missing_ok=True)


if __name__ == '__main__':
    from backend.core.cluster_ssh import ClusterConnection
    from backend.core import alpine_operations
    os.umask(0o077)
    alpine_operations.configure(Path(os.environ.get('NADOC_WORKSPACE', str(ROOT / 'workspace'))))
    asyncio.run(Worker(Path(sys.argv[1]), ClusterConnection()).serve())
