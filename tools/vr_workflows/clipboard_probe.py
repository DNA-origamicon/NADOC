"""Copy and Paste via real thumb input, with hand tracking and stereo pixels."""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
from PIL import Image
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import rotate
from tools.vr_motion.model import multiply
from .profile_input import reach_target, zoom_scene
from .edit_wheel_check import slide
from .selection_wheel_check import capture

def preview_pixels(rgb, eye, center, *, placed=False):
    q=eye["orientation_xyzw"]
    local=rotate([-q[0],-q[1],-q[2],q[3]],np.array(center)-eye["position"])
    if local[2]>=-.001: return 0
    left,right,up,down=np.tan(eye["fov_left_right_up_down"])
    x=int((local[0]/-local[2]-left)/(right-left)*eye["width"])
    y=int((up-local[1]/-local[2])/(up-down)*eye["height"])
    if not 0<=x<eye["width"] or not 0<=y<eye["height"]: return 0
    crop=rgb[max(0,y-120):y+121,max(0,x-120):x+121]
    if placed:
        return int(((crop[:,:,0]>crop[:,:,1].astype(float)*1.1)&(crop[:,:,1]>crop[:,:,2].astype(float)*1.35)&(crop[:,:,0]>90)).sum())
    return int(((crop[:,:,0]<150)&(crop[:,:,1]>180)&(crop[:,:,2]>130)&(crop[:,:,2]<230)).sum())



def run(socket, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic()+30
    readiness = []
    while True:
        try:
            observed = bridge.call('scrywrite_observe', {})
            readiness.append({'focused': bool(observed.get('focused'))})
            if observed.get('focused'): break
        except OSError as error:
            readiness.append({'startup_transport': type(error).__name__})
        if time.monotonic()>deadline: raise RuntimeError('Viewer did not focus')
        time.sleep(.1)
    (output/'startup.json').write_text(json.dumps(readiness,indent=2))
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    preset = os.environ.get('NADOC_VR_PROFILE', 'steady_fast')
    trials = []
    def wait(predicate):
        deadline = time.monotonic()+40
        while True:
            live.frame()
            if predicate(): return
            if time.monotonic() > deadline: raise TimeoutError(live.state.get('ligation'))
            time.sleep(.05)
    def wheel(index):
        live.send('trackpad_axis',hand=1,x=0,y=0);live.frame()
        live.send('button',hand=1,button='trackpad',pressed=True);live.frame()
        slide(live,index,preset,trials)
        capture(live,output,'wheel-'+str(index),index,key='radial_edit')
        live.send('button',hand=1,button='trackpad',pressed=False);live.frame()
        wait(lambda: not live.state['ligation']['waiting'])
    def snapshot(name):
        evidence,_=live.capture_to(output/name,discard_source=True)
        counts={}
        for eye in ('left','right'):
            rgb=np.asarray(Image.open(output/name/(eye+'.png')).convert('RGB'))
            pose=next(e for e in evidence['eyes'] if e['eye']==eye)
            center=evidence['state']['clipboard']['center']
            counts[eye]=preview_pixels(rgb,pose,center)
            assert preview_pixels(np.zeros_like(rgb),pose,center)==0
            assert preview_pixels(rgb,pose,[1000,1000,1000])==0
        # Complete capture/readback work before starting another timed thumb reach.
        until=time.monotonic()+.5
        while time.monotonic()<until:
            live.frame();time.sleep(.02)
        return evidence,counts
    try:
        wait(lambda: live.state['ligation']['version'] > 0)
        for hand in (0,1):
            if live.state['sidebars'][hand]['open']: live.button('menu',hand=hand)
        evidence,_=live.capture_to(output/'anchor',files=['evidence.json'],discard_source=True)
        eye=evidence['eyes'][0];q=eye['orientation_xyzw'];head=eye['position']
        # Observation-only ordinary bimanual zoom makes the full-size ghost fit near the hand.
        zoom_scene(live,head,.2)
        (output/'observation.json').write_text(json.dumps({'scene_scale_factor':.2,'method':'ordinary bimanual grip','reason':'fit complete preview in stereo view'}))
        target=np.array(head)+rotate(q,[.08,-.06,-.65])
        trials.append(reach_target(live,target.tolist(),preset,920,target_position=target.tolist(),target_orientation=q,hand=1))
        live.send('pose',hand=0,position=(np.array(head)+[-.5,-.7,0]).tolist(),orientation=q);live.frame()
        before=live.state['scene_revision']
        wheel(4)
        assert live.state['clipboard']['active'], live.state['ligation']
        assert live.state['scene_revision']==before
        first,pixels=snapshot('preview-start')
        assert all(n>8 for n in pixels.values()),pixels
        start=np.array(live.state['clipboard']['center'])
        old_hand=np.array(live.state['hands'][1]['position'])
        target=old_hand+rotate(q,[.18,.08,0])
        turn=multiply(q,[0,np.sin(np.pi/6),0,np.cos(np.pi/6)])
        trials.append(reach_target(live,target.tolist(),preset,921,target_position=target.tolist(),target_orientation=turn,hand=1))
        new_hand=np.array(live.state['hands'][1]['position'])
        end=np.array(live.state['clipboard']['center'])
        assert np.linalg.norm(end-start)>.05
        expected=new_hand+rotate(live.state['hands'][1]['orientation_xyzw'],[0,0,-.12])
        np.testing.assert_allclose(end,expected,atol=.005)
        moved,moved_pixels=snapshot('preview-moved')
        assert all(n>8 for n in moved_pixels.values()),moved_pixels
        wheel(5)
        wait(lambda: live.state['scene_revision']>before and not live.state['clipboard']['active'])
        final,_=snapshot('pasted')
        if os.environ.get('NADOC_VR_CLIPBOARD_CASE') == 'rigid':
            placed_counts = {}
            for eye in ('left','right'):
                pose = next(e for e in final['eyes'] if e['eye']==eye)
                center = final['state']['clipboard']['center']
                before_rgb = np.asarray(Image.open(output/'preview-moved'/(eye+'.png')).convert('RGB'))
                after_rgb = np.asarray(Image.open(output/'pasted'/(eye+'.png')).convert('RGB'))
                old = preview_pixels(before_rgb,pose,center,placed=True)
                new = preview_pixels(after_rgb,pose,center,placed=True)
                placed_counts[eye] = {'before':old,'after':new}
                assert new > old+8, placed_counts
            (output/'placed-pixels.json').write_text(json.dumps(placed_counts,indent=2))
        (output/'result.json').write_text(json.dumps({'passed':True,'preset':preset,'preview_pixels':pixels,'moved_pixels':moved_pixels,'trials':trials,'clipboard':final['state']['clipboard']},indent=2))
    finally:
        live.release()
        (output/'trials.json').write_text(json.dumps(trials,indent=2))

if __name__ == '__main__': run(*sys.argv[1:])
