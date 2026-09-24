import math
import pytest
from tools.vr_workflows.review_view import coverage, visible_center


def image_rect(width,height,x0,y0,x1,y1):
    return [int(x0<=x<x1 and y0<=y<y1) for y in range(height) for x in range(width)]


def test_coverage_rejects_blank_tiny_and_edge_clipped_despite_pixel_presence():
    assert not coverage([0]*40000,200,200)['passed']
    tiny=image_rect(1000,1000,450,450,490,490)
    assert sum(tiny)>1000
    assert not coverage(tiny,1000,1000)['passed']
    assert not coverage(image_rect(200,200,0,50,50,100),200,200)['passed']
    assert coverage(image_rect(200,200,75,70,125,115),200,200)['passed']


def test_unprojection_uses_gl_row_direction_and_world_pose():
    eye={'width':2,'height':2,'position':[1,2,3], 'orientation_xyzw':[0,0,0,1],
         'fov_left_right_up_down':[-math.pi/4,math.pi/4,math.pi/4,-math.pi/4]}
    # near=1/far=10/depth=0 means one metre forward, lower-left pixel center.
    assert visible_center([1,0,0,0],[0,0,0,0],eye,1,10)==pytest.approx([.5,1.5,2])
    with pytest.raises(ValueError,match='no authored'):
        visible_center([0]*4,[0]*4,eye,1,10)
    with pytest.raises(ValueError,match='invalid depth'):
        visible_center([1,0,0,0],[1,0,0,0],eye,1,10)


def test_group_visibility_rejects_one_hidden_bundle_and_missing_metadata():
    from tools.vr_workflows.review_view import group_visibility
    objects=[{'id':i,'owner_tokens':['["cluster","'+('first' if i<=8 else 'second')+'"]']} for i in range(1,17)]
    assert group_visibility(list(range(1,17))*10,objects)['passed']
    assert not group_visibility(list(range(1,9))*20,objects)['passed']
    assert not group_visibility(list(range(1,17))*10,[])['passed']


def test_group_counts_do_not_inflate_duplicate_object_metadata():
    from tools.vr_workflows.review_view import group_visibility
    obj={'id':1,'owner_tokens':['["cluster","first"]']}
    result=group_visibility([1]*100,[obj]*12)
    assert result['groups']['first']=={'pixels':100,'primitives':1}
    assert not result['passed']


def test_measure_requires_colored_geometry_in_both_eyes_and_expected_groups(tmp_path):
    import array
    import json
    from PIL import Image
    from tools.vr_workflows.review_view import measure
    ids=array.array('I',(1+(i%8) if v else 0 for i,v in enumerate(image_rect(200,200,75,70,125,130))))
    (tmp_path/'evidence.json').write_text(json.dumps({'eyes':[
        {'eye':name,'width':200,'height':200} for name in ['left','right']]}))
    (tmp_path/'objects.json').write_text(json.dumps([
        {'id':i,'owner_tokens':['["cluster","bundle"]']} for i in range(1,9)]))
    for name in ['left','right']:
        (tmp_path/(name+'.ids.u32')).write_bytes(ids.tobytes())
        Image.new('RGB',(200,200)).save(tmp_path/(name+'.png'))
    assert not measure(tmp_path,1)['passed']  # IDs alone cannot prove visible colour.
    rgb=Image.new('RGB',(200,200))
    rgb.paste((255,200,80),(75,70,125,130))
    rgb.save(tmp_path/'left.png')
    assert not measure(tmp_path,1)['passed']  # Right eye still black.
    rgb.save(tmp_path/'right.png')
    assert measure(tmp_path,1)['passed']
    assert not measure(tmp_path,2)['passed']
