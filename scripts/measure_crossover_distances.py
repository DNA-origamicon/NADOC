#!/usr/bin/env python3
"""
Measure backbone-bead distances at valid crossover sites.

For every pair of lattice-adjacent helices, iterates the staple and scaffold
offset tables to find all valid crossover positions, then measures the 3D
distance between the two backbone beads that would be connected.

Non-neighbor helices are excluded by construction: forced crossovers between
distant helices do not appear in the offset tables.

Crossover type labels (xtype)
──────────────────────────────
  pN  neighbor at (row−1, col)
  pE  neighbor at (row,   col+1)
  pS  neighbor at (row+1, col)
  pW  neighbor at (row,   col−1)

Applies to both HC (3 active directions per helix) and SQ (4 directions).
The direction is always reported from the perspective of the lower-id helix.

File format detection
─────────────────────
  .nadoc  — native NADOC JSON
  .json   — caDNAno v2
  .sc     — scadnano

Usage
-----
    uv run scripts/measure_crossover_distances.py design.nadoc
    uv run scripts/measure_crossover_distances.py design.json     # cadnano
    uv run scripts/measure_crossover_distances.py design.sc       # scadnano
    uv run scripts/measure_crossover_distances.py design.nadoc --staple-only
    uv run scripts/measure_crossover_distances.py design.nadoc --scaffold-only
    uv run scripts/measure_crossover_distances.py design.nadoc --verbose
    uv run scripts/measure_crossover_distances.py design.nadoc --hist
    uv run scripts/measure_crossover_distances.py design.nadoc --threshold 1.2
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.core.constants import (
    HC_CROSSOVER_OFFSETS,
    HC_CROSSOVER_PERIOD,
    HC_SCAFFOLD_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_OFFSETS,
    SQ_CROSSOVER_PERIOD,
    SQ_SCAFFOLD_CROSSOVER_OFFSETS,
)
from backend.core.geometry import nucleotide_positions
from backend.core.models import Design, Direction, LatticeType

# Maps (drow, dcol) → crossover-type label.
_DELTA_TO_XTYPE: dict[tuple[int, int], str] = {
    (-1,  0): "pN",
    ( 0, +1): "pE",
    (+1,  0): "pS",
    ( 0, -1): "pW",
}


def _parity_fwd(row: int, col: int) -> bool:
    return (row + col) % 2 == 0


def _short_id(helix_id: str) -> str:
    if helix_id.startswith("h_XY_"):
        return helix_id
    return helix_id[-8:]


def _build_bead_map(helix) -> dict[tuple[int, str], np.ndarray]:
    """Return {(global_bp_index, direction_value): backbone_pos} for one helix."""
    return {
        (nuc.bp_index, nuc.direction.value): nuc.position
        for nuc in nucleotide_positions(helix)
    }


def _load_design(path: Path) -> Design:
    suffix = path.suffix.lower()
    raw = path.read_text(encoding="utf-8")
    if suffix == ".nadoc":
        return Design.from_json(raw)
    if suffix == ".json":
        from backend.core.cadnano import import_cadnano
        design, warnings = import_cadnano(json.loads(raw))
        if warnings:
            print(f"  import warnings: {warnings[:3]}")
        return design
    if suffix == ".sc":
        from backend.core.scadnano import import_scadnano
        design, warnings = import_scadnano(json.loads(raw))
        if warnings:
            print(f"  import warnings: {warnings[:3]}")
        return design
    sys.exit(f"Unknown file extension {suffix!r} — expected .nadoc, .json, or .sc")


def _ascii_histogram(values: list[float], bins: int = 20, bar_width: int = 50) -> str:
    arr = np.array(values)
    counts, edges = np.histogram(arr, bins=bins)
    max_count = max(counts) or 1
    lines = []
    for i, count in enumerate(counts):
        bar = "█" * int(count / max_count * bar_width)
        lines.append(f"  {edges[i]:6.3f}–{edges[i+1]:6.3f} nm │ {bar:<{bar_width}} {count}")
    return "\n".join(lines)


def measure(
    design: Design,
    *,
    staple: bool = True,
    scaffold: bool = True,
    xtypes: set[str] | None = None,
    verbose: bool = False,
    hist: bool = False,
    threshold: float | None = None,
) -> None:
    """xtypes: if given, only measure crossovers whose direction label is in the set."""
    cell_to_helix = {
        (h.grid_pos[0], h.grid_pos[1]): h
        for h in design.helices
        if h.grid_pos is not None
    }
    if not cell_to_helix:
        print("No helices with grid_pos — cannot measure.")
        return

    lt = design.lattice_type
    period   = HC_CROSSOVER_PERIOD           if lt == LatticeType.HONEYCOMB else SQ_CROSSOVER_PERIOD
    stap_tbl = HC_CROSSOVER_OFFSETS          if lt == LatticeType.HONEYCOMB else SQ_CROSSOVER_OFFSETS
    scaf_tbl = HC_SCAFFOLD_CROSSOVER_OFFSETS if lt == LatticeType.HONEYCOMB else SQ_SCAFFOLD_CROSSOVER_OFFSETS

    bead: dict[str, dict[tuple[int, str], np.ndarray]] = {
        h.id: _build_bead_map(h)
        for h in design.helices
        if h.grid_pos is not None
    }

    # (id_a, id_b, xtype) → distances
    pair_dists: dict[tuple[str, str, str], list[float]] = defaultdict(list)
    # (xtype, kind) → distances  for per-direction summary
    dir_dists:  dict[tuple[str, str], list[float]] = defaultdict(list)
    stap_all: list[float] = []
    scaf_all: list[float] = []
    # verbose row: (dist, xtype, kind, id_a, id_b, bp)
    verbose_rows: list[tuple] = []

    for h_a in design.helices:
        if h_a.grid_pos is None:
            continue
        row_a, col_a = h_a.grid_pos
        fwd_a = _parity_fwd(row_a, col_a)
        pos_a = bead[h_a.id]

        for bp in range(h_a.bp_start, h_a.bp_start + h_a.length_bp):
            off = bp % period

            def _measure_site(table: dict, is_scaffold: bool) -> None:
                delta = table.get((fwd_a, off))
                if delta is None:
                    return
                nb = (row_a + delta[0], col_a + delta[1])
                h_b = cell_to_helix.get(nb)
                if h_b is None:
                    return
                if h_a.id >= h_b.id:
                    return
                if is_scaffold:
                    dir_a = Direction.FORWARD if fwd_a else Direction.REVERSE
                    dir_b = Direction.REVERSE if fwd_a else Direction.FORWARD
                else:
                    dir_a = Direction.REVERSE if fwd_a else Direction.FORWARD
                    dir_b = Direction.FORWARD if fwd_a else Direction.REVERSE

                p_a = pos_a.get((bp, dir_a.value))
                p_b = bead[h_b.id].get((bp, dir_b.value))
                if p_a is None or p_b is None:
                    return

                dist  = float(np.linalg.norm(p_b - p_a))
                xtype = _DELTA_TO_XTYPE.get(delta, f"p{delta}")
                if xtypes is not None and xtype not in xtypes:
                    return
                kind  = "scaffold" if is_scaffold else "staple"
                pair_dists[(h_a.id, h_b.id, xtype)].append(dist)
                dir_dists[(xtype, kind)].append(dist)
                (scaf_all if is_scaffold else stap_all).append(dist)
                if verbose or (threshold is not None and dist > threshold):
                    verbose_rows.append((dist, xtype, kind, h_a.id, h_b.id, bp))

            if staple:
                _measure_site(stap_tbl, False)
            if scaffold:
                _measure_site(scaf_tbl, True)

    all_dists = stap_all + scaf_all
    if not all_dists:
        print("No crossover sites found.")
        return

    # ── Verbose / threshold listing ───────────────────────────────────────────
    if verbose_rows:
        print(f"\n{'dist':>9}  {'xtype':5}  {'kind':8}  {'bp':>6}  {'Helix A':<20} {'Helix B'}")
        print("─" * 78)
        for dist, xtype, kind, id_a, id_b, bp in sorted(verbose_rows, key=lambda r: -r[0]):
            flag = " ←" if (threshold and dist > threshold) else ""
            print(
                f"{dist:>9.4f}  {xtype:<5}  {kind:<8}  {bp:>6d}  "
                f"{_short_id(id_a):<20} {_short_id(id_b)}{flag}"
            )

    # ── Per-pair summary ──────────────────────────────────────────────────────
    print(f"\n{'Helix A':<22} {'Helix B':<22} {'xtype':5} {'N':>5} {'mean':>8} {'std':>8} {'min':>8} {'max':>8}  nm")
    print("─" * 95)
    for (id_a, id_b, xtype), dists in sorted(pair_dists.items()):
        a = np.array(dists)
        print(
            f"{_short_id(id_a):<22} {_short_id(id_b):<22} {xtype:<5}"
            f" {len(a):>5} {a.mean():>8.4f} {a.std():>8.4f}"
            f" {a.min():>8.4f} {a.max():>8.4f}"
        )

    # ── Per-direction summary ─────────────────────────────────────────────────
    print(f"\n{'xtype':5} {'kind':8}  {'N':>6}  {'mean':>8}  {'std':>8}  {'min':>8}  {'max':>8}  nm")
    print("─" * 68)
    for (xtype, kind) in sorted(dir_dists.keys()):
        a = np.array(dir_dists[(xtype, kind)])
        flag = ""
        if threshold is not None and a.max() > threshold:
            n_over = int((a > threshold).sum())
            flag = f"  ← {n_over} above {threshold} nm"
        print(
            f"{xtype:<5} {kind:<8}  {len(a):>6}  {a.mean():>8.4f}  {a.std():>8.4f}"
            f"  {a.min():>8.4f}  {a.max():>8.4f}{flag}"
        )

    # ── Global totals ─────────────────────────────────────────────────────────
    print()
    for label, vals in [("ALL   ", all_dists), ("STAPLE", stap_all), ("SCAFF ", scaf_all)]:
        if not vals:
            continue
        a = np.array(vals)
        line = (
            f"{label}  N={len(a):>5}  "
            f"mean={a.mean():.4f}  std={a.std():.4f}  "
            f"min={a.min():.4f}  max={a.max():.4f}  nm"
        )
        if threshold is not None:
            n_over = int((a > threshold).sum())
            line += f"   ({n_over} above {threshold} nm)"
        print(line)

    if hist:
        print(f"\nHistogram — all crossover backbone distances ({len(all_dists)} sites):")
        print(_ascii_histogram(all_dists))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("design", type=Path, help=".nadoc, .json (cadnano), or .sc (scadnano)")
    ap.add_argument("--staple-only",   action="store_true")
    ap.add_argument("--scaffold-only", action="store_true")
    ap.add_argument("--verbose", "-v", action="store_true", help="Print every individual site")
    ap.add_argument("--hist",          action="store_true", help="Print ASCII distance histogram")
    ap.add_argument(
        "--xtype", metavar="DIR", nargs="+",
        help="Only measure crossovers of these types (e.g. pN pS)",
    )
    ap.add_argument(
        "--threshold", type=float, metavar="NM",
        help="Flag sites with backbone distance > NM (lists them sorted worst-first)",
    )
    args = ap.parse_args()

    if not args.design.exists():
        sys.exit(f"Error: {args.design} not found")

    print(f"Loading {args.design} …")
    design = _load_design(args.design)
    n_grid = sum(1 for h in design.helices if h.grid_pos is not None)
    print(f"  {len(design.helices)} helices ({n_grid} with grid_pos)  lattice={design.lattice_type.value}")

    measure(
        design,
        staple=not args.scaffold_only,
        scaffold=not args.staple_only,
        xtypes=set(args.xtype) if args.xtype else None,
        verbose=args.verbose,
        hist=args.hist,
        threshold=args.threshold,
    )


if __name__ == "__main__":
    main()
