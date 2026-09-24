import math
import pytest
from tools.vr_motion.metrics import pose_error, target_metrics, visibility, distribution


def test_ray_rectangle_boundaries_and_behind():
    target = {'position': [0, 0, -1], 'hit_half_right': [.1, 0, 0], 'hit_half_up': [0, .05, 0]}
    pose = {'position': [0, 0, 0], 'orientation_xyzw': [0, 0, 0, 1]}
    result = target_metrics(target, pose)
    assert result['predicted_hit'] and result['edge_margin_m'] == .05
    assert result['width_m'] == .2 and result['distance_m'] == 1
    pose['position'][0] = .1001
    assert not target_metrics(target, pose)['predicted_hit']
    pose['position'] = [0, 0, -2]
    assert not target_metrics(target, pose)['predicted_hit']
    pose['position'] = [0, 0, 0]
    pose['orientation_xyzw'] = [0, math.sqrt(.5), 0, math.sqrt(.5)]
    assert not target_metrics(target, pose)['predicted_hit']


def test_quaternion_sign_and_known_errors():
    want = {'position': [0, 0, 0], 'orientation': [0, 0, 0, 1]}
    got = {'position': [.003, .004, 0], 'orientation_xyzw': [0, 0, 0, -1]}
    assert pose_error(want, got) == {'position_mm': 5, 'angle_deg': 0}
    got['orientation_xyzw'] = [0, 1, 0, 0]
    assert pose_error(want, got)['angle_deg'] == 180
    assert distribution([3, 4])['rmse'] == math.sqrt(12.5)


def test_pixel_identity_requires_submission_and_exact_dimensions(tmp_path):
    evidence = {'xr_end_frame_succeeded': True, 'controller_classes': {'left': 4, 'right': 5},
                'eyes': [{'eye': 'left', 'width': 3, 'height': 2}]}
    (tmp_path/'left.classes.u8').write_bytes(bytes([0, 3, 4, 4, 5, 1]))
    assert visibility(tmp_path, evidence) == {'left': {'left': 2, 'right': 1}}
    evidence['xr_end_frame_succeeded'] = False
    with pytest.raises(ValueError):
        visibility(tmp_path, evidence)
    evidence['xr_end_frame_succeeded'] = True
    evidence['eyes'][0]['width'] = 4
    with pytest.raises(ValueError):
        visibility(tmp_path, evidence)
