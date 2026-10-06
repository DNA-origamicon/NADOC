"""Production left-pad selection, release transactions and stereo highlight checks."""
import json
import time
import numpy as np
from PIL import Image
from tools.vr_motion.model import reach
from tools.vr_motion.presets import PRESETS
from tools.vr_motion.metrics import rotate, sub
from .profile_input import reach_target

LEVELS = ('default', 'cluster', 'strand', 'domain', 'xover', 'base')
AXES = ((0, .8), (.69282, .4), (.69282, -.4), (0, -.8), (-.69282, -.4), (-.69282, .4))


def thumb_samples(preset, start, target, seed):
    """Normalized pad-space stress path using existing profile timing and noise.

    Controller reaches still use physical metres; this path is dimensionless
    thumb travel, not a claim about measured human thumb biomechanics.
    """
    duration, profile = PRESETS[preset]
    path = reach([*start, 0], [*target, 0], start_q=[0, 0, 0, 1],
                 target_q=[0, 0, 0, 1], duration_s=duration, rate_hz=20,
                 seed=seed, profile=profile)
    return [dict(t=s['t'], axis=[max(-1, min(1, x)) for x in s['hands']['right']['position'][:2]])
            for s in path['samples']]


def amber_pixels(rgb, eye, center):
    q = eye['orientation_xyzw']
    local = rotate([-q[0], -q[1], -q[2], q[3]], sub(center, eye['position']))
    if local[2] >= -.001:
        return 0
    left, right, up, down = np.tan(eye['fov_left_right_up_down'])
    x = int((local[0] / -local[2] - left) / (right - left) * eye['width'])
    y = int((up - local[1] / -local[2]) / (up - down) * eye['height'])
    if not 25 <= x < eye['width'] - 25 or not 25 <= y < eye['height'] - 25:
        return 0
    crop = rgb[y-25:y+26, x-25:x+26]
    return int(((crop[:, :, 0] > 170) & (crop[:, :, 1] > 95)
                & (crop[:, :, 2] < 110)).sum())


def capture(live, output, name, index, key="selection_wheel"):
    dest = output / name
    evidence, _ = live.capture_to(dest, files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
    assert evidence['xr_end_frame_succeeded']
    center = evidence['state'][key]['items'][index]['center']
    pixels = {}
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(dest / (eye['eye']+'.png')).convert('RGB'))
        pixels[eye['eye']] = amber_pixels(rgb, eye, center)
        assert pixels[eye['eye']] >= 8, ('Selection highlight missing', name, eye['eye'], pixels)
        assert amber_pixels(np.zeros_like(rgb), eye, center) == 0
        assert amber_pixels(rgb, eye, [1000, 1000, 1000]) == 0
    (dest / 'pixels.json').write_text(json.dumps(pixels, indent=2)+'\n')
    # Capture/review time is outside the measured input interval.
    until = time.monotonic() + .3
    while time.monotonic() < until:
        live.frame()
        time.sleep(.02)


def run(live, _catalog, output, preset):
    checks, trials = {}, []
    def press(value):
        live.send('button', hand=0, button='trackpad', pressed=value)
        live.frame()
    def axis(value):
        live.send('trackpad_axis', hand=0, x=value[0], y=value[1])
        live.frame()
    def slide(start, target, seed):
        path = thumb_samples(preset, start, target, seed)
        trial = {'samples': []};trials.append(trial)
        begun = time.monotonic()
        for sample in path:
            time.sleep(max(0, begun+sample['t']-time.monotonic()))
            lag = time.monotonic()-begun-sample['t']
            if lag > .15:
                raise TimeoutError(f'Thumb profile playback late by {lag:.3f}s')
            axis(sample['axis'])
            trial['samples'].append({**sample, 'lag_s': lag,
                'hovered': live.state['selection_wheel']['hovered'],
                'level_sequence': live.state['level_sequence'],
                'haptic_requests': live.state['haptic_requests'][0]})
    try:
        press(False)
        for hand in (0, 1):
            if live.state['sidebars'][hand]['open']:
                live.button('menu', hand=hand)
        anchor, _ = live.capture_to(output / 'anchor', files=['evidence.json'], discard_source=True)
        q = anchor['eyes'][0]['orientation_xyzw']
        head = live.state['head_position']
        target = [a+b for a, b in zip(head, rotate(q, [-.12, -.10, -.65]))]
        trials.append(reach_target(live, target, preset, 500, target_position=target, target_orientation=q, hand=0))
        # Keep the other controller away from the palette's pixels.
        live.send('pose', hand=1, position=[head[0]+.5, head[1]-.7, head[2]], orientation=q)
        live.frame()
        identities = (live.state['selection_identity'], live.state['owner_tokens'])
        assert [i['level'] for i in live.state['selection_wheel']['items']] == list(LEVELS)
        for index, target_axis in enumerate(AXES):
            before = live.state['level_sequence']
            haptics = live.state['haptic_requests'][0]
            axis((0, 0));press(True)
            assert live.state['selection_wheel']['open'] and live.state['selection_wheel']['hovered'] is None
            assert live.state['hands'][0]['input_owner'] == 'selection-wheel'
            slide((0, 0), target_axis, 600+index)
            assert live.state['selection_wheel']['hovered'] == index
            assert live.state['level_sequence'] == before
            assert live.state['haptic_requests'][0] > haptics
            stable = live.state['haptic_requests'][0]
            live.frame();live.frame()
            assert live.state['haptic_requests'][0] == stable
            live.button('trigger', hand=0)
            assert live.state['level_sequence'] == before
            capture(live, output, LEVELS[index], index)
            press(False)
            assert not live.state['selection_wheel']['open']
            assert live.state['selection_level'] == LEVELS[index]
            assert live.state['level_sequence'] == before+1
            assert live.state['menu'] == 'closed'
            assert identities == (live.state['selection_identity'], live.state['owner_tokens'])
            checks[LEVELS[index]] = True
        # Change direction while held: only the last held sector can commit.
        before = live.state['level_sequence']
        axis(AXES[1]);press(True)
        pulse = live.state['haptic_requests'][0]
        slide(AXES[1], AXES[2], 701)
        assert live.state['haptic_requests'][0] > pulse
        assert live.state['level_sequence'] == before
        press(False)
        assert live.state['selection_level'] == 'strand' and live.state['level_sequence'] == before+1
        checks['hover_transition'] = True
        # Center cancels; a stale edge value received on release cannot select.
        before = live.state['level_sequence']
        axis(AXES[3]);press(True);axis((0, 0));press(False)
        assert live.state['level_sequence'] == before
        checks['center_cancel'] = True
        # The left pad keeps its selection role even with both sidebars open.
        for hand in (0, 1):live.button('menu', hand=hand)
        panels = [(s['open'], s['tab'], s['offset']) for s in live.state['sidebars']]
        axis(AXES[0]);press(True);press(False)
        assert live.state['selection_level'] == 'default'
        assert panels == [(s['open'], s['tab'], s['offset']) for s in live.state['sidebars']]
        assert live.state['sidebars'][0]['input_mode'] == 'pointer'
        checks['sidebar_independence'] = True
        # General Tools no longer contains a second scope picker.
        assert not any(c['id'].startswith('select:') for c in live.state['controls'])
        for hand in (0, 1):live.button('menu', hand=hand)
        axis(AXES[0]);press(True)
        capture(live, output, 'review', 0)
        # Caller captures actual desktop delivery before releasing owned inputs.
        return {'passed': all(checks.values()), 'checks': checks}
    finally:
        (output / 'selection-wheel.json').write_text(json.dumps({'checks': checks, 'trials': trials}, indent=2)+'\n')
        # On failure, never leave the pad held; on success retain it for review.
        if not all(checks.get(k) for k in (*LEVELS, 'center_cancel', 'sidebar_independence')):
            press(False)


def review(live, alive, sleep=time.sleep):
    """Keep the owned demo gesture visible; caller always releases in finally."""
    while alive():
        live.send('trackpad_axis', hand=0, x=0, y=.8)
        live.frame()
        sleep(.5)
