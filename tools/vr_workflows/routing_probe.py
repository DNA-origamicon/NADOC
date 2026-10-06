"""Exercise document-bound routing dialogs with ordinary profiled controller input."""
import json
import os
import sys
import time
from pathlib import Path
from copy import deepcopy
import numpy as np
from scipy.spatial.transform import Rotation
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.control_approach import control_approach
from tools.vr_workflows.menu_tour import click, scroll_page, enlarge_mirror
from tools.vr_workflows.menu_pixels import check


def run(socket, output, identifier):
    out = Path(output);out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    until=time.monotonic()+30
    while not bridge.call('scrywrite_observe', {}).get('focused'):
        if time.monotonic()>until:raise RuntimeError('Viewer did not focus')
        time.sleep(.1)
    live=LiveSession(bridge, physical=True, allow_transactions=True)
    trials=[];preset=os.environ.get('NADOC_VR_PROFILE','steady_fast')
    try:
        until=time.monotonic()+.7
        while time.monotonic()<until:live.frame();time.sleep(.02)
        if identifier=='setup':
            enlarge_mirror(live)
            if live.state['sidebars'][0]['open']:live.button('menu',hand=0)
            if not live.state['sidebars'][1]['open']:live.button('menu',hand=1)
            # Reopen at an eye-facing wrist pose derived from the exported panel
            # axes; this is observation setup, outside the measured input trials.
            anchor,_=live.capture_to(out/'anchor',files=['evidence.json'],discard_source=True)
            eye=anchor['eyes'][0];head=np.mean([e['position'] for e in anchor['eyes']],axis=0)
            control=next(c for c in live.state['controls'] if c.get('sidebar')=='right')
            r=np.array(control['hit_half_right']);r/=np.linalg.norm(r)
            u=np.array(control['hit_half_up']);u/=np.linalg.norm(u)
            panel=Rotation.from_matrix(np.column_stack([r,u,np.cross(r,u)]))
            wrist=Rotation.from_quat(live.state['hands'][1]['orientation_xyzw'])
            facing=Rotation.from_quat(eye['orientation_xyzw'])
            desired=facing*(wrist.inv()*panel).inv()
            center=head+facing.apply([0,0,-.60])
            live.button('menu',hand=1)
            live.send('pose',hand=1,position=(center-desired.apply([0,0,-.4])).tolist(),orientation=desired.as_quat().tolist());live.frame()
            live.button('menu',hand=1);live.frame()
            click(live,1,'tab:tools',preset,trials)
        elif identifier.startswith('menu-') and not live.state['routing_popup'][1]['open']:
            for _ in range(8):
                if any(c['id']==identifier for c in live.state['controls']):break
                scroll_page(live,1,1)
            click(live,1,identifier,preset,trials)
        else:
            target='routing:'+identifier
            for _ in range(25):
                control=next((c for c in live.state['controls'] if c['id']==target),None)
                if control:break
                # Popup scrolling is normal right trackpad focus navigation.
                from tools.vr_workflows.menu_focus_check import pad
                popup=live.state['routing_popup'][1]
                if popup['input_mode']!='trackpad':pad(live,1)
                pad(live,1,y=-1)
            if not control:raise RuntimeError('Missing popup control '+target)
            if live.state['routing_popup'][1]['input_mode']=='trackpad':
                from tools.vr_workflows.menu_focus_check import pad
                pad(live,1)
            acquired=lambda state:state['routing_popup'][1]['hover_id']==target
            for attempt in range(3):
                trial=reach_target(live,control['position'],preset,8300+attempt,acquired=acquired,target_position=control_approach(control,live.state['hands'][1]['position']))
                trials.append(trial)
                if trial['acquired_with_feedback'] and acquired(live.state):break
            else:raise RuntimeError('Could not point at '+target)
            live.button('trigger',hand=1)
        until=time.monotonic()+1
        while time.monotonic()<until:live.frame();time.sleep(.02)
        evidence,_=live.capture_to(out/'after',files=['left.png','right.png','mirror.png','evidence.json'],discard_source=True)
        pixels=check(out/'after',evidence)
        (out/'pixels.json').write_text(json.dumps(pixels,indent=2))
        (out/'state.json').write_text(json.dumps(live.state,indent=2))
        assert pixels['passed'], str([c for c in pixels['controls'] if not c['passed']])
        negative=deepcopy(evidence)
        for control in negative['state']['controls']:control['position']=[1000,1000,1000]
        assert not check(out/'after',negative)['passed']
    finally:
        (out/'reaches.json').write_text(json.dumps(trials,indent=2))
        live.release()


if __name__=='__main__':run(*sys.argv[1:])
