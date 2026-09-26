"""Real-design before/after surface benchmark; run through test_guard in a test session."""

import argparse
import gzip
import json
import os
import statistics
import subprocess
import sys
import time
import types
from unittest.mock import patch
import numpy as np
from backend.core import surface
from backend.core.models import Design
from backend.api.routes_display_geometry import _build_design_surface_mesh
from tests.conftest import make_6hb_design


def main():
    os.environ["NADOC_SURFACE_GPU"] = "0"  # This benchmark isolates CPU refactoring.
    p = argparse.ArgumentParser()
    p.add_argument("--baseline", required=True)
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--voltron", action="store_true")
    p.add_argument("--detail", action="append", choices=["coarse", "chimerax"])
    args = p.parse_args()
    source = subprocess.check_output(
        ["git", "show", f"{args.baseline}:backend/core/surface.py"], text=True
    )
    old = types.ModuleType("surface_benchmark_baseline")
    sys.modules[old.__name__] = old
    exec(compile(source, "<baseline-surface>", "exec"), old.__dict__)
    designs = [("6hb-84bp", make_6hb_design(84))]
    if args.voltron:
        with gzip.open("tests/fixtures/voltroncore_surface_input.json.gz", "rt") as f:
            designs.append(("VoltronCore", Design.model_validate(json.load(f))))
    # The route imports this module locally. Swap only public functions, so each
    # version retains its own module globals and helpers for an independent oracle.
    names = [
        "compute_surface",
        "compute_surface_from_cloud",
        "smooth_mesh",
        "cg_surface_mesh",
        "compute_split_surfaces_from_cloud",
    ]
    for name, design in designs:
        for detail in args.detail or ["coarse", "chimerax"]:
            times = [[], []]
            expected = None
            for repeat in range(args.repeats):
                for index in [0, 1] if repeat % 2 == 0 else [1, 0]:
                    overrides = (
                        {n: getattr(old, n) for n in names} if index == 0 else {}
                    )
                    with (
                        patch.multiple(surface, **overrides)
                        if overrides
                        else patch.dict({}, {})
                    ):
                        start = time.perf_counter()
                        m = _build_design_surface_mesh(
                            design, 0.2, 0.28, 1.3, 15, detail
                        )
                        times[index].append(time.perf_counter() - start)
                    if expected is None:
                        expected = m
                    np.testing.assert_array_equal(m.vertices, expected.vertices)
                    np.testing.assert_array_equal(m.faces, expected.faces)
                    assert m.vertex_strand_ids == expected.vertex_strand_ids
                    assert m.vertex_nuc_ids == expected.vertex_nuc_ids
            before, after = map(statistics.median, times)
            print(
                json.dumps(
                    dict(
                        design=name,
                        detail=detail,
                        baseline=args.baseline,
                        before_s=before,
                        after_s=after,
                        speedup=before / after,
                        samples=times,
                        vertices=len(m.vertices),
                        faces=len(m.faces),
                        exact=True,
                    )
                ),
                flush=True,
            )


if __name__ == "__main__":
    main()
