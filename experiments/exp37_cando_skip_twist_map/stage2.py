"""exp37 stage-2 — FINE local map around the stage-1 optimum, launched only if stage-1's best
verified config still misses |twist| < 1°.

Stage-1's uniform grid steps ~5°/skip, too coarse to land inside ±1°.  The fix is FRACTIONAL
density: hold most helices at the crossing count and bump a chosen subset by one skip, which moves
twist in ~0.3° steps.  This module sweeps that fractional line finely: starting from the stage-1
winner counts, it adds skips one-at-a-time to the HIGHEST twist-authority helices (and removes from
the lowest) to generate ~19 configs spanning ±9 total skips around the winner, solves them all IN
PARALLEL with the FINE solver, and keeps the |twist|<1° config with the lowest deviation.

Writes results/stage2.csv and, if it improves on the incumbent, rewrites results/optimized_marks.json.
Run:  OMP_NUM_THREADS=1 ... PYTHONPATH=. uv run python experiments/exp37_cando_skip_twist_map/stage2.py
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


def read_axes_slopes():
    path = os.path.join(RES, "axes.csv")
    by_h: dict = {}
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            if r.get("error") or not r.get("twist_deg"):
                continue
            by_h.setdefault(r["helix"], []).append((int(r["count"]), float(r["twist_deg"])))
    slope = {}
    for hid, v in by_h.items():
        xs = [c for c, _ in v]
        ys = [t for _, t in v]
        n = len(xs)
        mx = sum(xs) / n
        den = sum((x - mx) ** 2 for x in xs)
        my = sum(ys) / n
        slope[hid] = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den) if den else 0.0
    return slope


def main():
    meta = json.load(open(os.path.join(RES, "metadata.json")))
    d = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())
    forbidden, _ = _forbidden_bps(d)
    hb = {h.id: h for h in d.helices}
    free = {h.id: free_interior_candidates(d, hb[h.id], forbidden[h.id]) for h in d.helices}
    CAP = {hid: min(40, len(free[hid])) for hid in free}

    incumbent = json.load(open(os.path.join(RES, "optimized_marks.json")))
    start = dict(incumbent["counts"])
    slope = read_axes_slopes()
    order = sorted(slope, key=lambda h: slope[h])          # most twist-authority (most negative) first

    # Build the fractional-density bracket: start, then ±k skips placed on the top-|k| authority
    # helices (add when reducing twist / remove when raising it), for k = 1..9 both directions.
    cands = {"stage1_winner": dict(start)}
    for k in range(1, 10):
        cadd = dict(start)
        for j in range(k):
            hid = order[j % len(order)]
            cadd[hid] = min(CAP[hid], cadd[hid] + 1)
        cands[f"+{k}"] = cadd
        crem = dict(start)
        for j in range(k):
            hid = order[-1 - (j % len(order))]
            crem[hid] = max(0, crem[hid] - 1)
        cands[f"-{k}"] = crem

    names = list(cands)
    args = [(cands[n], free) for n in names]
    with Pool(min(N_WORKERS, len(args)), initializer=_init) as pool:
        results = pool.map(_solve, args)

    hdr = ["candidate", "total_skips", "twist_deg", "bend_deg", "rmsd_nm", "dev_max_nm", "solve_s"]
    with open(os.path.join(RES, "stage2.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=hdr)
        w.writeheader()
        for name, res in zip(names, results):
            w.writerow({"candidate": name, "total_skips": res["total_skips"],
                        **{k: res[k] for k in ("twist_deg", "bend_deg", "rmsd_nm",
                                               "dev_max_nm", "solve_s")}})
            print(f"  {name:14s} twist={res['twist_deg']:8} rmsd={res['rmsd_nm']} "
                  f"skips={res['total_skips']}")

    def key(nr):
        _, res = nr
        t, rm = abs(float(res["twist_deg"])), float(res["rmsd_nm"])
        return (0 if t < 1.0 else 1, rm if t < 1.0 else t)
    win_name, win = min(zip(names, results), key=key)

    inc_twist = abs(float(incumbent["twist_deg"]))
    if abs(float(win["twist_deg"])) < inc_twist:
        counts = cands[win_name]
        marks = {hid: {bp: -1 for bp in even_place(free[hid], counts[hid])} for hid in counts}
        marks = {k: v for k, v in marks.items() if v}
        json.dump({"candidate": f"stage2:{win_name}", "twist_deg": win["twist_deg"],
                   "rmsd_nm": win["rmsd_nm"], "bend_deg": win["bend_deg"],
                   "total_skips": win["total_skips"], "counts": counts,
                   "marks": {hid: {str(bp): dl for bp, dl in v.items()} for hid, v in marks.items()}},
                  open(os.path.join(RES, "optimized_marks.json"), "w"), indent=2)
        print(f"STAGE2 IMPROVED → {win_name}: twist {win['twist_deg']}° rmsd {win['rmsd_nm']}")
    else:
        print(f"STAGE2 no improvement (incumbent twist {incumbent['twist_deg']}° kept)")


if __name__ == "__main__":
    main()
