"""Private linker-v3 routes share native direct restoration and atomic recording."""

import pytest

from tests.test_part_connection_compose import document as document, choices
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, authored, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, params as direct_params


@pytest.fixture
def inverse_document(document, monkeypatch):
    from backend.api import routes_connection_versions as routes
    monkeypatch.setattr(routes, 'NATIVE_LINKER_V3_ENABLED', True)
    source = pending(document.source)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    document.source = source
    document.session.design = source
    return document


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('connection_type', ['root-to-root-ssdna-linker', 'root-to-root-indirect'])
def test_inverse_http_one_undo_and_independent_replay(inverse_document, connection_type, combined):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    doc = inverse_document
    if not combined:
        doc.source = pending(doc.source, connection_type, 'replacement')
        doc.session.design = doc.source
    before = doc.source.model_dump_json()
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/connect', json=choices(doc.source).model_copy(
            update={'connection_type': connection_type}).model_dump()) if combined else client.post(
                '/design/connection-versions/replacement/apply')
    assert response.status_code == (201 if combined else 200), response.text
    result = doc.session.design
    marker = 'connection_composition_version' if combined else 'connection_application_version'
    assert result.feature_log[-1].params[marker] == 3
    assert not result.duplexes and not result.overhang_bindings
    assert len(doc.session.history) == 1 and doc.session.revision == 5
    assert proof(result)['status'] == 'verified'
    assert doc.source.model_dump_json() == before
    state.undo()
    assert authored(doc.session.design) == authored(doc.source)
    state.redo()
    assert authored(doc.session.design) == authored(result)
    # Once direct ownership is gone, v3 must also handle ordinary linker-only
    # reapplication; enabling inverse support must not break the next Apply.
    with TestClient(app) as client:
        response = client.post(f'/design/connection-versions/{result.connection_versions[-1].id}/apply')
    assert response.status_code == 200, response.text
    reapplied = doc.session.design
    assert len(reapplied.overhang_connections) == 1
    assert reapplied.overhang_connections[0].id != result.overhang_connections[0].id
    assert len(doc.session.history) == 2
    assert proof(reapplied)['status'] == 'verified'


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('failure', ['materialize', 'validate'])
def test_inverse_failure_does_not_retry_or_change_source(inverse_document, combined, failure, monkeypatch):
    from backend.api import routes_connection_versions as routes, state
    from backend.api import part_connection_application_commands as application
    doc = inverse_document
    if not combined:
        doc.source = pending(doc.source, 'root-to-root-indirect', 'replacement')
        doc.session.design = doc.source
    before = doc.source.model_dump_json()
    doc.session.redo.append(doc.source.model_copy(deep=True))

    def fail(*_args, **_kw):
        raise RuntimeError('injected inverse failure')

    monkeypatch.setattr(application if failure == 'materialize' else state,
                        '_materialize' if failure == 'materialize' else 'validate_design', fail)
    monkeypatch.setattr(routes, '_apply_connection_version_legacy', lambda *_a, **_kw: pytest.fail('legacy retry'))
    with pytest.raises(RuntimeError, match='injected inverse failure'):
        if combined:
            routes.create_and_apply_connection_version(choices(doc.source).model_copy(update={'connection_type': 'root-to-root-indirect'}))
        else:
            routes.apply_connection_version('replacement')
    assert doc.session.design.model_dump_json() == before
    assert doc.source.model_dump_json() == before
    assert not doc.session.history and len(doc.session.redo) == 1 and doc.session.revision == 4
