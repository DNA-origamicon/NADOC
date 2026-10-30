"""Isolate strand metadata optimization from round-1 geometry emission."""
from __future__ import annotations

import ast
import argparse
import gc
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from unittest.mock import patch

import orjson
from backend.core import design_geometry as geometry
from backend.core.lattice import make_bundle_design
from scripts.benchmark_desktop_geometry_emission import check_cases

BASELINE = '2f3b962966b4917d9f626e486d56680306600363'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disable-gc', action='store_true', help='Diagnostic: suppress cyclic GC only during timed calls')
    args = parser.parse_args()
    if os.environ.get('NADOC_VALIDATION_SCOPE') != '1':
        raise SystemExit('Use scripts/validation_guard.sh')
    source = subprocess.check_output(
        ['git', 'show', f'{BASELINE}:backend/core/design_geometry.py'], text=True)
    node = next(n for n in ast.parse(source).body
                if isinstance(n, ast.FunctionDef) and n.name == '_strand_nucleotide_info')
    scope = dict(vars(geometry))
    exec(compile(ast.Module(body=[node], type_ignores=[]), '<original-metadata>', 'exec'), scope)
    old = scope['_strand_nucleotide_info']
    current = geometry._strand_nucleotide_info

    def old_geometry(design, **kwargs):
        with patch.object(geometry, '_strand_nucleotide_info', old):
            return geometry._geometry_for_helices(design, **kwargs)

    checks = check_cases(old_geometry)
    rows = []
    for count in (6, 24, 96):
        design = make_bundle_design([(i // 6, i % 6) for i in range(count)], 84)
        original = design.model_dump_json()
        expected = orjson.dumps(old_geometry(design))
        expected_metadata = old(design)
        for operation in ('metadata', 'whole_geometry'):
            samples = [[], []]
            for repeat in range(-2, 21):
                for index in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                    fn = old if index == 0 else current
                    with patch.object(geometry, '_strand_nucleotide_info', fn):
                        was_enabled = gc.isenabled()
                        if args.disable_gc:
                            gc.disable()
                        try:
                            start = time.perf_counter()
                            result = fn(design) if operation == 'metadata' else geometry._geometry_for_helices(design)
                            elapsed = (time.perf_counter() - start) * 1000
                        finally:
                            if was_enabled:
                                gc.enable()
                    if operation == 'metadata':
                        assert result == expected_metadata
                    else:
                        assert orjson.dumps(result) == expected
                    assert design.model_dump_json() == original
                    if repeat >= 0:
                        samples[index].append(elapsed)
            before, after = map(statistics.median, samples)
            rows.append(dict(helices=count, operation=operation, before_ms=before,
                             after_ms=after, speedup=before/after, samples_ms=samples, exact=True))
    print(json.dumps(dict(baseline=BASELINE, repeats=21, warmups=2,
        gc='disabled during timing' if args.disable_gc else 'enabled',
        scope='Only strand metadata helper alternates; current round-1 emission shared. CPU only, no E2E claim.',
        candidate_sha256=hashlib.sha256(Path(geometry.__file__).read_bytes()).hexdigest(),
        correctness_cases=checks, results=rows), indent=2))


if __name__ == '__main__':
    main()
