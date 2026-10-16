"""Drain request-owned threads before releasing their resource admission."""

import asyncio
from functools import partial

from starlette.concurrency import run_in_threadpool


async def thread_call(function, *args, cancelled=None, **kwargs):
    """Forward cancellation, finish cleanup, then rethrow caller cancellation.

    The blocking function must observe the supplied event or have bounded work.
    Shielding alone is insufficient: the request must retain its resource slot
    until its thread has actually returned, including repeated cancellation.
    """
    task = asyncio.create_task(run_in_threadpool(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if cancelled is not None:
            cancelled.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if task.done() and not task.cancelled():
            task.exception()
        raise
