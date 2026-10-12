"""Measured slow/fast range-wheel drags following unchanged profile reaches."""
import copy
import json
import time

import numpy as np

from tools.vr_workflows.menu_tour import click, find_control
from tools.vr_workflows.menu_pixels import check
from tools.vr_workflows.profile_input import reach_target
from tools.vr_workflows.control_approach import control_approach


def settled(live):
    until = time.monotonic() + 15
    while time.monotonic() < until:
        live.frame()
        state = live.state['simulation_menu']
        if state['acknowledged'] >= state['sequence']:
            return state
        time.sleep(.05)
    raise AssertionError('Range edit was not acknowledged by desktop')


def run(live, output, preset, trials):
    results = []
    for identifier, field, direction in [(300, 'first', 1), (301, 'last', -1), (302, 'interval', 1)]:
        click(live, 0, 'sim:local:t:309', preset, trials)
        settled(live)
        control_id = f'sim:local:t:{identifier}'
        for speed, distance, duration, samples in [('slow', .014, 1.2, 30), ('fast', .10, .12, 6)]:
            control = find_control(live, 0, control_id)
            # The sidebar rectangle includes the slot around the cylinder. Use
            # the wheel's own physical-surface highlight as acquisition feedback.
            for attempt in range(3):
                trial = reach_target(live, control['position'], preset, 4200 + len(trials),
                    acquired=lambda state: state['simulation_menu']['range_hover'] == identifier,
                    target_position=control_approach(control, live.state['hands'][1]['position']))
                trial.update(control=control_id, attempt=attempt+1, feedback='physical cylinder')
                trials.append(trial)
                if trial['acquired_with_feedback']:
                    break
            else:
                raise AssertionError(f'{preset}: {control_id} cylinder was not acquired')
            up = np.asarray(control['hit_half_up']) / .034
            pose = dict(live.state['hands'][1])
            origin = np.asarray(pose['position'])
            before_state = dict(live.state['simulation_menu'])
            before = before_state[field]
            headroom = before_state['last'] - before if field == 'first' else before - before_state['first'] if field == 'last' else before_state['available'] - before
            live.send('button', hand=1, button='trigger', pressed=True)
            live.frame()
            assert live.state['simulation_menu']['range_wheel'] == identifier
            started = time.monotonic()
            trace = []
            try:
                for n in range(1, samples + 1):
                    time.sleep(max(0, started + duration * n / samples - time.monotonic()))
                    position = origin + up * direction * distance * n / samples
                    live.send('pose', hand=1, position=position.tolist(), orientation=pose['orientation_xyzw'])
                    live.frame()
                    trace.append(dict(t=time.monotonic()-started, state=dict(live.state['simulation_menu'])))
            finally:
                live.send('button', hand=1, button='trigger', pressed=False)
                live.frame()
            state = settled(live)
            delta = (state[field] - before) * direction
            result = dict(field=field, speed=speed, before=before, after=state[field], delta=delta, trace=trace)
            results.append(result)
            (output/'gestures.json').write_text(json.dumps(results, indent=2))
            assert not state['popup'] and state['range_wheel'] == -1
            if speed == 'slow':
                assert delta == min(1, headroom), result
            else:
                assert delta >= min(10 if state['available'] >= 100 else 2, headroom), result
            assert 1 <= state['first'] <= state['last'] <= state['available']
            assert 1 <= state['interval'] <= state['available']
    click(live, 0, 'sim:local:t:309', preset, trials)
    settled(live)
    # Move the ray clear so wheel pixels are the unhighlighted cyan cylinders.
    live.send('pose', hand=1, position=[0, -1, 0], orientation=[0, 1, 0, 0])
    live.frame()
    evidence, _ = live.capture_to(output/'wheels', files=['left.png', 'right.png', 'mirror.png', 'evidence.json'], discard_source=True)
    visible = check(output/'wheels', evidence)
    rows = [r for r in visible['controls'] if r['id'] in [f'sim:local:t:{i}' for i in (300, 301, 302)]]
    (output/'pixels.json').write_text(json.dumps(rows, indent=2))
    assert len(rows) == 6 and all(r['passed'] for r in rows), rows
    outside = copy.deepcopy(evidence)
    for control in outside['state']['controls']:
        control['position'] = [1000, 1000, 1000]
    assert not check(output/'wheels', outside)['passed']
    from tools.vr_motion.desktop_check import run as desktop_check
    delivery = desktop_check(live.bridge.socket_path, output/'desktop', live=live, reveal=True)
    (output/'delivery.json').write_text(json.dumps(delivery, indent=2))
    assert delivery['passed'], delivery
