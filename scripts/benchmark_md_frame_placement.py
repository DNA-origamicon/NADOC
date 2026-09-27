"""Compare direct MD PBC placement against a Git baseline; no workspace writes.
Run under scripts/test_guard.sh with slow=1 and an open test session.
"""
import argparse
import ast
import json
import statistics
import subprocess
import time

import numpy as np
from backend.core import md_trajectory as md


def fixture(n_segments=300, atoms_per_residue=20):
    counts = np.resize([16, 24, 31, 32, 40], n_segments)
    counts[0] = 2000  # scaffold plus short staples
    segment = np.repeat(np.arange(n_segments), counts)
    residue = np.repeat(np.arange(len(segment)), atoms_per_residue)
    anchors = np.arange(len(segment)) * atoms_per_residue
    rng = np.random.default_rng(42)
    origins = rng.uniform(0, 80, (len(segment), 3))
    raw = origins[residue] + rng.uniform(-.08, .08, (len(residue), 3))
    raw[anchors] = origins
    layout = dict(heavy_res_group=residue, residue_anchor_rows=anchors,
                  residue_segment_ids=segment.astype(str), heavy_segment_group=segment[residue],
                  p_heavy_rows=anchors, p_segment_group=segment, n_segments=n_segments,
                  segment_p_rows=[np.flatnonzero(segment == s) for s in range(n_segments)],
                  segment_heavy_rows=[np.flatnonzero(segment[residue] == s) for s in range(n_segments)])
    return raw, origins + rng.integers(-2, 3, (n_segments, 3))[segment]*80, np.array([80., 80., 80.]), np.array([-40., 3., -2.]), layout


def legacy_function(revision):
    path = 'backend/core/md_trajectory.py'
    source = subprocess.check_output(['git', 'show', f'{revision}:{path}'], text=True)
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_direct_heavy_pre_positions')
    scope = vars(md).copy()
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), scope)
    return scope[node.name]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', required=True)
    args = parser.parse_args()
    before = legacy_function(args.baseline)
    results = []
    for strands in [300, 1000]:
        values = fixture(strands)
        ref = before(*values)
        cold_start = time.perf_counter()
        actual = md._direct_heavy_pre_positions(*values)
        cold = time.perf_counter() - cold_start
        np.testing.assert_array_equal(actual, ref)
        times = [[], []]
        for repeat in range(15):
            for index in ([0, 1] if repeat % 2 == 0 else [1, 0]):
                fn = (before, md._direct_heavy_pre_positions)[index]
                start = time.perf_counter()
                out = fn(*values)
                times[index].append(time.perf_counter() - start)
                np.testing.assert_array_equal(out, ref)
        t0, t1 = map(statistics.median, times)
        result = dict(atoms=len(values[0]), segments=strands, before_s=t0, after_s=t1,
                      cold_after_s=cold, speedup=t0/t1, exact=True)
        results.append(result)
        print(json.dumps(result), flush=True)
    print(json.dumps({'baseline': args.baseline, 'results': results}, indent=2))


if __name__ == '__main__':
    main()
