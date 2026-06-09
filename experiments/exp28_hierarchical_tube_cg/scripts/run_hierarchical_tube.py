#!/usr/bin/env python3
"""Run the Exp28 hierarchical coarse tube workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from experiments.exp28_hierarchical_tube_cg.tube_cg import run_workflow


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, help="tube_spec.json override file")
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("experiments/exp28_hierarchical_tube_cg/results/default"),
    )
    ap.add_argument("--perturb-nm", type=float, default=0.0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--no-reconstruct",
        action="store_true",
        help="Skip windowed atomistic reconstruction and only write symbolic CG outputs.",
    )
    args = ap.parse_args()

    written = run_workflow(
        spec_path=args.spec,
        out_dir=args.out_dir,
        perturb_nm=args.perturb_nm,
        seed=args.seed,
        reconstruct=not args.no_reconstruct,
    )
    print(json.dumps({"out_dir": str(args.out_dir), "written": written}, indent=2))


if __name__ == "__main__":
    main()

