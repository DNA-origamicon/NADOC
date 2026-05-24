"""
Per-request "current document" context for multi-document support (Phase 2).

The backend can hold many documents at once, keyed by an opaque ``doc_id``.
Each request names its document via the ``X-NADOC-Doc`` header (or a ``?doc=``
query param).  A pure-ASGI middleware reads that and binds it to a ContextVar
for the lifetime of the request; ``state.py`` / ``assembly_state.py`` resolve
the active document from this ContextVar.

Why a ContextVar resolved by a *pure-ASGI* middleware (not BaseHTTPMiddleware):
contextvars set inside a Starlette ``BaseHTTPMiddleware.dispatch`` do NOT
propagate to the endpoint (Starlette runs dispatch in a separate task/context).
A pure-ASGI middleware sets the value in the same context chain, and Starlette
copies that context into the threadpool that runs sync endpoints — so the state
modules see the right ``doc_id``.

When no document is named — the entire existing test suite, single-document use,
internal callers, and the WebSocket/relax paths that don't pass a doc — the
ContextVar falls back to :data:`DEFAULT_DOC_ID`, preserving all legacy behavior.
"""

from __future__ import annotations

import contextvars
from urllib.parse import parse_qs

# The slot used when a request names no document.  Single-document clients and
# every existing test resolve here, so their behavior is unchanged.
DEFAULT_DOC_ID = "__default__"

_current_doc: contextvars.ContextVar[str] = contextvars.ContextVar(
    "nadoc_current_doc", default=DEFAULT_DOC_ID,
)

# Header / query names the frontend uses to name its document.
DOC_HEADER = "x-nadoc-doc"
DOC_QUERY = "doc"


def get_current_doc() -> str:
    """The document id bound to the current request (or DEFAULT_DOC_ID)."""
    return _current_doc.get()


def set_current_doc(doc_id: str | None):
    """Bind ``doc_id`` for the current context. Returns a reset token."""
    return _current_doc.set(doc_id or DEFAULT_DOC_ID)


def reset_current_doc(token) -> None:
    _current_doc.reset(token)


def _extract_doc_id(scope) -> str:
    """Read the doc id from the ASGI scope: ``X-NADOC-Doc`` header, else ?doc=."""
    for k, v in scope.get("headers", []):
        if k == DOC_HEADER.encode("latin-1"):
            val = v.decode("latin-1").strip()
            if val:
                return val
    qs = scope.get("query_string", b"")
    if qs:
        vals = parse_qs(qs.decode("latin-1")).get(DOC_QUERY)
        if vals and vals[0].strip():
            return vals[0].strip()
    return DEFAULT_DOC_ID


class DocContextMiddleware:
    """Pure-ASGI middleware binding each request's doc id to the ContextVar."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            token = _current_doc.set(_extract_doc_id(scope))
            try:
                await self.app(scope, receive, send)
            finally:
                _current_doc.reset(token)
        else:
            await self.app(scope, receive, send)
