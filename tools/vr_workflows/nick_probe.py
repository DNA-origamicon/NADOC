"""Physical wheel Nick / Undo / Redo, including analog squeeze and visible glow."""
import json
from tools.vr_workflows.audit_intervals import operation
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
from tools.vr_workflows.demo_view import reveal, hold
from tools.vr_workflows.nick_pixels import check


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
            if time.monotonic()>deadline:raise RuntimeError('Wheel edit timed out')
            try:live.frame()
            except TimeoutError:continue
            time.sleep(.05)
    def reach(p,q=None,acquired=None):
        for attempt in range(3 if acquired else 1):
            trial=reach_target(live,p,preset,9600+len(trials),target_position=p,target_orientation=q or [0,0,0,1],acquired=acquired)
            trial['attempt']=attempt+1;trials.append(trial)
            (out/'reaches.json').write_text(json.dumps(trials,indent=2))
            if acquired is None or acquired(live.state):return
        raise RuntimeError('Target not acquired in three profile reaches')
    try:
        reveal(live)
        for h in (0,1):
            if live.state['sidebars'][h]['open']:live.button('menu',hand=h);live.frame()
        wait(lambda s:s.get('ligation',{}).get('version',0)>0)
        initial_bonds = bridge.request('observe targets')['ligation']['bonds']
        assert len(initial_bonds)>5
        evidence,_=live.capture_to(out/'before',discard_source=True);eye=evidence['eyes'][0]
        if action=='nick':
            points=[b[k] for b in initial_bonds for k in ('a','b')]
            center=np.mean(points,axis=0)
            # Fit the actual bundle, preserving enough apparent bond width for
            # the downsampled mirror. A fixed 1.5 m placement made the nearly
            # closed glow vanish there despite passing both full eye images.
            radius=max(np.linalg.norm(np.asarray(point)-center) for point in points)
            distance=max(.9,1.5*radius) if os.environ.get('NADOC_VR_AUDIT_DESIGN') else .7
            (out/'model-framing.json').write_text(json.dumps({'radius':radius,'distance':distance,
                'reason':'ordinary model grip; size-derived stereo framing and mirror legibility'},indent=2))
            target=np.array(eye['position'])+rotate(eye['orientation_xyzw'],[0,0,-distance])
            turn=multiply(eye['orientation_xyzw'],[0,np.sin(np.pi/4),0,np.cos(np.pi/4)])
            live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
            live.send('button',hand=1,button='grip',pressed=True);live.frame()
            live.send('pose',hand=1,position=target.tolist(),orientation=turn);live.frame()
            live.send('button',hand=1,button='grip',pressed=False);live.frame()
        revision=live.state['scene_revision'];version=live.state['ligation']['version']
        q=eye['orientation_xyzw'];center=np.array(eye['position'])+rotate(q,[0,-.1,-.55])
        reach((center+rotate(q,[0,0,.12])).tolist(),q)
        live.send('trackpad_axis', hand=1, x=0, y=0);live.frame()
        live.send('button',hand=1,button='trackpad',pressed=True);live.frame()
        index={'nick':1,'undo':2,'redo':3}[action]
        item=live.state['radial_edit']['items'][index]
        assert item['enabled']
        from .edit_wheel_check import slide
        slide(live,index,preset,trials)
        live.capture_to(out/'wheel',discard_source=True)
        if os.environ.get('NADOC_VR_FRAME_AUDIT'):
            # Readback/compositor samples can spill into the next few frames.
            # Keep this diagnostic hold outside the timed release/commit.
            until=time.monotonic()+.35
            while time.monotonic()<until:live.frame();time.sleep(.01)
        history_panels = [(panel['open'], panel['tab']) for panel in live.state['sidebars']]
        haptics_before = live.state['haptic_requests'][1]
        live.send('button',hand=1,button='trackpad',pressed=False);live.frame()
        if action in ('undo', 'redo'):
            assert live.state['haptic_requests'][1] > haptics_before, 'History command omitted controller feedback'
            assert live.state['haptic_amplitude'][1] > 0
            assert live.state['radial_edit']['pending'] == index, 'History command omitted its pending indicator'
            assert live.state['menu'] == 'closed', 'History command opened a menu'
            assert history_panels == [(panel['open'], panel['tab']) for panel in live.state['sidebars']]
            if not os.environ.get('NADOC_VR_FRAME_AUDIT'):
                live.capture_to(out/'history-feedback',discard_source=True)
        if action=='nick':
            assert live.state['ligation']['nick_active']
            # Quiver toggles only after a deliberate front-to-behind reach.
            head=np.mean([e['position'] for e in evidence['eyes']],axis=0)
            forward=rotate(q,[0,0,-1]);forward[1]=0;forward=forward/np.linalg.norm(forward)
            right=np.cross(forward,[0,1,0])
            holster=multiply(q,[np.sin(3*np.pi/8),0,0,np.cos(3*np.pi/8)])
            front=head+right*.28+forward*.4+[0,-.1,0]
            behind=head+right*.28-forward*.28+[0,.08,0]
            def dwell(seconds,hand=1):
                until=time.monotonic()+seconds
                while time.monotonic()<until:
                    pose=live.state['hands'][hand]
                    live.send('pose',hand=hand,position=pose['position'],orientation=pose['orientation_xyzw'])
                    live.frame();time.sleep(.02)
            # The frame audit measures the edit; the ordinary tour retains the
            # independent quiver/tablet demonstration and its pixel checks.
            if not os.environ.get('NADOC_VR_FRAME_AUDIT'):
                for equipped,label in [(False,'quiver-stowed'),(True,'quiver-equipped')]:
                    reach(front.tolist(),q);dwell(.2)
                    assert live.state['ligation']['quiver']['armed'][1]
                    sequence=live.state['ligation']['quiver']['sequence']
                    reach(behind.tolist(),holster)
                    assert live.state['ligation']['quiver']['sequence']==sequence+1
                    assert live.state['ligation']['nick_active']==equipped
                    dwell(.7)
                    assert live.state['ligation']['quiver']['sequence']==sequence+1, 'Held-behind gesture repeated'
                    reach(front.tolist(),q)
                    assert live.state['scene_revision']==revision
                    live.capture_to(out/label,discard_source=True)
                    from tools.vr_workflows.quiver_pixels import check as quiver_pixels
                    checked=out/label
                    if not quiver_pixels(checked)['passed'] and os.environ.get('NADOC_VR_AUDIT_DESIGN'):
                        from tools.vr_workflows.audit_observation import clear_wrist
                        observation_position=clear_wrist(checked)
                        reach(observation_position,q)
                        checked=out/(label+'-clear')
                        live.capture_to(checked,discard_source=True)
                        (checked/'placement.json').write_text(json.dumps({'position':observation_position,'reason':'controller cleared from captured molecular pixels in both eyes; unchanged model, quiver gesture endpoints and pixel oracle'},indent=2))
                    assert quiver_pixels(checked)['passed'], 'Scissors did not visibly equip/stow'
                    assert not quiver_pixels(checked,offscreen=True)['passed']
                # The left quiver independently opens/stows the tablet while the
                # right scissors remain equipped throughout.
                left_front=head-right*.28+forward*.4+[0,-.1,0]
                left_behind=head-right*.28-forward*.28+[0,.08,0]
                for opened,label in [(True,'left-menu-open'),(False,'left-menu-closed')]:
                    for point,pause in [(left_front,.25),(left_behind,.6),(left_front,.05)]:
                        trial=reach_target(live,point.tolist(),preset,9800+len(trials),target_position=point.tolist(),target_orientation=holster if point is left_behind else q,hand=0)
                        trials.append(trial);dwell(pause,hand=0)
                    (out/'reaches.json').write_text(json.dumps(trials,indent=2))
                    assert live.state['view_tools']['open']==opened
                    assert live.state['ligation']['nick_active']
                    live.capture_to(out/label,discard_source=True)
                    from tools.vr_workflows.view_tools_pixels import check as tablet_pixels
                    assert tablet_pixels(out/label)['passed']==opened
                    assert not tablet_pixels(out/label,offscreen=True)['passed']
                    assert quiver_pixels(out/label)['passed']
            # Empty-space full click must not edit.
            reach((np.array(eye['position'])+rotate(q,[.4,0,-.5])).tolist(),q)
            live.button('trigger',hand=1);live.frame()
            assert live.state['scene_revision']==revision
            bonds=bridge.request('observe targets')['ligation']['bonds'];index=len(bonds)//4
            if os.environ.get('NADOC_VR_AUDIT_DESIGN'):
                from tools.vr_workflows.audit_observation import front_bond
                target_evidence,_=live.capture_to(out/'bond-target-setup',discard_source=True)
                bonds=bridge.request('observe targets')['ligation']['bonds']
                # A molecular pixel behind the frontmost blade is not an
                # occluder. Choose by depth/framing; the unchanged captured
                # scissors/glow oracle below establishes actual visibility.
                index=front_bond(target_evidence,bonds)
                (out/'bond-target-setup'/'target.json').write_text(json.dumps({
                    'original_index':len(bonds)//4,'index':index,'bond':bonds[index],
                    'reason':'nearest bond with stereo framing; depth-aware targeting, unchanged motion and captured scissors/glow pixel oracle'},indent=2))
            b=bonds[index];mid=(np.array(b['a'])+b['b'])/2
            left_trial=reach_target(live,mid.tolist(),preset,9699,target_position=(mid+rotate(q,[0,0,.12])).tolist(),target_orientation=q,hand=0)
            trials.append(left_trial);(out/'reaches.json').write_text(json.dumps(trials,indent=2))
            live.button('trigger',hand=0);live.frame()
            assert live.state['scene_revision']==revision and live.state['ligation']['nick_hover'][0] is None, 'Left hand cut a bond'
            # Move the sphere aside before the right scissors acquire the bond.
            reach_target(live,front.tolist(),preset,9700,target_position=(head+rotate(q,[-.3,-.1,-.4])).tolist(),target_orientation=q,hand=0)
            # Face the blade plane toward the observer on imported bundles.
            # A forward-pointing wrist presents the blades edge-on and extends
            # them behind the near-side bond into adjacent helices. Rotate the
            # ordinary controller pose about the same cutting center instead.
            cut_q=q
            if os.environ.get('NADOC_VR_AUDIT_DESIGN'):
                chord=np.asarray(b['b'])-b['a']
                theta=np.arctan2(np.dot(chord,rotate(q,[0,1,0])),np.dot(chord,rotate(q,[1,0,0])))
                roll=[0,0,np.sin(theta/2),np.cos(theta/2)]
                cut_q=multiply(multiply(q,roll),[np.sin(np.pi/4),0,0,np.cos(np.pi/4)])
            (out/'cut-observation.json').write_text(json.dumps({
                'cut_center':mid.tolist(),'orientation_xyzw':cut_q,
                'reason':'face scissors toward eyes and closed blades across projected bond, exposing glow beside them; same bond, native hit geometry and pixel thresholds'},indent=2))
            reach((mid+rotate(cut_q,[0,0,.12])).tolist(),cut_q,lambda s:s['ligation']['nick_hover'][1] is not None)
            target=live.state['ligation']['nick_hover'][1]
            for label,value in [('open',0),('half',.45),('almost',.8)]:
                live.send('trigger_value',hand=1,value=value);live.frame()
                assert live.state['ligation']['nick_hover'][1]==target
                assert live.state['scene_revision']==revision
                live.capture_to(out/label,discard_source=True)
                assert check(out/label)['passed'],f'{label}: scissors or bond glow missing'
                assert not check(out/label,offscreen=True)['passed']
            live.send('trigger_value',hand=1,value=1);live.frame()
        with operation(live,'nick-feedback'):
            wait(lambda s:s['scene_revision']>revision and s['ligation']['version']>version and not s['ligation']['waiting'])
        if action in ('undo', 'redo'):
            assert live.state['radial_edit']['pending'] is None, 'History pending indicator did not clear'
            assert live.state['menu'] == 'closed', 'History acknowledgement opened a menu'
            assert history_panels == [(panel['open'], panel['tab']) for panel in live.state['sidebars']]
        assert live.state['ligation']['status']=='created'
        # A held trigger across topology refresh must not cut another bond.
        settled=live.state['scene_revision']
        for _ in range(12):live.frame()
        assert live.state['scene_revision']==settled
        live.capture_to(out/'after',discard_source=True)
        hold(live,action+' complete')
        (out/'result.json').write_text(json.dumps(live.state,indent=2))
    except Exception:
        (out/'failure-state.json').write_text(json.dumps(live.state,indent=2));raise
    finally:
        for button in ('trigger','trackpad','grip'):live.send('button',hand=1,button=button,pressed=False)
        live.frame()

if __name__=='__main__':run(*sys.argv[1:])
