"""OptiX process/route contracts without requiring GPU or Blender in CI."""
import asyncio
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.rendering import optix_service
from backend.api import routes_optix_export as routes


def test_persistent_worker_and_cleanup(tmp_path, monkeypatch):
    worker = tmp_path / "worker"
    worker.write_text("""#!/usr/bin/env python3
import json,sys
from pathlib import Path
print('NADOC_READY {"device":"test protocol only"}',flush=True)
for line in sys.stdin:
 c=json.loads(line);d=json.loads(Path(c['input']).read_text())
 Path(c['output']).write_bytes(bytes(d['width']*d['height']*16))
 print('NADOC_DONE',flush=True)
""")
    worker.chmod(0o700)
    monkeypatch.setattr(optix_service, "blender_executable", lambda: str(worker))

    async def exercise():
        session = await optix_service.OptixSession().start()
        pid = session.process.pid
        try:
            for _ in range(2):
                assert len(await session.render({"width": 4, "height": 3})) == 192
                assert session.process.pid == pid
                assert not (session.root / "frame.json").exists()
                assert not (session.root / "frame.rgba").exists()
        finally:
            await session.close()
        assert not session.root.exists()
        assert session.process.returncode is not None
    asyncio.run(exercise())


def test_unavailable_runtime_does_not_fallback(monkeypatch):
    monkeypatch.setenv("NADOC_BLENDER", "/not/a/blender")
    with pytest.raises(RuntimeError, match="no fallback"):
        optix_service.blender_executable()


def test_disconnect_during_startup_closes_owned_worker(monkeypatch):
    class Fake:
        closed = False
        async def start(self):
            await asyncio.sleep(10)
        async def close(self):
            self.closed = True
    class Disconnected:
        async def is_disconnected(self):
            return True
    session = Fake()
    monkeypatch.setattr(routes, "OptixSession", lambda: session)
    async def exercise():
        with pytest.raises(asyncio.CancelledError):
            await routes.create_session(Disconnected())
        assert session.closed
        assert not routes.sessions
    asyncio.run(exercise())


@pytest.mark.parametrize("failure", [RuntimeError, OSError])
def test_routes_bound_frames_and_close_on_failure(monkeypatch, tmp_path, failure):
    class Fake:
        id = "test-session"
        device = "protocol test"
        closed = False
        touched = 0
        lock = asyncio.Lock()
        upload_lock = asyncio.Lock()
        root = tmp_path
        stats = {"scene_reused": True, "render_ms": 12.5}
        async def start(self):
            return self
        async def close(self):
            self.closed = True
        async def render(self, data, *, source=None):
            assert source is not None
            if json.loads(source.read_text()).get("fail"):
                raise failure("GPU failed")
            return bytes(data["width"] * data["height"] * 16)
    monkeypatch.setattr(routes, "OptixSession", Fake)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        assert client.post("/render/optix/session").status_code == 200
        assert client.post("/render/optix/session").status_code == 409
        assert client.get("/render/optix/test-session/capacity").json()['upload_limit_bytes'] > 0
        path = "/render/optix/test-session/frame"
        assert client.post(path, json={"width": 9000, "height": 1, "samples": 1}).status_code == 422
        response = client.post(path, json={"width": 1, "height": 1, "samples": 1})
        assert response.content == bytes(16)
        assert json.loads(response.headers['X-NADOC-Render-Stats']) == Fake.stats
        with monkeypatch.context() as guard:
            guard.setattr(routes.json, 'load', lambda _: pytest.fail('New uploads must not parse geometry in the API process'))
            assert client.post(path, json={"width": 1, "height": 1, "samples": 1}, headers={
                'X-NADOC-Frame-width':'1', 'X-NADOC-Frame-height':'1', 'X-NADOC-Frame-samples':'1', 'X-NADOC-Render-Id':'frame-2',
            }).content == bytes(16)
        progress = client.get('/render/optix/test-session/progress').json()
        assert progress['request_id'] == 'frame-2'
        assert progress['label'] == 'Uploading OptiX scene'
        session = routes.sessions[Fake.id]
        assert client.post(path, json={"width": 1, "height": 1, "samples": 1, "fail": True}).status_code == 503
        assert session.closed
        assert not routes.sessions
        assert client.delete("/render/optix/test-session").status_code == 200
        assert not (tmp_path / 'upload.json').exists()


def test_upload_uses_current_resources_and_cleans_partial_files(monkeypatch, tmp_path):
    class Fake:
        root = tmp_path
        upload_lock = asyncio.Lock()
        lock = asyncio.Lock()
        touched = 0
    session = Fake()
    monkeypatch.setitem(routes.sessions, 'capacity-test', session)
    resources = {'available_memory_bytes': 1024**3, 'scratch_free_bytes': 2*1024**3, 'upload_limit_bytes': 1024**3}
    monkeypatch.setattr(routes, 'upload_capacity', lambda _: resources)
    app = FastAPI(); app.include_router(routes.router)
    # No lifespan/worker is needed to test admission and streamed-body cleanup.
    client = TestClient(app)
    assert client.get('/render/optix/capacity-test/capacity').json()['upload_limit_bytes'] == 1024**3
    resources['available_memory_bytes'] = 10
    response = client.post('/render/optix/capacity-test/frame', json={'width':1,'height':1,'samples':1})
    assert response.status_code == 413
    assert 'currently available RAM' in response.json()['detail']
    assert not (tmp_path / 'upload.json').exists()


def test_upload_disconnect_closes_worker_and_removes_partial_file(monkeypatch, tmp_path):
    from starlette.requests import ClientDisconnect
    class Fake:
        root = tmp_path
        upload_lock = asyncio.Lock()
        lock = asyncio.Lock()
        touched = 0
        closed = False
        async def close(self):
            self.closed = True
    class Disconnected:
        async def stream(self):
            yield b'{'
            raise ClientDisconnect()
    session = Fake()
    monkeypatch.setitem(routes.sessions, 'disconnected-upload', session)
    async def exercise():
        with pytest.raises(ClientDisconnect):
            await routes.render_frame('disconnected-upload', Disconnected())
    asyncio.run(exercise())
    assert session.closed
    assert 'disconnected-upload' not in routes.sessions
    assert not (tmp_path / 'upload.json').exists()


def test_admission_reclaims_expired_unclaimed_and_dead_workers_but_keeps_live_work():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    def session(age, *, claimed=True, busy=False, dead=False):
        lock = asyncio.Lock()
        value = SimpleNamespace(touched=optix_service.time.monotonic()-age, claimed=claimed,
            lock=lock, upload_lock=asyncio.Lock(), process=SimpleNamespace(returncode=0 if dead else None),
            closed=False, close=AsyncMock())
        return value, busy

    async def exercise():
        values = dict(stale=session(121), abandoned=session(11, claimed=False),
                      dead=session(0, dead=True), active=session(20),
                      rendering=session(200, busy=True), pending_ack=session(1, claimed=False))
        try:
            for key, (value, busy) in values.items():
                if busy:
                    await value.lock.acquire()
                routes.sessions[key] = value
            await routes.release_expired_sessions()
            assert set(routes.sessions) == {'active', 'rendering', 'pending_ack'}
            for key in ('stale', 'abandoned', 'dead'):
                values[key][0].close.assert_awaited_once()
            for key in ('active', 'rendering', 'pending_ack'):
                values[key][0].close.assert_not_awaited()
        finally:
            routes.sessions.clear()
    asyncio.run(exercise())
