"""
API layer — active assembly state singleton.

Mirrors backend/api/state.py exactly, substituting Assembly for Design.
Holds a single in-memory Assembly instance shared across all request handlers.
All mutations are protected by a threading.Lock.

Also maintains undo/redo history stacks (up to MAX_UNDO_STEPS deep each).
Every call to set_assembly() pushes the previous state onto the undo stack
and clears the redo stack.  undo() pops from the undo stack and pushes the
displaced state onto the redo stack.  redo() reverses that.

The assembly undo stack is completely independent of the design undo stack —
Ctrl+Z in assembly mode only pops from this stack.

Usage
-----
    from backend.api import assembly_state

    # Read
    assembly = assembly_state.get_or_404()

    # Mutate (push old state onto undo stack)
    assembly_state.set_assembly(new_assembly)

    # Undo last mutation
    assembly = assembly_state.undo()

    # Get or auto-create (for GET /assembly)
    assembly = assembly_state.get_or_create()
"""

from __future__ import annotations

import threading
from collections import deque

from fastapi import HTTPException

from backend.core.models import Assembly

MAX_UNDO_STEPS = 50

_lock = threading.Lock()
_active_assembly: Assembly | None = None
_history: deque[Assembly] = deque(maxlen=MAX_UNDO_STEPS)
_redo:    deque[Assembly] = deque(maxlen=MAX_UNDO_STEPS)


def get_assembly() -> Assembly | None:
    with _lock:
        return _active_assembly


def set_assembly(a: Assembly) -> None:
    global _active_assembly
    with _lock:
        if _active_assembly is not None:
            _history.append(_active_assembly.model_copy(deep=True))
        _redo.clear()
        _active_assembly = a


def get_or_404() -> Assembly:
    with _lock:
        if _active_assembly is None:
            raise HTTPException(status_code=404, detail="No active assembly.")
        return _active_assembly


def get_or_create() -> Assembly:
    """Return the active assembly, creating a new empty one if none exists."""
    global _active_assembly
    with _lock:
        if _active_assembly is None:
            _active_assembly = Assembly()
        return _active_assembly


def undo() -> Assembly:
    """Restore the previous assembly state.

    Returns the restored assembly.  Raises HTTP 404 if nothing to undo.
    """
    global _active_assembly
    with _lock:
        if not _history:
            raise HTTPException(status_code=404, detail="Nothing to undo.")
        _redo.append(_active_assembly.model_copy(deep=True))
        _active_assembly = _history.pop()
    return _active_assembly


def redo() -> Assembly:
    """Re-apply the last undone mutation.

    Returns the restored assembly.  Raises HTTP 404 if nothing to redo.
    """
    global _active_assembly
    with _lock:
        if not _redo:
            raise HTTPException(status_code=404, detail="Nothing to redo.")
        _history.append(_active_assembly.model_copy(deep=True))
        _active_assembly = _redo.pop()
    return _active_assembly


def clear_history() -> None:
    """Discard both undo and redo history (e.g. after loading a new assembly from disk)."""
    with _lock:
        _history.clear()
        _redo.clear()


def close_session() -> None:
    """Erase the active assembly and all history."""
    global _active_assembly
    with _lock:
        _active_assembly = None
        _history.clear()
        _redo.clear()


def snapshot() -> None:
    """Push the current assembly onto the undo stack without changing it.

    Use before starting a multi-step operation so the entire operation is
    undoable as a single Ctrl-Z.
    """
    global _active_assembly
    with _lock:
        if _active_assembly is not None:
            _history.append(_active_assembly.model_copy(deep=True))
        _redo.clear()


def set_assembly_silent(a: Assembly) -> None:
    """Update the active assembly without pushing to the undo stack.

    Use for intermediate steps in a multi-step operation where snapshot()
    was already called before the first step.
    """
    global _active_assembly
    with _lock:
        _active_assembly = a


def undo_depth() -> int:
    """Return the current undo stack depth."""
    with _lock:
        return len(_history)


def redo_depth() -> int:
    """Return the current redo stack depth."""
    with _lock:
        return len(_redo)
