import numpy as np
from tools.vr_workflows.move_pixels import remote_drag_delta


def test_fixed_wrist_preserves_hand_translation():
    start=dict(position=[1,2,3],orientation_xyzw=[0,0,0,1])
    end=dict(position=[1.1,2.2,3.3],orientation_xyzw=[0,0,0,1])
    np.testing.assert_allclose(remote_drag_delta(start,end,.45),[.1,.2,.3])


def test_stationary_hand_rotates_remote_point_at_grabbed_depth():
    start=dict(position=[1,2,3],orientation_xyzw=[0,0,0,1])
    end=dict(position=[1,2,3],orientation_xyzw=[0,np.sqrt(.5),0,np.sqrt(.5)])
    np.testing.assert_allclose(remote_drag_delta(start,end,2),[-2,0,2],atol=1e-12)
    np.testing.assert_allclose(remote_drag_delta(start,end,0),[0,0,0],atol=1e-12)


def test_remote_approach_clears_large_origami_without_changing_small_fixture():
    from tools.vr_workflows.move_pixels import remote_pointing_distance
    aim=np.array([0.,0.,0.]);toward=np.array([0.,0.,1.])
    assert remote_pointing_distance(aim,toward,[]) == .45
    assert remote_pointing_distance(aim,toward,[[0,0,.1]]) == .45
    distance=remote_pointing_distance(aim,toward,[[0,0,.7],[.2,0,.4]])
    np.testing.assert_allclose(distance,.9)
    assert distance-.7 > .15
