"""Real controller down-click, row motion, and retained stereo menu evidence."""
import json
import time
from tools.vr_workflows.menu_tour import find_control, acquired, scroll_page
from tools.vr_workflows.menu_focus_check import pad
from tools.vr_workflows.menu_pixels import check as menu_pixels
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.control_approach import control_approach


def check(live, output, preset, trials):
    hand=1
    while live.state['sidebars'][hand]['offset']:
        scroll_page(live, hand, -1)
    if live.state['sidebars'][hand]['input_mode']=='trackpad':
        pad(live, hand)
    catalog=json.loads(open('native/vr_viewer/sidebar_catalog.json').read())
    rows=next(t['rows'] for t in catalog['tabs'] if t['key']=='visualization')
    target=rows[7]['id']
    control=find_control(live,hand,target)
    for attempt in range(3):
        trial=reach_target(live,control['position'],preset,7300+len(trials),
                           acquired=lambda state: acquired(state,hand,target),
                           target_position=control_approach(control,live.state['hands'][1]['position']))
        trial.update(control=target,preset=preset,attempt=attempt+1)
        trials.append(trial)
        if trial['acquired_with_feedback'] and acquired(live.state,hand,target):
            break
    else:
        raise AssertionError('Noisy reach did not acquire scroll boundary after three attempts')
    files=['left.png','right.png','mirror.png','evidence.json']
    live.capture_to(output/(preset+'-scroll-before'),files=files,discard_source=True)
    before=find_control(live,hand,target)['position']
    pad(live,hand,y=-1)
    samples=[]
    until=time.monotonic()+.3
    while time.monotonic()<until:
        live.frame()
        samples.append(dict(frame=live.state['frame'],position=find_control(live,hand,target)['position']))
        time.sleep(.01)
    side=live.state['sidebars'][hand]
    assert side['offset']==1 and side['focus_id']==rows[8]['id'], side
    after=find_control(live,hand,target)['position']
    assert sum((a-b)**2 for a,b in zip(after,before))>.001, 'Row did not move visibly'
    destination=output/(preset+'-scroll-after')
    evidence,_=live.capture_to(destination,files=files,discard_source=True)
    pixels=menu_pixels(destination,evidence)
    revealed=[c for c in pixels['controls'] if c['id']==rows[8]['id']]
    assert len(revealed)==2 and all(c['passed'] for c in revealed), revealed
    (output/(preset+'-scroll.json')).write_text(json.dumps(dict(before=before,after=after,samples=samples,side=side,pixels=revealed),indent=2))
    pad(live,hand,y=1)
    assert live.state['sidebars'][hand]['focus_id']==target
    pad(live,hand)
