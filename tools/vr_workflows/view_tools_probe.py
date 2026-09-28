"""Reach with the left hand to equip the desktop-icon view tablet, then click it."""
import json
import os
import sys
import time
from pathlib import Path
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import rotate
from tools.vr_motion.model import multiply
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.demo_view import reveal


def run(socket, output, action):
    out=Path(output);out.mkdir(parents=True,exist_ok=True)
    bridge=Bridge(socket)
    deadline=time.monotonic()+30
    readiness=[]
    while True:
        try:
            observed=bridge.call('scrywrite_observe',{})
            readiness.append({'focused':bool(observed.get('focused'))})
            if observed.get('focused'):break
        except OSError as error:
            # Socket creation precedes the first responsive OpenXR frame.
            readiness.append({'startup_transport':type(error).__name__})
        (out/'startup.json').write_text(json.dumps(readiness,indent=2))
        if time.monotonic()>deadline:raise RuntimeError('Viewer did not focus')
        time.sleep(.1)
    (out/'startup.json').write_text(json.dumps(readiness,indent=2))
    live=LiveSession(bridge,physical=True,allow_transactions=True)
    trials=[];preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
    def wait(predicate):
        deadline=time.monotonic()+60
        while not predicate(live.state):
            if time.monotonic()>deadline:raise RuntimeError('View tools timed out')
            live.frame();time.sleep(.05)
    def reach(p,q,hand=0,acquired=None):
        trial=reach_target(live,p,preset,17000+len(trials),target_position=p,target_orientation=q,hand=hand,acquired=acquired)
        trials.append(trial);(out/'reaches.json').write_text(json.dumps(trials,indent=2))
        if acquired is not None:assert acquired(live.state),'Panel target not acquired'
    def dwell(seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:live.frame();time.sleep(.02)
    try:
        reveal(live)
        wait(lambda s:s.get('view_tools',{}).get('version',0)>0)
        if action in ('equip','stow'):
            for h in (0,1):
                if live.state['sidebars'][h]['open']:live.button('menu',hand=h);live.frame()
            evidence,_=live.capture_to(out/'before',discard_source=True)
            head=np.mean([e['position'] for e in evidence['eyes']],axis=0)
            q=evidence['eyes'][0]['orientation_xyzw']
            if action=='equip':
                wait(lambda s:len(s['ligation']['bonds'])>5)
                center=np.mean([b[k] for b in live.state['ligation']['bonds'] for k in ('a','b')],axis=0)
                target=head+rotate(q,[.23,-.05,-.85])
                turn=multiply(q,[0,np.sin(np.pi/4),0,np.cos(np.pi/4)])
                live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
                live.send('button',hand=1,button='grip',pressed=True);live.frame()
                live.send('pose',hand=1,position=target.tolist(),orientation=turn);live.frame()
                live.send('button',hand=1,button='grip',pressed=False);live.frame()
            forward=rotate(q,[0,0,-1]);forward[1]=0;forward/=np.linalg.norm(forward)
            right=np.cross(forward,[0,1,0])
            front=head-right*.28+forward*.4+[0,-.1,0]
            behind=head-right*.28-forward*.28+[0,.08,0]
            nick=live.state['ligation']['nick_active']
            reach(front.tolist(),q);dwell(.25)
            assert live.state['ligation']['quiver']['armed'][0]
            seq=live.state['ligation']['quiver']['sequence']
            reach(behind.tolist(),q);dwell(.6)
            assert live.state['ligation']['quiver']['sequence']==seq+1
            assert live.state['view_tools']['open']==(action=='equip')
            assert live.state['ligation']['nick_active']==nick,'Left gesture changed scissors'
            dwell(.6)
            assert live.state['ligation']['quiver']['sequence']==seq+1
            reach(front.tolist(),q)
        else:
            i=int(action);v=live.state['view_tools'];assert v['open']
            p=np.array(v['items'][i]['center'])
            evidence,_=live.capture_to(out/'before',discard_source=True)
            q=evidence['eyes'][0]['orientation_xyzw']
            reach((p+rotate(q,[0,0,.22])).tolist(),q,acquired=lambda s:s['view_tools']['hover'][0]==i)
            version=live.state['view_tools']['version']
            expected_sequence=live.state['view_tools']['sequence']+1
            live.button('trigger',hand=0);live.frame()
            wait(lambda s:s['view_tools']['ack_sequence']>=expected_sequence and not s['view_tools']['waiting'])
        live.capture_to(out/'after',discard_source=True)
        from tools.vr_workflows.view_tools_pixels import check
        if action!='stow':
            assert check(out/'after')['passed'], 'Tablet missing from stereo/mirror pixels'
            assert not check(out/'after',offscreen=True)['passed']
        else:
            assert not check(out/'after')['passed'], 'Stowed tablet is still visible'
        (out/'result.json').write_text(json.dumps(live.state,indent=2))
    except Exception:
        (out/'failure-state.json').write_text(json.dumps(live.state,indent=2));raise
    finally:
        live.send('button',hand=0,button='trigger',pressed=False);live.frame()

if __name__=='__main__':run(*sys.argv[1:])
