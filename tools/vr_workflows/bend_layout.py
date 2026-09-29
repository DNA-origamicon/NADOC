"""Keep a deformation model beside its persistent panel through normal scene grips."""
import json
from copy import deepcopy
from pathlib import Path
import numpy as np
from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project


def check(evidence):
    state = evidence['state']
    deformation = state.get('twist', state.get('bend'))
    points = [p['world'] for p in deformation['targets']]
    if deformation['ready']:
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


def place(live, evidence, output):
    deformation = live.state.get('twist', live.state.get('bend'))
    points = np.array([p['world'] for p in deformation['targets']])
    center = (points.min(axis=0)+points.max(axis=0))/2
    eye = evidence['eyes'][0]
    destination = np.array(eye['position'])+rotate(eye['orientation_xyzw'],[-.55,0,-1.15])
    hand = np.array(live.state['head_position'])+[0,-1,0]
    live.send('pose',hand=1,position=hand.tolist(),orientation=[0,0,0,1]);live.frame()
    live.send('button',hand=1,button='grip',pressed=True);live.frame()
    try:
        live.send('pose',hand=1,position=(hand+destination-center).tolist(),orientation=[0,0,0,1]);live.frame()
    finally:
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
    captured,_ = live.capture_to(Path(output)/'panel-clear',discard_source=True)
    result = check(captured)
    obscured = deepcopy(captured)
    obscured['state']['twist' if obscured['state'].get('twist', {}).get('active') else 'bend']['targets'] = [{'world':captured['state']['sidebars'][1]['position']}]
    result['overlap_negative_passed'] = not check(obscured)['passed']
    result['translation_m'] = (destination-center).tolist()
    (Path(output)/'panel-layout.json').write_text(json.dumps(result,indent=2))
    assert result['passed'] and result['overlap_negative_passed'],result
