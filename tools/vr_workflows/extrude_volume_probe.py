"""Create/resize an actual volume around the newly authored model and capture styles."""
import sys
import json
import time
from pathlib import Path
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.extrude_sidebar import SidebarControls
from tools.vr_workflows.demo_view import hold,reveal
import os

socket,output,mode=sys.argv[1:4]
out=Path(output);out.mkdir(parents=True,exist_ok=True)
live=LiveSession(Bridge(socket),physical=True,allow_transactions=True)
from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
prepare_audit_representation(live)
controls=SidebarControls(live,out,os.environ.get('NADOC_VR_PROFILE','steady_fast'))
def wait(predicate):
    deadline=time.monotonic()+15
    while not predicate(live.state):
        if time.monotonic()>deadline: raise RuntimeError('Timed out: '+str(live.state))
        live.frame();time.sleep(.1)
def entry():return live.state['view_volumes']['entries'][0]
def park():
    # Observation setup: keep controllers away from design pixels in both captures.
    p=np.array(live.state['head_position'])+[0,-1.0,0]
    for h in (0,1):live.send('pose',hand=h,position=p.tolist(),orientation=live.state['hands'][h]['orientation_xyzw'])
    live.frame()

try:
    reveal(live)
    if mode=='create':
        import array
        from tools.vr_workflows.review_view import visible_center
        evidence,_=live.capture_to(out/'model-before-volume',discard_source=True)
        eye=evidence['eyes'][0]
        ids=array.array('I');ids.frombytes((out/'model-before-volume'/f"{eye['eye']}.ids.u32").read_bytes())
        depth=array.array('f');depth.frombytes((out/'model-before-volume'/f"{eye['eye']}.depth.f32").read_bytes())
        model_center=visible_center(ids,depth,eye,evidence['depth_near_m'],evidence['depth_far_m'])
        if not live.state['sidebars'][1]['open']:live.button('menu',hand=1);live.frame()
        controls.click('tab:visualization')
        controls.click('section:visualization:template:view-volumes')
        controls.click('volume:new:box')
        wait(lambda s:len(s['view_volumes']['entries'])==1 and not s['view_volumes']['pending'])
        # Position and size through trigger grabs. Keep a finite section of the
        # new model inside the volume and the entire box visible for review.
        from tools.vr_workflows.menu_grip_check import move
        trials=[];preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
        center=entry()['world_center']
        move(live,{0:center},preset,trials)
        live.send('button',hand=0,button='trigger',pressed=True);live.frame()
        wait(lambda s:s['view_volumes']['hand']==0)
        move(live,{0:model_center},preset,trials)
        for face_index,fraction in [(1,.35),(2,.35),(5,.3)]:
            center=np.array(entry()['world_center'])
            face=np.array(entry()['faces'][face_index]['world_center'])
            move(live,{1:face.tolist()},preset,trials)
            live.send('button',hand=1,button='trigger',pressed=True);live.frame()
            wait(lambda s:s['view_volumes']['resize_face']==face_index)
            target=center+fraction*(face-center)
            move(live,{1:target.tolist()},preset,trials)
            live.send('button',hand=1,button='trigger',pressed=False);live.frame()
        live.send('button',hand=0,button='trigger',pressed=False);live.frame()
        wait(lambda s:not s['view_volumes']['pending'])
        controls.click('volume:toggle')
        live.button('menu',hand=1);live.frame()
        (out/'resize.json').write_text(json.dumps(trials,indent=2))
        live.capture_to(out/'subsection',discard_source=True)
    else:
        wait(lambda s:s['view_volumes']['entries'][0].get('representation')=='beads')
        park()
        live.capture_to(out/'enabled',discard_source=True);hold(live,'beads inside the view volume')
        live.button('menu',hand=1);live.frame()
        controls.click('section:visualization:template:view-volumes')
        identifier=entry()['id'];controls.click('volume:enabled:'+identifier)
        wait(lambda s:not s['view_volumes']['pending'] and not s['view_volumes']['entries'][0]['enabled'])
        controls.click('volume:toggle');live.button('menu',hand=1);live.frame()
        park()
        live.capture_to(out/'disabled',discard_source=True);hold(live,'original representation with volume disabled')
        from tools.vr_workflows.volume_pixels import compare
        checks=compare(out/'enabled',out/'disabled',entry())
        (out/'comparison.json').write_text(json.dumps(checks,indent=2))
        assert checks['passed'],checks
        live.button('menu',hand=1);live.frame();controls.click('section:visualization:template:view-volumes')
        controls.click('volume:enabled:'+identifier)
        wait(lambda s:not s['view_volumes']['pending'] and s['view_volumes']['entries'][0]['enabled'])
        controls.click('volume:toggle');live.button('menu',hand=1);live.frame()
    (out/'state.json').write_text(json.dumps(live.state,indent=2))
finally:
    (out/'last-state.json').write_text(json.dumps(live.state,indent=2))
    live.release()
