"""Controller-docked six-gradient selection through ordinary touchpad input."""
import json
import time

import numpy as np
from PIL import Image

from tools.vr_motion.metrics import rotate
from tools.vr_motion.visual_checks import project
from tools.vr_workflows.menu_tour import click

# Independent desktop palette anchors; pixels must match the requested gradients,
# not merely contain colour from a tablet or molecular model behind the wheel.
STOPS = [
    [[68,1,84],[59,82,139],[33,144,140],[93,201,99],[253,231,37]],
    [[0,0,4],[81,18,124],[183,55,121],[252,137,97],[252,253,191]],
    [[48,18,59],[50,102,229],[26,199,194],[132,228,72],[236,203,40],[241,96,26],[122,4,3]],
    [[0,0,255],[0,255,255],[0,255,0],[255,255,0],[255,0,0]],
    [[63,185,80],[210,153,34],[248,81,73]],
    [[59,76,192],[144,178,254],[221,221,221],[246,158,131],[180,4,38]],
]


def pixels(directory, evidence, offset=None):
    menu = evidence['state']['simulation_menu']
    center = np.asarray(menu['palette_center']) + (np.zeros(3) if offset is None else offset)
    right, up = np.asarray(menu['palette_right']), np.asarray(menu['palette_up'])
    results = []
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(directory / (eye['eye'] + '.png')).convert('RGB'))
        for index in range(6):
            angle = index * np.pi / 3
            values = []
            errors = []
            for radius in [.06, .095, .13, .16]:
                point = center + (right * np.sin(angle) + up * np.cos(angle)) * radius
                point += np.cross(right, up) * .01
                xy = project(point, eye)
                if xy is None or not (2 <= xy[0] < rgb.shape[1]-2 and 2 <= xy[1] < rgb.shape[0]-2):
                    break
                x, y = map(int, xy)
                values.append(np.median(rgb[y-1:y+2, x-1:x+2].reshape(-1, 3), axis=0))
                stops = np.asarray(STOPS[index])
                t = np.clip((radius-.04)/.129, 0, 1) * (len(stops)-1)
                lo = min(int(t), len(stops)-2)
                expected = stops[lo] + (stops[lo+1]-stops[lo]) * (t-lo)
                errors.append(float(np.max(np.abs(values[-1]-expected))))
            visible = len(values) == 4 and max(errors) < 35
            results.append(dict(eye=eye['eye'], option=index, passed=bool(visible), colour_errors=errors))
    return dict(passed=bool(results) and all(r['passed'] for r in results), sectors=results)


def run(live, output, preset, trials):
    anchor, _ = live.capture_to(output/'anchor', files=['evidence.json'], discard_source=True)
    head = np.mean([e['position'] for e in anchor['eyes']], axis=0)
    q = anchor['eyes'][0]['orientation_xyzw']
    # Ordinary controller pose, held close enough to observe the popup. The
    # production dock still determines its offset/orientation; no hit target edits.
    position = head + rotate(q, [.20, 0, -.46])
    for option in range(6):
        click(live, 0, 'sim:local:palette', preset, trials)
        live.send('pose', hand=0, position=position.tolist(), orientation=q)
        live.send('trackpad_axis', hand=0, x=0, y=0)
        live.send('button', hand=0, button='trackpad', pressed=False)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            live.frame()
            if live.state['simulation_menu']['palette_pulses'] == 3:
                break
            time.sleep(.04)
        assert live.state['simulation_menu']['palette_pulses'] == 3
        angle = option * np.pi / 3
        live.send('trackpad_axis', hand=0, x=float(np.sin(angle)), y=float(np.cos(angle)))
        live.send('button', hand=0, button='trackpad', pressed=True)
        live.frame()
        assert live.state['simulation_menu']['palette_hover'] == option
        if option == 0:
            evidence, _ = live.capture_to(output/'wheel', files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
            result = pixels(output/'wheel', evidence)
            (output/'pixels.json').write_text(json.dumps(result, indent=2))
            assert result['passed'], result
            assert not pixels(output/'wheel', evidence, np.array([1000, 1000, 1000]))['passed']
            from tools.vr_motion.desktop_check import run as desktop_check
            delivery = desktop_check(live.bridge.socket_path, output/'desktop', live=live, reveal=True)
            (output/'delivery.json').write_text(json.dumps(delivery, indent=2))
            assert delivery['passed'], delivery
        live.send('button', hand=0, button='trackpad', pressed=False)
        live.frame()
        assert not live.state['simulation_menu']['palette_open']
        assert live.state['simulation_menu']['palette'] == option
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            live.frame()
            state = live.state['simulation_menu']
            if state['acknowledged'] >= state['sequence']:
                break
            time.sleep(.05)
        assert state['acknowledged'] >= state['sequence']
    (output/'result.json').write_text(json.dumps(live.state, indent=2))
