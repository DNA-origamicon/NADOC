"""Visible, non-creating File workflow through real controller and browser input."""
import json
import os
from pathlib import Path
import sys
import time
from copy import deepcopy

import numpy as np
from scipy.spatial.transform import Rotation
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import FINAL_PRESETS
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.control_approach import control_approach
from tools.vr_workflows.sweep_probe import wait_for_headset
from tools.vr_workflows.sweep_view import dismiss_dashboard, fullscreen_mirror
from tools.vr_workflows.menu_pixels import check as pixels
from tools.vr_motion.desktop_check import run as desktop_check


def run(socket, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    wait_for_headset(bridge, output, dismiss=dismiss_dashboard, message='Waiting for tracked headset focus for the File demo; no part will be created.')
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    trials, stages = [], []
    closing = False
    cancelled = 0
    validate = os.environ.get('NADOC_VR_FILE_VALIDATE') == '1'
    hold = .5 if validate else float(os.environ.get('NADOC_VR_DEMO_HOLD', '5'))

    def wait(predicate, timeout=12):
        until = time.monotonic()+timeout
        settled_since = None
        while True:
            live.frame()
            # Open replaces an already visible picker asynchronously. A single
            # matching frame can still be the old picker before Working appears.
            if predicate(live.state):
                if settled_since is None: settled_since = time.monotonic()
                if time.monotonic()-settled_since >= .35: return
            else: settled_since = None
            if time.monotonic() > until: raise RuntimeError('File workflow state did not settle')
            time.sleep(.05)

    def control(identifier):
        return next((c for c in live.state['controls'] if c['id'] == identifier), None)

    def click(identifier, preset, disabled=False):
        wait(lambda s: control(identifier) and (disabled or control(identifier)['enabled']))
        for attempt in range(3):
            target = control(identifier)
            popup = bool(live.state['routing_popup'][1]['open'])
            side = 1 if popup else 0
            def acquired(state):
                return state['routing_popup' if popup else 'sidebars'][side]['hover_id'] == identifier
            trial = reach_target(live, target['position'], preset, 9100+len(trials),
                acquired=acquired, target_position=control_approach(target, live.state['hands'][1]['position']))
            trial.update(control=identifier, attempt=attempt+1, preset=preset)
            trials.append(trial)
            if trial['acquired_with_feedback'] and acquired(live.state):
                live.button('trigger', hand=1)
                return
        raise RuntimeError('Could not acquire '+identifier)

    def review(name, required):
        print('Review: '+name, flush=True)
        # Release the pointing trigger and park the hand clear of the lettering.
        live.frame()
        destination = output/name
        evidence, _ = live.capture_to(destination, files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
        selected = deepcopy(evidence)
        selected['state']['controls'] = [c for c in selected['state']['controls'] if c['id'] in required]
        assert set(required) == {c['id'] for c in selected['state']['controls']}, ('missing rendered controls', name)
        report = pixels(destination, selected)
        (destination/'pixels.json').write_text(json.dumps(report, indent=2))
        assert report['passed'], [c for c in report['controls'] if not c['passed']]
        negative = deepcopy(selected)
        for c in negative['state']['controls']: c['position'] = [1000, 1000, 1000]
        assert not pixels(destination, negative)['passed'], 'offscreen negative passed'
        delivered = desktop_check(socket, destination/'desktop', live=live, reveal=True)
        assert delivered['passed'], delivered
        stages.append({'name': name, 'controls': required, 'pixels': True, 'desktop': True})
        until = time.monotonic()+hold
        while time.monotonic() < until: live.frame(); time.sleep(.05)

    try:
        fullscreen_mirror(live, output)
        anchor, _ = live.capture_to(output/'anchor', files=['evidence.json'], discard_source=True)
        head = np.mean([e['position'] for e in anchor['eyes']], axis=0)
        facing = Rotation.from_quat(anchor['eyes'][0]['orientation_xyzw'])
        for hand in (0, 1):
            if live.state['sidebars'][hand]['open']: live.button('menu', hand=hand)
        wrist_position = head+facing.apply([0, 0, -.4])
        live.send('pose', hand=0, position=wrist_position.tolist(), orientation=facing.as_quat().tolist()); live.frame()
        live.button('menu', hand=0); live.frame()
        panel = live.state['sidebars'][0]
        sample = next(c for c in live.state['controls'] if c.get('sidebar') == 'left')
        right = np.array(sample['hit_half_right']); right /= np.linalg.norm(right)
        up = np.array(sample['hit_half_up']); up /= np.linalg.norm(up)
        observed = Rotation.from_matrix(np.column_stack([right, up, np.cross(right, up)]))
        offset = facing.inv().apply(np.asarray(panel['position'])-wrist_position)
        wrist = facing*(facing.inv()*observed).inv()
        # Place the full-size keyboard inside the actual eye frustum; no headset
        # pose override and no reduced key hit boxes. The menu is enlarged separately.
        live.button('menu', hand=0)
        def menu(distance=1.30):
            center = head+facing.apply([0, .1, -distance])
            spawn = center-wrist.apply(offset)
            if live.state['sidebars'][0]['open']: live.button('menu', hand=0)
            live.send('pose', hand=0, position=spawn.tolist(), orientation=wrist.as_quat().tolist()); live.frame()
            if not live.state['sidebars'][0]['open']: live.button('menu', hand=0)
            live.frame()
        menu()
        # Ordinary two-hand border resizing, outside measured controller reaches.
        panel = live.state['sidebars'][0]; before = panel['scale']
        ends = np.asarray(panel['grip_targets'][:2]); midpoint = ends.mean(axis=0)
        for hand in (0, 1): live.send('pose', hand=hand, position=(ends[hand]+[0, 0, .12]).tolist(), orientation=[0, 0, 0, 1])
        live.frame()
        try:
            for hand in (0, 1): live.send('button', hand=hand, button='grip', pressed=True); live.frame()
            assert live.state['sidebars'][0]['grip_state'] == 'resizing'
            for hand in (0, 1): live.send('pose', hand=hand, position=(midpoint+(ends[hand]-midpoint)*(.8/before)+[0, 0, .12]).tolist(), orientation=[0, 0, 0, 1])
            live.frame()
        finally:
            for hand in (0, 1): live.send('button', hand=hand, button='grip', pressed=False)
            live.frame()
        assert abs(live.state['sidebars'][0]['scale']-.8) < .002
        (output/'presentation.json').write_text(json.dumps({'method': 'observed wrist calibration and ordinary menu resize',
            'menu_distance_m': 1.30, 'keyboard_distance_m': 1.30, 'menu_scale': .8, 'keyboard_scale_unchanged': 1.2,
            'head': head.tolist(), 'keyboard_center': (head+facing.apply([0, .1, -1.30])).tolist()}, indent=2))
        for preset in FINAL_PRESETS if validate else ['steady_fast']:
            menu()
            click('tab:file', preset)
            wait(lambda s: control('routing:file-entry-0') is not None)
            roots = ['routing:file-'+key for key in ('new', 'assembly', 'open', 'save', 'close')]
            review(preset+'-file-menu', roots)
            assert not control('routing:file-assembly')['enabled']
            click('routing:file-assembly', preset, disabled=True)
            assert live.state['routing_popup'][1]['open']
            click('routing:file-new', preset)
            wait(lambda s: control('routing:file-key-d') is not None)
            assert not live.state['sidebars'][0]['open']
            keys = [c['id'] for c in live.state['controls'] if c['id'].startswith('routing:file-key-')]
            assert len(keys) == 42
            review(preset+'-new-part-keyboard', keys+['routing:file-button-0', 'routing:file-button-1', 'routing-help'])
            for key, expected in [('d', 'd'), ('e', 'de'), ('m', 'dem'), ('o', 'demo'), ('1', 'demo1'), ('delete', 'demo'), ('2', 'demo2')]:
                click('routing:file-key-'+key, preset)
                wait(lambda s: control('routing-help') and (' / '+expected+' [') in control('routing-help')['label'])
            review(preset+'-typed-demo2-before-cancel', keys+['routing:file-button-0', 'routing:file-button-1', 'routing-help'])
            click('routing:file-button-0', preset)
            wait(lambda s: not s['routing_popup'][1]['open'])
            cancelled += 1
            menu(); click('tab:file', preset)
            wait(lambda s: control('routing:file-entry-0') is not None)
            review(preset+'-cancelled-no-part-created', roots)
            click('routing:file-open', preset)
            wait(lambda s: control('routing:file-entry-0') is not None)
            review(preset+'-open-browser', [c['id'] for c in live.state['controls'] if c['id'].startswith('routing:')])
            entry = next(c['id'] for c in live.state['controls'] if 'File demo folder' in c['label'])
            click(entry, preset)
            wait(lambda s: control('routing-help') and 'File demo folder' in control('routing-help')['label'])
            review(preset+'-inside-folder', [c['id'] for c in live.state['controls'] if c['id'].startswith('routing:')])
            click('routing:file-button-0', preset)
            wait(lambda s: not s['routing_popup'][1]['open'])
        menu(); click('tab:file', 'steady_fast')
        wait(lambda s: control('routing:file-close') is not None)
        review('close-session-ready', roots)
        print('Close Session: ending only this isolated demo viewer.', flush=True)
        closing = True
        click('routing:file-close', 'steady_fast')
    finally:
        (output/'reaches.json').write_text(json.dumps(trials, indent=2))
        (output/'stages.json').write_text(json.dumps({'stages': stages,
            'not_exercised': ['Save As commit and Open file loading: no saved structure fixture; no files created'],
            'cancelled_new_part_attempts': cancelled}, indent=2))
        try: live.release()
        except (OSError, RuntimeError):
            if not closing: raise


if __name__ == '__main__': run(*sys.argv[1:])
