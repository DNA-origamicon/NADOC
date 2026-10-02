"""The visible-motion oracle rejects blank and unchanged submitted-eye evidence."""
import json
import numpy as np
from tools.vr_workflows.move_pixels import compare


def capture(path,shift=0,blank=False):
    path.mkdir()
    eyes=[{'eye':eye,'width':64,'height':64,'position':[0,0,0],
           'orientation_xyzw':[0,0,0,1],'fov_left_right_up_down':[-.785398,.785398,.785398,-.785398]}
          for eye in ('left','right')]
    (path/'evidence.json').write_text(json.dumps({'eyes':eyes,'depth_near_m':.1,'depth_far_m':10}))
    (path/'objects.json').write_text(json.dumps([{'id':i,'owner_tokens':['target' if i==1 else 'other']} for i in range(1,30)]))
    ids=np.zeros((64,64),dtype=np.uint32)
    if not blank:
        for i in range(1,30):
            x=4+(i%8)*7+(shift if i==1 else 0);y=4+(i//8)*7
            ids[y:y+2,x:x+2]=i
    for eye in ('left','right'):
        ids.tofile(path/f'{eye}.ids.u32')
        np.full((64,64),.91,dtype=np.float32).tofile(path/f'{eye}.depth.f32')


def test_visible_scope_must_move_and_other_geometry_stay(tmp_path):
    a,b,blank=[tmp_path/name for name in ('before','after','blank')]
    capture(a);capture(b,shift=3);capture(blank,blank=True)
    assert compare(a,b,'target')['passed']
    assert not compare(a,a,'target')['passed']
    assert not compare(blank,blank,'target')['passed']


def test_whole_scene_motion_has_no_unselected_witnesses(tmp_path):
    a,b=[tmp_path/name for name in ('before','after')]
    capture(a);capture(b,shift=3)
    # A subset cannot opt out of stationary-witness checks by calling itself
    # the whole scene: the other visible owners disqualify that claim.
    assert not compare(a,b,'target',entire_scene=True)['passed']
    for directory in (a,b):
        for eye in ('left','right'):
            path=directory/f'{eye}.ids.u32'
            ids=np.fromfile(path,dtype=np.uint32)
            ids[ids!=1]=0
            ids.tofile(path)
    assert compare(a,b,'target',entire_scene=True)['passed']
    assert not compare(a,a,'target',entire_scene=True)['passed']
