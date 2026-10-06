"""Right-pad gesture and real command publication in an isolated metadata fixture."""
import json
import time
from .selection_wheel_check import thumb_samples, capture
from .profile_input import reach_target
from tools.vr_motion.metrics import rotate

LABELS = ('LIGATE', 'NICK', 'UNDO', 'REDO')
AXES = ((.8, 0), (0, .8), (-.8, 0), (0, -.8))


def slide(live, index, preset, trials, start=(0, 0)):
    trial = {'kind': 'right_thumb', 'samples': []}
    trials.append(trial)
    begun = time.monotonic()
    for sample in thumb_samples(preset, start, AXES[index], 850+len(trials)):
        time.sleep(max(0, begun+sample['t']-time.monotonic()))
        lag = time.monotonic()-begun-sample['t']
        if lag > .15:
            raise TimeoutError(f'Thumb profile playback late by {lag:.3f}s')
        live.send('trackpad_axis', hand=1, x=sample['axis'][0], y=sample['axis'][1])
        live.frame()
        trial['samples'].append({**sample, 'lag_s': lag, 'hovered': live.state['radial_edit']['hovered']})
    assert live.state['radial_edit']['hovered'] == index


def run(live, _catalog, output, preset, events):
    checks, trials = {}, []
    def press(value):
        live.send('button', hand=1, button='trackpad', pressed=value);live.frame()
    def axis(value):
        live.send('trackpad_axis', hand=1, x=value[0], y=value[1]);live.frame()
    def request():
        return json.loads(events.read_text())['ligation']
    def acknowledge():
        version = live.state['ligation']['version']+1
        events.with_suffix(events.suffix+'.ligation').write_text(f'NADOC_LIGATION_1 {version} READY 0\n')
        deadline = time.monotonic()+5
        while live.state['ligation']['version'] != version:
            assert time.monotonic() < deadline
            live.frame();time.sleep(.02)
    try:
        axis((0, 0));press(False)
        for hand in (0, 1):
            if live.state['sidebars'][hand]['open']:live.button('menu', hand=hand)
        anchor, _ = live.capture_to(output/'anchor', files=['evidence.json'], discard_source=True)
        q = anchor['eyes'][0]['orientation_xyzw'];head = live.state['head_position']
        target = [a+b for a, b in zip(head, rotate(q, [.12, -.10, -.65]))]
        trials.append(reach_target(live, target, preset, 800, target_position=target, target_orientation=q, hand=1))
        live.send('pose', hand=0, position=[head[0]-.5, head[1]-.7, head[2]], orientation=q);live.frame()
        assert [i['label'] for i in live.state['radial_edit']['items']] == list(LABELS)
        acknowledge()
        for index, label in enumerate(LABELS):
            before = request();level = live.state['level_sequence']
            axis((0, 0));press(True)
            assert live.state['radial_edit']['open'] and live.state['radial_edit']['hovered'] is None
            assert live.state['hands'][1]['input_owner'] == 'radial'
            pulse = live.state['haptic_requests'][1]
            slide(live, index, preset, trials)
            assert request() == before and live.state['level_sequence'] == level
            assert live.state['haptic_requests'][1] > pulse
            pulse = live.state['haptic_requests'][1]
            live.frame();live.frame()
            assert live.state['haptic_requests'][1] == pulse
            live.button('trigger', hand=1)
            assert request() == before and live.state['level_sequence'] == level
            capture(live, output, label.lower(), index, key='radial_edit')
            press(False)
            trials.append({'kind': 'release', 'label': label, 'before': before, 'after': request(),
                           'haptic_requests': live.state['haptic_requests'][1]})
            assert not live.state['radial_edit']['open'] and live.state['menu'] == 'closed'
            assert live.state['haptic_requests'][1] == pulse+1
            if index < 2:
                assert live.state['ligation']['active'] == (index == 0)
                assert live.state['ligation']['nick_active'] == (index == 1)
            else:
                assert request()['sequence'] == before['sequence']+1 and request()['action'] == label.lower()
                assert live.state['ligation']['waiting']
                # A second held/released history gesture while pending is inert.
                axis(AXES[index]);press(True);press(False)
                assert request()['sequence'] == before['sequence']+1
                acknowledge()
            checks[label] = True
        # Retargeting a held pad only commits the last sector, without early activation.
        before = request();axis(AXES[2]);press(True)
        slide(live, 3, preset, trials, start=AXES[2])
        assert request() == before
        press(False)
        assert request()['sequence'] == before['sequence']+1 and request()['action'] == 'redo'
        acknowledge();checks['retarget'] = True
        before = request();axis(AXES[2]);press(True);axis((0, 0));press(False)
        assert request() == before;checks['center_cancel'] = True
        axis(AXES[2]);press(True);live.button('menu', hand=1)
        assert not live.state['radial_edit']['open']
        press(False);live.button('menu', hand=1)
        assert request() == before;checks['menu_cancel'] = True
        # Both pads can be held without stealing each other's pending sector.
        live.send('trackpad_axis', hand=0, x=0, y=.8)
        live.send('button', hand=0, button='trackpad', pressed=True)
        axis(AXES[2]);press(True)
        assert live.state['selection_wheel']['hovered'] == 0 and live.state['radial_edit']['hovered'] == 2
        axis((0, 0));press(False)
        live.send('button', hand=0, button='trackpad', pressed=False);live.frame()
        assert live.state['selection_level'] == 'default' and request() == before
        checks['independent_hands'] = True
        # Right-menu focus keeps ownership while that sidebar is open.
        live.button('menu', hand=1);axis((0, .8));press(True)
        assert not live.state['radial_edit']['open']
        press(False);live.button('menu', hand=1)
        checks['sidebar_focus'] = True
        axis(AXES[2]);press(True)
        capture(live, output, 'review', 2, key='radial_edit')
        return {'passed': all(checks.values()), 'checks': checks}
    finally:
        (output/'edit-wheel.json').write_text(json.dumps({'checks': checks, 'trials': trials}, indent=2)+'\n')
        if not checks.get('sidebar_focus'):press(False)


def review(live, alive, sleep=time.sleep):
    while alive():
        live.send('trackpad_axis', hand=1, x=-.8, y=0);live.frame();sleep(.5)
