"""exp37 stage-2 (spread) — a PHYSICAL sub-1° config: near-uniform fractional density.

The auto-optimizer's `analytic-1` hit twist~0 by piling 38 skips on the single highest-authority
helix — low deviation but bend 1.66° and physically fragile.  The map says the clean lever is
FRACTIONAL UNIFORM density: uniform 12/helix gives +3.3° and 13/helix gives −2.1°, so bumping a
SUBSET of helices 12→13 (chosen by twist authority) lands inside ±1° while every helix stays at
12–13 skips (bend ~0.4°).  This sweeps that subset size k = 0…18 (top-k authority helices bumped),
solves all in parallel with the FINE solver, and writes the |twist|<1° config with the lowest
bend+deviation to results/optimized_spread.json.

Run:  OMP_NUM_THREADS=1 ... PYTHONPATH=. uv run python experiments/exp37_cando_skip_twist_map/stage2_spread.py
"""
from __future__ import annotations

import csv
import json
import os
from multiprocessing import Pool

from backend.core.models import Design
from backend.core.cando_autorefine import _forbidden_bps, free_interior_candidates
from experiments.exp37_cando_skip_twist_map.sweep import DESIGN_PATH, even_place, measure, N_WORKERS

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
_G: dict = {}


def _init():
    _G["design"] = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())


def _solve(counts_and_free):
    counts, free = counts_and_free
    marks = {hid: {bp: -1 for bp in even_place(free[hid], counts[hid])} for hid in counts}
    marks = {k: v for k, v in marks.items() if v}
    m = measure(_G["design"], marks)
    return {"counts": counts, "total_skips": sum(len(v) for v in marks.values()), **m}


def authority_order():
    by_h: dict = {}
    with open(os.path.join(RES, "axes.csv"), newline="") as f:
        for r in csv.DictReader(f):
            if r.get("error") or not r.get("twist_deg"):
                continue
            by_h.setdefault(r["helix"], []).append((int(r["count"]), float(r["twist_deg"])))
    slope = {}
    for hid, v in by_h.items():
        xs = [c for c, _ in v]; ys = [t for _, t in v]; n = len(xs)
        mx = sum(xs) / n; my = sum(ys) / n
        den = sum((x - mx) ** 2 for x in xs)
        slope[hid] = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) if den else 0.0
    return sorted(slope, key=lambda h: slope[h]), slope   # most authority (most negative) first


def main():
    d = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())
    forbidden, _ = _forbidden_bps(d)
    hbx = {h.id: h for h in d.helices}
    free = {h.id: free_interior_candidates(d, hbx[h.id], forbidden[h.id]) for h in d.helices}
    order, slope = authority_order()

    # base all helices at 12; bump the top-k authority helices to 13 (k = 0..18).
    cands = {}
    for k in range(0, len(order) + 1):
        c = {hid: 12 for hid in free}
        for hid in order[:k]:
            c[hid] = 13
        cands[f"12base+{k}@13"] = c

    names = list(cands)
    args = [(cands[n], free) for n in names]
    with Pool(min(N_WORKERS, len(args)), initializer=_init) as pool:
        results = pool.map(_solve, args)

    hdr = ["candidate", "n_at_13", "total_skips", "twist_deg", "bend_deg", "rmsd_nm",
           "dev_max_nm", "solve_s"]
    rows = []
    with open(os.path.join(RES, "stage2_spread.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=hdr)
        w.writeheader()
        for name, res in zip(names, results):
            n13 = sum(1 for v in res["counts"].values() if v == 13)
            row = {"candidate": name, "n_at_13": n13, "total_skips": res["total_skips"],
                   **{k: res[k] for k in ("twist_deg", "bend_deg", "rmsd_nm", "dev_max_nm", "solve_s")}}
            w.writerow(row); rows.append((row, res))
            print(f"  {name:14s} n13={n13:2d} twist={res['twist_deg']:8} bend={res['bend_deg']} "
                  f"rmsd={res['rmsd_nm']}")

    # winner: |twist|<1°, then minimise bend + rmsd (physical + low deviation)
    def key(rr):
        row, _ = rr
        t = abs(float(row["twist_deg"]))
        return (0 if t < 1.0 else 1,
                (float(row["bend_deg"]) + float(row["rmsd_nm"])) if t < 1.0 else t)
    row, res = min(rows, key=key)
    counts = res["counts"]
    marks = {hid: {bp: -1 for bp in even_place(free[hid], counts[hid])} for hid in counts}
    marks = {k: v for k, v in marks.items() if v}
    json.dump({"candidate": f"spread:{row['candidate']}", "twist_deg": row["twist_deg"],
               "bend_deg": row["bend_deg"], "rmsd_nm": row["rmsd_nm"],
               "total_skips": res["total_skips"], "counts": counts,
               "marks": {hid: {str(bp): dl for bp, dl in v.items()} for hid, v in marks.items()}},
              open(os.path.join(RES, "optimized_spread.json"), "w"), indent=2)
    print(f"\nSPREAD WINNER {row['candidate']}: twist {row['twist_deg']}° bend {row['bend_deg']}° "
          f"rmsd {row['rmsd_nm']} skips {res['total_skips']}")


if __name__ == "__main__":
    main()
