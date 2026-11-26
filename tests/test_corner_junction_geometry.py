import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.corner_junction_geometry import (
    endpoint_from_full_sites, native_seam_candidate, transported_full_sites,
)
from backend.core.native_full_placement import place_native_full


def sites():
    return dict(helix_id='source', bp_indices=np.array([50, 50]), directions=np.array([0, 1]),
                axis_points=np.array([[0., 0., 3.], [0., 0., 3.]]),
                radial_hats=np.array([[1., 0., 0.], [1., 0., 0.]]),
                axis_tangents=np.array([[0., 0., 1.], [0., 0., 1.]]), azimuths=np.zeros(2))


def test_transport_commutes_with_native_projection_and_preserves_source():
    source = sites()
    before = {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in source.items()}
    original = place_native_full(source)
    center = np.array((8., -2., 7.))
    rotation = Rotation.from_euler('xyz', [15, 90, -30], degrees=True).as_matrix()
    moved = transported_full_sites(source, center_nm=center, rotation=rotation)
    for key in ('positions', 'base_positions', 'axis_points'):
        np.testing.assert_allclose(moved[key], (original[key] - center) @ rotation.T + center, atol=1e-12)
    for key in ('base_normals', 'axis_tangents'):
        np.testing.assert_allclose(moved[key], original[key] @ rotation.T, atol=1e-12)
    for key in before:
        np.testing.assert_equal(source[key], before[key])
    assert 'placement_source' not in source


def test_endpoint_is_native_backbone_not_cylinder_axis():
    full = place_native_full(sites())
    endpoint = endpoint_from_full_sites(full, 50, 'REVERSE')
    np.testing.assert_allclose(endpoint['backbone_position'], full['positions'][1])
    assert np.linalg.norm(np.asarray(endpoint['backbone_position']) - full['axis_points'][1]) > .5
    assert endpoint['direction'] == 'REVERSE'
    with pytest.raises(ValueError, match='missing'):
        endpoint_from_full_sites(full, 49, 'FORWARD')
    with pytest.raises(ValueError, match='authoritative'):
        endpoint_from_full_sites(sites(), 50, 'FORWARD')


@pytest.mark.parametrize('sequence', ['', 'N', 'NN', 'NNN', 'ACGT'])
def test_native_seam_accounts_for_every_insert_and_backbone_edge(sequence):
    a = dict(backbone_position=[0., 0., 0.], axis_tangent=[0., 0., 1.], direction='FORWARD')
    b = dict(backbone_position=[1.1, .2, .1], axis_tangent=[1., 0., 0.], direction='FORWARD')
    result = native_seam_candidate(a, b, sequence)
    assert result.sequence == sequence
    assert len(result.insert_backbone_positions) == len(sequence)
    assert len(result.backbone_lengths_nm) == len(sequence) + 1
    assert np.isfinite(result.backbone_lengths_nm).all()
    assert sum(result.backbone_lengths_nm) >= np.linalg.norm(b['backbone_position']) - 1e-10
    if not sequence:
        assert result.max_backbone_length_nm == pytest.approx(np.linalg.norm(b['backbone_position']))


def test_rejects_reflections_and_nonfinite_or_nonunit_inputs():
    with pytest.raises(ValueError, match='proper rigid'):
        transported_full_sites(sites(), center_nm=[0, 0, 0], rotation=np.diag([1, 1, -1]))
    with pytest.raises(ValueError, match='projected'):
        transported_full_sites(place_native_full(sites()), center_nm=[0, 0, 0], rotation=np.eye(3))
    a = dict(backbone_position=[0, 0, 0], axis_tangent=[0, 0, 2], direction='FORWARD')
    with pytest.raises(ValueError, match='unit tangents'):
        native_seam_candidate(a, a, 'NN')
    with pytest.raises(ValueError, match='uppercase DNA'):
        native_seam_candidate(a, a, 'tt')
