"""Isolated native component gallery; desktop uses identical meshes and controls."""
import argparse
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from tools.vr_workflows.tour_catalog import ROOT


def validate(live, output):
    from tools.vr_motion.presets import PRESETS
    from tools.vr_workflows.profile_input import reach_target
    from tools.vr_motion.metrics import rotate
    from tools.vr_workflows.gallery_pixels import check as check_pixels
    results = []

    def acquire(target, preset, destination, acquired, label):
        for attempt in range(3):
            trial = reach_target(live, target, preset, 7120+len(results),
                target_position=destination, acquired=acquired)
            trial.update(target_label=label, attempt=attempt+1)
            results.append(trial)
            if trial['acquired_with_feedback']:
                return
            print(f'{preset}: {label} acquisition {attempt+1} missed; retained in trials', flush=True)
        raise AssertionError(f'{preset}: {label} not acquired after three profile reaches')

    try:
        for preset in ['steady_fast', *[p for p in PRESETS if p != 'steady_fast']]:
            print(f'Validating {preset}', flush=True)
            live.frame()
            reset = live.state['component_gallery']['buttons'][1]['position']
            orientation = live.state['component_gallery']['orientation_xyzw']
            normal = rotate(orientation, [0, 0, .3])
            acquire(reset, preset, [p+n for p,n in zip(reset,normal)],
                    lambda s: s['component_gallery']['buttons'][1]['hovered'], 'reset')
            live.button('trigger')
            if live.state['component_gallery']['component'] in ('buttons','cards','lists'):
                for index in range(6):
                    target=live.state['component_gallery']['samples'][index]['position']
                    acquire(target,preset,[p+n for p,n in zip(target,normal)],
                            lambda s: s['component_gallery']['samples'][index]['hovered'],f'button {index}')
                    before=live.state['component_gallery']['samples'][index]['clicks']
                    live.send('button',hand=1,button='trigger',pressed=True);live.frame()
                    assert live.state['component_gallery']['samples'][index]['state']=='PRESSED'
                    live.send('button',hand=1,button='trigger',pressed=False);live.frame()
                    assert live.state['component_gallery']['samples'][index]['clicks']==before+1
                    if live.state['component_gallery']['component']=='lists':
                        sample=live.state['component_gallery']['samples'][index]
                        assert sample['selected']==0
                        for control in (2,10):
                            target=sample['controls'][control]
                            acquire(target,preset,[p+n for p,n in zip(target,normal)],
                                    lambda s:s['component_gallery']['samples'][index]['hovered_control']==control,f'list {index} control {control}')
                            live.button('trigger')
                        sample=live.state['component_gallery']['samples'][index]
                        assert sample['offset']==1 and sample['selected']==0
                        if index in (1,3):
                            assert sample['items'][0]['value']==21
                        else:
                            assert sample['items'][0]['pinned']
                    if live.state['component_gallery']['component']=='cards':
                        assert live.state['component_gallery']['samples'][index]['open']
                        time.sleep(.3);live.frame()
                        child=live.state['component_gallery']['samples'][index]['children'][0]
                        acquire(child,preset,[p+n for p,n in zip(child,normal)],
                                lambda s:s['component_gallery']['samples'][index]['hovered_row']==1,f'child {index}')
                        live.button('trigger')
                        assert live.state['component_gallery']['samples'][index]['selected']==1
            else:
                for index in (0, 4, 8):
                    live.frame()
                    target = live.state['component_gallery']['wheels'][index]['position']
                    up = rotate(orientation, [0, .14, 0])
                    start = [p+n for p,n in zip(target,normal)]
                    acquire(target, preset, start,
                            lambda s: s['component_gallery']['wheels'][index]['hovered'], f'wheel {index}')
                    before = live.state['component_gallery']['wheels'][index]['value']
                    live.send('button', hand=1, button='trigger', pressed=True)
                    live.frame()
                    assert live.state['component_gallery']['wheels'][index]['dragging']
                    pose = live.state['hands'][1]
                    end = [p+u for p,u in zip(pose['position'],up)]
                    drag = reach_target(live, target, preset, 9210+len(results), target_position=end,
                                        target_orientation=pose['orientation_xyzw'])
                    results.append(drag)
                    live.send('button', hand=1, button='trigger', pressed=False)
                    live.frame()
                    after = live.state['component_gallery']['wheels'][index]['value']
                    assert after > before, (preset,index,before,after)
            capture = output/preset
            evidence, _ = live.capture_to(capture, files=['left.png','right.png','evidence.json'], discard_source=True)
            pixels = check_pixels(capture, evidence)
            (capture/'pixels.json').write_text(json.dumps(pixels,indent=2))
            assert pixels['passed'], pixels
            if live.state['component_gallery']['component'] in ('buttons','cards','lists'):
                target=live.state['component_gallery']['buttons'][3]['position']
                acquire(target,preset,[p+n for p,n in zip(target,normal)],
                        lambda s:s['component_gallery']['buttons'][3]['hovered'],'disable')
                live.button('trigger')
                assert all(s['state']=='DISABLED' for s in live.state['component_gallery']['samples'])
                sample=live.state['component_gallery']['samples'][0]
                target=sample['position'];before=sample['clicks']
                acquire(target,preset,[p+n for p,n in zip(target,normal)],
                        lambda s:s['component_gallery']['samples'][0]['hovered'],'disabled button')
                live.button('trigger')
                assert live.state['component_gallery']['samples'][0]['clicks']==before

    finally:
        live.release()
        (output/'trials.json').write_text(json.dumps(results,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--component',choices=['thumbwheel','buttons','cards','lists'],default='thumbwheel')
    parser.add_argument('--desktop',action='store_true')
    parser.add_argument('--validate',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.desktop and args.validate:
        parser.error('Use the native unit/render tests for desktop validation.')
    from backend.api.routes_vr import _build_environment, _ensure_viewer_built, _start_steamvr
    output=(args.output or ROOT/'.development-artifacts/vr-component-gallery'/uuid.uuid4().hex[:10]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    _ensure_viewer_built()
    if not args.desktop:
        from backend.api.routes_vr_tours import _viewer_active
        if _viewer_active():raise RuntimeError('Close the active VR viewer before opening a gallery VR demo.')
        _start_steamvr()
    with tempfile.TemporaryDirectory(prefix='nadoc-gallery-') as temp:
        socket=str(Path(temp)/'viewer.sock')
        command=[str(ROOT/'native/vr_viewer/build/nadoc-vr-viewer'),
                 str(ROOT/'native/vr_viewer/examples/empty_authoring.nadocvr'),
                 '--component-gallery',args.component,'--gallery-output',str(output)]
        if args.desktop:command+=['--gallery-desktop','on']
        else:command+=['--mirror-eye','left','--scrywrite-live',socket,'--scrywrite-live-mode','control' if args.validate else 'inspect']
        with (output/'viewer.log').open('w') as log:
            process=subprocess.Popen(command,env=_build_environment(),stdout=log,stderr=subprocess.STDOUT)
        (output/'launch.json').write_text(json.dumps({'pid':process.pid,'command':command,'socket':socket},indent=2))
        try:
            if args.validate:
                from frontend.scrywrite.mcp_bridge import Bridge
                from tools.vr_motion.session import LiveSession
                deadline=time.monotonic()+45
                while True:
                    try:
                        live=LiveSession(Bridge(socket_path=socket))
                        if live.state.get('component_gallery',{}).get('active'):break
                    except (OSError,RuntimeError,ValueError):
                        if time.monotonic()>deadline or process.poll() is not None:raise
                    time.sleep(.2)
                validate(live,output)
                print('All four controller profiles passed.',flush=True)
            else:
                print('Gallery ready. Try the controls or select Play demo. Close its window to finish.',flush=True)
                result=process.wait()
                if result:raise RuntimeError(f'Gallery exited with {result}; see {output / "viewer.log"}')
        finally:
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__=='__main__':main()
