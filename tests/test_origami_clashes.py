"""Geometric negative controls for conservative body-clearance constraints."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from backend.core.origami_clashes import PlanarBodyClearance


def boxes():
    square = np.array(
        [[0.0, 0.0, 0.0], [2.0, 0.0, 0.0], [2.0, 2.0, 0.0], [0.0, 2.0, 0.0]]
    )
    return PlanarBodyClearance(
        [square, square], [[0], [1]], np.zeros((2, 3)), np.eye(3)[:2]
    )


@pytest.mark.parametrize(
    "shift, expected", [(0.0, -2.0), (1.0, -1.0), (3.0, 1.0), (5.0, 3.0)]
)
def test_signed_clearance_detects_overlap_and_separation(shift, expected):
    clearance = boxes()
    gaps = clearance.gaps(
        Rotation.identity(2), np.array([[0.0, 0.0, 0.0], [shift, 0.0, 0.0]])
    )
    assert gaps[0] == pytest.approx(expected)


def test_crossing_thin_bodies_cannot_hide_intersection():
    line = np.array([[-5.0, 0.0, 0.0], [5.0, 0.0, 0.0]])
    clearance = PlanarBodyClearance(
        [line, line], [[0], [1]], np.zeros((2, 3)), np.eye(3)[:2]
    )
    rotations = Rotation.from_rotvec([[0.0, 0.0, 0.0], [0.0, 0.0, np.pi / 2]])
    assert clearance.summary(rotations, np.zeros((2, 3)))["overlapping_body_pairs"] == 1
    assert clearance.gaps(rotations, np.zeros((2, 3)))[0] < 0


def test_rotated_touching_boxes_need_radius_clearance():
    clearance = boxes()
    rotations = Rotation.from_rotvec([[0.0, 0.0, 0.0], [0.0, 0.0, np.pi / 2]])
    translations = np.array([[0.0, 0.0, 0.0], [4.0, 0.0, 0.0]])
    assert clearance.gaps(rotations, translations)[0] == pytest.approx(0.0)
    assert clearance.summary(rotations, translations)["overlapping_body_pairs"] == 1
