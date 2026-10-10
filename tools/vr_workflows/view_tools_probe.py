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
    from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
    prepare_audit_representation(live)
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
                wait(lambda s:s['ligation']['version']>0)
                bonds=bridge.request('observe targets')['ligation']['bonds']
                center=np.mean([b[k] for b in bonds for k in ('a','b')],axis=0)
                # Leave the tablet's left foreground clear even when overlay labels extend the model.
                target=head+rotate(q,[.65,-.05,-1.8])
                turn=multiply(q,[0,np.sin(np.pi/4),0,np.cos(np.pi/4)])
                live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
                live.send('button',hand=1,button='grip',pressed=True);live.frame()
                live.send('pose',hand=1,position=target.tolist(),orientation=turn);live.frame()
                live.send('button',hand=1,button='grip',pressed=False);live.frame()
            forward=rotate(q,[0,0,-1]);forward[1]=0;forward/=np.linalg.norm(forward)
            right=np.cross(forward,[0,1,0])
            holster=multiply(q,[np.sin(3*np.pi/8),0,0,np.cos(3*np.pi/8)])
            front=head-right*.28+forward*.4+[0,-.1,0]
            behind=head-right*.28-forward*.28+[0,.08,0]
            nick=live.state['ligation']['nick_active']
            reach(front.tolist(),q);dwell(.25)
            assert live.state['ligation']['quiver']['armed'][0]
            seq=live.state['ligation']['quiver']['sequence']
            reach(behind.tolist(),holster)
            assert live.state['ligation']['quiver']['sequence']==seq+1
            assert live.state['view_tools']['open']==(action=='equip')
            assert live.state['view_tools']['following']==(action=='equip')
            assert live.state['ligation']['nick_active']==nick,'Left gesture changed scissors'
            dwell(.6)
            assert live.state['ligation']['quiver']['sequence']==seq+1
            reach(front.tolist(),q)
            assert live.state['view_tools']['following']==(action=='equip'), 'Tablet attachment changed after returning in front'
            if action=='equip':
                # The tablet still follows the left hand. Explicitly place
                # its actual border only to frame the subsequent tile checks.
                from scipy.spatial.transform import Rotation
                live.capture_to(out/'quiver-open-before-framing',discard_source=True)
                centers=np.array([item['center'] for item in live.state['view_tools']['items']])
                across=centers[1]-centers[0];down=centers[2]-centers[0]
                width=np.linalg.norm(across)/(376/768)
                right_axis=across/np.linalg.norm(across);up_axis=-down/np.linalg.norm(down)
                normal=np.cross(right_axis,up_axis)
                panel_q=Rotation.from_matrix(np.column_stack((right_axis,up_axis,normal))).as_quat().tolist()
                # The mean tile center is 104/768 above the content center.
                center=centers.mean(axis=0)-up_axis*width*(104/768)
                dock=center+right_axis*width*(184/768-.5)+up_axis*width*(.5-652/768)
                reach((dock+normal*.22).tolist(),panel_q,hand=1)
                live.button('trigger',hand=1);live.frame()
                assert not live.state['view_tools']['following'], 'Dock button did not freeze tablet'
                border=center+right_axis*width*.565
                reach((border+rotate(panel_q,[0,0,.12])).tolist(),panel_q,hand=1)
                live.send('button',hand=1,button='grip',pressed=True);live.frame()
                destination=head+rotate(q,[-.25,.08,-.60])
                try:
                    reach((destination+rotate(q,[width*.565,0,.12])).tolist(),q,hand=1)
                finally:
                    live.send('button',hand=1,button='grip',pressed=False);live.frame()
                (out/'tablet-framing.json').write_text(json.dumps({'initial_center':center.tolist(),
                    'destination':destination.tolist(),'policy':'ordinary border grip; orientation derived from live tile positions'},indent=2))
        elif action=='controls':
            from scipy.spatial.transform import Rotation
            def geometry():
                centers=np.array([item['center'] for item in live.state['view_tools']['items']])
                across=centers[1]-centers[0];down=centers[2]-centers[0]
                width=np.linalg.norm(across)/(376/768)
                right=across/np.linalg.norm(across);up=-down/np.linalg.norm(down);normal=np.cross(right,up)
                q=Rotation.from_matrix(np.column_stack((right,up,normal))).as_quat().tolist()
                center=centers.mean(axis=0)-up*width*(104/768)
                return center,right,up,normal,width,q
            evidence,_=live.capture_to(out/'controls-before',discard_source=True)
            head=np.mean([e['position'] for e in evidence['eyes']],axis=0)
            eyeq=evidence['eyes'][0]['orientation_xyzw']
            forward=rotate(eyeq,[0,0,-1]);forward[1]=0;forward/=np.linalg.norm(forward)
            side=np.cross(forward,[0,1,0]);holster=multiply(eyeq,[np.sin(3*np.pi/8),0,0,np.cos(3*np.pi/8)])
            def shoulder(hand):
                sign=1 if hand else -1
                reach((head+side*.28*sign+forward*.4+[0,-.1,0]).tolist(),eyeq,hand=hand)
                reach((head+side*.28*sign-forward*.28+[0,.08,0]).tolist(),holster,hand=hand)
            def button_at(x,y):
                center,right,up,normal,width,q=geometry()
                point=center+right*width*(x/768-.5)+up*width*(.5-y/768)
                reach((point+normal*.22).tolist(),q,hand=1,acquired=(lambda s:s['view_tools']['close_hover'][1]) if x==682 else None)
                live.capture_to(out/f'pointer-{len(trials)}-{x}-{y}',discard_source=True)
                live.button('trigger',hand=1);live.frame()
            for hand,button in [(1,'trigger'),(0,'grip')]:
                assert live.state['view_tools']['open'] and not live.state['view_tools']['following']
                center,right,up,normal,width,q=geometry()
                border=center+right*width*.565
                reach((border+normal*(.3 if button=='trigger' else .12)).tolist(),q,hand=hand)
                live.send('button',hand=hand,button=button,pressed=True);live.frame()
                try:shoulder(hand)
                finally:live.send('button',hand=hand,button=button,pressed=False);live.frame()
                assert not live.state['view_tools']['open'], f'{button} shoulder dismissal failed'
                live.capture_to(out/f'dismissed-{button}',discard_source=True)
                shoulder(0)
                reach((head-side*.28+forward*.4+[0,-.1,0]).tolist(),eyeq,hand=0)
                assert live.state['view_tools']['following']
                button_at(184,652)
                assert not live.state['view_tools']['following']
            button_at(682,30)
            assert not live.state['view_tools']['open'], 'Close button failed'
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
        if action not in ('stow','controls'):
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
