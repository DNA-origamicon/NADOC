"""Bounded request-owned file recovery never acquires a live document.

All transport controls are memory-only. The one native HTTP case uses a tiny
recipe and the ordinary spawned worker, without app lifespan or workspace I/O.
"""

import asyncio
from contextlib import ExitStack
from hashlib import sha256
import importlib
import json
import struct
from threading import BoundedSemaphore, Event
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect

from backend.api import doc_context, part_publication_policy as policy, state


PATH = "/api/part-recipe/recovery"
REVIEW = {"status": "review", "issues": [], "upgrades": [], "recovery": {"old_state_verified": False}}
REVIEW_BYTES = json.dumps(REVIEW, separators=(",", ":")).encode()
INSPECT = {"version": 1, "operation": "inspect"}


def service():
    return importlib.import_module("backend.api.part_recipe_file_transport")


def frame(raw=b"original file bytes", operation=None, *, header=None):
    metadata = (json.dumps(INSPECT if operation is None else operation, separators=(",", ":")).encode()
                if header is None else header)
    return struct.pack("!I", len(metadata)) + metadata + raw


def scope():
    return {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "POST", "scheme": "http", "path": PATH, "raw_path": PATH.encode(),
            "root_path": "", "query_string": b"", "headers": [],
            "client": ("test", 1), "server": ("test", 80)}


class Incoming:
    def __init__(self, body=None, *, headers=None, chunks=None, disconnected=False):
        self.body = frame() if body is None else body
        pairs = [("content-type", "application/octet-stream")] if headers is None else headers
        self.headers = Headers(raw=[(key.encode(), value.encode()) for key, value in pairs])
        self.chunks = [self.body] if chunks is None else chunks
        self.consumed = self.eof = False
        self.disconnected = disconnected
        self.scope = scope()

    async def stream(self):
        self.consumed = True
        for chunk in self.chunks:
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk
        self.eof = True

    async def is_disconnected(self):
        assert self.eof, "Disconnect polling competed with the body receive owner"
        return self.disconnected


@pytest.fixture
def transport(monkeypatch):
    module = service()  # No global mutation before a test-first import succeeds.
    slot = BoundedSemaphore(1)
    monkeypatch.setattr(module, "_slot", slot)
    document = f"recipe-file-transport-{uuid4()}"
    previous = policy.current_configuration()
    with ExitStack() as cleanup:
        token = doc_context.set_current_doc(document)
        cleanup.callback(doc_context.reset_current_doc, token)
        cleanup.callback(state.configure_part_publication_policy, previous)
        state.configure_part_publication_policy(policy.HostPolicyConfiguration())
        yield SimpleNamespace(module=module, slot=slot, document=document)
    assert document not in state._sessions


@pytest.fixture
def open_document(transport):
    from backend.core.part_history_contract import create_empty_part

    original = create_empty_part("Keep this open part", "HONEYCOMB")
    with ExitStack() as cleanup:
        cleanup.callback(state.drop_doc, transport.document)
        state.load_design(original)
        yield original


def available(slot):
    acquired = slot.acquire(blocking=False)
    if acquired:
        slot.release()
    return acquired


def stub_evaluation(monkeypatch, module):
    calls = []

    def evaluate(raw, operation, cancelled, deadline, policy_check):
        policy_check()
        assert not cancelled.is_set()
        calls.append((raw, operation, deadline))
        return REVIEW_BYTES

    monkeypatch.setattr(module, "_evaluate", evaluate)
    return calls


async def send_response(response, send=None):
    messages = []

    async def receive():
        return {"type": "http.disconnect"}

    async def collect(message):
        messages.append(message)

    await response(scope(), receive, send or collect)
    return messages


def test_exact_frame_bytes_reach_worker_and_slot_lasts_through_response(transport, monkeypatch):
    raw = b"\x00original\xff\nbytes\r\n"
    incoming = Incoming(frame(raw), chunks=[frame(raw)[:2], frame(raw)[2:11], frame(raw)[11:]])
    calls = stub_evaluation(monkeypatch, transport.module)

    async def exercise():
        response = await transport.module.recover_file(incoming)
        assert not available(transport.slot)
        messages = await send_response(response)
        assert available(transport.slot)
        assert getattr(response, "body", b"") == b""
        content = b"".join(message.get("body", b"") for message in messages)
        assert json.loads(content) == REVIEW

    asyncio.run(exercise())
    assert len(calls) == 1 and calls[0][0] == raw
    operation = calls[0][1]
    assert (operation.model_dump(exclude_none=True) if hasattr(operation, "model_dump") else operation) == INSPECT


@pytest.mark.parametrize("headers,status", [
    ([], 415),
    ([("content-type", "application/json")], 415),
    ([("content-type", "application/octet-stream"), ("content-encoding", "gzip")], 415),
    ([("content-type", "application/octet-stream"), ("content-type", "application/octet-stream")], 415),
    ([("content-type", "application/octet-stream"), ("content-length", "+12")], 400),
    ([("content-type", "application/octet-stream"), ("content-length", "2000000")], 413),
])
def test_bad_headers_refuse_before_body_or_worker(transport, monkeypatch, headers, status):
    calls = stub_evaluation(monkeypatch, transport.module)
    incoming = Incoming(headers=headers)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.module.recover_file(incoming))
    assert caught.value.status_code == status
    assert not incoming.consumed and not calls and available(transport.slot)


def test_busy_refuses_before_body_without_queuing(transport, monkeypatch):
    calls = stub_evaluation(monkeypatch, transport.module)
    incoming = Incoming()
    assert transport.slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(transport.module.recover_file(incoming))
        assert caught.value.status_code == 429
        assert not incoming.consumed and not calls
    finally:
        transport.slot.release()


@pytest.mark.parametrize("body", [
    b"", b"\x00\x00", struct.pack("!I", 0) + b"x",
    frame(header=b'{"version":1,"operation":"inspect","operation":"recover"}'),
    frame(operation={"version": True, "operation": "inspect"}),
    frame(operation={"version": 1, "operation": []}),
    frame(operation={"version": 1, "operation": "other"}),
    frame(operation={"version": 1, "operation": "inspect", "request": {}}),
    frame(operation={"version": 1, "operation": "recover"}),
    frame(operation={**INSPECT, "candidate_id": "caller-owned"}),
    frame(raw=b""),
], ids=["empty", "short-prefix", "empty-header", "duplicate-json", "bool-version", "unhashable-operation",
        "unknown-operation", "inspect-with-action", "recover-without-request", "authority-field", "no-file"])
def test_bad_frames_and_operation_shapes_never_start_worker(transport, monkeypatch, body):
    calls = stub_evaluation(monkeypatch, transport.module)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.module.recover_file(Incoming(body)))
    assert caught.value.status_code == 400
    assert not calls and available(transport.slot)


@pytest.mark.parametrize("event,status", [(ClientDisconnect(), 499), (TimeoutError(), 408)])
def test_body_disconnect_or_timeout_releases_admission(transport, monkeypatch, event, status):
    calls = stub_evaluation(monkeypatch, transport.module)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.module.recover_file(Incoming(chunks=[b"\x00", event])))
    assert caught.value.status_code == status
    assert not calls and available(transport.slot)


def test_strict_host_refuses_before_body_without_a_session(transport, monkeypatch):
    calls = stub_evaluation(monkeypatch, transport.module)
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    incoming = Incoming()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.module.recover_file(incoming))
    assert caught.value.status_code == 403
    assert not incoming.consumed and not calls and available(transport.slot)


def test_response_send_owns_admission_until_the_last_await(transport, monkeypatch):
    stub_evaluation(monkeypatch, transport.module)

    async def exercise():
        response = await transport.module.recover_file(Incoming())
        sending, release = asyncio.Event(), asyncio.Event()

        async def send(message):
            if message["type"] == "http.response.body":
                sending.set()
                await release.wait()

        task = asyncio.create_task(send_response(response, send))
        try:
            await asyncio.wait_for(sending.wait(), 2)
            second = Incoming()
            with pytest.raises(HTTPException) as caught:
                await transport.module.recover_file(second)
            assert caught.value.status_code == 429 and not second.consumed
        finally:
            release.set()
            await task
        assert available(transport.slot) and response.body == b""

    asyncio.run(exercise())


def test_body_cancellation_releases_slot_without_starting_work(transport, monkeypatch):
    calls = stub_evaluation(monkeypatch, transport.module)

    async def exercise():
        entered = asyncio.Event()

        class Blocked(Incoming):
            async def stream(self):
                entered.set()
                await asyncio.Event().wait()
                yield b"unreachable"

        task = asyncio.create_task(transport.module.recover_file(Blocked()))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert not available(transport.slot)
        finally:
            task.cancel()
            outcome = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(outcome[0], asyncio.CancelledError)
        assert available(transport.slot) and not calls

    asyncio.run(exercise())


def immediate_worker(monkeypatch, module, *, failure=None, on_start=None, on_close=None):
    observed = SimpleNamespace(constructed=0, started=0, reads=0, closes=0)

    class Worker:
        def __init__(self, raw, operation):
            observed.constructed += 1
            assert type(raw) is bytes and operation == INSPECT
            if failure == "construct":
                raise RuntimeError("Injected construction failure")

        def start(self):
            observed.started += 1
            if on_start:
                on_start()
            if failure == "start":
                raise RuntimeError("Injected start failure")

        def wait(self, timeout):
            return True

        def is_alive(self):
            return False

        def response_bytes(self):
            observed.reads += 1
            if failure == "result":
                raise ValueError("Injected malformed worker result")
            return REVIEW_BYTES

        def close(self):
            observed.closes += 1
            if on_close:
                on_close()
            if failure == "close" and observed.closes == 1:
                raise RuntimeError("Injected first cleanup failure")

    monkeypatch.setattr(module, "RecipeFileWorker", Worker)
    return observed


@pytest.mark.parametrize("phase", ["construct", "start", "result", "close"])
def test_worker_failures_are_nonready_and_cleanup_precedes_slot_release(transport, monkeypatch, phase):
    observed = immediate_worker(monkeypatch, transport.module, failure=phase)

    async def exercise():
        response = await transport.module.recover_file(Incoming())
        assert not available(transport.slot)
        expected_closes = 0 if phase == "construct" else 2 if phase == "close" else 1
        assert observed.closes == expected_closes
        result = json.loads(response.body)
        assert result["status"] == "unverified"
        assert "candidate" not in result and "recovered_file" not in result
        assert result["issues"][0]["code"] == (
            "worker_cleanup_error" if phase == "close" else "recovery_worker_error")
        await send_response(response)
        assert available(transport.slot)

    asyncio.run(exercise())


def test_dead_worker_cleanup_cannot_release_after_three_failed_buffer_unlinks(transport, monkeypatch):
    fourth_close, release = Event(), Event()

    def close_buffers():
        if observed.closes <= 4:
            if observed.closes == 4:
                fourth_close.set()
                assert release.wait(5), "Test did not release its controlled buffer cleanup"
            raise OSError(f"Buffer cleanup failure {observed.closes}")

    observed = immediate_worker(monkeypatch, transport.module, on_close=close_buffers)

    async def exercise():
        task = asyncio.create_task(transport.module.recover_file(Incoming()))
        response = None
        try:
            assert await asyncio.to_thread(fourth_close.wait, 1), (
                "A dead process was treated as complete buffer cleanup after only three attempts")
            assert not task.done() and not available(transport.slot)
            incoming = Incoming()
            with pytest.raises(HTTPException) as caught:
                await transport.module.recover_file(incoming)
            assert caught.value.status_code == 429 and not incoming.consumed
        finally:
            release.set()
            response = await asyncio.wait_for(task, 2)
            result = json.loads(response.body)
            await send_response(response)
        assert observed.closes == 5
        assert result["status"] == "unverified"
        assert result["issues"][0]["code"] == "worker_cleanup_error"
        assert result["issues"][0]["detail"] == "Buffer cleanup failure 1"
        assert "recovered_file" not in result and available(transport.slot)

    asyncio.run(exercise())


def test_repeated_request_cancellation_waits_for_reaping_before_releasing_slot(transport, monkeypatch):
    entered, closing, release, closed = Event(), Event(), Event(), Event()

    class Worker:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def wait(self, timeout):
            entered.set()
            closed.wait(min(timeout, .005))
            return False

        def is_alive(self):
            return not closed.is_set()

        def response_bytes(self):
            pytest.fail("Cancelled worker returned a successful response")

        def close(self):
            closing.set()
            assert release.wait(5), "Test did not release its controlled cleanup"
            closed.set()

    monkeypatch.setattr(transport.module, "RecipeFileWorker", Worker)

    async def exercise():
        task = asyncio.create_task(transport.module.recover_file(Incoming()))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            assert await asyncio.to_thread(closing.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not closed.is_set() and not available(transport.slot)
            incoming = Incoming()
            with pytest.raises(HTTPException) as caught:
                await transport.module.recover_file(incoming)
            assert caught.value.status_code == 429 and not incoming.consumed
        finally:
            release.set()
            task.cancel()
            outcome = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(outcome[0], asyncio.CancelledError)
        assert closed.is_set() and available(transport.slot)

    asyncio.run(exercise())


def test_disconnect_after_body_cancels_worker_and_reaps_before_499(transport, monkeypatch):
    entered, closed = Event(), Event()
    incoming = Incoming()

    class Worker:
        def __init__(self, *_args):
            pass

        def start(self):
            pass

        def wait(self, timeout):
            entered.set()
            closed.wait(min(timeout, .005))
            return False

        def is_alive(self):
            return not closed.is_set()

        def close(self):
            closed.set()

    monkeypatch.setattr(transport.module, "RecipeFileWorker", Worker)

    async def exercise():
        task = asyncio.create_task(transport.module.recover_file(incoming))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            incoming.disconnected = True
            with pytest.raises(HTTPException) as caught:
                await asyncio.wait_for(task, 2)
            assert caught.value.status_code == 499
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert incoming.eof and closed.is_set() and available(transport.slot)

    asyncio.run(exercise())


@pytest.mark.parametrize("phase", ["body", "start", "close"])
def test_policy_generation_change_never_returns_ready(transport, monkeypatch, phase):
    def changed():
        # Even the same mode has a new host generation; no client authority flag.
        state.configure_part_publication_policy(policy.HostPolicyConfiguration())

    observed = immediate_worker(monkeypatch, transport.module,
        on_start=changed if phase == "start" else None,
        on_close=changed if phase == "close" else None)

    class ChangesDuringBody(Incoming):
        async def stream(self):
            async for chunk in super().stream():
                yield chunk
            if phase == "body":
                changed()

    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.module.recover_file(ChangesDuringBody()))
    assert caught.value.status_code == 409
    assert available(transport.slot)
    assert observed.constructed == (0 if phase == "body" else 1)
    assert observed.closes == (0 if phase == "body" else 1)


@pytest.mark.parametrize("phase", ["construct", "close"])
def test_original_deadline_is_not_restarted_around_worker_lifecycle(transport, monkeypatch, phase):
    now = [100.0]
    monkeypatch.setattr(transport.module, "monotonic", lambda: now[0])
    observed = immediate_worker(monkeypatch, transport.module,
        on_close=(lambda: now.__setitem__(0, 102.0)) if phase == "close" else None)
    original_factory = transport.module.RecipeFileWorker

    def factory(raw, operation):
        worker = original_factory(raw, operation)
        if phase == "construct":
            now[0] = 102.0
        return worker

    monkeypatch.setattr(transport.module, "RecipeFileWorker", factory)
    result = json.loads(transport.module._evaluate(b"original", INSPECT, Event(), 101.0, lambda: None))
    assert result["status"] == "unverified" and result["issues"][0]["code"] == "time_limit"
    assert observed.started == (0 if phase == "construct" else 1)
    assert observed.closes == 1
    assert available(transport.slot)


def test_cancelled_response_always_clears_its_bytes_and_releases_slot(transport, monkeypatch):
    stub_evaluation(monkeypatch, transport.module)

    async def exercise():
        response = await transport.module.recover_file(Incoming())
        entered = asyncio.Event()

        async def blocked_send(_message):
            entered.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(send_response(response, blocked_send))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            assert not available(transport.slot)
        finally:
            task.cancel()
            outcome = await asyncio.gather(task, return_exceptions=True)
        assert isinstance(outcome[0], asyncio.CancelledError)
        assert response.body == b"" and available(transport.slot)

    asyncio.run(exercise())


def test_already_expired_response_refuses_before_even_nonyielding_send(transport, monkeypatch):
    stub_evaluation(monkeypatch, transport.module)
    now = [100.0]
    monkeypatch.setattr(transport.module, "monotonic", lambda: now[0])

    async def exercise():
        response = await transport.module.recover_file(Incoming())
        now[0] += transport.module.TOTAL_SECONDS + 1
        sent = []

        async def send(message):
            sent.append(message)  # Deliberately no suspension point.

        with pytest.raises(HTTPException) as caught:
            await send_response(response, send)
        assert caught.value.status_code == 408 and not sent
        assert response.body == b"" and available(transport.slot)

    asyncio.run(exercise())


def test_gzip_middleware_does_not_reencode_response_or_release_admission_early(transport, monkeypatch):
    from starlette.middleware.gzip import GZipMiddleware, GZipResponder

    stub_evaluation(monkeypatch, transport.module)
    monkeypatch.setattr(GZipResponder, "apply_compression",
        lambda *_a, **_k: pytest.fail("Recovery compressed a large result on the event loop"))

    async def exercise():
        response = await transport.module.recover_file(Incoming())
        request_scope = {**scope(), "headers": [(b"accept-encoding", b"gzip")]}
        messages = []

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            assert not available(transport.slot)
            messages.append(message)

        await GZipMiddleware(response, minimum_size=1)(request_scope, receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        assert dict(start["headers"])[b"content-encoding"] == b"identity"
        assert b"".join(message.get("body", b"") for message in messages) == REVIEW_BYTES
        assert response.body == b"" and available(transport.slot)

    asyncio.run(exercise())


def test_file_byte_limit_refuses_before_worker(transport, monkeypatch):
    calls = stub_evaluation(monkeypatch, transport.module)
    monkeypatch.setattr(transport.module, "MAX_FILE_BYTES", 3)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(transport.module.recover_file(Incoming(frame(b"four"))))
    assert caught.value.status_code == 413 and not calls and available(transport.slot)


def test_production_import_uses_the_shared_history_admission_slot():
    from backend.api.part_history_verification import _slot

    assert service()._slot is _slot


def test_strict_dispatch_refuses_recovery_route_before_receive_or_fallback(transport):
    from backend.api.part_strict_http import StrictPartDispatch

    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    sent = []

    async def fallback(*_args):
        pytest.fail("Strict recovery reached compatibility routing")

    async def receive():
        pytest.fail("Strict recovery acquired uploaded file bytes")

    async def send(message):
        sent.append(message)

    asyncio.run(StrictPartDispatch(fallback)(scope(), receive, send))
    assert sent[0]["status"] == 403 and available(transport.slot)


def test_real_http_recovers_exact_download_without_changing_original_or_live_state(transport, open_document, monkeypatch):
    from backend.api.routes_part_recipe_recovery import router
    from backend.core.models import Design
    from tests.test_part_recipe_file_recovery import saved
    from tests.test_part_structure_proof import assess

    source, raw = saved()
    original_state = source.model_dump_json()
    with state._lock:
        sessions = {key: (item, item.design, item.revision, tuple(item.history), tuple(item.redo))
                    for key, item in state._sessions.items()}

    def forbidden(*_args, **_kwargs):
        pytest.fail("File recovery crossed the active-document boundary")

    for name in ("get_or_404", "get_design", "load_design", "set_design", "set_design_silent", "snapshot"):
        monkeypatch.setattr(state, name, forbidden)

    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    client = TestClient(app)  # No production app lifespan, cache or workspace.
    try:
        inspected = client.post(PATH, content=frame(raw),
            headers={"Content-Type": "application/octet-stream", "X-NADOC-Doc": transport.document})
        assert inspected.status_code == 200, inspected.text
        review = inspected.json()
        assert review["status"] == "review" and review["upgrades"]
        assert review["recovery"]["source_sha256"] == sha256(raw).hexdigest()
        assert available(transport.slot)
        operation = {"version": 1, "operation": "recover", "request": {
            "version": 1, "expected_source_sha256": review["recovery"]["source_sha256"],
            "actions": [descriptor["action"] for descriptor in review["upgrades"]],
        }}
        response = client.post(PATH, content=frame(raw, operation),
            headers={"Content-Type": "application/octet-stream", "X-NADOC-Doc": transport.document})
    finally:
        client.close()
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "ready" and "candidate" not in result
    artifact = result["recovered_file"]
    artifact_bytes = artifact["json_text"].encode("utf-8")
    assert len(artifact_bytes) == artifact["size_bytes"]
    assert sha256(artifact_bytes).hexdigest() == artifact["sha256"]
    candidate = Design.from_json(artifact["json_text"])
    assert candidate.id != source.id and candidate.id == result["recovery"]["recovered_design_id"]
    assert candidate.model_dump(mode="json") == json.loads(artifact["json_text"])
    assert assess(candidate)["status"] == "verified"
    assert result["recovery"]["source_sha256"] == sha256(raw).hexdigest()
    assert source.model_dump_json() == original_state
    with state._lock:
        assert set(state._sessions) == set(sessions)
        for key, (item, design, revision, history, redo) in sessions.items():
            current = state._sessions[key]
            assert current is item and current.design is design and current.revision == revision
            assert tuple(current.history) == history and tuple(current.redo) == redo
    assert available(transport.slot)
