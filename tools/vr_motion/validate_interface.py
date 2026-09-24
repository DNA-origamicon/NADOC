"""Run an isolated live VR debugging check; retain JSON and stereo evidence.

python -m tools.vr_motion.validate_interface SOCKET OUTPUT_DIRECTORY
Only control mode is accepted. Stop other scripted input producers first.
"""
import argparse
import json
from pathlib import Path
import time
from frontend.scrywrite.mcp_bridge import Bridge
from .demo_loop import demonstration
from .model import multiply
from .report import write_report
from .metrics import distribution, pose_error, target_metrics, visibility
from .session import LiveSession


class Probe(LiveSession):
    def __init__(self, socket, output, cancel=None):
        super().__init__(Bridge(socket), physical=True, cancel=cancel)
        if self.state['mode'] != 'control':
            raise ValueError('probe requires isolated control mode')
        self.output = output

    def capture(self, name):
        destination = self.output/name
        evidence, _ = self.capture_to(destination, files=("left.png","right.png","left.classes.u8","right.classes.u8","evidence.json"), discard_source=True)
        return evidence, visibility(destination, evidence)


def run(socket, output):
    output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'nadoc-vr-interface-1', 'passed': False, 'checks': {},
              'scope': 'Production app input and submitted stereo images; no compositor scanout acknowledgement. Synthetic motion is uncalibrated.'}
    probe = Probe(socket, output)
    report['session'] = probe.session
    try:
        probe.send('release')
        if probe.state['menu'] != 'closed':
            probe.button('menu')
        anchor, _ = probe.capture('anchor')
        trace = demonstration(anchor['eyes'][0])
        (output/'desired.motion.json').write_text(json.dumps(trace))
        rows = []
        # Frame-paced sampling measures applied poses, not wall-clock playback fidelity.
        for sample in trace['samples'][::10]:
            started = time.monotonic()
            for index, hand in enumerate(('left', 'right')):
                pose = sample['hands'][hand]
                probe.send('pose', hand=index, position=pose['position'], orientation=pose['orientation'])
            state = probe.frame()
            for index, hand in enumerate(('left', 'right')):
                rows.append({'t': sample['t'], 'hand': hand, 'frame': state['frame'],
                    'command_sequence': state['command_sequence'],
                    'desired': sample['hands'][hand], 'actual': state['hands'][index],
                    'round_trip_s': time.monotonic()-started,
                    **pose_error(sample['hands'][hand], state['hands'][index])})
        report['path'] = {'sampling': 'frame-paced, every tenth demo sample',
            'position_mm': distribution([r['position_mm'] for r in rows]),
            'angle_deg': distribution([r['angle_deg'] for r in rows]),
            'round_trip_s': distribution([r['round_trip_s'] for r in rows]), 'samples': rows}
        report['checks']['path_applied'] = (report['path']['position_mm']['max'] < 1
            and report['path']['angle_deg']['max'] < .1 and all(r['actual']['valid'] for r in rows))
        _, visible = probe.capture('controllers-visible')
        report['visible_pixels'] = visible
        report['checks']['both_controllers_both_eyes'] = all(n >= 10 for eye in visible.values() for n in eye.values())
        saved = probe.state['hands']
        for hand in range(2):
            probe.send('pose', hand=hand, position=[50, 50, 50], orientation=[0, 0, 0, 1])
        probe.frame()
        _, hidden = probe.capture('controllers-offscreen')
        report['offscreen_pixels'] = hidden
        report['checks']['offscreen_negative_control'] = all(n == 0 for eye in hidden.values() for n in eye.values())
        for hand, pose in enumerate(saved):
            probe.send('pose', hand=hand, position=pose['position'], orientation=pose['orientation_xyzw'])
        probe.frame()
        probe.button('menu')
        report['checks']['menu_button_opens'] = probe.state['menu'] == 'options'
        target = next(c for c in probe.state['controls'] if c['label'] == 'TOOLS')
        probe.send('aim_menu', hand=1, label='TOOLS')
        probe.frame()
        good = probe.state['hands'][1]
        # Reverse the ray: no panel in front, no target activation expected.
        q = good['orientation_xyzw']
        probe.send('pose', hand=1, position=good['position'], orientation=multiply(q, [0, 1, 0, 0]))
        probe.frame()
        target = next(c for c in probe.state['controls'] if c['label'] == 'TOOLS')
        miss = target_metrics(target, probe.state['hands'][1])
        miss['hover'] = probe.state['hover']
        probe.button('trigger')
        miss['menu_after_click'] = probe.state['menu']
        report['checks']['miss_rejected'] = not miss['predicted_hit'] and miss['hover'] != 'tools' and probe.state['menu'] == 'options'
        probe.send('pose', hand=1, position=good['position'], orientation=q)
        probe.frame()
        target = next(c for c in probe.state['controls'] if c['label'] == 'TOOLS')
        hit = target_metrics(target, probe.state['hands'][1])
        hit['hover'] = probe.state['hover']
        probe.capture('menu-target')
        probe.button('trigger')
        hit['menu_after_click'] = probe.state['menu']
        report['checks']['target_activated'] = hit['predicted_hit'] and hit['hover'] == 'tools' and probe.state['menu'] == 'tools'
        report['target_trials'] = {'label': 'TOOLS', 'target': target, 'miss': miss, 'hit': hit}
        probe.capture('menu-result')
        probe.button('menu')
        report['interaction_counts'] = {'intended_hits': 1, 'successful_hits': int(report['checks']['target_activated']),
            'intended_misses': 1, 'correctly_rejected_misses': int(report['checks']['miss_rejected'])}
        report['passed'] = all(report['checks'].values())
    except Exception as error:
        report['error'] = repr(error)
        raise
    finally:
        try:
            probe.release()
        finally:
            (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
            write_report(output, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('socket')
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    report = run(args.socket, args.output)
    print(json.dumps({k: report[k] for k in ('passed', 'checks')}, indent=2))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
