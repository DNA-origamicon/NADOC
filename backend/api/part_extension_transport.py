"""Bounded HTTP acquisition for the five existing extension authoring routes."""

from contextvars import ContextVar
from dataclasses import dataclass
import json
from threading import Lock

from fastapi import HTTPException
from fastapi.routing import APIRoute

from backend.api import doc_context, state, part_publication_policy as policy
from backend.api.part_bounded_json import read_operation_json
from backend.api.part_group_organization_gate import require_group_edit_enabled

_input_slot = Lock()
_source = ContextVar("extension_request_source", default=None)


@dataclass(frozen=True)
class RequestSource:
    doc: str
    session: object
    session_identity: str
    design: object
    revision: int
    policy_generation: int


def require_current():
    """State-lock-owned check, also used after request-thread dispatch."""
    context = _source.get()
    if context is None:
        return
    if policy.resolve(context.doc).generation != context.policy_generation:
        raise HTTPException(409, detail={"code": "policy_changed", "message": "Construction policy changed during extension request acquisition."})
    session = state._sessions.get(context.doc)
    if (doc_context.get_current_doc() != context.doc or session is not context.session
            or session.identity != context.session_identity
            or session.design is not context.design or session.revision != context.revision):
        raise HTTPException(409, detail={"code": "source_changed", "message": "The document changed during extension request acquisition."})


class ExtensionRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            doc = doc_context.get_current_doc()
            effective = policy.require_compatibility(doc, "extension_authoring")
            with state._lock:
                session = state._sessions.get(doc)
                if session is None or session.design is None:
                    raise HTTPException(404, detail="No active design.")
                if session.design.group_organization is not None:
                    require_group_edit_enabled()
                context = RequestSource(doc, session, session.identity, session.design, session.revision, effective.generation)
            token = _source.set(context)
            try:
                # Existing single DELETE permits no body. Cache the declared
                # empty body so FastAPI cannot subsequently acquire unbounded data.
                if (request.method == "DELETE" and not request.url.path.endswith("/batch")
                        and request.headers.get("content-length") in {None, "0"}
                        and "transfer-encoding" not in request.headers
                        and "content-type" not in request.headers):
                    request._body = b""
                else:
                    value = await read_operation_json(request, prefix="extension", label="Extension edit",
                                                      slot=_input_slot, read_seconds=5.0)
                    request._body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
                with state._lock:
                    require_current()
                return await handler(request)
            finally:
                _source.reset(token)

        return bounded
