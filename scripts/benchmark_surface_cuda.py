"""Compare optimized CPU vs optional CUDA closing on complete real-design surfaces.
Run through test_guard with an active test session. Requires local CUDA PyTorch.
"""

import gzip
import hashlib
import json
import os
from pathlib import Path
import statistics
import time
from unittest.mock import patch
import numpy as np
from backend.core import surface_acceleration as accel
from backend.core.models import Design
from backend.api.routes_display_geometry import _build_design_surface_mesh
from tests.conftest import make_6hb_design


def main():
    with gzip.open("tests/fixtures/voltroncore_surface_input.json.gz", "rt") as f:
        large = Design.model_validate(json.load(f))
    results = []
    for name, design in [("6hb-84bp", make_6hb_design(84)), ("VoltronCore", large)]:
        samples = [[], []]
        expected = None
        accelerated = []
        original = accel._try_cuda_closing

        def observed(grid, structure):
            result = original(grid, structure)
            accelerated.append(result is not None)
            return result

        for repeat in range(3):
            for index in [0, 1] if repeat % 2 == 0 else [1, 0]:
                accelerated.clear()
                with (
                    patch.dict(os.environ, {"NADOC_SURFACE_GPU": str(index)}),
                    patch.object(accel, "_try_cuda_closing", observed),
                ):
                    start = time.perf_counter()
                    mesh = _build_design_surface_mesh(
                        design, 0.2, 0.28, 1.3, 15, "chimerax"
                    )
                    elapsed = time.perf_counter() - start
                samples[index].append(elapsed)
                if expected is None:
                    expected = mesh
                np.testing.assert_array_equal(mesh.vertices, expected.vertices)
                np.testing.assert_array_equal(mesh.faces, expected.faces)
                assert mesh.vertex_strand_ids == expected.vertex_strand_ids
                assert mesh.vertex_nuc_ids == expected.vertex_nuc_ids
                if index:
                    assert any(accelerated), "No real CUDA closing was used"
                print(
                    json.dumps(
                        dict(
                            design=name,
                            repeat=repeat,
                            gpu=bool(index),
                            seconds=elapsed,
                            accelerated=sum(accelerated),
                            fallback=len(accelerated) - sum(accelerated),
                            exact=True,
                        )
                    ),
                    flush=True,
                )
        cpu, gpu = map(statistics.median, samples)
        results.append(
            dict(
                design=name,
                cpu_s=cpu,
                gpu_s=gpu,
                speedup=cpu / gpu,
                samples=samples,
                exact=True,
            )
        )
    hashes = {
        p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
        for p in ["backend/core/surface.py", "backend/core/surface_acceleration.py"]
    }
    print(json.dumps(dict(results=results, source_sha256=hashes), indent=2), flush=True)


if __name__ == "__main__":
    main()
