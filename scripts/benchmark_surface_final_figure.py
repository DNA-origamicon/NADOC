"""Matched, lossless surface optimizations at the requested probe; read-only input."""

from contextlib import ExitStack
from unittest.mock import patch
from pathlib import Path
import hashlib
import json
import statistics
import time
import numpy as np
from backend.core.models import Design
from backend.api.routes_display_geometry import _build_design_surface_mesh
from backend.core import surface_tiled, surface_remesh
from backend.core.surface import surface_to_json
from backend.core.oxdna_health import pack_surface_bin
from backend.core.surface_acceleration import initialize_surface_cuda
from backend.core.surface_quality import surface_quality


def reference_weld(keys):
    _, first, inverse = np.unique(keys, axis=0, return_index=True, return_inverse=True)
    return first, inverse


def reference_edges(faces):
    edges = np.sort(
        np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]]), axis=1
    )
    stride = int(faces.max()) + 1
    keys = edges[:, 0] * stride + edges[:, 1]
    unique_keys, inverse, counts = np.unique(
        keys, return_inverse=True, return_counts=True
    )
    unique = np.column_stack([unique_keys // stride, unique_keys % stride])
    order = np.argsort(inverse, kind="stable")
    starts = np.r_[0, np.cumsum(counts)[:-1]]
    paired = np.flatnonzero(counts == 2)
    owners = np.tile(np.arange(len(faces)), 3)[order]
    adjacent = np.column_stack([owners[starts[paired]], owners[starts[paired] + 1]])
    return unique, inverse.reshape(3, -1).T, paired, adjacent


def main():
    design = Design.model_validate_json(Path("workspace/mini_rect.nadoc").read_text())
    result = {
        "design": "workspace/mini_rect.nadoc",
        "probe_nm": 0.06,
        "cuda": initialize_surface_cuda(),
        "samples": [],
    }
    digest = None
    for repeat in range(4):
        for optimized in [False, True] if repeat % 2 == 0 else [True, False]:
            with ExitStack() as stack:
                if not optimized:
                    stack.enter_context(
                        patch.object(surface_tiled, "weld_key_indices", reference_weld)
                    )
                    stack.enter_context(
                        patch.object(surface_remesh, "_edge_table", reference_edges)
                    )
                start = time.perf_counter()
                mesh = _build_design_surface_mesh(
                    design, 0.2, 0.06, 1.3, 15, "chimerax"
                )
                generated = time.perf_counter()
                data = pack_surface_bin(
                    surface_to_json(mesh, design, array_payload=optimized)
                )
                end = time.perf_counter()
            sha = hashlib.sha256(data).hexdigest()
            if digest is None:
                digest = sha
            assert sha == digest, "Optimization changed mesh bytes"
            row = {
                "optimized": optimized,
                "warmup": repeat == 0,
                "mesh_s": generated - start,
                "packing_s": end - generated,
                "total_s": end - start,
            }
            result["samples"].append(row)
            print(row, flush=True)
    result["sha256"] = digest
    result["bytes"] = len(data)
    result["quality"] = surface_quality(mesh)
    result["medians"] = {
        str(flag): statistics.median(
            r["total_s"]
            for r in result["samples"]
            if r["optimized"] == flag and not r["warmup"]
        )
        for flag in [False, True]
    }
    output = Path(".development-artifacts/surface-final-figure/benchmark.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(result["medians"], flush=True)


if __name__ == "__main__":
    main()
