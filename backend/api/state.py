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

from backend.core.cluster_reconcile import (
    MutationReport,
    reconcile_cluster_membership,
)
from backend.core.models import Design
from backend.core.validator import ValidationReport, validate_design

MAX_UNDO_STEPS = 50

_lock = threading.Lock()
_active_design: Design | None = None
_history: deque[Design] = deque(maxlen=MAX_UNDO_STEPS)
_redo:    deque[Design] = deque(maxlen=MAX_UNDO_STEPS)

# Optional pre-built atomistic model from PDB import.
# When set, GET /design/atomistic returns this instead of computing from templates.
_pdb_atomistic: object | None = None


def get_design() -> Design | None:
    with _lock:
        return _active_design


def set_design(d: Design) -> None:
    global _active_design
    with _lock:
        if _active_design is not None:
            _history.append(_active_design.model_copy(deep=True))
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


def mutate_with_reconcile(
    fn: Callable[[Design], MutationReport | None],
) -> tuple[Design, ValidationReport]:
    """Apply *fn* to the active design in-place, then reconcile cluster membership.

    The mutation function may return a ``MutationReport`` to hint at strand
    renames, new-helix parents, etc.  Returning ``None`` is fine — the
    reconciler falls back to bp-range overlap and lattice-neighbor heuristics.

    Pushes the pre-mutation snapshot onto the undo stack and clears redo,
    same as :func:`mutate_and_validate`.  Returns ``(design, report)``.
    Raises HTTP 404 if no active design.

    Use this for any topology mutation that may affect cluster scope:
    crossover/nick/ligation, autostaple/autobreak, end-extend, slice-plane
    extrude, overhang/linker creation, helix CRUD.

    Do NOT use this for routes that explicitly edit ``cluster_transforms``
    (cluster CRUD, feature-log replay, ``relax_overhang_connection``,
    importers).  Those keep :func:`mutate_and_validate`.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        before = _active_design.model_copy(deep=True)
        _history.append(before)
        _redo.clear()
        report = fn(_active_design)
        reconciled = reconcile_cluster_membership(before, _active_design, report)
        _active_design = reconciled
        validation = validate_design(_active_design)
    return _active_design, validation


def replace_with_reconcile(
    new_design: Design,
    report: MutationReport | None = None,
) -> tuple[Design, ValidationReport]:
    """Replace the active design with ``new_design``, snapshot for undo, then reconcile.

    Use this for routes that build the post-mutation design immutably (via
    pure functions in ``backend.core.lattice``) and would otherwise call
    :func:`set_design` directly.

    Same cluster-reconciler semantics as :func:`mutate_with_reconcile`.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        before = _active_design.model_copy(deep=True)
        _history.append(before)
        _redo.clear()
        reconciled = reconcile_cluster_membership(before, new_design, report)
        _active_design = reconciled
        validation = validate_design(_active_design)
    return _active_design, validation


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
    global _pdb_atomistic
    with _lock:
        _history.clear()
        _redo.clear()
        _pdb_atomistic = None


def close_session() -> None:
    """Erase the active design and all history (used when the user closes the session)."""
    global _active_design, _pdb_atomistic
    with _lock:
        _active_design = None
        _history.clear()
        _redo.clear()
        _pdb_atomistic = None


def snapshot() -> None:
    """Push the current design onto the undo stack without changing it.

    Use this before starting a multi-step operation (e.g., step-by-step autostaple)
    so the entire operation is undoable as a single Ctrl-Z.
    """
    global _active_design
    with _lock:
        if _active_design is not None:
            _history.append(_active_design.model_copy(deep=True))
        _redo.clear()


def get_pdb_atomistic() -> object | None:
    """Return the stored PDB atomistic model, or None."""
    with _lock:
        return _pdb_atomistic


def set_pdb_atomistic(model: object | None) -> None:
    """Store a pre-built atomistic model from PDB import."""
    global _pdb_atomistic
    with _lock:
        _pdb_atomistic = model


def set_design_silent(d: Design) -> None:
    """Update the active design without pushing to the undo stack.

    Use for intermediate steps in a multi-step operation where snapshot()
    was already called before the first step.
    """
    global _active_design
    with _lock:
        _active_design = d
