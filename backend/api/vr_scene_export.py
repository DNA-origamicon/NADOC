"""Single CPU worker for canonical VR exports, isolated from HTTP polling's GIL.

Only immutable request/design snapshots cross the process boundary. Publication,
document ownership and revision checks stay in the parent. The native render
thread and its bounded GPU upload policy are unchanged.
"""
import atexit
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
import multiprocessing
import os
from pathlib import Path
import threading

from fastapi import HTTPException

_lock = threading.Lock()
_pool = None


def _warm():
    from backend.api import routes_vr  # noqa: F401
    from backend.core.native_slab_placement import _native_registration
    _native_registration()


def _render(body, design, representations):
    from backend.api import routes_vr as vr
    from backend.core.native_full_placement import NativePlacementError
    try:
        def produce(write):
            profile_dir = os.environ.get('NADOC_VR_EXPORT_PROFILE_DIR')
            if not profile_dir:
                return vr._snapshot(body, line_writer=write, design_snapshot=design, representations=representations)
            import cProfile
            profiler = cProfile.Profile()
            try:
                with profiler:
                    return vr._snapshot(body, line_writer=write, design_snapshot=design, representations=representations)
            finally:
                directory = Path(profile_dir)
                directory.mkdir(parents=True, exist_ok=True)
                profiler.dump_stats(str(directory / f'worker-{os.getpid()}.prof'))
        return {'path': str(vr._write_scene_snapshot(producer=produce))}
    except NativePlacementError as error:
        # Exception constructors are not necessarily pickle-compatible. Preserve
        # the authority error and site details for the parent's existing gate.
        return {'placement_error': str(error), 'details': error.details}
    except HTTPException as error:
        return {'http_status': error.status_code, 'detail': error.detail}


def _executor():
    global _pool
    with _lock:
        if _pool is None:
            # Forking a threaded HTTP server can inherit locked mutexes.
            _pool = ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context('spawn'))
        return _pool


def warm():
    """Import the CPU exporter while the initial native scene is loading."""
    _executor().submit(_warm)


def export_scene(body, design, representations=None):
    try:
        result = _executor().submit(_render, body, design, representations).result()
    except BrokenProcessPool as error:
        shutdown()
        raise HTTPException(503, detail='VR export worker stopped; retry the scene refresh') from error
    if 'placement_error' in result:
        from backend.core.native_full_placement import NativePlacementError
        raise NativePlacementError(result['placement_error'], details=result['details'])
    if 'http_status' in result:
        raise HTTPException(result['http_status'], detail=result['detail'])
    return Path(result['path'])


def shutdown():
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.shutdown(wait=True, cancel_futures=True)


atexit.register(shutdown)
