"""One bounded UTF-8 operation-body reader for explicitly admitted part routes.

Callers own policy/feature admission and a nonqueued acquisition slot. This
reader does not access a document or grant publication authority.
"""

import asyncio
import json

from fastapi import HTTPException
from starlette.requests import ClientDisconnect

from backend.core.part_operation_input import MAX_OPERATION_BYTES, validate_operation_input


def _fail(status, code, detail):
    raise HTTPException(status, detail={"code": code, "detail": detail})


def _headers(request, prefix, label):
    invalid = f"invalid_{prefix}_transport"
    for name in ("content-type", "content-length", "content-encoding", "transfer-encoding"):
        if len(request.headers.getlist(name)) > 1:
            _fail(400, invalid, "Duplicate media or body framing headers are unsupported")
    media = request.headers.get("content-type", "").lower().split(";")
    if media[0].strip() != "application/json" or any(
            parameter.strip() not in {"charset=utf-8", 'charset="utf-8"'} for parameter in media[1:]):
        _fail(415, invalid, "Send UTF-8 application/json")
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        _fail(415, invalid, f"Compressed {label.lower()} requests are unsupported")
    length = request.headers.get("content-length")
    if length is not None:
        if len(length) > 20 or not length.isascii() or not length.isdecimal():
            _fail(400, invalid, "Content-Length must be one bounded decimal byte count")
        if int(length) > MAX_OPERATION_BYTES:
            _fail(413, f"{prefix}_request_limit", f"{label} input exceeds the ordinary operation allowance")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Repeated JSON keys are unsupported")
        result[key] = value
    return result


async def read_operation_json(request, *, prefix, label, slot, read_seconds):
    """Retain at most the ordinary operation byte allowance, then validate it."""
    _headers(request, prefix, label)
    if not slot.acquire(blocking=False):
        _fail(429, f"{prefix}_input_busy", f"Another {label.lower()} request body is being acquired")
    try:
        body = bytearray()
        try:
            async with asyncio.timeout(read_seconds):
                async for chunk in request.stream():
                    if len(chunk) > MAX_OPERATION_BYTES - len(body):
                        _fail(413, f"{prefix}_request_limit", f"{label} input exceeds the ordinary operation allowance")
                    body.extend(chunk)
        except TimeoutError as error:
            raise HTTPException(408, detail={"code": f"{prefix}_request_timeout",
                "detail": f"{label} input did not arrive within its read deadline"}) from error
        except ClientDisconnect as error:
            raise HTTPException(499, detail={"code": f"{prefix}_request_disconnected",
                "detail": f"{label} request disconnected before host work"}) from error

        def nonfinite(_value):
            raise ValueError(f"{label} input numbers must be finite")

        try:
            value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique, parse_constant=nonfinite)
            if type(value) is not dict:
                raise ValueError(f"{label} requests require a JSON object")
            validate_operation_input(value)
        except (ValueError, RecursionError) as error:
            raise HTTPException(422, detail={"code": f"invalid_{prefix}_transport", "detail": str(error)}) from error
        return value
    finally:
        slot.release()
