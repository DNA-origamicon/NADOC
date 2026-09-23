from copy import deepcopy
import math
import pytest
from tools.vr_workflows.placement_oracle import compare, check_design


def example():
    # View: scale2, rotate90deg about Z, translate(1,2,3).
    view = {'model_to_tracking_rows':[[0,-2,0,1],[2,0,0,2],[0,0,2,3],[0,0,0,1]],
            'source_center_nm':[10,20,30],'normalization_model_per_nm':.01,
            'normalized_offset_model':[0,0,-1]}
    cluster = {'translation':[12,23,34],'rotation':[0,1,0,0],
               'pivot':[0,0,0],'parent_cluster_id':None}
    pose = {'position':[.94,2.04,1.08],
            'orientation_xyzw':[0,0,math.sqrt(.5),math.sqrt(.5)]}
    return view,pose,cluster


def test_forward_mapping_includes_view_scale_rotation_center_and_offset():
    view,pose,cluster = example()
    assert compare(view,pose,cluster,'XY')['passed']
    wrong = deepcopy(cluster);wrong['translation'][0] += .02
    assert not compare(view,pose,wrong,'XY')['passed']


def test_design_check_uses_frame_cluster_identity_and_actual_pose():
    view,pose,cluster = example()
    cluster['id'] = 'placed'
    capture = {'state':{'presentation':view,'extrude':{'freeform_placed':True}},
               'actual_capture_pose':pose,'position':[99,99,99]}
    design = {'lattice_frames':[{'plane':'XY','placement_cluster_id':'placed'}],
              'cluster_transforms':[{'id':'unrelated'},cluster]}
    assert check_design(capture,design)['passed']
    capture['actual_capture_pose'] = {**pose,'position':[99,99,99]}
    assert not check_design(capture,design)['passed']
    wrong = deepcopy(cluster);wrong['rotation'] = [0,0,0,1]
    assert not compare(view,pose,wrong,'XY')['passed']


@pytest.mark.parametrize('plane,q', [('XY',[0,1,0,0]),
    ('XZ',[-math.sqrt(.5),0,0,math.sqrt(.5)]),
    ('YZ',[0,math.sqrt(.5),0,math.sqrt(.5)])])
def test_each_plane_preserves_transverse_orientation(plane,q):
    view,pose,cluster = example()
    cluster['rotation'] = q
    assert compare(view,pose,cluster,plane)['passed']
    # Same axial direction can hide a 180degree roll: full rotation must reject it.
    cluster['rotation'] = [-q[1],q[0],q[3],-q[2]]
    assert not compare(view,pose,cluster,plane)['passed']


@pytest.mark.parametrize('change', ['scale','shear','reflection','normalization','parent','pivot'])
def test_invalid_mapping_context_fails_closed(change):
    view,pose,cluster = example()
    if change == 'scale':view['model_to_tracking_rows'][2][2] = 3
    if change == 'shear':view['model_to_tracking_rows'][0][2] = .1
    if change == 'reflection':view['model_to_tracking_rows'][2][2] = -2
    if change == 'normalization':view['normalization_model_per_nm'] = float('nan')
    if change == 'parent':cluster['parent_cluster_id'] = 'another'
    if change == 'pivot':cluster['pivot'] = [1,0,0]
    with pytest.raises(ValueError):compare(view,pose,cluster,'XY')
