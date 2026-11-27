"""Ephemeral EM trajectory jobs: bounded optical inputs, cancellable process groups.

No molecular document writes. Results expire after 30 idle minutes; only four
archives retained. The shared EM lock excludes simultaneous snapshot/batch work.
"""
import asyncio
import atexit
import json
import os
import orjson
from pathlib import Path
import signal
import shutil
import tempfile
import time
import uuid

from starlette.responses import Response

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.physics.em_volume_archive import read_frame
from backend.rendering.em_interpolation import with_display_tetrahedra


def encode_frame(path, ordinal):
    # Native NumPy serialization avoids FastAPI walking every scalar on its event
    # loop. Preserve float64 samples; attach derived display connectivity only here.
    return orjson.dumps(with_display_tetrahedra(read_frame(path, ordinal)), option=orjson.OPT_SERIALIZE_NUMPY)


def mount_trajectory_routes(router, request_type, solver_python, root, lock):
    class Frame(BaseModel):
        model_config = ConfigDict(extra='forbid')
        frame_index: int = Field(ge=0)
        input: request_type

    class Batch(BaseModel):
        model_config = ConfigDict(extra='forbid')
        frames: list[Frame] = Field(min_length=1, max_length=10000)

    jobs = {}

    def terminate(job):
        process = job.get('process')
        if process and process.returncode is None:
            try:
                if os.name == 'posix':
                    os.killpg(process.pid, signal.SIGTERM)
                else:
                    process.kill()
            except ProcessLookupError:
                pass

    def cleanup():
        for job in jobs.values():
            terminate(job)
            job['directory'].cleanup()
    atexit.register(cleanup)

    def expire():
        now = time.monotonic()
        for key, job in list(jobs.items()):
            if job['done'] and now-job['touched'] > 1800:
                job['directory'].cleanup()
                del jobs[key]

    def lookup(identity):
        expire()
        if identity not in jobs:
            raise HTTPException(404, 'EM results expired or unavailable. Run EM Analysis again.')
        jobs[identity]['touched'] = time.monotonic()
        return jobs[identity]

    async def work(job, entries):
        try:
            executable = solver_python()
            env = {**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1',
                   'MKL_NUM_THREADS': '1', 'NUMBA_NUM_THREADS': '1'}
            process = await asyncio.create_subprocess_exec(executable, '-m',
                'backend.physics.em_volume_archive', str(job['path']), '--compute-backend', 'auto',
                cwd=root, env=env, start_new_session=os.name == 'posix',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            job['process'] = process
            if job.get('cancelled'):
                terminate(job)
            stdout, stderr = await process.communicate(('\n'.join(entries)+'\n').encode())
            if process.returncode and not job.get('cancelled'):
                job['error'] = (stderr.decode(errors='replace') or stdout.decode(errors='replace'))[-2000:]
        except Exception as exc:
            job['error'] = str(exc)
        finally:
            job['done'] = True
            lock.release()

    @router.on_event('shutdown')
    async def shutdown():
        for job in list(jobs.values()):
            job['cancelled'] = True
            terminate(job)
        await asyncio.gather(*(job['task'] for job in jobs.values()), return_exceptions=True)
        cleanup()
        jobs.clear()

    @router.post('/trajectories')
    async def start(payload: Batch):
        if len({f.frame_index for f in payload.frames}) != len(payload.frames):
            raise HTTPException(422, 'Duplicate source frame index.')
        if not solver_python():
            raise HTTPException(503, 'EM solver is not installed.')
        # Expire completed caches without requiring a client to access them again.
        expire()
        if len(jobs) >= 4:
            raise HTTPException(409, 'Close an existing EM trajectory result before starting another.')
        if lock.locked():
            raise HTTPException(409, 'Another EM analysis is running.')
        await lock.acquire()
        identity = uuid.uuid4().hex
        try:
            scratch = Path(os.environ.get('NADOC_TEST_SCRATCH_ROOT') or tempfile.gettempdir())
            mount = os.environ.get('NADOC_TEST_SCRATCH_MOUNT')
            budget = sum(5 * f.input.resolution**3 * 64 for f in payload.frames) + 512*1024**2
            if (not scratch.is_dir() or shutil.disk_usage(scratch).free < budget or
                (mount and (not Path(mount).is_mount() or not scratch.resolve().is_relative_to(Path(mount).resolve())))):
                raise HTTPException(507, 'Insufficient or unavailable scratch storage for EM trajectory volumes.')
            directory = tempfile.TemporaryDirectory(prefix='nadoc-em-trajectory-', dir=scratch)
        except BaseException:
            lock.release()
            raise
        job = {'directory': directory, 'path': Path(directory.name)/'volumes',
               'done': False, 'touched': time.monotonic(), 'total': len(payload.frames)}
        jobs[identity] = job
        job['task'] = asyncio.create_task(work(job, [f.model_dump_json() for f in payload.frames]))
        return {'id': identity, 'total': job['total']}

    @router.get('/trajectories/{identity}')
    async def progress(identity: str):
        job = lookup(identity)
        path = job['path']/'manifest.json'
        manifest = json.loads(path.read_text()) if path.exists() else {}
        return {'id': identity, 'total': job['total'], 'completed': len(manifest.get('frames', [])),
                'frames': [f['frame_index'] for f in manifest.get('frames', [])],
                'status': 'cancelled' if job.get('cancelled') else 'failed' if job.get('error') else
                          'complete' if job['done'] else 'running',
                'error': job.get('error'), 'processing': manifest.get('processing')}

    @router.get('/trajectories/{identity}/frames/{ordinal}')
    async def frame(identity: str, ordinal: int):
        job = lookup(identity)
        try:
            body = await asyncio.to_thread(encode_frame, job['path'], ordinal)
        except (IndexError, FileNotFoundError) as exc:
            raise HTTPException(404, 'EM frame is not ready.') from exc
        return Response(body, media_type='application/json')

    @router.delete('/trajectories/{identity}')
    async def cancel(identity: str):
        job = lookup(identity)
        job['cancelled'] = True
        terminate(job)
        await job['task']
        job['directory'].cleanup()
        jobs.pop(identity, None)
        return {'cancelled': True}
