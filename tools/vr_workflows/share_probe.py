"""Physical controller Share tab actions; only test-owned local hosting is started by this tour."""
import copy
import json
import os
from pathlib import Path
import sys
import time
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.demo_view import reveal
from tools.vr_workflows.audit_representation import wait_startup
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.menu_tour import click
from tools.vr_workflows.menu_pixels import check

socket, output, action = sys.argv[1:4]
out = Path(output); out.mkdir(parents=True, exist_ok=True)
bridge = Bridge(socket)
deadline = time.monotonic()+30
while True:
    try:
        if bridge.call('scrywrite_observe', {}).get('focused'): break
    except OSError: pass
    if time.monotonic()>deadline: raise RuntimeError('Viewer did not focus')
    time.sleep(.1)
live = LiveSession(bridge, physical=True, allow_transactions=True)
trials = []
preset = os.environ.get('NADOC_VR_PROFILE', 'steady_fast')
try:
    wait_startup(live)
    reveal(live)
    anchor, _ = live.capture_to(out/'anchor', files=['left.png','right.png','evidence.json'], discard_source=True)
    orientation = anchor['eyes'][0]['orientation_xyzw']
    head = live.state['head_position']
    for hand, offset in [(0, [-.25,-.18,-.35]), (1, [.25,-.18,-.35])]:
        delta = rotate(orientation, offset)
        live.send('pose', hand=hand, position=[a+b for a,b in zip(head,delta)], orientation=orientation)
        live.frame()
    if live.state['sidebars'][1]['open']: live.button('menu', hand=1); live.frame()
    if not live.state['sidebars'][0]['open']: live.button('menu', hand=0); live.frame()
    if live.state['sidebars'][0]['tab'] != 'share': click(live, 0, 'tab:share', preset, trials)
    assert live.state['sidebars'][0]['layout']=='valid'
    def control(identifier):
        return next(c for c in live.state['controls'] if c['id']==identifier)
    if action in ('start', 'pause', 'resume', 'end', 'admit'):
        deadline=time.monotonic()+15
        while not control('share-'+action)['enabled']:
            if time.monotonic()>deadline: raise RuntimeError('Presenter control unavailable: '+str(live.state))
            live.frame(); time.sleep(.1)
        click(live,0,'share-'+action,preset,trials)
    else:
        assert not any(control('share-'+name)['enabled'] for name in ('pause','resume','end','admit'))
    time.sleep(.5);live.frame()
    # Remove the pointing hand from the text before captures.
    live.send('pose', hand=1, position=[0,-1,0], orientation=[0,0,0,1]);live.frame()
    evidence,_=live.capture_to(out/'after',discard_source=True)
    result=check(out/'after',evidence)
    (out/'pixels.json').write_text(json.dumps(result,indent=2))
    assert result['passed'],str([v for v in result['controls'] if not v['passed']])
    negative=copy.deepcopy(evidence)
    for c in negative['state']['controls']:c['position']=[1000,1000,1000]
    assert not check(out/'after',negative)['passed']
    from tools.vr_motion.desktop_check import run as check_desktop
    assert check_desktop(socket,out/'desktop',live=live,reveal=True)['passed']
except Exception:
    live.capture_to(out/'failure', discard_source=True)
    raise
finally:
    (out/'reaches.json').write_text(json.dumps(trials,indent=2))
    live.release()
