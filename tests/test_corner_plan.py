"""Analytic oracles for a non-authoring cylinder guide; no Design is generated."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.corner_plan import AxisPath, CornerParameters, plan_corner_guide


FRAME = dict(axis_dir=(0, 0, 1), frame_right=(1, 0, 0), frame_up=(0, 1, 0))


def test_unoccupied_curve_prefix_cannot_create_an_extra_plane_crossing():
    raw = AxisPath('path', (0, 20, 40, 60, 100),
                   ((0, 0, 0), (0, 0, 20), (0, 0, -20), (0, 0, -10), (0, 0, 30)))
    params = CornerParameters(70, 90, 0)
    with pytest.raises(ValueError, match='exactly once'):
        plan_corner_guide([raw], params, **FRAME)
    occupied = raw.clipped(50.5, 99.5)
    assert occupied.stations_bp == (50.5, 60, 99.5)
    assert occupied.points_nm[0] == pytest.approx((0, 0, -14.75))
    assert occupied.points_nm[-1] == pytest.approx((0, 0, 29.5))
    guide = plan_corner_guide([occupied], params, **FRAME)
    assert guide.cuts[0].incoming_bp == pytest.approx(70)
    assert guide.cuts[0].outgoing_bp == pytest.approx(70)


def paths():
    return tuple(AxisPath(str(i), (0, 100), ((x, 0, -50), (x, 0, 50)))
                 for i, x in enumerate((-3., -1., 1., 3.)))


@pytest.mark.parametrize("angle", [0, 15, 45, 90, 120, 150])
def test_symmetric_miter_intersects_without_shearing_cross_section(angle):
    guide = plan_corner_guide(paths(), CornerParameters(50, angle, 0), **FRAME)
    for path, cut in zip(paths(), guide.cuts):
        shift = path.points_nm[0][0] * np.tan(np.deg2rad(angle / 2))
        assert cut.incoming_bp == pytest.approx(50 - shift)
        assert cut.outgoing_bp == pytest.approx(50 + shift)
        assert cut.incoming_nm == pytest.approx(cut.outgoing_nm)
        assert cut.incoming_path_nm[0] == path.points_nm[0]
        mobile = np.asarray(cut.outgoing_path_nm)
        tangent = (mobile[-1] - mobile[0]) / np.linalg.norm(mobile[-1] - mobile[0])
        assert tangent == pytest.approx((np.sin(np.deg2rad(angle)), 0, np.cos(np.deg2rad(angle))))


def test_material_frame_follows_existing_twist_and_rigid_pose():
    baseline = plan_corner_guide(paths(), CornerParameters(50, 90, 30), **FRAME)
    rotation = Rotation.from_euler('xyz', (35, -42, 81), degrees=True).as_matrix()
    offset = np.array((17, -9, 28))
    moved = tuple(AxisPath(p.helix_id, p.stations_bp,
                          tuple(map(tuple, np.asarray(p.points_nm) @ rotation.T + offset))) for p in paths())
    frame = {key: rotation @ value for key, value in FRAME.items()}
    guide = plan_corner_guide(moved, CornerParameters(50, 90, 30), **frame)
    assert guide.center_nm == pytest.approx(rotation @ baseline.center_nm + offset)
    for a, b in zip(baseline.cuts, guide.cuts):
        assert a.incoming_bp == pytest.approx(b.incoming_bp)
        assert a.outgoing_bp == pytest.approx(b.outgoing_bp)
        np.testing.assert_allclose(b.outgoing_path_nm, np.asarray(a.outgoing_path_nm) @ rotation.T + offset)


def test_curved_path_is_retained_on_both_sides():
    path = AxisPath('curve', (0, 20, 50, 70, 100),
                    ((-4, 0, -50), (-1, 0, -30), (0, 0, 0), (2, 0, 20), (9, 0, 50)))
    guide = plan_corner_guide((path,), CornerParameters(50, 90, 0), **FRAME)
    cut, = guide.cuts
    np.testing.assert_allclose(cut.incoming_path_nm, path.points_nm[:3])
    np.testing.assert_allclose(cut.outgoing_path_nm, np.asarray(path.points_nm[2:]) @ np.asarray(guide.rotation).T, atol=1e-12)


def test_direction_is_local_azimuth_and_normalized():
    a = plan_corner_guide(paths(), CornerParameters(50, 90, -270), **FRAME)
    b = plan_corner_guide(paths(), CornerParameters(50, 90, 90), **FRAME)
    assert a == b
    assert np.asarray(a.rotation) @ np.array((0, 0, 1)) == pytest.approx((0, 1, 0), abs=1e-12)


@pytest.mark.parametrize('params', [(True, 90, 0), (0.5, 90, 0), (0, -1, 0),
                                    (0, 180, 0), (0, float('nan'), 0), (0, 90, float('inf'))])
def test_rejects_invalid_parameters(params):
    with pytest.raises(ValueError):
        CornerParameters(*params)


def test_refuses_impossible_miter_instead_of_clamping_to_ends():
    with pytest.raises(ValueError, match='cross the corner plane'):
        plan_corner_guide(paths(), CornerParameters(50, 179, 0), **FRAME)


def test_rejects_multiple_crossings_of_curved_path():
    loop = AxisPath('loop', (0, 25, 50, 75, 100),
                    ((0, 0, -10), (0, 0, 10), (0, 0, 0), (0, 0, -10), (0, 0, 10)))
    with pytest.raises(ValueError, match='exactly once'):
        plan_corner_guide((loop,), CornerParameters(50, 0, 0), **FRAME)


def test_rejects_wrong_handed_frame_and_reversed_path():
    with pytest.raises(ValueError, match='right-handed'):
        plan_corner_guide(paths(), CornerParameters(50, 90, 0), **{**FRAME, 'frame_up': (0, -1, 0)})
    reverse = AxisPath('reverse', (0, 100), ((0, 0, 50), (0, 0, -50)))
    with pytest.raises(ValueError, match='traversal'):
        plan_corner_guide((reverse,), CornerParameters(50, 0, 0), **FRAME)


def test_requires_material_on_both_sides_and_valid_sampling():
    with pytest.raises(ValueError, match='both sides'):
        plan_corner_guide(paths(), CornerParameters(0, 0, 0), **FRAME)
    malformed = AxisPath('bad', (0, 0), ((0, 0, 0), (0, 0, 10)))
    with pytest.raises(ValueError, match='ordered axis'):
        malformed.point(0)
