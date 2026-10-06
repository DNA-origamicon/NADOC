"""Profile-driven presenter gestures; hold the measured pose for guest capture."""
import json, os, sys, time
from pathlib import Path
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.menu_tour import click
CAPTURE_FILES=['evidence.json','objects.json','left.png','right.png','mirror.png','left.scry-visual','right.scry-visual','mirror.scry-visual']
socket, output, action=sys.argv[1:4]
out=Path(output);out.mkdir(parents=True,exist_ok=True)
bridge=Bridge(socket);deadline=time.monotonic()+30
while True:
    try:
        if bridge.call('scrywrite_observe',{}).get('focused'):break
    except OSError:pass
    if time.monotonic()>deadline:raise RuntimeError('Viewer did not focus')
    time.sleep(.1)
live=LiveSession(bridge,physical=True,allow_transactions=True)
preset=os.environ.get('NADOC_VR_PROFILE','steady_fast');trials=[]
try:
    before=live.state['presentation']
    if action in ('off','on'):
        if not live.state['sidebars'][0]['open']:live.button('menu',hand=0);live.frame()
        if live.state['sidebars'][0]['tab']!='share':click(live,0,'tab:share',preset,trials)
        assert live.state['show_vr_model']==(action=='off')
        click(live,0,'share-avatar',preset,trials)
        assert live.state['show_vr_model']==(action=='on')
        evidence,_=live.capture_to(out/'menu',files=CAPTURE_FILES,discard_source=True)
        from tools.vr_workflows.menu_pixels import check
        assert check(out/'menu',evidence)['passed']
    else:
        for h in (0,1):
            if live.state['sidebars'][h]['open']:live.button('menu',hand=h);live.frame()
    evidence,_=live.capture_to(out/'before',files=CAPTURE_FILES,discard_source=True)
    head=np.mean([e['position'] for e in evidence['eyes']],axis=0);q=evidence['eyes'][0]['orientation_xyzw']
    def reach(hand,local):
        p=(head+rotate(q,local)).tolist()
        trials.append(reach_target(live,p,preset,21000+len(trials),target_position=p,target_orientation=q,hand=hand))
    for h in (0,1):reach(h,[(-1 if h==0 else 1)*.15,-.3,-.45])
    if action=='scale':
        for h in (0,1):live.send('button',hand=h,button='grip',pressed=True);live.frame()
        reach(0,[-.3,-.3,-.45]);reach(1,[.3,-.3,-.45])
        for h in (0,1):live.send('button',hand=h,button='grip',pressed=False);live.frame()
    if action=='gesture':reach(1,[.4,-.1,-.65])
    if action in ('left-menu','right-menu'):
        hand=0 if action=='left-menu' else 1
        live.button('menu',hand=hand);live.frame()
        click(live,hand,'tab:share' if hand==0 else 'tab:visualization',preset,trials)
    if action=='desktop':
        live.button('menu',hand=1);live.frame()
        click(live,1,'tab:tools',preset,trials)
        click(live,1,'vr-desktop',preset,trials)
    if action=='wheel':
        live.send('trackpad_axis', hand=1, x=0, y=0);live.frame()
        live.send('button',hand=1,button='trackpad',pressed=True);live.frame()
        from .edit_wheel_check import slide
        slide(live,1,preset,trials)
    if action=='view-tools' or (action=='scissors' and not live.state['ligation']['nick_active']):
        hand=0 if action=='view-tools' else 1
        forward=rotate(q,[0,0,-1]);forward[1]=0;forward/=np.linalg.norm(forward)
        right=np.cross(forward,[0,1,0]);side=-1 if hand==0 else 1
        for point,pause in [(head+right*side*.28+forward*.4+[0,-.1,0],.25),(head+right*side*.28-forward*.28+[0,.08,0],.6),(head+right*side*.28+forward*.4+[0,-.1,0],.1)]:
            p=point.tolist();trials.append(reach_target(live,p,preset,22000+len(trials),target_position=p,target_orientation=q,hand=hand))
            until=time.monotonic()+pause
            while time.monotonic()<until:live.frame();time.sleep(.02)
        assert live.state['view_tools']['open'] if hand==0 else live.state['ligation']['nick_active']
    if action=='closed' and live.state['view_tools']['open']:
        forward=rotate(q,[0,0,-1]);forward[1]=0;forward/=np.linalg.norm(forward);right=np.cross(forward,[0,1,0])
        for point,pause in [(head-right*.28+forward*.4+[0,-.1,0],.25),(head-right*.28-forward*.28+[0,.08,0],.6),(head-right*.28+forward*.4+[0,-.1,0],.1)]:
            p=point.tolist();trials.append(reach_target(live,p,preset,23000+len(trials),target_position=p,target_orientation=q,hand=0))
            until=time.monotonic()+pause
            while time.monotonic()<until:live.frame();time.sleep(.02)
        assert not live.state['view_tools']['open']

    live.capture_to(out/'after',files=CAPTURE_FILES,discard_source=True)
    (out/'ready.json').write_text(json.dumps({'before':before,'after':live.state['presentation'],'show':live.state['show_vr_model'],'view_tools':live.state['view_tools'],'sidebars':live.state['sidebars'],'nick':live.state['ligation']['nick_active']}))
    if action=='scissors':assert live.state['ligation']['nick_active']
    deadline=time.monotonic()+25
    held=[dict(p) for p in live.state['hands']]
    while not (out/'release').exists() and time.monotonic()<deadline:
        # Review time is outside measured reaches; renew the owned input lease
        # at the actual reached poses so a held wheel cannot expire mid-capture.
        for h,p in enumerate(held):live.send('pose',hand=h,position=p['position'],orientation=p['orientation_xyzw'])
        live.frame();time.sleep(.03)
    if action=='wheel':
        live.send('button',hand=1,button='trackpad',pressed=False);live.frame()
        assert live.state['ligation']['nick_active']
finally:
    (out/'reaches.json').write_text(json.dumps(trials,indent=2));live.release()
