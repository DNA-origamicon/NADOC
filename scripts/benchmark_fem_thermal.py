"""Read-only reconstruction benchmark; does not solve modes or create jobs.

Run with one BLAS thread, e.g.:
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 uv run python -m scripts.benchmark_fem_thermal SNAPSHOT
"""

import argparse
import time
import json
import resource
from pathlib import Path
import numpy as np
from backend.core.models import Design
from backend.physics.fem_solver import build_fem_mesh, deformed_positions_with_axis
from backend.physics.fem_thermal_reconstruction import ThermalReconstruction


def stamp(label, start):
    print(label, round(time.perf_counter() - start, 3), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    path = parser.parse_args().snapshot
    design = Design.from_json(path.read_text())
    mesh = build_fem_mesh(design)
    print("nodes", len(mesh.nodes), flush=True)
    rng = np.random.default_rng(20260927)
    u = rng.normal(0, 0.025, 6 * len(mesh.nodes))
    t = time.perf_counter()
    baseline, _ = deformed_positions_with_axis(design, mesh, np.zeros_like(u))
    stamp("static reference seconds", t)
    t = time.perf_counter()
    context = ThermalReconstruction(design, mesh, baseline)
    stamp("prepare context seconds", t)
    del baseline
    for i in range(2):
        draw = u * (i + 1)
        t = time.perf_counter()
        old, _ = deformed_positions_with_axis(design, mesh, draw)
        old_time = time.perf_counter() - t
        stamp("full reconstruction seconds", t)
        t = time.perf_counter()
        xyz = context.coordinates(draw)
        new_time = time.perf_counter() - t
        stamp("thermal XYZ seconds", t)
        assert context.keys == [
            [p["helix_id"], p["bp_index"], p["direction"], p.get("copy", 0)]
            for p in old
        ]
        error = float(
            np.max(np.abs(xyz - np.asarray([p["backbone_position"] for p in old])))
        )
        print(
            json.dumps(
                {
                    "draw": i,
                    "nucleotides": len(xyz),
                    "max_abs_error_nm": error,
                    "speedup": old_time / new_time,
                    "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
                    / 1024,
                }
            ),
            flush=True,
        )
        assert error < 1e-9
        del old, xyz


if __name__ == "__main__":
    main()
