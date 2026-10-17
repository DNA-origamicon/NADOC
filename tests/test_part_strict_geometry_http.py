"""Complete gated HTTP workflows and document ownership during body reads."""

import asyncio
import json
from threading import Event

from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request
import pytest

from backend.api import state, part_immutable_recovery as recovery
from backend.api import part_strict_geometry_http as routes
from backend.api import part_immutable_geometry_publication as authority
from backend.api import part_immutable_geometry_host as host
from backend.api.part_strict_http import StrictPartDispatch
from backend.api.part_strict_reads import CONTEXT_KEY, StrictRequestContext
from backend.api.part_immutable_revision import materialize_revision
from backend.core.part_command_errors import CommandContractError
from tests.test_part_immutable_recovery import document as document, immediate as _recovery_fixture
from tests.test_part_immutable_geometry_host import immediate as _geometry_fixture, available
from tests.test_part_immutable_geometry_recovery import store, KINDS
from tests.test_part_strict_http import forbidden_app, invoke, response, scope, JOBS
from tests.test_group_organization_history import _verified

immediate_recovery = _recovery_fixture
immediate_geometry = _geometry_fixture

PREFIX = routes.PREFIX


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(authority, 'ENABLED', True)


@pytest.fixture
def client(document):
    doc, _ = document
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        yield client


def recover(client):
    started = client.post(PREFIX + '/recovery/jobs', json={'expected_revision': 0})
    assert started.status_code == 202, started.text
    identity = started.json()['job_id']
    result = client.get(f'{JOBS}/{identity}')
    assert result.json()['result']['status'] == 'ready', result.text
    committed = client.post(f'{JOBS}/{identity}/commit')
    assert committed.status_code == 200, committed.text
    return committed.json()


def edit_body(operation, revision=1):
    header = operation['header']
    return {'expected_revision': revision, 'expected_design_id': header['source_design_id'],
        'expected_kind': header['expected_kind'], 'expected_feature_id': header['expected_feature_id'],
        'params': operation['request']['params']}


@pytest.mark.parametrize('kind', KINDS)
def test_http_recovery_edit_save_undo_redo(client, immediate_recovery, immediate_geometry, kind):
    doc, owner = immediate_recovery
    original, operation = store(immediate_recovery, kind)
    recover(client)
    index = operation['request']['index']
    changed = client.post(f'{PREFIX}/features/{index}/edit', json=edit_body(operation))
    assert changed.status_code == 200, changed.text
    assert changed.json()['revision'] == 2
    published = state._sessions[doc].design
    _verified(materialize_revision(published))
    body = {'expected_design_id': changed.json()['design_id'], 'expected_revision': 2}
    saved = client.post(PREFIX + '/save', json=body)
    assert saved.status_code == 200 and saved.json()['current'] is True
    assert saved.json()['saved_revision'] == 2 and owner.read_pending(doc).payload == published.payload
    undo = client.post(PREFIX + '/history/undo', json=body)
    assert undo.status_code == 200 and undo.json()['revision'] == 3
    assert state._sessions[doc].design.payload == original.payload
    redo = client.post(PREFIX + '/history/redo', json={**body, 'expected_revision': 3})
    assert redo.status_code == 200 and redo.json()['revision'] == 4
    assert state._sessions[doc].design is published


def test_real_http_workers_and_durable_acknowledgement(client, document):
    doc, owner = document
    _, operation = store(document)
    recover(client)
    changed = client.post(PREFIX + '/features/0/edit', json=edit_body(operation))
    assert changed.status_code == 200, changed.text
    saved = client.post(PREFIX + '/save', json={
        'expected_design_id': changed.json()['design_id'], 'expected_revision': 2})
    assert saved.status_code == 200 and saved.json()['current'] is True
    assert owner.read_pending(doc).payload == state._sessions[doc].design.payload


def test_disabled_geometry_route_refuses_before_reading_body(document, monkeypatch):
    doc, _ = document
    monkeypatch.setattr(authority, 'ENABLED', False)
    sent, reads = invoke(StrictPartDispatch(forbidden_app), scope(doc, PREFIX + '/recovery/jobs',
        headers=[(b'content-type', b'application/json')]))
    assert response(sent)[0] == 409 and not reads
    assert doc not in state._sessions


@pytest.mark.parametrize('recovering', [False, True])
def test_document_replacement_during_body_acquisition_is_refused(document, immediate_recovery, client, recovering):
    doc, _ = document
    _, operation = store(document)
    if not recovering:
        recover(client)
    old = state._sessions.get(doc)
    path = PREFIX + ('/recovery/jobs' if recovering else '/features/0/edit')
    body = {'expected_revision': 0} if recovering else edit_body(operation)

    async def receive():
        state.drop_doc(doc)
        with state._lock:
            replacement = state._session()
            if old is not None:
                replacement.design, replacement.revision = old.design, old.revision
        return {'type': 'http.request', 'body': json.dumps(body).encode(), 'more_body': False}

    sent, _ = invoke(StrictPartDispatch(forbidden_app), scope(doc, path,
        headers=[(b'content-type', b'application/json')]), receive=receive)
    assert response(sent)[0] == 409
    assert response(sent)[1]['detail']['code'] == 'source_changed'


def test_reopen_between_handler_check_and_host_admission_is_refused(client, immediate_recovery, monkeypatch):
    doc, _ = immediate_recovery
    _, operation = store(immediate_recovery)
    recover(client)
    old = state._sessions[doc]
    original = host.edit

    def changed(*args, **kwargs):
        state.drop_doc(doc)
        with state._lock:
            current = state._session()
            current.design, current.revision = old.design, old.revision
        return original(*args, **kwargs)

    monkeypatch.setattr(host, 'edit', changed)
    result = client.post(PREFIX + '/features/0/edit', json=edit_body(operation))
    assert result.status_code == 409 and result.json()['detail']['code'] == 'source_changed'
    assert not state._sessions[doc].history


def test_recovery_reopen_between_handler_check_and_admission_is_refused(client, document, monkeypatch):
    doc, _ = document
    store(document)
    original = recovery.start_geometry

    def changed(*args, **kwargs):
        with state._lock:
            state._session()
        return original(*args, **kwargs)

    monkeypatch.setattr(recovery, 'start_geometry', changed)
    result = client.post(PREFIX + '/recovery/jobs', json={'expected_revision': 0})
    assert result.status_code == 409 and state._sessions[doc].design is None


@pytest.mark.parametrize('extra', [{'verified': True}, {'expected_source': {}}, {'candidate': {}}])
def test_body_cannot_supply_authority_or_source_handles(client, immediate_recovery, extra):
    doc, _ = immediate_recovery
    _, operation = store(immediate_recovery)
    recover(client)
    source = state._sessions[doc].design
    result = client.post(PREFIX + '/features/0/edit', json={**edit_body(operation), **extra})
    assert result.status_code == 422 and state._sessions[doc].design is source


@pytest.mark.parametrize('fault', ['write_failure', 'newer_revision'])
def test_save_acknowledgement_never_claims_unsaved_current_state(client, immediate_recovery, monkeypatch, fault):
    doc, owner = immediate_recovery
    _, operation = store(immediate_recovery)
    recover(client)
    original = owner.write_capture

    def write(capture):
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        if fault == 'write_failure':
            raise CommandContractError('injected write failure', code='strict_cache_changed')
        revision = original(capture)
        with state._lock:
            state._sessions[doc].revision += 1
        return revision

    monkeypatch.setattr(owner, 'write_capture', write)
    result = client.post(PREFIX + '/save', json={
        'expected_design_id': operation['header']['source_design_id'], 'expected_revision': 1})
    if fault == 'write_failure':
        assert result.status_code == 409
    else:
        assert result.status_code == 200
        assert result.json()['saved_revision'] == 1 and result.json()['current'] is False


def test_disconnect_cancels_native_work_and_drains_before_response(document, immediate_recovery, immediate_geometry, client, monkeypatch):
    doc, _ = document
    _, operation = store(document)
    recover(client)
    source = state._sessions[doc].design
    started = Event()
    event = []
    original = host.edit

    def edit(*args, **kwargs):
        event.append(kwargs['cancelled'])
        return original(*args, **kwargs)

    def native_start():
        started.set()
        assert event[0].wait(2), 'Disconnect did not reach the native owner'

    monkeypatch.setattr(host, 'edit', edit)
    immediate_geometry.start = native_start
    generation = recovery.policy.resolve(doc).generation
    request_scope = scope(doc, PREFIX + '/features/0/edit')
    request_scope[CONTEXT_KEY] = StrictRequestContext(doc, generation)
    request_scope[routes.CONTEXT_KEY] = routes.capture_context(doc, generation, recovering=False)

    async def disconnected():
        # Starlette polls receive within a cancelled scope; keep it nonblocking.
        if started.is_set():
            return {'type': 'http.disconnect'}
        return {'type': 'http.request', 'body': b'', 'more_body': False}

    async def exercise():
        with pytest.raises(HTTPException) as error:
            await routes.edit(0, routes.EditRequest(**edit_body(operation)), Request(request_scope, disconnected))
        assert error.value.detail['code'] == 'cancelled'

    asyncio.run(exercise())
    assert state._sessions[doc].design is source and not state._sessions[doc].history
    assert immediate_geometry.closed == 1
    available()
