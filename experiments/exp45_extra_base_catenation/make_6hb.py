#!/usr/bin/env python3
"""Generate short 6-helix-bundle designs with crossover extra bases, for catenation MD.

The 2hb proxy has exactly ONE reciprocal crossover pair, so it can only ever answer
"does the repair hold for a single junction".  A 6hb at 21 or 42 bp is the smallest
structure that puts MANY reciprocal pairs in a real honeycomb neighbourhood — each helix
has up to three neighbours, so a junction's repair can be disturbed by the crossovers
around it — while staying small enough to relax locally in minutes.

    python experiments/exp45_extra_base_catenation/make_6hb.py
    python experiments/exp45_extra_base_catenation/make_6hb.py --lengths 42 --extra TT

Writes ``workspace/<name>.nadoc`` and prints a catenation screen for each.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.api.headless_build import (
    auto_break, auto_crossover, auto_scaffold, create_bundle, full_sequence,
    scratch_session, set_crossover_extra_bases_bulk,
)
from backend.core.atomistic import build_atomistic_model
from backend.core.junction_topology import catenation_report, crossover_connectors, reciprocal_pairs
from backend.core.md_sequence_guard import scaffold_sequence_problems
from backend.core.models import LatticeType

WORKSPACE = ROOT / "workspace"

# Honeycomb 6HB — the same cell set the atomistic tests use.
CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]


def build_one(length_bp: int, extra: str, name: str):
    """Route + staple a 6hb, then put ``extra`` at every staple crossover."""
    with scratch_session(LatticeType.HONEYCOMB):
        create_bundle(CELLS_6HB, length_bp, lattice=LatticeType.HONEYCOMB,
                      name=name, plane="XY")
        # A raw bundle carries ONE scaffold strand per helix; auto_scaffold routes them
        # into a single scaffold, which full_sequence needs in order to complement every
        # staple. Without it the SCAFFOLD ends up unsequenced and the MD gate refuses the
        # build ("every unassigned base is silently built as thymine").
        auto_scaffold()
        auto_crossover()
        auto_break()
        full_sequence(scaffold_name="M13mp18")
        if extra:
            set_crossover_extra_bases_bulk(extra, crossover_filter="staple")
        design = design_snapshot()
    return design


def design_snapshot():
    from backend.api import state as design_state
    d = design_state.get_or_404()
    return d.model_copy(deep=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lengths", nargs="+", type=int, default=[21, 42])
    ap.add_argument("--extra", nargs="+", default=["T", "TT"])
    ap.add_argument("--prefix", default="6hbS")
    ap.add_argument("--screen", action="store_true", default=True)
    args = ap.parse_args(argv)

    made = []
    for length_bp in args.lengths:
        for extra in args.extra:
            tag = f"{len(extra)}xT" if extra else "noT"
            name = f"{args.prefix}{length_bp}_{tag}"
            try:
                design = build_one(length_bp, extra, name)
            except Exception as exc:  # noqa: BLE001
                print(f"{name:18s} BUILD FAILED {type(exc).__name__}: {exc}")
                continue

            conns = crossover_connectors(design)
            pairs = reciprocal_pairs(conns)
            n_extra = sum(1 for c in (design.crossovers or []) if c.extra_bases)
            # Check the ACTUAL MD gate, not "some strand has a sequence" — staples can be
            # sequenced while the scaffold is not, which is exactly what silently produced
            # six unusable designs the first time round.
            gate_problems = scaffold_sequence_problems(design)

            out = WORKSPACE / f"{name}.nadoc"
            out.write_text(design.model_dump_json())

            line = (f"{name:18s} helices={len(design.helices)} strands={len(design.strands)} "
                    f"xovers={len(design.crossovers or [])} with_extra={n_extra} "
                    f"connectors={len(conns)} reciprocal={len(pairs)} "
                    f"seq_ok={not gate_problems}")
            if args.screen and pairs:
                rep = catenation_report(design, model=build_atomistic_model(design))
                line += f" CATENATED={rep['n_catenated']}"
            if gate_problems:
                line += f"  !! {gate_problems[0][:80]}"
            print(line)
            if not gate_problems:
                made.append(name)

    print(f"\nwrote {len(made)} design(s) to {WORKSPACE}")
    return 0 if made else 1


if __name__ == "__main__":
    raise SystemExit(main())
