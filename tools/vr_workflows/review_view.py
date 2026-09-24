"""Post-action observation through ordinary grip gestures; no design mutation.

Native ID/depth capture supplies visible geometry, never editable review parts.
These deterministic presentation gestures are outside the measured authoring reach.
"""
import array
import json
import math
from collections import Counter
from urllib.parse import unquote
from pathlib import Path
from tools.vr_motion.metrics import rotate
from tools.vr_motion.model import multiply
from tools.vr_workflows.profile_input import zoom_scene


def coverage(ids, width, height):
    if len(ids) != width*height or min(width,height) <= 0:
        raise ValueError('invalid ID image dimensions')
    points = [i for i,v in enumerate(ids) if v]
    if not points:
        return {'passed':False,'pixels':0,'bounds':None,'major_fraction':0}
    x0,x1 = min(i%width for i in points),max(i%width for i in points)
    y0,y1 = min(i//width for i in points),max(i//width for i in points)
    spans = [(x1-x0+1)/width,(y1-y0+1)/height]
    margin = min(x0/width,(width-1-x1)/width,y0/height,(height-1-y1)/height)
    return {'passed':len(points)>=1000 and max(spans)>=.16 and min(spans)>=.06 and margin>=.03,
            'pixels':len(points),'bounds':[x0,y0,x1+1,y1+1],
            'major_fraction':max(spans),'minor_fraction':min(spans),'edge_margin_fraction':margin}


def visible_center(ids, depths, eye, near, far):
    """Unproject the rendered surfaces and center their visible 3D bounds."""
    width,height=eye['width'],eye['height']
    if len(ids)!=width*height or len(depths)!=len(ids):
        raise ValueError('capture dimensions differ')
    left,right,up,down=map(math.tan,eye['fov_left_right_up_down'])
    points=[]
    for i,identity in enumerate(ids):
        if not identity:continue
        d=depths[i]
        if not math.isfinite(d) or not 0<=d<1:
            raise ValueError('authored pixel has invalid depth')
        z=near*far/(far-d*(far-near))
        direction=[left+(right-left)*((i%width+.5)/width),
                   down+(up-down)*((i//width+.5)/height),-1]
        delta=rotate(eye['orientation_xyzw'],[z*v for v in direction])
        points.append([p+v for p,v in zip(eye['position'],delta)])
    if not points:raise ValueError('no authored pixels for review pivot')
    return [(min(p[i] for p in points)+max(p[i] for p in points))/2 for i in range(3)]


def group_visibility(ids, objects):
    counts=Counter(ids)
    groups={}
    for obj in objects:
        for encoded in obj['owner_tokens']:
            token=json.loads(unquote(encoded))
            if token[0]!='cluster':continue
            groups.setdefault(token[1],set()).add(obj['id'])
    groups={name:{'pixels':sum(counts[i] for i in identities),
                  'primitives':sum(counts[i]>0 for i in identities)}
            for name,identities in groups.items()}
    return {'passed':bool(groups) and all(g['pixels']>=64 and g['primitives']>=8 for g in groups.values()),
            'groups':groups}


def measure(directory, expected_groups=None):
    import numpy as np
    from PIL import Image
    directory=Path(directory)
    evidence=json.loads((directory/'evidence.json').read_text())
    objects=json.loads((directory/'objects.json').read_text())
    eyes={}
    for eye in evidence['eyes']:
        ids=array.array('I');ids.frombytes((directory/(eye['eye']+'.ids.u32')).read_bytes())
        result=coverage(ids,eye['width'],eye['height'])
        groups=group_visibility(ids,objects)
        mask=np.frombuffer(ids,dtype=np.uint32).reshape(eye['height'],eye['width'])!=0
        rgb=np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))[::-1]
        contrast=float(((rgb.max(axis=2)>=32)&mask).sum()/max(1,mask.sum()))
        result.update(group_visibility=groups,colored_fraction=contrast)
        result['passed'] &= groups['passed'] and contrast>=.9 and (expected_groups is None or len(groups['groups'])==expected_groups)
        eyes[eye['eye']]=result
    return {'passed':all(e['passed'] for e in eyes.values()),'eyes':eyes}


def improve_review(live, initial, output, expected_groups=None):
    initial,output=Path(initial),Path(output)
    output.mkdir(parents=True,exist_ok=False)
    before=measure(initial,expected_groups)
    report={'scope':'deterministic observation after authoring; canonical geometry unchanged',
            'criteria':{'minimum_pixels':1000,'major_fraction':.16,'minor_fraction':.06,'edge_margin_fraction':.03},
            'expected_groups':expected_groups,'before':before,'attempts':[]}
    sequence=live.state['config_sequence'];revision=live.state['scene_revision']
    if live.state['menu']!='closed' or live.state['extrude']['open']:
        raise ValueError('close menus/tablet before scene observation')
    evidence=json.loads((initial/'evidence.json').read_text())
    eye=evidence['eyes'][0]
    ids=array.array('I');ids.frombytes((initial/(eye['eye']+'.ids.u32')).read_bytes())
    depths=array.array('f');depths.frombytes((initial/(eye['eye']+'.depth.f32')).read_bytes())
    pivot=visible_center(ids,depths,eye,evidence['depth_near_m'],evidence['depth_far_m'])
    q=eye['orientation_xyzw']
    target=[p+v for p,v in zip(eye['position'],rotate(q,[0,0,-1.0]))]
    yaw=math.radians(45)/2;pitch=math.radians(-30)/2
    turn=multiply([0,math.sin(yaw),0,math.cos(yaw)],[math.sin(pitch),0,0,math.cos(pitch)])
    try:
        live.send('pose',hand=1,position=pivot,orientation=q);live.frame()
        live.send('button',hand=1,button='grip',pressed=True);live.frame()
        live.send('pose',hand=1,position=target,orientation=multiply(q,turn));live.frame()
    finally:
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
    live.capture_to(output/'oriented',discard_source=True)
    current=measure(output/'oriented',expected_groups)
    report['orientation']={'pivot':pivot,'target':target,'yaw_deg':45,'pitch_deg':-30}
    report['attempts'].append({'capture':'oriented','metrics':current})
    for attempt in range(2):
        if current['passed']:break
        span=min(e['major_fraction'] for e in current['eyes'].values())
        if span<=0:break
        factor=min(2.5,max(.5,.22/span))
        # zoom_scene offsets its hand midpoint by -0.25 world-Y.
        zoom_scene(live,[target[0],target[1]+.25,target[2]],factor)
        name=f'scaled-{attempt+1}'
        live.capture_to(output/name,discard_source=True)
        current=measure(output/name,expected_groups)
        report['attempts'].append({'capture':name,'scale_factor':factor,'metrics':current})
    report['passed']=current['passed']
    report['config_unchanged']=live.state['config_sequence']==sequence
    report['scene_revision_unchanged']=live.state['scene_revision']==revision
    (output/'review-view.json').write_text(json.dumps(report,indent=2)+'\n')
    if not all(report[k] for k in ['passed','config_unchanged','scene_revision_unchanged']):
        raise RuntimeError('Review view remains inadequate or observation changed design state')
    return report
