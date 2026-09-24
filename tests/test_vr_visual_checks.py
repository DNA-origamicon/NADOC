import math
import numpy as np
import pytest
from tools.vr_motion.visual_checks import contact, coverage, project, check_capture


def test_contact_tracks_ray_direction_not_controller_body():
    state={'extrude':{'panel_position':[0,0,-1],'panel_orientation_xyzw':[0,0,0,1]}}
    pose={'position':[0,0,0],'orientation_xyzw':[0,math.sin(math.pi/8),0,math.cos(math.pi/8)]}
    assert contact(pose,state)==pytest.approx([-1,0,-1])
    assert contact(pose,state,ideal=True)==pytest.approx([0,0,-1])
    pose['orientation_xyzw']=[0,1,0,0]
    assert contact(pose,state) is None


def test_offscreen_or_blank_trace_cannot_pass_coverage():
    mask=np.zeros((30,30),dtype=bool);mask[15,15]=True
    assert coverage(mask,[(15,15),None,(100,100)],radius=1)==pytest.approx(1/3)
    assert coverage(mask,[(0,0)],radius=1)==0
    assert coverage(mask,[])==0
    eye={'position':[0,0,0],'orientation_xyzw':[0,0,0,1],
         'fov_left_right_up_down':[-math.pi/4,math.pi/4,math.pi/4,-math.pi/4], 'width':100,'height':80}
    assert project([0,0,-1],eye)==pytest.approx([50,40])
    assert project([0,0,1],eye) is None


def test_blank_eye_and_mirror_fail_even_with_successful_pose_state(tmp_path):
    from PIL import Image
    eyes=[{'eye':side,'position':[0,0,0],'orientation_xyzw':[0,0,0,1],
        'fov_left_right_up_down':[-.7,.7,.7,-.7],'width':40,'height':40} for side in ('left','right')]
    for name in ('left','right','mirror'):Image.new('RGB',(40,40)).save(tmp_path/(name+'.png'))
    for name in ('left','right'):(tmp_path/(name+'.classes.u8')).write_bytes(bytes(1600))
    state={'extrude':{'panel_position':[0,0,-1],'panel_orientation_xyzw':[0,0,0,1],
        'lattice_hit_radius_m':.01,'cells':[[0,0],[0,1],[0,2]],
        'visible_cells':[{'row':0,'column':i,'position':[i*.01,0,-1]} for i in range(3)]}}
    evidence={'eyes':eyes,'state':state,'mirror':{'source':'submitted_eye_blit_backbuffer','eye':'left',
        'width':40,'height':40,'viewport_bottom_up':[0,0,40,40]}}
    pose={'position':[0,0,0],'orientation_xyzw':[0,0,0,1]}
    result=check_capture(tmp_path,evidence,[{'intended':pose,'actual':pose}]*2,'paint')
    assert result['checks']['desktop_matches_submitted_eye']
    assert not result['checks']['desktop_traces_visible']
    assert not result['checks']['left_paint_visible']
    assert not result['checks']['right_actual_trace_visible']


def test_desktop_occlusion_is_not_a_passing_black_background_match():
    from tools.vr_motion.desktop_check import pixel_agreement
    source=np.zeros((50,50,3),dtype=np.uint8);source[10:30,10:30]=[255,190,30]
    assert pixel_agreement(source,source)['passed']
    assert not pixel_agreement(source,np.zeros_like(source))['passed']
    assert not pixel_agreement(np.zeros_like(source),np.zeros_like(source))['passed']
