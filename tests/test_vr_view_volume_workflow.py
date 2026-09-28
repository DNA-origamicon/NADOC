"""ScryWrite evidence must fail for blank/offscreen/missing-eye captures."""
import numpy as np
from PIL import Image
from tools.vr_workflows.view_volumes_check import highlight_pixels, highlight_passed
from tools.vr_workflows.tour_catalog import catalog, arguments


def test_demo_and_validation_use_same_owned_workflow():
    tour=next(t for t in catalog()['tours'] if t['id']=='view-volumes')
    assert tour['runnable'] and tour['group']=='view-volumes'
    assert arguments(tour)==['-m','tools.vr_workflows.view_volumes_check','--demo']
    assert arguments(tour,True)==['-m','tools.vr_workflows.view_volumes_check','--validate']


def test_highlight_requires_visible_expected_pixels_in_both_eyes(tmp_path):
    eyes=[dict(eye=side,position=[0,0,0],orientation_xyzw=[0,0,0,1],
               fov_left_right_up_down=[-.7,.7,.7,-.7],width=64,height=64) for side in ('left','right')]
    evidence={'eyes':eyes}
    blank=np.zeros((64,64,3),dtype=np.uint8)
    def write(side,rgb):Image.fromarray(rgb).save(tmp_path/(side+'.png'))
    for side in ('left','right'):write(side,blank)
    assert not highlight_passed(highlight_pixels(tmp_path,evidence,[[0,0,-1]]))
    gold=blank.copy();gold[28:37,28:37]=[255,204,38]
    write('left',gold)
    assert not highlight_passed(highlight_pixels(tmp_path,evidence,[[0,0,-1]]))
    write('right',gold)
    assert highlight_passed(highlight_pixels(tmp_path,evidence,[[0,0,-1]]))
    for points in ([],[[0,0,1]],[[100,0,-1]]):
        assert not highlight_passed(highlight_pixels(tmp_path,evidence,points))
    blue=blank.copy();blue[28:37,28:37]=[70,181,255]
    for side in ('left','right'):write(side,blue)
    assert not highlight_passed(highlight_pixels(tmp_path,evidence,[[0,0,-1]]))
    assert not highlight_passed([])
    assert not highlight_passed([{'eye':'left','fraction':1}])

def test_face_checks_sample_edges_not_the_orange_controller_at_center(tmp_path):
    from tools.vr_workflows.view_volumes_check import face_samples
    presentation=dict(source_center_nm=[0,0,0],normalization_model_per_nm=1,
                      normalized_offset_model=[0,0,0],model_to_tracking_rows=np.eye(4).tolist())
    entry=dict(half_nm=[.3,.3,.3],center_nm=[0,0,-1],rotation_xyzw=[0,0,0,1],faces=[{}]*6)
    samples=face_samples(entry,5,presentation)
    assert len(samples)==4
    assert all(np.linalg.norm(np.array(p)-[0,0,-.7])>.2 for p in samples)
    eyes=[dict(eye=side,position=[0,0,0],orientation_xyzw=[0,0,0,1],
               fov_left_right_up_down=[-.7,.7,.7,-.7],width=128,height=128) for side in ('left','right')]
    controller=np.zeros((128,128,3),dtype=np.uint8);controller[60:69,60:69]=[255,166,25]
    for side in ('left','right'):Image.fromarray(controller).save(tmp_path/(side+'.png'))
    assert not highlight_passed(highlight_pixels(tmp_path,{'eyes':eyes},samples))
    entry['faces']=[{}]*8
    assert len(face_samples(entry,7,presentation))==6
