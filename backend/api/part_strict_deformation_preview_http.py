"""Closed strict adapter for existing preview paths; no compatibility fallback."""
from fastapi import Request
from fastapi.responses import ORJSONResponse

from backend.api import state, part_strict_geometry_http as geometry
from backend.api import part_source_bound_route as source_binding
from backend.api.part_async_work import thread_call
from backend.api.routes_part_deformation_preview import _enabled
from backend.core.part_operation_input import MAX_OPERATION_BYTES

PREFIX = '/api/design/features/deformation-preview'
PATHS = frozenset({PREFIX, *(PREFIX + '/' + action for action in ('evaluate', 'apply', 'cancel', 'status'))})


def capture_context(doc, generation):
    _enabled()
    return geometry.capture_context(doc, generation, recovering=False)


def _respond(operation, body, context):
    _enabled()
    with state._lock:
        geometry._check(context)
    captured = source_binding.RequestSource(context.doc, context.session, context.session_identity,
        context.source, context.revision, context.generation)
    token = source_binding._source.set(captured)
    try:
        from backend.api import part_deformation_preview_sessions as host
        # Cancel remains nonce-bound/catalog-only after this admission check:
        # it cannot publish or undo, and must remain callable during commit.
        # Encode bounded display/receipt on the work thread, not the event loop.
        return ORJSONResponse(getattr(host, operation)(body))
    finally:
        source_binding._source.reset(token)


async def _dispatch(operation, body, request):
    context = geometry._context(request)
    # Disconnect is not lease Cancel or publication rollback. Drain task-owned
    # work even on caller cancellation; nonce/receipt Status resolves lost replies.
    return await thread_call(_respond, operation, body, context)


async def prepare(body: dict, request: Request):
    return await _dispatch('prepare', body, request)


async def evaluate(body: dict, request: Request):
    return await _dispatch('evaluate', body, request)


async def apply(body: dict, request: Request):
    return await _dispatch('apply', body, request)


async def cancel(body: dict, request: Request):
    return await _dispatch('cancel', body, request)


async def status(body: dict, request: Request):
    return await _dispatch('status', body, request)


def definitions():
    return tuple((path, 'POST', handler, 200, MAX_OPERATION_BYTES) for path, handler in (
        (PREFIX, prepare), (PREFIX + '/evaluate', evaluate), (PREFIX + '/apply', apply),
        (PREFIX + '/cancel', cancel), (PREFIX + '/status', status)))
