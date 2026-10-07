"""Durable, fail-closed reporting for rejected molecular placement."""
from typing import Any
import traceback
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.core.native_full_placement import NativePlacementError
from tools.native_placement_audit import record_failure, check_review_gate
from tools.native_placement_audit.store import _jsonable

router = APIRouter()


@router.get("/design/placement-integrity-status")
def placement_integrity_status():
    try:
        incidents = [{**incident, "details": json.loads(Path(incident["report"]).read_text())}
                     for incident in check_review_gate()]
    except Exception as error:
        return JSONResponse(status_code=503, content={"review_required": True,
            "message": "The DNA positioning review journal could not be verified.",
            "report_delivery_error": str(error), "incidents": []})
    return {"review_required": bool(incidents), "incidents": incidents,
            "message": "DNA positioning failed an integrity check. A full positioning review is required before relying on the affected geometry." if incidents else "Native placement review gate is clear."}


class PlacementIncident(BaseModel):
    message: str
    code: str = "NATIVE_PLACEMENT_INTEGRITY"
    identity: Any = None
    field: str | None = None
    actual: Any = None
    expected: Any = None
    phase: str = "frontend-rendering"
    details: dict = Field(default_factory=dict)


def _document_id(request=None):
    from backend.api.doc_context import get_current_doc
    return ((request.headers.get("X-NADOC-Doc") or request.query_params.get("doc"))
            if request else None) or get_current_doc()


def _record(payload, request=None, *, context=None):
    result = record_failure({
        "test_id": f"runtime:{payload.get('phase', 'backend-geometry')}",
        "exception": payload["message"],
        "phase": payload.get("phase", "backend-geometry"),
        "evidence": {**payload, "request_path": request.url.path if request else None,
                     "document_id": _document_id(request),
                     **(context or {})},
        "reproduce_command": "Run python -m tools.native_placement_audit check; reproduce this request on a preserved copy of the named document.",
        "source_files": ["backend/core/native_full_placement.py", "backend/core/native_slab_placement.py",
                         "backend/core/design_geometry.py", "frontend/src/scene/helix_renderer.js", "backend/api/routes_vr.py"],
    })
    return {"incident_id": result["incident_id"], "report_path": str(result["html"]), "review_required": True}


def _quarantine_native_viewer(payload, *, event_path=None, document_id=None):
    """Latch a matching headset session even if durable report delivery failed."""
    import tempfile
    import uuid
    if event_path is None:
        from backend.api import routes_vr as vr
        from backend.api.doc_context import get_current_doc
        with vr._STATE_LOCK:
            session = vr._read_state()
            if not session or session.get("doc_id") != (document_id or get_current_doc()):
                return
            event_path = session.get("event_path")
        if not event_path:
            return
    path = Path(str(event_path) + ".placement-error")
    temporary = None
    try:
        # Unique candidates prevent two concurrent failures overwriting each
        # other's pending file. NamedTemporaryFile is private from creation.
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name + ".", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(f"NADOCVR_PLACEMENT_ERROR 1 {uuid.uuid4().hex}\n")
            stream.write(str(payload["message"]).replace("\n", " ") + "\n")
            stream.write(str(payload.get("report_path", payload.get("report_delivery_error", "Review required"))).replace("\n", " ") + "\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def record_native_placement_failure(error, *, request=None, phase="backend-geometry", event_path=None, context=None):
    """One reporting path for HTTP requests and workers outside FastAPI."""
    payload = {"code": "NATIVE_PLACEMENT_INTEGRITY", "message": str(error),
               "details": getattr(error, "details", {}), "phase": phase,
               "traceback": "".join(traceback.format_exception(error))}
    return _record_and_quarantine(payload, request=request, event_path=event_path, context=context)


def _stop_matching_native_viewer(*, event_path=None, document_id=None):
    """Stop only the verified viewer bound to this document and exact IPC path.

    The pidfd pins the checked process, so a recycled PID cannot redirect the
    signal. Do not acquire _STATE_LOCK: publication callers may already hold it.
    """
    import os
    import signal
    from backend.api import routes_vr as vr
    from backend.api.doc_context import get_current_doc
    expected_doc = document_id or get_current_doc()
    session = vr._read_state()  # Verifies /proc/PID/exe against the native binary.
    if (not session or session.get("doc_id") != expected_doc
            or (event_path is not None and session.get("event_path") != str(event_path))):
        return {"headset_stop_status": "no_matching_session"}
    pid = int(session["pid"])
    descriptor = None
    try:
        descriptor = os.pidfd_open(pid, 0)
        current = vr._read_state()
        if (not current or current.get("pid") != session["pid"] or current.get("doc_id") != expected_doc
                or current.get("event_path") != session.get("event_path")):
            return {"headset_stop_status": "session_changed"}
        arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        target = str(session.get("event_path", "")).encode()
        if not target or not any(arguments[index:index + 2] == [b"--events", target] for index in range(len(arguments) - 1)):
            raise RuntimeError("Native viewer command does not match the failed session; refusing to signal a different process.")
        signal.pidfd_send_signal(descriptor, signal.SIGKILL)
        return {"headset_stop_status": "stopped", "viewer_pid": pid}
    except ProcessLookupError:
        return {"headset_stop_status": "already_exited"}
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _deliver_native_quarantine(payload, *, event_path=None, document_id=None):
    try:
        _quarantine_native_viewer(payload, event_path=event_path, document_id=document_id)
        return {}
    except Exception as error:
        result = {"headset_quarantine_delivery_error": str(error)}
    try:
        result.update(_stop_matching_native_viewer(event_path=event_path, document_id=document_id))
    except Exception as error:
        import logging
        result.update(headset_stop_delivery_error=str(error), headset_stop_status="unrecoverable")
        logging.getLogger(__name__).critical("DNA POSITIONING FAILURE: headset quarantine and verified stop failed. "
            "Close VR immediately. Original failure: %s; delivery details: %s", payload["message"], result)
    return result


def _record_and_quarantine(payload, *, request=None, event_path=None, context=None):
    # Delivery comes first so its evidence (including an emergency stop) is in
    # the immutable report. A report-storage failure cannot bypass quarantine.
    result = {**payload, **_deliver_native_quarantine(payload, event_path=event_path, document_id=_document_id(request))}
    try:
        report = _record(result, request, context=context)
    except Exception as report_error:
        report = {"review_required": True, "report_delivery_error": str(report_error)}
    return _jsonable({**result, **report})


def require_native_placement_review_clear(*, event_path=None):
    """No new native viewer publication may bypass an unresolved review."""
    try:
        incidents = check_review_gate()
        if not incidents:
            return
        payload = {"code": "NATIVE_PLACEMENT_REVIEW_REQUIRED", "review_required": True,
                   "message": "DNA positioning review is required before starting or refreshing native VR.",
                   "incidents": incidents}
    except Exception as error:
        payload = {"code": "NATIVE_PLACEMENT_REVIEW_REQUIRED", "review_required": True,
                   "message": "The DNA positioning review journal could not be verified.",
                   "report_delivery_error": str(error)}
    payload.update(_deliver_native_quarantine(payload, event_path=event_path))
    # This is an existing incident, not a new geometry failure to duplicate.
    raise HTTPException(503, detail=_jsonable(payload))


@router.post("/design/placement-integrity-report")
def report_placement_integrity(body: PlacementIncident, request: Request):
    return _record_and_quarantine(body.model_dump(), request=request)


async def native_placement_exception_handler(request: Request, error: NativePlacementError):
    return JSONResponse(status_code=500, content={"detail": record_native_placement_failure(error, request=request)})
