"""Move and resize the production keyboard via its ordinary border handlers."""
import json
import numpy as np
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.menu_grip_check import move, grip_origin


def verify(live, output, preset, review, keys, click, wait):
    trials=[]
    def menu(): return live.state['routing_popup'][1]
    assert abs(menu()['scale']-.84)<1e-5, 'keyboard did not open at 70% scale'
    def edge(): return np.asarray(menu()['grip_targets'][1])
    def axis():
        a,b=map(np.asarray,menu()['grip_targets'][:2]);return (b-a)/np.linalg.norm(b-a)
    left,right,top,bottom=map(np.asarray,menu()['grip_targets'])
    normal=np.cross(right-left,top-bottom);normal/=np.linalg.norm(normal)
    if np.dot(normal,np.asarray(live.state['hands'][1]['position'])-edge())<0:normal=-normal
    # Reach a defined 0.6 m ray distance with the same noisy profile, instead of
    # inheriting a distant, oblique pose from the last key on the opposite edge.
    origin=edge()+normal*.6
    def trigger(held):
        live.send('button',hand=1,button='trigger',pressed=held);live.frame()
    def aim(point,acquired=None):
        trials.append(reach_target(live,point.tolist(),preset,35000+len(trials),acquired=acquired,target_position=origin.tolist()))
    try:
        for _ in range(3):
            aim(edge(),lambda s:s['routing_popup'][1]['grip_state']=='ready')
            trigger(True)
            if live.state['remote_border']['active']:break
            trigger(False)
        assert live.state['remote_border']['active']
        start=np.asarray(menu()['position']);target=edge()+axis()*.10
        aim(target,lambda s:np.linalg.norm(np.asarray(s['routing_popup'][1]['position'])-start)>.025)
        assert np.linalg.norm(np.asarray(menu()['position'])-start)>.025
        trigger(False)
        review(preset+'-keyboard-border-moved',keys)
        for _ in range(3):
            aim(edge(),lambda s:s['routing_popup'][1]['grip_state']=='ready')
            trigger(True);trigger(False);trigger(True)
            if live.state['remote_border']['resizing']:break
            trigger(False)
        assert live.state['remote_border']['resizing']
        scale=menu()['scale'];aim(edge()+axis()*.10,lambda s:s['routing_popup'][1]['scale']>scale*1.04)
        assert menu()['scale']>scale*1.04
        trigger(False)
        resized=menu()['scale']
        click('routing:file-key-shift',preset);click('routing:file-key-shift',preset)
        wait(lambda s:any(c['id']=='routing:file-key-shift' and c['enabled'] for c in s['controls']))
        assert abs(menu()['scale']-resized)<1e-5, 'typing reset keyboard size'
        review(preset+'-keyboard-border-resized',keys)
        # Touch the same rail with the actual controller selection sphere.
        for _ in range(3):
            move(live,{1:grip_origin(live,1,edge())},preset,trials)
            if menu()['grip_nearby'][1]:break
        assert menu()['grip_nearby'][1]
        live.send('button',hand=1,button='grip',pressed=True);live.frame()
        assert menu()['grip_state']=='moving'
        start=np.asarray(menu()['position']);origin=np.asarray(live.state['hands'][1]['position'])
        move(live,{1:(origin+axis()*.06).tolist()},preset,trials)
        assert np.linalg.norm(np.asarray(menu()['position'])-start)>.025
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
        (output/(preset+'-border.json')).write_text(json.dumps({'passed':True,'opening_scale':.84,'resized_scale':resized,'trials':trials},indent=2))
    finally:
        (output/(preset+'-border-state.json')).write_text(json.dumps({'popup':menu(),'remote_border':live.state['remote_border']},indent=2))
        trigger(False);live.send('button',hand=1,button='grip',pressed=False);live.frame()
        (output/(preset+'-border-trials.json')).write_text(json.dumps(trials,indent=2))
