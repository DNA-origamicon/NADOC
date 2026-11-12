"""Check guide freshness without changing baselines or launching the app."""
import argparse
import json

from scripts.feature_guides import GUIDES, REPO, inspect_guides, render_ledger


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--json', action='store_true', help='Machine-readable report')
    parser.add_argument('--require-all', action='store_true', help='Fail for incomplete feature coverage too')
    parser.add_argument('--write-ledger', action='store_true', help='Refresh the Markdown table only; never source baselines')
    args = parser.parse_args(argv)
    try:
        report = inspect_guides(REPO)
        if args.write_ledger:
            (REPO / GUIDES / 'LEDGER.md').write_text(render_ledger(REPO))
        expected = render_ledger(REPO)
        ledger = REPO / GUIDES / 'LEDGER.md'
        if not ledger.exists() or ledger.read_text() != expected:
            report['inventory_problems'].append('Ledger table outdated: run --write-ledger')
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'inventory_problems': [str(error)], 'guides': []}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for problem in report['inventory_problems']:
            print(f'INVENTORY: {problem}')
        for row in report['guides']:
            if row['state'] != 'not-created':
                print(f'{row["state"].upper()}: {row["id"]} (coverage: {row["coverage"]}; captured {row["captured_at"]})')
                for change in row['changes']:
                    print(f'  {change["change"]}: {change["path"]}')
                for problem in row['problems']:
                    print(f'  {problem}')
        count = sum(r['state'] == 'not-created' for r in report['guides'])
        print(f'{len(report["guides"])} features registered; {count} have no illustrated guide yet.')
    bad = bool(report['inventory_problems']) or any(r['state'] in {'stale', 'broken'} for r in report['guides'])
    incomplete = any(r['coverage'] != 'complete' for r in report['guides'])
    return int(bad or (args.require_all and incomplete))


if __name__ == '__main__':
    raise SystemExit(main())
