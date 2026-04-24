#!/usr/bin/env python3
"""
Empirically probe what row/col direction change fixes SQ crossover distances.

Tests combinations of:
  - Row direction: current (nr = max_row - cadnano_row) vs flipped (nr = cadnano_row - min_row)
  - Column direction: current (nc = col - min_col) vs flipped (nc = max_col - col)

When flipping, BOTH axis position AND grid_pos are updated together, so the
crossover table lookup reflects the same change as a code-level import fix would.

Usage:
    uv run scripts/probe_sq_axis.py Examples/cadnano/2x4hb_sq_test.json
"""
from __future__ import annotations

import copy
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.constants import (
    SQ_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_PERIOD,
    SQ_SCAFFOLD_CROSSOVER_OFFSETS,
    SQUARE_COL_PITCH,
    SQUARE_ROW_PITCH,
)
from backend.core.geometry import nucleotide_positions
from backend.core.models import Design, Direction, LatticeType, Vec3


def _parity_fwd(row: int, col: int) -> bool:
    return (row + col) % 2 == 0


def _build_bead_map(helix):
    return {
        (nuc.bp_index, nuc.direction.value): nuc.position
        for nuc in nucleotide_positions(helix)
    }


def _flip_design(design: Design, flip_row: bool, flip_col: bool) -> Design:
    """
    Rebuild grid_pos and axis XY as if the import used a different row/col direction.

    flip_row: reindex nr as (max_nr - nr) instead of nr
    flip_col: reindex nc as (max_nc - nc) instead of nc
    """
    d = copy.deepcopy(design)
    helices = [h for h in d.helices if h.grid_pos is not None]
    if not helices:
        return d

    max_nr = max(h.grid_pos[0] for h in helices)
    max_nc = max(h.grid_pos[1] for h in helices)

    for h in helices:
        old_nr, old_nc = h.grid_pos
        new_nr = (max_nr - old_nr) if flip_row else old_nr
        new_nc = (max_nc - old_nc) if flip_col else old_nc

        new_x = new_nc * SQUARE_COL_PITCH
        new_y = new_nr * SQUARE_ROW_PITCH
        h.grid_pos = (new_nr, new_nc)
        h.axis_start = Vec3(x=new_x, y=new_y, z=h.axis_start.z)
        h.axis_end   = Vec3(x=new_x, y=new_y, z=h.axis_end.z)

    return d


def _measure(design: Design) -> tuple[int, int, float, float, dict]:
    cell_to_helix = {
        (h.grid_pos[0], h.grid_pos[1]): h
        for h in design.helices if h.grid_pos is not None
    }
    bead = {h.id: _build_bead_map(h) for h in design.helices if h.grid_pos is not None}

    dists = []
    xtype_map = {(-1,0):"pN",(0,+1):"pE",(+1,0):"pS",(0,-1):"pW"}
    per_xtype: dict[str, list[float]] = defaultdict(list)

    for h_a in design.helices:
        if h_a.grid_pos is None:
            continue
        row_a, col_a = h_a.grid_pos
        fwd_a = _parity_fwd(row_a, col_a)
        pos_a = bead[h_a.id]

        for bp in range(h_a.bp_start, h_a.bp_start + h_a.length_bp):
            off = bp % SQ_CROSSOVER_PERIOD

            for table, is_scaffold in [(SQ_CROSSOVER_OFFSETS, False),
                                       (SQ_SCAFFOLD_CROSSOVER_OFFSETS, True)]:
                delta = table.get((fwd_a, off))
                if delta is None:
                    continue
                nb = (row_a + delta[0], col_a + delta[1])
                h_b = cell_to_helix.get(nb)
                if h_b is None or h_a.id >= h_b.id:
                    continue

                if is_scaffold:
                    dir_a = Direction.FORWARD if fwd_a else Direction.REVERSE
                    dir_b = Direction.REVERSE if fwd_a else Direction.FORWARD
                else:
                    dir_a = Direction.REVERSE if fwd_a else Direction.FORWARD
                    dir_b = Direction.FORWARD if fwd_a else Direction.REVERSE

                pa = pos_a.get((bp, dir_a.value))
                pb = bead[h_b.id].get((bp, dir_b.value))
                if pa is None or pb is None:
                    continue
                d = float(np.linalg.norm(np.array(pa) - np.array(pb)))
                dists.append(d)
                xt = xtype_map.get(delta, str(delta))
                per_xtype[xt].append(d)

    if not dists:
        return 0, 0, 0.0, 0.0, {}
    arr = np.array(dists)
    xtype_fails = {xt: sum(1 for v in vs if v > 1.2) for xt, vs in per_xtype.items()}
    return len(arr), int((arr > 1.2).sum()), float(arr.mean()), float(arr.max()), xtype_fails


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: probe_sq_axis.py <design.json>")

    path = Path(sys.argv[1])
    raw = path.read_text()

    if path.suffix == ".json":
        from backend.core.cadnano import import_cadnano
        design, _ = import_cadnano(json.loads(raw))
    elif path.suffix == ".sc":
        from backend.core.scadnano import import_scadnano
        design, _ = import_scadnano(json.loads(raw))
    else:
        design = Design.from_json(raw)

    print(f"Design: {path.name}  ({len(design.helices)} helices, lattice={design.lattice_type})\n")
    print(f"{'variant':<30} {'fail':>8} {'mean':>8} {'max':>8}  dir-fails")
    print("-" * 80)

    for flip_row, flip_col in [(False, False), (True, False), (False, True), (True, True)]:
        label = ("flip_row " if flip_row else "row      ") + ("flip_col" if flip_col else "col     ")
        d = _flip_design(design, flip_row, flip_col)
        n, nf, mean, mx, xf = _measure(d)
        mark = " ✓" if nf == 0 else ""
        xstr = "  ".join(f"{k}:{v}" for k, v in sorted(xf.items()) if v > 0)
        print(f"  {label:<28} {nf:>5}/{n:<5} {mean:>8.4f} {mx:>8.4f}  {xstr}{mark}")

    print()


if __name__ == "__main__":
    main()
