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

import base64
import gzip
import threading
from collections import deque

from fastapi import HTTPException

from backend.core.models import Assembly

MAX_UNDO_STEPS = 50

_lock = threading.Lock()
_active_assembly: Assembly | None = None
_history: deque[Assembly] = deque(maxlen=MAX_UNDO_STEPS)
_redo:    deque[Assembly] = deque(maxlen=MAX_UNDO_STEPS)

# Per-instance display preferences kept OUTSIDE the assembly object so they
# survive feature-log scrubbing. `representation` and `visible` are pure
# display state — when the user switches a heavy part to a cheap renderer
# for performance, that preference must not be undone every time they move
# the slider.  Keyed by PartInstance.id → {representation?, visible?}.
_display_state: dict[str, dict] = {}


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
        _display_state.clear()


def remember_instance_display(instance_id: str, *,
                                representation: str | None = None,
                                visible:        bool | None = None) -> None:
    """Record a per-instance display preference that survives seek scrubbing.

    Called from any route that mutates ``representation`` or ``visible`` on
    a PartInstance (e.g. ``patch_instance``).  The values are NOT part of
    the assembly snapshot — encoded snapshots still carry whatever was
    current at the time — so seek uses these values to overlay the cheap
    rendering preference on top of the restored geometry.
    """
    with _lock:
        entry = _display_state.get(instance_id, {})
        if representation is not None:
            entry["representation"] = representation
        if visible is not None:
            entry["visible"] = visible
        _display_state[instance_id] = entry


def get_display_overrides() -> dict[str, dict]:
    """Snapshot of the current per-instance display overrides."""
    with _lock:
        return {k: dict(v) for k, v in _display_state.items()}


def forget_instance_display(instance_id: str) -> None:
    """Drop overrides for an instance (e.g. when the instance is deleted)."""
    with _lock:
        _display_state.pop(instance_id, None)


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


# ── Assembly snapshot encoder / decoder ──────────────────────────────────────
#
# Mirrors backend.api.state.encode_design_snapshot for embedding pre/post
# assembly states in SnapshotLogEntry payloads.  Required for the assembly
# feature log's per-entry Delete / Revert / Edit actions: without a payload
# the log entry can only carry params, not enough state to surgically remove
# or edit mid-history.

def encode_assembly_snapshot(assembly: Assembly) -> tuple[str, int]:
    """Serialize an Assembly to a gzip+base64 payload for a SnapshotLogEntry.

    The assembly's own ``feature_log`` and ``feature_log_cursor`` are
    stripped to prevent recursive nesting (snapshots embedded inside
    snapshots).  Returns ``(payload_b64, uncompressed_byte_length)``.
    """
    stripped = assembly.model_copy(update={
        "feature_log": [],
        "feature_log_cursor": -1,
    })
    raw = stripped.model_dump_json().encode("utf-8")
    gz = gzip.compress(raw, compresslevel=6)
    return base64.b64encode(gz).decode("ascii"), len(raw)


def decode_assembly_snapshot(payload_b64: str) -> Assembly:
    """Inverse of :func:`encode_assembly_snapshot`."""
    if not payload_b64:
        raise ValueError("empty assembly snapshot payload")
    raw = gzip.decompress(base64.b64decode(payload_b64.encode("ascii")))
    return Assembly.model_validate_json(raw)
