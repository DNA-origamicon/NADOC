import asyncio

import httpx

from backend.core import collaboration_status as status
from backend.core.collaboration_peers import Peer, PeerRegistry


def test_tabs_share_probe_and_disconnect_does_not_cancel_it(monkeypatch, tmp_path):
    registry = PeerRegistry(tmp_path)
    registry.register(peer_id='peer', name='Other', base_url='http://localhost:9999', token='test')
    calls = []

    async def run():
        started, release = asyncio.Event(), asyncio.Event()

        async def probe(ws, peer):
            calls.append(peer)
            started.set()
            await release.wait()
            return {**peer.public(), 'online': False}

        monkeypatch.setattr(status, '_probe_peer', probe)
        first = asyncio.create_task(status.peer_statuses(tmp_path))
        await started.wait()
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        others = [asyncio.create_task(status.peer_statuses(tmp_path)) for _ in range(8)]
        release.set()
        results = await asyncio.gather(*others)
        assert len(calls) == 1
        assert all(r == results[0] for r in results)
        assert await status.peer_statuses(tmp_path) == results[0]
        assert len(calls) == 1
        registry.register(peer_id='peer', name='Changed', base_url='http://localhost:9998', token='changed')
        changed = await status.peer_statuses(tmp_path)
        assert changed['peers'][0]['name'] == 'Changed'
        assert len(calls) == 2
        monkeypatch.setattr(status, '_STATUS_TTL_SECONDS', -1)
        await status.peer_statuses(tmp_path)
        assert len(calls) == 3
    asyncio.run(run())
    assert not status._in_flight


def test_reachable_saved_address_does_not_wait_for_reverse_dns(monkeypatch, tmp_path):
    def forbidden_dns(*args):
        raise AssertionError('reachable peers need no DNS migration')
    monkeypatch.setattr(status.socket, 'gethostbyaddr', forbidden_dns)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(status.httpx, 'AsyncClient', lambda **kw: real_client(
        transport=httpx.MockTransport(lambda request: httpx.Response(200)), **kw))
    peer = Peer('p', 'Other', 'http://100.99.71.2:5173', 'test')
    assert asyncio.run(status._probe_peer(tmp_path, peer))['online']


def test_whole_probe_has_a_deadline(monkeypatch, tmp_path):
    async def stalled(request):
        await asyncio.Event().wait()
    real_client = httpx.AsyncClient
    monkeypatch.setattr(status.httpx, 'AsyncClient', lambda **kw: real_client(
        transport=httpx.MockTransport(stalled), **kw))
    monkeypatch.setattr(status, '_PROBE_TIMEOUT_SECONDS', 0.02)
    peer = Peer('p', 'Other', 'http://localhost:9999', 'test')
    assert asyncio.run(status._probe_peer(tmp_path, peer)) == {**peer.public(), 'online': False}
