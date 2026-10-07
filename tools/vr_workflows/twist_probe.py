"""Twist via production controller input; exported geometry is read-only targeting."""
import argparse
import json
from tools.vr_workflows.audit_intervals import operation
import os
import time
from pathlib import Path
from urllib.parse import unquote
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.control_approach import control_approach
from tools.vr_workflows.demo_view import reveal
from tools.vr_workflows.extrude_sidebar import SidebarControls
from tools.vr_workflows.menu_tour import acquired
from tools.vr_workflows.profile_input import reach_target, aim_orientation


def run(socket, output, preset, mode):
    out = Path(output); out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic()+30
    while True:
        try:
            if bridge.call('scrywrite_observe', {}).get('focused'):
                break
        except OSError:
            pass  # The process is running before OpenXR creates its socket.
        if time.monotonic() > deadline:
            raise RuntimeError('Viewer did not become focused')
        time.sleep(.1)
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
    if os.environ.get('NADOC_VR_AUDIT_DESIGN') and mode=='edit':
        from tools.vr_workflows.audit_representation import wait_startup
        wait_startup(live)
    else:prepare_audit_representation(live)
    controls = SidebarControls(live, out, preset)
    trials = []

    def wait(predicate):
        deadline = time.monotonic()+45
        while not predicate(live.state):
            if time.monotonic() > deadline:
                raise RuntimeError('Twist feedback timed out')
            try:live.frame()
            except TimeoutError:continue
            time.sleep(.05)

    def reach(position, hand=1, **kwargs):
        trial = reach_target(live, list(position), preset, 7100+len(trials), hand=hand,
            target_position=list(position), **kwargs)
        trials.append(trial)
        (out/'reaches.json').write_text(json.dumps(trials, indent=2))
        return trial

    def radial_choice(hand, target, seed):
        from tools.vr_workflows.selection_wheel_check import thumb_samples
        live.send('trackpad_axis', hand=hand, x=0, y=0)
        live.send('button', hand=hand, button='trackpad', pressed=True); live.frame()
        begun = time.monotonic()
        samples = []
        try:
            for sample in thumb_samples(preset, (0, 0), target, seed):
                time.sleep(max(0, begun+sample['t']-time.monotonic()))
                lag = time.monotonic()-begun-sample['t']
                if lag > .15:
                    raise TimeoutError(f'Thumb profile playback late by {lag:.3f}s')
                live.send('trackpad_axis', hand=hand, x=sample['axis'][0], y=sample['axis'][1]); live.frame()
                samples.append({**sample, 'lag_s':lag})
        finally:
            live.send('button', hand=hand, button='trackpad', pressed=False); live.frame()
            (out/f'radial-{hand}-{seed}.json').write_text(json.dumps(samples, indent=2))

    def keep_alive():
        # Renew the ScryWrite input lease without moving or re-clicking the hand.
        pose = live.state['hands'][1]
        live.send('pose',hand=1,position=pose['position'],orientation=pose['orientation_xyzw'])

    def settle(seconds=1.0):
        # Observation pauses are outside measured reaches; preserve held triggers.
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            keep_alive(); live.frame(); time.sleep(.05)

    def click(identifier):
        controls.click(identifier)
        # Parameter clicks enqueue asynchronous browser feasibility checks. Let
        # that work settle outside the next measured controller reach.
        settle(.75)

    def park(only=None):
        for hand in ((0, 1) if only is None else (only,)):
            live.send('pose', hand=hand, position=(np.array(live.state['head_position'])+[0,-1,0]).tolist(), orientation=[0,0,0,1])
        live.frame()

    def capture(name):
        if name == 'rotation-preview':
            assert live.state['twist']['point_preview_count'] > 0
        keep_alive()
        evidence,_ = live.capture_to(out/name, discard_source=True)
        if name not in ('before-framing','twist-menu'):
            from tools.vr_workflows.bend_layout import check
            layout = check(evidence)
            (out/name/'panel-layout.json').write_text(json.dumps(layout,indent=2))
            assert layout['passed'],layout
        if name in ('planes-and-handles', 'rotation-preview'):
            from tools.vr_workflows.bend_pixels import validate
            validate(out/name)
        if os.environ.get('NADOC_VR_DEMO') == '1':
            reveal(live);print('Review: '+name.replace('-', ' '),flush=True)
            settle(float(os.environ.get('NADOC_VR_DEMO_HOLD','3')))
        settle()  # Capture/readback is outside the next measured controller reach.

    def menu():
        if not live.state['sidebars'][1]['open']:
            live.button('menu', hand=1)

    def approach_point(point):
        point = np.array(point)
        toward_eye = np.array(live.state['head_position'])-point
        body = point+.12*toward_eye/np.linalg.norm(toward_eye)
        reach(body,target_orientation=aim_orientation(body.tolist(),point.tolist()))

    def pick(slot, bp):
        menu(); click('twist:plane'+str(slot))
        assert live.state['sidebars'][1]['open']
        settle()
        candidates = [p for p in live.state['twist']['targets'] if int(unquote(p['identity']).split(':')[4]) == bp]
        assert candidates, f'No rendered bp {bp}'
        target = candidates[0]
        approach_point(target['world'])
        live.send('button', hand=1, button='trigger', pressed=True); live.frame()
        wait(lambda s: s['twist']['plane'+str(slot)] is not None)
        # Continue holding and move along the element: bp must follow the hand.
        initial = live.state['twist']['plane'+str(slot)]
        adjacent = [p for p in live.state['twist']['targets'] if int(unquote(p['identity']).split(':')[4]) == bp+8]
        approach_point(adjacent[0]['world'])
        wait(lambda s: s['twist']['plane'+str(slot)] != initial)
        live.send('button', hand=1, button='trigger', pressed=False); live.frame()
        park(); settle()

    try:
        reveal(live)
        live.send('pose',hand=1,position=(np.array(live.state['head_position'])+[.2,-.25,-.35]).tolist(),orientation=[0,0,0,1])
        live.frame(); menu();wait(lambda s: s['sidebars'][1]['open'])
        if mode == 'undo':
            click('twist:undo'); wait(lambda s: s['status'] == 'UNDONE')
            park(); capture('undone')
        else:
            if not live.state.get('twist', {}).get('active'):
                click('tab:tools');click('tool-twist')
            click('twist:recenter');click('twist:back')
            live.button('menu', hand=1); park()
            capture('before-framing')
            from tools.vr_workflows.review_view import improve_review
            improve_review(live, out/'before-framing', out/'review-view')
            settle(); menu()
            click('tab:tools'); click('tool-twist')
            click('twist:cancel')
            # Entry starts in selection mode. Desktop selection may not survive
            # native startup/reframing; acquire through the ordinary controller.
            if live.state['selection_kind'] != 'cluster':
                park()
                # The persistent Twist panel owns rays through its surface even
                # during selection. Frame the model beside it before acquisition.
                from tools.vr_workflows.bend_layout import place
                selection_view, _ = live.capture_to(out/'selection-menu', discard_source=True)
                place(live, selection_view, out/'selection-framing')
                radial_choice(0, (.69282, .4), 7099)
                wait(lambda s: s['selection_level'] == 'cluster')
                candidates = sorted(live.state['twist']['targets'],
                    key=lambda p: np.linalg.norm(np.array(p['world'])-live.state['head_position']))
                acquisitions = []
                for target in candidates[:24]:
                    point = np.array(target['world'])
                    toward_eye = np.array(live.state['head_position'])-point
                    body = point+.12*toward_eye/np.linalg.norm(toward_eye)
                    reach(body, hand=0, target_orientation=aim_orientation(body.tolist(), point.tolist()))
                    live.send('trigger_value', hand=0, value=.5); live.frame()
                    acquisitions.append({'target':target, 'hover':live.state.get('scene_hover')})
                    (out/'selection-acquisition.json').write_text(json.dumps(acquisitions, indent=2))
                    if (live.state.get('scene_hover') or '').startswith('nuc:'):
                        live.button('trigger', hand=0)
                        live.send('trigger_value', hand=0, value=0); live.frame()
                        wait(lambda s: s['selection_kind'] == 'cluster')
                        break
                    live.send('trigger_value', hand=0, value=0); live.frame()
                else:
                    raise RuntimeError('No nucleotide acquired for Twist cluster selection')
                park(); menu()
            radial_choice(1, (.8, 0), 7100)  # Workflow Next / Use selection.
            wait(lambda s: s['twist']['ready'])
            assert live.state['twist']['plane1'] < live.state['twist']['plane2']
            assert live.state['sidebars'][1]['tab'] == 'twist'
            assert not any(c['id'].startswith('tool-') for c in live.state['controls'])
            capture('twist-menu')
            from tools.vr_workflows.bend_layout import place
            evidence = json.loads((out/'twist-menu/evidence.json').read_text())
            place(live, evidence, out)
            park(); settle()
            pick(1, 12); pick(2, 80)
            wait(lambda s: s['twist']['ready'])
            if os.environ.get('NADOC_VR_AUDIT_DESIGN'):
                prepare_audit_representation(live,via_feedback=True)
            capture('planes-and-handles')
            starting_planes = live.state['twist']['planes']
            # Turn the Plane 2 radial handle through a quarter circle; Plane 1 stays fixed.
            twist = live.state['twist']
            center = np.array(twist['endpoints'][1])
            radial = np.array(twist['handles'][1])-center
            normal = np.array(twist['planes'][1]['normal'])
            wrist = aim_orientation(live.state['head_position'],twist['handles'][1])
            reach(twist['handles'][1],target_orientation=wrist)
            live.send('button',hand=1,button='trigger',pressed=True);live.frame()
            assert live.state['twist']['hand'] == 1
            before = live.state['twist']['total_degrees']
            for angle in np.linspace(0,np.pi/2,7)[1:]:
                destination = center+radial*np.cos(angle)+np.cross(normal,radial)*np.sin(angle)
                reach(destination,target_orientation=wrist)
            assert live.state['twist']['total_degrees'] > before+60
            assert live.state['twist']['planes'] == starting_planes
            assert not live.state['twist']['ready']
            capture('rotation-preview')
            live.send('button',hand=1,button='trigger',pressed=False);live.frame()
            park();settle()
            for unit in ('total_degrees','degrees_per_nm'):
                if live.state['twist']['amount_mode'] != unit:
                    before = live.state['twist']['total_degrees']
                    click('twist:units')
                    assert abs(live.state['twist']['total_degrees']-before)<.001
                identifier = 'twist:amount'
                click(identifier)
                c = next(c for c in live.state['controls'] if c['id'] == identifier)
                destination = control_approach(c, live.state['hands'][1]['position'])
                trials.append(reach_target(live,c['position'],preset,8100+len(trials),
                    target_position=destination, acquired=lambda s: acquired(s,1,identifier)))
                assert acquired(live.state,1,identifier)
                before = live.state['twist']['amount']
                live.send('button',hand=1,button='trigger',pressed=True);live.frame()
                assert live.state['twist']['wheel_hand'] == 1
                up = np.array(c['hit_half_up']);up /= np.linalg.norm(up)
                reach(np.array(live.state['hands'][1]['position'])+up*.16,
                    target_orientation=live.state['hands'][1]['orientation_xyzw'])
                live.send('button',hand=1,button='trigger',pressed=False);live.frame()
                after = live.state['twist']['amount']
                assert after != before
                detents = after*(1 if unit=='total_degrees' else 10)
                assert abs(detents-round(detents))<.001
                capture(unit+'-wheel')
                for suffix,sign in (('more',1),('less',-1)):
                    before = live.state['twist']['amount']
                    click('twist:'+suffix)
                    assert abs(live.state['twist']['amount']-before-sign*(5 if unit=='total_degrees' else .5))<.001
            before = live.state['twist']['amount']
            click('twist:reverse')
            assert abs(live.state['twist']['amount']+before)<.001
            capture('negative-twist')
            click('twist:zero');assert live.state['twist']['amount']==0
            # Leave a modest signed deformation for desktop persistence checks.
            click('twist:less');click('twist:less')
            wait(lambda s: s['twist']['ready'])
            (out/'draft.json').write_text(json.dumps(live.state['twist'], indent=2))
            with operation(live,'twist-commit'):
                click('twist:confirm'); wait(lambda s: s['status'] == 'COMMITTED')
            park(); capture('committed')
        (out/'result.json').write_text(json.dumps(live.state, indent=2))
    except Exception:
        (out/'failure-state.json').write_text(json.dumps(live.state, indent=2))
        raise
    finally:
        live.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket'); parser.add_argument('output')
    parser.add_argument('--preset', default='steady_fast')
    parser.add_argument('--mode', choices=['edit','undo'], default='edit')
    args = parser.parse_args()
    run(args.socket, args.output, args.preset, args.mode)
