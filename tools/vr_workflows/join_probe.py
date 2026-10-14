"""Physical Join input using production selection, remote grabs and thumbwheels.

Native stereo capture is separate from timed motion. Frame audit records retain
the application budget and submission cadence; they do not establish scanout FPS.
"""
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import unquote

import numpy as np

from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.model import multiply
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.audit_intervals import operation
from tools.vr_workflows.control_approach import control_approach
from tools.vr_workflows.demo_view import reveal
from tools.vr_workflows.extrude_sidebar import SidebarControls
from tools.vr_workflows.menu_tour import scroll_page
from tools.vr_workflows.move_acquisition import remote_target
from tools.vr_workflows.profile_input import aim_orientation, reach_target


def main():
    socket, destination, before_path, stage = sys.argv[1:5]
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic() + 60
    while True:
        try:
            state = bridge.call('scrywrite_observe', {})
        except TimeoutError:
            # Startup can spend more than the bridge's three-second read
            # timeout compiling/loading. Observations are safe to retry;
            # retain the original readiness deadline and never retry input.
            state = None
        if state and state.get('focused') and not state.get('startup', {}).get('active'):
            break
        if time.monotonic() > deadline:
            raise RuntimeError('Join viewer did not become focused and ready')
        time.sleep(.1)
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    preset = os.environ.get('NADOC_VR_PROFILE', 'steady_fast')
    controls = SidebarControls(live, output, preset)
    trials = []
    os.environ['NADOC_VR_AUDIT_INTERVALS'] = str(output / 'intervals.jsonl')

    def wait(predicate, timeout=45):
        end = time.monotonic() + timeout
        while not predicate(live.state):
            if time.monotonic() > end:
                raise RuntimeError('Join timed out: ' + str(live.state.get('join_status')))
            try:
                live.frame()
            except TimeoutError:
                pass
            time.sleep(.04)

    def reach(position, orientation=None, *, hand=1, acquired=None):
        trials.append(reach_target(live, position, preset, 23000 + len(trials),
            target_position=position, target_orientation=orientation or [0, 0, 0, 1], hand=hand, acquired=acquired))
        assert live.state.get('join_frame_comparisons', 0) <= 4096, 'Join exceeded its per-frame proximity budget'
        (output / 'reaches.json').write_text(json.dumps(trials, indent=2))

    def park():
        for hand in (0, 1):
            live.send('pose', hand=hand, position=(np.array(live.state['head_position']) + [hand * .6 - .3, -.8, .1]).tolist(), orientation=[0, 0, 0, 1])
        live.frame()

    def menu():
        if not live.state['sidebars'][1]['open']:
            live.button('menu', hand=1)

    def activate():
        menu()
        if live.state.get('join_active'):
            controls.click('join:back')
        controls.click('tab:tools')
        controls.click('tool-join')
        wait(lambda s: s['join_active'] and s['selection_level'] == 'cluster')
        assert live.state['sidebars'][1]['layout'] == 'valid'

    def select_cluster():
        if live.state['sidebars'][1]['open']:
            live.button('menu', hand=1)
        before = json.loads(Path(before_path).read_text())
        donor = next(c for c in before['cluster_transforms'] if c['id'] == 'join_cluster_1')
        # The bounded read-only move_targets list can contain only the first
        # cluster of a large scene. Locate the donor in actual submitted stereo
        # pixels and depth instead of expanding that runtime observation budget.
        from tools.vr_workflows.move_pixels import centers
        acquisition = output / 'acquisition'
        live.capture_to(acquisition, discard_source=True)
        objects = json.loads((acquisition / 'objects.json').read_text())
        token = next((token for obj in objects for token in obj['owner_tokens']
                      if json.loads(unquote(token)) == ['cluster', donor['id']]), None)
        assert token, 'Rendered object metadata has no moving-cluster owner'
        left, selected = centers(acquisition, 'left', token)
        right, _ = centers(acquisition, 'right', token)
        identities = {obj['id']: obj['identity'] for obj in objects}
        candidates = [{'identity': identities[index], 'world': ((left[index] + right[index]) / 2).tolist()}
                      for index in left.keys() & right.keys() & selected if identities[index].startswith('nuc:')]
        assert candidates, 'Moving cluster has no visible nucleotide geometry in both submitted eyes'
        candidates.sort(key=lambda p: np.linalg.norm(np.array(p['world']) - live.state['head_position']))
        for candidate in candidates[:24]:
            point = np.array(candidate['world'])
            offset = np.array(live.state['head_position']) - point
            body = (point + .15 * offset / np.linalg.norm(offset)).tolist()
            reach(body, aim_orientation(body, point.tolist()), hand=0)
            live.send('trigger_value', hand=0, value=.5)
            live.frame()
            if (live.state.get('scene_hover') or '').startswith('nuc:'):
                # A retained selection may toggle off once after Cancel.
                for _ in range(2):
                    live.button('trigger', hand=0)
                    live.send('trigger_value', hand=0, value=0)
                    for _ in range(15):
                        live.frame()
                        owner_matches = any(json.loads(unquote(token)) == ['cluster', donor['id']] for token in live.state.get('owner_tokens', []))
                        if live.state['selection_kind'] == 'cluster' and owner_matches and live.state.get('move_handle'):
                            park()
                            return point.tolist()
                        time.sleep(.04)
            live.send('trigger_value', hand=0, value=0)
        raise RuntimeError('Could not select a rendered Join cluster')

    def wheel(index):
        menu()
        identifier = f'join:{index}-wheel'
        for _ in range(40):
            if any(c['id'] == identifier for c in live.state['controls']):
                break
            scroll_page(live, 1, 1)
        field, axis, step = ('move_position_nm', index, 1) if index < 3 else ('move_rotation_degrees', index - 3, 15)
        before = live.state[field][axis]
        for _ in range(3):
            control = next(c for c in live.state['controls'] if c['id'] == identifier)
            target = control_approach(control, live.state['hands'][1]['position'])
            trials.append(reach_target(live, control['position'], preset, 24000 + len(trials), target_position=target))
            live.send('button', hand=1, button='trigger', pressed=True)
            live.frame()
            if live.state.get('move_wheel_hand') == 1:
                break
            live.send('button', hand=1, button='trigger', pressed=False)
        assert live.state.get('move_wheel_hand') == 1, 'Raised thumbwheel was not acquired'
        up = np.array(control['hit_half_up'])
        up /= np.linalg.norm(up)
        reach((np.array(live.state['hands'][1]['position']) + up * .12).tolist(), live.state['hands'][1]['orientation_xyzw'])
        live.send('button', hand=1, button='trigger', pressed=False)
        live.frame()
        wait(lambda s: not s.get('move_wheel_moving'))
        after = live.state[field][axis]
        assert after != before, 'Thumbwheel did not change the pose'
        assert abs(after / step - round(after / step)) < 1e-4, 'Join thumbwheel did not snap'
        live.capture_to(output / f'wheel-{index}', discard_source=True)

    try:
        reveal(live)
        park()
        if stage == 'undo':
            menu()
            version = live.state['ligation']['version']
            controls.click('join:undo')
            wait(lambda s: s['ligation']['version'] > version and not s['ligation']['waiting'])
            assert live.state['ligation']['status'] == 'created'
        else:
            activate()
            target = select_cluster()
            live.capture_to(output / 'selected', discard_source=True)
            if stage == 'cancel':
                point = np.array(target)
                toward = np.array(live.state['head_position']) - point
                pointer = (point + .4 * toward / np.linalg.norm(toward)).tolist()
                reach(pointer, aim_orientation(pointer, target), acquired=remote_target)
                assert live.state['move_beam_end'] is not None
                live.send('button', hand=1, button='trigger', pressed=True)
                live.frame()
                assert live.state['move_grabbing']
                start = np.array(live.state['hands'][1]['position'])
                wrist = live.state['hands'][1]['orientation_xyzw']
                with operation(live, 'join-trigger-preview'):
                    reach((start + [.03, .015, 0]).tolist(), wrist)
                live.send('button', hand=1, button='trigger', pressed=False)
                live.frame()
                assert np.linalg.norm(live.state['move_position_nm']) > .01
                live.send('button', hand=1, button='grip', pressed=True)
                live.frame()
                assert live.state['move_rotating']
                with operation(live, 'join-grip-preview'):
                    reach(live.state['hands'][1]['position'], multiply([0, 0, np.sin(np.pi / 24), np.cos(np.pi / 24)], wrist))
                live.send('button', hand=1, button='grip', pressed=False)
                live.frame()
                assert np.linalg.norm(live.state['move_rotation_degrees']) > 1
                park()
                live.capture_to(output / 'moved-rotated', discard_source=True)
                wheel(0)
                wheel(5)
                controls.click('join:cancel')
                wait(lambda s: s['status'] == 'CANCELLED')
                assert live.state['move_position_nm'] == [0, 0, 0]
                assert live.state['move_rotation_degrees'] == [0, 0, 0]
            else:
                # Fresh cluster selection publishes the compatible pose. Await
                # its authoritative feedback before clicking the real Apply
                # control; wheel movement and snapping were exercised above.
                wait(lambda s: s['join_valid'], timeout=75)
                assert live.state['join_bridge_count'] > 0
                park()
                live.capture_to(output / 'valid-connections', discard_source=True)
                menu()
                with operation(live, 'join-apply'):
                    controls.click('join:apply')
                    wait(lambda s: s.get('status') == 'COMMITTED', timeout=75)
        park()
        live.capture_to(output / 'result', discard_source=True)
        (output / 'result.json').write_text(json.dumps(live.state, indent=2))
    except Exception:
        (output / 'failure-state.json').write_text(json.dumps(live.state, indent=2))
        raise
    finally:
        (output / 'sidebar-reaches.json').write_text(json.dumps(controls.trials, indent=2))
        live.release()


if __name__ == '__main__':
    main()
