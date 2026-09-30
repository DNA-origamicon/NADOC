"""Normal-route on-demand loads; private desktop-style acknowledgements only."""
import json
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image
from backend.api import routes_vr as vr
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.menu_tour import click, scroll_page
from tools.vr_workflows.representation_tour import REPS
from tools.vr_motion.metrics import rotate


def progress_pixels(directory, evidence, identifier):
    control=next(c for c in evidence['state']['controls'] if c.get('id')==identifier)
    counts=[]
    # Project the lower part of the actual clicked button, not a screen-fixed ROI.
    for eye in evidence['eyes']:
        q=eye['orientation_xyzw'];inverse=[-q[0],-q[1],-q[2],q[3]]
        rgb=np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))
        origin=np.asarray(control['position']);r=np.asarray(control['hit_half_right']);u=np.asarray(control['hit_half_up'])
        left,right,up,down=np.tan(eye['fov_left_right_up_down'])
        hits=0
        for y in np.linspace(-.87,-.6,12):
            for x in np.linspace(-.94,.94,160):
                p=rotate(inverse,origin+x*r+y*u-np.asarray(eye['position']))
                px=int((p[0]/-p[2]-left)/(right-left)*eye['width'])
                py=int((up-p[1]/-p[2])/(up-down)*eye['height'])
                if 0<=px<eye['width'] and 0<=py<eye['height']:
                    color=rgb[py,px].astype(float)
                    hits+=bool(color[1]>100 and color[1]>color[0]*1.7 and color[2]>color[0]*1.3)
        counts.append(dict(eye=eye['eye'],bar_samples=hits))
    return counts


def run(live, session, output, validate=False):
    output.mkdir()
    stopping=threading.Event();errors=[];trials=[];results=[]
    def respond():
        last=0
        while not stopping.wait(.02):
            try:
                event=json.loads(Path(session['event_path']).read_text());seq=event.get('style_sequence',0)
                if seq>last and event['representation'] != 'full':
                    # Real browsers may suppress the redundant startup Full ack.
                    # Deliberately omit it: the first ack must apply the chosen style.
                    path=Path(session['visualization_path']);temp=path.with_suffix('.next')
                    temp.write_text(vr._visualization_snapshot_record([],sequence=seq+10,mode='design',view_rotation=np.eye(3),representation=event['representation'],coloring=event['coloring']))
                    temp.replace(path);last=seq
            except (FileNotFoundError,json.JSONDecodeError):
                continue
            except Exception as exc:
                errors.append(str(exc));return
    responder=threading.Thread(target=respond,daemon=True);responder.start()
    try:
        assert live.state['representation']=='full'
        if live.state['sidebars'][0]['open']:live.button('menu',hand=0)
        if not live.state['sidebars'][1]['open']:live.button('menu',hand=1)
        click(live,1,'tab:visualization','steady_fast',trials)
        catalog=json.loads(Path('native/vr_viewer/sidebar_catalog.json').read_text())
        tab=next(t for t in catalog['tabs'] if t['side']=='right' and t['key']=='visualization')
        indices={r['id']:i for i,r in enumerate(tab['rows'])}
        # Every profile has a distinct initially-unloaded representation.
        cases=list(zip(PRESETS,['cylinders','surface','stick','vdw'])) if validate else [('steady_fast','cylinders')]
        for preset,rep in cases:
            identifier=REPS[rep]
            for _ in range(30):
                if any(c.get('id')==identifier for c in live.state['controls']):break
                scroll_page(live,1,-1 if indices[identifier]<live.state['sidebars'][1]['offset'] else 1)
            before=live.state['representation'];start=time.monotonic();samples=[];capture=None;fallback_capture=None
            click(live,1,identifier,preset,trials)
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                live.frame();p=live.state['representation_loading']
                samples.append(dict(seconds=time.monotonic()-start,frame=live.state['frame'],lightweight=live.state['loading_diagnostics']['lightweight_guard'],**p))
                assert p['phase']!='error',p
                if p['pending'] and p['percent']<99:
                    assert live.state['representation']==before,'Previous model must remain active while loading'
                if capture is None and p['pending'] and 10<p['percent']<95:
                    capture=output/(preset+'-'+rep+'-loading')
                    evidence,_=live.capture_to(capture,files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'],discard_source=True)
                    for eye in ('left','right'):
                        assert (np.fromfile(capture/(eye+'.classes.u8'),np.uint8)==1).sum()>100, 'Loading must retain visible model pixels'
                    pixels=progress_pixels(capture,evidence,identifier)
                    assert all(row['bar_samples']>20 for row in pixels),pixels
                    # A blank button must fail this color/position check.
                    from unittest.mock import patch
                    with patch('tools.vr_workflows.lazy_representation_check.Image.open',return_value=Image.new('RGB',(evidence['eyes'][0]['width'],evidence['eyes'][0]['height']))):
                        assert not any(row['bar_samples'] for row in progress_pixels(capture,evidence,identifier))
                if fallback_capture is None and p['pending'] and live.state['loading_diagnostics']['lightweight_guard']:
                    fallback_capture=output/(preset+'-'+rep+'-point-fallback')
                    evidence,_=live.capture_to(fallback_capture,files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'],discard_source=True)
                    for eye in ('left','right'):
                        assert (np.fromfile(fallback_capture/(eye+'.classes.u8'),np.uint8)==1).sum()>100, 'Frame guard must retain model pixels'
                if live.state['representation']==rep and not p['pending']:break
                time.sleep(.04)
            assert live.state['representation']==rep and not live.state['representation_loading']['pending'],samples[-1]
            assert capture is not None,'Loading bar was not captured'
            percentages=[s['percent'] for s in samples]
            assert percentages==sorted(percentages),percentages
            assert percentages[-1]==100
            assert samples[-1]['frame']>samples[0]['frame']+5
            ready=output/(preset+'-'+rep+'-ready')
            evidence,_=live.capture_to(ready,files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','evidence.json'],discard_source=True)
            for eye in ('left','right'):
                assert (np.fromfile(ready/(eye+'.classes.u8'),np.uint8)==1).sum()>100
            results.append(dict(preset=preset,representation=rep,seconds=time.monotonic()-start,pixels=pixels,samples=samples))
            (output/'results.json').write_text(json.dumps(results,indent=2))
        assert not errors,errors
        from tools.vr_motion.desktop_check import run as desktop_check
        desktop=desktop_check(live.bridge.socket_path,output/'desktop',live=live,reveal=True)
        assert desktop['passed'],desktop
        return results
    finally:
        stopping.set();responder.join(timeout=2)
        (output/'reaches.json').write_text(json.dumps(trials,indent=2))
        live.release()
