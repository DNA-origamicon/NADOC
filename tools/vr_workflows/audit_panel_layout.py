"""Separate a panel from captured molecular pixels using an ordinary border grip."""
import json
from pathlib import Path
import numpy as np
from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project
from tools.vr_workflows.menu_grip_check import acquire, move


def clear_panel(live, directory, evidence, preset):
    directory=Path(directory)
    panel=evidence['state']['sidebars'][1]
    left,right,top,bottom=map(np.array,panel['grip_targets'])
    half=(top-bottom)/2
    corners=[left-half,left+half,right-half,right+half]
    bounds=[]
    for eye in evidence['eyes']:
        ids=np.fromfile(directory/(eye['eye']+'.ids.u32'),dtype=np.uint32).reshape(eye['height'],eye['width'])
        y,x=np.nonzero(ids)
        if not len(x):raise RuntimeError('No molecular pixels for panel placement')
        bounds.append((np.array([x.min(),y.min()]),np.array([x.max(),y.max()])))
    eye=evidence['eyes'][0]
    choices=[]
    for dx in (0,-.2,.2,-.4,.4,-.6,.6):
        for dy in (0,.2,.4,-.2,-.4):
            delta=np.array(rotate(eye['orientation_xyzw'],[dx,dy,0]))
            if not np.linalg.norm(delta):continue
            valid=True
            for target_eye,(ml,mh) in zip(evidence['eyes'],bounds):
                projected=[project((p+delta).tolist(),target_eye) for p in corners]
                if any(p is None for p in projected):valid=False;break
                lo,hi=np.min(projected,axis=0),np.max(projected,axis=0)
                clear=hi[0]+16<ml[0] or mh[0]+16<lo[0] or hi[1]+16<ml[1] or mh[1]+16<lo[1]
                if not (clear and np.all(lo>8) and hi[0]<target_eye['width']-8 and hi[1]<target_eye['height']-8):valid=False;break
            if valid:choices.append(delta)
    if not choices:raise RuntimeError('No visible panel translation clears the captured model')
    delta=min(choices,key=np.linalg.norm)
    trials=[]
    acquire(live,1,1,0,preset,trials)
    start=np.array(live.state['hands'][1]['position'])
    live.send('button',hand=1,button='grip',pressed=True);live.frame()
    try:
        assert live.state['sidebars'][1]['grip_state']=='moving'
        move(live,{1:(start+delta).tolist()},preset,trials)
    finally:
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
    for hand in (0,1):live.send('pose',hand=hand,position=(np.array(live.state['head_position'])+[0,-1,0]).tolist(),orientation=[0,0,0,1])
    live.frame()
    target=directory.with_name(directory.name+'-clear')
    captured,_=live.capture_to(target,discard_source=True)
    (target/'placement.json').write_text(json.dumps({'policy':'stereo molecular bounds; normal border grip; unchanged head/model/scale/pixel oracle','delta_m':delta.tolist(),'trials':trials},indent=2))
    return target,captured
