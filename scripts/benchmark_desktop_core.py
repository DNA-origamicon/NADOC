"""In-memory desktop design pipeline: construction, geometry, JSON and history.

Synthetic straight honeycomb bundles; no files, API state mutations or solvers.
Each operation has one first call and 15 warmed samples with GC left enabled.
"""
from __future__ import annotations

import argparse
import cProfile
import json
import pstats
from pathlib import Path
import math
import statistics
import time

from backend.api.state import decode_design_snapshot, encode_design_snapshot
from backend.core.design_geometry import _geometry_for_design
from backend.core.lattice import make_bundle_design
from backend.core.models import Design


def measure(fn, check):
    start = time.perf_counter()
    first = fn()
    cold = (time.perf_counter() - start) * 1000
    check(first)
    samples = []
    for _ in range(15):
        start = time.perf_counter()
        result = fn()
        samples.append((time.perf_counter() - start) * 1000)
        check(result)
    return dict(first_call_ms=cold, median_ms=statistics.median(samples),
                p95_ms=sorted(samples)[math.ceil(len(samples) * .95) - 1],
                samples_ms=samples, correctness='passed')


def require(condition):
    if not condition:
        raise AssertionError('Benchmark correctness invariant failed')


def main():
    cases = []
    for helices in (6, 24, 96):
        cells = [(i // 6, i % 6) for i in range(helices)]
        design = make_bundle_design(cells, length_bp=84)
        original = design.model_dump(mode='json')
        raw = design.model_dump_json()
        snapshot, _ = encode_design_snapshot(design)
        geometry = _geometry_for_design(design)
        require(len(geometry) > 0)
        for row in geometry:
            require(all(math.isfinite(v) for v in row['backbone_position']))
        operations = {
            'construct_bundle': (lambda: make_bundle_design(cells, length_bp=84),
                                 lambda d: require(len(d.helices) == helices and len(d.strands) == len(design.strands))),
            'native_display_geometry': (lambda: _geometry_for_design(design), lambda g: require(g == geometry)),
            'serialize_design_json': (design.model_dump_json, lambda s: require(json.loads(s) == original)),
            'parse_validate_design_json': (lambda: Design.model_validate_json(raw), lambda d: require(d.model_dump(mode='json') == original)),
            'encode_history_snapshot': (lambda: encode_design_snapshot(design), lambda s: require(decode_design_snapshot(s[0]).model_dump(mode='json') == original)),
            'decode_history_snapshot': (lambda: decode_design_snapshot(snapshot), lambda d: require(d.model_dump(mode='json') == original)),
        }
        measured = {name: measure(fn, check) for name, (fn, check) in operations.items()}
        require(design.model_dump(mode='json') == original)
        cases.append(dict(helices=helices, bp_per_helix=84, nucleotides=len(geometry),
                          json_bytes=len(raw.encode()), snapshot_base64_bytes=len(snapshot), operations=measured))
    print(json.dumps(dict(scope='Synthetic in-memory CPU pipeline; no disk, HTTP, complex junctions or rendering. First-call is not a fresh-process cold start.',
                         repeats=15, gc='enabled', cases=cases), indent=2))


def profile_geometry():
    design = make_bundle_design([(i // 6, i % 6) for i in range(96)], length_bp=84)
    _geometry_for_design(design)
    profiler = cProfile.Profile()
    profiler.runcall(_geometry_for_design, design)
    root = Path(__file__).resolve().parents[1]
    rows = []
    for (filename, line, name), (_, calls, self_s, cumulative_s, _) in pstats.Stats(profiler).stats.items():
        path = Path(filename)
        if not path.is_absolute() or not path.is_relative_to(root / 'backend'):
            continue
        rows.append(dict(source=path.relative_to(root).as_posix(), line=line,
                         function=name, calls=calls, self_ms=self_s * 1000,
                         cumulative_ms=cumulative_s * 1000))
    rows.sort(key=lambda row: row['cumulative_ms'], reverse=True)
    print(json.dumps(dict(scope='One warm cProfile call, 96 helices x 84 bp. Instrumented timings are diagnostic, not baseline latency. Cumulative rows overlap.',
                          top_cumulative=rows[:25]), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', action='store_true', help='Profile one warm 96-helix geometry call instead of running the timing sweep')
    args = parser.parse_args()
    profile_geometry() if args.profile else main()
