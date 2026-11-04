"""Read-only benchmark: python -m scripts.benchmark_scaffold_register FILE ..."""
import argparse
import hashlib
import json
import platform
from pathlib import Path
from statistics import median
from time import perf_counter
from backend.core.models import Design
from backend.core.scaffold_register import evaluate_design, apply_nick


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('designs', nargs='+', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    rows = []
    for path in args.designs:
        raw = path.read_bytes()
        design = Design.model_validate_json(raw)
        timings = []
        for _ in range(args.repeats):
            started = perf_counter()
            result = evaluate_design(design)
            timings.append(perf_counter()-started)
        applied = apply_nick(design, result['best']['cut_index'])
        rescore = evaluate_design(applied)
        rows.append({
            'design': str(path), 'sha256': hashlib.sha256(raw).hexdigest(),
            'scaffold_nt': result['scaffold_nt'], 'staples': result['staple_count'],
            'eligible_starts': result['candidate_count'], 'seconds': timings,
            'median_seconds': median(timings),
            'apply_score_error': abs(result['best']['q']-rescore['current']['q']),
        })
    print(json.dumps({'python': platform.python_version(), 'platform': platform.platform(),
                      'timing_scope': 'mapping, complete CPU sweep, ranking, report; excludes file parsing, HTTP and rendering',
                      'results': rows}, indent=2))


if __name__ == '__main__':
    main()
