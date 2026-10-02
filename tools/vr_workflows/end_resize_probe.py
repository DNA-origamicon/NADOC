"""Exercise the selected arrow through the ordinary trigger path and human profiles."""
import json
from tools.vr_workflows.audit_intervals import operation
import os
import sys
import time
from pathlib import Path
import numpy as np
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.demo_view import reveal, hold
from tools.vr_motion.metrics import rotate
from tools.vr_motion.model import multiply


def check_pixels(directory, color, *, points_override=None):
    from PIL import Image
    from tools.vr_motion.visual_checks import project
    evidence = json.loads((directory/'evidence.json').read_text())
    # A committed edit may clear the selection. Geometry visibility does not
    # require an arrow; colored preview checks still require the actual arrow.
    points = points_override
    if color and points is None:
        arrow = evidence['state']['end_resize']['arrows'][0]
        points = [arrow['origin'], arrow['tip']]
    checks = {}
    for name in ('left', 'right', 'mirror'):
        rgb = np.asarray(Image.open(directory / (name + '.png')).convert('RGB')).astype(float)
        if color == 'cyan':
            mask = (rgb[:,:,1] > 150) & (rgb[:,:,2] > 150) & (rgb[:,:,0] < 100)
        elif color == 'orange':
            mask = (rgb[:,:,0] > 150) & (rgb[:,:,1] > 40) & (rgb[:,:,1] < 140) & (rgb[:,:,2] < 70)
        elif color == 'yellow':
            mask = (rgb[:,:,0] > 150) & (rgb[:,:,1] > 150) & (rgb[:,:,2] < 100)
        else:
            mask = rgb.max(axis=2) > 60
        if color:
            eye = next(e for e in evidence['eyes'] if e['eye'] == (evidence['mirror']['eye'] if name == 'mirror' else name))
            projected = [project(point, eye) for point in points]
            assert all(p is not None for p in projected), 'Arrow is behind the eye'
            if name == 'mirror':
                vx, vy, vw, vh = evidence['mirror']['viewport_bottom_up']
                projected = [(vx + x * vw / eye['width'], rgb.shape[0] - vy - vh + y * vh / eye['height']) for x, y in projected]
            x0, y0 = np.floor(np.min(projected, axis=0) - 6).astype(int)
            x1, y1 = np.ceil(np.max(projected, axis=0) + 6).astype(int)
            x0, x1 = max(0, x0), min(mask.shape[1], x1)
            y0, y1 = max(0, y0), min(mask.shape[0], y1)
            mask = mask[y0:y1, x0:x1] if x1 > x0 and y1 > y0 else mask[:0,:0]
        checks[name] = int(mask.sum())
    if points_override is None:
        (directory/'pixel-check.json').write_text(json.dumps(checks, indent=2))
    assert min(checks.values()) >= 8, f'Visible {color or "geometry"} pixels missing: {checks}'



def run(socket, output, amount="12", frame="1"):
    amount = int(amount)
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic() + 30
    while not bridge.call('scrywrite_observe', {}).get('focused'):
        if time.monotonic() > deadline:
            raise RuntimeError('Viewer did not focus')
        time.sleep(.1)
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    from tools.vr_workflows.audit_representation import prepare as prepare_audit_representation
    prepare_audit_representation(live)
    preset = os.environ.get('NADOC_VR_PROFILE', 'steady_fast')
    trials = []
    def wait(predicate):
        deadline = time.monotonic() + 90
        while not predicate(live.state):
            if time.monotonic() > deadline:
                raise RuntimeError('Resize state timed out')
            try:live.frame()
            except TimeoutError:continue
            time.sleep(.05)
    def reach(point, acquired=None):
        trials.append(reach_target(live, point, preset, 7300 + len(trials),
            target_position=point, target_orientation=[0, 0, 0, 1], acquired=acquired))
        (out/'reaches.json').write_text(json.dumps(trials, indent=2))
    try:
        reveal(live)
        # Keep menus clear of the selected arrow using their normal buttons.
        for h in (0, 1):
            if live.state['sidebars'][h]['open']:
                live.button('menu', hand=h)
                live.frame()
        wait(lambda s: s.get('end_resize', {}).get('arrows'))
        if frame == "1":
            evidence, _ = live.capture_to(out/'before-framing', discard_source=True)
            eye = evidence['eyes'][0]
            arrow = live.state['end_resize']['arrows'][0]
            # Translate/rotate the generated helix into the actual tracked view using
            # the same grip gesture available to the user. Outside measured reaches.
            center = np.array(arrow['origin']) - np.array(arrow['bp_step']) * 20.5
            target = np.array(eye['position']) + rotate(eye['orientation_xyzw'], [0, 0, -1.05])
            turn = multiply(eye['orientation_xyzw'], [0, np.sin(np.pi/4), 0, np.cos(np.pi/4)])
            live.send('pose', hand=1, position=center.tolist(), orientation=[0,0,0,1])
            live.frame()
            live.send('button', hand=1, button='grip', pressed=True)
            live.frame()
            live.send('pose', hand=1, position=target.tolist(), orientation=turn)
            live.frame()
            live.send('button', hand=1, button='grip', pressed=False)
            live.frame()
            (out/'framing.json').write_text(json.dumps({'center':center.tolist(), 'target':target.tolist(), 'rotation':turn}))
        live.capture_to(out/'selected', discard_source=True)
        # Park after framing so the saved arrow is not highlighted by proximity.
        park = (np.array(live.state['head_position']) + [0, -1, 0]).tolist()
        live.send('pose', hand=1, position=park, orientation=[0,0,0,1])
        live.frame()
        live.capture_to(out/'selected-clear', discard_source=True)
        check_pixels(out/'selected-clear', 'cyan')
        try:
            check_pixels(out/'selected-clear', 'cyan', points_override=[[1000,1000,1000],[1001,1000,1000]])
        except AssertionError:
            pass
        else:
            raise AssertionError('Offscreen arrow unexpectedly passed the pixel check')
        arrow = live.state['end_resize']['arrows'][0]
        point = ((np.array(arrow['origin']) + arrow['tip']) / 2).tolist()
        reach(point, acquired=lambda s: s['end_resize']['nearby'])
        live.send('button', hand=1, button='trigger', pressed=True)
        live.frame()
        assert live.state['end_resize']['grabbing'], 'Arrow did not acquire trigger'
        start = np.array(live.state['hands'][1]['position'])
        reach((start + np.array(arrow['bp_step']) * amount).tolist())
        delta = live.state['end_resize']['delta']
        assert delta * amount > 0, 'Pull did not resize in the requested direction'
        live.capture_to(out/'preview', discard_source=True)
        check_pixels(out/'preview', 'yellow' if delta > 0 else 'orange')
        version = live.state['end_resize']['version']
        revision = live.state['scene_revision']
        with operation(live,'end_resize-commit'):
            live.send('button', hand=1, button='trigger', pressed=False)
            wait(lambda s: s['scene_revision'] > revision and s['end_resize']['version'] > version)
        live.capture_to(out/'committed', discard_source=True)
        check_pixels(out/'committed', None)
        hold(live, 'End resized by trigger pull')
        (out/'result.json').write_text(json.dumps({'delta': delta, 'offscreen_negative_control': True, 'state': live.state}, indent=2))
    except Exception:
        (out/'failure-state.json').write_text(json.dumps(live.state, indent=2))
        raise
    finally:
        live.send('button', hand=1, button='trigger', pressed=False)
        live.frame()


if __name__ == '__main__':
    run(*sys.argv[1:])
