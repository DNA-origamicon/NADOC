"""Remote border gestures with tracked-head geometry and unmodified motion profiles."""
import json
import math
import numpy as np
from tools.vr_motion.metrics import rotate, target_metrics
from .profile_input import reach_target
from .menu_grip_check import capture


def run(live, catalog, output, preset):
    del catalog
    trials=[]
    evidence,_=live.capture_to(output/'anchor',files=['evidence.json'],discard_source=True)
    eye=evidence['eyes'][0]
    head=np.mean([e['position'] for e in evidence['eyes']],axis=0)
    scene=live.state['presentation']['model_to_tracking_rows']
    def trigger(hand,pressed):
        live.send('button',hand=hand,button='trigger',pressed=pressed);live.frame()
    for panel in (0,1):
        print(preset, "remote panel",panel,flush=True)
        if live.state['sidebars'][1-panel]['open']:live.button('menu',hand=1-panel)
        if not live.state['sidebars'][panel]['open']:live.button('menu',hand=panel)
        hand=panel
        origin=head+rotate(eye['orientation_xyzw'],[(-.16 if hand==0 else .16),-.22,-.22])
        def menu():return live.state['sidebars'][panel]
        def target():
            a,b=map(np.asarray,menu()['grip_targets'][:2])
            direction=(b-a)/np.linalg.norm(b-a)
            margin=max(.04*menu()["scale"],.05)
            offset=(margin-.04*menu()["scale"])*.5
            return a-direction*offset if panel==0 else b+direction*offset
        def acquired(state):
            m=state['sidebars'][panel]
            a,b,top,bottom=map(np.asarray,m['grip_targets'])
            axis=(b-a)/np.linalg.norm(b-a)
            outer=max(.04*m['scale'],.05);inner=.04*m['scale']
            edge=a-axis*(outer-inner)*.5 if panel==0 else b+axis*(outer-inner)*.5
            border={'position':edge.tolist(),'hit_half_right':(axis*(outer+inner)*.5).tolist(),
                    'hit_half_up':((top-bottom)*.45).tolist()}
            return m['grip_state']=='ready' and target_metrics(border,state['hands'][hand])['predicted_hit']
        def aim(point,acquired=None):
            trial=reach_target(live,list(point),preset,23000+len(trials),target_position=origin.tolist(),hand=hand,acquired=acquired)
            trials.append(trial)
            (output/'remote-trials.json').write_text(json.dumps(trials,indent=2)+'\n')
            (output/'latest-state.json').write_text(json.dumps(live.state,indent=2)+'\n')
        def correction():
            a,b,top,bottom=map(np.asarray,menu()['grip_targets'])
            normal=np.cross(b-a,top-bottom);normal/=np.linalg.norm(normal)
            pose=live.state['hands'][hand];p=np.asarray(pose['position'])
            ray=np.asarray(rotate(pose['orientation_xyzw'],[0,0,-1]))
            denominator=np.dot(ray,normal)
            if abs(denominator)<1e-5:return np.zeros(3)
            hit=p+ray*np.dot(np.asarray(menu()['position'])-p,normal)/denominator
            error=target()-hit
            return error*min(.75,.06/max(np.linalg.norm(error),1e-6))
        # No controller reaches the window: only the ray changes orientation.
        # Bounded corrective aims use the observed ray error, with the same noise.
        offset=np.zeros(3)
        for attempt in range(3):
            aim(target()+offset,acquired)
            if not acquired(live.state):
                offset+=correction();continue
            trigger(hand,True)
            if live.state['remote_border']['active']:break
            trigger(hand,False)
        assert live.state['remote_border']['active'] and not live.state['remote_border']['resizing']
        original_tab=menu()['tab']
        initial=np.asarray(menu()['position']);radius=np.linalg.norm(initial-head)
        # Sweep sideways by a modest angle while maintaining the original depth.
        start_target=target()
        sweep=np.asarray(rotate(eye['orientation_xyzw'],[(-.08 if panel==0 else .08),.03,0]))
        for factor in (1,1.4,1.8):
            aim(start_target+sweep*factor,lambda s:math.dist(s['sidebars'][panel]['position'],initial)>.05)
            if math.dist(menu()['position'],initial)>.025:break
        assert np.linalg.norm(np.asarray(menu()['position'])-initial)>.025
        assert abs(np.linalg.norm(np.asarray(menu()['position'])-head)-radius)<.035
        assert math.dist(live.state['hands'][hand]['position'],origin)<.05
        capture(live,output,f'{panel}-remote-moving',panel,'moving')
        trigger(hand,False);assert not live.state['remote_border']['active']
        # Acquire once, then tap/release and immediately hold the second click.
        offset=np.zeros(3)
        for attempt in range(3):
            aim(target()+offset,acquired)
            if not acquired(live.state):
                offset+=correction();continue
            trigger(hand,True)
            if not live.state['remote_border']['active']:
                trigger(hand,False);continue
            trigger(hand,False);trigger(hand,True)
            if live.state['remote_border']['resizing']:break
            trigger(hand,False)
        assert live.state['remote_border']['resizing'],live.state['remote_border']
        center=np.asarray(menu()['position']);scale=menu()['scale']
        start=target()
        # Keep the noisy profile; use visible size feedback to stop the gesture,
        # as a person does, instead of accepting its arbitrary noisy endpoint.
        for factor in (1.4,1.6,1.8):
            aim(center+(start-center)*factor,lambda s:s['sidebars'][panel]['scale']>scale*1.20)
            if menu()['scale']>scale*1.12:break
        assert menu()['scale']>scale*1.12
        assert math.dist(center,menu()['position'])<.005
        capture(live,output,f'{panel}-remote-resizing',panel,'resizing')
        # Return to the initial size before release, keeping successive presets comparable.
        aim(start,lambda s:abs(s['sidebars'][panel]['scale']-scale)<scale*.08)
        trigger(hand,False);assert not live.state['remote_border']['active']
        assert menu()['tab']==original_tab,'Border gesture activated a neighboring tab'
        assert scene==live.state['presentation']['model_to_tracking_rows'],'Border gesture manipulated scene'
    (output/'remote-trials.json').write_text(json.dumps(trials,indent=2)+'\n')
    return {'remote_borders':True,'both_hands':True,'scene_unchanged':True}
