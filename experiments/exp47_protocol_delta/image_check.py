#!/usr/bin/env python3
"""Did the arm end up with the solute touching its own periodic image?

Surviving the run is not the same as surviving into a usable state: an arm can complete
2 ns precisely by reaching the collapsed cell.  This measures, on the last DCD frame,
the minimum distance between any DNA atom and any DNA atom of the 26 neighbouring
periodic images.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "exp46_xb_placement"))
from xb_map import FrameJoiner, build_package_map, load_design  # noqa: E402

WORK = Path("/media/jojo/Archive/exp47_protocol_delta")
PKG = WORK / "pkg"
STEM = "2hb_1xT"
DESIGN = Path("/media/jojo/Archive/NADOC_archive/29c5b267380f/design.json")
SHIFTS = [np.array([a, b, c]) for a in (-1, 0, 1) for b in (-1, 0, 1)
          for c in (-1, 0, 1) if (a, b, c) != (0, 0, 0)]


def main():
    import MDAnalysis as mda
    design = load_design(DESIGN)
    pm = build_package_map(design, PKG / f"{STEM}.pdb")
    man = json.loads((WORK / "arms.json").read_text())
    print(f"{'arm':<15s} {'status':<7s} {'box a':>8s} {'DNA x-span':>11s} "
          f"{'min image d':>12s}")
    print("-" * 60)
    for arm in man:
        dcd = PKG / "out" / arm / f"{STEM}.dcd"
        if not dcd.exists() or dcd.stat().st_size < 1000:
            print(f"{arm:<15s} {man[arm]['status']:<7s} {'-':>8s} {'-':>11s} {'no dcd':>12s}")
            continue
        u = mda.Universe(str(PKG / f"{STEM}_hmr.psf"), str(dcd))
        fj = FrameJoiner(u, pm, design)
        ts = u.trajectory[-1]
        box = ts.dimensions[:3].astype(float)
        X = fj.positions(box)
        t = cKDTree(X)
        dmin = min(t.query(X + s * box, k=1)[0].min() for s in SHIFTS)
        span = X.max(0) - X.min(0)
        print(f"{arm:<15s} {man[arm]['status']:<7s} {box[0]:>8.2f} {span[0]:>11.1f} "
              f"{dmin:>12.2f}")
    print("\nDNA-to-own-image distance: >24 A (2x cutoff) is clean; <12 A is direct "
          "interaction; <3 A is contact.")


if __name__ == "__main__":
    main()
