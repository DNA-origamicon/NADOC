"""ScryWrite input and stereo evidence; the real browser owns all acknowledgements."""
import argparse
import os
import json
import time
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
    live = LiveSession(Bridge(args.socket), physical=True, allow_transactions=True)
    trials, results = [], []
    try:
        deadline = time.monotonic()+90
        while live.state['startup']['active'] and time.monotonic()<deadline:
            live.frame()
            time.sleep(.05)
        assert not live.state['startup']['active']
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
                click(live, 1, REPS[rep], preset, trials)
                samples = []
                deadline = time.monotonic()+180
                while time.monotonic()<deadline:
                    live.frame()
                    samples.append({key: live.state[key] for key in ('frame','representation','representation_loading','visualization_sequence')})
                    if live.state['representation']==rep and not live.state['representation_loading']['pending']:
                        break
                    time.sleep(.04)
                results.append(dict(preset=preset, target=rep, control=REPS[rep], samples=samples))
                print(json.dumps(samples[-1]),flush=True)
                assert live.state['representation']==rep, samples[-1]
                assert already_active or live.state['representation_loading']['percent']==100, samples[-1]
                destination=args.output/(preset+'-'+rep+'-'+str(len(results)))
                live.capture_to(destination, files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','left.ids.u32','right.ids.u32','objects.json','evidence.json'], discard_source=True)
                import numpy as np
                for eye in ('left','right'):
                    classes=np.fromfile(destination/(eye+'.classes.u8'),np.uint8)
                    ids=np.fromfile(destination/(eye+'.ids.u32'),np.uint32)
                    assert ((classes==1)&(ids>0)).sum()>100, 'No visible '+rep+' geometry in '+eye
            live.capture_to(args.output/preset, files=['left.png','right.png','mirror.png','left.classes.u8','right.classes.u8','left.ids.u32','right.ids.u32','objects.json','evidence.json'], discard_source=True)
            import numpy as np
            for eye in ('left', 'right'):
                classes=np.fromfile(args.output/preset/(eye+'.classes.u8'), dtype=np.uint8)
                ids=np.fromfile(args.output/preset/(eye+'.ids.u32'), dtype=np.uint32)
                assert ((classes==1) & (ids>0)).sum()>100, 'No identifiable model pixels in '+eye
        print(json.dumps({'passed': True, 'profiles': len(results), 'representation': live.state['representation']}))
    finally:
        (args.output/'results.json').write_text(json.dumps(results, indent=2))
        (args.output/'reaches.json').write_text(json.dumps(trials, indent=2))
        live.release()


if __name__ == '__main__':
    main()
