"""Independent ordering, stress paths, stereo oracle and tour discoverability."""
import numpy as np
import pytest
from tools.vr_workflows.selection_wheel_check import LEVELS, AXES, thumb_samples, amber_pixels
from tools.vr_workflows.tour_catalog import catalog, arguments


def test_clockwise_layout_and_discoverability():
    assert LEVELS == ('default', 'cluster', 'strand', 'domain', 'xover', 'base')
    assert AXES[0] == (0, .8) and AXES[3] == (0, -.8)
    assert AXES[1][0] > 0 and AXES[-1][0] < 0
    tour = next(t for t in catalog()['tours'] if t['id'] == 'selection-wheel')
    assert tour['group'] == 'interaction' and tour['runnable']
    assert '--selection-checks' in arguments(tour, True)
    assert '--validate' in arguments(tour, True)


@pytest.mark.parametrize('preset', ['steady_fast', 'steady_deliberate', 'variable_fast', 'variable_deliberate'])
def test_thumb_paths_retain_noisy_intermediate_motion(preset):
    for axis in AXES:
        samples = thumb_samples(preset, (0, 0), axis, 41)
        assert samples[0]['t'] == 0 and samples[-1]['t'] > .6
        assert all(-1 <= x <= 1 for s in samples for x in s['axis'])
        assert any(.1 < np.linalg.norm(s['axis']) < .7 for s in samples)
        assert np.linalg.norm(np.asarray(samples[-1]['axis'])-axis) < .1
        assert samples == thumb_samples(preset, (0, 0), axis, 41)


def test_pixel_oracle_rejects_blank_offscreen_and_wrong_color():
    eye = dict(position=[0, 0, 0], orientation_xyzw=[0, 0, 0, 1],
               fov_left_right_up_down=[-.7, .7, .7, -.7], width=200, height=200)
    image = np.zeros((200, 200, 3), dtype=np.uint8)
    assert amber_pixels(image, eye, [0, 0, -1]) == 0
    image[95:105, 95:105] = [255, 200, 40]
    assert amber_pixels(image, eye, [0, 0, -1]) == 100
    assert amber_pixels(image, eye, [1000, 1000, 1000]) == 0
    image[95:105, 95:105] = [80, 180, 255]
    assert amber_pixels(image, eye, [0, 0, -1]) == 0


def test_review_refreshes_only_owned_pad_axis_until_stopped():
    from unittest.mock import Mock
    from tools.vr_workflows.selection_wheel_check import review
    live = Mock()
    alive = iter([True, True, False])
    review(live, lambda: next(alive), sleep=lambda _: None)
    assert live.send.call_count == live.frame.call_count == 2
    live.send.assert_called_with('trackpad_axis', hand=0, x=0, y=.8)
    live.release.assert_not_called()  # Enclosing tour owns failure-safe release.
