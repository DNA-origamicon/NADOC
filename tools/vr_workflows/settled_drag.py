"""Long held-trigger motion using the existing, unchanged controller profiles."""
import json
import time

from tools.vr_motion.model import multiply
from tools.vr_workflows.audit_intervals import operation
from tools.vr_workflows.profile_input import reach_target


def run(live, output, preset, start, orientation, shift, rotation):
    endpoints = [(start.tolist(), orientation),
                 ((start + shift).tolist(), multiply(rotation, orientation))]
    trials = []
    stages = []
    quality = {}

    def check_grab():
        if not live.state.get('move_grabbing'):
            raise AssertionError('Settled drag lost the held trigger/target')

    def motion(label, seconds):
        started = time.monotonic()
        first = len(trials)
        with operation(live, label):
            while time.monotonic() - started < seconds:
                check_grab()
                position, wrist = endpoints[len(trials) % 2]
                trials.append(reach_target(
                    live, position, preset, 9000 + len(trials),
                    target_position=position, target_orientation=wrist))
                check_grab()
        stages.append(dict(name=label, seconds=time.monotonic()-started,
                           first_trial=first, trials=len(trials)-first))

    def stationary(label, seconds):
        pose = dict(live.state['hands'][1])
        started = time.monotonic()
        with operation(live, label):
            while time.monotonic() - started < seconds:
                check_grab()
                # Identical pose keeps the input lease alive without generating
                # preview changes. Use the same observation path as motion.
                live.send('pose', hand=1, position=pose['position'],
                          orientation=pose['orientation_xyzw'])
                live.frame()
                time.sleep(.04)
        stages.append(dict(name=label, seconds=time.monotonic()-started))

    completed = False
    try:
        motion('settled-drag-warmup', 5)
        motion('settled-drag', 30)
        if 'motion_detail_reduced' in live.state:
            evidence, _ = live.capture_to(output/'motion-quality', discard_source=True)
            quality['motion_reduced'] = evidence['state']['motion_detail_reduced']
        stationary('settled-hold-warmup', 5)
        stationary('settled-hold', 10)
        if 'motion_detail_reduced' in live.state:
            evidence, _ = live.capture_to(output/'settled-quality', discard_source=True)
            quality['settled_reduced'] = evidence['state']['motion_detail_reduced']
            assert not quality['settled_reduced'], 'Full detail did not return after settling'
        # Preserve the ordinary tour's nonzero final edit and persistence checks.
        position, wrist = endpoints[1]
        trials.append(reach_target(live, position, preset, 9000+len(trials),
                                  target_position=position, target_orientation=wrist))
        check_grab()
        completed = True
    finally:
        (output / 'settled-drag.json').write_text(json.dumps(dict(
            preset=preset, completed=completed, stages=stages, trials=trials,
            captures_during_measurement=False, quality=quality,
            limits='Synthetic profile reaches at the existing 20 Hz input cadence; not a wearer trace.'), indent=2))
        if not completed:
            live.release()
