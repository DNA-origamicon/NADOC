"""Fast stencil measurements and explicit, fail-closed numeric expectations.

CLI: python -m tools.scrywrite_inspector.visual_metrics --socket PATH --expect JSON
Rules: [{"eye":0,"class_id":3,"ranges":{"pixels":[100,null],"width":[20,800]}}]
"""
import argparse
import json
import math
from pathlib import Path
from frontend.scrywrite.mcp_bridge import Bridge
from tools.vr_motion.session import LiveSession

FIELDS = ('pixels', 'x', 'y', 'width', 'height', 'cx', 'cy', 'fill_ratio', 'major', 'minor')


def evaluate(measurement, rules):
    if not isinstance(rules, list) or not rules:
        raise ValueError('at least one expectation is required')
    if (measurement.get('status') != 'complete'
            or measurement.get('source') != 'application_stencil'
            or measurement.get('xr_end_frame_succeeded') is not True):
        return {'passed': False, 'error': 'no completed submitted measurement', 'checks': []}
    checks = []
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {'eye', 'class_id', 'ranges'}:
            raise ValueError('expect eye, class_id and ranges')
        eye, identifier = rule['eye'], rule['class_id']
        if type(eye) is not int or eye not in (0, 1) or type(identifier) is not int or not 1 <= identifier <= 7:
            raise ValueError('invalid eye or class')
        ranges = rule['ranges']
        if not isinstance(ranges, dict) or not ranges or set(ranges)-set(FIELDS):
            raise ValueError('invalid metric names')
        rows = measurement['eyes'][eye]['masks']
        matches = [row for row in rows if row['class_id'] == identifier]
        row = matches[0] if len(matches) == 1 else {}
        values = dict(zip(FIELDS, [row.get('pixels'), *(row.get('bounds') or [None]*4),
            *(row.get('centroid') or [None]*2), row.get('fill_ratio'), *(row.get('moment_axes') or [None]*2)]))
        for field, bounds in ranges.items():
            if not isinstance(bounds, list) or len(bounds) != 2 or bounds == [None, None]:
                raise ValueError('range needs two bounds, at least one finite')
            for bound in bounds:
                if bound is not None and (type(bound) not in (int, float) or not math.isfinite(bound)):
                    raise ValueError('range must be finite')
            low, high = bounds
            if low is not None and high is not None and low > high:
                raise ValueError('reversed range')
            actual = values[field]
            passed = (type(actual) in (int, float) and math.isfinite(actual)
                      and (low is None or actual >= low) and (high is None or actual <= high))
            checks.append({'eye': eye, 'class_id': identifier, 'metric': field,
                           'actual': actual, 'range': bounds, 'passed': passed})
    return {'passed': all(check['passed'] for check in checks), 'checks': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--socket')
    parser.add_argument('--roi', nargs=4, type=float, default=[0, 0, 1, 1])
    parser.add_argument('--expect', type=Path)
    args = parser.parse_args()
    live = LiveSession(Bridge(args.socket))
    measurement = live.send('measure', roi=args.roi)['measurement']
    result = {'session': live.session, 'measurement': measurement}
    if args.expect:
        result['evaluation'] = evaluate(measurement, json.loads(args.expect.read_text()))
    print(json.dumps(result, allow_nan=False))
    return 0 if measurement['status'] == 'complete' and result.get('evaluation', {}).get('passed', True) else 1


if __name__ == '__main__':
    raise SystemExit(main())
