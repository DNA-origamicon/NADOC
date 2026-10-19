"""Pause cyclic garbage collection around one large, short-lived computation.

A real-part preview allocates millions of small objects; generation-2
collections over the ~1M long-lived tracked objects then cost up to ~0.5 s at
random points (measured on an 18-helix x 504 bp part). Reference counting still
frees memory immediately; cycles are collected after the outermost pause ends.
Re-entrant and thread-safe: collection resumes only when every pause has ended,
and only if it was enabled when the first pause began.
"""

from contextlib import contextmanager
import gc
from threading import Lock

_lock = Lock()
_depth = 0
_was_enabled = False


@contextmanager
def paused_gc():
    global _depth, _was_enabled
    with _lock:
        if _depth == 0:
            _was_enabled = gc.isenabled()
            gc.disable()
        _depth += 1
    try:
        yield
    finally:
        with _lock:
            _depth -= 1
            if _depth == 0 and _was_enabled:
                gc.enable()
