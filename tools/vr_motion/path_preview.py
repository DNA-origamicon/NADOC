"""Prepare an ideal route and perturbed motion for a single-pass live preview.

python -m tools.vr_motion.path_preview EYE_EVIDENCE OUTPUT_DIRECTORY
Launch viewer with --controller-path OUTPUT_DIRECTORY/intended.path, then play
actual.motion.json once using the existing live command. This never starts a loop.
"""
import argparse
import json
from pathlib import Path
from .demo_loop import demonstration
from .model import Profile, validate_trace


def export_path(trace):
    validate_trace(trace, playable=True)
    lines = ['# NADOC intended route: hand(0=left,1=right) x y z; OpenXR_LOCAL metres']
    for sample in trace['samples']:
        for hand, pose in sample['hands'].items():
            if not pose['valid']:
                raise ValueError('intended route must be continuous and valid')
            lines.append(' '.join(map(str, [int(hand == 'right'), *pose['position']])))
    return '\n'.join(lines)+'\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('evidence', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    eye = json.loads(args.evidence.read_text())['eyes'][0]
    intended = demonstration(eye, profile=Profile(position_sigma_m=0, rotation_sigma_deg=0,
        overshoot_fraction=0, reaction_s=0))
    actual = demonstration(eye, profile=Profile(position_sigma_m=.012, rotation_sigma_deg=1.2,
        overshoot_fraction=.12, reaction_s=0))
    for name, trace in [('intended', intended), ('actual', actual)]:
        trace['provenance']['description'] = name+' preview; illustrative synthetic profile, not a fitted human category'
        (args.output/(name+'.motion.json')).write_text(json.dumps(trace, indent=2)+'\n')
    (args.output/'intended.path').write_text(export_path(intended))
    (args.output/'legend.txt').write_text('INTENDED: dashed pale blue (left), pale gold (right)\nACTUAL: solid green (left), magenta (right), sampled from production hand poses\nActual input has synthetic 12mm per-axis variability and 12% overshoot. Not human-calibrated.\n')


if __name__ == '__main__':
    main()
