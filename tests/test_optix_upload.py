"""Large scene transfer stays ordered, capacity checked and disposable."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.requests import ClientDisconnect

from backend.api import routes_optix_export as routes
from backend.rendering import optix_upload


def test_chunk_upload_render_order_identity_and_cleanup(tmp_path, monkeypatch):
    async def render(data, *, source):
        assert json.loads(source.read_bytes()) == payload
        return bytes(data['width'] * data['height'] * 16)

    session = SimpleNamespace(root=tmp_path, upload_lock=asyncio.Lock(), lock=asyncio.Lock(), touched=0, render=render)
    monkeypatch.setitem(routes.sessions, 'pieces', session)
    app = FastAPI(); app.include_router(routes.router)
    client = TestClient(app)
    payload = {'width': 1, 'height': 1, 'samples': 1, 'mesh': 'é'}
    encoded = json.dumps(payload, ensure_ascii=False).encode()
    path = '/render/optix/pieces'
    headers = {'X-NADOC-Upload-Bytes': str(len(encoded)), 'X-NADOC-Render-Id': 'a',
               'X-NADOC-Frame-width': '1', 'X-NADOC-Frame-height': '1', 'X-NADOC-Frame-samples': '1'}
    def piece(offset, body, **extra):
        return client.post(path + '/upload', content=body,
                           headers={**headers, 'X-NADOC-Upload-Offset': str(offset), **extra})
    assert piece(0, encoded[:20]).json() == {'received': 20}
    assert piece(0, encoded[:20]).json() == {'received': 20}
    assert piece(0, b'x' * 20).status_code == 409
    assert piece(20, encoded[20:], **{'X-NADOC-Render-Id': 'b'}).status_code == 409
    assert piece(20, encoded[20:]).status_code == 200
    assert session.progress['fraction'] == 1
    assert client.post(path + '/frame', headers=headers).content == bytes(16)
    assert not (tmp_path / 'upload.json').exists()

    assert piece(0, encoded[:20]).status_code == 200
    assert client.post(path + '/frame', headers=headers).status_code == 422
    assert not (tmp_path / 'upload.json').exists()


def test_chunk_disconnect_keeps_worker_and_rolls_back_only_partial_piece(tmp_path, monkeypatch):
    session = SimpleNamespace(root=tmp_path, upload_lock=asyncio.Lock(), lock=asyncio.Lock(), touched=0,
                              close=AsyncMock())
    monkeypatch.setitem(routes.sessions, 'interrupted-piece', session)

    (tmp_path / 'upload.json').write_bytes(b'previous')
    session.upload_identity = (100, None)

    class Disconnected:
        headers = {'x-nadoc-upload-offset': '8', 'x-nadoc-upload-bytes': '100'}

        async def stream(self):
            yield b'{'
            raise ClientDisconnect()

    with pytest.raises(ClientDisconnect):
        asyncio.run(routes.upload_piece('interrupted-piece', Disconnected()))
    session.close.assert_not_awaited()
    assert 'interrupted-piece' in routes.sessions
    assert (tmp_path / 'upload.json').read_bytes() == b'previous'
    asyncio.run(routes.close_session('interrupted-piece'))
    session.close.assert_awaited_once()
    assert 'interrupted-piece' not in routes.sessions


def test_chunk_capacity_and_overflow(tmp_path, monkeypatch):
    session = SimpleNamespace(root=tmp_path, upload_lock=asyncio.Lock(), lock=asyncio.Lock(), touched=0)
    monkeypatch.setitem(routes.sessions, 'capacity-pieces', session)
    app = FastAPI(); app.include_router(routes.router)
    client = TestClient(app)
    path = '/render/optix/capacity-pieces/upload'
    headers = {'X-NADOC-Upload-Bytes': '5', 'X-NADOC-Upload-Offset': '0'}
    monkeypatch.setattr(optix_upload, 'upload_capacity', lambda _: {'available_memory_bytes': 4, 'scratch_free_bytes': 100})
    assert client.post(path, content=b'123', headers=headers).status_code == 413
    assert not (tmp_path / 'upload.json').exists()
    monkeypatch.setattr(optix_upload, 'upload_capacity', lambda _: {'available_memory_bytes': 100, 'scratch_free_bytes': 100})
    assert client.post(path, content=b'123456', headers=headers).status_code == 422
    assert not (tmp_path / 'upload.json').exists()
