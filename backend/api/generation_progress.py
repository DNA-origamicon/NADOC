"""Ephemeral, document-scoped progress for atomic design generation."""

from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic

from fastapi import HTTPException
from backend.api.doc_context import get_current_doc

_records = OrderedDict()
_lock = Lock()
_reporter = ContextVar("generation_reporter", default=None)


def report(stage, detail="", fraction=None):
    callback = _reporter.get()
    if callback:
        callback(stage, detail, fraction)


def snapshot(request_id):
    with _lock:
        record = _records.get((get_current_doc(), request_id))
        if record is None or monotonic() - record["updated"] > 600:
            raise HTTPException(404, "Generation progress expired or not started")
        return {
            **{k: v for k, v in record.items() if k != "updated"},
            "steps": list(record["steps"]),
        }


@contextmanager
def tracking(request_id):
    if not request_id:
        yield
        return
    key = (get_current_doc(), request_id)
    with _lock:
        for old in list(_records):
            if monotonic() - _records[old]["updated"] > 600:
                del _records[old]
        if key in _records:
            raise HTTPException(409, "Generation progress ID already used")
        if len(_records) >= 128:
            finished = next(
                (k for k, v in _records.items() if v["state"] != "running"), None
            )
            if finished is None:
                raise HTTPException(429, "Too many active generations")
            del _records[finished]
        _records[key] = dict(
            state="running",
            stage="Planning",
            detail="",
            fraction=0,
            steps=[],
            updated=monotonic(),
        )

    def update(stage, detail, fraction):
        with _lock:
            record = _records[key]
            if stage != record["stage"]:
                record["steps"].append(record["stage"])
            record.update(stage=stage, detail=detail, updated=monotonic())
            if fraction is not None:
                record["fraction"] = max(record["fraction"], min(0.99, fraction))

    token = _reporter.set(update)
    try:
        yield
    except BaseException:
        with _lock:
            _records[key].update(state="failed", updated=monotonic())
        raise
    else:
        with _lock:
            _records[key].update(state="complete", fraction=1, updated=monotonic())
    finally:
        _reporter.reset(token)
