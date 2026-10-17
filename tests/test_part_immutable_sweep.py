"""Sweep shares extrusion's immutable host, with native mixed-history proof."""

from fastapi.testclient import TestClient
import pytest

from backend.api import state
from backend.api import part_immutable_geometry_publication as authority
from backend.api.part_immutable_revision import materialize_revision, prepare_geometry_revision
from backend.api.part_strict_geometry_http import PREFIX
from backend.api.part_strict_http import StrictPartDispatch
from tests.test_part_immutable_recovery import document as document, immediate as _recovery
from tests.test_part_immutable_geometry_host import immediate as _geometry
from tests.test_part_immutable_geometry_append import add
from tests.test_part_strict_geometry_http import recover
from tests.test_part_strict_http import forbidden_app
from tests.test_group_organization_history import _verified
from tests.test_part_sweep_preview import source_recipe

immediate_recovery = _recovery
immediate_geometry = _geometry


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(authority, 'ENABLED', True)


@pytest.fixture
def client(document):
    doc, _ = document
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': doc}) as client:
        yield client


def sweep_inputs(*, attached=None, end='end'):
    return {'cells': [[0, 0], [0, 1]] if attached else [[4, 4]],
            'points_nm': [[0, 0, 0], [0, 0, -4 if attached and end == 'start' else 4]],
            'ligate_adjacent': False, 'source_helix_id': attached, 'source_end': end}


def create_base(client):
    created = client.post(PREFIX + '/empty', json={})
    assert created.status_code == 201, created.text
    added = add(client, 'bundle-create', {'cells': [[0, 0], [0, 1]], 'length_bp': 12,
        'ligate_adjacent': False}, created.json())
    assert added.status_code == 200, added.text
    return added.json()


@pytest.mark.parametrize('attached,end', [(False, 'end'), (True, 'end'), (True, 'start')])
def test_mixed_sweep_append_edit_save_recover(document, client, immediate_geometry, immediate_recovery, attached, end):
    doc, owner = document
    current = create_base(client)
    source = materialize_revision(state._sessions[doc].design)
    params = sweep_inputs(attached=source.helices[0].id if attached else None, end=end)
    swept = add(client, 'sweep', params, current)
    assert swept.status_code == 200, swept.text
    tail = add(client, 'extrude-segment', {'cells': [[8, 8]], 'length_bp': 5}, swept.json())
    assert tail.status_code == 200, tail.text
    response = client.post(PREFIX + '/features/1/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': tail.json()['revision'],
        'expected_feature_id': swept.json()['feature_id'], 'expected_kind': 'sweep',
        'params': {'points_nm': [[0, 0, 0], [0, 0, -5 if attached and end == 'start' else 5]]}})
    assert response.status_code == 200, response.text
    handle = state._sessions[doc].design
    candidate = materialize_revision(handle)
    _verified(candidate)
    assert len(candidate.feature_log) == 3 and len(candidate.deformations) == 1
    assert candidate.feature_log[1].params['sweep_id'] == swept.json()['feature_id']
    assert candidate.deformations[0].id == 'sweep_' + swept.json()['feature_id']
    assert candidate.feature_log[-1].id == tail.json()['feature_id']
    guards = {'expected_design_id': current['design_id'], 'expected_revision': response.json()['revision']}
    assert client.post(PREFIX + '/save', json=guards).json()['current']
    assert owner.read_pending(doc).payload == handle.payload
    undo = client.post(PREFIX + '/history/undo', json=guards)
    assert undo.status_code == 200
    redo = client.post(PREFIX + '/history/redo', json={**guards, 'expected_revision': undo.json()['revision']})
    assert redo.status_code == 200 and state._sessions[doc].design is handle
    state.drop_doc(doc)
    recover(client)
    assert state._sessions[doc].design.payload == handle.payload


def test_real_worker_sweep_creation_and_upstream_extrusion_edit(document, client):
    doc, _ = document
    current = create_base(client)
    swept = add(client, 'sweep', sweep_inputs(), current)
    assert swept.status_code == 200, swept.text
    response = client.post(PREFIX + '/features/0/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': swept.json()['revision'],
        'expected_feature_id': current['feature_id'], 'expected_kind': 'bundle-create', 'params': {'length_bp': 14}})
    assert response.status_code == 200, response.text
    _verified(materialize_revision(state._sessions[doc].design))


@pytest.mark.parametrize('fault', ['identity', 'missing_source', 'unknown', 'coercion', 'nonfinite'])
def test_invalid_sweep_cannot_publish(document, client, immediate_geometry, fault):
    doc, _ = document
    current = create_base(client)
    before = state._sessions[doc].design
    params = sweep_inputs()
    if fault == 'identity': params['sweep_id'] = 'caller-owned'
    elif fault == 'missing_source': params['source_helix_id'] = 'missing'
    elif fault == 'unknown': params['candidate'] = {}
    elif fault == 'coercion': params['ligate_adjacent'] = 1
    else: params['points_nm'][0][0] = 'NaN'
    response = add(client, 'sweep', params, current)
    assert response.status_code != 200
    assert state._sessions[doc].design is before and state._sessions[doc].revision == current['revision']
    if fault == 'missing_source': assert 'missing_reference' in response.text


def test_saved_sweep_is_admitted_but_storage_seal_is_not_proof():
    source = source_recipe(attached=True)
    handle = prepare_geometry_revision(source)
    _verified(materialize_revision(handle))
    assert source.feature_log[1].post_state_gz_b64 == 'poisoned-post'


def test_storage_admission_never_calls_editor_normalization(monkeypatch):
    from backend.api import part_sweep_preview as editor
    source = source_recipe(attached=True)
    monkeypatch.setattr(editor, 'normalize', lambda *_a, **_k: pytest.fail('Storage invoked editor validation'))
    prepare_geometry_revision(source)
