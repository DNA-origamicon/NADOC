import numpy as np
import pytest
from backend.core.bevel_plan import intersect_bevel_plane


@pytest.mark.parametrize('residual', [-1e-14, 0, 1e-14])
def test_on_plane_station_is_counted_once(residual):
    bps = np.array([0, 1, 2])
    points = np.array([[0., 0., -1.], [0., 0., residual], [0., 0., 1.]])
    bp, point = intersect_bevel_plane(bps, points, np.zeros(3), np.array([0, 0, 1]))
    assert bp == 1
    np.testing.assert_array_equal(point, points[1])


def test_interpolated_crossing_and_true_multiple_crossings():
    bps = np.array([0., 1., 2., 3.])
    points = np.array([[0., 0., z] for z in [-1, -.5, .5, 1]])
    bp, point = intersect_bevel_plane(bps, points, np.zeros(3), np.array([0, 0, 1]))
    assert bp == 1.5
    np.testing.assert_array_equal(point, np.zeros(3))
    points[:, 2] = [-1, 1, -1, 1]
    with pytest.raises(ValueError, match='exactly once'):
        intersect_bevel_plane(bps, points, np.zeros(3), np.array([0, 0, 1]))
