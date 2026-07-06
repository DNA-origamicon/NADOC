#!/usr/bin/env python
"""Headlessly regenerate ``3x6x200_test.nadoc`` — the fixture design used by the
one-off MD-display-toggle E2E specs (``frontend/e2e/md_display_toggle*.spec.js``).

The design is a scratch/regenerable fixture, so it is NOT committed to git
(``.gitignore``d).  This script rebuilds it deterministically by replaying the
exact recipe recorded in the original file's feature log:

    3x6 SQUARE bundle @ 200 bp  (snake-ordered cells → fixed helix ids)
      → seamless auto-scaffold
      → full autostaple (M13mp18)
      → apply loop/skips (SQ-periodic)
      → assign scaffold sequence (M13mp18)
      → assign staple sequences

Helix ordering (the ``cells`` list) is reproduced byte-for-byte because the live
NAMD job's psfgen segid → p_order mapping is keyed off it; a different order would
break the display-toggle spec's mapping assertion.

Usage:
    python scripts/build_3x6x200_test.py            # writes ./3x6x200_test.nadoc
    python scripts/build_3x6x200_test.py OUT.nadoc  # writes to OUT.nadoc
"""
from __future__ import annotations

import sys
from pathlib import Path

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.models import LatticeType

# Exact snake-ordered cells from the original file's bundle-create feature-log entry.
CELLS = [
    [0, 0], [0, 1], [0, 2], [0, 3], [0, 4], [0, 5],
    [1, 5], [1, 4], [1, 3], [1, 2], [1, 1], [1, 0],
    [2, 0], [2, 1], [2, 2], [2, 3], [2, 4], [2, 5],
]
LENGTH_BP = 200
NAME = "3x6x200_test"


def build() -> str:
    """Return the native ``.nadoc`` JSON for the regenerated fixture design."""
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(CELLS, LENGTH_BP, lattice=LatticeType.SQUARE, name=NAME)
        hb.auto_scaffold(seamless=True)
        hb.full_autostaple(scaffold_name="M13mp18")
        hb.apply_loop_skip_deformations()
        hb.assign_scaffold_sequence("M13mp18")
        hb.assign_staple_sequences()
        return design_state.get_or_404().to_json()


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("3x6x200_test.nadoc")
    out.write_text(build())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
