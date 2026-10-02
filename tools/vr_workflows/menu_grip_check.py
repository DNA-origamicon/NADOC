"""Physical-runtime border movement/resize checks using unchanged motion profiles."""
import json
import time
import math
import numpy as np
from PIL import Image
from tools.vr_motion.model import reach
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


def acquire(live, panel, hand, edge, preset, trials):
    for _ in range(3):
        move(live, {hand: live.state['sidebars'][panel]['grip_targets'][edge]}, preset, trials)
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
    original_scene = live.state['presentation']['model_to_tracking_rows']
    try:
        for panel in (0, 1):
            other = dict(live.state['sidebars'][1-panel])
            edge = panel  # Outside edge of each panel.
            acquire(live, panel, 1, edge, preset, trials)
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
            live.button('menu', hand=panel)
        return {**checks, 'passed': True}
    finally:
        for hand in (0, 1):
            live.send('button', hand=hand, button='grip', pressed=False)
        (output/'grip-checks.json').write_text(json.dumps({'checks': checks, 'trials': trials}, indent=2)+'\n')
