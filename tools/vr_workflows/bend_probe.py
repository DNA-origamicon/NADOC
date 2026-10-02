"""Bend via production controller input; exported geometry is read-only targeting."""
import argparse
import json
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
    controls = SidebarControls(live, out, preset)
    trials = []

    def wait(predicate):
        deadline = time.monotonic()+45
        while not predicate(live.state):
            if time.monotonic() > deadline:
                raise RuntimeError('Bend feedback timed out')
            live.frame(); time.sleep(.05)

    def reach(position, hand=1, **kwargs):
        trial = reach_target(live, list(position), preset, 7100+len(trials), hand=hand,
            target_position=list(position), **kwargs)
        trials.append(trial)
        (out/'reaches.json').write_text(json.dumps(trials, indent=2))
        return trial

    def keep_alive():
        # Renew the ScryWrite input lease without moving or re-clicking the hand.
        pose = live.state['hands'][1]
        live.send('pose',hand=1,position=pose['position'],orientation=pose['orientation_xyzw'])

    def settle(seconds=1.0):
        # Observation pauses are outside measured reaches; preserve held triggers.
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            keep_alive(); live.frame(); time.sleep(.05)

    def park(only=None):
        for hand in ((0, 1) if only is None else (only,)):
            live.send('pose', hand=hand, position=(np.array(live.state['head_position'])+[0,-1,0]).tolist(), orientation=[0,0,0,1])
        live.frame()

    def capture(name):
        if live.state['bend']['grabbing']:
            bend = live.state['bend']
            for i, plane in enumerate(bend['planes']):
                assert np.linalg.norm(np.array(plane['center'])-bend['endpoints'][i]) < 2e-5, 'Plane did not follow endpoint'
                assert np.linalg.norm(np.array(plane['normal'])-bend['tangents'][i]) < 2e-5, 'Plane is not normal to curve'
        keep_alive()
        evidence,_ = live.capture_to(out/name, discard_source=True)
        if name not in ('before-framing','bend-menu'):
            from tools.vr_workflows.bend_layout import check
            layout = check(evidence)
            (out/name/'panel-layout.json').write_text(json.dumps(layout,indent=2))
            assert layout['passed'],layout
        if name in ('planes-and-handles', 'end-0-preview', 'end-1-preview'):
            from tools.vr_workflows.bend_pixels import validate
            validate(out/name)
        if os.environ.get('NADOC_VR_DEMO') == '1':
            reveal(live);print('Review: '+name.replace('-', ' '),flush=True)
            settle(float(os.environ.get('NADOC_VR_DEMO_HOLD','3')))
        settle()  # Capture/readback is outside the next measured controller reach.

    def menu():
        # A legacy menu may consume the first click by closing. Only start
        # sidebar navigation after its actual open state has been observed.
        for _ in range(2):
            if live.state['sidebars'][1]['open']:
                return
            live.button('menu', hand=1)
            live.frame()

    def approach_point(point):
        point = np.array(point)
        toward_eye = np.array(live.state['head_position'])-point
        body = point+.12*toward_eye/np.linalg.norm(toward_eye)
        reach(body,target_orientation=aim_orientation(body.tolist(),point.tolist()))

    def pick(slot, bp):
        wait(lambda s: s['bend']['ready'])
        plane = np.array(live.state['bend']['planes'][slot-1]['center'])
        approach_point(plane)
        wait(lambda s: s['bend']['plane_hover'][1] == slot-1)
        live.send('button', hand=1, button='trigger', pressed=True); live.frame()
        assert live.state['bend']['plane_hand'] == 1 and not live.state['bend']['grabbing']
        initial = live.state['bend']['plane'+str(slot)]
        target = next(p for p in live.state['bend']['targets'] if int(unquote(p['identity']).split(':')[4]) == bp)
        # Translate the held controller along the cluster, retaining its aim.
        delta = np.array(target['world'])-plane
        reach(np.array(live.state['hands'][1]['position'])+delta,
              target_orientation=live.state['hands'][1]['orientation_xyzw'])
        wait(lambda s: s['bend']['plane'+str(slot)] != initial)
        live.send('button', hand=1, button='trigger', pressed=False); live.frame()
        park(); settle()

    try:
        reveal(live)
        # Physical controllers may be asleep; seed a valid wrist pose before
        # asking the normal menu action to place the panel.
        live.send('pose',hand=1,position=(np.array(live.state['head_position'])+[.2,-.25,-.35]).tolist(),orientation=[0,0,0,1])
        live.frame(); menu();wait(lambda s: s['sidebars'][1]['open'])
        if mode == 'undo':
            controls.click('bend:undo'); wait(lambda s: s['status'] == 'UNDONE')
            park(); capture('undone')
        else:
            if not live.state['bend']['active']:
                controls.click('tab:tools');controls.click('tool-bend')
            controls.click('bend:recenter');controls.click('bend:back')
            live.button('menu', hand=1); park()
            capture('before-framing')
            from tools.vr_workflows.review_view import improve_review
            improve_review(live, out/'before-framing', out/'review-view')
            settle(); menu()
            controls.click('tab:tools'); controls.click('tool-bend')
            controls.click('bend:cancel')
            wait(lambda s: s['bend']['ready'])
            assert live.state['bend']['plane1'] < live.state['bend']['plane2']
            assert live.state['sidebars'][1]['tab'] == 'bend'
            assert not any(c['id'].startswith('tool-') for c in live.state['controls'])
            capture('bend-menu')
            from tools.vr_workflows.bend_layout import place
            evidence = json.loads((out/'bend-menu/evidence.json').read_text())
            place(live, evidence, out)
            park(); settle()
            # Two-column controls retain ordinary touchpad directional navigation.
            from tools.vr_workflows.menu_focus_check import pad, seek
            seek(live,1,'bend:direction-less');pad(live,1,x=1)
            assert live.state['sidebars'][1]['focus_id'] == 'bend:direction-more'
            pad(live,1)
            pick(1, 12); pick(2, 80)
            wait(lambda s: s['bend']['ready'])
            controls.click('bend:manual'); assert live.state['bend']['manual']
            capture('planes-and-handles')
            starting_endpoints = np.array(live.state['bend']['endpoints'])
            starting_normals = np.array([p['normal'] for p in live.state['bend']['planes']])
            for end, hand in ((1,1), (0,0)):
                bend = live.state['bend']
                wrist = aim_orientation(live.state['head_position'],bend['handles'][end])
                reach(bend['handles'][end], hand=hand, target_orientation=wrist)
                live.send('button', hand=hand, button='trigger', pressed=True); live.frame()
                assert live.state['bend']['hand'] == hand
                if end == 0:
                    assert np.linalg.norm(np.array(live.state['bend']['endpoints'])-starting_endpoints) < 2e-5, 'Switching ends must reset the bend'
                    assert live.state['bend']['angle'] == 0
                fixed = np.array(live.state['bend']['endpoints'][1-end])
                assert np.linalg.norm(fixed-starting_endpoints[1-end]) < 2e-5, 'Anchor left its starting plane'
                moving = np.array(live.state['bend']['endpoints'][end])
                start = np.array(live.state['hands'][hand]['position'])
                delta = fixed-moving
                perpendicular = np.cross(delta, [0,1,0])
                perpendicular /= np.linalg.norm(perpendicular)
                reach(start+.25*delta+perpendicular*np.linalg.norm(delta)*.12,
                    hand=hand, target_orientation=wrist)
                current = live.state['bend']
                assert np.linalg.norm(np.array(current['endpoints'][1-end])-fixed) < 1e-5
                assert np.linalg.norm(np.array(current['tangents'][1-end])-starting_normals[1-end]) < 2e-5, 'Fixed surface normal changed'
                assert np.linalg.norm(np.diff(current['endpoints'], axis=0)) <= current['contour_m']+1e-5
                # A second controller cannot steal the active endpoint.
                other = 1-hand
                reach(current['handles'][1-end], hand=other, target_orientation=aim_orientation(live.state['head_position'],current['handles'][1-end]))
                live.send('button', hand=other, button='trigger', pressed=True); live.frame()
                assert live.state['bend']['hand'] == hand
                live.send('button', hand=other, button='trigger', pressed=False); live.frame()
                capture('end-'+str(end)+'-preview')
                menu(); live.frame()
                rows = {c['id']: c['label'] for c in live.state['controls']}
                for field in ('angle','direction'):
                    assert ' / '+field.title()+': '+str(round(live.state['bend'][field]))+' deg [' in rows['bend:'+field]
                capture('end-'+str(end)+'-live-menu')
                assert live.state['sidebars'][1]['open']
                if end == 1:
                    live.send('button', hand=hand, button='trigger', pressed=False); live.frame()
                    park()
                else:
                    park(1)  # Keep Plane 1 held while the free hand operates the wheels.
            menu()
            for name, field in (('angle','angle'), ('direction','direction'), ('radius','angle')):
                identifier = 'bend:'+name+'-wheel'
                controls.click(identifier)
                c = next(c for c in live.state['controls'] if c['id'] == identifier)
                destination = control_approach(c, live.state['hands'][1]['position'])
                trials.append(reach_target(live,c['position'],preset,8100+len(trials),
                    target_position=destination, acquired=lambda s: acquired(s,1,identifier)))
                assert acquired(live.state,1,identifier)
                before = live.state['bend'][field]
                live.send('button', hand=1, button='trigger', pressed=True); live.frame()
                assert live.state['bend']['wheel_hand'] == 1
                assert live.state['bend']['hand'] == 0
                up = np.array(c['hit_half_up']); up /= np.linalg.norm(up)
                reach(np.array(live.state['hands'][1]['position'])+up*.16,
                    target_orientation=live.state['hands'][1]['orientation_xyzw'])
                live.send('button', hand=1, button='trigger', pressed=False); live.frame()
                settle()
                after = live.state['bend'][field]
                assert np.linalg.norm(np.array(live.state['bend']['endpoints'][1])-starting_endpoints[1]) < 2e-5
                assert np.linalg.norm(np.array(live.state['bend']['tangents'][1])-starting_normals[1]) < 2e-5
                assert after != before, name+' wheel did not change'
                assert abs(after-round(after)) < 1e-4, name+' did not snap to degrees'
                capture(name+'-wheel')
            for name, field, amount in (('direction','direction',5),('radius','angle',10)):
                for sign, suffix in ((1,'more'),(-1,'less')):
                    before = live.state['bend'][field]
                    contour = (live.state['bend']['plane2']-live.state['bend']['plane1'])*.334
                    controls.click('bend:'+name+'-'+suffix)
                    after = live.state['bend'][field]
                    if name == 'direction':
                        assert abs(((after-before-sign*amount+180)%360)-180) < .002
                    else:
                        before_radius = contour/np.radians(before)
                        after_radius = contour/np.radians(after)
                        assert abs(after_radius-(before_radius+sign*amount)) < .002
                    assert np.linalg.norm(np.array(live.state['bend']['endpoints'][1])-starting_endpoints[1]) < 2e-5
                    assert live.state['sidebars'][1]['open'] and live.state['bend']['hand'] == 0
                capture(name+'-step-buttons')
            live.send('button', hand=0, button='trigger', pressed=False); live.frame()
            wait(lambda s: s['bend']['ready'])
            (out/'draft.json').write_text(json.dumps(live.state['bend'], indent=2))
            controls.click('bend:confirm'); wait(lambda s: s['status'] == 'COMMITTED')
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
