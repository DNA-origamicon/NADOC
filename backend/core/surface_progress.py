"""Request-local surface work reporting. No timers or guessed time percentages."""

from contextvars import ContextVar
from contextlib import contextmanager

_sink = ContextVar("surface_progress_sink", default=None)
_group = ContextVar("surface_progress_group", default=None)


def report(stage, done=None, total=None):
    sink = _sink.get()
    if sink is not None:
        sink({"stage": stage, "done": done, "total": total, "strand": _group.get()})


@contextmanager
def reporting(sink):
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def strand_scope(index, total):
    token = _group.set({"index": index, "total": total})
    try:
        yield
    finally:
        _group.reset(token)
