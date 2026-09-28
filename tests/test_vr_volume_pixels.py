import json
import numpy as np
from PIL import Image
from tools.vr_workflows.volume_pixels import compare


def captures(tmp_path):
    enabled=tmp_path/'enabled';disabled=tmp_path/'disabled'
    enabled.mkdir();disabled.mkdir()
    eyes=[dict(eye=name,height=64,width=64,position=[0,0,0],orientation_xyzw=[0,0,0,1],
               fov_left_right_up_down=[-np.pi/4,np.pi/4,np.pi/4,-np.pi/4]) for name in ('left','right')]
    for directory in (enabled,disabled):
        (directory/'evidence.json').write_text(json.dumps(dict(eyes=eyes,depth_near_m=.1,depth_far_m=10)))
    before=np.zeros((64,64,3),np.uint8);before[:,:,0]=200
    after=before.copy();after[:,32:]=[0,200,0]
    for eye in ('left','right'):
        Image.fromarray(before).save(disabled/f'{eye}.png')
        Image.fromarray(after).save(enabled/f'{eye}.png')
        for directory in (enabled,disabled):
            np.ones((64,64),np.uint32).tofile(directory/f'{eye}.ids.u32')
        np.full((64,64),(10+.1-2*10*.1)/(10-.1)/2+.5,np.float32).tofile(disabled/f'{eye}.depth.f32')
    faces=[([0,0,-1],[-1,0,0]),([3,0,-1],[1,0,0]),([0,-3,-1],[0,-1,0]),
           ([0,3,-1],[0,1,0]),([0,0,-2],[0,0,-1]),([0,0,0],[0,0,1])]
    return enabled,disabled,{'faces':[dict(world_center=p,world_normal=n) for p,n in faces]}


def test_local_style_change_preserves_exterior(tmp_path):
    assert compare(*captures(tmp_path))['passed']


def test_global_change_cannot_pass_as_local_volume(tmp_path):
    enabled,disabled,volume=captures(tmp_path)
    for eye in ('left','right'):
        Image.fromarray(np.full((64,64,3),[0,200,0],np.uint8)).save(enabled/f'{eye}.png')
    assert not compare(enabled,disabled,volume)['passed']


def test_outline_or_controller_changes_cannot_replace_design_evidence(tmp_path):
    enabled,disabled,volume=captures(tmp_path)
    for eye in ('left','right'):
        ids=np.ones((64,64),np.uint32);ids[:,32:]=0
        ids.tofile(disabled/f'{eye}.ids.u32')
    assert not compare(enabled,disabled,volume)['passed']


def test_similar_color_from_different_primitive_is_not_a_match(tmp_path):
    enabled,disabled,volume=captures(tmp_path)
    for eye in ('left','right'):
        np.full((64,64),2,np.uint32).tofile(enabled/f'{eye}.ids.u32')
    result=compare(enabled,disabled,volume)
    assert not result['passed']
    assert all(c['exterior_stable_fraction']==0 for c in result['checks'])
