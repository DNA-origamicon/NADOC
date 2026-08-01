#!/usr/bin/env python3
"""Screen a design (or a whole directory of them) for PERMANENT topological defects.

Two are measured, both of which relaxation can never undo because every chain end is
covalently pinned into the origami network:

1. **Catenation.**  A reciprocal crossover pair carrying inserted extra bases can be
   built with its two backbones wound around one another (Gauss linking number != 0).
2. **Ring piercing.**  A covalent bond can be built straight through a sugar or base
   ring.  Minimisation cannot pull it out; it only stretches the impaled bond (measured
   1.60 -> 3.08 A on 2hb_2xT job c8c4a87e2033, still 2.98 A at the end of the run).

They are independent and complementary — the catenation measure walks the backbone
through C4'->C3', so a threaded sugar ring is off-curve and invisible to it — and
base-pairing health checks see neither.  Hence this screen.

This is the cheap, build-only gate to run BEFORE spending any GPU time:

    uv run python scripts/check_catenation.py workspace/2hb_1xT.nadoc
    uv run python scripts/check_catenation.py workspace/*.nadoc --quiet
    uv run python scripts/check_catenation.py workspace/6hbx100_2xT.nadoc --json out.json

Exit status is 1 if any design carries either defect, so it can gate a script.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _screen(path: Path, *, fast_bridges: bool | None = None) -> dict:
    from backend.core.atomistic import build_atomistic_model
    from backend.core.junction_topology import catenation_report
    from backend.core.models import Design

    design = Design.model_validate_json(path.read_text())
    t0 = time.time()
    kwargs = {} if fast_bridges is None else {"fast_bridges": fast_bridges}
    model = build_atomistic_model(design, **kwargs)
    build_s = time.time() - t0

    t0 = time.time()
    report = catenation_report(design, model=model)

    # Second, independent permanent defect measured off the SAME build: a covalent bond
    # threaded through a nucleotide ring.  The two are complementary — on 2hb_2xT the raw
    # build is catenated and unpierced, and the repaired build was the reverse.
    from backend.core.ring_piercing import piercing_report
    pierce = piercing_report(design, model=model)
    report["n_ring_pierced"] = pierce["n_pierced"]
    report["ring_pierced"] = pierce["pierced"]
    report["ok"] = bool(report["ok"] and pierce["ok"])
    report_s = time.time() - t0

    report["design"] = path.name
    report["build_seconds"] = round(build_s, 2)
    report["report_seconds"] = round(report_s, 2)
    report["n_atoms"] = len(model.atoms)
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("designs", nargs="+", type=Path, help=".nadoc files to screen")
    ap.add_argument("--json", type=Path, default=None, help="write the full reports here")
    ap.add_argument("--quiet", action="store_true", help="one line per design")
    ap.add_argument("--fast-bridges", dest="fast_bridges", action="store_true",
                    default=None,
                    help="build via the display path (skips the L-BFGS-B bridge solve) — "
                         "use to isolate whether the minimiser is what catenates")
    args = ap.parse_args(argv)

    paths: list[Path] = []
    for p in args.designs:
        if p.is_dir():
            paths.extend(sorted(p.glob("*.nadoc")))
        else:
            paths.append(p)

    reports = []
    worst = 0
    for p in paths:
        if not p.exists():
            print(f"{p.name:28s} MISSING", file=sys.stderr)
            continue
        try:
            rep = _screen(p, fast_bridges=args.fast_bridges)
        except Exception as exc:  # noqa: BLE001 — a screen must never abort the sweep
            print(f"{p.name:28s} ERROR  {type(exc).__name__}: {exc}", file=sys.stderr)
            continue
        reports.append(rep)
        worst = max(worst, rep["n_catenated"])

        flag = "OK " if rep["ok"] else "BAD"
        print(f"{flag} {p.name:28s} catenated={rep['n_catenated']:3d}/"
              f"{rep['n_pairs_tested']:<3d} pierced={rep['n_ring_pierced']:3d} "
              f"reciprocal={rep['n_reciprocal_pairs']:3d} "
              f"ambiguous={rep['n_closure_ambiguous']:2d} "
              f"({rep['n_atoms']} atoms, build {rep['build_seconds']}s)")
        if not args.quiet:
            for c in rep["catenated"]:
                print(f"      Lk={c['lk_int']:+d} {c['helices'][0]}/{c['helices'][1]} "
                      f"bp{c['bp'][0]}-{c['bp'][1]} inserts={c['n_inserts']} "
                      f"gap={c['min_backbone_dist_nm']:.3f} nm "
                      f"{'reciprocal' if c['reciprocal'] else 'NON-RECIPROCAL'}")
            for h in rep["ring_pierced"]:
                print(f"      PIERCED {h['bond']} through {h['ring']} {h['ring_kind']} "
                      f"(bond {h['bond_len_nm'] * 10:.2f} A)")

    if args.json:
        args.json.write_text(json.dumps(reports, indent=2))
        print(f"\nwrote {args.json}")

    n_bad = sum(1 for r in reports if not r["ok"])
    n_cat = sum(1 for r in reports if r["n_catenated"])
    n_pierce = sum(1 for r in reports if r["n_ring_pierced"])
    print(f"\n{len(reports)} design(s) screened, {n_bad} defective "
          f"({n_cat} catenated, {n_pierce} with a threaded ring)")
    return 1 if n_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
