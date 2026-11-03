"""Paired geometry-output CPU benchmark; verifies exact baseline JSON bytes.

No placement formulas or reference goldens are changed. Loads one historical
function in memory; does not check out files, open designs or launch simulations.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import platform
import statistics
import subprocess
import time
from pathlib import Path

import orjson

from backend.core import design_geometry as geometry
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, LatticeType, StrandExtension
from tests.test_native_compact_geometry import _design

ROOT = Path(__file__).resolve().parents[1]


def reference(revision):
    path = 'backend/core/design_geometry.py'
    source = subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT, text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_geometry_for_helices')
    scope = dict(vars(geometry))
    exec(compile(ast.Module(body=[node], type_ignores=[]), f'{revision}:{path}', 'exec'), scope)
    return scope['_geometry_for_helices'], hashlib.sha256(source.encode()).hexdigest()


def check_cases(old):
    fixtures = [('empty', Design(), {})]
    for kind in ('straight', 'bend', 'twist', 'sweep', 'partial'):
        d = _design(kind)
        fixtures.append((kind, d, {}))
        fixtures.append((kind + '-scoped', d, {'helix_ids': frozenset([d.helices[0].id])}))
        fixtures.append((kind + '-compact-skips', d, {'compact_skips': True}))
    d = _design('bend')
    d.extensions = [StrandExtension(strand_id=d.strands[0].id, end='five_prime', sequence='AAA')]
    fixtures.append(('extension', d, {}))
    d = _design('straight')
    d.strands[0].domains[0].start_bp = -2
    fixtures.append(('outside-helix', d, {}))
    fixtures.append(('square', make_bundle_design([(0, 0), (0, 1)], 42, lattice_type=LatticeType.SQUARE), {}))
    checks = []
    for name, design, kwargs in fixtures:
        original = design.model_dump_json()
        expected = orjson.dumps(old(design, **kwargs))
        assert orjson.dumps(geometry._geometry_for_helices(design, **kwargs)) == expected, name
        assert design.model_dump_json() == original, name
        checks.append(name)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', default='2f3b962966b4917d9f626e486d56680306600363')
    parser.add_argument('--repeats', type=int, default=15)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    old, baseline_hash = reference(args.baseline)
    checks = check_cases(old)
    cases = []
    for count in (6, 24, 96):
        design = make_bundle_design([(i // 6, i % 6) for i in range(count)], 84)
        expected = orjson.dumps(old(design))
        samples = {'before': [], 'after': []}
        for iteration in range(args.repeats + 2):
            variants = [('before', old), ('after', geometry._geometry_for_helices)]
            if iteration % 2:
                variants.reverse()
            for name, fn in variants:
                start = time.perf_counter()
                result = fn(design)
                elapsed = (time.perf_counter() - start) * 1000
                assert orjson.dumps(result) == expected, (count, name)
                if iteration >= 2:
                    samples[name].append(elapsed)
        summary = {name: {'median_ms': statistics.median(values),
                          'p95_ms': sorted(values)[math.ceil(len(values) * .95) - 1]}
                   for name, values in samples.items()}
        cases.append(dict(helices=count, bp_per_helix=84, samples_ms=samples, summary=summary,
                          speedup=summary['before']['median_ms'] / summary['after']['median_ms'], exact_json_bytes=True))
    print(json.dumps(dict(scope='Paired warm geometry-output CPU, GC enabled; not HTTP or browser latency',
                          baseline=args.baseline, baseline_source_sha256=baseline_hash,
                          candidate_source_sha256=hashlib.sha256(Path(geometry.__file__).read_bytes()).hexdigest(),
                          python=platform.python_version(), correctness_cases=checks, cases=cases), indent=2))


if __name__ == '__main__':
    main()
