"""Geometry creation shares durable ownership without accepting authored content."""

import json

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import state, part_immutable_creation as creation
from backend.api import part_immutable_geometry_publication as authority
from backend.api import part_publication_permit as permits
from backend.api.part_immutable_revision import materialize_revision, revision_metadata
from backend.api.part_strict_http import StrictPartDispatch
from backend.api.part_strict_geometry_http import PREFIX
from tests.test_part_immutable_recovery import document as document, immediate as _immediate
from tests.test_part_strict_geometry_http import recover
from tests.test_part_strict_http import forbidden_app, invoke, response, scope
from tests.test_group_organization_history import _verified

immediate = _immediate


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(authority, 'ENABLED', True)


@pytest.mark.parametrize('lattice', ['HONEYCOMB', 'SQUARE'])
def test_create_save_close_recover_exact_file(document, immediate, lattice):
    doc, owner = document
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        created = client.post(PREFIX + '/empty', json={'name': 'New geometry', 'lattice_type': lattice})
        assert created.status_code == 201, created.text
        source = state._sessions[doc].design
        metadata = revision_metadata(source)
        assert metadata.scope_tag == 'native_extrusion_v1' and metadata.history_rows == 0
        assert metadata.name == 'New geometry' and metadata.lattice_type == lattice
        assert owner.read_pending(doc).payload == source.payload
        _verified(materialize_revision(source))
        assert not state._sessions[doc].history
        saved = client.post(PREFIX + '/save', json={'expected_design_id': metadata.design_id, 'expected_revision': 1})
        assert saved.json()['current'] is True
        state.drop_doc(doc)
        refused = client.post(PREFIX + '/empty', json={})
        assert refused.status_code == 409 and refused.json()['detail']['code'] == 'strict_cache_pending'
        assert owner.read_pending(doc).payload == source.payload
        recover(client)
        assert state._sessions[doc].design.payload == source.payload


@pytest.mark.parametrize('when', ['admission', 'prepared', 'written', 'retained'])
def test_revoked_gate_never_publishes_geometry(document, monkeypatch, when):
    doc, owner = document
    if when == 'admission':
        monkeypatch.setattr(authority, 'ENABLED', False)
    else:
        from backend.api import part_immutable_storage as storage
        target, name = ((permits, 'prepare_admitted_empty') if when == 'prepared' else
                        (owner, 'write_initial') if when == 'written' else (storage, 'retained_history'))
        original = getattr(target, name)

        def revoke(*args, **kwargs):
            result = original(*args, **kwargs)
            monkeypatch.setattr(authority, 'ENABLED', False)
            return result

        monkeypatch.setattr(target, name, revoke)
    with pytest.raises(HTTPException):
        creation.create_durable_geometry_empty()
    session = state._sessions.get(doc)
    assert session is None or (session.design is None and session.revision == 0 and not session.history)
    if when in {'written', 'retained'}:
        assert owner.read_pending(doc).payload and owner.write_if_immutable(doc) is None
    else:
        assert not list(owner.cache.directory.glob('*.partcache'))


@pytest.mark.parametrize('fault', ['write', 'publication', 'close'])
def test_creation_failure_preserves_recoverable_file_and_source(document, monkeypatch, fault):
    doc, owner = document
    original = owner.write_initial

    def write(*args):
        assert state._lock.acquire(blocking=False)
        state._lock.release()
        lease = original(*args)
        if fault == 'write':
            raise RuntimeError('injected post-write failure')
        if fault == 'close':
            state.drop_doc(doc)
        return lease

    monkeypatch.setattr(owner, 'write_initial', write)
    if fault == 'publication':
        original_bump = state._bump_revision

        def bump(session):
            original_bump(session)
            raise RuntimeError('injected publication failure')

        monkeypatch.setattr(state, '_bump_revision', bump)
    with pytest.raises((RuntimeError, HTTPException)):
        creation.create_durable_geometry_empty()
    assert owner.read_pending(doc).payload and owner.write_if_immutable(doc) is None
    assert doc not in state._sessions or state._sessions[doc].design is None


def test_reopen_while_reading_creation_body_is_rejected(document):
    doc, owner = document

    async def receive():
        with state._lock:
            state._session()
        return {'type': 'http.request', 'body': json.dumps({}).encode(), 'more_body': False}

    sent, _ = invoke(StrictPartDispatch(forbidden_app), scope(doc, PREFIX + '/empty',
        headers=[(b'content-type', b'application/json')]), receive=receive)
    assert response(sent)[0] == 409 and state._sessions[doc].design is None
    assert not list(owner.cache.directory.glob('*.partcache'))


def test_reopen_at_creation_admission_is_rejected(document, monkeypatch):
    doc, owner = document
    original = creation.create_durable_geometry_empty

    def reopen(*args, **kwargs):
        with state._lock:
            state._session()
        return original(*args, **kwargs)

    monkeypatch.setattr(creation, 'create_durable_geometry_empty', reopen)
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        result = client.post(PREFIX + '/empty', json={})
    assert result.status_code == 409 and state._sessions[doc].design is None
    assert not list(owner.cache.directory.glob('*.partcache'))


@pytest.mark.parametrize('body', [{'scope_tag': 'native_extrusion_v1'}, {'helices': []}, {'name': ' '}, {'lattice_type': 'OTHER'}])
def test_creation_rejects_authored_content_and_invalid_options(document, body):
    doc, owner = document
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        result = client.post(PREFIX + '/empty', json=body)
    assert result.status_code == 422 and doc not in state._sessions
    assert not list(owner.cache.directory.glob('*.partcache'))


def test_created_geometry_recovers_through_real_worker(document):
    doc, owner = document
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        result = client.post(PREFIX + '/empty', json={})
        assert result.status_code == 201, result.text
        payload = owner.read_pending(doc).payload
        state.drop_doc(doc)
        recover(client)
        assert state._sessions[doc].design.payload == payload


def test_disabled_creation_refuses_before_body_acquisition(document, monkeypatch):
    doc, owner = document
    monkeypatch.setattr(authority, 'ENABLED', False)
    sent, reads = invoke(StrictPartDispatch(forbidden_app), scope(doc, PREFIX + '/empty',
        headers=[(b'content-type', b'application/json')]))
    assert response(sent)[0] == 409 and not reads and doc not in state._sessions
    assert not list(owner.cache.directory.glob('*.partcache'))
