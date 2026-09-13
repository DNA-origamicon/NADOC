"""Read-only benchmark of NAMD heavy-frame extraction (setup reported separately).

Run from the repository root:
  .venv/bin/python scripts/benchmark_namd_trajectory.py JOB_DIRECTORY
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.core.models import Design
from backend.core.md_trajectory import _build_md_nadoc_ctx, _extract_md_atoms_frame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("--frames", type=int, default=10)
    args = parser.parse_args()
    if args.frames < 1:
        parser.error("--frames must be positive")
    psfs = sorted((args.job / "package").glob("*/*.psf"))
    psf = next(p for p in psfs if not p.stem.endswith("_hmr"))
    paths = sorted((psf.parent / "output").glob("*.dcd"))
    design = Design.model_validate_json((args.job / "design.json").read_text())
    start = time.perf_counter()
    ctx = _build_md_nadoc_ctx(psf, paths, psf.with_suffix(".pdb"), design, with_atoms=True)
    setup = time.perf_counter() - start
    prefix = ctx.get("dcd_prefix")
    indices = np.linspace(0, ctx["n_frames"] - 1, min(args.frames, ctx["n_frames"]), dtype=int)
    serials = np.array([a["serial"] for a in ctx["atom_meta"]], dtype=np.int64)
    timings = {"records_full_read_ms": [], "coordinates_prefix_read_ms": [], "scatter_and_list_ms": []}
    error = 0.0
    try:
        for idx in indices:
            start = time.perf_counter()
            records = _extract_md_atoms_frame(ctx, int(idx))
            timings["records_full_read_ms"].append((time.perf_counter() - start) * 1000)
            expected = np.array([[a[k] for k in ("x", "y", "z")] for a in records])
            start = time.perf_counter()
            actual = _extract_md_atoms_frame(ctx, int(idx), positions_only=True)
            timings["coordinates_prefix_read_ms"].append((time.perf_counter() - start) * 1000)
            error = max(error, float(np.max(np.abs(expected - actual))))
            np.testing.assert_allclose(actual, expected, rtol=0, atol=1e-7)
            start = time.perf_counter()
            flat = np.zeros((int(serials.max()) + 1, 3))
            flat[serials] = np.round(actual, 4)
            flat.ravel().tolist()
            timings["scatter_and_list_ms"].append((time.perf_counter() - start) * 1000)
        print(json.dumps({"setup_seconds": setup, "atoms": len(serials), "frames": len(indices),
                          "prefix_reader": prefix is not None, "max_error_nm": error,
                          "median_ms": {k: float(np.median(v)) for k, v in timings.items()}}, indent=2))
    finally:
        if prefix is not None:
            prefix.close()
        ctx["universe"].trajectory.close()


if __name__ == "__main__":
    main()
