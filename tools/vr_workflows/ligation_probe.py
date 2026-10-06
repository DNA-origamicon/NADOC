"""Ordinary radius-wheel selection and trigger-stretched forced ligation."""
import json
from tools.vr_workflows.audit_intervals import operation
import os
import sys
import time
from pathlib import Path
from urllib.parse import unquote
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import rotate
from tools.vr_motion.model import multiply
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.demo_view import reveal, hold
from tools.vr_workflows.ligation_pixels import preview, committed


def run(socket, output, role):
    role = int(role)
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic() + 30
    readiness=[]
    while True:
        try:
            observed=bridge.call('scrywrite_observe', {})
            readiness.append({'focused':bool(observed.get('focused'))})
            if observed.get('focused'):break
        except OSError as error:
            readiness.append({'startup_transport':type(error).__name__})
        (out/'startup.json').write_text(json.dumps(readiness,indent=2))
        if time.monotonic() > deadline: raise RuntimeError('Viewer did not focus')
        time.sleep(.1)
    (out/'startup.json').write_text(json.dumps(readiness,indent=2))
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
    prepare_audit_representation(live)
    preset = os.environ.get('NADOC_VR_PROFILE', 'steady_fast')
    trials = []
    def wait(predicate):
        deadline = time.monotonic() + 90
        while not predicate(live.state):
            if time.monotonic() > deadline: raise RuntimeError('Ligation state timed out')
            try:live.frame()
            except TimeoutError:continue
            time.sleep(.05)
    def reach(point, q=None, acquired=None):
        for attempt in range(3 if acquired else 1):
            trial = reach_target(live, point, preset, 9200 + len(trials),
                target_position=point, target_orientation=q or [0,0,0,1], acquired=acquired)
            trial['attempt'] = attempt + 1
            trials.append(trial)
            (out/'reaches.json').write_text(json.dumps(trials, indent=2))
            if acquired is None or acquired(live.state): return
        raise RuntimeError('Target not acquired after three ordinary profile reaches')
    def endpoint(index, acquired=None):
        point = np.array(live.state['ligation']['ends'][index]['world']) + [0,0,.12]
        reach(point.tolist(), acquired=acquired)
    def wheel(index):
        q = eye['orientation_xyzw']
        center = np.array(eye['position']) + rotate(q, [0,-.1,-.55])
        reach((center + rotate(q,[0,0,.12])).tolist(), q)
        live.send('trackpad_axis', hand=1, x=0, y=0);live.frame()
        live.send('button', hand=1, button='trackpad', pressed=True);live.frame()
        assert live.state['radial_edit']['open']
        items = live.state['radial_edit']['items']
        assert [i['label'] for i in items] == ['LIGATE','NICK','UNDO','REDO']
        assert [i['enabled'] for i in items] == [True,True,True,True]
        from .edit_wheel_check import slide
        slide(live,index,preset,trials)
        live.capture_to(out/f'wheel-{index}', discard_source=True)
        live.send('button', hand=1, button='trackpad', pressed=False);live.frame()
    try:
        reveal(live)
        for h in (0,1):
            if live.state['sidebars'][h]['open']: live.button('menu',hand=h);live.frame()
        wait(lambda s:len(s.get('ligation',{}).get('ends',[]))>=4)
        evidence,_=live.capture_to(out/'before-framing',discard_source=True)
        eye=evidence['eyes'][0]
        if role==3:
            ends=live.state['ligation']['ends']
            center=np.mean([e['world'] for e in ends],axis=0)
            target=np.array(eye['position'])+rotate(eye['orientation_xyzw'],[0,0,-.85])
            turn=multiply(eye['orientation_xyzw'],[0,np.sin(np.pi/4),0,np.cos(np.pi/4)])
            live.send('pose',hand=1,position=center.tolist(),orientation=[0,0,0,1]);live.frame()
            live.send('button',hand=1,button='grip',pressed=True);live.frame()
            live.send('pose',hand=1,position=target.tolist(),orientation=turn);live.frame()
            live.send('button',hand=1,button='grip',pressed=False);live.frame()
            wheel(0)
        assert live.state['ligation']['active']
        ends=live.state['ligation']['ends']
        source=next(i for i,e in enumerate(ends) if e['role']==role)
        target=next(i for i,e in enumerate(ends) if e['role']!=role and e['strand']!=ends[source]['strand'])
        invalid=next(i for i,e in enumerate(ends) if i!=source and e['role']==role)
        if os.environ.get('NADOC_VR_AUDIT_DESIGN'):
            # Dense origami can put a compatible end inside the selection sphere
            # around the old fixture's first same-polarity end. Choose the most
            # isolated same-polarity end from live geometry; retain the original
            # no-target/no-edit assertions and normal controller motion.
            compatible=[e for e in ends if e['role']!=role and e['strand']!=ends[source]['strand']]
            def clearance(index):
                return min(float(np.linalg.norm(np.array(ends[index]['world'])-e['world'])) for e in compatible)
            original=invalid
            invalid=max((i for i,e in enumerate(ends) if i!=source and e['role']==role),key=clearance)
            (out/'negative-target-setup.json').write_text(json.dumps({'source':source,'original_invalid':original,
                'chosen_invalid':invalid,'original_clearance_m':clearance(original),'chosen_clearance_m':clearance(invalid),
                'policy':'Most isolated same-polarity live endpoint; unchanged selection radius, geometry and no-edit assertions'},indent=2))
        # A same-polarity release must not create an edit or leave a held source.
        revision=live.state['scene_revision']
        endpoint(source,lambda s:s['ligation']['hover'][1]==source)
        live.send('button',hand=1,button='trigger',pressed=True);live.frame()
        assert live.state['ligation']['grabbing']
        endpoint(invalid)
        assert live.state['ligation']['target'] is None
        live.capture_to(out/'invalid-preview',discard_source=True)
        live.send('button',hand=1,button='trigger',pressed=False);live.frame()
        assert not live.state['ligation']['grabbing'] and live.state['scene_revision']==revision
        endpoint(source,lambda s:s['ligation']['hover'][1]==source)
        live.send('button',hand=1,button='trigger',pressed=True);live.frame()
        assert live.state['ligation']['grabbing']
        loose=np.array(ends[source]['world'])+[0,.15,.12]
        reach(loose.tolist());assert live.state['ligation']['target'] is None
        live.capture_to(out/'stretched',discard_source=True)
        assert preview(out/'stretched')['passed'], 'Stretched bond pixels missing'
        assert not preview(out/'stretched', offscreen=True)['passed'], 'Offscreen negative control passed'
        endpoint(target,lambda s:s['ligation']['target']==target)
        assert live.state['ligation']['target']==target
        live.capture_to(out/'compatible-preview',discard_source=True)
        assert preview(out/'compatible-preview')['passed'], 'Compatible bond pixels missing'
        version=live.state['ligation']['version']
        with operation(live,'ligation-commit'):
            live.send('button',hand=1,button='trigger',pressed=False)
            wait(lambda s:s['scene_revision']>revision and s['ligation']['version']>version)
        assert live.state['ligation']['status']=='created'
        live.capture_to(out/'committed',discard_source=True)
        assert committed(out/'committed',ends[source]['identity'],ends[target]['identity'])['passed'], 'Saved bond is not visible'
        hold(live,'Forced ligation saved')
        # Canonical IDs are encoded as whole semantic strings. Generated fixture
        # strand IDs have no colons; source selection itself uses the full identity.
        three=ends[source] if role==3 else ends[target]
        five=ends[target] if role==3 else ends[source]
        (out/'result.json').write_text(json.dumps({'three_strand':unquote(three['identity']).split(':')[1],
            'five_strand':unquote(five['identity']).split(':')[1],'state':live.state},indent=2))
    except Exception:
        (out/'failure-state.json').write_text(json.dumps(live.state,indent=2));raise
    finally:
        for button in ('trigger','trackpad','grip'):
            live.send('button',hand=1,button=button,pressed=False)
        live.frame()


if __name__=='__main__':run(*sys.argv[1:])
