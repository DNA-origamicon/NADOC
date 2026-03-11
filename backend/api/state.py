"""
API layer — active design state singleton.

Holds a single in-memory Design instance shared across all request handlers.
All mutations are protected by a threading.Lock.

Also maintains undo/redo history stacks (up to MAX_UNDO_STEPS deep each).
Every call to set_design() or mutate_and_validate() pushes the previous state
onto the undo stack and clears the redo stack.  undo() pops from the undo stack
and pushes the displaced state onto the redo stack.  redo() reverses that.

Usage
-----
    from backend.api import state

    # Read
    design = state.get_or_404()

    # Mutate + validate atomically
    design, report = state.mutate_and_validate(lambda d: d.helices.append(h))

    # Undo last mutation (returns (design, report) or raises 404 if nothing to undo)
    design, report = state.undo()

    # Redo last undone mutation (returns (design, report) or raises 404 if nothing to redo)
    design, report = state.redo()
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable

from fastapi import HTTPException

from backend.core.models import Design
from backend.core.validator import ValidationReport, validate_design

MAX_UNDO_STEPS = 50

_lock = threading.Lock()
_active_design: Design | None = None
_history: deque[Design] = deque(maxlen=MAX_UNDO_STEPS)
_redo:    deque[Design] = deque(maxlen=MAX_UNDO_STEPS)


def get_design() -> Design | None:
    with _lock:
        return _active_design


def set_design(d: Design) -> None:
    global _active_design
    with _lock:
        if _active_design is not None:
            _history.append(_active_design)
        _redo.clear()
        _active_design = d


def get_or_404() -> Design:
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        return _active_design


def mutate_and_validate(
    fn: Callable[[Design], None],
) -> tuple[Design, ValidationReport]:
    """Apply *fn* to the active design in-place under the lock, then validate.

    Pushes the pre-mutation snapshot onto the undo stack and clears redo.
    Returns (design, report).  Raises HTTP 404 if no active design.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        _history.append(_active_design.model_copy(deep=True))
        _redo.clear()
        fn(_active_design)
        report = validate_design(_active_design)
    return _active_design, report


def undo() -> tuple[Design, ValidationReport]:
    """Restore the previous design state.

    Returns (design, report).  Raises HTTP 404 if nothing to undo.
    """
    global _active_design
    with _lock:
        if not _history:
            raise HTTPException(status_code=404, detail="Nothing to undo.")
        _redo.append(_active_design.model_copy(deep=True))
        _active_design = _history.pop()
        report = validate_design(_active_design)
    return _active_design, report


def redo() -> tuple[Design, ValidationReport]:
    """Re-apply the last undone mutation.

    Returns (design, report).  Raises HTTP 404 if nothing to redo.
    """
    global _active_design
    with _lock:
        if not _redo:
            raise HTTPException(status_code=404, detail="Nothing to redo.")
        _history.append(_active_design.model_copy(deep=True))
        _active_design = _redo.pop()
        report = validate_design(_active_design)
    return _active_design, report


def clear_history() -> None:
    """Discard both undo and redo history (e.g. after loading a new design from disk)."""
    with _lock:
        _history.clear()
        _redo.clear()
