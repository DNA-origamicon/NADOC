"""Optional representation setup for existing physical authoring probes."""
import os
import time
from tools.vr_workflows.menu_tour import click, scroll_page
from tools.vr_workflows.representation_tour import REPS, ROOT
import json
from pathlib import Path


def prepare(live, *, via_feedback=False):
    rep=os.environ.get('NADOC_VR_AUDIT_REPRESENTATION')
    if not rep: return
    if rep not in ('full','stick','ballstick','surface'): raise ValueError(rep)
    path=os.environ.get('NADOC_VR_AUDIT_INTERVALS')
    record=Path(path).with_name('representation-setup.json') if path else None
    if record and record.exists():
        previous=json.loads(record.read_text())
        if previous.get('session')==live.session and previous.get('passed'): return
    trials=[]
    try:
        if os.environ.get("NADOC_VR_AUDIT_DESIGN"):
            from tools.vr_workflows.menu_tour import enlarge_mirror
            enlarge_mirror(live)
            trials.append({"observation":"enlarged owned mirror to primary monitor; eye rendering unchanged"})
        if via_feedback:_feedback(live,rep,trials)
        else:_prepare(live,rep,trials)
        if os.environ.get('NADOC_VR_AUDIT_DESIGN'):
            # Compare the same live tool scene without per-frame inspector IPC.
            # No controller command or capture occurs inside this interval.
            from tools.vr_workflows.audit_intervals import operation
            time.sleep(1)
            with operation(live,'stationary-after-representation'):
                time.sleep(3)
            if os.environ.get('NADOC_VR_AUDIT_PROFILE','steady_fast')=='steady_fast':
                with operation(live,'stationary-observed'):
                    until=time.monotonic()+3
                    while time.monotonic()<until:live.frame()
    except Exception as error:
        if record: record.write_text(json.dumps(dict(session=live.session,requested=rep,passed=False,error=str(error),trials=trials),indent=2))
        raise
    if record: record.write_text(json.dumps(dict(session=live.session,requested=rep,passed=True,trials=trials),indent=2))


def _prepare(live,rep,trials):
    def setup_click(identifier):
        if not os.environ.get('NADOC_VR_AUDIT_DESIGN'):
            return click(live,1,identifier,'steady_fast',trials)
        # Setup is not a motion trial. Pad navigation uses the production menu
        # event and desktop acknowledgement, keeping both renderers consistent.
        from tools.vr_workflows.menu_focus_check import seek
        seek(live,1,identifier)
        live.button('trigger',hand=1);live.frame()
        trials.append({'setup':'production trackpad focus + trigger','control':identifier})
    deadline=time.monotonic()+120
    while live.state.get('startup',{}).get('active') and time.monotonic()<deadline:
        live.frame();time.sleep(.05)
    if live.state.get('startup',{}).get('active'): raise RuntimeError('Audit startup timed out')
    if live.state['representation']==rep and not live.state['representation_loading']['pending']: return
    was_open=live.state['sidebars'][1]['open']
    head=live.state['head_position']
    live.send('pose',hand=1,position=[head[0]+.3,head[1]-.3,head[2]-.3],orientation=[0,0,0,1])
    live.frame()
    if not was_open: live.button('menu',hand=1)
    restore_move=live.state['sidebars'][1]['tab']=='move'
    if restore_move: setup_click('move:back')
    setup_click('tab:visualization')
    catalog=json.loads((ROOT/'native/vr_viewer/sidebar_catalog.json').read_text())
    tab=next(t for t in catalog['tabs'] if t['side']=='right' and t['key']=='visualization')
    indices={r['id']:i for i,r in enumerate(tab['rows'])}
    for _ in range(30):
        if any(c.get('id')==REPS[rep] for c in live.state['controls']): break
        scroll_page(live,1,-1 if indices[REPS[rep]]<live.state['sidebars'][1]['offset'] else 1)
    setup_click(REPS[rep])
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        live.frame()
        if live.state['representation']==rep and not live.state['representation_loading']['pending']: break
        time.sleep(.1)
    else: raise RuntimeError('Audit representation did not become ready: '+rep)
    if restore_move:
        setup_click('tab:tools')
        setup_click('tool-move')
    if live.state['sidebars'][1]['input_mode']=='trackpad':
        from tools.vr_workflows.menu_focus_check import pad
        pad(live,1)
    if not was_open: live.button('menu',hand=1)
    time.sleep(2)


def wait_startup(live):
    deadline=time.monotonic()+120
    while live.state.get('startup',{}).get('active'):
        if time.monotonic()>deadline:raise RuntimeError('Audit startup timed out')
        live.frame();time.sleep(.05)


def _feedback(live,rep,trials):
    import urllib.request
    wait_startup(live)
    base=os.environ['NADOC_E2E_API_BASE']
    with urllib.request.urlopen(base+'/api/vr/status') as response:status=json.load(response)
    if status.get('scrywrite_socket')!=live.bridge.socket_path:raise RuntimeError('Audit viewer ownership changed')
    style_url=os.environ.get('NADOC_VR_AUDIT_STYLE_URL')
    if os.environ.get('NADOC_VR_AUDIT_DESIGN') and not style_url:
        raise RuntimeError('Full-size deformation audit requires the owned desktop style bridge')
    request=urllib.request.Request(style_url or base+'/api/vr/visualization-feedback',data=json.dumps({'representation':rep}).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=120) as response:json.load(response)
    trials.append({'setup':'desktop native-style handler through owned Playwright bridge' if style_url else 'production visualization-feedback','representation':rep})
    deadline=time.monotonic()+180
    while live.state['representation']!=rep or live.state['representation_loading']['pending']:
        if time.monotonic()>deadline:raise RuntimeError('Audit representation did not become ready: '+rep)
        live.frame();time.sleep(.05)
    time.sleep(2)
