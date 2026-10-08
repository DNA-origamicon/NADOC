"""Authored point frames, direction-dependent warnings, persistence and preview parity."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from backend.core.models import Design
from backend.core.sweep import SweepRequest, sweep_preview, build_sweep
from backend.core.sweep_path import canonical_basis, oriented_sample
from backend.core.lattice import make_bundle_design


@pytest.mark.parametrize('plane,normal', [('XY',[0,0,1]), ('XZ',[0,1,0]), ('YZ',[1,0,0])])
def test_endpoint_direction_and_twist_are_exact_in_starting_plane(plane, normal):
    basis = canonical_basis(normal)
    points = (np.array([[0,0,0],[2,0,12],[10,3,20]]) @ basis.T).tolist()
    angles = [[0,0,0], None, [15,90,45]]
    body = SweepRequest(cells=[(0,0),(0,1)], points_nm=points, orientations_deg=angles, plane=plane)
    preview, _ = sweep_preview(Design(), body, include_geometry=True)
    local = np.column_stack([preview['cross_section_nm'],np.zeros(len(body.cells))])
    np.testing.assert_allclose(np.asarray(preview['helix_paths_nm'])[:,0,:], local @ np.asarray(preview['point_bases'][0]).T + preview['origin_nm'], atol=1e-8)
    expected = basis @ Rotation.from_euler('YXZ',[90,15,45], degrees=True).as_matrix()
    np.testing.assert_allclose(preview['point_bases'][-1], expected, atol=1e-8)
    result = build_sweep(Design(), body)
    restored = Design.model_validate_json(result.model_dump_json())
    p = restored.deformations[0].params
    _, actual, _ = oriented_sample(p.points_nm, [p.path_length_nm], p.initial_tangent,
        np.asarray(p.initial_rotation).reshape(3,3), np.asarray(normal), p.point_frames)
    np.testing.assert_allclose(actual[0] @ basis, expected, atol=1e-8)
    # Canonical helix offsets in the ghost and committed evaluation agree.
    from backend.core.deformation import deformed_helix_axes
    axes = deformed_helix_axes(result)
    np.testing.assert_allclose(axes[0]['samples'][-1], preview['helix_paths_nm'][0][-1], atol=1e-6)


def test_roll_preserves_positions_and_interpolates_without_rotating_uncontrolled_origin():
    points = [[0,0,0],[0,0,10],[0,0,20]]
    preview, _ = sweep_preview(Design(), SweepRequest(cells=[(0,0)], points_nm=points,
        orientations_deg=[None,None,[0,0,90]]))
    np.testing.assert_allclose(preview['point_bases'][0], np.eye(3), atol=1e-9)
    np.testing.assert_allclose(preview['point_bases'][1], Rotation.from_euler('z',45,degrees=True).as_matrix(), atol=1e-9)
    np.testing.assert_allclose(np.asarray(preview['path_nm'])[:,:2], 0, atol=1e-9)


def test_disabling_all_controls_restores_legacy_spline():
    points = [[0,0,0],[3,2,8],[7,-2,15]]
    a,_ = sweep_preview(Design(), SweepRequest(cells=[(0,0)], points_nm=points))
    b,_ = sweep_preview(Design(), SweepRequest(cells=[(0,0)], points_nm=points, orientations_deg=[None]*3))
    np.testing.assert_array_equal(a['path_nm'], b['path_nm'])


def test_warning_depends_on_footprint_orientation_and_does_not_block_creation():
    points = [[0,0,0],[0,0,5],[5,0,5]]
    cells = [(0,i) for i in range(9)]
    normal = SweepRequest(cells=cells, points_nm=points, ligate_adjacent=False)
    turned = normal.model_copy(update={'orientations_deg': [(0,0,90), None, None]})
    a,_ = sweep_preview(Design(),normal)
    b,_ = sweep_preview(Design(),turned)
    assert a['feasibility']['status'] == 'warning'
    assert a['feasibility']['warning_segments']
    assert b['feasibility']['max_delta_per_cell'] < a['feasibility']['max_delta_per_cell'] * .1
    assert build_sweep(Design(), normal).helices


def test_attached_source_orientation_is_preserved_when_endpoint_twists():
    original = make_bundle_design([(0,0)], 21)
    body = SweepRequest(cells=[(0,0)], points_nm=[[0,0,0],[0,0,10]],
        orientations_deg=[None,[0,0,90]], source_helix_id=original.helices[0].id)
    preview,_ = sweep_preview(original, body)
    np.testing.assert_allclose(preview['point_bases'][0],np.eye(3),atol=1e-8)
    with pytest.raises(ValueError, match='origin orientation'):
        SweepRequest(**{**body.model_dump(), 'orientations_deg': [[15,0,0],None]})


@pytest.mark.parametrize('angles', [[], [[0,0,0]], [[0,0,0],[float('nan'),0,0]], [[0,0,0],[0,0,361]]])
def test_invalid_orientations_rejected(angles):
    with pytest.raises(ValueError):
        SweepRequest(cells=[(0,0)],points_nm=[[0,0,0],[0,0,10]],orientations_deg=angles)


def test_oriented_continuation_inherits_rotated_cluster_without_double_rotation():
    from backend.core.models import ClusterRigidTransform
    from backend.core.deformation import deformed_helix_axes
    original = make_bundle_design([(0,0),(0,1)],21)
    rotation = Rotation.from_euler('xyz',[20,30,40],degrees=True)
    original = original.copy_with(cluster_transforms=[ClusterRigidTransform(
        helix_ids=[h.id for h in original.helices],rotation=rotation.as_quat().tolist(),translation=[10,20,30])])
    points=rotation.apply([[0,0,0],[0,0,8],[5,0,15]]).tolist()
    body=SweepRequest(cells=[(0,0),(0,1)],points_nm=points,orientations_deg=[None,None,[15,45,60]],
        source_helix_id=original.helices[0].id)
    preview,_=sweep_preview(original,body,include_geometry=True)
    result=build_sweep(original,body)
    axes=deformed_helix_axes(result)
    for actual,expected in zip(axes[-2:],preview['helix_paths_nm']):
        np.testing.assert_allclose(actual['samples'][-1],expected[-1],atol=1e-7)

@pytest.mark.parametrize('attached', [False, True])
def test_new_bp_total_matches_added_helix_sites(attached):
    cells = [(0,0),(0,1)]
    design = make_bundle_design(cells,21) if attached else Design()
    body = SweepRequest(cells=cells,points_nm=[[0,0,0],[0,0,10]],
        source_helix_id=design.helices[0].id if attached else None)
    preview,_ = sweep_preview(design,body)
    result = build_sweep(design,body)
    assert preview['total_new_bp'] == sum(h.length_bp for h in result.helices)-sum(h.length_bp for h in design.helices)
    assert preview['total_new_bp'] == 2*preview['length_bp']
