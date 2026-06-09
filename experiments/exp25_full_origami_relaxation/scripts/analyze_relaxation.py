"""Measure early full-origami relaxation from NAMD DCD/restart outputs."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np


def _load_positions(pdb: Path, psf: Path, dcd: Path | None, coor: Path | None) -> tuple[np.ndarray, np.ndarray]:
    import MDAnalysis as mda

    ref = mda.Universe(str(psf), str(pdb))
    ref_pos = np.asarray(ref.atoms.positions, dtype=float) / 10.0

    if dcd is not None and dcd.exists():
        u = mda.Universe(str(psf), str(dcd))
        frames = []
        for ts in u.trajectory:
            frames.append(np.asarray(u.atoms.positions, dtype=float) / 10.0)
        if frames:
            return ref_pos, np.stack(frames, axis=0)

    if coor is None or not coor.exists():
        raise SystemExit("No DCD frames and no coordinate restart file found.")
    u = mda.Universe(str(psf), str(coor), format="NAMDBIN")
    return ref_pos, np.asarray(u.atoms.positions, dtype=float)[None, :, :] / 10.0


def _summarize(ref_pos: np.ndarray, frames: np.ndarray) -> dict:
    metrics = []
    for i, pos in enumerate(frames):
        disp = pos - ref_pos
        norm = np.linalg.norm(disp, axis=1)
        metrics.append({
            "frame": i,
            "rmsd_nm": math.sqrt(float(np.mean(np.sum(disp * disp, axis=1)))),
            "mean_disp_nm": float(np.mean(norm)),
            "p50_disp_nm": float(np.percentile(norm, 50)),
            "p90_disp_nm": float(np.percentile(norm, 90)),
            "p99_disp_nm": float(np.percentile(norm, 99)),
            "max_disp_nm": float(np.max(norm)),
        })

    final = metrics[-1]
    return {
        "n_atoms": int(ref_pos.shape[0]),
        "n_frames": int(frames.shape[0]),
        "initial": metrics[0],
        "final": final,
        "frames": metrics,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--psf", type=Path, required=True)
    ap.add_argument("--pdb", type=Path, required=True)
    ap.add_argument("--dcd", type=Path)
    ap.add_argument("--coor", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    ref_pos, frames = _load_positions(args.pdb, args.psf, args.dcd, args.coor)
    result = _summarize(ref_pos, frames)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2))
    print(json.dumps({
        "n_atoms": result["n_atoms"],
        "n_frames": result["n_frames"],
        "final": result["final"],
    }, indent=2))


if __name__ == "__main__":
    main()
