"""Private, disabled HTTP adapter for owned deformation-editor leases.

Only bounded input JSON is acquired on the event loop. Native work and explicit
response serialization use the request thread. Disconnecting an HTTP request is
not cancellation or rollback; the caller-known nonce and status endpoint resolve
that lifecycle. The strict route table deliberately does not admit this router.
"""

import asyncio
import json
from threading import Lock

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import ORJSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from backend.api import doc_context, part_publication_policy as policy
from backend.api.document_identity import UnsafeDocumentIdentity, require_document_identity
from backend.core.part_operation_input import MAX_OPERATION_BYTES, validate_operation_input


router = APIRouter()
DEFORMATION_PREVIEW_ENABLED = False
READ_SECONDS = 5.0
_input_slot = Lock()  # one nonqueued body acquisition; never held during host work
_PATH = "/design/features/deformation-preview"


def _fail(status, code, detail):
    raise HTTPException(status, detail={"code": code, "detail": detail})


def _enabled():
    if not DEFORMATION_PREVIEW_ENABLED:
        _fail(403, "preview_disabled", "The isolated deformation editor is not enabled on this host")


def _headers(request):
    for name in ("content-type", "content-length", "content-encoding", "transfer-encoding"):
        if len(request.headers.getlist(name)) > 1:
            _fail(400, "invalid_preview_transport", "Duplicate media or body framing headers are unsupported")
    media = request.headers.get("content-type", "").lower().split(";")
    if media[0].strip() != "application/json" or any(
            parameter.strip() not in {"charset=utf-8", 'charset="utf-8"'} for parameter in media[1:]):
        _fail(415, "invalid_preview_transport", "Send UTF-8 application/json")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        _fail(415, "invalid_preview_transport", "Compressed preview requests are unsupported")
    length = request.headers.get("content-length")
    if length is not None:
        if len(length) > 20 or not length.isascii() or not length.isdecimal():
            _fail(400, "invalid_preview_transport", "Content-Length must be one bounded decimal byte count")
        if int(length) > MAX_OPERATION_BYTES:
            _fail(413, "preview_request_limit", "Preview input exceeds the ordinary operation allowance")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON keys are unsupported")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("Preview input numbers must be finite")


async def _read_request(request):
    _headers(request)
    if not _input_slot.acquire(blocking=False):
        _fail(429, "preview_input_busy", "Another preview request body is being acquired")
    try:
        body = bytearray()
        try:
            async with asyncio.timeout(READ_SECONDS):
                async for chunk in request.stream():
                    if len(chunk) > MAX_OPERATION_BYTES - len(body):
                        _fail(413, "preview_request_limit", "Preview input exceeds the ordinary operation allowance")
                    body.extend(chunk)
        except TimeoutError as error:
            raise HTTPException(408, detail={"code": "preview_request_timeout",
                "detail": "Preview input did not arrive within its read deadline"}) from error
        except ClientDisconnect as error:
            raise HTTPException(499, detail={"code": "preview_request_disconnected",
                "detail": "Preview request disconnected before host work"}) from error
        try:
            value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_nonfinite)
            if type(value) is not dict:
                raise ValueError("Preview requests require a JSON object")
            validate_operation_input(value)
        except (ValueError, RecursionError) as error:
            raise HTTPException(422, detail={"code": "invalid_preview_transport", "detail": str(error)}) from error
        return value
    finally:
        _input_slot.release()


def _respond(operation, value, generation):
    _enabled()
    current = policy.require_compatibility(doc_context.get_current_doc(), "deformation_preview")
    if current.generation != generation:
        _fail(409, "policy_changed", "Construction policy changed during request acquisition")
    from backend.api import part_deformation_preview_sessions as host

    # The DTO has already bounded the whole response, including host identity.
    # Returning Response avoids FastAPI's generic coordinate traversal; only the
    # actual final JSON encoding remains, on this worker thread.
    return ORJSONResponse(getattr(host, operation)(value))


async def _dispatch(request, operation):
    _enabled()  # disabled means no body acquisition or native host import
    doc = doc_context.get_current_doc()
    selected = policy.require_compatibility(doc, "deformation_preview")
    try:
        require_document_identity(doc)
    except UnsafeDocumentIdentity as error:
        _fail(422, error.code, str(error))
    value = await _read_request(request)
    return await run_in_threadpool(_respond, operation, value, selected.generation)


@router.post(_PATH)
async def prepare(request: Request):
    return await _dispatch(request, "prepare")


@router.post(_PATH + "/evaluate")
async def evaluate(request: Request):
    return await _dispatch(request, "evaluate")


@router.post(_PATH + "/apply")
async def apply(request: Request):
    return await _dispatch(request, "apply")


@router.post(_PATH + "/cancel")
async def cancel(request: Request):
    return await _dispatch(request, "cancel")


@router.post(_PATH + "/status")
async def status(request: Request):
    return await _dispatch(request, "status")
