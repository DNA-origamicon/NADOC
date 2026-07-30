#!/usr/bin/env python3
"""Where does each candidate build put the insert, compared with the 200 ns ensemble?

Reports the insert C1' in the HOP-REFERENCED chord frame (t, bow, ax) for:
  arc            pure Bezier pose (fast_bridges: joint solve skipped)
  built          today's full build (joint solve + catenation repair)
  arc-hop        pure Bezier pose with the bow referenced to the chemical hop
  built-hop      full build with the hop-referenced bow
and prints the MD target next to them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hop_bow_experiment import hop_orient  # noqa: E402
from xb_map import build_package_map, load_design  # noqa: E402
from xb_observables import JunctionProbe, ModelSource  # noqa: E402


def hop_sign_map(design):
    ends = set()
    for s in design.strands:
        for d in s.domains:
            ends.add((d.helix_id, d.end_bp, d.direction.value))
    out = {}
    for xo in design.crossovers:
        ka = (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value)
        src_helix = xo.half_a.helix_id if ka in ends else xo.half_b.helix_id
        out[xo.id] = 1 if src_helix == xo.half_a.helix_id else -1
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--job", required=True, type=Path)
    ap.add_argument("--dump", type=Path, default=None)
    ap.add_argument("--burn", type=int, default=400)
    args = ap.parse_args(argv)

    from backend.core.atomistic import build_atomistic_model

    design = load_design(args.job / "design.json")
    stem = json.loads((args.job / "job.json").read_text())["name_stem"]
    pdb = args.job / "package" / f"{stem}_namd_solvated" / f"{stem}.pdb"
    pm = build_package_map(design, pdb)

    flipped, n_sw = hop_orient(design)
    print(f"{stem}: {n_sw} extra-base crossover(s) re-referenced to the hop\n")

    variants = [("arc", design, {"fast_bridges": True}),
                ("built", design, {}),
                ("arc-hop", flipped, {"fast_bridges": True}),
                ("built-hop", flipped, {})]

    rows = {}
    for tag, dsg, kw in variants:
        half_a = {xo.id: xo.half_a.helix_id for xo in dsg.crossovers}
        sg = hop_sign_map(dsg)
        model = build_atomistic_model(dsg, **kw)
        s = ModelSource(model)
        for ins in pm.inserts:
            pr = JunctionProbe(pm, ins, half_a[ins.crossover_id])
            m = pr.measure(s)
            k = sg[ins.crossover_id]
            rows.setdefault(ins.crossover_id, {})[tag] = (
                m["t_c1"], k * m["bow_c1"], k * m["ax_c1"], m["L"])

    md = {}
    if args.dump:
        d = json.loads(args.dump.read_text())
        sg0 = hop_sign_map(design)
        for ins in d["inserts"]:
            s = ins["samples"][args.burn:]
            k = sg0[ins["crossover_id"]]
            md[ins["crossover_id"]] = (
                np.mean([q["t_c1"] for q in s]), np.std([q["t_c1"] for q in s]),
                k * np.mean([q["bow_c1"] for q in s]), np.std([q["bow_c1"] for q in s]),
                k * np.mean([q["ax_c1"] for q in s]), np.std([q["ax_c1"] for q in s]),
                np.mean([q["L"] for q in s]))

    for xid, per in rows.items():
        print(f"── crossover {xid[:8]}")
        print(f"   {'variant':<12s} {'t':>8s} {'bow':>8s} {'ax':>8s} {'L':>7s}"
              f"   {'|d| to MD (A)':>14s}")
        tgt = md.get(xid)
        for tag, (t, b, a, L) in per.items():
            extra = ""
            if tgt:
                dv = np.array([t - tgt[0], b - tgt[2], a - tgt[4]]) * tgt[6]
                extra = f"{np.linalg.norm(dv):>14.2f}"
            print(f"   {tag:<12s} {t:+8.3f} {b:+8.3f} {a:+8.3f} {L:7.2f}   {extra}")
        if tgt:
            print(f"   {'MD 180 ns':<12s} {tgt[0]:+8.3f} {tgt[2]:+8.3f} {tgt[4]:+8.3f} "
                  f"{tgt[6]:7.2f}   (sd {tgt[1]:.3f} / {tgt[3]:.3f} / {tgt[5]:.3f})")
            print(f"   {'':<12s} thermal spread of the MD ensemble itself: "
                  f"{np.linalg.norm(np.array([tgt[1],tgt[3],tgt[5]])*tgt[6]):.2f} A")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
