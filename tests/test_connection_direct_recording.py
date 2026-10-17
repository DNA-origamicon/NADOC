"""Ordinary direct Apply owns one guarded transaction, including failures."""

import pytest

from tests.test_part_connection_compose import document as document
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import authored, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, ACTION


@pytest.fixture(params=[False, True], ids=["literal-v1", "creator-v2"])
def direct_document(document, monkeypatch, request):
    from backend.api import routes_connection_versions as routes

    monkeypatch.setattr(routes, 'NATIVE_CONNECTION_OWNER_SELECTION_ENABLED', request.param)
    monkeypatch.setattr(routes, 'NATIVE_DIRECT_APPLY_ENABLED', True)
    document.source = pending(document.source)
    document.session.design = document.source
    return document


def test_direct_http_apply_reapply_undo_redo_and_cold_replay(direct_document):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state

    doc = direct_document
    before = doc.source.model_dump_json()
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/candidate/apply')
        assert response.status_code == 200, response.text
        current = doc.session.design
        assert current.feature_log[-1].params['action'] == ACTION
        assert len(doc.session.history) == 1 and doc.session.revision == 5
        assert proof(current)['status'] == 'verified'
        assert doc.source.model_dump_json() == before
        response = client.post('/design/connection-versions/candidate/apply')
        assert response.status_code == 200, response.text
        replaced = doc.session.design
        assert len(replaced.duplexes) == 1
        assert replaced.duplexes[0].id != current.duplexes[0].id
        assert len(doc.session.history) == 2 and doc.session.revision == 6
        assert proof(replaced)['status'] == 'verified'
        state.undo()
        assert authored(doc.session.design) == authored(current)
        state.undo()
        assert authored(doc.session.design) == authored(doc.source)
        state.redo()
        assert authored(doc.session.design) == authored(current)


@pytest.mark.parametrize('failure', ['materialize', 'validate'])
def test_direct_failure_is_atomic_without_legacy_retry(direct_document, monkeypatch, failure):
    from backend.api import state, routes_connection_versions as routes, part_connection_direct_commands as commands

    doc = direct_document
    before = doc.source.model_dump_json()
    doc.session.redo.append(doc.source.model_copy(deep=True))

    def fail(*_args, **_kwargs):
        raise RuntimeError('injected direct failure')

    monkeypatch.setattr(commands if failure == 'materialize' else state,
                        'materialize' if failure == 'materialize' else 'validate_design', fail)
    monkeypatch.setattr(routes, '_apply_connection_version_legacy', lambda *_a, **_kw: pytest.fail('legacy retry'))
    with pytest.raises(RuntimeError, match='injected direct failure'):
        routes.apply_connection_version('candidate')
    assert doc.session.design.model_dump_json() == before
    assert doc.source.model_dump_json() == before
    assert not doc.session.history and len(doc.session.redo) == 1
    assert doc.session.revision == 4


@pytest.mark.parametrize('guard', ['cursor', 'loadout'])
def test_direct_document_guard_precedes_source_preparation(direct_document, monkeypatch, guard):
    from fastapi import HTTPException
    from backend.api import routes_connection_versions as routes, part_connection_direct_ownership as ownership
    from backend.core.models import DesignLoadout

    source = direct_document.source
    if guard == 'cursor':
        source.feature_log_cursor = 0
    else:
        source.loadouts = [DesignLoadout(id='protected', name='Protected', protected=True)]
        source.active_loadout_id = 'protected'
    monkeypatch.setattr(ownership, 'prepare', lambda *_: pytest.fail('prepared before guard'))
    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version('candidate')
    assert caught.value.status_code == 409
    assert not direct_document.session.history


def test_direct_apply_rejects_body_inputs(direct_document):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes

    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/candidate/apply', json={})
    assert response.status_code == 400
    assert not direct_document.session.history


def test_direct_http_refuses_source_changed_during_acquisition(direct_document, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    from backend.api import part_connection_composition_route as transport

    doc = direct_document
    before = doc.source.model_dump_json()
    reader = transport._no_apply_inputs

    async def changed(request, **kwargs):
        result = await reader(request, **kwargs)
        with state._lock:
            state._bump_revision(doc.session)
        return result

    monkeypatch.setattr(transport, '_no_apply_inputs', changed)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/candidate/apply')
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'source_changed'
    assert doc.session.design.model_dump_json() == before
    assert not doc.session.history
