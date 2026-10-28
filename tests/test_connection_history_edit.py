"""Ordinary connection edits bind the selected recipe and return its full display."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import crud, state, routes_connection_versions as routes
from tests.connection_history_fixture import fixture, enabled
from tests.test_part_pattern_recording import document as document, saved, unchanged
from tests.test_part_pending_connection_versions import proof


def connected(document):
    state.load_design(fixture('connection-opposite'))
    source = document.design
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(crud.router)
    client = TestClient(app)
    with enabled():
        response = client.post('/design/connection-versions/connect', json={
            'overhang_a_id': source.overhangs[0].id, 'overhang_b_id': source.overhangs[1].id,
            'connection_type': 'root-to-root-ssdna-linker', 'bridge_length': 7})
    assert response.status_code == 201, response.text
    return client, len(document.design.feature_log) - 1


def body(document, index):
    return {'params': {'bridge_length': 11}, 'expected_design_id': document.design.id,
            'expected_revision': document.revision, 'expected_feature_id': document.design.feature_log[index].id}


def test_history_edit_returns_complete_source_bound_geometry_with_one_undo(document):
    client, index = connected(document)
    before = saved(document)
    with client:
        response = client.post(f'/design/features/{index}/edit', json=body(document, index))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result.get('nucleotides') and not result.get('partial_geometry')
    assert not result.get('geometry_skipped')
    assert result.get('diff_kind') not in {'cluster_only', 'positions_only'}
    assert document.design.overhang_connections[0].length_value == 11
    assert len(document.history) == len(before[3]) + 1
    assert proof(document.design)['status'] == 'verified'
    state.undo()
    assert document.design.overhang_connections[0].length_value == 7


def test_refused_edit_identifies_its_first_feature_and_preserves_the_recipe(document):
    client, index = connected(document)
    request = body(document, index)
    request['params']['bridge_length'] = 5000
    before = saved(document)
    with client:
        response = client.post(f'/design/features/{index}/edit', json=request)
    assert response.status_code == 409, response.text[:1000]
    assert response.json()['detail']['feature_id'] == document.design.feature_log[index].id
    unchanged(document, before)


@pytest.mark.parametrize('field,value', [('expected_design_id', 'other'),
    ('expected_revision', -1), ('expected_feature_id', 'other')])
def test_stale_history_editor_cannot_rebind_to_current_recipe(document, field, value):
    client, index = connected(document)
    request = body(document, index)
    request[field] = request[field] - 1 if field == 'expected_revision' else value
    before = saved(document)
    with client:
        response = client.post(f'/design/features/{index}/edit', json=request)
    assert response.status_code == 409, response.text[:1000]
    unchanged(document, before)


def test_enabled_native_connection_refuses_unsupported_source_without_legacy_retry(document, monkeypatch):
    from tests.test_part_pending_connection_versions import append
    source = append(fixture('connection-opposite'), 'nanoparticle-create', {
        '_proof_version': 1, 'nanoparticle_version': 1, 'nanoparticle_id': 'parked-asset',
        'diameter_nm': 10.0}, 'parked-asset-create')
    state.load_design(source)
    before = saved(document)
    def legacy(*args, **kwargs):
        pytest.fail('Unsupported native scope retried through unrecorded compatibility Apply')
    monkeypatch.setattr(routes, '_apply_connection_version_legacy', legacy)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client, enabled():
        response = client.post('/design/connection-versions/connect', json={
            'overhang_a_id': source.overhangs[0].id, 'overhang_b_id': source.overhangs[1].id,
            'connection_type': 'root-to-root', 'bridge_length': 0})
    assert response.status_code == 422, response.text[:1000]
    unchanged(document, before)


def test_metadata_body_cannot_cross_a_document_reset(document, monkeypatch):
    from backend.api import part_connection_composition_route as transport
    client, _ = connected(document)
    version = document.design.connection_versions[0]
    caller_context = saved(document)[5:]
    read = transport.read_operation_json
    after_reset = []
    async def changed(request, **kwargs):
        values = await read(request, **kwargs)
        state.load_design(document.design.model_copy(deep=True))
        after_reset.append(saved(document))
        return values
    monkeypatch.setattr(transport, 'read_operation_json', changed)
    with client, enabled():
        response = client.patch(f'/design/connection-versions/{version.id}', json={'name': 'Stale name'})
    assert response.status_code == 409, response.text[:1000]
    assert response.json()['detail']['code'] == 'source_changed'
    # HTTP request revision metadata belongs to its worker context; the caller's
    # context stays unchanged while both observe the same reset document.
    unchanged(document, (*after_reset[0][:5], *caller_context))
