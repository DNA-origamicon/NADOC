"""Production right-menu input while the focused simulation menu stays open."""
import json
import time
import numpy as np
from tools.vr_workflows.menu_tour import click, scroll_page
from tools.vr_workflows.representation_tour import REPS, ROOT
from tools.vr_motion.metrics import rotate

ALLOWED = {'full','vdw','ballstick','stick','oxdna','mrdna-coarse','mrdna-fine'}


def run(live, out, identifier, preset, trials, socket):
    if identifier.startswith('review:'):
        rep=identifier.split(':',1)[1]
        deadline=time.monotonic()+120
        while (live.state['representation'] != rep or live.state.get('representation_loading',{}).get('pending')) and time.monotonic()<deadline:
            live.frame();time.sleep(.05)
        assert live.state['representation']==rep
        assert all(s['open'] for s in live.state['sidebars'])
        time.sleep(1);live.frame()
        evidence,_=live.capture_to(out/'after',files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'],discard_source=True)
        for eye in ('left','right'):
            pixels=np.fromfile(out/'after'/(eye+'.classes.u8'),np.uint8)
            assert (pixels==1).sum()>100, 'No rendered simulation in '+eye
        from tools.vr_workflows.menu_pixels import check
        pixels=check(out/'after',evidence)
        (out/'pixels.json').write_text(json.dumps(pixels,indent=2))
        assert pixels['passed'], 'Menu controls are not visible in both submitted eyes'
        if rep=='full':
            from tools.vr_motion.desktop_check import run as desktop_check
            delivered=desktop_check(socket, out/'desktop',live=live,reveal=True)
            (out/'delivery.json').write_text(json.dumps(delivered,indent=2))
            assert delivered['passed'], delivered
        return
    if not live.state['sidebars'][1]['open']:
        evidence, _ = live.capture_to(out/'anchor', files=['evidence.json'], discard_source=True)
        eye = evidence['eyes'][0]
        head = np.mean([e['position'] for e in evidence['eyes']], axis=0)
        # Move the result above both tablets using ordinary scene grip. This
        # observation adjustment leaves menu size and all motion presets intact.
        presentation=live.state['presentation']
        center=(np.array(presentation['model_to_tracking_rows']) @ np.r_[presentation['normalized_offset_model'],1])[:3]
        target=head+rotate(eye['orientation_xyzw'],[.1,.75,-1.35])
        grab=head+rotate(eye['orientation_xyzw'],[.9,.7,-.8])
        live.send('pose',hand=1,position=grab.tolist(),orientation=[0,0,0,1]);live.frame()
        live.send('button',hand=1,button='grip',pressed=True);live.frame()
        live.send('pose',hand=1,position=(grab+target-center).tolist(),orientation=[0,0,0,1]);live.frame()
        live.send('button',hand=1,button='grip',pressed=False);live.frame()
        scale_ratio=1
        if not (out.parent/'representation-placement.json').exists():
            q=eye['orientation_xyzw']
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
            assert after_scale>before_scale*1.8, 'Observation enlargement did not acquire scene grips'
            for h in (0,1):live.send('button',hand=h,button='grip',pressed=False)
            live.frame()
            scale_ratio=after_scale/before_scale
        placement={'before':presentation,'after':live.state['presentation'],'target':target.tolist(),'scale_ratio':scale_ratio}
        (out/'placement.json').write_text(json.dumps(placement,indent=2))
        if not (out.parent/'representation-placement.json').exists():
            (out.parent/'representation-placement.json').write_text(json.dumps(placement,indent=2))
        live.send('pose', hand=1, position=(head+rotate(eye['orientation_xyzw'],[.4,-.1,-.5])).tolist(), orientation=eye['orientation_xyzw'])
        live.frame()
        live.button('menu',hand=1);live.frame()
    click(live,1,'tab:visualization',preset,trials)
    deadline=time.monotonic()+2
    while time.monotonic()<deadline:live.frame();time.sleep(.05)
    assert all(s['open'] for s in live.state['sidebars']), 'Simulation refresh closed a menu'
    rep=identifier.split(':',1)[1]
    catalog=json.loads((ROOT/'native/vr_viewer/sidebar_catalog.json').read_text())
    rows=next(t['rows'] for t in catalog['tabs'] if t['side']=='right' and t['key']=='visualization')
    indices={r['id']:i for i,r in enumerate(rows)}
    def reveal(control):
        for _ in range(30):
            item=next((c for c in live.state['controls'] if c.get('id')==control and c.get('sidebar')=='right'),None)
            if item:return item
            scroll_page(live,1,-1 if indices[control]<live.state['sidebars'][1]['offset'] else 1)
        raise AssertionError('Missing control '+control)
    if rep in ('availability','native'):
        for style, control in REPS.items():
            item=reveal(control)
            assert item['enabled']==(style in ALLOWED or rep=='native'), (style,item['enabled'])
    else:
        assert reveal(REPS[rep])['enabled']
        click(live,1,REPS[rep],preset,trials)
    live.capture_to(out/'after',files=['left.png','right.png','mirror.png','evidence.json'],discard_source=True)
    (out/'result.json').write_text(json.dumps(live.state,indent=2))
