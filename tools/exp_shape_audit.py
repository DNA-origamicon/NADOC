"""CPU-only, sparse shape triage of inventoried NAMD production trajectories.

This nominates windows for further analysis, NOT equilibrium training labels.
It never modifies trajectories or starts simulations. Units in the output are nm.
Run with BLAS threads capped; output belongs under .development-artifacts/.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import time

import numpy as np

from backend.core.dcd_fast import read_frame, read_layout


def c1_indices(psf: Path, expected_atoms: int) -> np.ndarray:
    with psf.open() as stream:
        for line in stream:
            if "!NATOM" in line:
                count = int(line.split()[0])
                if count != expected_atoms:
                    raise ValueError("PSF/DCD atom counts differ")
                indices = []
                for i in range(count):
                    fields = next(stream).split()
                    if fields[4] in {"C1'", "C1*"}:
                        indices.append(i)
                if len(indices) < 3:
                    raise ValueError("Too few DNA C1 atoms")
                return np.array(indices)
    raise ValueError("Missing NATOM")


def align(x, reference):
    x = x - x.mean(axis=0)
    reference = reference - reference.mean(axis=0)
    u, _, vt = np.linalg.svd(x.T @ reference)
    correction = np.diag([1., 1., np.linalg.det(u @ vt)])
    return x @ u @ correction @ vt


def audit(dcd: Path, psf: Path, samples: int = 64):
    start = time.monotonic()
    layout = read_layout(dcd)
    indices = c1_indices(psf, layout.n_atoms)
    selected = np.unique(np.linspace(layout.n_frames // 2, layout.n_frames - 1,
                                    samples, dtype=int))
    if len(selected) < 16:
        raise ValueError("Need at least 16 sampled frames")
    frames, cells = [], []
    for i in selected:
        coords, cell = read_frame(dcd, layout, int(i))
        x = coords[indices].astype(float) / 10
        x -= x.mean(axis=0)
        frames.append(x)
        if cell is not None:
            cells.append([float(cell[j]) / 10 for j in (0, 2, 5)])
    raw = np.array(frames)
    aligned = np.array([align(x, raw[0]) for x in raw])
    # A second generalized-Procrustes pass reduces first-frame reference bias.
    mean = aligned.mean(axis=0)
    aligned = np.array([align(x, mean) for x in raw])
    blocks = np.array_split(aligned, 4)
    means = np.array([b.mean(axis=0) for b in blocks])
    rg = np.sqrt(np.mean(np.sum(raw**2, axis=2), axis=1))
    rms = lambda x: float(np.sqrt(np.mean(np.sum(x*x, axis=-1))))
    return {
        "dcd": str(dcd), "psf": str(psf), "samples": len(selected),
        "c1_atoms": len(indices), "atom_count": layout.n_atoms,
        "sample_frame_indices": selected.tolist(),
        "header_time_window_ns": [(layout.first_ps + int(i)*layout.delta_ps)/1000
                                  for i in (selected[0], selected[-1])],
        "block_rg_nm": [float(b.mean()) for b in np.array_split(rg, 4)],
        "block_mean_shift_nm": [rms(align(b, means[0])-means[0]) for b in means],
        "block_internal_rmsf_nm": [rms(b-b.mean(axis=0)) for b in blocks],
        "cell_length_ranges_nm": np.ptp(cells, axis=0).tolist() if cells else None,
        "wall_seconds": time.monotonic()-start,
        "qualification": "triage_only; no PBC unwrapping, contact/pairing test, effective sample size or independent-replica validation",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--jobs", nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rows = json.loads(args.inventory.read_text())
    results = []
    for job_id in args.jobs:
        row = next(r for r in rows if r["job_id"] == job_id)
        # Select the longest file, never silently concatenate overlapping continuations.
        dcd = max((Path(c["dcd"]) for c in row["configs"]), key=lambda p: p.stat().st_size)
        psfs = sorted(dcd.parent.parent.glob("*.psf"))
        if not psfs:
            psfs = sorted(Path(row["job_dir"]).glob("package/*/*.psf"))
        try:
            if not psfs:
                raise ValueError("No PSF found in source package")
            result = audit(dcd, psfs[0])
        except Exception as exc:
            result = {"error": str(exc)}
        results.append({"job_id": job_id, "design": row["design_name"], **result})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, indent=2)+"\n")
        print(json.dumps(results[-1]), flush=True)


if __name__ == "__main__":
    main()
