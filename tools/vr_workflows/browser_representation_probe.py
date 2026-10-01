"""ScryWrite input and stereo evidence; the real browser owns all acknowledgements."""
import argparse
import os
import json
import time
import copy
from pathlib import Path

from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import PRESETS
from tools.vr_workflows.menu_tour import click as menu_click, scroll_page
from tools.vr_workflows.representation_tour import REPS


def click(live, hand, identifier, preset, trials):
    # Loading is the oracle here. Preserve failed timing trials, release no
    # synthetic click, and begin a new measured reach after a transport stall.
    # Never loosen the motion runner's deadline or call a late reach successful.
    for attempt in range(3):
        try:
            return menu_click(live, hand, identifier, preset, trials)
        except TimeoutError as error:
            trials.append(dict(side=hand, control=identifier, preset=preset,
                               hit=False, timingFailure=str(error), retry=attempt+1))
            print('Reach timing failure (retained): '+str(error), flush=True)
            if attempt == 2:
                raise
            time.sleep(2)
            live.frame()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    bridge = Bridge(args.socket)
    readiness = []
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        observed = bridge.call('scrywrite_observe', {})
        readiness.append(dict(wall_time_ms=time.time()*1000, focused=observed.get('focused'), session_state=observed.get('session_state')))
        if observed.get('focused'):
            break
        time.sleep(.1)
    (args.output/'readiness.json').write_text(json.dumps(readiness, indent=2))
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    motion_reference = None
    trials, results = [], []
    motion_failures = []
    try:
        startup_samples = []
        deadline = time.monotonic()+90
        while live.state['startup']['active'] and time.monotonic()<deadline:
            live.frame()
            startup_samples.append(dict(wall_time_ms=time.time()*1000, frame=live.state['frame'], startup=live.state['startup']))
            time.sleep(.05)
        (args.output/'startup.json').write_text(json.dumps(startup_samples, indent=2))
        assert not live.state['startup']['active']
        motion_reference = copy.deepcopy(live.state)
        head = live.state['head_position']
        live.send('pose', hand=1, position=[head[0]+.3, head[1]-.3, head[2]-.3], orientation=[0,0,0,1])
        live.frame()
        if not live.state['sidebars'][1]['open']:
            live.button('menu', hand=1)
        click(live, 1, 'tab:visualization', 'steady_fast', trials)
        catalog=json.loads(Path('native/vr_viewer/sidebar_catalog.json').read_text())
        tab=next(t for t in catalog['tabs'] if t['side']=='right' and t['key']=='visualization')
        indices={r['id']:i for i,r in enumerate(tab['rows'])}
        for index, preset in enumerate(PRESETS if args.validate else ['steady_fast']):
            from tools.vr_workflows.sidebar_scroll_probe import check
            if not os.environ.get('NADOC_VR_MOTION_CHECK') or index == 0:
                check(live,args.output,preset,trials)
            for rep in (os.environ.get('NADOC_VR_TEST_REPS','surface,hull-prism,cylinders,beads,ballstick,vdw,stick,mrdna-coarse,mrdna-fine,oxdna,full,cylinders').split(',') if index == 0 else os.environ.get('NADOC_VR_TEST_MATRIX_REPS','full,surface,cylinders').split(',')):
                for _ in range(25):
                    if any(c.get('id')==REPS[rep] for c in live.state['controls']):break
                    scroll_page(live,1,-1 if indices[REPS[rep]]<live.state['sidebars'][1]['offset'] else 1)
                # Style acknowledgements precede delayed desktop-view uploads.
                # Let those uploads settle outside the measured controller reach.
                time.sleep(3)
                live.frame()
                print('Selecting '+rep,flush=True)
                already_active=live.state['representation']==rep and not live.state['representation_loading']['pending']
                if not already_active or not os.environ.get('NADOC_VR_MOTION_CHECK'):
                    click(live, 1, REPS[rep], preset, trials)
                samples = []
                deadline = time.monotonic()+180
                while time.monotonic()<deadline:
                    sample_started=time.monotonic()
                    live.frame()
                    sample={key: live.state[key] for key in ('frame','representation','representation_loading','visualization_sequence')}
                    sample.update(loading_diagnostics=live.state.get("loading_diagnostics"),wall_time_ms=time.time()*1000,observe_ms=(time.monotonic()-sample_started)*1000)
                    samples.append(sample)
                    if live.state['representation']==rep and not live.state['representation_loading']['pending']:
                        break
                    # Native tracing samples every XR frame. Full semantic RPC
                    # snapshots are more expensive; keep their progress polling
                    # separate from the unchanged 20 Hz controller motion.
                    time.sleep(float(os.environ.get('NADOC_VR_LOADING_POLL_SECONDS', '.1')))
                results.append(dict(preset=preset, target=rep, control=REPS[rep], samples=samples))
                print(json.dumps(samples[-1]),flush=True)
                assert live.state['representation']==rep, samples[-1]
                assert already_active or live.state['representation_loading']['percent']==100, samples[-1]
                settle=[]
                until=time.monotonic()+float(os.environ.get('NADOC_VR_POST_READY_SECONDS','0'))
                while time.monotonic()<until:
                    sample_started=time.monotonic()
                    live.frame()
                    settle.append(dict(wall_time_ms=time.time()*1000,observe_ms=(time.monotonic()-sample_started)*1000,frame=live.state['frame'],visualization_sequence=live.state['visualization_sequence']))
                    time.sleep(.04)
                results[-1]['post_ready_samples']=settle
                destination=args.output/(preset+'-'+rep+'-'+str(len(results)))
                live.capture_to(destination, files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','left.ids.u32','right.ids.u32','objects.json','evidence.json'], discard_source=True)
                import numpy as np
                for eye in ('left','right'):
                    classes=np.fromfile(destination/(eye+'.classes.u8'),np.uint8)
                    ids=np.fromfile(destination/(eye+'.ids.u32'),np.uint32)
                    assert ((classes==1)&(ids>0)).sum()>100, 'No visible '+rep+' geometry in '+eye
                if os.environ.get('NADOC_VR_MOTION_CHECK'):
                    from tools.vr_workflows.representation_motion import check as check_motion
                    from tools.vr_workflows.motion_delivery import frame_broadside, sweep
                    try:
                        framing = frame_broadside(live, motion_reference)
                        (args.output/(preset+'-'+rep+'-framing.json')).write_text(json.dumps(framing, indent=2))
                        # Captures stall the GPU. Keep them out of the measured
                        # steady-state delivery interval and let pacing recover.
                        time.sleep(15)
                        check_motion(live,args.output/(preset+'-'+rep+'-motion'),preset)
                        if index == 0:
                            time.sleep(15)
                            sweep(live,args.output/(preset+'-'+rep+'-speeds'))
                    except TimeoutError as error:
                        motion_failures.append(dict(preset=preset,representation=rep,error=str(error)))
                        print('Grip timing failure (retained): '+str(error),flush=True)
                    # Restore the menu for the next style selection.
                    if not live.state['sidebars'][1]['open']:
                        head = live.state['head_position']
                        live.send('pose',hand=1,position=[head[0]+.3,head[1]-.3,head[2]-.3],orientation=[0,0,0,1])
                        live.frame()
                        live.button('menu', hand=1)
            live.capture_to(args.output/preset, files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','left.ids.u32','right.ids.u32','objects.json','evidence.json'], discard_source=True)
            import numpy as np
            for eye in ('left', 'right'):
                classes=np.fromfile(args.output/preset/(eye+'.classes.u8'), dtype=np.uint8)
                ids=np.fromfile(args.output/preset/(eye+'.ids.u32'), dtype=np.uint32)
                assert ((classes==1) & (ids>0)).sum()>100, 'No identifiable model pixels in '+eye
        if motion_failures:
            raise AssertionError('Grip timing failures: '+json.dumps(motion_failures))
        print(json.dumps({'passed': True, 'profiles': len(results), 'representation': live.state['representation']}))
    finally:
        (args.output/'results.json').write_text(json.dumps(results, indent=2))
        (args.output/'reaches.json').write_text(json.dumps(trials, indent=2))
        live.release()


if __name__ == '__main__':
    main()
