"""Bounded raw repair-source acquisition; no multipart cache or upload queue."""

import asyncio
from functools import partial
import json
from threading import Event, Lock

from fastapi import HTTPException
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.requests import ClientDisconnect

from backend.api import part_repair_source_host as host
from backend.core.part_repair_sources import MAX_UPLOAD_BYTES, parse_source_request


METADATA_HEADER = "x-nadoc-repair-source"
MAX_METADATA_BYTES = 8_192
READ_SECONDS = 15.0
_slot = Lock()  # resource admission only; document state remains in state.py


def _fail(detail, *, status=422, code="invalid_source_transport"):
    raise HTTPException(status, detail={"code": code, "detail": detail})


def _metadata(request):
    headers = request.headers.getlist(METADATA_HEADER)
    if len(headers) != 1 or len(headers[0]) > MAX_METADATA_BYTES:
        _fail("Supply exactly one bounded X-NADOC-Repair-Source JSON header.")
    # HTTP header strings decode byte-for-byte as latin-1; avoid a larger encode
    # or body allocation before this wire envelope is admitted.
    text = headers[0]
    if not text.isascii():
        _fail("Source metadata must use ASCII JSON (escape non-ASCII labels).")

    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Repeated source metadata key")
            value[key] = item
        return value

    try:
        value = json.loads(text, object_pairs_hook=unique)
        parsed = parse_source_request(value, mutation=True)
    except (ValueError, RecursionError, ValidationError) as error:
        _fail(f"Invalid source metadata: {error}")
    if parsed.source.size_bytes > MAX_UPLOAD_BYTES:
        _fail("Source exceeds the repair-upload allowance.", status=413, code="source_limit")
    if request.headers.getlist("content-type") != ["application/octet-stream"]:
        _fail("Upload original source bytes as application/octet-stream.", status=415)
    if request.headers.getlist("content-encoding") not in ([], ["identity"]):
        _fail("Compressed repair-source transport is not supported.", status=415)
    lengths = request.headers.getlist("content-length")
    if lengths:
        if (len(lengths) != 1 or not lengths[0].isascii() or not lengths[0].isdecimal()
                or len(lengths[0]) > 9):
            _fail("Content-Length must be one bounded decimal byte count.")
        length = int(lengths[0])
        if length > MAX_UPLOAD_BYTES:
            _fail("Source body exceeds the repair-upload allowance.", status=413, code="source_limit")
        if length != parsed.source.size_bytes:
            _fail("Content-Length does not match the selected source descriptor.")
    return parsed


async def _read_source(request, size):
    raw = bytearray()
    try:
        async with asyncio.timeout(READ_SECONDS):
            async for chunk in request.stream():
                if len(chunk) > size - len(raw):
                    _fail("Source body exceeds its selected descriptor.", status=413, code="source_limit")
                raw.extend(chunk)
    except TimeoutError as error:
        raise HTTPException(408, detail={"code": "source_upload_timeout",
            "detail": "Source body did not arrive within the bounded read deadline."}) from error
    except ClientDisconnect as error:
        raise HTTPException(499, detail="Source upload disconnected before publication.") from error
    if len(raw) != size:
        _fail("Source body length does not match the selected descriptor.")
    return bytes(raw)


async def _thread_call(function, *args, cancelled=None, **kwargs):
    """Do not release admission while a cancelled request still owns a worker.

    These workers do bounded metadata/hash work only. The publication callback
    also checks the local cancellation event after acquiring the state lock.
    Cancellation after the atomic commit has begun cannot undo that commit.
    """
    task = asyncio.create_task(run_in_threadpool(partial(function, *args, **kwargs)))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if cancelled is not None:
            cancelled.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        if task.done() and not task.cancelled():
            task.exception()  # retrieve a failed worker without replacing cancellation
        raise


async def upload_source(request):
    """Thin route target: independently bounded metadata + one original byte body."""
    metadata = _metadata(request)  # reject invalid metadata before admission/body read
    if not _slot.acquire(blocking=False):
        _fail("A repair-source upload is already active; retry after it finishes.",
              status=409, code="source_upload_busy")
    cancelled = Event()
    try:
        captured = await _thread_call(host.capture_source_request, metadata, mutation=True,
                                     cancelled=cancelled)
        raw = await _read_source(request, metadata.source.size_bytes)
        prepared, response = await _thread_call(host.prepare_upload, captured, raw, cancelled=cancelled)
        if await request.is_disconnected():
            _fail("Source upload disconnected before publication.", status=499, code="source_upload_cancelled")
        return await _thread_call(partial(host.publish_upload, cancelled=cancelled.is_set),
                                  captured, prepared, response, cancelled=cancelled)
    finally:
        _slot.release()
