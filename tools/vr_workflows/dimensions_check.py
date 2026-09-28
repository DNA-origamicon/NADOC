"""Exercise controller dimensions through native ScryWrite input and submitted eyes."""
import json
import numpy as np
from .menu_tour import click, scroll_page
from .menu_focus_check import pad, seek
from .menu_grip_check import move
from .menu_pixels import check as check_pixels
from PIL import Image
from tools.vr_motion.visual_checks import project, coverage
from tools.vr_motion.metrics import rotate, target_metrics


def measurement_clearance(state):
    """Reject menu focus, ray hits and controller tips near the complete frame."""
    menu=state['sidebars'][1]
    left,right,top,bottom=map(np.asarray,menu['grip_targets'])
    r=(right-left)*.5
    u=(top-bottom)*.5
    center=(left+right)*.5
    target={'position':center.tolist(),'hit_half_right':r.tolist(),'hit_half_up':u.tolist()}
    checks=[]
    for pose in state['hands']:
        tip=np.asarray(pose['position'])+np.asarray(rotate(pose['orientation_xyzw'],[0,0,-.12]))
        # Require the tip to stay beyond the left edge, not merely outside a button.
        gap=-float(np.dot(tip-left,r/np.linalg.norm(r)))
        hit=target_metrics(target,pose)['predicted_hit']
        checks.append({'tip_left_clearance_m':gap,'ray_hits_panel':hit,
                       'input_owner':pose['input_owner'],
                       'passed':gap>=.10 and not hit and pose['input_owner']=='dimension'})
    endpoints=[]
    dimensions=state.get('dimensions',{})
    for entry in dimensions.get('entries',[]):
        if entry['id']==dimensions.get('selected'):
            endpoints=[-float(np.dot(np.asarray(e['world'])-left,r/np.linalg.norm(r)))
                       for e in entry['endpoints'] if e['valid']]
    return {'passed':menu['input_mode']=='pointer' and all(c['passed'] for c in checks)
            and all(gap>=.10 for gap in endpoints), 'hands':checks,
            'endpoint_left_clearance_m':endpoints}


def run(live, catalog, output, preset):
    trials = []
    checks = {}
    click(live, 1, 'tab:properties', preset, trials)
    while not any(c['id'] == 'section:properties:dimensions-heading' for c in live.state['controls']):
        scroll_page(live, 1, 1)
    click(live, 1, 'section:properties:dimensions-heading', preset, trials)
    assert live.state['dimensions']['active']
    assert not live.state['sidebars'][0]['open']
    assert all(not c['id'].startswith('tab:') for c in live.state['controls'])
    control = next(c for c in live.state['controls'] if c['id']=='dimension:toggle')
    right = np.array(control['hit_half_right']); right /= np.linalg.norm(right)
    up = np.array(control['hit_half_up']); up /= np.linalg.norm(up)
    normal = np.cross(right, up)
    # One workspace, derived from the actual panel, for every endpoint and model
    # manipulation. Stay left of the entire frame, including its grab margin.
    left_edge = np.asarray(live.state['sidebars'][1]['grip_targets'][0])
    base = left_edge-right*.48+normal*.20
    def position(x, y=0):
        return (base+right*x+up*y).tolist()
    forward = -normal
    q = np.r_[np.cross([0,0,-1], forward), 1+np.dot([0,0,-1],forward)]
    q = q/np.linalg.norm(q) if np.linalg.norm(q)>1e-8 else np.array([0,1,0,0])
    clearance = []
    def clear(stage):
        result = measurement_clearance(live.state)
        clearance.append({'stage':stage, 'frame':live.state['frame'], **result})
        (output/'measurement-clearance.json').write_text(json.dumps(clearance,indent=2))
        assert result['passed'], result
    def park():
        if live.state['sidebars'][1]['input_mode']=='trackpad':
            pad(live,1)
        # Setup/review repositioning is outside the measured noisy motion interval.
        for h in (0,1):
            live.send('pose',hand=h,position=position(-.14 if h==0 else .14),orientation=q.tolist())
        live.frame()
        clear('park')
    def trigger(hand):
        clear('before endpoint trigger')
        live.button('trigger',hand=hand)
        clear('after endpoint trigger')
    def measure_move(targets):
        move(live,targets,preset,trials)
        (output/'trials.json').write_text(json.dumps(trials,indent=2))
        for frame in trials[-1]['observed']:
            result=measurement_clearance(frame)
            clearance.append({'stage':'motion sample','frame':frame['frame'],**result})
            if not result['passed']:
                (output/'measurement-clearance.json').write_text(json.dumps(clearance,indent=2))
                raise AssertionError(result)
        clear('measured move')
    def freeze_new():
        park()
        for h in (0,1):
            if current()['endpoints'][h]['attached']:
                trigger(h)
        assert all(not e['attached'] for e in current()['endpoints'])
    park()
    def current():
        state = live.state['dimensions']
        return next(e for e in state['entries'] if e['id'] == state['selected'])
    pad(live,1)
    seek(live,1,'dimension:clear')
    live.button('trigger',hand=1)
    seek(live,1,'dimension:new')
    live.button('trigger',hand=1)
    park()
    identifier = current()['id']
    initial = current()['length_nm']
    live.frame()
    evidence, _ = live.capture_to(output/'line', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
    entry = next(e for e in evidence['state']['dimensions']['entries'] if e['id']==identifier)
    a, b = (np.array(e['world']) for e in entry['endpoints'])
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(output/'line'/(eye['eye']+'.png')).convert('RGB'))
        mask = (rgb[:,:,0]<80)&(rgb[:,:,1]>150)&(rgb[:,:,2]>180)
        points = [project(a+(b-a)*t, eye) for t in np.linspace(.15,.85,30)]
        assert coverage(mask,points,radius=3) >= .95, 'Measurement line missing in '+eye['eye']
        assert coverage(np.zeros_like(mask),points,radius=3)==0
    measure_move({1: position(.24)})
    assert current()['length_nm'] > initial
    trigger(0)
    pinned = current()['endpoints'][0]['world']
    measure_move({0: position(-.24)})
    assert np.allclose(current()['endpoints'][0]['world'], pinned, atol=1e-5)
    trigger(0)
    live.frame()
    assert current()['endpoints'][0]['attached']
    assert not np.allclose(current()['endpoints'][0]['world'], pinned, atol=.02)
    for h in (0, 1):
        trigger(h)
    assert all(not e['attached'] for e in current()['endpoints'])
    checks['live_length_pin_recall'] = True
    checks['measurement_clear_of_menu'] = True
    before = current()['length_nm']
    endpoints = np.array([e['world'] for e in current()['endpoints']])
    live.send('button', hand=0, button='grip', pressed=True)
    measure_move({0: position(-.24,.05)})
    live.send('button', hand=0, button='grip', pressed=False)
    live.frame()
    assert abs(current()['length_nm']-before) < .001
    assert not np.allclose([e['world'] for e in current()['endpoints']], endpoints, atol=.02)
    checks['model_move'] = True
    endpoints = np.array([e['world'] for e in current()['endpoints']])
    for h in (0, 1):
        live.send('button', hand=h, button='grip', pressed=True)
    measure_move({0: position(-.30,.05), 1: position(.30)})
    for h in (0, 1):
        live.send('button', hand=h, button='grip', pressed=False)
    live.frame()
    assert abs(current()['length_nm']-before) < .001
    resized = np.array([e['world'] for e in current()['endpoints']])
    assert np.linalg.norm(resized[1]-resized[0]) > np.linalg.norm(endpoints[1]-endpoints[0])*1.1
    checks['model_resize'] = True
    # Pad activates eye and delete independently from endpoint pinning.
    pad(live, 1)
    seek(live, 1, 'dimension:visibility:'+str(identifier))
    live.button('trigger', hand=1)
    assert not current()['visible']
    live.button('trigger', hand=1)
    assert current()['visible']
    seek(live, 1, 'dimension:new')
    live.button('trigger', hand=1)
    assert current()['id'] != identifier
    assert all(e['attached'] for e in current()['endpoints']), 'Menu trigger also pinned endpoint'
    freeze_new()
    pad(live,1)
    target = 'dimension:delete:'+str(identifier)
    # New-line auto-scroll may have crossed a page; reach the older row by pad.
    while not any(c['id']==target for c in live.state['controls']):
        previous_offset = live.state['sidebars'][1]['offset']
        assert previous_offset > 0, 'Retained dimension is not reachable'
        seek(live, 1, 'scrollbar')
        pad(live, 1, y=1)
        assert live.state['sidebars'][1]['offset'] < previous_offset
        assert any(c['id']=='dimension:toggle' for c in live.state['controls'])
        checks['sticky_commands_and_pad_scroll'] = True
    seek(live, 1, target)
    live.button('trigger', hand=1)
    assert all(e['id'] != identifier for e in live.state['dimensions']['entries'])
    checks['entry_actions'] = True
    evidence, _ = live.capture_to(output/'entries', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
    pixels = check_pixels(output/'entries', evidence)
    (output/'entries'/'pixels.json').write_text(json.dumps(pixels, indent=2))
    assert pixels['passed'], [c for c in pixels['controls'] if not c['passed']]
    pad(live, 1)  # Explicitly return to pointer selection for the small icons.
    remaining = current()['id']
    click(live, 1, 'dimension:visibility:'+str(remaining), preset, trials)
    assert not current()['visible']
    click(live, 1, 'dimension:visibility:'+str(remaining), preset, trials)
    assert current()['visible']
    click(live, 1, 'dimension:new', preset, trials)
    extra = current()['id']
    assert all(e['attached'] for e in current()['endpoints']), 'Pointer trigger also pinned endpoint'
    freeze_new()
    click(live, 1, 'dimension:delete:'+str(extra), preset, trials)
    assert all(e['id']!=extra for e in live.state['dimensions']['entries'])
    checks['pointer_icons'] = True
    live.button('menu', hand=0)
    assert not live.state['dimensions']['active'] and all(s['open'] for s in live.state['sidebars'])
    click(live, 1, 'section:properties:dimensions-heading', preset, trials)
    freeze_new()
    click(live, 1, 'dimension:toggle', preset, trials)
    assert not live.state['dimensions']['active'] and all(s['open'] for s in live.state['sidebars'])
    checks['both_exit_routes'] = True
    (output/'trials.json').write_text(json.dumps(trials, indent=2))
    return {'passed': True, 'checks': checks}
