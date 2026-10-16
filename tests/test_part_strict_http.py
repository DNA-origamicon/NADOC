"""The closed strict app never delegates rejected requests or live aliases."""

import asyncio
import json
import threading
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import part_publication_policy as policy, part_strict_http as strict, state
from backend.api.doc_context import DocContextMiddleware, get_current_doc, reset_current_doc, set_current_doc


JOBS = "/api/design/features/evaluation/jobs"
EMPTY = "/api/design/registered-empty"
REVISION = "/api/design/revision"
POLICY = "/api/design/construction-policy"


@pytest.fixture
def documents():
    previous = policy.current_configuration()
    doc, other = f"__strict_http__{uuid4()}", f"__compat_http__{uuid4()}"
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(
        document_modes={doc: "registered_only"}))
    token = set_current_doc(doc)
    try:
        yield doc, other
    finally:
        state.configure_part_publication_policy(previous)
        state.drop_doc(doc)
        state.drop_doc(other)
        reset_current_doc(token)


def scope(doc, path, method="POST", headers=(), *, query=b"", kind="http"):
    return {"type": kind, "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "root_path": "", "query_string": query,
        "headers": ([(b"x-nadoc-doc", doc.encode())] if doc is not None else []) + list(headers),
        "client": ("test", 1), "server": ("test", 80)}


def invoke(app, request, *, messages=None, receive=None):
    sent, reads = [], []
    pending = iter(messages or [])

    async def receive_default():
        reads.append(True)
        try:
            return next(pending)
        except StopIteration:
            pytest.fail("Request body was acquired without admission")

    async def send(message):
        sent.append(message)

    asyncio.run(app(request, receive or receive_default, send))
    return sent, reads


def response(sent):
    start = next(message for message in sent if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in sent if message["type"] == "http.response.body")
    return start["status"], json.loads(body)


async def forbidden_app(request, receive, send):
    if request["type"] == "lifespan":
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return
    pytest.fail("Strict request reached compatibility fallback")


@pytest.mark.parametrize("path,method", [
    ("/api/design", "POST"), ("/api/design", "GET"),
    ("/api/design/features/seek", "POST"), ("/api/design/import", "POST"),
    ("/api/fs/mkdir", "POST"), ("/api/design/geometry", "GET"),
    ("/api/documents/another", "DELETE"), ("/openapi.json", "GET"),
    ("/docs", "GET"), (REVISION, "HEAD"), (EMPTY, "OPTIONS"), (JOBS + "/", "POST"),
])
def test_unlisted_routes_never_read_body_or_fall_back(documents, path, method):
    doc, _other = documents
    sent, reads = invoke(strict.StrictPartDispatch(forbidden_app), scope(doc, path, method,
        headers=[(b"content-type", b"multipart/form-data; boundary=never-read")]))
    assert response(sent)[0] == 403 and not reads
    assert doc not in state._sessions


def test_websocket_refused_without_accept_receive_or_fallback(documents):
    doc, _other = documents
    sent, reads = invoke(strict.StrictPartDispatch(forbidden_app), scope(doc, "/ws", kind="websocket"))
    assert sent[0]["type"] == "websocket.close" and sent[0]["code"] == 1008 and not reads


def test_compatibility_and_lifespan_delegate_once_unchanged(documents):
    _doc, other = documents
    calls = []

    async def original(request, receive, send):
        calls.append(request)

    app = strict.StrictPartDispatch(original)
    legacy = scope(other, "/arbitrary-compatibility", headers=[(b"content-type", b"unknown/type")])
    assert invoke(app, legacy) == ([], [])
    lifespan = {"type": "lifespan"}
    assert invoke(app, lifespan) == ([], [])
    assert calls[0] is legacy and calls[1] is lifespan


@pytest.mark.parametrize("headers,query,expected", [
    ([(b"x-nadoc-doc", b" {strict} "), (b"x-nadoc-doc", b"{compat}")], b"doc={compat}", "strict"),
    ([(b"x-nadoc-doc", b" "), (b"x-nadoc-doc", b"{strict}")], b"doc={compat}", "strict"),
    ([(b"x-nadoc-doc", b"{compat}"), (b"x-nadoc-doc", b"{strict}")], b"doc={strict}", "compat"),
    ([], b"doc={strict}&doc={compat}", "strict"),
    ([], b"doc={compat}&doc={strict}", "compat"),
])
def test_document_resolution_is_exactly_the_existing_header_query_contract(documents, headers, query, expected):
    doc, other = documents

    def replace(value):
        return value.replace(b"{strict}", doc.encode()).replace(b"{compat}", other.encode())

    original = FastAPI()

    @original.get(REVISION)
    def legacy():
        return {"doc_id": get_current_doc(), "legacy": True}

    app = strict.StrictPartDispatch(DocContextMiddleware(original))
    sent, reads = invoke(app, scope(None, REVISION, "GET",
        headers=[(key, replace(value)) for key, value in headers], query=replace(query)))
    status, result = response(sent)
    assert status == 200 and result["doc_id"] == (doc if expected == "strict" else other)
    assert result.get("legacy", False) == (expected == "compat") and not reads
    assert get_current_doc() == doc


def test_query_decoding_and_client_authority_flags_cannot_downgrade_strict_host(documents):
    doc, _other = documents
    request = scope(None, "/api/design/save", headers=[(b"x-nadoc-policy", b"compatibility"),
        (b"x-nadoc-agent", b"human")], query=urlencode({"doc": f" {doc} ", "strict": "false"}).encode())
    assert response(invoke(strict.StrictPartDispatch(forbidden_app), request)[0])[0] == 403


def test_default_strict_binding_survives_unselected_and_new_document_contexts(documents):
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    for doc in (None, "new-unregistered-doc"):
        assert response(invoke(strict.StrictPartDispatch(forbidden_app), scope(doc, "/api/fs/mkdir"))[0])[0] == 403


def test_compatibility_context_cannot_close_a_strict_path_target(documents):
    doc, other = documents
    source = state.create_empty_part("Protected")
    from backend.api.documents import router

    original = FastAPI()
    original.include_router(router, prefix="/api")
    original.add_middleware(DocContextMiddleware)
    app = strict.StrictPartDispatch(original)
    with TestClient(app) as client:
        denied = client.delete(f"/api/documents/{doc}", headers={"X-NADOC-Doc": other})
        allowed = client.delete(f"/api/documents/{other}", headers={"X-NADOC-Doc": other})
    assert denied.status_code == 403 and allowed.status_code == 200
    assert state.peek_design(doc) is source


@pytest.mark.parametrize("headers,status", [
    ([(b"content-type", b"multipart/form-data")], 415),
    ([(b"content-type", b"application/octet-stream")], 415),
    ([], 415),
    ([(b"content-type", b"application/json; charset=utf-16")], 415),
    ([(b"content-type", b"application/json"), (b"content-encoding", b"gzip")], 415),
    ([(b"content-type", b"application/json"), (b"content-length", b"256001")], 413),
    ([(b"content-type", b"application/json"), (b"content-length", b"1"), (b"content-length", b"2")], 400),
    ([(b"content-type", b"application/json"), (b"content-length", b"-1")], 400),
])
def test_known_json_route_refuses_unsupported_media_before_body(documents, headers, status):
    doc, _other = documents
    sent, reads = invoke(strict.StrictPartDispatch(forbidden_app), scope(doc, JOBS, headers=headers))
    assert response(sent)[0] == status and not reads


@pytest.mark.parametrize("path,method", [(REVISION, "GET"), (JOBS + "/job", "DELETE"), (JOBS + "/job/commit", "POST")])
def test_bodyless_routes_reject_declared_bodies_before_read(documents, path, method):
    doc, _other = documents
    sent, reads = invoke(strict.StrictPartDispatch(forbidden_app), scope(doc, path, method,
        headers=[(b"content-length", b"1")]))
    assert response(sent)[0] == 413 and not reads


def test_chunked_limit_enforced_without_a_length_header(documents):
    doc, _other = documents
    app = strict.StrictPartDispatch(forbidden_app)
    sent, reads = invoke(app, scope(doc, JOBS, headers=[(b"content-type", b"application/json")]), messages=[
        {"type": "http.request", "body": b" " * 128_000, "more_body": True},
        {"type": "http.request", "body": b" " * 128_001, "more_body": True}])
    assert response(sent)[0] == 413 and len(reads) == 2


@pytest.mark.parametrize("body,status", [
    (b'{"operation":"edit"}', 403), (b'{"operation":"append"}', 403),
    (b'{"operation":"verify","operation":"batch"}', 422), (b'[]', 422),
    (b'{"operation":[]}', 422), (b'{"operation":{}}', 422),
    (b'{"operation":"verify","params":NaN}', 422), (b'\xff', 422),
    (b'[' * 1000 + b']' * 1000, 422),
])
def test_json_and_operation_admission_precede_shared_handler(documents, monkeypatch, body, status):
    from backend.api import part_evaluation_jobs as jobs

    monkeypatch.setattr(jobs, "start", lambda *_a, **_k: pytest.fail("Unadmitted operation reached shared jobs"))
    doc, _other = documents
    sent, _reads = invoke(strict.StrictPartDispatch(forbidden_app),
        scope(doc, JOBS, headers=[(b"content-type", b"application/json")]),
        messages=[{"type": "http.request", "body": body}])
    assert response(sent)[0] == status


def test_body_disconnect_and_cancellation_never_start_work(documents):
    doc, _other = documents
    app = strict.StrictPartDispatch(forbidden_app)
    request = scope(doc, JOBS, headers=[(b"content-type", b"application/json")])
    sent, reads = invoke(app, request, messages=[{"type": "http.disconnect"}])
    assert not sent and len(reads) == 1

    async def cancelled():
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        invoke(app, request, receive=cancelled)


def test_body_deadline_cancels_pending_receive(documents, monkeypatch):
    doc, _other = documents
    monkeypatch.setattr(strict, "MAX_BODY_SECONDS", .001)
    cancelled = []

    async def stalled():
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.append(True)

    sent, _reads = invoke(strict.StrictPartDispatch(forbidden_app),
        scope(doc, JOBS, headers=[(b"content-type", b"application/json")]), receive=stalled)
    assert response(sent)[0] == 408 and cancelled == [True]


@pytest.mark.parametrize("when", ["during_body", "after_body", "before_handler"])
def test_policy_generation_change_denies_without_fallback(documents, monkeypatch, when):
    doc, _other = documents
    app = strict.StrictPartDispatch(forbidden_app)

    def change():
        # Even reinstalling the identical profile invalidates this request.
        state.configure_part_publication_policy(policy.current_configuration())

    if when == "after_body":
        original = strict._json_input

        def after(*args, **kwargs):
            result = original(*args, **kwargs)
            change()
            return result

        monkeypatch.setattr(strict, "_json_input", after)
    elif when == "before_handler":
        original = app.strict

        async def before(*args):
            change()
            await original(*args)

        app.strict = before

    async def receive():
        if when == "during_body":
            change()
        return {"type": "http.request", "body": b'{}'}

    sent, _reads = invoke(app, scope(doc, EMPTY, headers=[(b"content-type", b"application/json")]), receive=receive)
    status, result = response(sent)
    assert status == 409 and result["detail"]["code"] == "policy_changed"
    assert doc not in state._sessions


def test_scalar_reads_do_not_create_sessions_or_serialize_live_designs(documents, monkeypatch):
    from backend.core.models import Design

    doc, _other = documents
    app = strict.StrictPartDispatch(forbidden_app)

    def forbidden(*_args, **_kwargs):
        pytest.fail("Scalar strict read created, copied or serialized a Design")

    monkeypatch.setattr(state, "_session", forbidden)
    monkeypatch.setattr(state, "get_design", forbidden)
    monkeypatch.setattr(Design, "model_dump", forbidden)
    monkeypatch.setattr(Design, "model_copy", forbidden)
    for path in (REVISION, POLICY):
        sent, reads = invoke(app, scope(doc, path, "GET"))
        assert response(sent)[0] == 200 and not reads
        assert doc not in state._sessions


def test_empty_creation_is_host_owned_and_response_has_no_design_alias(documents, monkeypatch):
    from backend.api import crud

    monkeypatch.setattr(crud, "_design_response", lambda *_a, **_k: pytest.fail("Legacy response helper ran"))
    doc, _other = documents
    app = strict.StrictPartDispatch(forbidden_app)
    with TestClient(app) as client:
        first = client.post(EMPTY, headers={"X-NADOC-Doc": doc}, json={"name": "Native", "lattice_type": "SQUARE"})
        denied = client.post(EMPTY, headers={"X-NADOC-Doc": doc}, json={"name": "Replace"})
        read = client.get(REVISION, headers={"X-NADOC-Doc": doc})
    assert first.status_code == 201 and denied.status_code == 409
    assert first.json()["recipe_root"] == {"kind": "empty", "version": 1}
    assert "design" not in first.json() and "feature_log" not in first.json()
    source, revision = state.get_design_with_revision()
    assert read.json()["design_id"] == source.id == first.json()["design_id"]
    assert read.json()["revision"] == revision == first.json()["revision"]
    result = read.json()
    result["design_id"] = "caller changed its output"
    assert source.id != result["design_id"] and not source.feature_log


@pytest.mark.parametrize("body", [{"design": {}}, {"policy": "compatibility"}, {"name": 5},
    {"name": "a" * 1025}, {"lattice_type": "CUSTOM"}, {"name": "  "}])
def test_empty_creation_rejects_client_models_authority_and_invalid_inputs(documents, body):
    doc, _other = documents
    with TestClient(strict.StrictPartDispatch(forbidden_app)) as client:
        result = client.post(EMPTY, headers={"X-NADOC-Doc": doc}, json=body)
    assert result.status_code == 422
    assert state.peek_design(doc) is None


def test_exact_existing_job_handlers_are_reused_with_the_canonical_context(documents, monkeypatch):
    from backend.api import part_evaluation_jobs as jobs

    doc, _other = documents
    calls = []

    def start(body, *, expected_policy_generation=None):
        assert expected_policy_generation == policy.resolve(doc).generation
        calls.append(("start", body.operation, get_current_doc()))
        return {"job_id": "opaque-job", "status": "running"}

    def inspect(identity, *, cancel=False):
        calls.append(("cancel" if cancel else "inspect", identity, get_current_doc()))
        return {"job_id": identity, "status": "running"}

    def commit(identity):
        calls.append(("commit", identity, get_current_doc()))
        return {"job_id": identity, "status": "committed", "revision": 2}

    monkeypatch.setattr(jobs, "start", start)
    monkeypatch.setattr(jobs, "inspect", inspect)
    monkeypatch.setattr(jobs, "commit", commit)
    with TestClient(strict.StrictPartDispatch(forbidden_app)) as client:
        headers = {"X-NADOC-Doc": doc}
        assert client.post(JOBS, headers=headers, json={"operation": "verify", "expected_revision": 1}).status_code == 202
        assert client.get(JOBS + "/opaque-job", headers=headers).status_code == 200
        assert client.delete(JOBS + "/opaque-job", headers=headers).status_code == 200
        assert client.post(JOBS + "/opaque-job/commit", headers=headers).status_code == 200
    assert calls == [(kind, value, doc) for kind, value in
        [("start", "verify"), ("inspect", "opaque-job"), ("cancel", "opaque-job"), ("commit", "opaque-job")]]


def test_public_batch_gate_stays_closed_before_worker_launch(documents, monkeypatch):
    from backend.api import part_batch_evaluation, part_evaluation_jobs as jobs

    monkeypatch.setattr(part_batch_evaluation, "REGISTERED_BATCH_ENABLED", False)
    monkeypatch.setattr(jobs, "_submit", lambda *_a, **_k: pytest.fail("Closed batch gate launched a worker"))
    doc, _other = documents
    source = state.create_empty_part("Batch target")
    request = {"operation": "batch", "batch": {"batch_version": 1,
        "expected_design_id": source.id, "expected_revision": state.revision(), "commands": [
            {"kind": "nanoparticle-create", "version": 1, "params": {
                "nanoparticle_id": str(uuid4()), "diameter_nm": 10.0}}]}}
    with TestClient(strict.StrictPartDispatch(forbidden_app)) as client:
        result = client.post(JOBS, headers={"X-NADOC-Doc": doc}, json=request)
    assert result.status_code == 422 and result.json()["detail"]["code"] == "registered_batch_unavailable"
    assert state.get_design() is source


def test_production_dispatch_is_outside_compatibility_preflight_without_lifespan(documents):
    from backend.api.main import app

    doc, other = documents
    assert app.user_middleware[0].cls is strict.StrictPartDispatch
    headers = [(b"origin", b"http://localhost:5173"), (b"access-control-request-method", b"POST")]
    sent, reads = invoke(app, scope(doc, "/api/design/import", "OPTIONS", headers=headers))
    assert response(sent)[0] == 403 and not reads
    sent, reads = invoke(app, scope(other, "/api/design/import", "OPTIONS", headers=headers))
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 200 and not reads


def test_strict_reads_and_creation_never_reenter_the_state_lock(documents, monkeypatch):
    class RejectReentry:
        def __init__(self):
            self.lock = threading.Lock()
            self.owner = None

        def acquire(self, *args, **kwargs):
            assert self.owner != threading.get_ident(), "Strict handler reentered the non-reentrant state lock"
            acquired = self.lock.acquire(*args, **kwargs)
            if acquired:
                self.owner = threading.get_ident()
            return acquired

        def release(self):
            self.owner = None
            self.lock.release()

        def __enter__(self):
            self.acquire()

        def __exit__(self, *_args):
            self.release()

    doc, _other = documents
    monkeypatch.setattr(state, "_lock", RejectReentry())
    with TestClient(strict.StrictPartDispatch(forbidden_app)) as client:
        headers = {"X-NADOC-Doc": doc}
        assert client.get(POLICY, headers=headers).status_code == 200
        assert client.get(REVISION, headers=headers).status_code == 200
        assert client.post(EMPTY, headers=headers, json={}).status_code == 201
        assert client.get(REVISION, headers=headers).json()["has_design"]


def test_dispatch_generation_reaches_locked_job_admission_before_session_or_copy(documents, monkeypatch):
    from backend.api import part_evaluation_capture, part_evaluation_jobs as jobs

    doc, _other = documents
    original = jobs.start

    def changed_after_dependency(body, **guards):
        assert guards["expected_policy_generation"] == policy.resolve(doc).generation
        state.configure_part_publication_policy(policy.current_configuration())
        return original(body, **guards)

    def forbidden(*_args, **_kwargs):
        pytest.fail("A stale dispatch entered session creation, source capture or worker launch")

    monkeypatch.setattr(jobs, "start", changed_after_dependency)
    monkeypatch.setattr(state, "_session_for_identity", forbidden)
    monkeypatch.setattr(part_evaluation_capture, "capture_for_evaluation", forbidden)
    monkeypatch.setattr(jobs, "_submit", forbidden)
    with TestClient(strict.StrictPartDispatch(forbidden_app)) as client:
        result = client.post(JOBS, headers={"X-NADOC-Doc": doc}, json={"operation": "verify"})
    assert result.status_code == 409 and result.json()["detail"]["code"] == "policy_changed"
    assert doc not in state._sessions
