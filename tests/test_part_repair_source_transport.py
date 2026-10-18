"""Bound metadata before reading raw bytes; retain no queued upload workers."""

import asyncio
import json
from threading import Event, Lock

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest
from starlette.datastructures import Headers
from starlette.requests import ClientDisconnect

from backend.api import doc_context, part_repair_source_host as host, part_repair_source_transport as transport, state
from tests.test_part_repair_source_host import document as document, request
from tests.test_part_repair_sources import NEW, descriptor, mutation, source


class RawRequest:
    def __init__(self, body=NEW, metadata=None, headers=(), chunks=None, disconnected=False):
        values = [(transport.METADATA_HEADER, json.dumps(metadata or mutation(source()))),
                  ("content-type", "application/octet-stream"), *headers]
        self.headers = Headers(raw=[(key.encode(), value.encode()) for key, value in values])
        self.chunks = [body] if chunks is None else chunks
        self.consumed = False
        self.disconnected = disconnected

    async def stream(self):
        self.consumed = True
        for item in self.chunks:
            if isinstance(item, Exception):
                raise item
            yield item

    async def is_disconnected(self):
        return self.disconnected


@pytest.fixture(autouse=True)
def independent_slot(monkeypatch):
    monkeypatch.setattr(transport, "_slot", Lock())


def private_stub(monkeypatch):
    monkeypatch.setattr(host, "capture_source_request", lambda *_a, **_k: "captured")
    monkeypatch.setattr(host, "prepare_upload", lambda *_a: ("prepared", {"ok": True}))
    monkeypatch.setattr(host, "publish_upload", lambda *_a, **_k: {"ok": True})


def test_actual_raw_request_inspects_then_stages_original_bytes_for_same_document(document):
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)

    @app.post("/source")
    async def upload(incoming: Request):
        return await transport.upload_source(incoming)

    metadata = host.inspect_source(request())
    before, revision = state.get_design_with_revision()
    with TestClient(app) as client:
        response = client.post("/source", content=NEW,
            headers={"X-NADOC-Doc": document, "Content-Type": "application/octet-stream",
                     transport.METADATA_HEADER: json.dumps(metadata)})
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == revision + 1
    assert state.get_or_404().repair_draft is before.repair_draft
    assert descriptor(NEW).sha256 in state.get_or_404().input_sources
    assert before.input_sources == {} and state.undo_depth() == 0


@pytest.mark.parametrize("headers,status", [
    ([("content-type", "application/json")], 415),
    ([("content-length", "350001")], 413),
    ([("content-length", "1")], 422),
    ([("content-length", str(len(NEW))), ("content-length", str(len(NEW)))], 422),
    ([("content-length", "+2")], 422),
    ([("content-encoding", "gzip")], 415),
    ([(transport.METADATA_HEADER, "{}")], 422),
])
def test_invalid_transport_rejected_before_body_or_capture(headers, status, monkeypatch):
    incoming = RawRequest(headers=headers)
    monkeypatch.setattr(host, "capture_source_request", lambda *_a, **_k: pytest.fail("Invalid header captured"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(transport.upload_source(incoming))
    assert error.value.status_code == status and not incoming.consumed
    assert not transport._slot.locked()


@pytest.mark.parametrize("text", ["x" * 8193, '{"operation":"x","operation":"y"}', "[" * 1000,
                                  '{"source_repair_version":NaN}', "é"])
def test_metadata_bound_and_duplicate_keys_precede_body(text):
    incoming = RawRequest()
    incoming.headers = Headers({transport.METADATA_HEADER: text, "content-type": "application/octet-stream"})
    with pytest.raises(HTTPException):
        asyncio.run(transport.upload_source(incoming))
    assert not incoming.consumed and not transport._slot.locked()


@pytest.mark.parametrize("chunks,status", [([NEW, b"excess"], 413), ([NEW[:-1]], 422),
                                           ([ClientDisconnect()], 499)])
def test_stream_enforces_exact_declared_bytes_and_releases_admission(chunks, status, monkeypatch):
    private_stub(monkeypatch)
    incoming = RawRequest(chunks=chunks)
    with pytest.raises(HTTPException) as error:
        asyncio.run(transport.upload_source(incoming))
    assert error.value.status_code == status and not transport._slot.locked()


def test_deadline_cancels_blocked_read_and_releases_slot(monkeypatch):
    private_stub(monkeypatch)
    monkeypatch.setattr(transport, "READ_SECONDS", 0)
    class Blocked(RawRequest):
        async def stream(self):
            await asyncio.Event().wait()
            yield b"unreachable"
    with pytest.raises(HTTPException) as error:
        asyncio.run(transport.upload_source(Blocked()))
    assert error.value.status_code == 408
    assert not transport._slot.locked()


@pytest.mark.parametrize("phase", ["capture_source_request", "prepare_upload", "publish_upload"])
def test_every_private_failure_releases_slot(phase, monkeypatch):
    private_stub(monkeypatch)
    def fail(*_a, **_k):
        raise HTTPException(409, detail="failure")
    monkeypatch.setattr(host, phase, fail)
    with pytest.raises(HTTPException):
        asyncio.run(transport.upload_source(RawRequest()))
    assert not transport._slot.locked()


def test_busy_has_no_queue_and_cancelled_read_releases_slot(monkeypatch):
    private_stub(monkeypatch)
    async def exercise():
        started = asyncio.Event()
        class Blocked(RawRequest):
            async def stream(self):
                started.set()
                await asyncio.Event().wait()
                yield b"unreachable"
        first = asyncio.create_task(transport.upload_source(Blocked()))
        await started.wait()
        second = RawRequest()
        with pytest.raises(HTTPException) as error:
            await transport.upload_source(second)
        assert error.value.detail["code"] == "source_upload_busy" and not second.consumed
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not transport._slot.locked()
        assert await transport.upload_source(RawRequest()) == {"ok": True}
    asyncio.run(exercise())


def test_cancel_waits_for_private_worker_before_releasing_slot(monkeypatch):
    private_stub(monkeypatch)
    entered, release, returned = Event(), Event(), Event()
    def blocked(*_a, **_k):
        entered.set()
        assert release.wait(5)
        returned.set()
        return "captured"
    monkeypatch.setattr(host, "capture_source_request", blocked)
    async def exercise():
        first = asyncio.create_task(transport.upload_source(RawRequest()))
        assert await asyncio.to_thread(entered.wait, 5)
        first.cancel()
        try:
            second = RawRequest()
            with pytest.raises(HTTPException) as error:
                await transport.upload_source(second)
            assert error.value.detail["code"] == "source_upload_busy"
            assert not returned.is_set() and transport._slot.locked()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert returned.is_set() and not transport._slot.locked()
    asyncio.run(exercise())


def test_disconnect_after_preparation_never_publishes(monkeypatch):
    private_stub(monkeypatch)
    monkeypatch.setattr(host, "publish_upload", lambda *_a, **_k: pytest.fail("Disconnected upload published"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(transport.upload_source(RawRequest(disconnected=True)))
    assert error.value.status_code == 499 and not transport._slot.locked()
