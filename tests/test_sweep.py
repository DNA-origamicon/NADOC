"""Sweep geometry, canonical topology, continuation and transactional history."""
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.core.models import Design, LatticeType, DeformationOp, BendParams
from backend.core.lattice import make_bundle_design
from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.sweep import SweepRequest, build_sweep, sweep_preview
from backend.core.sweep_path import path_table, sample_path
from backend.core.deformation import deformed_nucleotide_arrays, deformed_helix_axes, _frame_at_bp, _precompute_arm_frames


def test_spline_interpolates_points_and_transports_without_roll():
    points = ((0., 0., 0.), (0., 0., 10.), (10., 4., 20.), (20., -3., 25.))
    spline, u, arc, tangents, _ = path_table(points)
    knots = np.r_[0, np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    np.testing.assert_allclose(spline(knots), points, atol=1e-12)
    positions, rotations, sampled_tangents = sample_path(points, arc[::19])
    np.testing.assert_allclose(positions, spline(u[::19]), atol=1e-10)
    np.testing.assert_allclose(rotations @ tangents[0], sampled_tangents, atol=1e-8)
    np.testing.assert_allclose(np.linalg.det(rotations), 1, atol=1e-10)


@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
@pytest.mark.parametrize('lattice', list(LatticeType))
def test_straight_sweep_is_canonical_extrusion(plane, lattice):
    points = [(0,0,0), {'XY': (0,0,20*RISE), 'XZ': (0,20*RISE,0), 'YZ': (20*RISE,0,0)}[plane]]
    body = SweepRequest(cells=[(0,0),(0,1)], points_nm=points, plane=plane, ligate_adjacent=False)
    design = build_sweep(Design(lattice_type=lattice), body)
    straight = make_bundle_design(body.cells, 21, plane=plane, lattice_type=lattice)
    for h, original in zip(design.helices, straight.helices):
        actual = deformed_nucleotide_arrays(h, design)
        expected = deformed_nucleotide_arrays(original, straight)
        for key in ['positions', 'axis_points', 'axis_tangents', 'radial_hats']:
            np.testing.assert_allclose(actual[key], expected[key], atol=1e-9)
    assert len(design.deformations) == 1
    assert design.deformations[0].type == 'sweep'
    restored = Design.model_validate_json(design.model_dump_json())
    np.testing.assert_allclose(deformed_helix_axes(restored)[0]['samples'], deformed_helix_axes(design)[0]['samples'])


@pytest.mark.parametrize('end', ['start', 'end'])
@pytest.mark.parametrize('lattice', list(LatticeType))
def test_continuation_preserves_original_geometry_polarity_and_phase(end, lattice):
    original = make_bundle_design([(0,0),(0,1)], 21, lattice_type=lattice)
    h = original.helices[0]
    sign = 1 if end == 'end' else -1
    body = SweepRequest(cells=[(0,0),(0,1)], points_nm=[(0,0,0),(0,0,sign*20*RISE)],
                        source_helix_id=h.id, source_end=end, ligate_adjacent=False)
    result = build_sweep(original, body)
    assert len(result.strands) == len(original.strands)
    assert all(len(s.domains) == 2 for s in result.strands)
    for old in original.helices:
        np.testing.assert_allclose(deformed_nucleotide_arrays(old, original)['positions'],
                                   deformed_nucleotide_arrays(result.find_helix(old.id), result)['positions'], atol=1e-10)
    # Compare the combined sites to a single canonical helix spanning both ranges.
    offset = -20*RISE if end == 'start' else 0
    reference = make_bundle_design(body.cells, 41, offset_nm=offset, lattice_type=lattice)
    for new, full in zip(result.helices[-2:], reference.helices):
        a, b = deformed_nucleotide_arrays(new, result), deformed_nucleotide_arrays(full, reference)
        mask = np.isin(b['bp_indices'], a['bp_indices'])
        for key in ['positions', 'axis_points', 'radial_hats']:
            np.testing.assert_allclose(a[key], b[key][mask], atol=1e-8)


def test_bent_end_and_sweep_end_can_be_continued():
    original = make_bundle_design([(0,0),(0,1)], 42)
    original = original.copy_with(deformations=[DeformationOp(type='bend', plane_a_bp=0, plane_b_bp=41,
        affected_helix_ids=[h.id for h in original.helices], params=BendParams(curvature_deg_per_bp=1))])
    first = build_sweep(original, SweepRequest(cells=[(0,0),(0,1)], points_nm=[(0,0,0),(10,0,10),(15,8,20)],
        source_helix_id=original.helices[0].id))
    second = build_sweep(first, SweepRequest(cells=[(0,0),(0,1)], points_nm=[(0,0,0),(5,5,10)],
        source_helix_id=first.helices[-2].id))
    for h in first.helices:
        np.testing.assert_allclose(deformed_nucleotide_arrays(h, first)['positions'], deformed_nucleotide_arrays(h, second)['positions'], atol=1e-9)
    arm = second.helices[-2:]
    scalar = _frame_at_bp(second, 5, arm)
    arrays = _precompute_arm_frames(second, arm, min(h.bp_start for h in arm), 5)
    for single, batch in zip(scalar, arrays):
        np.testing.assert_allclose(single, batch[5], atol=1e-9)


@pytest.mark.parametrize('points', [[(0,0,0)], [(1,0,0),(2,0,0)], [(0,0,0),(0,0,0)], [(0,0,0),(float('nan'),0,0)]])
def test_bad_paths_rejected(points):
    with pytest.raises(ValueError):
        body = SweepRequest(cells=[(0,0)], points_nm=points)
        sweep_preview(Design(), body)


def test_api_preview_commit_edit_revert_undo_redo_and_seek():
    client = TestClient(app)
    # Direct state setup matches the existing headless API test contract.
    from backend.api import state
    state.set_design(Design())
    body = dict(cells=[[0,0],[0,1]], points_nm=[[0,0,0],[0,0,5],[5,0,10]], ligate_adjacent=False)
    before = state.get_or_404().model_dump_json()
    response = client.post('/api/design/sweep/preview', json=body)
    assert response.status_code == 200, response.text
    assert state.get_or_404().model_dump_json() == before
    response = client.post('/api/design/sweep', json=body)
    assert response.status_code == 201, response.text
    committed = state.get_or_404()
    assert len(committed.feature_log) == 1 and committed.feature_log[0].op_kind == 'sweep'
    assert len(committed.deformations) == 1
    response = client.post('/api/design/undo')
    assert response.status_code == 200, response.text
    assert not state.get_or_404().helices
    assert client.post('/api/design/redo').status_code == 200
    assert state.get_or_404().deformations[0].type == 'sweep'
    old_ids = [h.id for h in state.get_or_404().helices]
    changed = {**state.get_or_404().feature_log[0].params, 'points_nm': [[0,0,0],[0,0,8],[8,0,15]]}
    response = client.post('/api/design/features/0/edit', json={'params': changed})
    assert response.status_code == 200, response.text
    assert [h.id for h in state.get_or_404().helices] == old_ids
    assert state.get_or_404().deformations[-1].params.points_nm[-1] == (8,0,15)
    from backend.api.crud import _seek_feature_log
    empty = _seek_feature_log(state.get_or_404(), -2)
    assert not empty.deformations
    seek = _seek_feature_log(empty, -1)
    assert len(seek.deformations) == 1 and seek.deformations[0].type == 'sweep'
    response = client.post('/api/design/features/0/revert')
    assert response.status_code == 200, response.text
    assert not state.get_or_404().helices


def test_sequenced_continuation_preserves_assigned_bases():
    original = make_bundle_design([(0,0)], 21)
    original.strands[0].sequence = 'ACG' * 7
    for end in ['start', 'end']:
        sign = 1 if end == 'end' else -1
        result = build_sweep(original, SweepRequest(cells=[(0,0)], points_nm=[(0,0,0),(0,0,sign*10*RISE)],
            source_helix_id=original.helices[0].id, source_end=end))
        sequence = result.strands[0].sequence
        assert sequence == ('ACG'*7 + 'N'*10 if end == 'end' else 'N'*10 + 'ACG'*7)


def test_rotated_source_continuation_inherits_pose_once():
    from backend.core.models import ClusterRigidTransform
    from scipy.spatial.transform import Rotation
    original = make_bundle_design([(0,0),(0,1)], 21)
    rotation = Rotation.from_euler('xyz', [20,30,40], degrees=True)
    original = original.copy_with(cluster_transforms=[ClusterRigidTransform(
        helix_ids=[h.id for h in original.helices], rotation=rotation.as_quat().tolist(),
        translation=[10,20,30], pivot=[0,0,0])])
    vector = rotation.apply([0,0,20*RISE])
    result = build_sweep(original, SweepRequest(cells=[(0,0),(0,1)], points_nm=[(0,0,0),vector.tolist()],
        source_helix_id=original.helices[0].id, ligate_adjacent=False))
    reference = make_bundle_design([(0,0),(0,1)], 41)
    for new, full in zip(result.helices[-2:], reference.helices):
        a = deformed_nucleotide_arrays(new, result)
        b = deformed_nucleotide_arrays(full, reference)
        mask = np.isin(b['bp_indices'], a['bp_indices'])
        np.testing.assert_allclose(a['positions'], rotation.apply(b['positions'][mask]) + [10,20,30], atol=1e-8)


def test_invalid_commit_is_atomic_and_preview_is_guarded():
    from backend.api import state
    state.set_design(Design())
    client = TestClient(app)
    before = state.get_or_404().model_dump_json()
    body = dict(cells=[[0,0]], points_nm=[[0,0,0],[0,0,0]])
    response = client.post('/api/design/sweep', json=body)
    assert response.status_code == 422
    assert state.get_or_404().model_dump_json() == before
    body['points_nm'][1] = [0,0,10]
    body.update(expected_design_id='another-design', expected_revision=0)
    assert client.post('/api/design/sweep', json=body).status_code == 409
    assert client.post('/api/design/sweep/preview', json=body).status_code == 409
    assert state.get_or_404().model_dump_json() == before


def test_editing_upstream_bend_rebuilds_sweep_source_with_stable_ids():
    from backend.api import state
    client = TestClient(app)
    state.set_design(Design())
    assert client.post('/api/design/bundle', json={'cells': [[0,0]], 'length_bp': 42}).status_code == 201
    ref = state.get_or_404().helices[0].id
    bend = dict(type='bend', plane_a_bp=0, plane_b_bp=41,
                params={'kind': 'bend', 'curvature_deg_per_bp': 1, 'direction_deg': 0})
    assert client.post('/api/design/deformation', json=bend).status_code == 200
    response = client.post('/api/design/sweep', json=dict(cells=[[0,0]], points_nm=[[0,0,0],[5,0,10]], source_helix_id=ref))
    assert response.status_code == 201, response.text
    before = state.get_or_404()
    origin = before.deformations[-1].params.origin_nm
    ids = [h.id for h in before.helices]
    bend['params']['curvature_deg_per_bp'] = 0
    response = client.post('/api/design/features/1/edit', json={'params': bend})
    assert response.status_code == 200, response.text
    after = state.get_or_404()
    assert [h.id for h in after.helices] == ids
    sweep = next(op for op in after.deformations if op.type == 'sweep')
    assert not np.allclose(sweep.params.origin_nm, origin)
    np.testing.assert_allclose(sweep.params.origin_nm, [0,0,41*RISE], atol=1e-8)


@pytest.fixture(autouse=True)
def close_api_session():
    yield
    from backend.api import state
    state.close_session()


def test_continuation_can_add_vacant_cells_alongside_existing_ends():
    original = make_bundle_design([(0,0)], 21)
    result = build_sweep(original, SweepRequest(cells=[(0,0),(0,1)], points_nm=[(0,0,0),(0,0,20*RISE)],
                        source_helix_id=original.helices[0].id, ligate_adjacent=False))
    assert len(result.helices) == 3
    assert len(result.strands) == 4
    assert [len(s.domains) for s in result.strands] == [2,2,1,1]
    np.testing.assert_allclose(deformed_nucleotide_arrays(result.helices[1], result)['axis_points'][0], [0,0,21*RISE], atol=1e-9)


def test_edit_keeps_later_cluster_pose_and_preview_matches_it():
    from backend.api import state
    from backend.core.models import ClusterOpLogEntry
    client = TestClient(app)
    state.set_design(Design())
    body = dict(cells=[[0,0]], points_nm=[[0,0,0],[0,0,10]])
    assert client.post('/api/design/sweep', json=body).status_code == 201
    design = state.get_or_404()
    cluster = design.cluster_transforms[0].model_copy(update={'translation': [10,20,30]})
    move = ClusterOpLogEntry(cluster_id=cluster.id, translation=cluster.translation,
                            rotation=cluster.rotation, pivot=cluster.pivot)
    state.set_design(design.copy_with(cluster_transforms=[cluster], feature_log=[*design.feature_log, move]))
    response = client.post('/api/design/sweep/preview?feature_index=0', json=body)
    assert response.status_code == 200, response.text
    np.testing.assert_allclose(response.json()['origin_nm'], [10,20,30])
    body['points_nm'][-1] = [0,0,15]
    response = client.post('/api/design/features/0/edit', json={'params': body})
    assert response.status_code == 200, response.text
    after = state.get_or_404()
    assert after.helices[0].id == design.helices[0].id
    assert after.cluster_transforms[0].translation == [10,20,30]
    np.testing.assert_allclose(deformed_nucleotide_arrays(after.helices[0], after)['axis_points'][0], [10,20,30])


@pytest.mark.parametrize('end', [None, 'start', 'end'])
@pytest.mark.parametrize('plane', ['XY', 'XZ', 'YZ'])
def test_swept_helix_preview_matches_committed_axis_endpoints(plane, end):
    original = make_bundle_design([(0,0), (0,1)], 21, plane=plane)
    original = original.copy_with(helices=[h.model_copy(update={'grid_pos': cell}) for h, cell in zip(original.helices, [(0,0), (0,1)])])
    direction = -1 if end == 'start' else 1
    normal = np.eye(3)[{'XY': 2, 'XZ': 1, 'YZ': 0}[plane]] * direction
    body = SweepRequest(cells=[(0,0), (0,1)] if end else [(1,0), (1,1)], plane=plane,
        points_nm=[(0,0,0), tuple(normal * 8), tuple(normal * 14 + np.array([4,3,2]))],
        source_helix_id=original.helices[0].id if end else None, source_end=end or 'end')
    preview, _ = sweep_preview(original, body, include_geometry=True)
    result = build_sweep(original, body)
    for path, helix in zip(preview['helix_paths_nm'], result.helices[-2:]):
        axes = deformed_nucleotide_arrays(helix, result)
        for i, bp in [(0, helix.bp_start), (-1, helix.bp_start + helix.length_bp - 1)]:
            actual = axes['axis_points'][np.flatnonzero(axes['bp_indices'] == bp)[0]]
            expected = path[-1 if i == 0 else 0] if direction == -1 else path[i]
            np.testing.assert_allclose(actual, expected, atol=1e-6)
