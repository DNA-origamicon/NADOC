"""Physical-runtime border movement/resize checks using unchanged motion profiles."""
import json
import time
import math
import numpy as np
from PIL import Image
from tools.vr_motion.model import reach
from tools.vr_motion.metrics import rotate
from tools.vr_motion.presets import PRESETS
from tools.vr_motion.visual_checks import project


from tools.vr_workflows.audit_intervals import record_reach


@record_reach
def move(live, targets, preset, trials):
    duration, profile = PRESETS[preset]
    paths = {}
    for hand, target in targets.items():
        pose = live.state['hands'][hand]
        paths[hand] = reach(pose['position'], target, start_q=pose['orientation_xyzw'],
                           target_q=pose['orientation_xyzw'], hand='left' if hand == 0 else 'right',
                           duration_s=duration, rate_hz=20, seed=9000+len(trials)*2+hand,
                           profile=profile)
    trial = {'preset': preset, 'paths': paths, 'observed': []}
    trials.append(trial)
    started = time.monotonic()
    for index, sample in enumerate(next(iter(paths.values()))['samples']):
        time.sleep(max(0, started+sample['t']-time.monotonic()))
        lag = time.monotonic()-started-sample['t']
        if lag > .15:
            raise TimeoutError(f'Grip profile playback late by {lag:.3f}s')
        for hand, path in paths.items():
            pose = next(iter(path['samples'][index]['hands'].values()))
            live.send('pose', hand=hand, position=pose['position'], orientation=pose['orientation'])
        live.frame()
        trial['observed'].append({'frame': live.state['frame'], 'lag_s': lag,
                                  'hands': live.state['hands'], 'sidebars': live.state['sidebars'],
                                  'extrude': live.state.get('extrude')})


def grip_origin(live, hand, target):
    """Place the tip selection sphere at a target without changing the wrist."""
    offset = rotate(live.state['hands'][hand]['orientation_xyzw'], [0, 0, -.12])
    return (np.asarray(target)-offset).tolist()


def assert_controller_spawn(panel, pose):
    expected = np.asarray(pose['position']) + rotate(pose['orientation_xyzw'], [0, 0, -.40])
    assert np.linalg.norm(np.asarray(panel['position'])-expected) < 2e-5
    left, right, top, bottom = map(np.asarray, panel['grip_targets'])
    right_axis = (right-left)/np.linalg.norm(right-left)
    up_axis = (top-bottom)/np.linalg.norm(top-bottom)
    assert np.linalg.norm(right_axis-rotate(pose['orientation_xyzw'], [1, 0, 0])) < 2e-5
    assert np.linalg.norm(up_axis-rotate(pose['orientation_xyzw'], [0, math.cos(math.pi/6), -math.sin(math.pi/6)])) < 2e-5


def acquire(live, panel, hand, edge, preset, trials):
    for _ in range(3):
        target = np.asarray(live.state['sidebars'][panel]['grip_targets'][edge])
        move(live, {hand: grip_origin(live, hand, target)}, preset, trials)
        if live.state['sidebars'][panel]['grip_nearby'][hand]:
            return
    raise AssertionError(f'Could not acquire {panel}/{edge} border with hand {hand}')


def frame_pixels(directory, evidence, panel, state):
    menu = evidence['state']['sidebars'][panel]
    assert menu['grip_state'] == state, menu
    left, right, top, bottom = map(np.asarray, menu['grip_targets'])
    center = (left+right)*.5
    dx, dy = right-center, top-center
    points = [center+dx*x+dy*y for t in np.linspace(-.9, .9, 13)
              for x, y in ((-1, t), (1, t), (t, -1), (t, 1))]
    expected = np.array({'ready': (88, 166, 255), 'moving': (255, 202, 94),
                         'resizing': (100, 220, 150)}[state])
    checks = []
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))
        matches = 0
        for point in points:
            xy = project(point.tolist(), eye)
            if xy is None:
                continue
            x, y = map(round, xy)
            if not (3 <= x < eye['width']-3 and 3 <= y < eye['height']-3):
                continue
            patch = rgb[y-3:y+4, x-3:x+4].astype(float)
            matches += bool((np.abs(patch-expected).max(axis=2) < 60).any())
        fraction = matches/len(points)
        checks.append({'eye': eye['eye'], 'frame_fraction': fraction, 'passed': fraction >= .6})
    return checks


def capture(live, output, name, panel, state):
    evidence, _ = live.capture_to(output/name, files=('left.png', 'right.png', 'mirror.png', 'evidence.json'), discard_source=True)
    checks = frame_pixels(output/name, evidence, panel, state)
    (output/name/'frame-pixels.json').write_text(json.dumps(checks, indent=2)+'\n')
    assert all(c['passed'] for c in checks), checks


def run(live, catalog, output, preset):
    del catalog
    checks, trials = {}, []
    spawn_hands = [dict(h) for h in live.state['hands']]
    original_scene = live.state['presentation']['model_to_tracking_rows']
    try:
        for panel in (0, 1):
            assert_controller_spawn(live.state["sidebars"][panel], spawn_hands[panel])
            checks[f"{panel}_controller_spawn_30_degrees"] = True
            other = dict(live.state['sidebars'][1-panel])
            edge = panel  # Outside edge of each panel.
            frozen_position = list(live.state['sidebars'][panel]['position'])
            # The old origin-only hit must no longer light the frame.
            move(live, {1: live.state['sidebars'][panel]['grip_targets'][edge]}, preset, trials)
            assert not live.state['sidebars'][panel]['grip_nearby'][1]
            checks[f'{panel}_midpoint_contact_rejected'] = True
            acquire(live, panel, 1, edge, preset, trials)
            assert live.state['sidebars'][panel]['position'] == frozen_position
            checks[f'{panel}_spawn_stays_world_fixed'] = True
            capture(live, output, f'{panel}-ready', panel, 'ready')
            initial = live.state['sidebars'][panel]['position']
            live.send('button', hand=1, button='grip', pressed=True)
            live.frame()
            assert live.state['sidebars'][panel]['grip_state'] == 'moving'
            left, right, top, bottom = map(np.asarray, live.state['sidebars'][panel]['grip_targets'])
            outward = (right-left)/np.linalg.norm(right-left)*(-.07 if panel == 0 else .07)
            upward = (top-bottom)/np.linalg.norm(top-bottom)*.04
            target = (np.asarray(live.state['hands'][1]['position'])+outward+upward).tolist()
            move(live, {1: target}, preset, trials)
            assert math.dist(initial, live.state['sidebars'][panel]['position']) > .035
            capture(live, output, f'{panel}-moving', panel, 'moving')
            acquire(live, panel, 0, 1-edge, preset, trials)
            live.send('button', hand=0, button='grip', pressed=True)
            live.frame()
            assert live.state['sidebars'][panel]['grip_state'] == 'resizing'
            scale = live.state['sidebars'][panel]['scale']
            positions = [np.asarray(h['position']) for h in live.state['hands']]
            midpoint = (positions[0]+positions[1])*.5
            targets = {h: (midpoint+(positions[h]-midpoint)*1.15).tolist() for h in (0, 1)}
            move(live, targets, preset, trials)
            assert live.state['sidebars'][panel]['scale'] > scale*1.04
            capture(live, output, f'{panel}-resizing', panel, 'resizing')
            for hand in (0, 1):
                live.send('button', hand=hand, button='grip', pressed=False)
            live.frame()
            assert live.state['sidebars'][panel]['grip_state'] not in ('moving', 'resizing')
            assert live.state['sidebars'][1-panel]['position'] == other['position']
            assert live.state['sidebars'][1-panel]['scale'] == other['scale']
            assert live.state['presentation']['model_to_tracking_rows'] == original_scene
            checks[f'{panel}_move_resize_release_independent'] = True
            # Review reset outside measured motion; release before closing a panel.
            live.button('menu', hand=panel)
            pose = spawn_hands[panel]
            live.send('pose', hand=panel, position=pose['position'], orientation=pose['orientation_xyzw'])
            live.frame()
            live.button('menu', hand=panel)
        for hand, pose in enumerate(spawn_hands):
            live.send('pose', hand=hand, position=pose['position'], orientation=pose['orientation_xyzw'])
        live.frame()
        return {**checks, 'passed': True}
    finally:
        for hand in (0, 1):
            live.send('button', hand=hand, button='grip', pressed=False)
        (output/'grip-checks.json').write_text(json.dumps({'checks': checks, 'trials': trials}, indent=2)+'\n')
