"""Gated geometry HTTP adapters with source ownership before body acquisition."""

import asyncio
from dataclasses import dataclass
from functools import partial
from threading import Event
from typing import Literal

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from backend.api import state, session_cache, part_publication_policy as policy
from backend.api import part_immutable_geometry_publication as publication
from backend.api import part_immutable_geometry_host as host
from backend.api.part_async_work import thread_call
from backend.api.part_immutable_recovery_inputs import RestoreRequest
from backend.api.part_immutable_persistence import PersistenceCapture, StrictPersistence
from backend.api.part_immutable_storage import require_empty_session
from backend.api.part_strict_reads import require_context, EmptyPartRequest
from backend.core.part_command_errors import CommandContractError

PREFIX = '/api/design/geometry-history'
CONTEXT_KEY = 'nadoc.strict_geometry_context'


@dataclass(frozen=True)
class GeometryContext:
    doc: str
    generation: int
    session: object
    source: object
    revision: int
    session_identity: str | None


def capture_context(doc, generation, *, recovering):
    """Called by the strict dispatcher before reading any geometry body."""
    with state._lock:
        current = publication.require_policy(doc_id=doc)
        if current.generation != generation:
            raise HTTPException(409, detail={'code': 'policy_changed'})
        session = state._sessions.get(doc)
        if recovering:
            if session is not None:
                require_empty_session(session)
        elif session is None or session.design is None:
            raise HTTPException(404, detail={'code': 'no_active_geometry'})
        else:
            publication.source_metadata(session.design)
        return GeometryContext(doc, generation, session, session.design if session else None,
            session.revision if session else 0, session.identity if session else None)


def _check(context):
    publication.require_policy(doc_id=context.doc)
    session = state._sessions.get(context.doc)
    if (policy.resolve(context.doc).generation != context.generation
            or session is not context.session
            or (session is not None and (session.identity != context.session_identity
                or session.design is not context.source or session.revision != context.revision))):
        raise HTTPException(409, detail={'code': 'source_changed',
            'detail': 'The document changed during request acquisition'})


def _context(request):
    selected, _ = require_context(request)
    context = request.scope.get(CONTEXT_KEY)
    if type(context) is not GeometryContext or context.doc != selected.doc_id:
        raise HTTPException(403, detail={'code': 'geometry_request_context'})
    with state._lock:
        _check(context)
    return context


class SourceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_design_id: StrictStr = Field(min_length=1, max_length=1024)
    expected_revision: StrictInt = Field(ge=0)


ExtrusionKind = Literal['bundle-create', 'extrude-segment', 'extrude-continuation',
    'extrude-deformed-continuation', 'extrude-frame', 'circle-segment', 'overhang-extrude']


class EditRequest(SourceRequest):
    expected_feature_id: StrictStr = Field(min_length=1, max_length=512)
    expected_kind: ExtrusionKind
    params: dict


class AppendRequest(SourceRequest):
    kind: ExtrusionKind
    params: dict


def create(body: EmptyPartRequest, request: Request):
    from backend.api.part_immutable_creation import create_durable_geometry_empty
    context = _context(request)
    candidate, revision = create_durable_geometry_empty(body.name, body.lattice_type,
        expected_policy_generation=context.generation, expected_empty_session=context.session)
    metadata = publication.source_metadata(candidate)
    return {'status': 'created', 'doc_id': context.doc, 'design_id': metadata.design_id,
            'revision': revision, 'name': metadata.name, 'lattice_type': metadata.lattice_type,
            'recipe_root': {'kind': 'empty', 'version': 1}}


def restore(body: RestoreRequest, request: Request):
    from backend.api.part_immutable_recovery import start_geometry
    context = _context(request)
    return start_geometry(body, expected_policy_generation=context.generation,
                          expected_empty_session=context.session)


async def edit(index: int, body: EditRequest, request: Request):
    return await _change(request, host.edit, index, body.params, expected_kind=body.expected_kind,
        expected_feature_id=body.expected_feature_id, expected_design_id=body.expected_design_id,
        expected_revision=body.expected_revision)


async def append(body: AppendRequest, request: Request):
    return await _change(request, host.append, body.kind, body.params,
        expected_design_id=body.expected_design_id, expected_revision=body.expected_revision)


async def _change(request, function, *args, **kwargs):
    context = _context(request)
    cancelled = Event()
    from backend.api.part_recipe_file_transport import _watch_disconnect
    watcher = asyncio.create_task(_watch_disconnect(request, cancelled))
    try:
        work = partial(function, *args, **kwargs, cancelled=cancelled,
            expected_source=context.source, expected_session_identity=context.session_identity)
        return await thread_call(work, cancelled=cancelled)
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def history(action: Literal['undo', 'redo'], body: SourceRequest, request: Request):
    context = _context(request)
    return host.history(action, **body.model_dump(), expected_source=context.source,
                        expected_session_identity=context.session_identity)


def save(body: SourceRequest, request: Request):
    context = _context(request)
    with state._lock:
        _check(context)
        metadata = publication.source_metadata(context.source)
        if body.expected_design_id != metadata.design_id or body.expected_revision != context.revision:
            raise HTTPException(409, detail={'code': 'source_changed'})
        owner = session_cache._strict_persistence
        if type(owner) is not StrictPersistence:
            raise HTTPException(503, detail={'code': 'strict_cache_unavailable'})
        capture = PersistenceCapture(context.doc, context.session_identity, context.revision, context.source)
    try:
        written = owner.write_capture(capture)
    except CommandContractError as error:
        raise HTTPException(409, detail=error.as_issue()) from error
    with state._lock:
        session = state._sessions.get(context.doc)
        current = (publication.ENABLED is True and session_cache._strict_persistence is owner
            and policy.resolve(context.doc).generation == context.generation
            and session is context.session and session.design is context.source
            and session.revision == context.revision and written == context.revision)
    return {'design_id': metadata.design_id, 'saved_revision': written,
            'requested_revision': context.revision, 'current': current}


def definitions():
    from backend.core.part_operation_input import MAX_OPERATION_BYTES
    return (
        (PREFIX + '/empty', 'POST', create, 201, 8192),
        (PREFIX + '/recovery/jobs', 'POST', restore, 202, 8192),
        (PREFIX + '/features', 'POST', append, 200, MAX_OPERATION_BYTES),
        (PREFIX + '/features/{index}/edit', 'POST', edit, 200, MAX_OPERATION_BYTES),
        (PREFIX + '/history/{action}', 'POST', history, 200, 8192),
        (PREFIX + '/save', 'POST', save, 200, 8192),
    )
