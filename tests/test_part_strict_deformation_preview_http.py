"""Actual strict preview HTTP lifecycle and pre-body source ownership."""
import json

from fastapi.testclient import TestClient
import pytest

from backend.api import state, part_publication_policy as policy
from backend.api import part_deformation_preview_sessions as host
from backend.api import routes_part_deformation_preview as flags
from backend.api import part_strict_deformation_preview_http as routes
from backend.api import part_immutable_geometry_publication as authority
from backend.api.part_strict_http import StrictPartDispatch
from backend.api.part_immutable_revision import materialize_revision
from tests.test_part_immutable_geometry_host import document as document, saved
from tests.test_part_immutable_deformation_preview import cleanup as cleanup, install
from tests.test_part_deformation_preview_sessions import update, cancellation
from tests.test_part_deformation_preview import patch
from tests.test_group_organization_history import _verified
from tests.test_part_strict_http import forbidden_app, invoke, response, scope

PREFIX = routes.PREFIX


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(flags, 'DEFORMATION_PREVIEW_ENABLED', True)


@pytest.fixture
def client(document):
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': document[0]}) as value:
        yield value


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_native_http_lifecycle_receipt_and_exact_undo(document, client, kind):
    source, origin = install(document, kind)
    before = saved(document[1])
    opened = client.post(PREFIX, json=origin)
    assert opened.status_code == 200, opened.text
    opened = opened.json()
    evaluated = client.post(PREFIX + '/evaluate', json=update(opened, params=patch(kind)))
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()['stage'] == 'feature'
    assert saved(document[1]) == before
    applied = client.post(PREFIX + '/apply', json=update(opened, sequence=2, params=patch(kind)))
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    assert receipt['revision'] == 8 and len(document[1].history) == 1
    assert document[1].history[-1] is before[0]
    _verified(materialize_revision(document[1].design))
    recovered = client.post(PREFIX + '/status', json=cancellation(opened))
    assert recovered.status_code == 200
    assert {k: recovered.json()[k] for k in receipt} == receipt
    assert client.post(PREFIX + '/cancel', json=cancellation(opened)).json() == receipt
    assert client.post(PREFIX + '/apply', json=update(opened, sequence=3, params=patch(kind))).status_code == 409
    undone = client.post('/api/design/geometry-history/history/undo', json={
        'expected_design_id': source.id, 'expected_revision': 8})
    assert undone.status_code == 200 and document[1].design is before[0]


@pytest.mark.parametrize('gate', ['preview', 'immutable'])
def test_disabled_gate_refuses_before_body(document, monkeypatch, gate):
    install(document, 'bend')
    if gate == 'preview': monkeypatch.setattr(flags, 'DEFORMATION_PREVIEW_ENABLED', False)
    else: monkeypatch.setattr(authority, 'ENABLED', False)
    sent, reads = invoke(StrictPartDispatch(forbidden_app), scope(document[0], PREFIX,
        headers=[(b'content-type', b'application/json')]))
    assert response(sent)[0] in {403, 409} and not reads


@pytest.mark.parametrize('change', ['session', 'source', 'revision', 'policy', 'gate'])
def test_body_acquisition_change_cannot_rebind(document, monkeypatch, change):
    _, origin = install(document, 'bend')
    doc, session = document
    before = saved(session)
    async def receive():
        if change == 'session':
            state.drop_doc(doc)
            with state._lock:
                replacement = state._session();replacement.design, replacement.revision = session.design, session.revision
        elif change == 'source': session.design = None
        elif change == 'revision': session.revision += 1
        elif change == 'policy': policy._install_configuration(policy.current_configuration())
        else: monkeypatch.setattr(flags, 'DEFORMATION_PREVIEW_ENABLED', False)
        return {'type': 'http.request', 'body': json.dumps(origin).encode(), 'more_body': False}
    sent, _ = invoke(StrictPartDispatch(forbidden_app), scope(doc, PREFIX,
        headers=[(b'content-type', b'application/json')]), receive=receive)
    assert response(sent)[0] in {403, 409}
    assert doc not in host._entries and list(session.history) == before[2]


def test_reopen_between_handler_and_host_admission_refuses(document, client, monkeypatch):
    _, origin = install(document, 'bend')
    doc, session = document
    original = host.prepare
    def prepare(body):
        state.drop_doc(doc)
        with state._lock:
            replacement = state._session();replacement.design, replacement.revision = session.design, session.revision
        return original(body)
    monkeypatch.setattr(host, 'prepare', prepare)
    result = client.post(PREFIX, json=origin)
    assert result.status_code == 409 and result.json()['detail']['code'] == 'source_changed'
    assert doc not in host._entries


@pytest.mark.parametrize('path,method', [(PREFIX + '/create', 'POST'), (PREFIX, 'GET'),
    (PREFIX + '/other', 'POST'), (PREFIX + '/', 'POST')])
def test_unsupported_route_never_reads_or_falls_back(document, path, method):
    sent, reads = invoke(StrictPartDispatch(forbidden_app), scope(document[0], path, method))
    assert response(sent)[0] == 403 and not reads


@pytest.mark.parametrize('body', [b'[]', b'{"a":1,"a":2}', b'{"a":NaN}', b'{', b'{"verified":true}'])
def test_invalid_body_never_creates_lease(document, client, body):
    install(document, 'bend')
    result = client.post(PREFIX, content=body, headers={'Content-Type': 'application/json'})
    assert result.status_code == 422 and document[0] not in host._entries


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_http_cancel_discards_preview_without_canonical_change(document, client, kind):
    _, origin = install(document, kind)
    before = saved(document[1])
    opened = client.post(PREFIX, json=origin).json()
    evaluated = client.post(PREFIX + '/evaluate', json=update(opened, params=patch(kind)))
    assert evaluated.status_code == 200
    cancelled = client.post(PREFIX + '/cancel', json=cancellation(opened))
    assert cancelled.status_code == 200 and cancelled.json()['status'] == 'cancelled'
    assert saved(document[1]) == before and document[0] not in host._entries


def test_request_cancellation_drains_work_without_implicit_lease_cancel(monkeypatch):
    import asyncio
    from threading import Event
    started, release, finished = Event(), Event(), Event()
    def work(*args):
        started.set()
        try:
            assert release.wait(3)
        finally:
            finished.set()
    monkeypatch.setattr(routes.geometry, '_context', lambda request: object())
    monkeypatch.setattr(routes, '_respond', work)
    async def exercise():
        task = asyncio.create_task(routes._dispatch('apply', {}, object()))
        try:
            for _ in range(200):
                if started.is_set(): break
                await asyncio.sleep(.005)
            assert started.is_set()
            task.cancel()
            await asyncio.sleep(.02)
            assert not task.done() and not finished.is_set()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert finished.is_set()
    asyncio.run(exercise())


@pytest.mark.parametrize('operation', ['open', 'apply'])
def test_http_history_waits_for_passive_readiness(document, client, monkeypatch, operation):
    """HTTP dispatch preserves the shared reservation until a real poll drains."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from backend.api import part_immutable_display_reads as reads
    from tests.test_part_work_admission import observe_wait, submit
    from tests.test_part_immutable_geometry_host import available
    _, origin = install(document, 'bend')
    opened = client.post(PREFIX, json=origin).json() if operation == 'apply' else None
    before = saved(document[1])
    draining, release, closed = Event(), Event(), Event()
    original = reads.DisplayReadWorker
    class Held(original):
        def close(self):
            draining.set()
            assert release.wait(3)
            super().close()
            closed.set()
    monkeypatch.setattr(reads, 'DisplayReadWorker', Held)
    waiting = observe_wait(monkeypatch)
    with ThreadPoolExecutor(2) as pool:
        poll = submit(pool, lambda: client.get('/api/design/readiness'))
        try:
            assert draining.wait(2)
            work = submit(pool, lambda: client.post(
                PREFIX + '/apply' if opened else PREFIX,
                json=update(opened, params=patch('bend')) if opened else origin))
            assert waiting.wait(2) and not work.done()
            assert saved(document[1]) == before
            assert client.get('/api/design/readiness').status_code == 429
        finally:
            release.set()
        assert poll.result(timeout=3).status_code == 200
        result = work.result(timeout=4)
        assert result.status_code == 200, result.text
        assert closed.is_set()
    if opened:
        assert result.json()['revision'] == 8 and len(document[1].history) == 1
        _verified(materialize_revision(document[1].design))
    else:
        assert saved(document[1]) == before
    available()
