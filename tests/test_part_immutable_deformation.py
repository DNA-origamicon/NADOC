"""Typed Bend/Twist creation and editing through the immutable geometry host."""

from fastapi.testclient import TestClient
import pytest

from backend.api import state
from backend.api import part_immutable_geometry_publication as authority
from backend.api.part_immutable_revision import materialize_revision
from backend.api.part_strict_geometry_http import PREFIX
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.models import DeformationLogEntry
from tests.test_part_immutable_recovery import document as document, immediate as _recovery
from tests.test_part_immutable_geometry_host import immediate as _geometry
from tests.test_part_immutable_geometry_append import add
from tests.test_part_strict_geometry_http import recover
from tests.test_part_strict_http import forbidden_app
from tests.test_group_organization_history import _verified

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


def base(client):
    created = client.post(PREFIX + '/empty', json={}).json()
    response = add(client, 'bundle-create', {'cells': [[0, 0], [0, 1]], 'length_bp': 42}, created)
    assert response.status_code == 200, response.text
    return response.json()


def inputs(kind):
    return {'type': kind, 'plane_a_bp': 4, 'plane_b_bp': 32,
        'params': {'kind': kind, **({'curvature_deg_per_bp': .25, 'direction_deg': 0}
                                   if kind == 'bend' else {'total_degrees': 8})}}


@pytest.mark.parametrize('kind', ['bend', 'twist'])
@pytest.mark.parametrize('selection', ['whole', 'cluster', 'domain'])
def test_create_edit_suffix_undo_save_recover(document, client, immediate_geometry, immediate_recovery, kind, selection):
    doc, owner = document
    current = base(client)
    source = materialize_revision(state._sessions[doc].design)
    params = inputs(kind)
    if selection == 'cluster': params['cluster_ids'] = [source.cluster_transforms[0].id]
    if selection == 'domain': params['targets'] = [{'kind': 'domain', 'strand_id': source.strands[0].id, 'domain_index': 0}]
    added = add(client, 'deformation', params, current)
    assert added.status_code == 200, added.text
    tail = add(client, 'extrude-segment', {'cells': [[8, 8]], 'length_bp': 7}, added.json())
    assert tail.status_code == 200, tail.text
    changed = client.post(PREFIX + '/features/1/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': tail.json()['revision'],
        'expected_feature_id': added.json()['feature_id'], 'expected_kind': 'deformation',
        'params': {'plane_b_bp': 30}})
    assert changed.status_code == 200, changed.text
    handle = state._sessions[doc].design
    model = materialize_revision(handle)
    entry = model.feature_log[1]
    assert type(entry) is DeformationLogEntry and entry.id == added.json()['feature_id']
    assert entry.deformation_id == entry.op_snapshot.id == entry.id
    assert entry.op_snapshot.plane_b_bp == 30
    assert model.feature_log[-1].id == tail.json()['feature_id']
    _verified(model)
    guards = {'expected_design_id': current['design_id'], 'expected_revision': changed.json()['revision']}
    assert client.post(PREFIX + '/save', json=guards).json()['current']
    assert owner.read_pending(doc).payload == handle.payload
    undo = client.post(PREFIX + '/history/undo', json=guards).json()
    redo = client.post(PREFIX + '/history/redo', json={**guards, 'expected_revision': undo['revision']})
    assert redo.status_code == 200 and state._sessions[doc].design is handle
    state.drop_doc(doc)
    recover(client)
    assert state._sessions[doc].design.payload == handle.payload


def test_real_worker_bend_and_upstream_edit(document, client):
    doc, _ = document
    current = base(client)
    added = add(client, 'deformation', inputs('bend'), current)
    assert added.status_code == 200, added.text
    changed = client.post(PREFIX + '/features/0/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': added.json()['revision'],
        'expected_feature_id': current['feature_id'], 'expected_kind': 'bundle-create',
        'params': {'length_bp': 40}})
    assert changed.status_code == 200, changed.text
    _verified(materialize_revision(state._sessions[doc].design))


@pytest.mark.parametrize('patch', [{'id': 'caller'}, {'affected_helix_ids': []}, {'target_ranges': []},
    {'type': 'sweep'}, {'plane_a_bp': True}, {'plane_b_bp': 4}, {'cluster_ids': ['missing']},
    {'params': {'kind': 'twist', 'total_degrees': 8}}])
def test_invalid_creation_is_atomic(document, client, immediate_geometry, patch):
    doc, _ = document
    current = base(client)
    before = state._sessions[doc].design
    response = add(client, 'deformation', {**inputs('bend'), **patch}, current)
    assert response.status_code != 200
    assert state._sessions[doc].design is before and state._sessions[doc].revision == current['revision']


@pytest.mark.parametrize('patch', [{'id': 'changed'}, {'affected_helix_ids': []}, {'type': 'twist'},
    {'plane_b_bp': True}, {'plane_b_bp': 100_000}, {'params': {'curvature_deg_per_bp': '0.5'}}])
def test_invalid_edit_keeps_typed_source(document, client, immediate_geometry, patch):
    doc, _ = document
    current = base(client)
    added = add(client, 'deformation', inputs('bend'), current)
    assert added.status_code == 200, added.text
    before = state._sessions[doc].design
    response = client.post(PREFIX + '/features/1/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': added.json()['revision'],
        'expected_feature_id': added.json()['feature_id'], 'expected_kind': 'deformation', 'params': patch})
    assert response.status_code != 200
    assert state._sessions[doc].design is before


def test_storage_requires_typed_deformation_and_matching_operation_identity():
    from backend.api.part_immutable_revision import prepare_geometry_revision
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_overlay_commands import command_input
    from backend.core.part_command_errors import CommandContractError
    from tests.test_part_deformation_preview import native_source

    source = native_source('bend')
    entry = source.feature_log[-1]
    kind, params = command_input(entry)
    source.feature_log[-1] = SnapshotLogEntry(id=entry.id, op_kind="sweep", label="forged", params=params).model_copy(update={"op_kind": kind})
    with pytest.raises(CommandContractError):
        prepare_geometry_revision(source)
    source.feature_log[-1] = entry.model_copy(update={'deformation_id': 'different'})
    with pytest.raises(CommandContractError):
        prepare_geometry_revision(source)


def test_edit_missing_group_refuses_without_broadening_scope(document, client, immediate_geometry):
    doc, _ = document
    current = base(client)
    added = add(client, 'deformation', inputs('bend'), current)
    assert added.status_code == 200, added.text
    source = state._sessions[doc].design
    response = client.post(PREFIX + '/features/1/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': added.json()['revision'],
        'expected_feature_id': added.json()['feature_id'], 'expected_kind': 'deformation',
        'params': {'cluster_ids': ['missing']}})
    assert response.status_code == 409 and 'missing_reference' in response.text
    assert state._sessions[doc].design is source
