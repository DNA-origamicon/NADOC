"""Production VR compact tabs: matched seeded reaches, no retries or endpoint snaps."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import rotate
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.profile_input import reach_target, aim_orientation
from tools.vr_workflows.control_approach import control_approach
from tools.vr_workflows.menu_tour import find_control, acquired, enlarge_mirror
from tools.vr_workflows.menu_pixels import check as check_pixels


def settle(live, seconds=.25):
    time.sleep(seconds)
    live.frame()


def summarize(trials):
    hits=sum(t['hit'] for t in trials)
    selections=sum(t['clicked'] and t['after']==t['target'][4:] for t in trials)
    return {'trials':len(trials),'hits':hits,'misses':len(trials)-hits,
            'hit_rate':hits/len(trials) if trials else 0,
            'acquisition_hits':sum(t['acquired'] for t in trials),
            'selection_hits':selections,'selection_misses':len(trials)-selections,
            'selection_hit_rate':selections/len(trials) if trials else 0,
            'non_tab_endpoints':sum(not t['clicked'] for t in trials),
            'wrong_tab_activations':sum(t['wrong_tab'] for t in trials)}


def capture(live, output, name):
    directory=output/name
    evidence,_=live.capture_to(directory,files=['left.png','right.png','mirror.png','evidence.json'],discard_source=True)
    evidence['state']['controls']=[c for c in evidence['state']['controls'] if c.get('id','').startswith('tab:')]
    pixels=check_pixels(directory,evidence)
    (output/(name+'-pixels.json')).write_text(json.dumps(pixels,indent=2)+'\n')
    if not pixels['passed']:
        raise AssertionError(f'Tab stereo pixels failed: {name}; see pixel summary')
    # Same geometry against blank eye images must fail every tab region.
    from PIL import Image
    negative=directory/'negative';negative.mkdir()
    for eye in evidence['eyes']:
        Image.new('RGB',(eye['width'],eye['height'])).save(negative/(eye['eye']+'.png'))
    blank=check_pixels(negative,evidence)
    assert not blank['passed'] and all(not row['passed'] for row in blank['controls'])
    (output/(name+'-negative.json')).write_text(json.dumps({'passed':True,'rejected_regions':len(blank['controls'])})+'\n')
    return evidence


def run_profile(live, catalog, eye, output, preset, repeats):
    q=eye['orientation_xyzw'];head=eye['position'];trials=[]
    def world(offset):return [a+b for a,b in zip(head,rotate(q,offset))]
    home=world([.22,-.12,-.25])
    def park():
        live.send('pose',hand=1,position=home,orientation=q)
        live.frame()
    def point_at(side, identifier):
        for _ in range(3):
            c=find_control(live,side,identifier)
            origin=control_approach(c,home)
            live.send('pose',hand=1,position=origin,orientation=aim_orientation(origin,c['position']))
            live.frame();settle(live)
        assert live.state['sidebars'][side]['hover_id']==identifier
    for side in (0,1):
        # Place one ordinary controller-spawned menu at a time using observed
        # placement feedback. Keep real HMD tracking, default tilt and .45 scale.
        for hand in (0,1):
            if live.state['sidebars'][hand]['open']:live.button('menu',hand=hand)
        wrist=world([0,0,-.25])
        live.send('pose',hand=side,position=wrist,orientation=q);live.frame();live.button('menu',hand=side)
        actual=live.state['sidebars'][side]['position']
        desired=world([0,0,-.65])
        wrist=[p+d-a for p,d,a in zip(wrist,desired,actual)]
        live.button('menu',hand=side)
        live.send('pose',hand=side,position=wrist,orientation=q);live.frame();live.button('menu',hand=side)
        park();settle(live)
        targets=[c['id'] for c in live.state['controls'] if c.get('sidebar')==('left' if side==0 else 'right') and c['id'].startswith('tab:')]
        expected=['tab:'+t['key'] for t in catalog['tabs'] if t['side']==('left' if side==0 else 'right') and t['key']!='assembly']
        assert targets==expected,(targets,expected)
        for repeat in range(repeats):
            for index,identifier in enumerate(targets):
                # Deterministic precondition through production pointer input,
                # outside the measured reach. Follow setup geometry to its settled
                # center; measured profiles below never receive this correction.
                baseline=targets[(index+3)%len(targets)]
                park()
                point_at(side,baseline)
                live.button('trigger',hand=1)
                assert live.state['sidebars'][side]['tab']==baseline[4:]
                park();settle(live)
                assert live.state['sidebars'][side]['input_mode']=='pointer'
                control=find_control(live,side,identifier)
                seed=8100+side*1000+repeat*100+index
                trial=reach_target(live,control['position'],preset,seed,
                    target_position=control_approach(control,home),
                    acquired=lambda state:acquired(state,side,identifier))
                stable=trial['acquired_with_feedback'] and acquired(live.state,side,identifier)
                before=live.state['sidebars'][side]['tab']
                end_hover=live.state['sidebars'][side]['hover_id']
                # A miss must not activate arbitrary menu content in the empty fixture.
                clicked=end_hover.startswith('tab:')
                if clicked:live.button('trigger',hand=1)
                after=live.state['sidebars'][side]['tab']
                hit=bool(stable and clicked and after==identifier[4:])
                samples=trial['samples']
                trials.append({'preset':preset,'side':side,'target':identifier,'seed':seed,
                    'acquired':bool(stable),'hit':hit,'clicked':clicked,'wrong_tab':bool(clicked and after!=identifier[4:]),
                    'before':before,'after':after,'end_hover':end_hover,
                    'hover_samples':sum(s['target_hover'] for s in samples),'samples':len(samples),
                    'max_lag_s':max(s['lag_s'] for s in samples),
                    'target_position':control['position'],'target_half_right':control['hit_half_right'],
                    'target_half_up':control['hit_half_up'],
                    'end_position':samples[-1]['actual']['position'],
                    'end_orientation':samples[-1]['actual']['orientation_xyzw']})
                (output/'trials.json').write_text(json.dumps(trials,indent=2)+'\n')
                print(f'{preset} {side}/{identifier} seed={seed}: {"HIT" if hit else "MISS"} hover={end_hover}',flush=True)
        # Untimed visual review: two long labels, one selected and one hovered.
        longest=sorted(targets,key=lambda identifier:len(find_control(live,side,identifier)['label']),reverse=True)
        park();point_at(side,longest[0]);live.button('trigger',hand=1)
        point_at(side,longest[1]);settle(live)
        capture(live,output,f'side-{side}')
    result=summarize(trials)
    (output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.repeats<=20:parser.error('repeats must be 1..20')
    root=Path(__file__).resolve().parents[2]
    base=root/'.development-artifacts/vr-compact-tabs'
    archive=Path('/media/jojo/Archive')
    if not archive.is_mount() or (root/'.development-artifacts').resolve().stat().st_dev!=archive.stat().st_dev:
        raise RuntimeError('Mounted Archive storage required')
    scratch=base/'tmp';scratch.mkdir(parents=True,exist_ok=True)
    os.environ['TMPDIR']=str(scratch);tempfile.tempdir=str(scratch)
    os.environ.setdefault('NADOC_VR_BUILD_DIR',str(root/'.development-artifacts/vr-simulation-menu-round1/build'))
    from backend.api.routes_vr import _ensure_viewer_built, _start_steamvr, _build_environment, _VIEWER
    from backend.api.routes_vr_tours import _viewer_active
    if _viewer_active():raise RuntimeError('Close the existing viewer before starting the isolated compact-tab tour')
    _ensure_viewer_built();_start_steamvr()
    output=args.output or base/time.strftime('run-%Y%m%d-%H%M%S')
    output.mkdir(parents=True,exist_ok=False)
    catalog=json.loads((root/'native/vr_viewer/sidebar_catalog.json').read_text())
    live=None;results={}
    with tempfile.TemporaryDirectory(prefix='tabs-',dir=scratch) as temp:
        socket=str(Path(temp)/'viewer.sock')
        command=[str(_VIEWER),str(root/'native/vr_viewer/examples/empty_authoring.nadocvr'),
            '--scrywrite-live',socket,'--scrywrite-live-mode','control','--mirror-eye','left','--reference-grid','off']
        with (output/'viewer.log').open('w') as log:proc=subprocess.Popen(command,env=_build_environment(),stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+60
            while True:
                try:live=LiveSession(Bridge(socket_path=socket),physical=True);break
                except (OSError,RuntimeError,ValueError):
                    if proc.poll() is not None or time.monotonic()>deadline:raise
                    time.sleep(.2)
            enlarge_mirror(live)
            evidence,_=live.capture_to(output/'anchor',files=['evidence.json'],discard_source=True)
            eye=evidence['eyes'][0]
            for preset in list(PRESETS) if args.validate else ['steady_fast']:
                destination=output/preset;destination.mkdir()
                results[preset]=run_profile(live,catalog,eye,destination,preset,args.repeats)
                print(preset,json.dumps(results[preset]),flush=True)
                (output/'summary.json').write_text(json.dumps({'profiles':results,'policy':'one matched seeded reach per trial; no retries; stable acquisition AND correct activation required',
                    'synthetic_uncalibrated':True,'assembly':'excluded: Part fixture','panel_scale':.45,'placement':'one menu centered at 0.65 m, normal controller tilt'},indent=2)+'\n')
        finally:
            if live:
                try:live.release()
                except (OSError,RuntimeError):pass
            if proc.poll() is None:
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill();proc.wait()
            # Captures are transient; retain trial outcomes and pixel summaries.
            removed=0
            for name in ['anchor',*[f'{p}/side-{s}' for p in PRESETS for s in (0,1)]]:
                folder=output/name
                if folder.exists():
                    removed+=sum(p.stat().st_size for p in folder.rglob('*') if p.is_file());shutil.rmtree(folder)
            (output/'cleanup.json').write_text(json.dumps({'removed_capture_bytes':removed,'viewer_stopped':proc.poll() is not None})+'\n')


if __name__=='__main__':main()
