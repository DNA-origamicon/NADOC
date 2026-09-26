"""Read-only A/B audit; run through scripts/test_guard.sh (slow=1).

Baseline functions are loaded from the requested Git revision, never checked out.
No designs, jobs, or files are created in the user workspace.
"""

from __future__ import annotations

import argparse
import ast
import json
import statistics
import subprocess
import time
import types
from pathlib import Path

import numpy as np
from backend.physics import fem_solver as fem
from tests.conftest import make_6hb_design, make_18hb_design


def baseline_function(module, name, revision):
    path = str(
        Path(module.__file__).resolve().relative_to(Path(__file__).resolve().parents[1])
    )
    source = subprocess.check_output(["git", "show", f"{revision}:{path}"], text=True)
    node = next(
        n
        for n in ast.parse(source).body
        if isinstance(n, ast.FunctionDef) and n.name == name
    )
    scope = vars(module).copy()
    exec(
        compile(ast.Module(body=[node], type_ignores=[]), f"{revision}:{path}", "exec"),
        scope,
    )
    return scope[name]


def timed(fn, *args, repeats=3, **kwargs):
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn(*args, **kwargs)
        times.append(time.perf_counter() - start)
    return result, statistics.median(times)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    old_fem = baseline_function(fem, "assemble_global_stiffness", args.baseline)

    results = []
    for name, design in [
        ("6hb_84", make_6hb_design(84)),
        ("18hb_196", make_18hb_design(196)),
    ]:
        for material in ["cando", "snupi"]:
            mesh = fem.build_fem_mesh(design, material=material)
            (before, f0), t0 = timed(old_fem, mesh, material=material)
            (after, f1), t1 = timed(
                fem.assemble_global_stiffness, mesh, material=material
            )
            delta = (before.tocsr() - after.tocsr()).data
            max_error = float(np.max(np.abs(delta))) if delta.size else 0.0
            scale = max(float(np.max(np.abs(before.tocsr().data))), 1.0)
            assert max_error / scale < 1e-14
            np.testing.assert_array_equal(f0, f1)
            results.append(
                dict(
                    case=name,
                    operation=material + "_assembly",
                    nodes=len(mesh.nodes),
                    before_s=t0,
                    after_s=t1,
                    speedup=t0 / t1,
                    max_abs_error=max_error,
                    relative_max_error=max_error / scale,
                )
            )
            print(json.dumps(results[-1]), flush=True)
    old_gc = baseline_function(
        fem, "compute_generalized_correlation_matrix", args.baseline
    )
    for n in [504, 1500]:
        rng = np.random.default_rng(42)
        lam = np.geomspace(0.1, 10.0, 200)
        phi = rng.normal(size=(6 * n, 200))

        def with_modes(fn):
            scope = fn.__globals__.copy()
            scope["_nma_modes"] = lambda *a: (lam, phi)
            return types.FunctionType(fn.__code__, scope, fn.__name__, fn.__defaults__)

        before, t0 = timed(with_modes(old_gc), None, n)
        after, t1 = timed(
            with_modes(fem.compute_generalized_correlation_matrix), None, n
        )
        error = float(np.max(np.abs(before - after)))
        np.testing.assert_allclose(after, before, rtol=1e-12, atol=1e-12)
        results.append(
            dict(
                case=f"{n}_nodes_200_modes",
                operation="generalized_correlation_post_nma",
                before_s=t0,
                after_s=t1,
                speedup=t0 / t1,
                max_abs_error=error,
            )
        )
        print(json.dumps(results[-1]), flush=True)
    print(json.dumps({"baseline": args.baseline, "results": results}, indent=2))


if __name__ == "__main__":
    main()
