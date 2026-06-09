#!/usr/bin/env python3
"""Build an explicit-solvent NaCl/MgCl2 NAMD package from a NADOC design."""

from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.models import Design
from backend.core.namd_solvate import build_namd_solvated_package, get_solvation_stats


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--design", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--padding-nm", type=float, default=1.2)
    ap.add_argument("--nacl-mM", type=float, default=150.0)
    ap.add_argument("--mgcl2-mM", type=float, default=12.5)
    ap.add_argument("--mg-hexahydrate", action="store_true")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--stats-only", action="store_true")
    args = ap.parse_args()

    design = Design.model_validate_json(args.design.read_text())
    stats = get_solvation_stats(
        design,
        padding_nm=args.padding_nm,
        ion_conc_mM=args.nacl_mM,
        mg_conc_mM=args.mgcl2_mM,
        mg_hexahydrate=args.mg_hexahydrate,
    )
    print("Estimated explicit-solvent system:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    if args.stats_only:
        return

    data = build_namd_solvated_package(
        design,
        padding_nm=args.padding_nm,
        ion_conc_mM=args.nacl_mM,
        mg_conc_mM=args.mgcl2_mM,
        mg_hexahydrate=args.mg_hexahydrate,
        seed=args.seed,
    )
    args.out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = args.out_dir / "explicit_mg_package.zip"
    zip_path.write_bytes(data)
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(args.out_dir)
    print(f"Wrote {zip_path} and extracted it under {args.out_dir}")


if __name__ == "__main__":
    main()
