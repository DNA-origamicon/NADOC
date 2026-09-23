import math
import pytest
from tools.vr_workflows.profile_input import aim_orientation, target_reaches
from tools.vr_motion.metrics import rotate


@pytest.mark.parametrize('target', [(0,0,-1),(0,0,1),(1,2,3),(-2,1,-4)])
def test_ray_points_at_target(target):
    q=aim_orientation([0,0,0],target)
    norm=math.sqrt(sum(v*v for v in target))
    assert rotate(q,[0,0,-1]) == pytest.approx([v/norm for v in target])


def test_coincident_target_is_rejected():
    with pytest.raises(ValueError):aim_orientation([1,2,3],[1,2,3])


def test_noisy_endpoint_is_not_pinned_and_seed_is_repeatable():
    args=({'position':[0,0,0], 'orientation_xyzw':[0,0,0,1]},[1,0,-1],'steady_fast',17)
    ideal,noisy=target_reaches(*args)
    assert target_reaches(*args)==(ideal,noisy)
    assert noisy['samples'][-1]['hands']['right'] != ideal['samples'][-1]['hands']['right']
    assert len(noisy['samples'])==len(ideal['samples'])


@pytest.mark.parametrize('preset', ['steady_fast','steady_deliberate','variable_fast','variable_deliberate'])
def test_explicit_pose_keeps_wrist_roll_and_unpinned_endpoint(preset):
    pose = {'position':[0,0,0], 'orientation_xyzw':[0,0,0,1]}
    destination = [.3,.2,-.5]
    # A 90-degree roll has the same forward ray as identity; aiming cannot encode it.
    orientation = [0,0,math.sqrt(.5),math.sqrt(.5)]
    ideal,noisy = target_reaches(pose,destination,preset,29,destination,orientation)
    endpoint = ideal['samples'][-1]['hands']['right']
    assert endpoint['position'] == pytest.approx(destination)
    assert rotate(endpoint['orientation'],[1,0,0]) == pytest.approx([0,1,0])
    assert noisy['samples'][-1]['hands']['right'] != endpoint
    assert target_reaches(pose,destination,preset,29,destination,orientation) == (ideal,noisy)
    with pytest.raises(ValueError,match='normalized'):
        target_reaches(pose,destination,preset,29,destination,[0,0,0,0])


def test_pose_playback_records_applied_error_without_snapping(monkeypatch):
    from tools.vr_workflows import profile_input
    clock = [0.0]
    monkeypatch.setattr(profile_input.time,'monotonic',lambda:clock[0])
    monkeypatch.setattr(profile_input.time,'sleep',lambda seconds:clock.__setitem__(0,clock[0]+seconds))
    class Live:
        state = {'hands':[{}, {'position':[0,0,0], 'orientation_xyzw':[0,0,0,1]}], 'frame':0}
        def send(self, action, **pose):
            assert action == 'pose' and pose['hand'] == 1
            self.state['hands'][1] = {'position':[pose['position'][0]+.001,*pose['position'][1:]],
                                      'orientation_xyzw':pose['orientation']}
        def frame(self):
            self.state['frame'] += 1
    live = Live()
    result = profile_input.reach_target(live,[.3,.2,-.5],'variable_fast',29,
        target_position=[.3,.2,-.5],target_orientation=[0,0,1,0])
    assert result['position_policy'] == 'explicit_pose'
    assert result['stop_reason'] == 'completed_reach'
    assert all(s['applied_error']['position_mm'] == pytest.approx(1) for s in result['samples'])
    assert result['samples'][-1]['actual'] == live.state['hands'][1]
    assert result['samples'][-1]['desired']['position'] != pytest.approx([.3,.2,-.5])


def test_feedback_window_ignores_early_hover_and_resets_on_miss():
    from tools.vr_workflows.profile_input import AcquisitionWindow
    window = AcquisitionWindow(1.8,.3)
    assert not window.update(.1,True)
    assert not window.update(1.75,True)
    assert not window.update(1.9,True)
    assert not window.update(1.95,False)
    assert not window.update(2,True)
    assert not window.update(2.25,True)
    assert window.update(2.3,True)


def test_feedback_window_does_not_accept_transient_crossing():
    from tools.vr_workflows.profile_input import AcquisitionWindow
    window = AcquisitionWindow(.65,.12)
    assert not window.update(.15,True)
    assert not window.update(.2,False)
    assert not window.update(.25,True)
    assert not window.update(.3,True)


def test_feedback_can_acquire_midreach_without_waiting_for_final_sample():
    from tools.vr_workflows.profile_input import AcquisitionWindow
    window = AcquisitionWindow(1.8,.3)
    assert not window.update(.95,True)
    assert not window.update(1.15,True)
    assert window.update(1.25,True)


def test_translating_approach_starts_at_actual_pose_and_keeps_noise():
    pose = {'position':[0,0,0], 'orientation_xyzw':[0,0,0,1]}
    ideal,noisy = target_reaches(pose,[1,0,-1],'variable_fast',17,[1,0,-.7])
    assert ideal['samples'][0]['hands']['right']['position'] == pose['position']
    assert ideal['samples'][-1]['hands']['right']['position'] == pytest.approx([1,0,-.7])
    assert noisy['samples'][-1]['hands']['right']['position'] != ideal['samples'][-1]['hands']['right']['position']
    q = ideal['samples'][-1]['hands']['right']['orientation']
    assert rotate(q,[0,0,-1]) == pytest.approx([0,0,-1])


@pytest.mark.parametrize('hand,expected', [([0,0,0],[0,0,-.7]),([0,0,-2],[0,0,-1.3])])
def test_control_approach_preserves_side(hand,expected):
    from tools.vr_workflows.control_approach import control_approach
    target = {'position':[0,0,-1], 'hit_half_right':[.1,0,0], 'hit_half_up':[0,.04,0]}
    assert control_approach(target,hand) == pytest.approx(expected)
    with pytest.raises(ValueError,match='target plane'):
        control_approach(target,[0,0,-1])
    target['hit_half_up'] = [.1,0,0]
    with pytest.raises(ValueError,match='degenerate'):
        control_approach(target,hand)


def test_control_approach_uses_rotated_rectangle_not_world_z():
    from tools.vr_workflows.control_approach import control_approach
    target = {'position':[2,1,0], 'hit_half_right':[0,0,.1], 'hit_half_up':[0,.04,0]}
    assert control_approach(target,[3,1,0]) == pytest.approx([2.3,1,0])


def test_lattice_approach_tracks_cell_in_rotated_panel_without_using_hit_radius():
    from tools.vr_workflows.control_approach import lattice_approach
    panel = {'panel_orientation_xyzw':[0,math.sqrt(.5),0,math.sqrt(.5)],
             'lattice_hit_radius_m':.026}
    assert lattice_approach(panel,[1,2,3],[2,1,3]) == pytest.approx([1.3,2,3])
    panel['lattice_hit_radius_m'] = .001
    assert lattice_approach(panel,[1,2.2,3],[2,1,3]) == pytest.approx([1.3,2.2,3])
    assert lattice_approach(panel,[1,2,3],[0,1,3]) == pytest.approx([.7,2,3])
