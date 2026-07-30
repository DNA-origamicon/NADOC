#!/usr/bin/env python3
"""Two solvated ladder packages, identical except for the starting coordinates.

  cold — solvate the IDEALISED build (what Relax does today)
  vac  — solvate the VACUUM ENRG-MD relaxed structure

Everything else is held equal: same protocol, padding, salt, box mode, ladder. The
comparison then answers the two questions directly:

  * "does it speed up the relax overall?" — solvated atom count sets the per-step cost,
    so a smaller box after vacuum relaxation is a speed-up before a single step runs.
  * "can we cut more from the ladder?" — run both ladders and see how early each one's
    observables plateau.

The vacuum coordinates enter through ``solute_coords``, the same (N,3) psfgen-ordered
hook the BLADE seed uses, with ``require_full_topology`` because that alignment only
holds under the full all-hydrogen topology.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from backend.core.md_presets import EXPLICIT_PROTOCOL  # noqa: E402
from backend.core.md_protocols import prepare_mgh_slow_release  # noqa: E402

from build_vacuum import load_design  # noqa: E402

# The Standard (Aksimentiev) preset's solvation settings — see backend/core/md_presets.py.
PADDING_NM = 1.2
WATER_SHELL_NM = 0.0        # 0 = full water box, no carve (no vacuum corners)


def vacuum_final_coords(run_dir: Path, stem: str) -> np.ndarray:
    """Final heavy+hydrogen coordinates of the vacuum run, in psfgen atom order."""
    import MDAnalysis as mda

    psf = run_dir / f"{stem}.psf"
    coor = run_dir / "output" / f"{stem}.restart.coor"
    if coor.exists():
        u = mda.Universe(str(psf), str(coor), format="NAMDBIN")
        return u.atoms.positions.copy()
    dcd = run_dir / "output" / f"{stem}.dcd"
    u = mda.Universe(str(psf), str(dcd))
    u.trajectory[-1]
    return u.atoms.positions.copy()


def build_arm(design, out: Path, *, solute_coords=None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    kw = dict(
        protocol=EXPLICIT_PROTOCOL,
        salt_mode="screening",
        padding_nm=PADDING_NM,
        water_shell_nm=WATER_SHELL_NM,
    )
    if solute_coords is not None:
        kw["solute_coords"] = solute_coords
        kw["require_full_topology"] = True
    t0 = time.time()
    subdir, stem, segments = prepare_mgh_slow_release(design, out, **kw)
    dt = time.time() - t0

    pkg = out / subdir
    manifest = json.loads((pkg / "manifest.json").read_text())
    psf = next(pkg.glob("*_hmr.psf"), None) or next(pkg.glob("*.psf"))
    n_atoms = None
    for line in psf.read_text(errors="replace").splitlines()[:8]:
        if "!NATOM" in line:
            n_atoms = int(line.split()[0])
            break
    return {
        "subdir": subdir, "stem": stem, "prep_seconds": round(dt, 1),
        "n_atoms": n_atoms,
        "n_segments": len(segments),
        "total_steps": int(sum(getattr(s, "steps", 0) for s in segments)),
        "segments": [{"name": s.name, "stage": getattr(s, "stage", ""),
                      "steps": getattr(s, "steps", 0)} for s in segments],
        "solvation": manifest.get("solvation"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("design", type=Path)
    ap.add_argument("--vacuum-dir", type=Path, required=True)
    ap.add_argument("-o", "--out", type=Path, required=True)
    args = ap.parse_args()

    design = load_design(args.design)
    info = json.loads((args.vacuum_dir / "build_info.json").read_text())
    stem = info["stem"]

    print("[cold] solvating the idealised build…")
    cold = build_arm(design, args.out / "cold")
    print(f"       {cold['n_atoms']:,} atoms, {cold['n_segments']} segments, "
          f"{cold['total_steps']:,} steps  ({cold['prep_seconds']}s prep)")

    print("[vac ] solvating the vacuum-relaxed structure…")
    coords = vacuum_final_coords(args.vacuum_dir, stem)
    print(f"       seed coords: {coords.shape[0]:,} atoms from the vacuum run")
    vac = build_arm(design, args.out / "vac", solute_coords=coords)
    print(f"       {vac['n_atoms']:,} atoms, {vac['n_segments']} segments, "
          f"{vac['total_steps']:,} steps  ({vac['prep_seconds']}s prep)")

    d = 100 * (vac["n_atoms"] / cold["n_atoms"] - 1) if cold["n_atoms"] else 0.0
    print()
    print(f"SOLVATED ATOM COUNT  {cold['n_atoms']:,} (cold) -> {vac['n_atoms']:,} (vac)"
          f"   {d:+.1f}%")
    print("Per-step cost scales with atom count, so this is the speed-up (or penalty)")
    print("that applies before a single ladder step runs.")

    (args.out / "arms.json").write_text(json.dumps(
        {"cold": cold, "vac": vac, "design": str(args.design),
         "vacuum": info}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
