"""
API layer — active design state singleton.

Holds a single in-memory Design instance shared across all request handlers.
All mutations are protected by a threading.Lock.

Usage
-----
    from backend.api import state

    # Read
    design = state.get_or_404()

    # Mutate + validate atomically
    design, report = state.mutate_and_validate(lambda d: d.helices.append(h))
"""

from __future__ import annotations

import threading
from typing import Callable

from fastapi import HTTPException

from backend.core.models import Design
from backend.core.validator import ValidationReport, validate_design

_lock = threading.Lock()
_active_design: Design | None = None


def get_design() -> Design | None:
    with _lock:
        return _active_design


def set_design(d: Design) -> None:
    global _active_design
    with _lock:
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

    Returns (design, report).  Raises HTTP 404 if no active design.
    """
    global _active_design
    with _lock:
        if _active_design is None:
            raise HTTPException(status_code=404, detail="No active design.")
        fn(_active_design)
        report = validate_design(_active_design)
    return _active_design, report
