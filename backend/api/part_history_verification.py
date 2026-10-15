"""On-demand part proof checks; never called by edit, render, or scrub paths."""
from threading import BoundedSemaphore
from time import monotonic

from fastapi import HTTPException

from backend.api import state
from backend.core.part_history_contract import assess_part_history
from backend.core.part_verification_capture import CaptureLimit
from backend.api.part_proof_commands import execute, dependencies


# Bound concurrent full-document copies. Contention fails immediately rather
# than queuing expensive work or making the editor wait for an audit slot.
_slot = BoundedSemaphore(1)


def verify_current_part():
    if not _slot.acquire(blocking=False):
        raise HTTPException(429, detail="A part history check is already running; retry later.")
    try:
        source, isolated, revision = state.capture_design_for_verification()
        deadline = monotonic() + 0.5
        def checkpoint():
            if monotonic() > deadline:
                raise HTTPException(408, detail="Synchronous verification time limit; use a verification job")
        result = assess_part_history(isolated, execute=execute, dependencies=dependencies, checkpoint=checkpoint)
        current, current_revision = state.get_design_with_revision()
        result["source_revision"] = revision
        result["design_id"] = isolated.id
        result["stale"] = current is not source or current_revision != revision
        if result["stale"]:
            result["status"] = "unverified"
            result["native_editable"] = False
            result["issues"].append({"code": "source_changed"})
        return result
    except CaptureLimit as exc:
        raise HTTPException(413, detail=str(exc)) from exc
    finally:
        _slot.release()
