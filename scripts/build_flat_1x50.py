#!/usr/bin/env python
"""Headlessly build ``flat_1x50.nadoc`` — a single-layer 50-helix SQUARE-lattice sheet.

The box-shape stress case for the RunPod benchmark (experiments/exp43_runpod_bench).
One row of 50 helices at SQUARE_COL_PITCH = 2.6 nm is ~1290 A wide against a ~20 A
single-layer thickness — an extreme aspect ratio that exercises the PME grid and
NAMD's patch decomposition in a way a compact bundle (6hb: 96 x 112 x 213 A) never does.

Length is a multiple of the square lattice's 32 bp crossover period.

Usage:
    python scripts/build_flat_1x50.py                    # workspace/flat_1x50.nadoc, 64 bp
    python scripts/build_flat_1x50.py OUT.nadoc 128      # custom output + length
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType

N_HELICES = 50
DEFAULT_LENGTH_BP = 64  # multiple of the SQ 32 bp crossover period
NAME = "flat_1x50"

# One row, 50 columns -> a flat single-layer sheet.
CELLS = [[0, c] for c in range(N_HELICES)]


def build(length_bp: int = DEFAULT_LENGTH_BP) -> str:
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(CELLS, length_bp, lattice=LatticeType.SQUARE, name=NAME)
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple(scaffold_name="M13mp18")
        hb.apply_loop_skip_deformations()
        hb.assign_scaffold_sequence("M13mp18")
        hb.assign_staple_sequences()
        return design_state.get_or_404().to_json()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("workspace/flat_1x50.nadoc")
    length = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_LENGTH_BP
    out.write_text(build(length))
    print(f"wrote {out}  ({N_HELICES} helices x {length} bp, SQUARE, single layer)")


if __name__ == "__main__":
    main()
