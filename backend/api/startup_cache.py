"""Coalesce concurrent job reads without retaining stale mutation results."""
import asyncio
from copy import deepcopy
from functools import wraps
from weakref import WeakKeyDictionary
from fastapi.concurrency import run_in_threadpool


def coalesce_job_reads(fn):
    # Tasks belong to an event loop; document and revision affect staleness fields.
    loops = WeakKeyDictionary()

    @wraps(fn)
    async def wrapped(*args, **kwargs):
        from backend.api import assembly, state
        from backend.api.doc_context import get_current_doc

        pending = loops.setdefault(asyncio.get_running_loop(), {})
        revision = await run_in_threadpool(state.revision)
        key = (str(assembly._WORKSPACE_DIR), get_current_doc(), revision, args, tuple(sorted(kwargs.items())))
        task = pending.get(key)
        if task is None:
            task = asyncio.create_task(fn(*args, **kwargs))
            pending[key] = task
            def finished(done):
                if pending.get(key) is done:
                    pending.pop(key, None)
                if not done.cancelled():
                    done.exception()  # retrieve failures even if all clients disconnected
            task.add_done_callback(finished)
        # One disconnected caller must not cancel the scan for everyone else.
        return deepcopy(await asyncio.shield(task))

    return wrapped
