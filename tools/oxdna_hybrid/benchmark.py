"""Matched-total-step ablation: no bias, COM metadynamics, HB and mixed hybrids.

Each case is sequential, with up to four concurrent walkers. Compare end-to-end
elapsed time as well as samples; equal MD steps do not imply equal compute cost.
"""
import argparse
import json
from pathlib import Path

from tools.oxdna_hybrid.analysis import analyze
from tools.oxdna_hybrid.campaign import campaign, parser


def main():
    p = parser()
    p.add_argument('--cases', nargs='+', choices=('unbiased', 'com', 'hb_cutoff', 'mixed'),
                   default=['unbiased', 'com', 'hb_cutoff', 'mixed'])
    p.add_argument('--resume-completed', action='store_true',
                   help='Reuse only completed, exactly matching cases; never resume partial native runs')
    args = p.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(exist_ok=args.resume_completed)
    reports = []
    for index, case in enumerate(args.cases):
        values = {key: value for key, value in vars(args).items() if key not in {'cases', 'resume_completed'}}
        values['output'] = str(output/case)
        values['coordinate'] = 'mixed' if case == 'unbiased' else case
        values['seed'] += index*100000
        if case == 'unbiased':
            values['production_steps'] += values['train_steps']
            values['train_steps'] = 0
        directory = Path(values['output'])
        if args.resume_completed and directory.exists():
            old = json.loads((directory/'manifest.json').read_text())
            if old['protocol'] != values:
                raise ValueError(f'Refusing mismatched completed protocol: {directory}')
            execution = json.loads((directory/'execution.json').read_text())
            if execution['status'] != 'completed':
                raise ValueError('Partial campaigns require a new output directory')
        else:
            campaign(argparse.Namespace(**values))
        report = analyze(values['output'])
        reports.append({'case': case, **report})
        (output/'benchmark.json').write_text(json.dumps(reports, indent=2)+'\n')


if __name__ == '__main__':
    main()
