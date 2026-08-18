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
    "nadoc_current_doc",
    default=DEFAULT_DOC_ID,
)

# The 2D cadnano editor draws from topology and never reads embedded 3D
# geometry, so it asks responses to omit it (saving the backend a full-design
# geometry recompute and itself a multi-MB JSON.parse of a payload it discards).
# Requests that don't send the header — the 3D view, internal callers, tests —
# resolve to False and get full geometry, so all legacy behavior is unchanged.
_skip_geometry: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "nadoc_skip_geometry",
    default=False,
)

# Display geometry is a projection of the persisted Design, not part of it.  The
# browser therefore states which projection it is currently displaying on every
# API request.  None preserves the legacy behavior for non-frontend callers.
_measured_positioning: contextvars.ContextVar[bool | None] = contextvars.ContextVar(
    "nadoc_measured_positioning",
    default=None,
)

# Revision assigned to the mutation handled by the CURRENT request, set under the
# state lock by state._bump_revision. _design_response stamps it on the response
# so the client can drop out-of-order/stale design responses (rapid-edit race).
# Reset to None per request by the middleware (below) so a read-only request never
# inherits a prior request's revision — must live HERE (not in state.py) so the
# middleware can reset it in the same context chain as the doc id.
_request_revision: contextvars.ContextVar = contextvars.ContextVar(
    "nadoc_request_revision",
    default=None,
)


def current_request_revision():
    """Revision assigned to the mutation in the current request, or None for a
    read-only request (no mutation happened)."""
    return _request_revision.get()


def set_request_revision(value: int) -> None:
    """Record the revision assigned to the current request's mutation."""
    _request_revision.set(value)


# Id of the feature-log SnapshotLogEntry (if any) created by the CURRENT
# request's mutation, set by state.mutate_with_feature_log right after it
# appends the entry. _design_response reads this as the default
# preserve_feature_log_id so a route's response never ships its own
# just-created entry with a stripped (empty) body — the client has never seen
# that entry's id before, so its cache-merge can't backfill a missing body,
# unlike an EXISTING entry. Discovered as a live gap: `mutate_with_feature_log`
# has 47+ call sites and manually threading preserve_feature_log_id through
# each one is exactly the kind of thing that gets missed once and silently
# corrupts that one route's local recovery cache. Auto-detection closes the
# whole class at once. Reset to None per request by the middleware (below).
_last_feature_log_entry_id: contextvars.ContextVar = contextvars.ContextVar(
    "nadoc_last_feature_log_entry_id",
    default=None,
)


def current_request_feature_log_entry_id():
    """Id of the feature-log entry created by the current request's mutation,
    or None if this request created no entry."""
    return _last_feature_log_entry_id.get()


def set_request_feature_log_entry_id(value: str) -> None:
    """Record the id of the feature-log entry just created by the current
    request's mutation."""
    _last_feature_log_entry_id.set(value)


# Header / query names the frontend uses to name its document.
DOC_HEADER = "x-nadoc-doc"
DOC_QUERY = "doc"
# Header the cadnano editor sets to opt out of embedded geometry in responses.
SKIP_GEOMETRY_HEADER = "x-nadoc-skip-geometry"
MEASURED_POSITIONING_HEADER = "x-nadoc-measured-positioning"


def get_current_doc() -> str:
    """The document id bound to the current request (or DEFAULT_DOC_ID)."""
    return _current_doc.get()


def should_skip_geometry() -> bool:
    """True when the current request asked responses to omit embedded geometry.

    Honored at the single ``_design_response_with_geometry`` choke point in
    crud.py, which falls back to the geometry-free ``_design_response``.
    """
    return _skip_geometry.get()


def requested_measured_positioning() -> bool | None:
    """Requested display projection, or None when the caller did not specify one."""
    return _measured_positioning.get()


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


def _extract_skip_geometry(scope) -> bool:
    """True iff the request carries a truthy ``X-NADOC-Skip-Geometry`` header."""
    for k, v in scope.get("headers", []):
        if k == SKIP_GEOMETRY_HEADER.encode("latin-1"):
            return v.decode("latin-1").strip().lower() not in ("", "0", "false")
    return False


def _extract_measured_positioning(scope) -> bool | None:
    """Parse the explicit display-projection header, if present."""
    for k, v in scope.get("headers", []):
        if k == MEASURED_POSITIONING_HEADER.encode("latin-1"):
            value = v.decode("latin-1").strip().lower()
            if value in ("1", "true"):
                return True
            if value in ("0", "false"):
                return False
    return None


class DocContextMiddleware:
    """Pure-ASGI middleware binding each request's doc id (and the
    skip-geometry flag) to ContextVars for the lifetime of the request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            doc_token = _current_doc.set(_extract_doc_id(scope))
            geo_token = _skip_geometry.set(_extract_skip_geometry(scope))
            measured_token = _measured_positioning.set(_extract_measured_positioning(scope))
            # Start each request with no recorded revision so a read-only request
            # never inherits a prior (mutating) request's value.
            rev_token = _request_revision.set(None)
            fl_entry_token = _last_feature_log_entry_id.set(None)
            try:
                await self.app(scope, receive, send)
            finally:
                _last_feature_log_entry_id.reset(fl_entry_token)
                _request_revision.reset(rev_token)
                _measured_positioning.reset(measured_token)
                _skip_geometry.reset(geo_token)
                _current_doc.reset(doc_token)
        else:
            await self.app(scope, receive, send)
