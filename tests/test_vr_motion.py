"""Motion properties, coordinate/timing contracts, and failure-safe live delivery."""
import copy
import json
import math
from pathlib import Path
import subprocess
import tempfile
import time

import pytest

from tools.vr_motion.behavior import catalog, import_behavior, register
from tools.vr_motion.model import Profile, reach, summary, validate_trace
from tools.vr_motion.playback import play_live, witness


def ideal(**kw):
    return reach([0, 1, 0], [0.2, 1, 0], profile=Profile(
        position_sigma_m=0, rotation_sigma_deg=0, reaction_s=0,
        overshoot_fraction=0), **kw)


def test_seed_reproducibility_and_unforced_endpoint():
    a = reach([0, 1, 0], [.2, 1, 0], seed=8)
    assert a == reach([0, 1, 0], [.2, 1, 0], seed=8)
    assert a != reach([0, 1, 0], [.2, 1, 0], seed=9)
    assert a['samples'][-1]['hands']['right']['position'] != [.2, 1, 0]
    assert a['provenance']['kind'] == 'synthetic_uncalibrated'
    for s in a['samples']:
        assert math.sqrt(sum(x*x for x in s['hands']['right']['orientation'])) == pytest.approx(1)


def test_minimum_jerk_midpoint_and_path():
    trace = ideal()
    assert trace['samples'][45]['hands']['right']['position'] == pytest.approx([.1, 1, 0])
    assert trace['samples'][-1]['hands']['right']['position'] == pytest.approx([.2, 1, 0])
    assert summary(trace)['hands']['right']['path_m'] == pytest.approx(.2)


def test_bimanual_demo_is_pose_only_and_registered_to_eye():
    from tools.vr_motion.demo_loop import demonstration
    eye = {'position': [1, 2, 3], 'orientation_xyzw': [0, 0, 0, 1]}
    trace = demonstration(eye)
    assert trace['events'] == []
    assert trace['samples'][-1]['t'] == 12
    assert len(trace['samples']) == 301
    for hand, x in [('left', .78), ('right', 1.22)]:
        first = trace['samples'][0]['hands'][hand]
        assert first['position'] == pytest.approx([x, 1.85, 2.28])
        assert any(s['hands'][hand]['position'] != first['position'] for s in trace['samples'][1:])
    validate_trace(trace, playable=True)


def test_overshoot_corrects_to_biased_endpoint():
    trace = reach([0, 1, 0], [.2, 1, 0], rate_hz=100, profile=Profile(
        position_sigma_m=0, rotation_sigma_deg=0, reaction_s=0,
        overshoot_fraction=.1, endpoint_bias_m=(.01, 0, 0)))
    xs = [s['hands']['right']['position'][0] for s in trace['samples']]
    assert max(xs) > .22
    assert xs[-1] == pytest.approx(.21)


def test_correlated_motion_is_not_independent_white_noise():
    trace = reach([0, 1, 0], [0, 1, 0], duration_s=20, seed=123,
                  profile=Profile(reaction_s=0, position_sigma_m=.01))
    xs = [s['hands']['right']['position'][0] for s in trace['samples'][100:]]
    energy = sum(x*x for x in xs)
    correlation = sum(a*b for a, b in zip(xs, xs[1:]))/energy
    assert .8 < correlation < 1


@pytest.mark.parametrize('change', [
    lambda t: t['samples'][1].update(t=0),
    lambda t: t['samples'][1]['hands']['right'].update(orientation=[0, 0, 0, 0]),
    lambda t: t['samples'][1]['hands']['right'].update(position=[float('nan'), 0, 0]),
    lambda t: t['samples'][1]['hands']['right'].update(valid=False),
    lambda t: t.update(space='unregistered'),
])
def test_bad_or_unregistered_motion_rejected_before_playback(change):
    trace = ideal()
    change(trace)
    with pytest.raises(ValueError):
        validate_trace(trace, playable=True)


def test_witness_quaternion_order_and_native_parser(tmp_path):
    trace = ideal(start_q=[0, 0, 1, 0], target_q=[0, 0, 1, 0])
    text = witness(trace)
    assert 'pose right 0 1 0 0 0 0 1' in text
    output = tmp_path/'motion.scry'
    output.write_text(text)
    binary = Path('native/vr_viewer/build/nadoc-vr-viewer')
    if binary.exists():
        result = subprocess.run([str(binary), '--validate-witness', str(output)], capture_output=True, text=True, timeout=5)
        assert result.returncode == 0, result.stderr


def test_witness_rejects_subframe_click():
    trace = ideal()
    trace['events'] = [{'t': .1, 'hand': 'right', 'button': 'trigger', 'pressed': True},
                       {'t': .1001, 'hand': 'right', 'button': 'trigger', 'pressed': False}]
    with pytest.raises(ValueError, match='collapse'):
        witness(trace)


class Clock:
    def __init__(self): self.t = 0
    def now(self): return self.t
    def sleep(self, t): self.t += t


class Bridge:
    def __init__(self, failure=None):
        self.state = {'session': '1-2', 'mode': 'control', 'focused': True,
                      'command_sequence': 0, 'frame': 1}
        self.calls = []
        self.failure = failure

    def call(self, name, args):
        self.calls.append((name, args))
        if name == 'scrywrite_observe': return dict(self.state)
        assert args['session'] == self.state['session']
        if name == 'scrywrite_wait':
            self.state['frame'] += 1
        else:
            assert args['expected_sequence'] == self.state['command_sequence']
            self.state['command_sequence'] += 1
        if name == 'scrywrite_pose' and self.failure:
            failure, self.failure = self.failure, None
            if failure == 'restart': self.state['session'] = '9-9'
            raise TimeoutError('delivery uncertain')
        return dict(self.state)


def test_live_pacing_and_final_release():
    clock, bridge = Clock(), Bridge()
    result = play_live(ideal(duration_s=.1, rate_hz=10), bridge, clock=clock.now, sleep=clock.sleep)
    assert result['released']
    assert clock.t == pytest.approx(.1)
    assert bridge.calls[-1][0] == 'scrywrite_release'


def test_live_uncertain_delivery_observes_before_release_without_retry():
    bridge = Bridge('timeout')
    clock = Clock()
    with pytest.raises(TimeoutError):
        play_live(ideal(), bridge, clock=clock.now, sleep=clock.sleep)
    assert [x[0] for x in bridge.calls].count('scrywrite_pose') == 1
    assert [x[0] for x in bridge.calls][-2:] == ['scrywrite_observe', 'scrywrite_release']


def test_live_never_releases_replacement_viewer():
    bridge = Bridge('restart')
    clock = Clock()
    with pytest.raises(TimeoutError) as error:
        play_live(ideal(), bridge, clock=clock.now, sleep=clock.sleep)
    assert [x[0] for x in bridge.calls].count('scrywrite_release') == 1  # initial release only
    assert 'release failed' in str(error.value.__notes__)


def test_live_late_schedule_aborts_and_releases():
    clock, bridge = Clock(), Bridge()
    def late(t): clock.t += t+1
    with pytest.raises(TimeoutError, match='deadline'):
        play_live(ideal(), bridge, clock=clock.now, sleep=late)
    assert bridge.calls[-1][0] == 'scrywrite_release'


def test_live_transactions_require_explicit_opt_in():
    bridge = Bridge()
    bridge.state['mode'] = 'transactions'
    with pytest.raises(ValueError, match='transactions'):
        play_live(ideal(), bridge)
    assert len(bridge.calls) == 1


def test_source_registration_preserves_distance_and_rotates_axes():
    trace = ideal()
    trace['space'] = 'iGibson_world_unregistered'
    original = copy.deepcopy(trace)
    s = math.sqrt(.5)
    result = register(trace, [0, 0, s, s], [1, 2, 3])
    assert trace == original
    assert result['samples'][0]['hands']['right']['position'] == pytest.approx([0, 2, 3])
    assert result['samples'][-1]['hands']['right']['position'] == pytest.approx([0, 2.2, 3])
    validate_trace(result, playable=True)


def test_behavior_uses_recorded_intervals_not_simulation_dt(tmp_path):
    h5py = pytest.importorskip('h5py')
    import numpy as np
    path = tmp_path/'recording.hdf5'
    with h5py.File(path, 'w') as f:
        f.attrs['/metadata/render_timestep'] = 1/30
        f['frame_data'] = [[0, 0, 0, 99], [1, 0, 0, .2], [2, 0, 0, .3]]
        rows = np.zeros((3, 27)); rows[:, 0] = 1; rows[:, 7] = 1
        rows[:, 1] = [0, .1, .2]
        for hand in ('left', 'right'):
            f[f'vr/vr_device_data/{hand}_controller'] = rows
            f[f'vr/vr_button_data/{hand}_controller'] = [[.2, .3, .4]]*3
        f['vr/vr_device_data/hmd'] = rows[:, :17]
    trace = import_behavior(path, count=3)
    assert [s['t'] for s in trace['samples']] == pytest.approx([0, .2, .5])
    assert trace['events'] == []
    assert trace['samples'][0]['hands']['right']['analog']['trigger'] == .2
    assert len(trace['provenance']['sha256']) == 64
    assert summary(trace)['hands']['right']['path_m'] == pytest.approx(.2)
    json.dumps(trace, allow_nan=False)
    index = catalog(tmp_path, measure=True)
    assert index['recordings'] == 1
    assert index['files'][0]['duration_s'] == pytest.approx(.5)
    assert index['files'][0]['hands']['right']['tracked_samples'] == 3
    lightweight = catalog(tmp_path)
    assert lightweight['measured'] is False
    assert lightweight['files'][0]['duration_s'] is None
    assert lightweight['files'][0]['hands']['right']['tracked_samples'] is None


def test_live_motion_against_production_native_handlers(tmp_path):
    from frontend.scrywrite.mcp_bridge import Bridge as NativeBridge

    binary = Path('native/vr_viewer/build/nadoc-vr-scrywrite-live-test')
    if not binary.exists():
        pytest.skip('build nadoc-vr-scrywrite-live-test for native IPC validation')
    with tempfile.TemporaryDirectory(prefix='motion-ipc-') as directory:
        socket = Path(directory)/'viewer.sock'
        process = subprocess.Popen([str(binary),
            'native/vr_viewer/examples/scrywrite_chiral_perspective.nadocvr', '--serve', str(socket)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+5
            while not socket.exists():
                assert process.poll() is None and time.monotonic() < deadline
                time.sleep(.01)
            log = tmp_path/'commands.jsonl'
            bridge = NativeBridge(socket, log)
            result = play_live(ideal(duration_s=.2, rate_hz=10), bridge)
            assert result['released']
            records = [json.loads(line) for line in log.read_text().splitlines()]
            assert any(r['state']['hands'][1]['position'][0] == pytest.approx(.2)
                       for r in records if 'hands' in r['state'])
            assert records[-1]['command'].endswith(' release')
            # This executable uses real production handlers, not an XR runtime.
            assert records[0]['state']['runtime_connected'] is False
        finally:
            process.terminate()
            process.wait(timeout=5)
            process.stderr.close()


def test_named_presets_preserve_speed_variability_independence():
    from tools.vr_motion.presets import PRESETS
    from tools.vr_motion.path_preview import export_path
    from tools.vr_motion.model import reach
    assert PRESETS['steady_fast'][0] == PRESETS['variable_fast'][0]
    assert PRESETS['steady_deliberate'][0] > PRESETS['steady_fast'][0]
    assert PRESETS['steady_fast'][1].position_sigma_m < PRESETS['variable_fast'][1].position_sigma_m
    duration, profile = PRESETS['steady_fast']
    trace = reach([0, 0, 0], [.1, 0, 0], duration_s=duration, profile=profile)
    lines = export_path(trace).splitlines()
    assert lines[0].startswith('#') and len(lines) == len(trace['samples'])+1
