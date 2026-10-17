"""Native placement/residue transforms share the immutable geometry lifecycle."""

from fastapi.testclient import TestClient
import pytest

from backend.api import state
from backend.api import part_immutable_geometry_publication as authority
from backend.api.part_immutable_revision import materialize_revision
from backend.api.part_strict_geometry_http import PREFIX
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.models import ClusterOpLogEntry
from tests.test_part_immutable_recovery import document as document, immediate as _recovery
from tests.test_part_immutable_geometry_host import immediate as _geometry
from tests.test_part_immutable_geometry_append import add
from tests.test_part_strict_geometry_http import recover
from tests.test_part_strict_http import forbidden_app
from tests.test_group_organization_history import _verified

immediate_recovery = _recovery
immediate_geometry = _geometry
KINDS = ('cluster_op', 'placement-poses', 'nucleotide-transform', 'nucleotide-transform-batch', 'nucleotide-transform-delete')


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
    result = add(client, 'bundle-create', {'cells': [[0, 0], [0, 1]], 'length_bp': 12,
        'ligate_adjacent': False}, created)
    assert result.status_code == 200, result.text
    return result.json()


def pose():
    return {'translation': [1, 2, 3], 'rotation': [0, 0, 0, 1], 'pivot': [0, 0, 0]}


def body(kind, source):
    owner = source.cluster_transforms[0]
    if kind == 'cluster_op': return {'cluster_id': owner.id, **pose()}
    if kind == 'placement-poses':
        return {'primary_cluster_id': owner.id, 'selected_cluster_ids': [owner.id],
            'poses': [{'cluster_id': owner.id, **pose(), 'parent_cluster_id': owner.parent_cluster_id,
                       'overhang_duplex_driver_id': owner.overhang_duplex_driver_id}],
            'authoring': {'mode': 'free', 'joint_id': None, 'fixed_cluster_ids': [], 'pivot_id': 'centroid'}}
    if kind == 'nucleotide-transform-delete': return {'transform_id': source.nucleotide_transforms[0].id}
    domain = source.strands[0].domains[0]
    values = {'kind': 'base', 'helix_id': domain.helix_id, 'bp_index': domain.start_bp,
              'direction': domain.direction.value, **pose()}
    return {'transforms': [values]} if kind.endswith('-batch') else values


@pytest.mark.parametrize('kind', KINDS)
def test_transform_append_edit_tail_save_undo_recover(document, client, immediate_geometry, immediate_recovery, kind):
    doc, owner = document
    current = base(client)
    if kind == 'nucleotide-transform-delete':
        for offset in (1, 2):
            values = body('nucleotide-transform', materialize_revision(state._sessions[doc].design))
            values['bp_index'] += offset
            result = add(client, 'nucleotide-transform', values, current)
            assert result.status_code == 200, result.text
            current = result.json()
    source = materialize_revision(state._sessions[doc].design)
    index = len(source.feature_log)
    values = body(kind, source)
    added = add(client, kind, values, current)
    assert added.status_code == 200, added.text
    tail = add(client, 'extrude-segment', {'cells': [[8, 8]], 'length_bp': 5}, added.json())
    assert tail.status_code == 200, tail.text
    patch = {'translation': [2, 3, 4]}
    if kind == 'placement-poses': patch = {'poses': [{**values['poses'][0], **patch}]}
    elif kind.endswith('-batch'): patch = {'transforms': [{**values['transforms'][0], **patch}]}
    elif kind.endswith('-delete'): patch = {'transform_id': source.nucleotide_transforms[1].id}
    edited = client.post(f'{PREFIX}/features/{index}/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': tail.json()['revision'],
        'expected_feature_id': added.json()['feature_id'], 'expected_kind': kind, 'params': patch})
    assert edited.status_code == 200, edited.text
    handle = state._sessions[doc].design
    candidate = materialize_revision(handle)
    _verified(candidate)
    entry = candidate.feature_log[index]
    assert entry.id == added.json()['feature_id'] and candidate.feature_log[-1].id == tail.json()['feature_id']
    if kind == 'cluster_op': assert type(entry) is ClusterOpLogEntry and entry.translation == [2, 3, 4]
    elif kind in {'nucleotide-transform', 'nucleotide-transform-batch'}: assert entry.params['history_seed'] == entry.id
    elif kind.endswith('-delete'): assert entry.params['target'] == list(source.nucleotide_transforms[1].target_key())
    guards = {'expected_design_id': current['design_id'], 'expected_revision': edited.json()['revision']}
    assert client.post(PREFIX + '/save', json=guards).json()['current']
    assert owner.read_pending(doc).payload == handle.payload
    undo = client.post(PREFIX + '/history/undo', json=guards).json()
    redo = client.post(PREFIX + '/history/redo', json={**guards, 'expected_revision': undo['revision']})
    assert redo.status_code == 200 and state._sessions[doc].design is handle
    state.drop_doc(doc)
    recover(client)
    assert state._sessions[doc].design.payload == handle.payload


def test_real_worker_placement_and_upstream_edit(document, client):
    doc, _ = document
    current = base(client)
    result = add(client, 'cluster_op', body('cluster_op', materialize_revision(state._sessions[doc].design)), current)
    assert result.status_code == 200, result.text
    edited = client.post(PREFIX + '/features/0/edit', json={
        'expected_design_id': current['design_id'], 'expected_revision': result.json()['revision'],
        'expected_feature_id': current['feature_id'], 'expected_kind': 'bundle-create', 'params': {'length_bp': 14}})
    assert edited.status_code == 200, edited.text
    _verified(materialize_revision(state._sessions[doc].design))


@pytest.mark.parametrize('patch', [{'history_seed': 'caller'}, {'_proof_version': 1}, {'rotation': [0, 0, 0, 0]},
    {'translation': [True, 0, 0]}, {'cluster_id': 'missing'}, {'primary_authored_fields': {}}])
def test_invalid_transform_cannot_publish(document, client, immediate_geometry, patch):
    doc, _ = document
    current = base(client)
    source = state._sessions[doc].design
    result = add(client, 'cluster_op', {**body('cluster_op', materialize_revision(source)), **patch}, current)
    assert result.status_code != 200 and state._sessions[doc].design is source


def test_unknown_residue_target_is_diagnosed(document, client, immediate_geometry):
    doc, _ = document
    current = base(client)
    source = state._sessions[doc].design
    values = body('nucleotide-transform', materialize_revision(source))
    values['bp_index'] = 1000
    result = add(client, 'nucleotide-transform', values, current)
    assert result.status_code == 409 and 'reference' in result.text
    assert state._sessions[doc].design is source
