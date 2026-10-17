"""Shared bounded HTTP acquisition bound to a document incarnation.

This captures ownership, not publication authority. Each registered route family
declares its policy and body reader; its owned recorder checks require_current
again after dispatch. A reset cannot rebind a held body to a replacement design.
"""

from contextvars import ContextVar
from dataclasses import dataclass
import json

from fastapi import HTTPException
from fastapi.routing import APIRoute

from backend.api import doc_context, state, part_publication_policy as policy
from backend.api.part_group_organization_gate import require_group_edit_enabled


_source = ContextVar("part_http_request_source", default=None)


@dataclass(frozen=True)
class RequestSource:
    doc: str
    session: object
    session_identity: str
    design: object
    revision: int
    policy_generation: int


def require_current():
    """Check under the state lock; direct private Python calls have no HTTP context."""
    context = _source.get()
    if context is None:
        return
    if policy.resolve(context.doc).generation != context.policy_generation:
        raise HTTPException(409, detail={"code": "policy_changed", "message": "Construction policy changed during request acquisition."})
    session = state._sessions.get(context.doc)
    if (doc_context.get_current_doc() != context.doc or session is not context.session
            or session.identity != context.session_identity
            or session.design is not context.design or session.revision != context.revision):
        raise HTTPException(409, detail={"code": "source_changed", "message": "The document changed during request acquisition."})


class SourceBoundRoute(APIRoute):
    """Abstract private route class; subclasses supply fixed admission settings."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            doc = doc_context.get_current_doc()
            effective = policy.require_compatibility(doc, self.policy_operation)
            with state._lock:
                session = state._sessions.get(doc)
                if session is None or session.design is None:
                    raise HTTPException(404, detail="No active design.")
                if session.design.group_organization is not None:
                    require_group_edit_enabled()
                context = RequestSource(doc, session, session.identity, session.design, session.revision, effective.generation)
            token = _source.set(context)
            try:
                empty_delete = (self.allow_empty_delete and request.method == "DELETE"
                    and not request.url.path.endswith("/batch")
                    and request.headers.get("content-length") in {None, "0"}
                    and "transfer-encoding" not in request.headers and "content-type" not in request.headers)
                if request.method == "GET" or empty_delete:
                    if request.method == "GET" and (request.headers.get("content-length") not in {None, "0"}
                            or "transfer-encoding" in request.headers):
                        raise HTTPException(400, detail="Historical input queries do not accept a body.")
                    request._body = b""
                else:
                    value = await self.body_reader(request, prefix=self.input_prefix, label=self.input_label,
                                                   slot=self.input_slot, read_seconds=5.0)
                    request._body = json.dumps(value, allow_nan=False, separators=(",", ":")).encode()
                with state._lock:
                    require_current()
                return await handler(request)
            finally:
                _source.reset(token)

        return bounded
