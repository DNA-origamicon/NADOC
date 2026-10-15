"""Closed, host-selected strict HTTP surface; compatibility is the default.

Compatibility requests retain their original application. Strict requests have
an exact route table, bounded JSON acquisition and no fallback. The dispatcher
owns neither a second session store nor an application lifespan. A strict default
on a dedicated agent-facing host is required to exclude compatibility documents
and global filesystem routes; a per-document binding is not authentication.
"""

import asyncio
import json
from time import monotonic

from fastapi import Depends, FastAPI
from starlette.responses import JSONResponse
from starlette.routing import compile_path

from backend.api import part_publication_policy as policy
from backend.api.doc_context import DocContextMiddleware, _extract_doc_id
from backend.api.document_identity import UnsafeDocumentIdentity, require_document_identity
from backend.api.part_strict_reads import (
    CONTEXT_KEY, StrictRequestContext, construction_policy, create_registered_empty,
    require_context, revision_metadata,
)
from backend.core.part_operation_input import MAX_OPERATION_BYTES, validate_operation_input


MAX_BODY_SECONDS = 5.0
MAX_EMPTY_BYTES = 8192
_JOBS = "/api/design/features/evaluation/jobs"
_EMPTY = "/api/design/registered-empty"
_POLICY = "/api/design/construction-policy"
_REVISION = "/api/design/revision"
_DOCUMENT_TARGET = compile_path("/api/documents/{doc_id}")[0]


def _strict_application():
    # Reuse only these exact handlers; never include the legacy feature router.
    from backend.api.routes_feature_log import (
        cancel_part_evaluation, commit_part_evaluation, get_part_evaluation, start_part_evaluation,
    )

    definitions = (
        (_EMPTY, "POST", create_registered_empty, 201, MAX_EMPTY_BYTES),
        (_POLICY, "GET", construction_policy, 200, 0),
        (_REVISION, "GET", revision_metadata, 200, 0),
        (_JOBS, "POST", start_part_evaluation, 202, MAX_OPERATION_BYTES),
        (_JOBS + "/{job_id}", "GET", get_part_evaluation, 200, 0),
        (_JOBS + "/{job_id}", "DELETE", cancel_part_evaluation, 200, 0),
        (_JOBS + "/{job_id}/commit", "POST", commit_part_evaluation, 200, 0),
    )
    app = FastAPI(openapi_url=None, docs_url=None, redoc_url=None, redirect_slashes=False)
    matches = []
    for path, method, endpoint, status, limit in definitions:
        app.add_api_route(path, endpoint, methods=[method], status_code=status,
                          dependencies=[Depends(require_context)])
        matches.append((compile_path(path)[0], method, limit))
    return DocContextMiddleware(app), tuple(matches)


def _error(status, code, detail):
    return JSONResponse({"detail": {"code": code, "detail": detail}}, status_code=status)


def _same_policy(context):
    selected = policy.resolve(context.doc_id)
    return selected.strict and selected.generation == context.policy_generation


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object keys are not admitted")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("JSON numbers must be finite")


def _json_input(body, *, evaluation):
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=_invalid_constant)
        validate_operation_input(value)
        if type(value) is not dict:
            raise ValueError("The request must be one JSON object")
    except (ValueError, RecursionError) as error:
        return _error(422, "invalid_strict_input", str(error))
    if evaluation:
        operation = value.get("operation")
        if type(operation) is not str:
            return _error(422, "invalid_strict_input", "Evaluation operation must be a string")
        if operation not in policy.STRICT_OPERATIONS:
            return _error(403, "construction_policy", "Only registered batch and verify jobs are admitted")
    return None


def _headers(scope, limit):
    """Fail before receive on unsupported media/encoding or oversized headers."""
    grouped = {}
    for name, value in scope.get("headers", ()):
        if name in {b"content-type", b"content-length", b"content-encoding", b"transfer-encoding"}:
            grouped.setdefault(name, []).append(value)
    if any(len(values) != 1 for values in grouped.values()):
        return _error(400, "invalid_strict_headers", "Duplicate body framing or media headers are not admitted")
    length = grouped.get(b"content-length", [b"0"])[0]
    if len(length) > 20 or not length.isdigit():
        return _error(400, "invalid_strict_headers", "Content-Length must be a bounded decimal byte count")
    if int(length) > limit:
        return _error(413, "strict_body_limit", "The request body exceeds the fixed route allowance")
    if not limit:
        if b"transfer-encoding" in grouped or b"content-encoding" in grouped or b"content-type" in grouped:
            return _error(415, "unsupported_strict_media", "This route accepts no request body")
        return None
    media = grouped.get(b"content-type", [b""])[0].decode("latin-1").lower().split(";")
    if media[0].strip() != "application/json" or any(
            parameter.strip() not in {"charset=utf-8", 'charset="utf-8"'} for parameter in media[1:]):
        return _error(415, "unsupported_strict_media", "This route accepts UTF-8 application/json only")
    if grouped.get(b"content-encoding", [b"identity"])[0].lower() != b"identity":
        return _error(415, "unsupported_strict_media", "Encoded request bodies are not admitted")
    return None


async def _body(receive, limit, context):
    body = bytearray()
    deadline = monotonic() + MAX_BODY_SECONDS
    while True:
        left = deadline - monotonic()
        if left <= 0:
            return None, _error(408, "strict_body_timeout", "Request body acquisition exceeded its deadline")
        try:
            message = await asyncio.wait_for(receive(), timeout=left)
        except TimeoutError:
            return None, _error(408, "strict_body_timeout", "Request body acquisition exceeded its deadline")
        if message["type"] == "http.disconnect":
            return None, None
        if monotonic() > deadline:
            return None, _error(408, "strict_body_timeout", "Request body acquisition exceeded its deadline")
        if not _same_policy(context):
            return None, _error(409, "policy_changed", "Host construction policy changed during body acquisition")
        chunk = message.get("body", b"")
        if message["type"] != "http.request" or type(chunk) is not bytes:
            return None, _error(400, "invalid_strict_body", "Invalid request body framing")
        if len(chunk) > limit - len(body):
            return None, _error(413, "strict_body_limit", "The request body exceeds the fixed route allowance")
        body.extend(chunk)
        if not message.get("more_body", False):
            return bytes(body), None


class StrictPartDispatch:
    """Wrap compatibility ASGI once; no strict request reaches its fallback."""

    def __init__(self, app):
        self.app = app
        self.strict, self.matches = _strict_application()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            # The real application's lifespan runs exactly once.
            await self.app(scope, receive, send)
            return
        doc = _extract_doc_id(scope)
        selected = policy.resolve(doc)
        path = scope.get("path", "")
        target = _DOCUMENT_TARGET.fullmatch(path)
        if target is not None and policy.resolve(target.group("doc_id")).strict:
            selected_target = True
        else:
            selected_target = False
        if not selected.strict and not selected_target:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008, "reason": "Strict part WebSockets are not admitted"})
            return
        limit = None
        for pattern, method, allowance in self.matches:
            match = pattern.fullmatch(path)
            if match is not None and method == scope.get("method"):
                if any(len(value) > 128 for value in match.groupdict().values()):
                    break
                limit = allowance
                break
        if limit is None or selected_target:
            await _error(403, "construction_policy", "This endpoint is outside the strict part route table")(scope, receive, send)
            return
        try:
            require_document_identity(doc)
        except UnsafeDocumentIdentity as error:
            await _error(422, error.code, str(error))(scope, receive, send)
            return
        error = _headers(scope, limit)
        if error is not None:
            await error(scope, receive, send)
            return
        context = StrictRequestContext(doc, selected.generation)
        if limit:
            body, error = await _body(receive, limit, context)
            if error is None and body is not None:
                error = _json_input(body, evaluation=path == _JOBS)
            if error is not None:
                await error(scope, receive, send)
                return
            if body is None:
                return  # Client disconnected; no handler ran.
            original_receive = receive
            consumed = False

            async def receive():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await original_receive()
        if not _same_policy(context):
            await _error(409, "policy_changed", "Host construction policy changed before strict dispatch")(scope, receive, send)
            return
        strict_scope = dict(scope)
        strict_scope[CONTEXT_KEY] = context
        await self.strict(strict_scope, receive, send)
