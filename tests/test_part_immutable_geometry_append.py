"""New geometry is authored through inputs and independently reproducible history."""

from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from backend.api import state
from backend.api import part_immutable_geometry_publication as authority
from backend.api import part_immutable_geometry_worker as worker
from backend.api.part_strict_http import StrictPartDispatch
from backend.api.part_strict_geometry_http import PREFIX
from backend.api.part_immutable_revision import materialize_revision
from tests.test_part_immutable_recovery import document as document
from tests.test_part_immutable_geometry_host import immediate as _geometry
from tests.test_part_strict_http import forbidden_app
from tests.test_part_strict_geometry_http import recover
from tests.test_part_extrusion_edit_routes import KINDS, recipe
from tests.test_group_organization_history import _verified
from backend.api.part_extrusion_edit_inputs import EDIT_FIELDS

immediate_geometry = _geometry


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(authority, 'ENABLED', True)


@pytest.fixture
def client(document):
    doc, _ = document
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        yield client


def add(client, kind, params, revision):
    return client.post(PREFIX + '/features', json={'kind': kind, 'params': params,
        'expected_design_id': revision['design_id'], 'expected_revision': revision['revision']})


def authored(entry):
    return {k: v for k, v in entry.params.items() if k in EDIT_FIELDS[entry.op_kind]}


def test_real_create_append_edit_save_undo_redo_recover(document, client):
    doc, owner = document
    created = client.post(PREFIX + '/empty', json={}).json()
    added = add(client, 'bundle-create', {'cells': [[0, 0]], 'length_bp': 21}, created)
    assert added.status_code == 200, added.text
    first = added.json()
    tail = add(client, 'extrude-segment', {'cells': [[4, 4]], 'length_bp': 7}, first)
    assert tail.status_code == 200, tail.text
    changed = client.post(PREFIX + '/features/0/edit', json={
        'expected_design_id': first['design_id'], 'expected_revision': tail.json()['revision'],
        'expected_kind': 'bundle-create', 'expected_feature_id': first['feature_id'],
        'params': {'length_bp': 14}})
    assert changed.status_code == 200, changed.text
    source = state._sessions[doc].design
    model = materialize_revision(source)
    assert len(model.feature_log) == 2 and model.feature_log[0].id == first['feature_id']
    assert model.feature_log[0].params['length_bp'] == 14
    _verified(model)
    guards = {'expected_design_id': first['design_id'], 'expected_revision': changed.json()['revision']}
    assert client.post(PREFIX + '/save', json=guards).json()['current']
    assert owner.read_pending(doc).payload == source.payload
    undone = client.post(PREFIX + '/history/undo', json=guards).json()
    redone = client.post(PREFIX + '/history/redo', json={**guards, 'expected_revision': undone['revision']})
    assert redone.status_code == 200 and state._sessions[doc].design is source
    state.drop_doc(doc)
    recover(client)
    assert state._sessions[doc].design.payload == source.payload


@pytest.mark.parametrize('kind', KINDS)
def test_every_family_appends_with_host_owned_outputs(document, client, immediate_geometry, kind):
    doc, _ = document
    template, index = recipe(kind, False)
    current = client.post(PREFIX + '/empty', json={}).json()
    # Generate equivalent source through the new HTTP path. Reference-bearing
    # overhang input is selected from that source, not fixture output identities.
    if index:
        base = add(client, 'bundle-create', authored(template.feature_log[0]), current)
        assert base.status_code == 200, base.text
        current = base.json()
    params = authored(template.feature_log[index])
    if kind == 'overhang-extrude':
        from tests.conftest import valid_overhang_sites
        params.update(valid_overhang_sites(materialize_revision(state._sessions[doc].design))[0])
    response = add(client, kind, params, current)
    assert response.status_code == 200, response.text
    model = materialize_revision(state._sessions[doc].design)
    entry = model.feature_log[-1]
    assert entry.op_kind == kind and entry.id == response.json()['feature_id']
    assert entry.params['history_seed'] == entry.id and entry.params['_proof_version'] == 1
    _verified(model)


@pytest.mark.parametrize('patch', [{'history_seed': 'caller'}, {'_proof_version': 1},
    {'_source_helix_ids': []}, {'length_bp': True}, {'cells': [[0, 0], [0, 0]]}, {'candidate': {}}])
def test_invalid_creation_inputs_cannot_publish(document, client, immediate_geometry, patch):
    doc, _ = document
    current = client.post(PREFIX + '/empty', json={}).json()
    source = state._sessions[doc].design
    response = add(client, 'bundle-create', {'cells': [[0, 0]], 'length_bp': 21, **patch}, current)
    assert response.status_code != 200
    assert state._sessions[doc].design is source and state._sessions[doc].revision == 1
    assert not state._sessions[doc].history


def test_append_missing_reference_preserves_empty_source(document, client, immediate_geometry):
    doc, _ = document
    current = client.post(PREFIX + '/empty', json={}).json()
    response = add(client, 'overhang-extrude', {'helix_id': 'missing', 'bp_index': 0,
        'direction': 'FORWARD', 'is_five_prime': False, 'neighbor_row': 1, 'neighbor_col': 0,
        'length_bp': 7}, current)
    assert response.status_code == 409, response.text
    assert 'missing_reference' in response.text
    assert state._sessions[doc].revision == 1 and not state._sessions[doc].history


def test_append_requires_exact_owned_capture_before_native_work(document, client, immediate_geometry, monkeypatch):
    doc, _ = document
    current = client.post(PREFIX + '/empty', json={}).json()
    original = worker.encode_input

    def tamper(ticket, operation):
        operation = deepcopy(operation)
        operation['header']['expected_feature_id'] = 'other'
        return original(ticket, operation)

    monkeypatch.setattr(worker, 'encode_input', tamper)
    response = add(client, 'bundle-create', {'cells': [[0, 0]], 'length_bp': 21}, current)
    assert response.status_code == 409
    assert state._sessions[doc].revision == 1


def test_generic_append_cannot_skip_owned_context(document, client):
    from backend.api.part_evaluation import evaluate
    from backend.core.part_verification_capture import capture
    from uuid import uuid4

    doc, _ = document
    client.post(PREFIX + '/empty', json={})
    source = materialize_revision(state._sessions[doc].design)
    result = evaluate(capture(source, preserve_entry_types=True), {
        'request': {'operation': 'append', 'kind': 'bundle-create',
                    'params': {'cells': [[0, 0]], 'length_bp': 21}, 'expected_revision': 1},
        'header': {'identity': str(uuid4()), 'timestamp': '2026-10-17T00:00:00Z'}})
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'invalid_capture_context'


def test_append_cancellation_retains_empty_source(document, client):
    from threading import Event
    from fastapi import HTTPException
    from backend.api.part_immutable_geometry_host import append

    doc, _ = document
    current = client.post(PREFIX + '/empty', json={}).json()
    source = state._sessions[doc].design
    cancelled = Event()
    cancelled.set()
    with pytest.raises(HTTPException) as error:
        append('bundle-create', {'cells': [[0, 0]], 'length_bp': 21},
               expected_design_id=current['design_id'], expected_revision=1, cancelled=cancelled)
    assert error.value.detail['code'] == 'cancelled'
    assert state._sessions[doc].design is source and not state._sessions[doc].history
