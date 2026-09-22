"""Loop two synthetic controllers in front of a captured physical eye.

Usage: python -m tools.vr_motion.demo_loop SOCKET EYE_EVIDENCE OUTPUT_DIRECTORY
Close the viewer or create OUTPUT_DIRECTORY/STOP to stop after the current lap.
"""
import argparse
import json
from pathlib import Path
import signal
import time

from frontend.scrywrite.mcp_bridge import Bridge
from .model import Profile, multiply, quaternion, reach, validate_trace
from .playback import play_live


def demonstration(eye, seed=42, profile=None):
    """12-second, pose-only bimanual demonstration in registered OpenXR metres."""
    q = quaternion(eye['orientation_xyzw'])
    inverse = [-x for x in q[:3]]+[q[3]]
    def world(p):
        r = multiply(multiply(q, [*p, 0]), inverse)
        return [r[i]+eye['position'][i] for i in range(3)]
    waypoints = [(0, 0, 0), (.12, .08, -.08), (-.06, .16, -.04),
                 (-.12, -.03, .06), (.05, -.10, -.02), (0, 0, 0)]
    samples = []
    for segment, (a, b) in enumerate(zip(waypoints, waypoints[1:])):
        hands = {}
        for index, hand in enumerate(('left', 'right')):
            sign = -1 if hand == 'left' else 1
            position = lambda v: world([sign*(.22+v[0]), -.15+v[1], -.72+v[2]])
            hands[hand] = reach(position(a), position(b), start_q=q, target_q=q,
                hand=hand, duration_s=2.4, rate_hz=25, seed=seed+index*100+segment,
                profile=profile or Profile(position_sigma_m=.004, rotation_sigma_deg=1.2,
                                overshoot_fraction=.07, reaction_s=0))
        for i, sample in enumerate(hands['left']['samples']):
            if segment and i == 0:
                continue
            samples.append({'t': segment*2.4+sample['t'], 'hands': {
                h: hands[h]['samples'][i]['hands'][h] for h in hands}})
    trace = {**hands['left'], 'samples': samples, 'events': [], 'provenance': {
        'kind': 'synthetic_uncalibrated', 'seed': seed, 'eye_anchor': eye,
        'description': 'pose-only bimanual sweep; no design inputs'}}
    validate_trace(trace, playable=True)
    return trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket', type=Path)
    parser.add_argument('eye_evidence', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    eye = json.loads(args.eye_evidence.read_text())['eyes'][0]
    trace = demonstration(eye)
    (args.output/'loop.motion.json').write_text(json.dumps(trace, indent=2)+'\n')
    def interrupted(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, interrupted)
    bridge = Bridge(args.socket)
    initial = bridge.call('scrywrite_observe', {})
    session = initial['session']
    lap = 0
    while not (args.output/'STOP').exists():
        current = bridge.call('scrywrite_observe', {})
        if current.get('session') != session:
            raise RuntimeError('original demonstration session ended')
        if not current.get('focused'):
            time.sleep(.25)
            continue
        try:
            result = play_live(trace, bridge, max_lag_s=.5)
        except TimeoutError as error:
            # Only this non-mutating visual demo repeats an interrupted lap.
            # play_live has already attempted release; regression tests still fail.
            print(json.dumps({'interrupted_lap': lap+1, 'reason': str(error),
                              'action': 'release then restart pose-only lap'}), flush=True)
            time.sleep(.25)
            continue
        lap += 1
        result['lap'] = lap
        temporary = args.output/'status.tmp'
        temporary.write_text(json.dumps(result, indent=2)+'\n')
        temporary.replace(args.output/'status.json')
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
