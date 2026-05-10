"""
rebuild_periodic_cell.py — Rebuild the periodic cell package with consensus sequences.

Loads B_tube, calls build_periodic_cell_package (which now runs
assign_consensus_sequence internally), extracts the ZIP to the run directory,
and validates that the PDB has mixed A/T/G/C residues.

Usage:
    python experiments/exp23_periodic_cell_benchmark/rebuild_periodic_cell.py
"""

from __future__ import annotations

import io
import json
import zipfile
from collections import Counter
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.core.models import Design
from backend.core.periodic_cell import build_periodic_cell_package

DESIGN_PATH = Path("workspace/B_tube.nadoc")
RUN_DIR     = Path("experiments/exp23_periodic_cell_benchmark/results/periodic_cell_run")
OUT_DIR     = RUN_DIR / "output"
ZIP_PATH    = Path("experiments/exp23_periodic_cell_benchmark/results/periodic_cell.zip")

def main() -> None:
    # ── 1. Load design ────────────────────────────────────────────────────────
    print(f"Loading design: {DESIGN_PATH}")
    design = Design.model_validate(json.load(open(DESIGN_PATH)))
    print(f"  Helices: {len(design.helices)}, Strands: {len(design.strands)}")
    n_seq = sum(1 for s in design.strands if s.sequence)
    print(f"  Strands with sequences: {n_seq}/{len(design.strands)}")

    # ── 2. Build package ──────────────────────────────────────────────────────
    print("Building periodic cell package (solvation takes ~1-2 min)…")
    zip_bytes = build_periodic_cell_package(design)
    ZIP_PATH.parent.mkdir(parents=True, exist_ok=True)
    ZIP_PATH.write_bytes(zip_bytes)
    print(f"  ZIP size: {len(zip_bytes)/1e6:.1f} MB")
    print(f"  ZIP path: {ZIP_PATH}")

    # ── 3. Extract to run directory ───────────────────────────────────────────
    print(f"Extracting to: {RUN_DIR}")
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for info in zf.infolist():
            member = info.filename
            # Strip leading "B_tube_periodic_1x/" prefix
            parts = Path(member).parts
            rel   = Path(*parts[1:]) if len(parts) > 1 else None
            if rel is None or str(rel) == ".":
                continue
            dest = RUN_DIR / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(info))
            mode = (info.external_attr >> 16) & 0o777
            if mode:
                if dest.suffix in (".sh", ".py") and not (mode & 0o111):
                    mode = 0o755
                dest.chmod(mode)
            elif dest.suffix in (".sh", ".py"):
                dest.chmod(0o755)
            print(f"  wrote {dest.relative_to(RUN_DIR)}")

    # ── 4. Verify residue composition ─────────────────────────────────────────
    pdb_path = RUN_DIR / "B_tube_periodic_1x.pdb"
    print(f"\nVerifying PDB: {pdb_path}")
    resname_counts: Counter = Counter()
    with open(pdb_path) as f:
        for line in f:
            if line[:6] in ("ATOM  ", "HETATM"):
                resname = line[17:21].strip()
                if resname in ("DA", "DT", "DG", "DC"):
                    resname_counts[resname] += 1

    total_dna = sum(resname_counts.values())
    print(f"  DNA residue counts: {dict(resname_counts)}")
    print(f"  Total DNA atoms: {total_dna:,}")

    if len(resname_counts) < 2:
        print("  FAIL: only one residue type found — sequence assignment may have failed")
        sys.exit(1)
    else:
        pct_dt = resname_counts.get("DT", 0) / total_dna * 100
        if pct_dt > 95:
            print(f"  FAIL: {pct_dt:.1f}% DT — still effectively poly-T")
            sys.exit(1)
        print(f"  OK: mixed residues confirmed ({pct_dt:.1f}% DT)")

    print("\nRebuild complete. Suggested phase order:")
    print(f"  cd {RUN_DIR}")
    print("  namd3 +p16 +devices 0 equilibrate_npt.conf > output/equilibrate_npt.log 2>&1")
    print("  scripts/lock_box_from_xst.py --xst output/B_tube_periodic_1x_equilibrate_npt.xst --template relax_locked_nvt.template.conf --out relax_locked_nvt.conf --z-angstrom 70.140")
    print("  namd3 +p16 +devices 0 relax_locked_nvt.conf > output/relax_locked_nvt.log 2>&1")
    print("  for f in ramp_locked_nvt_*.template.conf; do scripts/lock_box_from_xst.py --xst output/B_tube_periodic_1x_equilibrate_npt.xst --template \"$f\" --out \"${f%.template.conf}.conf\" --z-angstrom 70.140 && namd3 +p16 +devices 0 \"${f%.template.conf}.conf\" > \"output/${f%.template.conf}.log\" 2>&1; done")
    print("  scripts/lock_box_from_xst.py --xst output/B_tube_periodic_1x_equilibrate_npt.xst --template production_locked_nvt.template.conf --out production_locked_nvt.conf --z-angstrom 70.140")
    print("  namd3 +p16 +devices 0 production_locked_nvt.conf > output/production_locked_nvt.log 2>&1")
    print("\nOr run a short automated smoke:")
    print("  python experiments/exp23_periodic_cell_benchmark/run.py --skip-build --ramp-smoke")


if __name__ == "__main__":
    main()
