"""Bounded parallel CPU frames and resource-aware CPU/GPU trajectory selection.

CPU multiprocessing avoids Python-loop contention. One numerical thread per
worker; GPU uses one persistent worker. Only the coordinator writes the archive.
"""
from concurrent.futures import ProcessPoolExecutor
from contextlib import ExitStack
import json
import multiprocessing
import os
import time

from backend.physics.em_resources import observe
from backend.physics.em_volume_archive import VolumeArchive


def initialize_worker():
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMBA_NUM_THREADS'):
        os.environ[name] = '1'
    try:
        os.nice(10)
    except (AttributeError, OSError):
        pass
    # Spawn imports may have loaded NumPy already; cap those pools too.
    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(limits=1)
    except ImportError as exc:
        raise RuntimeError('Parallel EM requires threadpoolctl in the EM environment.') from exc


def solve_frame(payload, backend):
    from backend.physics.em_analysis import solve
    return solve({**payload, 'compute_backend': backend}, arrays=True)


def choose(cpu_seconds, gpu_seconds, workers):
    """Require a 15% advantage over estimated parallel CPU throughput."""
    return 'gpu' if gpu_seconds is not None and gpu_seconds < .85 * cpu_seconds / workers else 'cpu'


def write_trajectory(lines, destination, *, compute_backend='auto', workers=None,
                     allow_busy_gpu=False, resource_probe=observe, executor_factory=ProcessPoolExecutor):
    if compute_backend not in ('auto', 'cpu', 'gpu'):
        raise ValueError('Unknown trajectory compute backend.')
    if workers is not None and (type(workers) is not int or not 1 <= workers <= 4):
        raise ValueError('CPU workers must be between 1 and 4; resource limits may reduce this.')
    archive = VolumeArchive(destination)
    decisions = []
    archive.manifest['processing'] = {'requested_backend': compute_backend,
                                     'decisions': decisions, 'cpu_execution': 'processes, one numerical thread each'}
    def read_resources():
        snapshot = resource_probe()
        if snapshot['cpu_workers'] < 1:
            raise RuntimeError('Insufficient memory headroom for another EM frame; completed frames retained.')
        return snapshot
    def record(backend, count, resources, **extra):
        decisions.append({'before_ordinal': len(archive.manifest['frames']), 'backend': backend,
                          'workers': count, 'resources': resources, **extra})
        archive._save()
    try:
        with ExitStack() as stack:
            resources = read_resources()
            capacity = min(workers or 4, resources['cpu_workers'])
            # Spawn, never fork a live CUDA context or a numerical thread pool.
            cpu = stack.enter_context(executor_factory(max_workers=capacity,
                mp_context=multiprocessing.get_context('spawn'), initializer=initialize_worker))
            gpu = None
            def gpu_executor():
                nonlocal gpu
                if gpu is None:
                    gpu = stack.enter_context(executor_factory(max_workers=1,
                        mp_context=multiprocessing.get_context('spawn'), initializer=initialize_worker))
                return gpu
            entries = iter(lines)
            first = next(entries, None)
            if first is None:
                archive.finish()
                return archive.manifest
            first = json.loads(first)
            backend = compute_backend
            if backend == 'gpu' and not resources['gpu']['safe'] and not allow_busy_gpu:
                raise RuntimeError('GPU is busy or its availability is unknown. Use auto/CPU, or explicitly --allow-busy-gpu.')
            if backend == 'auto':
                started = time.perf_counter()
                cpu_result = cpu.submit(solve_frame, first['input'], 'cpu').result()
                cpu_time = time.perf_counter() - started
                gpu_result, gpu_time, gpu_error = None, None, None
                # A simulation may have started during the CPU pilot.
                resources = read_resources()
                capacity = min(capacity, resources['cpu_workers'])
                if resources['gpu']['safe']:
                    started = time.perf_counter()
                    try:
                        gpu_result = gpu_executor().submit(solve_frame, first['input'], 'gpu').result()
                        gpu_time = time.perf_counter() - started
                    except Exception as exc:
                        gpu_error = f'{type(exc).__name__}: {exc}'
                backend = choose(cpu_time, gpu_time, capacity)
                result = gpu_result if backend == 'gpu' else cpu_result
                if backend == 'cpu' and gpu is not None:
                    # Do not retain a CUDA context/VRAM after rejecting the GPU.
                    gpu.shutdown(wait=True, cancel_futures=True)
                    gpu = None
                record(backend, 1 if backend == 'gpu' else capacity, resources,
                       cpu_pilot_seconds=cpu_time, gpu_pilot_seconds=gpu_time,
                       gpu_pilot_error=gpu_error, policy='first-frame wall time; GPU needs 15% advantage over estimated parallel CPU')
                archive.append(result, frame_index=first['frame_index'], time_ps=first.get('time_ps'))
            else:
                record(backend, 1 if backend == 'gpu' else capacity, resources)
                result = (gpu_executor() if backend == 'gpu' else cpu).submit(solve_frame, first['input'], backend).result()
                archive.append(result, frame_index=first['frame_index'], time_ps=first.get('time_ps'))
            while True:
                resources = read_resources()
                count = min(capacity, resources['cpu_workers'])
                # Never begin another GPU frame against newly detected external work.
                if backend == 'gpu' and not resources['gpu']['safe'] and not allow_busy_gpu:
                    if compute_backend == 'gpu':
                        raise RuntimeError('GPU became busy; completed frames retained. Resume with CPU in a new archive.')
                    backend = 'cpu'
                    gpu.shutdown(wait=True, cancel_futures=True)
                    gpu = None
                    record(backend, count, resources, reason='GPU became occupied; remaining frames use CPU')
                count = 1 if backend == 'gpu' else count
                if decisions[-1]['workers'] != count:
                    record(backend, count, resources, reason='CPU resource budget changed')
                batch = []
                for _ in range(count):
                    line = next(entries, None)
                    if line is None:
                        break
                    batch.append(json.loads(line))
                if not batch:
                    break
                pool = gpu_executor() if backend == 'gpu' else cpu
                futures = [pool.submit(solve_frame, entry['input'], backend) for entry in batch]
                try:
                    for entry, future in zip(batch, futures):
                        result = future.result()
                        archive.append(result, frame_index=entry['frame_index'], time_ps=entry.get('time_ps'))
                finally:
                    for future in futures:
                        future.cancel()
    except BaseException as exc:
        archive.finish(error=f'{type(exc).__name__}: {exc}')
        raise
    archive.finish()
    return archive.manifest
