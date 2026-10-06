"""Exercise the real detached desktop, border grips and partial-trigger lens."""
import json
import math
import time
import numpy as np
from .menu_grip_check import move, grip_origin
from .profile_input import reach_target
from .control_approach import control_approach
from tools.vr_motion.visual_checks import project, coverage
from tools.vr_motion.metrics import rotate, target_metrics
from PIL import Image


def run(live, output, preset, owner, trials, spawn_pose=None):
    def state():
        return live.state['desktop_capture']
    def control(name):
        return next(c for c in live.state['controls'] if c['id'] == name)
    def capture(name):
        live.capture_to(output/name, files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
    assert state()['open'] and live.state['sidebars'][owner]['open']
    deadline = time.monotonic()+5
    while not state()['ready']:
        assert time.monotonic() < deadline
        live.frame(); time.sleep(.05)
    original = list(state()['position'])
    original_scene = live.state['presentation']['model_to_tracking_rows']
    # Close hand menus using their real menu buttons; desktop must stay in space.
    for hand in (0,1):
        if live.state['sidebars'][hand]['open']:
            live.button('menu',hand=hand)
    assert state()['open'] and state()['position'] == original
    capture('native-desktop')
    # Grab its right border and move it with the existing noisy motion profile.
    for _ in range(3):
        move(live,{1:grip_origin(live,1,control('desktop-grip-right')['position'])},preset,trials)
        live.send('button',hand=1,button='grip',pressed=True);live.frame()
        if state()['moving']:
            break
        # Release a missed contact before the next noisy reach; never move the
        # scene while a failed panel acquisition is still holding Grip.
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
    assert state()['moving'], state()
    target=np.asarray(live.state['hands'][1]['position'])+np.array([.08,.05,0])
    move(live,{1:target.tolist()},preset,trials)
    live.send('button',hand=1,button='grip',pressed=False);live.frame()
    assert math.dist(original,state()['position'])>.04
    for _ in range(3):
        move(live,{h:grip_origin(live,h,control('desktop-grip-left' if h==0 else 'desktop-grip-right')['position']) for h in (0,1)},preset,trials)
        for hand in (0,1):live.send('button',hand=hand,button='grip',pressed=True)
        live.frame()
        if state()['resizing']:
            break
        for hand in (0,1):live.send('button',hand=hand,button='grip',pressed=False)
        live.frame()
    assert state()['resizing'],state()
    scale=state()['scale']
    right=np.asarray(control('desktop-content')['hit_half_right']);right/=np.linalg.norm(right)
    move(live,{h:(np.asarray(live.state['hands'][h]['position'])+right*(.08 if h else -.08)).tolist() for h in (0,1)},preset,trials)
    for hand in (0,1):live.send('button',hand=hand,button='grip',pressed=False)
    live.frame();assert state()['scale']>scale+.02
    capture('desktop-resized')
    evidence=json.loads((output/'desktop-resized'/'evidence.json').read_text())
    head=np.mean([e['position'] for e in evidence['eyes']],axis=0)
    origin=head+rotate(evidence['eyes'][0]['orientation_xyzw'],[.12,-.2,-.22])
    def border_control(s):
        cs={c['id']:c for c in s['controls']}
        rail=cs['desktop-grip-right'];body=cs['desktop-content']
        axis=np.asarray(body['hit_half_right']);axis/=np.linalg.norm(axis)
        inner=s['desktop_capture']['scale']*.025;outer=max(inner,.05)
        return {**rail,'position':(np.asarray(rail['position'])+axis*(outer-inner)*.5).tolist(),
                'hit_half_right':(axis*(outer+inner)*.5).tolist(),'hit_half_up':body['hit_half_up']}
    def border_hit(s):
        return target_metrics(border_control(s),s['hands'][1])['predicted_hit']
    def aim_remote(point, acquired=None):
        trial=reach_target(live,list(point),preset,27000+len(trials),
            target_position=origin.tolist(),acquired=acquired)
        trials.append(trial)
        (output/'desktop-remote-trials.json').write_text(json.dumps(trials,indent=2)+'\n')
        (output/'desktop-latest-state.json').write_text(json.dumps(live.state,indent=2)+'\n')
    def correction():
        c=border_control(live.state)
        normal=np.cross(c['hit_half_right'],c['hit_half_up']);normal/=np.linalg.norm(normal)
        pose=live.state['hands'][1];p=np.asarray(pose['position'])
        ray=np.asarray(rotate(pose['orientation_xyzw'],[0,0,-1]))
        denominator=np.dot(ray,normal)
        if abs(denominator)<1e-5:return np.zeros(3)
        target=np.asarray(c['position'])
        hit=p+ray*np.dot(target-p,normal)/denominator
        error=target-hit
        return error*min(.75,.06/max(np.linalg.norm(error),1e-6))
    def trigger(pressed):
        live.send('button',hand=1,button='trigger',pressed=pressed);live.frame()
    offset=np.zeros(3)
    for attempt in range(6):
        aim_remote(np.asarray(border_control(live.state)['position'])+offset,border_hit)
        if not border_hit(live.state):
            offset+=correction();continue
        trigger(True)
        if live.state['remote_border']['active']:break
        trigger(False)
    assert live.state['remote_border']['active']
    before=np.asarray(state()['position'])
    def local_center():
        pose=live.state['hands'][1];q=pose['orientation_xyzw']
        return np.asarray(rotate([-q[0],-q[1],-q[2],q[3]],np.asarray(state()['position'])-pose['position']))
    anchor=local_center()
    target=np.asarray(border_control(live.state)['position'])
    sweep=np.asarray(rotate(evidence['eyes'][0]['orientation_xyzw'],[.1,.03,0]))
    for factor in (1,1.4,1.8):
        aim_remote(target+sweep*factor,lambda s:math.dist(s['desktop_capture']['position'],before)>.05)
        if math.dist(before,state()['position'])>.025:break
    assert math.dist(before,state()['position'])>.025
    assert np.linalg.norm(local_center()-anchor)<.005
    capture('desktop-remote-moving');trigger(False)
    offset=np.zeros(3)
    for attempt in range(6):
        aim_remote(np.asarray(border_control(live.state)['position'])+offset,border_hit)
        if not border_hit(live.state):
            offset+=correction();continue
        trigger(True)
        if not live.state['remote_border']['active']:
            trigger(False);continue
        trigger(False);trigger(True)
        if live.state['remote_border']['resizing']:break
        trigger(False)
    assert live.state['remote_border']['resizing']
    center=np.asarray(state()['position']);start=np.asarray(border_control(live.state)['position']);remote_scale=state()['scale']
    for factor in (1.4,1.6,1.8):
        aim_remote(center+(start-center)*factor,lambda s:s['desktop_capture']['scale']>remote_scale*1.2)
        if state()['scale']>remote_scale*1.12:break
    assert state()['scale']>remote_scale*1.12 and math.dist(center,state()['position'])<.005
    capture('desktop-remote-resizing')
    aim_remote(start,lambda s:abs(s['desktop_capture']['scale']-remote_scale)<remote_scale*.08)
    trigger(False)

    # Point at screen center. Scripted sessions suppress ALL OS pointer/click injection.
    c=control('desktop-content')
    trial=reach_target(live,c['position'],preset,18000+len(trials),
        target_position=control_approach(c,live.state['hands'][1]['position']))
    trials.append(trial)
    live.send('trigger_value',hand=1,value=.4);live.frame()
    assert state()['magnifying'],state()
    capture('desktop-magnifier')
    live.send('trigger_value',hand=1,value=1);live.frame()
    assert not state()['magnifying']
    live.send('trigger_value',hand=1,value=0);live.frame()
    assert not state()['magnifying']
    capture('desktop-unmagnified')
    # Locate the actual lens rim in both submitted eyes, plus a released-trigger
    # negative control at the same location. Never accept just the state flag.
    pixel_checks=[]
    for name,expected in [('desktop-magnifier',True),('desktop-unmagnified',False)]:
        evidence=json.loads((output/name/'evidence.json').read_text())
        dc=evidence['state']['desktop_capture']
        c=next(c for c in evidence['state']['controls'] if c['id']=='desktop-content')
        r=np.asarray(c['hit_half_right']);u=np.asarray(c['hit_half_up'])
        aspect=np.linalg.norm(r)/np.linalg.norm(u)
        center=np.asarray(c['position'])+r*(2*dc['pointer'][0]-1)+u*(1-2*dc['pointer'][1])
        points=[center+r*(2*.1575/aspect*np.cos(a))+u*(2*.1575*np.sin(a)) for a in np.linspace(0,2*np.pi,180)]
        for eye in evidence['eyes']:
            rgb=np.asarray(Image.open(output/name/(eye['eye']+'.png')).convert('RGB')).astype(int)
            rim=(rgb[:,:,2]>200)&(rgb[:,:,1]>110)&(rgb[:,:,1]<210)&(rgb[:,:,0]<140)&(rgb[:,:,2]>rgb[:,:,0]+60)
            score=coverage(rim,[project(p,eye) for p in points],radius=2)
            pixel_checks.append({'capture':name,'eye':eye['eye'],'rim_coverage':score,'expected':expected})
            assert (score>.65 if expected else score<.35),pixel_checks
    (output/'desktop-lens-pixels.json').write_text(json.dumps(pixel_checks,indent=2)+'\n')
    # Reopening a hand menu cannot dismiss/reset the desktop.
    if spawn_pose is not None:
        live.send('pose', hand=owner, position=spawn_pose['position'], orientation=spawn_pose['orientation_xyzw'])
        live.frame()
    live.button('menu',hand=owner)
    assert state()['open'] and live.state['sidebars'][owner]['open']
    for attempt in range(3):
        c=control('desktop-close')
        trial=reach_target(live,c['position'],preset,19000+len(trials),
            acquired=lambda s:s['desktop_capture']['close_hovered'],
            target_position=control_approach(c,live.state['hands'][1]['position']))
        trials.append(trial)
        if state()['close_hovered']:break
    assert state()['close_hovered']
    live.button('trigger',hand=1);live.frame()
    assert not state()['open'] and live.state['sidebars'][owner]['open']
    assert live.state['sidebars'][owner]['tab']=='vr'
    assert live.state['presentation']['model_to_tracking_rows'] == original_scene
    (output/'desktop-panel-check.json').write_text(json.dumps({'passed':True,'preset':preset,'initial_scale':scale,'final_scale':state()['scale'],'os_input_injected':False},indent=2)+'\n')
