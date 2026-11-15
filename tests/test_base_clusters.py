"""Exact base grouping through recorded native import and cluster authoring."""
import json
import pytest
import numpy as np
from backend.api import state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.crud import ScadnanoImportRequest, import_scadnano_design
from backend.api.routes_clusters import AddClusterBody, PatchClusterBody, add_cluster, update_cluster
from backend.core.models import Design
from backend.core.deformation import deformed_nucleotide_arrays
from scripts.agent_structure_guard import audit


@pytest.fixture
def imported():
    token = set_current_doc('base-cluster-test')
    try:
        source = {'name': 'base-cluster', 'version': '0.19.0', 'grid': 'square',
            'helices': [{'grid_position': [0, 0], 'max_offset': 12}],
            'strands': [
                {'is_scaffold': True, 'domains': [{'helix': 0, 'forward': True, 'start': 0, 'end': 12}]},
                {'domains': [{'helix': 0, 'forward': False, 'start': 0, 'end': 12}]}]}
        import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source)))
        yield state.get_or_404()
    finally:
        state.close_session()
        reset_current_doc(token)


def test_base_cluster_moves_only_selected_bases_and_replays(imported):
    hid = imported.helices[0].id
    bases = [dict(helix_id=hid, bp_index=bp, direction=direction)
             for direction in ('FORWARD', 'REVERSE') for bp in (4, 5)]
    original = imported.model_dump_json()
    add_cluster(AddClusterBody(name='Two base pairs', helix_ids=[hid], base_ids=bases))
    grouped = state.get_or_404()
    assert grouped.strands == imported.strands
    assert len(grouped.cluster_transforms[-1].base_ids) == 4
    audit(Design.model_validate_json(grouped.model_dump_json()))
    state.undo()
    assert state.get_or_404().model_dump_json() == original
    state.redo()
    cid = state.get_or_404().cluster_transforms[-1].id
    update_cluster(cid, PatchClusterBody(translation=[3., 0., 0.], commit=True))
    moved = state.get_or_404()
    before = deformed_nucleotide_arrays(imported.helices[0], imported)
    after = deformed_nucleotide_arrays(moved.helices[0], moved)
    mask = np.isin(before['bp_indices'], [4, 5])
    np.testing.assert_allclose(after['positions'][mask] - before['positions'][mask], np.tile([3, 0, 0], (mask.sum(), 1)))
    np.testing.assert_allclose(after['positions'][~mask], before['positions'][~mask])
    audit(Design.model_validate_json(moved.model_dump_json()))


def test_invalid_base_selection_is_atomic(imported):
    from fastapi import HTTPException
    hid = imported.helices[0].id
    before = imported.model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    with pytest.raises(HTTPException):
        add_cluster(AddClusterBody(helix_ids=[hid], base_ids=[dict(helix_id=hid, bp_index=99, direction='FORWARD')]))
    assert state.get_or_404().model_dump_json() == before
    assert (state.revision(), state.undo_depth()) == (revision, depth)


def test_two_nt_hinge_on_one_helix_can_connect_a_base_cluster(imported):
    from fastapi import Response
    from backend.api.routes_flexible_segments import FlexibleSegmentBatchBody, batch_flexible_segment
    # Re-import through the recorded native command with an actual scaffold gap.
    source = {'name': 'base-hinge', 'version': '0.19.0', 'grid': 'square',
        'helices': [{'grid_position': [0, 0], 'max_offset': 12}],
        'strands': [
            {'is_scaffold': True, 'domains': [{'helix': 0, 'forward': True, 'start': 0, 'end': 12}]},
            {'domains': [{'helix': 0, 'forward': False, 'start': 0, 'end': 4}]},
            {'domains': [{'helix': 0, 'forward': False, 'start': 6, 'end': 12}]}]}
    import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source)))
    d = state.get_or_404(); hid = d.helices[0].id
    bases = [dict(helix_id=hid, bp_index=bp, direction=direction)
             for direction in ('FORWARD', 'REVERSE') for bp in range(6, 12)]
    add_cluster(AddClusterBody(name='Right arm', helix_ids=[hid], base_ids=bases))
    scaffold = next(s for s in d.strands if s.is_scaffold)
    batch_flexible_segment(FlexibleSegmentBatchBody(marks=[dict(strand_id=scaffold.id, domain_index=0,
        bp_index=bp, direction='FORWARD') for bp in (4, 5)]), Response())
    result = state.get_or_404()
    assert len(result.flexible_connections) == 1
    connection = result.flexible_connections[0]
    assert connection.n_ss_bases == 2
    audit(Design.model_validate_json(result.model_dump_json()))


def test_base_assignment_separates_parent_movement_and_preserves_existing_pose(imported):
    hid = imported.helices[0].id
    owner = next(c for c in imported.cluster_transforms if not c.is_default)
    update_cluster(owner.id, PatchClusterBody(translation=[2., 1., 0.], commit=True))
    before = state.get_or_404()
    bases = [dict(helix_id=hid, bp_index=bp, direction=direction)
             for direction in ('FORWARD', 'REVERSE') for bp in (4, 5)]
    add_cluster(AddClusterBody(name='Subset', helix_ids=[hid], base_ids=bases))
    grouped = state.get_or_404()
    a = deformed_nucleotide_arrays(before.helices[0], before)
    b = deformed_nucleotide_arrays(grouped.helices[0], grouped)
    np.testing.assert_allclose(a['positions'], b['positions'])
    update_cluster(owner.id, PatchClusterBody(translation=[5., 1., 0.], commit=True))
    moved = state.get_or_404();c = deformed_nucleotide_arrays(moved.helices[0], moved)
    mask = np.isin(a['bp_indices'], [4, 5])
    np.testing.assert_allclose(c['positions'][mask], b['positions'][mask])
    np.testing.assert_allclose(c['positions'][~mask] - b['positions'][~mask], np.tile([3,0,0], ((~mask).sum(),1)))
    audit(Design.model_validate_json(moved.model_dump_json()))


@pytest.mark.parametrize('paired', [True, False])
def test_batch_move_compares_exact_complementary_base_frames(imported, paired):
    from backend.api.routes_clusters import ClusterPosesBody, move_clusters
    source = {'name': 'partial-domain-pair', 'version': '0.19.0', 'grid': 'square',
        'helices': [{'grid_position': [0, 0], 'max_offset': 12}],
        'strands': [
            {'is_scaffold': True, 'domains': [{'helix': 0, 'forward': True, 'start': 0, 'end': 12}]},
            {'domains': [{'helix': 0, 'forward': False, 'start': 4, 'end': 6}]}]}
    import_scadnano_design(ScadnanoImportRequest(content=json.dumps(source)))
    d = state.get_or_404(); hid = d.helices[0].id
    bases = [dict(helix_id=hid, bp_index=bp, direction=direction)
             for direction in (('FORWARD', 'REVERSE') if paired else ('REVERSE',)) for bp in (4, 5)]
    add_cluster(AddClusterBody(name='Partial scaffold domain', helix_ids=[hid], base_ids=bases))
    grouped = state.get_or_404(); cluster = grouped.cluster_transforms[-1]
    move_clusters(ClusterPosesBody(expected_revision=state.revision(), placements=[{
        'cluster_id': cluster.id, 'fields': {'translation': [3., 0., 0.],
            'rotation': cluster.rotation, 'pivot': cluster.pivot}}]))
    moved = state.get_or_404()
    if paired:
        assert moved.strands == grouped.strands
        assert moved.helices == grouped.helices
    else:
        assert len(moved.helices) == len(grouped.helices) + 1
        from backend.core.cluster_bases import validate_base_members
        validate_base_members(moved, moved.cluster_transforms[-1])
    audit(Design.model_validate_json(moved.model_dump_json()))
