"""Extrusion ownership is determined by continuation, never mere adjacency."""
import pytest
from backend.api.crud import (BundleSegmentRequest, BundleContinuationRequest,
                              _build_extrude_segment, _build_extrude_continuation,
                              _edit_dispatch_run)
from backend.core.cluster_reconcile import reconcile_cluster_membership, MutationReport
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterRigidTransform


def seed():
    design = make_bundle_design([(0, 0)], 42)
    return design.copy_with(cluster_transforms=[ClusterRigidTransform(
        id='existing', name='Cluster 1', helix_ids=[h.id for h in design.helices],
        translation=[5, 0, 0])])


def build(before, request, builder):
    after, report = builder(before, request)
    return reconcile_cluster_membership(before, after, report)


def test_new_cells_one_cluster_even_adjacent_or_disconnected():
    before = seed()
    body = BundleSegmentRequest(cells=[[0, 1], [12, 12]], length_bp=21)
    after = build(before, body, _build_extrude_segment)
    assert len(after.cluster_transforms) == 2
    assert after.cluster_transforms[0] == before.cluster_transforms[0]
    added = after.cluster_transforms[1]
    assert set(added.helix_ids) == {h.id for h in after.helices} - {h.id for h in before.helices}
    assert added.translation == [0, 0, 0]
    replay = _edit_dispatch_run('extrude-segment', before, body.model_dump())
    assert replay.cluster_transforms == after.cluster_transforms
    # Subsequent generic reconciliation cannot absorb the new body into its neighbor.
    assert reconcile_cluster_membership(after, after, MutationReport()).cluster_transforms == after.cluster_transforms


@pytest.mark.parametrize('inplace', [True, False])
@pytest.mark.parametrize('offset', [0, 42 * BDNA_RISE_PER_BP])
def test_continuation_and_disconnected_new_cells_follow_existing(inplace, offset):
    before = seed()
    body = BundleContinuationRequest(cells=[[0, 0], [12, 12]], length_bp=-21 if offset == 0 else 21,
                                     offset_nm=offset, extend_inplace=inplace)
    after = build(before, body, _build_extrude_continuation)
    assert len(after.cluster_transforms) == 1
    assert set(after.cluster_transforms[0].helix_ids) == {h.id for h in after.helices}
    assert after.cluster_transforms[0].translation == [5, 0, 0]


def test_legacy_feature_replay_retains_neighbor_inheritance():
    before = seed()
    after = _edit_dispatch_run('extrude-segment', before,
                              {'cells': [[0, 1]], 'length_bp': 21})
    assert len(after.cluster_transforms) == 1
    assert len(after.cluster_transforms[0].helix_ids) == 2


@pytest.mark.parametrize('mixed', [False, True])
def test_deformed_extrusion_uses_actual_continuation_and_preserves_pose(mixed):
    from backend.api.crud import BundleDeformedContinuationRequest, _build_extrude_deformed_continuation
    from backend.core.deformation import deformed_helix_axes
    before = seed()
    endpoint = deformed_helix_axes(before)[0]['end']
    body = BundleDeformedContinuationRequest(
        cells=[[0, 0], [12, 12]] if mixed else [[0, 1], [12, 12]], length_bp=21,
        grid_origin=endpoint, axis_dir=[0, 0, 1], frame_right=[1, 0, 0],
        frame_up=[0, 1, 0], ref_helix_id=before.helices[0].id)
    after = build(before, body, _build_extrude_deformed_continuation)
    assert len(after.cluster_transforms) == (1 if mixed else 2)
    assert after.cluster_transforms[-1].translation == [5, 0, 0]
    if mixed:
        assert set(after.cluster_transforms[0].helix_ids) == {h.id for h in after.helices}
    else:
        assert after.cluster_transforms[0] == before.cluster_transforms[0]


def test_repeated_fresh_legacy_plane_extrusions_preserve_placement_and_all_clusters():
    from backend.core.legacy_plane_extrusion import append_legacy_plane_bundle, legacy_plane_source
    from backend.core.extrusion_clusters import extrusion_clusters
    before = seed()
    for cell in [(0, 1), (0, 2)]:
        candidate = append_legacy_plane_bundle(before, [list(cell)], 21, plane='XY')
        candidate, report = extrusion_clusters(before, candidate, {})
        after = reconcile_cluster_membership(before, candidate, report)
        assert after.cluster_transforms[:-1] == before.cluster_transforms
        assert after.cluster_transforms[-1].translation == [5, 0, 0]
        assert len(legacy_plane_source(after, 'XY')[1]) == 1  # pose applied once
        before = after
    assert len(before.cluster_transforms) == 3


def test_continuation_of_new_frame_cluster_does_not_rejoin_original_placement():
    from backend.api.crud import BundleRequest, _build_bundle
    from backend.core.lattice_frames import append_frame_bundle
    from backend.core.extrusion_clusters import extrusion_clusters
    before = _build_bundle([(0, 0)], BundleRequest(cells=[[0, 0]], length_bp=42))
    frame = before.lattice_frames[0].id
    candidate = append_frame_bundle(before, frame, [[0, 1]], 42, plane='XY')
    candidate, report = extrusion_clusters(before, candidate, {})
    before = reconcile_cluster_membership(before, candidate, report)
    body = BundleContinuationRequest(cells=[[0, 1], [0, 2]], length_bp=21,
        offset_nm=before.helices[-1].axis_end.z, source_frame_id=frame)
    after = build(before, body, _build_extrude_continuation)
    assert after.cluster_transforms[0] == before.cluster_transforms[0]
    assert len(after.cluster_transforms) == 2
    assert len(after.cluster_transforms[1].helix_ids) == 2


def test_initial_disconnected_footprint_is_one_cluster_unless_legacy_requested():
    from backend.api.crud import BundleRequest, _build_bundle
    cells = [(0, 0), (12, 12)]
    for separate, count in [(True, 1), (False, 2)]:
        design = _build_bundle(cells, BundleRequest(cells=cells, length_bp=21,
                              separate_fresh_extrusions=separate))
        assert len(design.cluster_transforms) == count


def test_circle_new_positions_are_one_independent_cluster():
    from backend.api.crud import CircleSegmentRequest, _build_circle_segment
    before = seed()
    after = build(before, CircleSegmentRequest(cells=[[0, 1], [0, 12]],
                  cell_lengths=[21, 14]), _build_circle_segment)
    assert len(after.cluster_transforms) == 2
    assert after.cluster_transforms[0] == before.cluster_transforms[0]
    assert len(after.cluster_transforms[1].helix_ids) == 2
