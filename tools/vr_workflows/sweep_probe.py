"""Real VR Sweep input tour; observation is used only for read-only targeting."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import time

import numpy as np
from PIL import Image

from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.metrics import rotate, sub
from tools.vr_motion.model import multiply
from tools.vr_motion.session import LiveSession
from tools.vr_motion.presets import FINAL_PRESETS
from tools.vr_motion.sweep_calibration import calibration_stroke
from tools.vr_workflows.extrude_sidebar import SidebarControls
from tools.vr_workflows.profile_input import aim_orientation
from tools.vr_workflows.menu_tour import click as click_sidebar
from tools.vr_workflows.sidebar_pointer_scroll import at_fraction
from tools.vr_workflows.demo_view import reveal
from tools.vr_workflows.profile_input import reach_target


class SweepControls(SidebarControls):
    def click(self, identifier):
        if not self.live.state.get('sweep', {}).get('active') or self.live.state['sweep']['step'] != 2:
            return super().click(identifier)
        # Sweep owns the right touchpad for its point radial menu, just as the
        # left sidebar uses pointer scrolling while its pad selects scope.
        for fraction in [None, *np.linspace(0, 1, 11)]:
            if fraction is not None:
                at_fraction(self.live, 1, float(fraction))
            if any(c.get('id') == identifier for c in self.live.state['controls']):
                click_sidebar(self.live, 1, identifier, self.preset, self.trials)
                (self.output/'sidebar-reaches.json').write_text(json.dumps(self.trials, indent=2))
                return
        raise RuntimeError('Missing Sweep sidebar control: '+identifier)


def green_stroke_pixels(directory, evidence, points=None):
    """Require green stroke/pointer pixels near projected samples in both eyes."""
    if points is None:
        points = evidence['state']['sweep']['stroke_world']
    assert len(points) >= 5
    result = {}
    for eye in evidence['eyes']:
        rgb = np.asarray(Image.open(directory/(eye['eye']+'.png')).convert('RGB'))
        q = eye['orientation_xyzw']
        left, right, up, down = np.tan(eye['fov_left_right_up_down'])
        hits = 0
        for point in points[::max(1, len(points)//20)]:
            local = rotate([-q[0], -q[1], -q[2], q[3]], sub(point, eye['position']))
            if local[2] >= -.001:
                continue
            x = int((local[0]/-local[2]-left)/(right-left)*eye['width'])
            y = int((up-local[1]/-local[2])/(up-down)*eye['height'])
            if not 8 <= x < eye['width']-8 or not 8 <= y < eye['height']-8:
                continue
            patch = rgb[y-8:y+9, x-8:x+9].astype(int)
            hits += int(((patch[:, :, 1] > 130) & (patch[:, :, 1] > patch[:, :, 0]*1.3)
                         & (patch[:, :, 1] > patch[:, :, 2]*1.2)).sum())
        result[eye['eye']] = hits
        assert hits >= 15, ('Green Sweep line missing', eye['eye'], hits)
    return result


def s_shape_report(points, orientation):
    """Check both intended lobes after smoothing, independent of model axes.

    Endpoint chord removal keeps a tilted stroke from passing as an S. Distances
    are in tracking metres, so the same criterion applies at any model scale.
    """
    points = np.asarray(points, dtype=float)
    inverse = [-orientation[0], -orientation[1], -orientation[2], orientation[3]]
    local = np.asarray([rotate(inverse, p-points[0]) for p in points])
    progress = -local[:, 2]
    extent = float(progress[-1])
    if extent <= .1:
        return {'passed': False, 'forward_extent_m': extent}
    phase = progress/extent
    lateral = local[:, 0]-phase*local[-1, 0]
    first = lateral[(phase > .05) & (phase < .5)]
    second = lateral[(phase > .5) & (phase < .95)]
    positive = float(max(first, default=0))
    negative = float(min(second, default=0))
    return {'passed': positive >= .012 and negative <= -.012,
            'forward_extent_m': extent, 'first_lobe_m': positive,
            'second_lobe_m': negative, 'minimum_lobe_m': .012}


def run(socket, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    bridge = Bridge(socket)
    deadline = time.monotonic()+30
    while True:
        try:
            if bridge.call('scrywrite_observe', {}).get('focused'):
                break
        except OSError:
            pass
        if time.monotonic() > deadline:
            raise RuntimeError('Viewer did not become focused')
        time.sleep(.1)
    live = LiveSession(bridge, physical=True, allow_transactions=True)
    from tools.vr_workflows.audit_representation import wait_startup
    wait_startup(live)
    controls = SweepControls(live, output, 'steady_fast')
    profiles = FINAL_PRESETS if os.environ.get('NADOC_VR_SWEEP_VALIDATE', '1') == '1' else ['steady_fast']
    report = {'profiles': list(profiles), 'shape': 's-curve', 'point_edits': []}

    def wait(predicate, timeout=20):
        until = time.monotonic()+timeout
        while not predicate(live.state):
            if time.monotonic() > until:
                raise RuntimeError('Sweep feedback timed out')
            live.frame()
            time.sleep(.02)

    def save(name):
        (output/(name+'.json')).write_text(json.dumps(live.state, indent=2))

    def menu():
        if not live.state['sidebars'][1]['open']:
            live.button('menu', hand=1)
            wait(lambda state: state['sidebars'][1]['open'])

    def settle(seconds=.4):
        # Menu opening, backend feedback and diagnostic readback are outside
        # timed profile gestures. No tolerance or motion sample is changed.
        until = time.monotonic()+seconds
        while time.monotonic() < until:
            # A demonstration can pause with Trigger held. Renew the input
            # lease at the unchanged pose so review cannot end the stroke.
            hand = live.state['hands'][1]
            live.send('pose', hand=1, position=hand['position'], orientation=hand['orientation_xyzw'])
            live.frame()
            time.sleep(.025)

    def pose(position, orientation):
        live.send('pose', hand=1, position=list(position), orientation=list(orientation))
        live.frame()

    def capture(name):
        evidence, _ = live.capture_to(output/name,
            files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
        assert evidence['xr_end_frame_succeeded']
        assert all(side['layout'] == 'valid' for side in evidence['state']['sidebars'] if side['open'])
        if os.environ.get('NADOC_VR_DEMO') == '1':
            reveal(live)
            print('Review: '+name.replace('-', ' '), flush=True)
            settle(float(os.environ.get('NADOC_VR_DEMO_HOLD', '3')))
        return evidence

    def radial(axis):
        # Point editing uses the same right touchpad press/slide/release gesture.
        if live.state['sidebars'][1]['open']:
            live.button('menu', hand=1)
        live.send('trackpad_axis', hand=1, x=0, y=0)
        live.send('button', hand=1, button='trackpad', pressed=True)
        live.frame()
        live.send('trackpad_axis', hand=1, x=axis[0], y=axis[1])
        live.frame()
        live.send('button', hand=1, button='trackpad', pressed=False)
        live.frame()

    try:
        anchor = capture('anchor')
        q = anchor['eyes'][0]['orientation_xyzw']
        head = np.asarray(live.state['head_position'])
        pose(head+rotate(q, [.2, -.25, -.35]), q)
        menu()
        controls.click('tab:tools')
        controls.click('tool-sweep')
        assert live.state['sweep']['active'] and live.state['sweep']['step'] == 1
        controls.click('sweep:recenter')
        settle()
        for row, column in [(0, 0), (0, 1)]:
            live.send('aim_lattice', hand=1, row=row, column=column)
            live.frame()
            assert live.state['extrude']['hover'] == [row, column]
            live.button('trigger')
        assert sorted(live.state['extrude']['cells']) == [[0, 0], [0, 1]]
        capture('painted-footprint')
        controls.click('sweep:confirm')
        wait(lambda state: state['sweep']['step'] == 2)
        assert len(live.state['sweep']['points_nm']) == 2
        assert live.state['sweep']['preview_count'] > 0
        capture('initial-points')
        controls.click('sweep:point:1')
        before = live.state['sweep']['points_nm'][1][0]
        controls.click('sweep:axis:1:0:1')
        assert live.state['sweep']['points_nm'][1][0] > before
        # Close the sidebar so the model's independently raycast point owns input.
        live.button('menu', hand=1)
        target = np.asarray(live.state['sweep']['points_world'][1])
        toward_head = head-target
        origin = target+.25*toward_head/np.linalg.norm(toward_head)
        direction = aim_orientation(origin.tolist(), target.tolist())
        pose(origin, direction)
        wait(lambda state: state['sweep']['hover_point'] == 1)
        pointer = capture('point-pointer')
        interior = [(origin*(1-u)+target*u).tolist() for u in np.linspace(.2, .8, 12)]
        pixels = green_stroke_pixels(output/'point-pointer', pointer, interior)
        (output/'point-pointer'/'pixels.json').write_text(json.dumps(pixels))
        old = np.asarray(live.state['sweep']['points_nm'][1])
        live.send('button', hand=1, button='trigger', pressed=True)
        live.frame()
        assert live.state['sweep']['dragging']
        pose(origin+rotate(q, [.035, .015, 0]), direction)
        live.send('button', hand=1, button='trigger', pressed=False)
        live.frame()
        assert np.linalg.norm(np.asarray(live.state['sweep']['points_nm'][1])-old) > .1
        # Two-item radial: left deletes the last point, right adds a point.
        # Select a different point to distinguish this from Delete Selected.
        before_add = live.state['sweep']['points_nm']
        radial((.8, 0))
        assert len(live.state['sweep']['points_nm']) == 3
        menu()
        controls.click('sweep:point:1')
        assert live.state['sweep']['selected'] == 1
        radial((-.8, 0))
        assert live.state['sweep']['points_nm'] == before_add
        assert live.state['sweep']['selected'] == 1
        # Presentation setup through the normal model grip. Keep the draft
        # upright and in front of the tracked eye before the measured strokes;
        # neither headset tracking nor canonical points/configuration changes.
        for hand in (0, 1):
            if live.state['sidebars'][hand]['open']:
                live.button('menu', hand=hand)
        save('before-draft-framing')
        draft_before = live.state['sweep']['points_nm']
        sequence_before = live.state['config_sequence']
        origin_before = np.asarray(live.state['sweep']['origin_world'])
        framed_origin = head+rotate(q, [-.10, -.16, -.8])
        pose(origin_before, q)
        live.send('button', hand=1, button='grip', pressed=True)
        live.frame()
        pose(framed_origin, q)
        live.send('button', hand=1, button='grip', pressed=False)
        live.frame()
        assert live.state['sweep']['points_nm'] == draft_before
        assert live.state['config_sequence'] == sequence_before
        assert np.linalg.norm(np.asarray(live.state['sweep']['origin_world'])-framed_origin) < .002
        save('after-draft-framing')
        sketch_q = multiply(q, [math.sin(math.pi/4), 0, 0, math.cos(math.pi/4)])
        report['observation_setup'] = {'original_origin_world': origin_before.tolist(),
            'framed_origin_world': framed_origin.tolist(), 'sketch_orientation_xyzw': sketch_q,
            'method': 'ordinary model grip translation; upright stroke frame; unchanged points/configuration'}
        for preset in profiles:
            menu()
            controls.click('sweep:free-draw')
            assert live.state['sweep']['free_draw_armed']
            assert len(live.state['sweep']['points_nm']) <= 1
            if live.state['sidebars'][1]['open']:
                live.button('menu', hand=1)
            trace = calibration_stroke('s-curve', preset, 11, rate_hz=20)
            (output/f'input-stroke-{preset}.json').write_text(json.dumps(trace, indent=2))
            home = head+rotate(q, [-.07, -.18, -.65])
            pose(home, sketch_q)
            live.send('button', hand=1, button='trigger', pressed=True)
            live.frame()
            assert live.state['sweep']['drawing']
            samples = trace['samples']
            begun = time.monotonic()
            delivery = []
            for index, sample in enumerate(samples[1:], 1):
                time.sleep(max(0, begun+sample['t']-time.monotonic()))
                lag = time.monotonic()-begun-sample['t']
                if lag > .15:
                    raise TimeoutError(f'Sweep profile playback late by {lag:.3f}s')
                hand = sample['hands']['right']
                pose(home+rotate(sketch_q, hand['position']), multiply(sketch_q, hand['orientation']))
                delivery.append(dict(t=sample['t'], lag_s=lag, frame=live.state['frame']))
            (output/f'delivery-{preset}.json').write_text(json.dumps(delivery, indent=2))
            # Diagnostic readback is outside the measured controller trajectory.
            name = f'free-draw-glow-{preset}'
            eye = capture(name)
            pixels = green_stroke_pixels(output/name, eye)
            (output/name/'pixels.json').write_text(json.dumps(pixels))
            live.send('button', hand=1, button='trigger', pressed=False)
            live.frame()
            wait(lambda state: not state['sweep']['drawing'])
            assert not live.state['sweep']['free_draw_armed']
            assert 2 <= len(live.state['sweep']['points_nm']) <= 64
            assert live.state['sweep']['preview_count'] > 0
            wait(lambda state: state['sweep']['ready'])
            settle()
            save(f'smoothed-{preset}')
            shape = s_shape_report(live.state['sweep']['points_world'], sketch_q)
            (output/f's-shape-{preset}.json').write_text(json.dumps(shape, indent=2))
            assert shape['passed'], ('S shape lost an intended lobe', preset, shape)
            capture(f'smoothed-s-shape-{preset}')
            # Edit a fitted interior knot, proving Free Draw produced ordinary
            # editable points. Its first lobe is easy to distinguish in stereo.
            fitted = np.asarray(live.state['sweep']['points_world'])
            inverse = [-sketch_q[0], -sketch_q[1], -sketch_q[2], sketch_q[3]]
            lateral = [rotate(inverse, p-fitted[0])[0] for p in fitted[1:-1]]
            selected = 1+int(np.argmax(lateral))
            target = fitted[selected]
            toward_head = head-target
            origin = target+.25*toward_head/np.linalg.norm(toward_head)
            direction = aim_orientation(origin.tolist(), target.tolist())
            pose(origin, direction)
            wait(lambda state: state['sweep']['hover_point'] == selected)
            pointer_name = f'fitted-point-pointer-{preset}'
            pointer = capture(pointer_name)
            interior = [(origin*(1-u)+target*u).tolist() for u in np.linspace(.2, .8, 12)]
            pixels = green_stroke_pixels(output/pointer_name, pointer, interior)
            (output/pointer_name/'pixels.json').write_text(json.dumps(pixels))
            before_drag = np.asarray(live.state['sweep']['points_nm'])
            live.send('button', hand=1, button='trigger', pressed=True)
            live.frame()
            assert live.state['sweep']['dragging'] and live.state['sweep']['selected'] == selected
            destination = origin+rotate(q, [.04, .015, 0])
            drag = reach_target(live, destination.tolist(), preset, 7200,
                target_position=destination.tolist(), target_orientation=direction)
            live.send('button', hand=1, button='trigger', pressed=False)
            live.frame()
            wait(lambda state: state['sweep']['ready'])
            after_drag = np.asarray(live.state['sweep']['points_nm'])
            assert np.linalg.norm(after_drag[selected]-before_drag[selected]) > .1
            assert np.array_equal(np.delete(after_drag, selected, axis=0), np.delete(before_drag, selected, axis=0))
            assert np.linalg.norm(np.asarray(live.state['sweep']['points_world'][selected])-target) > .01
            capture(f'fitted-point-dragged-{preset}')
            menu()
            controls.click(f'sweep:point:{selected}')
            numeric_before = float(live.state['sweep']['points_nm'][selected][1])
            capture(f'fitted-xyz-before-{preset}')
            controls.click(f'sweep:axis:{selected}:1:1')
            numeric_after = float(live.state['sweep']['points_nm'][selected][1])
            assert numeric_after > numeric_before
            assert live.state['sweep']['points_nm'][0] == [0, 0, 0]
            wait(lambda state: state['sweep']['ready'])
            capture(f'fitted-xyz-after-{preset}')
            report['point_edits'].append({'preset': preset, 'index': selected,
                'shape_before_edit': shape, 'points_before_drag_nm': before_drag.tolist(),
                'points_after_drag_nm': after_drag.tolist(), 'numeric_axis': 'Y',
                'numeric_before_nm': numeric_before, 'numeric_after_nm': numeric_after,
                'drag_reach': drag})
            (output/'tour-report.json').write_text(json.dumps(report, indent=2))
        capture('editable-smoothed-stroke')
        save('ready-to-confirm')
        controls.click('sweep:confirm')
        wait(lambda state: state['status'] == 'COMMITTED' and bool(state['committed_feature_id']), 45)
        assert not live.state['sweep']['active']
        capture('committed')
        # Review presentation is outside the measured authoring gestures. The
        # existing grip-based workflow verifies unchanged design/config state
        # and useful authored-pixel coverage in both submitted eyes.
        for hand in (0, 1):
            if live.state['sidebars'][hand]['open']:
                live.button('menu', hand=hand)
        settle()
        live.capture_to(output/'committed-before-review', discard_source=True)
        from tools.vr_workflows.review_view import improve_review
        improve_review(live, output/'committed-before-review', output/'design-review', expected_groups=1)
        save('committed')
        # Move the reviewed molecule aside through an ordinary scene grip so
        # it cannot obscure the occupied cells in the painter behind it.
        revision = live.state['scene_revision']
        origin = head+rotate(q, [.2, -.25, -.35])
        pose(origin, q)
        live.send('button', hand=1, button='grip', pressed=True); live.frame()
        pose(origin+rotate(q, [-.7, 0, 0]), q)
        live.send('button', hand=1, button='grip', pressed=False); live.frame()
        assert live.state['scene_revision'] == revision
        # Reopening either painter must display and reject the newly occupied
        # footprint. Exercise real controller reaches, including noisy profiles.
        occupancy_trials = []
        for tool in ('sweep', 'extrude'):
            for preset in profiles:
                pose(origin, q)
                menu()
                controls.click('tab:tools')
                controls.click('tool-'+tool)
                wait(lambda state: state['extrude']['open'])
                assert sorted(live.state['extrude']['occupied_cells']) == [[0,0],[0,1]]
                cell = next(c for c in live.state['extrude']['visible_cells'] if (c['row'],c['column'])==(0,0))
                assert cell['occupied']
                trial = reach_target(live, cell['position'], preset, 9300)
                live.button('trigger');live.frame()
                assert [0,0] not in live.state['extrude']['cells']
                occupancy_trials.append({'tool':tool,'preset':preset,'reach':trial,
                                         'cells_after_click':live.state['extrude']['cells']})
                capture(f'occupied-{tool}-{preset}')
                controls.click('sweep:cancel' if tool=='sweep' else 'extrude:cancel')
        report['occupancy'] = occupancy_trials
        report['passed'] = True
        (output/'tour-report.json').write_text(json.dumps(report, indent=2))
    except Exception:
        report['passed'] = False
        (output/'tour-report.json').write_text(json.dumps(report, indent=2))
        save('failure-state')
        raise
    finally:
        live.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket')
    parser.add_argument('output')
    args = parser.parse_args()
    run(args.socket, args.output)
