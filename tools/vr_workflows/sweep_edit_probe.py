"""Open a saved Sweep using the native Feature Log and edit with normal controls."""
import argparse
import copy
import json
import os
import math
import time
from pathlib import Path
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.metrics import rotate
from tools.vr_workflows.profile_input import aim_orientation, reach_target
from tools.vr_workflows.menu_tour import click
from tools.vr_workflows.sweep_probe import SweepControls
from tools.vr_workflows.audit_representation import wait_startup
from tools.vr_workflows.menu_pixels import check as check_pixels


def run(socket, output, preset):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    live = LiveSession(Bridge(socket), physical=True, allow_transactions=True)
    wait_startup(live)
    anchor, _ = live.capture_to(output/'anchor', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
    orientation = anchor['eyes'][0]['orientation_xyzw']
    head = live.state['head_position']
    for hand, offset in [(0,[-.25,-.18,-.35]), (1,[.25,-.18,-.35])]:
        delta = rotate(orientation, offset)
        live.send('pose', hand=hand, position=[a+b for a,b in zip(head,delta)], orientation=orientation);live.frame()
        if live.state['sidebars'][hand]['open']:
            live.button('menu', hand=hand);live.frame()
    controls = SweepControls(live, output, preset)
    trials = []
    def wait(predicate, timeout=30):
        deadline = time.monotonic() + timeout
        while not predicate(live.state):
            if time.monotonic() > deadline:
                (output/'failure.json').write_text(json.dumps(live.state, indent=2))
                raise RuntimeError('Sweep edit did not reach expected state')
            live.frame(); time.sleep(.03)
    def open_edit(label):
        if not live.state['sidebars'][0]['open']:
            live.button('menu', hand=0);live.frame()
        click(live, 0, 'tab:feature-log', preset, trials)
        wait(lambda s: any(c['id']=='history:edit:1' and c['enabled'] for c in s['controls']))
        click(live, 0, 'history:edit:1', preset, trials)
        wait(lambda s: s.get('sweep', {}).get('active') and s['sweep']['ready'])
        # Remove overlapping history after Edit; retain the motion preset.
        if live.state['sidebars'][0]['open']:
            click(live, 0, 'close', preset, trials)
            wait(lambda s: not s['sidebars'][0]['open'])
        live.capture_to(output/label, files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
    def review(stage):
        if os.environ.get('NADOC_SWEEP_PREVIEW_REVIEW') != '1':return
        (output/(stage+'-ready')).write_text('ready')
        wait(lambda state:(output/(stage+'-reviewed')).exists(),30)
    def move_node():
        if os.environ.get('NADOC_SWEEP_NODE_DRAG') != '1':
            controls.click('sweep:point:1');controls.click('sweep:axis:1:1:1');return
        target=live.state['sweep']['points_world'][1]
        origin=[target[0],target[1],target[2]+.25]
        # Aim 25 mm off centre: outside the old 16 mm radius, inside the new 32 mm radius.
        aim=[target[0]+.025,target[1],target[2]]
        direction=aim_orientation(origin,aim)
        live.send('pose',hand=1,position=origin,orientation=direction);live.frame()
        wait(lambda state:state['sweep']['hover_point']==1)
        live.send('button',hand=1,button='trigger',pressed=True);live.frame()
        assert live.state['sweep']['dragging'] and live.state['sweep']['selected']==1
        destination=[origin[0]+.03,origin[1]+.02,origin[2]]
        trial=reach_target(live,destination,preset,7200,target_position=destination,target_orientation=direction)
        trials.append(trial)
        live.send('button',hand=1,button='trigger',pressed=False);live.frame()
    try:
        if os.environ.get('NADOC_SWEEP_PREVIEW_REVIEW') == '1':
            desired_avatar=preset!='steady_deliberate'
            if live.state.get('show_vr_model') != desired_avatar:
                live.button('menu',hand=0);live.frame()
                click(live,0,'tab:share',preset,trials)
                click(live,0,'share-avatar',preset,trials)
                wait(lambda state:state.get('show_vr_model')==desired_avatar)
        open_edit("opened")
        review('opened')
        before = live.state['sweep']['points_nm']
        move_node()
        wait(lambda s: s['sweep']['ready'])
        cancelled = live.state['sweep']['points_nm']
        assert cancelled != before
        controls.click('sweep:back')
        wait(lambda s: not s['sweep']['active'])
        review('cancelled')
        open_edit("reopened")
        assert live.state['sweep']['points_nm'] == before, 'Cancel changed saved geometry'
        move_node()
        wait(lambda s: s['sweep']['ready'])
        after = live.state['sweep']['points_nm']
        assert math.dist(after[1],before[1]) > .1
        if os.environ.get('NADOC_SWEEP_NODE_DRAG') != '1': assert after[1][1] > before[1][1]
        assert after[0] == before[0] and after[2:] == before[2:]
        evidence, _ = live.capture_to(output/'editing', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
        assert evidence['xr_end_frame_succeeded']
        checked=copy.deepcopy(evidence)
        checked['state']['controls']=[c for c in checked['state']['controls'] if c['id'] in ('sweep:confirm','sweep:back')]
        pixels=check_pixels(output/'editing',checked)
        assert pixels['passed'], pixels
        for c in checked['state']['controls']:c['position']=[1000,1000,1000]
        assert not check_pixels(output/'editing',checked)['passed']
        (output/'pixels.json').write_text(json.dumps(pixels,indent=2))
        review('editing')
        revision = live.state['scene_revision']
        start = time.monotonic()
        started_ms = time.time()*1000
        controls.click('sweep:confirm')
        wait(lambda s: not s['sweep']['active'] and s['status']=='COMMITTED' and s['scene_revision'] > revision, 60)
        commit_seconds = time.monotonic()-start
        review('committed')
        live.capture_to(output/'committed', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
        (output/'result.json').write_text(json.dumps(dict(preset=preset, before=before, after=after,
            commit_seconds=commit_seconds, started_ms=started_ms, feature_id=live.state['committed_feature_id'], trials=trials+controls.trials), indent=2))
    except Exception:
        (output/'failure.json').write_text(json.dumps({'state':live.state,'trials':trials+controls.trials}, indent=2))
        live.capture_to(output/'failure', files=['left.png','right.png','mirror.png','evidence.json'], discard_source=True)
        raise
    finally:
        live.release()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket');parser.add_argument('output');parser.add_argument('preset',default='steady_fast',nargs='?')
    args=parser.parse_args();run(args.socket,args.output,args.preset)
