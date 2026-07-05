"""exp37 analysis — summarise the skip-vs-twist landscape + propose a joint twist+deviation
optimum, then VERIFY a bracket of candidate configs with FRESH FINE solves (in parallel).

Reads results/uniform.csv + results/axes.csv (written by sweep.py), then:
  1. Renders results/SUMMARY.md: the uniform diagonal (twist/bend/dev vs count), its twist→0
     crossing, and the per-helix authority table (∂twist/∂count, ∂rmsd/∂count near best-guess).
  2. Builds a superposition model  twist(c) ≈ T0 + Σ a_h (c_h−base_h)  and picks per-helix counts
     that drive |twist|→0 by adding skips to the HIGHEST twist-authority helices first (fewest
     added skips ⇒ least deviation cost = the joint twist+deviation optimum).
  3. VERIFIES the analytic proposal + a small BRACKET of neighbours (±total-skip offsets, and a
     pure-uniform pick) with real FINE solves run IN PARALLEL, logs results/optimize.csv, writes
     the winner to results/optimized_marks.json.

Run AFTER sweep.py:  OMP_NUM_THREADS=1 ... PYTHONPATH=. uv run python .../analyze.py
"""
from __future__ import annotations

import csv
import json
import os
from multiprocessing import Pool

from backend.core.models import Design
from backend.core.cando_autorefine import _forbidden_bps, free_interior_candidates
from experiments.exp37_cando_skip_twist_map.sweep import (
    DESIGN_PATH, even_place, measure, N_WORKERS)

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")

_G: dict = {}


def _init():
    _G["design"] = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())


def _solve_counts(counts_and_free):
    """Worker: build even-placed marks for a per-helix count dict, one FINE solve → metrics."""
    counts, free = counts_and_free
    marks = {hid: {bp: -1 for bp in even_place(free[hid], counts[hid])} for hid in counts}
    marks = {k: v for k, v in marks.items() if v}
    m = measure(_G["design"], marks)
    return {"counts": counts, "total_skips": sum(len(v) for v in marks.values()), **m}


def read_csv(name):
    path = os.path.join(RES, name)
    if not os.path.isfile(path):
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if not r.get("error")]


def linfit(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def main():
    meta = json.load(open(os.path.join(RES, "metadata.json")))
    base_count = meta["base_count"]
    d = Design.from_json(open(DESIGN_PATH, encoding="utf-8").read())
    forbidden, _ = _forbidden_bps(d)
    hb = {h.id: h for h in d.helices}
    free = {h.id: free_interior_candidates(d, hb[h.id], forbidden[h.id]) for h in d.helices}

    uni = sorted(read_csv("uniform.csv"), key=lambda r: int(r["count"]))
    axes = read_csv("axes.csv")

    # baseline twist/rmsd from the uniform row at the base count (10)
    base_n = base_count[list(base_count)[0]]
    T0 = R0 = None
    for r in uni:
        if int(r["count"]) == base_n:
            T0, R0 = float(r["twist_deg"]), float(r["rmsd_nm"])
    if T0 is None and uni:
        r = min(uni, key=lambda r: abs(int(r["count"]) - base_n))
        T0, R0 = float(r["twist_deg"]), float(r["rmsd_nm"])

    # per-helix slopes near best-guess
    slope, by_h = {}, {}
    for r in axes:
        by_h.setdefault(r["helix"], []).append(r)
    for hid, rows in by_h.items():
        cs = [int(r["count"]) for r in rows]
        slope[hid] = {"a_tw": linfit(cs, [float(r["twist_deg"]) for r in rows]),
                      "a_rm": linfit(cs, [float(r["rmsd_nm"]) for r in rows])}

    # ── SUMMARY.md ───────────────────────────────────────────────────────────────────────────
    L = [f"# exp37 — CanDo-FEM skip-vs-twist landscape ({DESIGN_PATH})\n",
         f"{meta['n_helices']} helices, best-guess {meta['total_base_skips']} skips "
         f"({base_n}/helix). Solver: {'FINE (nonlinear)' if meta['nonlinear'] else 'linear'}, "
         f"n_steps={meta['n_steps']}. Best-guess twist **{T0:.2f}°**, rmsd **{R0:.3f} nm**.\n",
         "## Uniform density sweep (all helices = count)\n",
         "| count | total skips | twist° | bend° | rmsd nm | dev_max nm |",
         "|--:|--:|--:|--:|--:|--:|"]
    for r in uni:
        L.append(f"| {r['count']} | {r['total_skips']} | {r['twist_deg']} | {r['bend_deg']} "
                 f"| {r['rmsd_nm']} | {r['dev_max_nm']} |")
    cross = None
    for a, b in zip(uni, uni[1:]):
        ta, tb = float(a["twist_deg"]), float(b["twist_deg"])
        if ta == 0 or (ta > 0) != (tb > 0):
            ca, cb = int(a["count"]), int(b["count"])
            cross = ca + (cb - ca) * (0 - ta) / (tb - ta) if tb != ta else ca
            break
    L.append(f"\n**Uniform twist→0 crossing ≈ {cross:.2f} skips/helix**\n" if cross
             else "\n**No twist sign change in the uniform range.**\n")
    L += ["## Per-helix twist authority (∂ vs skip count, near best-guess)\n",
          "| helix | ∂twist/∂skip (°) | ∂rmsd/∂skip (nm) |", "|---|--:|--:|"]
    for hid in sorted(slope, key=lambda h: slope[h]["a_tw"]):
        L.append(f"| {hid} | {slope[hid]['a_tw']:.3f} | {slope[hid]['a_rm']:.4f} |")
    open(os.path.join(RES, "SUMMARY.md"), "w").write("\n".join(L) + "\n")
    print("wrote SUMMARY.md ; T0", T0, "crossing", cross)

    # ── Analytic joint optimum: add skips to highest twist-authority-per-rmsd helices ──────────
    counts = dict(base_count)
    CAP = {hid: min(40, len(free[hid])) for hid in free}
    pred = T0
    guard = 0
    while abs(pred) > 0.2 and guard < 4000:
        guard += 1
        best_h, best_gain = None, 0.0
        for hid in slope:
            step = 1 if pred > 0 else -1                # +twist → add skips; −twist → remove
            nc = counts[hid] + step
            if nc < 0 or nc > CAP[hid]:
                continue
            newpred = pred + step * slope[hid]["a_tw"]
            gain = (abs(pred) - abs(newpred)) / max(slope[hid]["a_rm"], 1e-4)
            if gain > best_gain:
                best_gain, best_h, best_step = gain, hid, step
        if best_h is None:
            break
        counts[best_h] += best_step
        pred += best_step * slope[best_h]["a_tw"]
    added = sum(counts[h] - base_count[h] for h in counts)
    print(f"analytic proposal: pred twist {pred:.2f}°, net added skips {added}")

    # ── Candidate bracket: analytic + uniform picks + ±small offsets, all verified in parallel ──
    cands = {"analytic": dict(counts)}
    # pure-uniform candidates at the integer counts bracketing the crossing
    if cross:
        for c in {int(cross), int(cross) + 1, round(cross)}:
            cands[f"uniform{c}"] = {hid: c for hid in base_count}
    # analytic ± a couple net skips (distribute over highest-authority helices)
    order = sorted(slope, key=lambda h: slope[h]["a_tw"])   # most authority first
    for off in (-2, -1, +1, +2):
        c2 = dict(counts)
        pool_h = order if off > 0 else order[::-1]
        for k in range(abs(off)):
            hid = pool_h[k % len(pool_h)]
            c2[hid] = max(0, min(CAP[hid], c2[hid] + (1 if off > 0 else -1)))
        cands[f"analytic{off:+d}"] = c2

    names = list(cands)
    args = [(cands[n], free) for n in names]
    with Pool(min(N_WORKERS, len(args)), initializer=_init) as pool:
        results = pool.map(_solve_counts, args)

    o_header = ["candidate", "total_skips", "twist_deg", "bend_deg", "rmsd_nm", "dev_max_nm", "solve_s"]
    with open(os.path.join(RES, "optimize.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=o_header)
        w.writeheader()
        for name, res in zip(names, results):
            w.writerow({"candidate": name, "total_skips": res["total_skips"],
                        **{k: res[k] for k in ("twist_deg", "bend_deg", "rmsd_nm",
                                               "dev_max_nm", "solve_s")}})
            print(f"  {name:14s} twist={res['twist_deg']:7} rmsd={res['rmsd_nm']} "
                  f"skips={res['total_skips']}")

    # winner: |twist|<1° preferred, then min rmsd; else min |twist|
    def key(nr):
        _, res = nr
        t, rm = abs(float(res["twist_deg"])), float(res["rmsd_nm"])
        return (0 if t < 1.0 else 1, rm if t < 1.0 else t)
    win_name, win = min(zip(names, results), key=key)
    win_counts = cands[win_name]
    marks = {hid: {bp: -1 for bp in even_place(free[hid], win_counts[hid])} for hid in win_counts}
    marks = {k: v for k, v in marks.items() if v}
    json.dump({"candidate": win_name, "twist_deg": win["twist_deg"], "rmsd_nm": win["rmsd_nm"],
               "bend_deg": win["bend_deg"], "total_skips": win["total_skips"],
               "counts": win_counts,
               "marks": {hid: {str(bp): dl for bp, dl in v.items()} for hid, v in marks.items()}},
              open(os.path.join(RES, "optimized_marks.json"), "w"), indent=2)

    with open(os.path.join(RES, "SUMMARY.md"), "a") as f:
        f.write(f"\n## Joint twist+deviation optimum → **{win_name}**\n\n"
                f"- twist **{win['twist_deg']}°** (from {T0:.2f}°), bend {win['bend_deg']}°, "
                f"rmsd {win['rmsd_nm']} nm, {win['total_skips']} skips "
                f"(best-guess {meta['total_base_skips']}).\n"
                f"- marks written to `results/optimized_marks.json` (NOT applied to the design).\n")
    print(f"WINNER {win_name}: twist {win['twist_deg']}° rmsd {win['rmsd_nm']} "
          f"skips {win['total_skips']}")


if __name__ == "__main__":
    main()
