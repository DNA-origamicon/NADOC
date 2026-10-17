"""First-time direct Connect owns its HTTP source and one undo transaction."""

import pytest

from tests.test_part_connection_compose import document as document, choices
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import authored, native_prefix as native_prefix, proof
from tests.test_part_connection_direct_compose import ACTION


@pytest.fixture
def direct_document(document, monkeypatch):
    from backend.api import routes_connection_versions as routes
    monkeypatch.setattr(routes, 'NATIVE_DIRECT_CONNECT_ENABLED', True)
    return document


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_connect_http_one_feature_one_undo(direct_document, connection_type):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state

    doc = direct_document
    before = doc.source.model_dump_json()
    body = choices(doc.source).model_copy(update={'connection_type': connection_type})
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/connect', json=body.model_dump())
    assert response.status_code == 201, response.text
    result = doc.session.design
    assert result.feature_log[-1].params['action'] == ACTION
    assert len(result.feature_log) == len(doc.source.feature_log) + 1
    assert len(doc.session.history) == 1 and doc.session.revision == 5
    assert proof(result)['status'] == 'verified'
    assert doc.source.model_dump_json() == before
    state.undo()
    assert authored(doc.session.design) == authored(doc.source)
    assert not doc.session.design.connection_versions
    state.redo()
    assert authored(doc.session.design) == authored(result)


@pytest.mark.parametrize('failure', ['materialize', 'validate'])
def test_direct_connect_failure_preserves_source_without_legacy_retry(direct_document, monkeypatch, failure):
    from backend.api import state, routes_connection_versions as routes, part_connection_direct_composition as composition
    doc = direct_document
    before = doc.source.model_dump_json()
    doc.session.redo.append(doc.source.model_copy(deep=True))

    def fail(*_args, **_kwargs):
        raise RuntimeError('injected direct Connect failure')

    monkeypatch.setattr(composition if failure == 'materialize' else state,
                        'materialize' if failure == 'materialize' else 'validate_design', fail)
    monkeypatch.setattr(routes, '_apply_connection_version_legacy', lambda *_a, **_kw: pytest.fail('legacy retry'))
    with pytest.raises(RuntimeError, match='injected direct Connect failure'):
        routes.create_and_apply_connection_version(choices(doc.source).model_copy(update={'connection_type': 'root-to-root'}))
    assert doc.session.design.model_dump_json() == before
    assert doc.source.model_dump_json() == before
    assert not doc.session.history and len(doc.session.redo) == 1 and doc.session.revision == 4


def test_direct_connect_http_source_changed_during_acquisition(direct_document, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    from backend.api import part_connection_composition_route as transport
    doc = direct_document
    before = doc.source.model_dump_json()
    reader = transport.read_operation_json

    async def changed(request, **kwargs):
        result = await reader(request, **kwargs)
        with state._lock:
            state._bump_revision(doc.session)
        return result

    monkeypatch.setattr(transport, 'read_operation_json', changed)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/connect', json=choices(doc.source).model_copy(
            update={'connection_type': 'root-to-root'}).model_dump())
    assert response.status_code == 409 and response.json()['detail']['code'] == 'source_changed'
    assert doc.session.design.model_dump_json() == before and not doc.session.history


@pytest.mark.parametrize('guard', ['cursor', 'loadout'])
def test_direct_connect_document_guards_precede_preparation(direct_document, monkeypatch, guard):
    from fastapi import HTTPException
    from backend.api import routes_connection_versions as routes, part_connection_direct_composition as composition
    from backend.core.models import DesignLoadout

    doc = direct_document
    if guard == 'cursor':
        doc.source.feature_log_cursor = 0
    else:
        doc.source.loadouts = [DesignLoadout(id='protected', name='Protected', protected=True)]
        doc.source.active_loadout_id = 'protected'
    monkeypatch.setattr(composition, 'prepare', lambda *_: pytest.fail('prepared before guard'))
    with pytest.raises(HTTPException) as caught:
        routes.create_and_apply_connection_version(choices(doc.source).model_copy(update={'connection_type': 'root-to-root'}))
    assert caught.value.status_code == 409
    assert not doc.session.history
