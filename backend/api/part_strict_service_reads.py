"""Closed observational status reads; no Design materialization or mutation authority."""
from fastapi import HTTPException, Request
from starlette.responses import JSONResponse

from backend.api import state
from backend.api.part_async_work import thread_call
from backend.api.part_strict_reads import require_context
from backend.core.service_status_io import StatusReader, StatusReadLimit


def capture(request):
    if set(request.query_params) - {'doc'} or any(
            len(request.query_params.getlist(k)) != 1 for k in request.query_params):
        raise HTTPException(422, detail={'code': 'unsupported_status_query'})
    context, _ = require_context(request)
    with state._lock:
        session = state._sessions.get(context.doc_id)
        return context, session, session.identity if session else None


SERVICE_MAX_NODES = 200_000
SERVICE_MAX_BYTES = 2_000_000


def response(request, captured, result):
    context, session, identity = captured
    # Apply the existing bounded display JSON node/byte contract before encoding.
    from backend.api.part_deformation_preview_dto import _bounded
    from backend.core.part_command_errors import CommandContractError
    try:
        # Service reads keep the original display wire allowance; the larger
        # deformation-preview allowance (sized for whole parts) does not apply.
        result = _bounded(result, max_nodes=SERVICE_MAX_NODES, max_bytes=SERVICE_MAX_BYTES)
    except CommandContractError as error:
        raise HTTPException(413, detail={'code': error.code}) from error
    encoded = JSONResponse(result)
    require_context(request)
    with state._lock:
        current = state._sessions.get(context.doc_id)
        if current is not session or (current is not None and current.identity != identity):
            raise HTTPException(409, detail={'code': 'status_session_changed'})
    return encoded


async def references(request: Request):
    captured = capture(request)
    from backend.api.vr_references import read_references
    try:
        result = await thread_call(read_references, request, reader=StatusReader())
    except StatusReadLimit as error:
        raise HTTPException(413, detail={'code': 'status_read_limit'}) from error
    return response(request, captured, result)


async def peers(request: Request):
    captured = capture(request)
    from backend.api.routes_project_collaboration import _workspace
    from backend.core.collaboration_status import peer_statuses
    try:
        result = await peer_statuses(_workspace(), read_only=True)
    except StatusReadLimit as error:
        raise HTTPException(413, detail={'code': 'status_read_limit'}) from error
    return response(request, captured, result)


def definitions():
    from backend.api.part_strict_activity_reads import active_jobs
    return (('/api/jobs/active', 'GET', active_jobs, 200, 0),
            ('/api/vr/references', 'GET', references, 200, 0),
            ('/api/collaboration/peers/status', 'GET', peers, 200, 0))
