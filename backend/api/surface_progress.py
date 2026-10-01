"""Bounded, document-scoped ephemeral progress for synchronous surface requests."""

from collections import OrderedDict
from threading import Lock
from time import monotonic
from urllib.parse import parse_qs
import re

from fastapi import APIRouter, HTTPException
from starlette.responses import JSONResponse
from backend.api.doc_context import get_current_doc
from backend.core.surface_progress import reporting, SurfaceCancelled

router = APIRouter()
_records = OrderedDict()
_lock = Lock()
_TTL = 600
_CAP = 256
_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")


def _prune():
    now = monotonic()
    for key in list(_records):
        if (
            _records[key]["value"]["state"] != "running"
            and now - _records[key]["updated"] > _TTL
        ):
            del _records[key]


def snapshot(doc, request_id):
    with _lock:
        _prune()
        entry = _records.get((doc, request_id))
        return dict(entry["value"]) if entry else None


@router.get("/surface-progress/{request_id}")
async def get_surface_progress(request_id: str):
    value = snapshot(get_current_doc(), request_id)
    if value is None:
        raise HTTPException(404, "Surface request not started or expired")
    return JSONResponse(value, headers={"Cache-Control": "no-store"})


@router.post("/surface-progress/{request_id}/cancel")
async def cancel_surface_progress(request_id: str):
    if not _ID.fullmatch(request_id):
        raise HTTPException(422, "Invalid surface request")
    key = (get_current_doc(), request_id)
    with _lock:
        _prune()
        entry = _records.get(key)
        if entry is None:
            # Cancellation can overtake the mesh request on another connection.
            if len(_records) >= _CAP:
                raise HTTPException(429, "Too many surface requests")
            entry = {"updated": monotonic(), "value": {"state": "cancelled"}}
            _records[key] = entry
        entry["cancelled"] = True
        entry["updated"] = monotonic()
    return {"cancelled": True}


class SurfaceProgressMiddleware:
    """Pure ASGI preserves the reporter across Starlette's worker-thread boundary."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        headers = dict(scope.get("headers", []))
        request_id = headers.get(b"x-nadoc-surface-progress", b"").decode(
            "ascii", "ignore"
        )
        path = scope.get("path", "")
        if (
            scope["type"] != "http"
            or not _ID.fullmatch(request_id)
            or "surface" not in path
        ):
            return await self.app(scope, receive, send)
        query = parse_qs(scope.get("query_string", b"").decode())
        doc = (
            headers.get(b"x-nadoc-doc", b"").decode()
            or query.get("doc", ["__default__"])[0]
        )
        key = (doc, request_id)
        with _lock:
            _prune()
            cancelled = _records.get(key, {}).get("cancelled", False)
            duplicate = key in _records and _records[key]["value"]["state"] == "running"
            if len(_records) >= _CAP:
                finished = next(
                    (
                        k
                        for k, v in _records.items()
                        if v["value"]["state"] != "running"
                    ),
                    None,
                )
                if finished is not None:
                    del _records[finished]
            full = len(_records) >= _CAP
            if not cancelled and not duplicate and not full:
                _records[key] = {
                    "updated": monotonic(),
                    "value": {
                        "state": "running",
                        "stage": "Preparing atoms",
                        "done": None,
                        "total": None,
                        "strand": None,
                    },
                }
        if cancelled:
            return await JSONResponse(
                {"detail": "Surface computation cancelled"}, status_code=499
            )(scope, receive, send)
        if duplicate or full:
            return await JSONResponse(
                {
                    "detail": "Surface progress request already active"
                    if duplicate
                    else "Too many active surface requests"
                },
                status_code=409 if duplicate else 429,
            )(scope, receive, send)

        def update(value):
            with _lock:
                entry = _records.get(key)
                if entry:
                    entry["updated"] = monotonic()
                    entry["value"].update(value)

        def checkpoint(value):
            with _lock:
                cancelled = _records.get(key, {}).get("cancelled", False)
            if cancelled:
                raise SurfaceCancelled()
            update(value)

        status = 500

        async def forward(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        failed = False
        cancelled = False
        try:
            with reporting(checkpoint):
                await self.app(scope, receive, forward)
        except SurfaceCancelled:
            cancelled = True
            await JSONResponse(
                {"detail": "Surface computation cancelled"}, status_code=499
            )(scope, receive, send)
        except BaseException:
            failed = True
            raise
        finally:
            update(
                {
                    "state": "cancelled"
                    if cancelled
                    else "complete"
                    if not failed and status < 400
                    else "error",
                    "stage": "Surface computation cancelled"
                    if cancelled
                    else "Surface ready"
                    if not failed and status < 400
                    else "Surface computation failed",
                    "done": None,
                    "total": None,
                    "strand": None,
                }
            )
