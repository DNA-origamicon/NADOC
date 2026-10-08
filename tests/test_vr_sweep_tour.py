"""The tour must reject an erased S, not merely accept a fitted point count."""
import math

import numpy as np
import pytest

from tools.vr_motion.metrics import rotate
from tools.vr_motion.sweep_calibration import curve
from tools.vr_workflows.sweep_probe import s_shape_report


@pytest.mark.parametrize('upright', [False, True])
def test_s_shape_requires_opposite_lobes_in_the_recorded_drawing_frame(upright):
    q = [math.sin(math.pi/4), 0, 0, math.cos(math.pi/4)] if upright else [0, 0, 0, 1]
    origin = np.array([.4, 1.1, -.8])
    points = [origin+rotate(q, curve(u, 's-curve')) for u in np.linspace(0, 1, 13)]
    assert s_shape_report(points, q)['passed']


@pytest.mark.parametrize('shape', ['line', 'arc'])
def test_straight_or_single_bend_does_not_pass_as_s_shape(shape):
    points = [curve(u, shape) for u in np.linspace(0, 1, 13)]
    assert not s_shape_report(points, [0, 0, 0, 1])['passed']


def test_s_shape_rejects_smoothing_that_erases_the_second_lobe():
    points = np.array([curve(u, 's-curve') for u in np.linspace(0, 1, 13)])
    points[:, 0] = np.maximum(points[:, 0], 0)
    assert not s_shape_report(points, [0, 0, 0, 1])['passed']
