#!/usr/bin/env python3
"""Does a HOP-REFERENCED bow direction remove the catenation?

The builder bows an insert along ``cross(half_a -> half_b, avg_axis)``.  ``half_a`` is
just the order the Crossover record happens to store its halves in, so the bow side is
arbitrary per crossover — and it turns out to seed BOTH inserts of every reciprocal pair
on the same physical side.  The 200 ns 2hb_1xT ensemble puts them on OPPOSITE sides.

Referencing the bow to the chemical hop (3' exit -> 5' entry) makes the sides alternate
automatically, because the hop runs opposite ways on the two crossovers of a reciprocal
pair.  Since the builder derives the bow from ``half_a -> half_b``, that change is
*exactly* equivalent to swapping the two halves on every crossover whose ``half_a`` is
not the 3'-exit — which can be done on an in-memory copy of the design, with no source
edit at all.  This script does that and re-measures catenation.

NOTE this is a MEASUREMENT, not a proposed implementation: swapping half_a/half_b in
stored records is explicitly a known-bad move (memory/feedback_crossover_no_reasoning).
The real change, if the user wants it, is to compute the bow from the hop inside
``_build_extra_base_atoms``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class _NoRepair:
    def __enter__(self):
        import backend.core.atomistic as _a
        self._mod = _a
        self._orig = _a._repair_catenated_pairs
        _a._repair_catenated_pairs = lambda *a, **k: {
            "n_pairs": 0, "n_repaired": 0, "n_unrepaired": 0, "repairs": []}
        return self

    def __exit__(self, *exc):
        self._mod._repair_catenated_pairs = self._orig
        return False


def domain_ends(design):
    out = set()
    for s in design.strands:
        for d in s.domains:
            out.add((d.helix_id, d.end_bp, d.direction.value))
    return out


def hop_orient(design, half_a: str = "dst"):
    """Return a copy whose every extra-base crossover has ``half_a`` = src or dst.

    The builder bows along ``cross(half_a -> half_b, avg_axis)``, so

      half_a = src  ->  bow along +cross(hop, axis)
      half_a = dst  ->  bow along -cross(hop, axis)   <-- the side the 200 ns run measures

    Either choice makes the bow ALTERNATE between the two crossovers of a reciprocal pair
    (their hops run opposite ways); only ``half_a = dst`` also puts each insert on the
    measured side.
    """
    ends = domain_ends(design)
    new = design.model_copy(deep=True)
    n_swapped = 0
    for xo in new.crossovers:
        if not xo.extra_bases:
            continue
        ka = (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value)
        a_is_src = ka in ends
        want_src = (half_a == "src")
        if a_is_src == want_src:
            continue
        xo.half_a, xo.half_b = xo.half_b, xo.half_a
        n_swapped += 1
    return new, n_swapped


def screen(design, label):
    from backend.core.atomistic import build_atomistic_model
    from backend.core.junction_topology import (catenation_report,
                                                crossover_connectors,
                                                reciprocal_pairs)
    with _NoRepair():
        model = build_atomistic_model(design)
    rep = catenation_report(design, model=model)
    conns = crossover_connectors(design)
    pairs = [(i, j) for i, j in reciprocal_pairs(conns)
             if conns[i].n_inserts and conns[j].n_inserts]
    print(f"   {label:<22s} catenated {rep['n_catenated']:>3d} / "
          f"{len(pairs):<3d} reciprocal insert pairs   "
          f"(ambiguous closures: {rep['n_closure_ambiguous']})")
    return rep, model


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="+", type=Path)
    args = ap.parse_args(argv)
    from backend.core.models import Design

    for path in args.designs:
        design = Design.model_validate_json(path.read_text())
        n_xb = sum(1 for x in design.crossovers if x.extra_bases)
        print(f"\n{path.name}   ({n_xb} extra-base crossovers)")
        screen(design, "as built today")
        for which, label in (("dst", "bow = -cross(hop,axis)  [MD side]"),
                             ("src", "bow = +cross(hop,axis)  [far side]")):
            flipped, n = hop_orient(design, half_a=which)
            screen(flipped, label)
            print(f"      ({n} of {n_xb} crossovers re-oriented)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
