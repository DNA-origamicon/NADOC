"""Keep a deformation model beside its persistent panel through normal scene grips."""
import json
from copy import deepcopy
from pathlib import Path
import numpy as np
from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project


def check(evidence):
    state = evidence['state']
    deformation = state['twist'] if state.get('twist',{}).get('active') else state['bend']
    points = [p['world'] for p in deformation['targets']]
    if deformation['ready'] or deformation.get('grabbing'):
        points += deformation['handles'] + deformation['endpoints']
    panel = state['sidebars'][1]['grip_targets']
    # Edge midpoints define the four actual panel corners.
    left, right, top, bottom = map(np.array, panel)
    half_up = (top-bottom)/2
    corners = [left-half_up,left+half_up,right-half_up,right+half_up]
    eyes = {}
    for eye in evidence['eyes']:
        model = [project(p, eye) for p in points]
        menu = [project(p, eye) for p in corners]
        if not model or any(p is None for p in model+menu):
            eyes[eye['eye']] = {'passed': False}; continue
        lo, hi = np.min(model,axis=0), np.max(model,axis=0)
        ml, mh = np.min(menu,axis=0), np.max(menu,axis=0)
        clear = bool(hi[0]+12 < ml[0] or mh[0]+12 < lo[0] or hi[1]+12 < ml[1] or mh[1]+12 < lo[1])
        visible = bool(np.all(lo >= 0) and hi[0] < eye['width'] and hi[1] < eye['height'])
        eyes[eye['eye']] = {'passed': clear and visible,'model_bounds':[lo.tolist(),hi.tolist()],
            'menu_bounds':[ml.tolist(),mh.tolist()]}
    return {'passed':state['sidebars'][1]['open'] and bool(eyes) and all(e['passed'] for e in eyes.values()),'eyes':eyes}


def translation_for_clear_view(evidence):
    """Find a small translation that passes the unchanged stereo layout oracle."""
    state=evidence['state']
    key='twist' if state.get('twist',{}).get('active') else 'bend'
    geometry=[p['world'] for p in state[key]['targets']]
    if state[key]['ready'] or state[key].get('grabbing'):geometry+=state[key]['handles']+state[key]['endpoints']
    if not geometry:raise RuntimeError('No deformation geometry is available for stereo framing')
    points=np.array(geometry)
    center=(points.min(axis=0)+points.max(axis=0))/2
    eye=evidence['eyes'][0]
    candidates=[]
    for distance in (1.15,1.5,1.9,2.3):
        for x in (-.35,-.55,-.75,-.95,.35,.55,.75,.95):
            for y in (0,-.3,.3):
                destination=np.array(eye['position'])+rotate(eye['orientation_xyzw'],[x,y,-distance])
                delta=destination-center
                projected=deepcopy(evidence)
                for data_key in ('bend','twist'):
                    data=projected['state'].get(data_key)
                    if not data: continue
                    for p in data.get('targets',[]):p['world']=(np.array(p['world'])+delta).tolist()
                    for field in ('handles','endpoints'):
                        if field in data:data[field]=[(np.array(p)+delta).tolist() for p in data[field]]
                if check(projected)['passed']:candidates.append(delta)
    if not candidates:raise RuntimeError('No translation leaves deformation targets visible beside the panel')
    return min(candidates,key=lambda delta:float(np.linalg.norm(delta)))


def place(live, evidence, output):
    delta=translation_for_clear_view(evidence)
    hand = np.array(live.state['head_position'])+[0,-1,0]
    # A parked left pointer must not retain menu ownership while the right grips.
    live.send('pose',hand=0,position=(hand+[-.15,0,0]).tolist(),orientation=[0,0,0,1])
    live.send('pose',hand=1,position=hand.tolist(),orientation=[0,0,0,1]);live.frame()
    live.send('button',hand=1,button='grip',pressed=True);live.frame()
    try:
        live.send('pose',hand=1,position=(hand+delta).tolist(),orientation=[0,0,0,1]);live.frame()
    finally:
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
    captured,_ = live.capture_to(Path(output)/'panel-clear',discard_source=True)
    result = check(captured)
    obscured = deepcopy(captured)
    obscured['state']['twist' if obscured['state'].get('twist', {}).get('active') else 'bend']['targets'] = [{'world':captured['state']['sidebars'][1]['position']}]
    result['overlap_negative_passed'] = not check(obscured)['passed']
    result['translation_m'] = delta.tolist()
    result['placement_policy'] = 'captured stereo bounds; ordinary model grip; no scale or head changes'
    (Path(output)/'panel-layout.json').write_text(json.dumps(result,indent=2))
    assert result['passed'] and result['overlap_negative_passed'],result
