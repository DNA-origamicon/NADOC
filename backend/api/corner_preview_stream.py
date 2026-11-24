"""Bounded, cancellable native Corner preview stream; never publishes a Design."""

import asyncio
from contextvars import copy_context
import logging
from queue import Empty, Full, Queue
from threading import BoundedSemaphore, Event, Thread
from time import monotonic

import orjson
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from backend.api.corner_guide import corner_guide
from backend.api.corner_preview import evaluate_corner_preview
from backend.api.part_corner_commands import CornerRequest

_slots = BoundedSemaphore(2)


class PreviewCancelled(Exception):
    pass


def corner_preview_response(source, body, *, feature_id=None):
    inputs = {key: getattr(body, key) for key in CornerRequest.model_fields}
    context = copy_context()

    async def events():
        if not _slots.acquire(blocking=False):
            yield orjson.dumps({'type': 'error', 'message': 'Corner preview is busy. Try again shortly.'}) + b'\n'
            return
        cancelled, queue = Event(), Queue(maxsize=8)

        def check():
            if cancelled.is_set():
                raise PreviewCancelled()

        def emit(value):
            while True:
                check()
                try:
                    queue.put(value, timeout=.1)
                    return
                except Full:
                    continue

        def worker():
            try:
                check()
                last_progress = None
                last_progress_time = 0.
                def progress(value):
                    nonlocal last_progress, last_progress_time
                    check()
                    key = (int(value['percent']) if value['percent'] is not None else None, value['stage'])
                    now = monotonic()
                    # Seam search may finish many work units in one display
                    # frame. Preserve actual counts while coalescing transport
                    # updates; otherwise progress itself delays the Full result.
                    changed_stage = last_progress is None or key[1] != last_progress[1]
                    if key != last_progress and (changed_stage or key[0] == 100 or now - last_progress_time >= .05):
                        last_progress = key
                        last_progress_time = now
                        emit({'type': 'progress', **value})
                if feature_id is None:
                    guide = corner_guide(source, body.cluster_id, body.parameters())
                    emit({'type': 'guide', 'guide': guide})
                    packet, _ = evaluate_corner_preview(source, inputs, on_progress=progress, check_cancel=check)
                else:
                    from backend.api.corner_history import evaluate_corner_edit
                    packet, _ = evaluate_corner_edit(source, inputs, feature_id,
                        on_progress=progress, check_cancel=check,
                        on_guide=lambda guide: emit({'type': 'guide', 'guide': guide}))
                check()
                emit({'type': 'ready', **packet})
            except PreviewCancelled:
                pass
            except (ValueError, HTTPException) as error:
                try:
                    emit({'type': 'error', 'message': str(getattr(error, 'detail', error))})
                except PreviewCancelled:
                    pass
            except Exception:
                logging.getLogger(__name__).exception('Corner preview failed')
                try:
                    emit({'type': 'error', 'message': 'Corner preview failed. Check the source geometry and retry.'})
                except PreviewCancelled:
                    pass
            finally:
                try:
                    emit(None)
                except PreviewCancelled:
                    pass
                _slots.release()

        def read():
            try:
                return True, queue.get(timeout=.2)
            except Empty:
                return False, None

        Thread(target=context.run, args=(worker,), daemon=True, name='corner-preview').start()
        try:
            while True:
                received, value = await asyncio.to_thread(read)
                if not received:
                    continue
                if value is None:
                    break
                yield orjson.dumps(value, option=orjson.OPT_SERIALIZE_NUMPY) + b'\n'
        finally:
            cancelled.set()

    return StreamingResponse(events(), media_type='application/x-ndjson',
        headers={'Cache-Control': 'no-store', 'X-Accel-Buffering': 'no', 'Content-Encoding': 'identity'})
