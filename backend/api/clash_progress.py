"""Bounded, ephemeral progress for read-only geometry checks, scoped to a tab."""
from collections import OrderedDict
from contextlib import contextmanager
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from backend.api.doc_context import get_current_doc

ProgressId = Annotated[str | None, Query(pattern=r'^[\w-]{8,80}$')]
router = APIRouter()
_records = OrderedDict()
_lock = Lock()


@router.get('/design/clashes/progress/{request_id}')
async def snapshot(request_id: str):
    # Async: polling must remain available while sync checks occupy worker threads.
    with _lock:
        record = _records.get((get_current_doc(), request_id))
        if record is None or monotonic() - record['updated'] > 600:
            raise HTTPException(404, 'Geometry check expired or not started')
        return {k: v for k, v in record.items() if k not in ('updated', 'cancelled')}


@router.delete('/design/clashes/progress/{request_id}', status_code=204)
async def release(request_id: str):
    with _lock:
        key = (get_current_doc(), request_id)
        record = _records.get(key)
        if record and record['state'] == 'running':
            record['cancelled'] = True
        else:
            _records.pop(key, None)


@contextmanager
def tracking(request_id):
    if not request_id:
        yield lambda *args: None
        return
    key = (get_current_doc(), request_id)
    with _lock:
        for old in list(_records):
            if monotonic() - _records[old]['updated'] > 600:
                del _records[old]
        if key in _records:
            raise HTTPException(409, 'Geometry check ID already used')
        if len(_records) >= 128:
            finished = next((k for k, v in _records.items() if v['state'] != 'running'), None)
            if finished is None:
                raise HTTPException(429, 'Too many active geometry checks')
            del _records[finished]
        record = dict(state='running', stage='Preparing geometry', completed=0,
                      total=None, percent=0, cancelled=False, updated=monotonic())
        _records[key] = record

    def update(stage, completed=0, total=None):
        with _lock:
            if record['cancelled']:
                raise HTTPException(409, 'Geometry check cancelled')
            percent = min(99, int(100 * completed / total)) if total else 0
            record.update(stage=stage, completed=completed, total=total,
                          percent=percent, updated=monotonic())

    try:
        yield update
    except BaseException:
        with _lock:
            record.update(state='failed', updated=monotonic())
        raise
    else:
        with _lock:
            record.update(state='complete', percent=100, updated=monotonic())
    finally:
        with _lock:
            if record['cancelled']:
                _records.pop(key, None)
