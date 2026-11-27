"""Tie speculative Bevel work to its HTTP owner, including worker reaping."""
import asyncio
from collections import OrderedDict
from threading import Event, Lock
from time import monotonic

from fastapi import HTTPException


class PreparationCancelled(Exception):
    pass


_lock = Lock()
_owners = OrderedDict()


def _owner(identity):
    from backend.api.doc_context import get_current_doc
    key = get_current_doc(), identity
    now = monotonic()
    for old_key, row in list(_owners.items()):
        if not row['active'] and now - row['time'] > 300:
            del _owners[old_key]
    if key not in _owners:
        if len(_owners) >= 256:
            expired = next((k for k, r in _owners.items() if not r['active']), None)
            if expired is None:
                raise HTTPException(503, detail='Bevel preparation is busy.')
            del _owners[expired]
        _owners[key] = {'event': Event(), 'active': False, 'time': now}
    return _owners[key]


def cancel_preparation(identity):
    # A cancellation arriving before the proxied preparation leaves a bounded
    # tombstone. Its late request must never start expensive work.
    with _lock:
        _owner(identity)['event'].set()


async def prepare_until_disconnected(request, evaluate, identity=None):
    with _lock:
        owner = _owner(identity) if identity else {'event': Event(), 'active': False}
        if owner['active']:
            raise HTTPException(409, detail='Bevel preparation is already running.')
        owner['active'] = True
    cancelled = owner['event']

    def check(*_):
        if cancelled.is_set():
            raise PreparationCancelled()

    # to_thread propagates the document/request ContextVars. The native recorder
    # remains detached; no canonical state is published during preparation.
    task = asyncio.create_task(asyncio.to_thread(evaluate, check))
    try:
        while not task.done():
            if await request.is_disconnected():
                raise HTTPException(499, detail='Bevel preparation cancelled.')
            await asyncio.wait({task}, timeout=.05)
        return task.result()
    except PreparationCancelled as error:
        raise HTTPException(499, detail='Bevel preparation cancelled.') from error
    finally:
        cancelled.set()
        # Checkpoints in the bounded projection loop close/reap both children.
        # Consume late exceptions and keep the owner alive until cleanup ends.
        await asyncio.shield(asyncio.gather(task, return_exceptions=True))
        with _lock:
            owner.update(active=False, time=monotonic())
