#!/usr/bin/env python3
"""Test the MD-derived bow-sign rule against the known catenation ground truth.

The builder bows an insert along ``cross(halfA -> halfB, avg_axis)``.  ``half_a`` /
``half_b`` are just the order the Crossover record happens to store, so for a reciprocal
pair the two inserts land on the SAME physical side whenever both records happen to put
half_a on the same helix — a frustrated, mutually overlapping pose.  Referencing the bow
to the CHEMICAL hop direction instead (3' exit -> 5' entry, which by definition runs
opposite ways on the two crossovers of a reciprocal pair) makes the two sides alternate
automatically.

Prediction: the pairs that build CATENATED are exactly the ones the current rule seeds
same-side.  This script builds each design with the catenation repair disabled and
compares.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


class _NoRepair:
    """Disable the catenation repair ladder so the raw build is measured."""

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


def _side(xo, lo_helix):
    """+1 if the builder bows this crossover's insert along +e_perp, else -1."""
    return 1 if xo.half_a.helix_id == lo_helix else -1


def _hop_side(xo, lo_helix, design):
    """The same, but referenced to the chemical 3'->5' hop (src -> dst)."""
    ends = set()
    for s in design.strands:
        for d in s.domains:
            ends.add((d.helix_id, d.end_bp, d.direction.value))
    ka = (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value)
    src_helix = xo.half_a.helix_id if ka in ends else xo.half_b.helix_id
    return 1 if src_helix == lo_helix else -1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("designs", nargs="+", type=Path)
    args = ap.parse_args(argv)

    from backend.core.atomistic import build_atomistic_model
    from backend.core.junction_topology import (catenation_report,
                                                crossover_connectors,
                                                reciprocal_pairs)
    from backend.core.models import Design

    for path in args.designs:
        design = Design.model_validate_json(path.read_text())
        xo_by_id = {x.id: x for x in design.crossovers}
        conns = crossover_connectors(design)
        pairs = reciprocal_pairs(conns)
        with _NoRepair():
            model = build_atomistic_model(design)
        rep = catenation_report(design, model=model)

        cat_sets = {frozenset(e["crossover_ids"]) for e in rep["catenated"]}
        n_same = n_cat = n_hit = 0
        rows = []
        for i, j in pairs:
            ca, cb = conns[i], conns[j]
            ids = [ca.crossover_id, cb.crossover_id]
            if any(k not in xo_by_id for k in ids):
                continue
            if not (ca.n_inserts and cb.n_inserts):
                continue                      # no inserts -> cannot catenate
            a, b = xo_by_id[ids[0]], xo_by_id[ids[1]]
            lo = min(a.half_a.helix_id, a.half_b.helix_id)
            same = _side(a, lo) == _side(b, lo)
            hop_same = _hop_side(a, lo, design) == _hop_side(b, lo, design)
            cat = frozenset(ids) in cat_sets
            n_same += same
            n_cat += cat
            n_hit += (same == cat)
            rows.append((ids[0][:8], ids[1][:8], same, hop_same, "", cat))

        n = len(rows)
        print(f"\n{path.name}: {n} reciprocal pairs with inserts   "
              f"(report: {rep['n_catenated']} catenated of "
              f"{rep['n_reciprocal_pairs']} reciprocal)")
        print(f"  current rule seeds SAME side: {n_same}/{n}   "
              f"catenated: {n_cat}/{n}   agreement: {n_hit}/{n}")
        print(f"  hop-referenced rule seeds same side: "
              f"{sum(r[3] for r in rows)}/{n} (0 expected)")
        for r in rows[:40]:
            print(f"    {r[0]} {r[1]}  same_side={int(r[2])} hop_same={int(r[3])} "
                  f"lk={r[4]}  catenated={int(r[5])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
