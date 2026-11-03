"""Real strict status dispatch with isolated files and fake peer transports only."""
import asyncio
import json
import os
from pathlib import Path

from fastapi.testclient import TestClient
import httpx
import pytest

from backend.api import routes_vr as vr, routes_project_collaboration as collab, state
from backend.api import part_strict_service_reads as reads, part_publication_policy as policy
from backend.api.part_strict_http import StrictPartDispatch
from backend.core import collaboration_status as status
from backend.core.collaboration_peers import PeerRegistry
from backend.core.service_status_io import StatusReader, StatusReadLimit
from tests.test_part_strict_http import documents as documents, forbidden_app

VR = '/api/vr/references'
PEERS = '/api/collaboration/peers/status'


@pytest.fixture
def isolated(documents, tmp_path, monkeypatch):
    monkeypatch.setattr(collab, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(vr, '_STATE_PATH', tmp_path / 'vr.json')
    monkeypatch.setattr(vr, '_capture_configuration', lambda: None)
    monkeypatch.setattr(vr, '_VIEWER', Path('/proc/self/exe').resolve())
    from collections import OrderedDict
    monkeypatch.setattr(status, '_cached', OrderedDict())
    monkeypatch.setattr(status, '_in_flight', {})
    with TestClient(StrictPartDispatch(forbidden_app), client=('127.0.0.1', 1234),
                    headers={'X-NADOC-Doc': documents[0]}) as client:
        yield client


def snapshots(root):
    return {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode', ['absent', 'active', 'other-document', 'stale-pid', 'malformed-event'])
def test_vr_status_parity_no_mutation(documents, isolated, tmp_path, mode):
    if mode != 'absent':
        vr._STATE_PATH.write_text(json.dumps({'pid': os.getpid() if mode != 'stale-pid' else 999999999,
            'doc_id': documents[0] if mode != 'other-document' else documents[1],
            'event_path': str(tmp_path / 'events')}))
        (tmp_path / 'events.references-event').write_text('bad' if mode == 'malformed-event' else
            json.dumps({'sequence': 2, 'action': 'color', 'id': 'reference'}))
    before = snapshots(tmp_path)
    result = isolated.get(VR)
    assert result.status_code == 200, result.text
    expected = {'session': None} if mode in {'absent', 'other-document', 'stale-pid'} else {
        'session': 'events', 'event': None if mode == 'malformed-event' else
        {'sequence': 2, 'action': 'color', 'id': 'reference'}}
    assert result.json() == expected
    assert snapshots(tmp_path) == before and documents[0] not in state._sessions


def test_vr_origin_and_remote_access_remain_closed(documents, isolated):
    assert isolated.get(VR, headers={'Origin': 'https://untrusted.example'}).status_code == 403
    with TestClient(StrictPartDispatch(forbidden_app), client=('192.0.2.1', 1234),
                    headers={'X-NADOC-Doc': documents[0]}) as client:
        assert client.get(VR).status_code == 403


@pytest.mark.parametrize('path', [VR, PEERS])
@pytest.mark.parametrize('query', ['verified=true', 'workspace=/tmp', 'doc=a&doc=b'])
def test_closed_query_never_calls_service(isolated, monkeypatch, path, query):
    monkeypatch.setattr(reads, 'StatusReader', lambda: pytest.fail('Unsupported query read'))
    monkeypatch.setattr(status, 'peer_statuses', lambda *a, **k: pytest.fail('Unsupported query probed'))
    # Duplicate doc selects a different policy at dispatcher, so use repeated current doc.
    if query.startswith('doc='):
        doc = isolated.headers['X-NADOC-Doc'];query = f'doc={doc}&doc={doc}'
    assert isolated.get(path + '?' + query).status_code == 422


@pytest.mark.parametrize('path', [VR, PEERS])
def test_mutations_stay_closed(isolated, path):
    for method in ('post', 'put', 'patch', 'delete'):
        assert getattr(isolated, method)(path).status_code == 403


@pytest.mark.parametrize('mode', ['online', 'offline', 'repair'])
def test_peer_status_read_only_and_ordinary_repair_preserved(isolated, tmp_path, monkeypatch, mode):
    registry = PeerRegistry(tmp_path)
    registry.register(peer_id='peer', name='Peer', base_url='http://host.ts.net', token='secret-test-token')
    before = snapshots(tmp_path)
    calls = []
    def transport(request):
        calls.append(str(request.url))
        assert 'authorization' not in request.headers
        return httpx.Response(200 if mode == 'online' or (mode == 'repair' and request.url.scheme == 'https') else 503)
    original = httpx.AsyncClient
    monkeypatch.setattr(status.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(transport), **kw))
    result = isolated.get(PEERS)
    assert result.status_code == 200, result.text
    expected = {'id': 'peer', 'name': 'Peer', 'base_url': 'https://host.ts.net' if mode == 'repair' else 'http://host.ts.net',
                'online': mode != 'offline'}
    assert result.json() == {'peers': [expected]} and 'secret-test-token' not in result.text
    assert snapshots(tmp_path) == before
    n = len(calls)
    assert isolated.get(PEERS).json() == result.json() and len(calls) == n
    ordinary = asyncio.run(status.peer_statuses(tmp_path))
    assert ordinary == result.json()
    assert (snapshots(tmp_path) != before) == (mode == 'repair')


@pytest.mark.parametrize('path', [VR, PEERS])
@pytest.mark.parametrize('change', ['policy', 'session'])
def test_late_status_cannot_cross_policy_or_session(documents, isolated, monkeypatch, path, change):
    def changed():
        if change == 'policy': policy._install_configuration(policy.current_configuration())
        else:
            with state._lock: state._session()
        return {'session': None} if path == VR else {'peers': []}
    if path == VR:
        from backend.api import vr_references
        monkeypatch.setattr(vr_references, 'read_references', lambda *a, **k: changed())
    else:
        async def peers(*a, **k): return changed()
        monkeypatch.setattr(status, 'peer_statuses', peers)
    assert isolated.get(path).status_code == 409


@pytest.mark.parametrize('path', [VR, PEERS])
def test_oversized_status_file_refuses(isolated, tmp_path, path):
    from backend.core.part_document_io import MAX_METADATA_BYTES
    target = vr._STATE_PATH if path == VR else PeerRegistry(tmp_path).peers_path
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('wb') as stream: stream.truncate(MAX_METADATA_BYTES + 1)
    assert isolated.get(path).status_code == 413


def test_status_reader_cumulative_and_nonregular_limits(tmp_path):
    reader = StatusReader();reader.remaining = 5
    p = tmp_path / 'file';p.write_text('123')
    assert reader(p) == '123'
    with pytest.raises(StatusReadLimit): reader(p)
    fifo = tmp_path / 'pipe';os.mkfifo(fifo)
    with pytest.raises(StatusReadLimit): StatusReader()(fifo)


@pytest.mark.parametrize('fault', ['count', 'field'])
def test_peer_record_bounds_refuse_before_network(isolated, tmp_path, monkeypatch, fault):
    record = {'id': 'p', 'name': 'Peer', 'base_url': 'https://example.invalid', 'token': 'secret'}
    data = {str(i): record for i in range(129)} if fault == 'count' else {'p': {**record, 'name': 'x' * 4097}}
    path = PeerRegistry(tmp_path).peers_path;path.parent.mkdir()
    path.write_text(json.dumps(data))
    monkeypatch.setattr(status, '_probe_peer', lambda *a, **k: pytest.fail('Oversized peer probed'))
    assert isolated.get(PEERS).status_code == 413


def test_output_budget_refuses(isolated, monkeypatch):
    # Service reads use their own wire allowance on the shared bounded contract.
    from backend.api import part_strict_service_reads as service
    monkeypatch.setattr(service, 'SERVICE_MAX_BYTES', 2)
    assert isolated.get(VR).status_code == 413


def test_cancelled_vr_reader_drains_thread(documents, monkeypatch):
    from threading import Event
    from fastapi import Request
    from backend.api import vr_references
    from backend.api.part_strict_reads import CONTEXT_KEY, StrictRequestContext
    from tests.test_part_strict_http import scope
    started, release, finished = Event(), Event(), Event()
    def read(*a, **k):
        started.set()
        assert release.wait(2)
        finished.set()
        return {'session': None}
    monkeypatch.setattr(vr_references, 'read_references', read)
    request_scope = scope(documents[0], VR, 'GET')
    request_scope[CONTEXT_KEY] = StrictRequestContext(documents[0], policy.resolve(documents[0]).generation)
    async def run():
        task = asyncio.create_task(reads.references(Request(request_scope)))
        await asyncio.to_thread(started.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError): await task
        assert finished.is_set()
    asyncio.run(run())
