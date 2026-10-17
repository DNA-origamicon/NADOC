"""One request-owned saved-recipe worker; no retained jobs or document writes."""

import asyncio
from functools import partial
import json
import struct
from threading import Event
from time import monotonic

from fastapi import HTTPException
from starlette.requests import ClientDisconnect
from starlette.responses import Response

from backend.api import part_publication_policy as policy
from backend.api.doc_context import get_current_doc
from backend.api.part_async_work import thread_call
from backend.api.part_history_verification import _slot
from backend.api.part_recipe_file_worker import RecipeFileWorker, parse_operation
from backend.api.part_verification_worker import WorkerLimit, _result_bytes, failure
from backend.core.part_operation_input import MAX_OPERATION_BYTES
from backend.core.part_recipe_file import MAX_FILE_BYTES


READ_SECONDS = 15.0
TOTAL_SECONDS = 180.0
POLL_SECONDS = 0.05
MAX_FRAME_BYTES = 4 + MAX_OPERATION_BYTES + MAX_FILE_BYTES


def _fail(status, code, detail):
    raise HTTPException(status, detail={"code": code, "detail": detail})


def _headers(request):
    if request.headers.getlist("content-type") != ["application/octet-stream"]:
        _fail(415, "invalid_recovery_media", "Send the original file in an uncompressed recovery frame")
    if request.headers.getlist("content-encoding") not in ([], ["identity"]):
        _fail(415, "invalid_recovery_media", "Encoded recovery uploads are not supported")
    lengths = request.headers.getlist("content-length")
    transfers = request.headers.getlist("transfer-encoding")
    if len(transfers) > 1 or (transfers and lengths):
        _fail(400, "invalid_recovery_headers", "Ambiguous request framing")
    if transfers not in ([], ["chunked"]):
        _fail(400, "invalid_recovery_headers", "Unsupported transfer encoding")
    if not lengths:
        return None
    if (len(lengths) != 1 or len(lengths[0]) > 9 or not lengths[0].isascii()
            or not lengths[0].isdecimal()):
        _fail(400, "invalid_recovery_headers", "Content-Length must be one bounded byte count")
    size = int(lengths[0])
    if size > MAX_FRAME_BYTES:
        _fail(413, "recovery_input_limit", "Recovery frame exceeds its byte allowance")
    return size


async def _read_frame(request, length, deadline):
    data = bytearray()
    header_size = None
    try:
        async with asyncio.timeout(min(READ_SECONDS, max(0, deadline - monotonic()))):
            async for chunk in request.stream():
                if type(chunk) is not bytes:
                    _fail(400, "invalid_recovery_frame", "Recovery frames require byte chunks")
                if len(chunk) > MAX_FRAME_BYTES - len(data):
                    _fail(413, "recovery_input_limit", "Recovery frame exceeds its byte allowance")
                data.extend(chunk)
                if header_size is None and len(data) >= 4:
                    header_size = struct.unpack_from("!I", data)[0]
                    if header_size == 0:
                        _fail(400, "invalid_recovery_frame", "Recovery metadata is empty")
                    if header_size > MAX_OPERATION_BYTES:
                        _fail(413, "recovery_input_limit", "Recovery metadata exceeds its byte allowance")
                if header_size is not None and len(data) > 4 + header_size + MAX_FILE_BYTES:
                    _fail(413, "recovery_input_limit", "Original file exceeds the recovery byte allowance")
    except TimeoutError as error:
        raise HTTPException(408, detail={"code": "recovery_upload_timeout",
            "detail": "Recovery upload exceeded its read deadline"}) from error
    except ClientDisconnect as error:
        raise HTTPException(499, detail={"code": "recovery_cancelled",
            "detail": "Recovery upload disconnected"}) from error
    if length is not None and len(data) != length:
        _fail(400, "invalid_recovery_frame", "Recovery upload length does not match its header")
    if header_size is None or len(data) <= 4 + header_size:
        _fail(400, "invalid_recovery_frame", "Recovery frame is incomplete or the original file is empty")
    return bytes(data[4 + header_size:]), bytes(data[4:4 + header_size])


def _parse_header(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate recovery metadata keys")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("Recovery metadata numbers must be finite")

    try:
        return parse_operation(json.loads(raw.decode("utf-8"), object_pairs_hook=unique,
                                          parse_constant=constant))
    except (ValueError, TypeError, RecursionError) as error:
        raise HTTPException(400, detail={"code": "invalid_recovery_request",
            "detail": "Recovery metadata does not match the supported request schema"}) from error


class _Stopped(Exception):
    pass


def _close_worker(worker):
    """Retain admission until both the child and its buffers are released."""
    error = None
    while True:
        try:
            worker.close()
            return error
        except BaseException as caught:
            # Death alone does not establish shared-memory close/unlink. Never
            # admit another allocation while cleanup is still failing, including
            # repeated caller cancellation. Report the first failure if recovery
            # later succeeds; do not publish a candidate from this attempt.
            if error is None:
                error = failure("worker_cleanup_error", caught)
            Event().wait(POLL_SECONDS)


def _evaluate(raw, operation, cancelled, deadline, policy_check):
    """Blocking supervisor: all process work, decode and validation stay here."""
    worker = None

    def check():
        if cancelled.is_set():
            raise _Stopped("cancelled")
        if monotonic() >= deadline:
            raise _Stopped("time_limit")
        policy_check()

    try:
        check()
        worker = RecipeFileWorker(raw, operation)
        check()
        worker.start()
        while True:
            check()
            ready = worker.wait(min(POLL_SECONDS, max(0, deadline - monotonic())))
            check()
            if ready or (not worker.is_alive() and worker.wait(0)):
                encoded = worker.response_bytes()
                break
            if not worker.is_alive():
                encoded = _result_bytes(failure("worker_exited"))
                break
    except _Stopped as error:
        encoded = _result_bytes(failure(str(error)))
    except WorkerLimit as error:
        encoded = _result_bytes(failure("worker_input_limit", error))
    except HTTPException:
        raise
    except Exception as error:
        encoded = _result_bytes(failure("recovery_worker_error", error))
    finally:
        if worker is not None:
            cleanup_error = _close_worker(worker)
            if cleanup_error is not None:
                encoded = _result_bytes(cleanup_error)
    try:
        check()
    except _Stopped as error:
        encoded = _result_bytes(failure(str(error)))
    return encoded


async def _watch_disconnect(request, cancelled, stopped):
    """Stop explicitly: receive cancellation scopes can consume task.cancel()."""
    try:
        while not stopped.is_set():
            if await request.is_disconnected():
                cancelled.set()
                return
            await asyncio.sleep(POLL_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception:
        cancelled.set()


class _OwnedResponse(Response):
    """Keep one retained response admitted until its final ASGI send returns."""

    def __init__(self, encoded, slot, deadline, policy_check):
        # GZipMiddleware otherwise compresses this bounded but potentially large
        # envelope synchronously on the event loop. Preserve the child's bytes.
        super().__init__(encoded, media_type="application/json", headers={
            "Cache-Control": "no-store", "Content-Encoding": "identity"})
        self._slot = slot
        self._deadline = deadline
        self._policy_check = policy_check

    async def __call__(self, scope, receive, send):
        try:
            self._policy_check()
            if monotonic() >= self._deadline:
                _fail(408, "recovery_timeout", "Recovery exceeded its response deadline")
            async with asyncio.timeout(max(0, self._deadline - monotonic())):
                await super().__call__(scope, receive, send)
        finally:
            self.body = b""
            if self._slot is not None:
                self._slot.release()
                self._slot = None


async def recover_file(request):
    """Acquire original bytes, evaluate privately, return an owned data response."""
    doc = get_current_doc()
    admitted_policy = policy.require_compatibility(doc, "saved_recipe_recovery")
    length = _headers(request)
    if not _slot.acquire(blocking=False):
        _fail(429, "part_worker_busy", "A part history operation is active; retry after it finishes")
    deadline = monotonic() + TOTAL_SECONDS
    cancelled, stopped, transferred = Event(), Event(), False

    def policy_check():
        current = policy.resolve(doc)
        if current.strict or current.generation != admitted_policy.generation:
            _fail(409, "policy_changed", "Host construction policy changed during recovery")

    try:
        raw, header = await _read_frame(request, length, deadline)
        monitor = asyncio.create_task(_watch_disconnect(request, cancelled, stopped))
        try:
            operation = await thread_call(_parse_header, header, cancelled=cancelled)
            encoded = await thread_call(partial(_evaluate, raw, operation, cancelled, deadline, policy_check),
                                        cancelled=cancelled)
            if cancelled.is_set() or await request.is_disconnected():
                _fail(499, "recovery_cancelled", "Recovery request disconnected")
            policy_check()
        finally:
            stopped.set()
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        response = _OwnedResponse(encoded, _slot, deadline, policy_check)
        transferred = True
        return response
    finally:
        if not transferred:
            cancelled.set()
            _slot.release()
