"""Opt-in isolated benchmark ASGI wrapper; samples delayed event-loop work."""
import asyncio
import gc
import json
import os
import sys
import threading
import time
import traceback

from backend.api.main import app as application

if os.environ.get('NADOC_VR_PUBLICATION_FREEZE') != '0':
    from server_bootstrap import create_app
    application = create_app()


async def app(scope, receive, send):
    if scope['type'] != 'lifespan':
        await application(scope, receive, send)
        return
    loop = asyncio.get_running_loop()
    owner = threading.get_ident()
    heartbeat = [time.monotonic()]
    stopped = threading.Event()
    collections = {}

    def collected(phase, info):
        generation = info['generation']
        if phase == 'start':
            collections[generation] = (time.perf_counter(), time.time() * 1000)
        elif generation in collections:
            start, epoch = collections.pop(generation)
            elapsed = (time.perf_counter() - start) * 1000
            if elapsed > 20 or generation == 2:
                print('VR_GC_COLLECTION ' + json.dumps({
                    'epoch_ms': epoch, 'ms': elapsed, **info,
                }), flush=True)

    def tick():
        heartbeat[0] = time.monotonic()
        if not stopped.is_set():
            loop.call_later(.01, tick)

    def sample():
        while not stopped.wait(.02):
            delay = time.monotonic() - heartbeat[0]
            if delay > .05:
                frame = sys._current_frames().get(owner)
                print('VR_LOOP_STALL ' + json.dumps({
                    'epoch_ms': time.time() * 1000, 'delay_ms': delay * 1000,
                    'stack': traceback.format_stack(frame) if frame else [],
                }), flush=True)

    tick()
    gc.callbacks.append(collected)
    worker = threading.Thread(target=sample, daemon=True)
    worker.start()
    try:
        await application(scope, receive, send)
    finally:
        stopped.set()
        gc.callbacks.remove(collected)
