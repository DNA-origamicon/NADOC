"""Hold engine and step budgets fixed while varying the mixed contact radius."""
import argparse
import json
from pathlib import Path

from tools.oxdna_hybrid.analysis import analyze
from tools.oxdna_hybrid.campaign import campaign, parser


def main():
    p = parser()
    p.add_argument('--radii', nargs='+', type=float, default=[.5, 1.5])
    args = p.parse_args()
    root = Path(args.output).resolve()
    root.mkdir(exist_ok=False)
    reports = []
    for radius in args.radii:
        values = {key: value for key, value in vars(args).items() if key != 'radii'}
        case = f'radius_{radius:g}'
        values.update(output=str(root/case), coordinate='mixed', contact_radius=radius)
        campaign(argparse.Namespace(**values))
        reports.append({'case': case, **analyze(values['output'])})
        (root/'benchmark.json').write_text(json.dumps(reports, indent=2)+'\n')


if __name__ == '__main__':
    main()
