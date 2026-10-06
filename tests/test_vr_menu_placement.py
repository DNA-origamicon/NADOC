"""Menu-tour geometry oracles reject the retired head/midpoint contracts."""
from types import SimpleNamespace
import math
import numpy as np
import pytest
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.menu_grip_check import assert_controller_spawn, grip_origin
from tools.vr_workflows.tour_catalog import catalog, arguments


def test_spawn_oracle_rejects_head_relative_and_wrong_tilt():
    pose = dict(position=[.3, 1.1, -.2], orientation_xyzw=[0, math.sin(.3), 0, math.cos(.3)])
    q = pose['orientation_xyzw']
    center = np.asarray(pose['position']) + rotate(q, [0, 0, -.4])
    right = rotate(q, [.2, 0, 0])
    up = rotate(q, [0, .3*math.cos(math.pi/6), -.3*math.sin(math.pi/6)])
    panel = dict(position=center.tolist(), grip_targets=[center-right, center+right, center+up, center-up])
    assert_controller_spawn(panel, pose)
    with pytest.raises(AssertionError):
        assert_controller_spawn({**panel, 'position': [0, 1, -.6]}, pose)
    flat_up = rotate(q, [0, .3, 0])
    with pytest.raises(AssertionError):
        assert_controller_spawn({**panel, 'grip_targets': [center-right, center+right, center+flat_up, center-flat_up]}, pose)


def test_grip_reach_uses_rotated_tip_and_registered_tour():
    q = [0, math.sin(math.pi/4), 0, math.cos(math.pi/4)]
    live = SimpleNamespace(state={'hands': [{}, {'orientation_xyzw': q}]})
    assert np.allclose(grip_origin(live, 1, [1, 2, 3]), [1.12, 2, 3])
    tour = next(t for t in catalog()['tours'] if t['id'] == 'grips')
    assert '--grip-checks' in arguments(tour, True)
    assert '--validate' in arguments(tour, True)
