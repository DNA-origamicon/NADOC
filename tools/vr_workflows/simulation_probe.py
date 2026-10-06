"""Drive simulation tabs, jobs, scrollbars and result controls with native input."""
import json
import os
from pathlib import Path
import sys
import time
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.menu_tour import click, find_control, scroll_page, enlarge_mirror
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.sidebar_pointer_scroll import reveal_result
from tools.vr_workflows.demo_view import reveal, hold
from tools.vr_workflows.menu_pixels import check


def run(socket, output, identifier):
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    until = time.monotonic() + 30
    while True:
        try:
            if bridge.call('scrywrite_observe', {}).get('focused'): break
        except OSError: pass
        if time.monotonic() > until: raise RuntimeError('VR did not focus')
        time.sleep(.1)
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
    prepare_audit_representation(live)
    trials = []; preset = os.environ.get('NADOC_VR_PROFILE', 'steady_fast')
    try:
        reveal(live)
        # Each invocation follows asynchronous desktop loading or native upload.
        # Observation settling is outside the unchanged measured input profile.
        settled = time.monotonic() + (3 if identifier == 'setup' else 1.5)
        while time.monotonic() < settled:
            live.frame()
            time.sleep(.05)
        if identifier == 'setup':
            enlarge_mirror(live)
            for h in (0, 1):
                if live.state['sidebars'][h]['open']: live.button('menu', hand=h)
            live.button('menu', hand=1);live.frame()
            click(live, 1, 'tab:visualization', preset, trials)
            for _ in range(50):
                if any(c['id']=='reset-btn' for c in live.state['controls']): break
                scroll_page(live, 1, 1)
            click(live, 1, 'reset-btn', preset, trials)
            live.button('menu', hand=1);live.frame()
            evidence, _ = live.capture_to(out/'anchor', files=['evidence.json'], discard_source=True)
            head = np.mean([e['position'] for e in evidence['eyes']], axis=0)
            q = evidence['eyes'][0]['orientation_xyzw']
            p = live.state['presentation'];matrix = np.array(p['model_to_tracking_rows'])
            center = (matrix @ np.r_[p['normalized_offset_model'], 1])[:3]
            live.send('pose', hand=1, position=center.tolist(), orientation=[0,0,0,1]);live.frame()
            live.send('button', hand=1, button='grip', pressed=True);live.frame()
            target = head + rotate(q,[.70,.12,-1.45])
            live.send('pose', hand=1, position=target.tolist(), orientation=[0,0,0,1]);live.frame()
            live.send('button', hand=1, button='grip', pressed=False);live.frame()
            live.button('menu', hand=0);live.frame()
            click(live, 0, 'tab:dynamics', preset, trials)
            panel = live.state['sidebars'][0]
            edge = np.array(panel['grip_targets'][0]);delta = head+rotate(q,[-.52,-.18,-1.35])-panel['position']
            live.send('pose', hand=1, position=edge.tolist(), orientation=q);live.frame()
            live.send('button', hand=1, button='grip', pressed=True);live.frame()
            assert live.state['sidebars'][0]['grip_state']=='moving'
            live.send('pose', hand=1, position=(edge+delta).tolist(), orientation=q);live.frame()
            live.send('button', hand=1, button='grip', pressed=False);live.frame()
            live.capture_to(out/'positioned', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
            return
        if identifier == 'capture':
            # Frame result is a footer action, outside the list navigation path.
            # Use the ordinary profile-driven ray click; keep prior touchpad
            # failures as separate evidence, without changing native focus rules.
            click(live,0,'sim:frame',preset,trials)
            anchor,_=live.capture_to(out/'fit',files=['evidence.json'],discard_source=True)
            head=np.mean([e['position'] for e in anchor['eyes']],axis=0);q=anchor['eyes'][0]['orientation_xyzw']
            center=head+rotate(q,[0,0,-1.3]);target=head+rotate(q,[.63,.22,-1.3])
            # Move the fitted result beside the menu through the normal scene grip.
            for h in (0,1):
                live.send('pose',hand=h,position=(head+rotate(q,[0,-1,0])).tolist(),orientation=[0,0,0,1])
            live.frame()
            live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
            live.send('button',hand=1,button='grip',pressed=True);live.frame()
            live.send('pose',hand=1,position=target.tolist(),orientation=[0,0,0,1]);live.frame()
            live.send('button',hand=1,button='grip',pressed=False);live.frame()
            # Enlarge the fitted result with the ordinary two-hand grip. This is
            # observation setup, outside the measured navigation reaches.
            for h,sign in ((0,-1),(1,1)):
                live.send('pose',hand=h,position=(target+rotate(q,[0,sign*.1,0])).tolist(),orientation=q)
            live.frame()
            for h in (0,1):live.send('button',hand=h,button='grip',pressed=True)
            live.frame()
            before_scale=np.linalg.norm(np.asarray(live.state['presentation']['model_to_tracking_rows'])[:3,0])
            for h,sign in ((0,-1),(1,1)):
                live.send('pose',hand=h,position=(target+rotate(q,[0,sign*.2,0])).tolist(),orientation=q)
            live.frame()
            after_scale=np.linalg.norm(np.asarray(live.state['presentation']['model_to_tracking_rows'])[:3,0])
            assert after_scale > before_scale*1.8, 'Observation enlargement did not acquire the model grips'
            for h in (0,1):live.send('button',hand=h,button='grip',pressed=False)
            live.frame()
            for h in (0,1):live.send('pose',hand=h,position=(head+rotate(q,[0,-1,0])).tolist(),orientation=[0,0,0,1])
            live.frame()
            hold(live,'Fitted static result')
            evidence, _ = live.capture_to(out/'after', files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'], discard_source=True)
            for eye in evidence['eyes']:
                classes=np.fromfile(out/'after'/(eye['eye']+'.classes.u8'),dtype=np.uint8)
                assert (classes==1).sum()>100, 'Static result missing in '+eye['eye']
            pixels=check(out/'after',evidence)
            (out/'pixels.json').write_text(json.dumps(pixels,indent=2))
            assert pixels['passed'], str([c for c in pixels['controls'] if not c['passed']])
            from copy import deepcopy
            offscreen = deepcopy(evidence)
            for control in offscreen['state']['controls']:
                control['position'] = [1000, 1000, 1000]
            assert not check(out/'after', offscreen)['passed'], 'Offscreen negative control passed'
            from tools.vr_motion.desktop_check import run as desktop_check
            desktop = desktop_check(socket, out/'desktop', live=live, reveal=True)
            # Keep visiting the other engines if the desktop window was covered;
            # the calling tour reports all delivery failures at its final gate.
            (out/'delivery.json').write_text(json.dumps(desktop, indent=2))
            return
        if live.state['sidebars'][1]['open']: live.button('menu', hand=1)
        if not live.state['sidebars'][0]['open']: live.button('menu', hand=0)
        live.frame()
        if live.state['sidebars'][0]['tab'] != 'dynamics': click(live, 0, 'tab:dynamics', preset, trials)
        target = 'sim:' + identifier
        if identifier.startswith(('j:', 'v:')):
            reveal_result(live, target)
            assert find_control(live, 0, target)['enabled'], target
            click(live, 0, target, preset, trials)
        else:
            click(live, 0, target, preset, trials)
        hold(live, identifier)
        evidence, _ = live.capture_to(out / 'after', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
        (out / 'result.json').write_text(json.dumps(live.state, indent=2))
        # Menu evidence is retained; model/result pixels are checked after the
        # browser has finished loading in the calling desktop test.
        (out / 'pixels.json').write_text(json.dumps(check(out / 'after', evidence), indent=2))
    finally:
        (out / 'reaches.json').write_text(json.dumps(trials, indent=2))
        live.release()


if __name__ == '__main__': run(*sys.argv[1:])
