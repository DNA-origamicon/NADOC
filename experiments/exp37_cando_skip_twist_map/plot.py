"""exp37 plot — one PNG summarising the skip-vs-twist landscape.

Reads results/uniform.csv + results/axes.csv (+ optional optimize.csv / stage2.csv /
optimized_marks.json) and writes results/exp37_summary.png.  Four panels:
  (a) uniform diagonal: end-to-end twist vs skips/helix, with the twist=0 line, the crossing,
      the best-guess, and the verified optimum;
  (b) deviation RMSD + bend vs skips/helix (shows the twist↔deviation tradeoff);
  (c) per-helix twist-vs-count curves (the raw landscape, one line/helix);
  (d) per-helix authority ∂twist/∂skip (sorted bars) — which helices steer twist hardest.

Run:  PYTHONPATH=. uv run python experiments/exp37_cando_skip_twist_map/plot.py
"""
from __future__ import annotations

import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")
OUT = os.path.join(RES, "exp37_summary.png")


def read_csv(name):
    path = os.path.join(RES, name)
    if not os.path.isfile(path):
        return []
    with open(path, newline="") as f:
        return [r for r in csv.DictReader(f) if not r.get("error") and r.get("twist_deg")]


def linfit(xs, ys):
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else 0.0


def main():
    meta = json.load(open(os.path.join(RES, "metadata.json")))
    base_n = meta["base_count"][list(meta["base_count"])[0]]
    uni = sorted(read_csv("uniform.csv"), key=lambda r: int(r["count"]))
    axes = read_csv("axes.csv")
    opt = None
    if os.path.isfile(os.path.join(RES, "optimized_marks.json")):
        opt = json.load(open(os.path.join(RES, "optimized_marks.json")))
    spread = None
    if os.path.isfile(os.path.join(RES, "optimized_spread.json")):
        spread = json.load(open(os.path.join(RES, "optimized_spread.json")))

    uc = [int(r["count"]) for r in uni]
    ut = [float(r["twist_deg"]) for r in uni]
    ur = [float(r["rmsd_nm"]) for r in uni]
    ub = [float(r["bend_deg"]) for r in uni]

    by_h: dict = {}
    for r in axes:
        by_h.setdefault(r["helix"], []).append((int(r["count"]), float(r["twist_deg"]),
                                                 float(r["rmsd_nm"])))
    for hid in by_h:
        by_h[hid].sort()
    slope = {hid: linfit([c for c, _, _ in v], [t for _, t, _ in v]) for hid, v in by_h.items()}

    # twist→0 crossing on the uniform diagonal
    cross = None
    for (ca, ta), (cb, tb) in zip(zip(uc, ut), list(zip(uc, ut))[1:]):
        if ta == 0 or (ta > 0) != (tb > 0):
            cross = ca + (cb - ca) * (0 - ta) / (tb - ta) if tb != ta else ca
            break

    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"exp37 — CanDo-FEM skip → twist landscape  ({os.path.basename(meta['design'])}, "
                 f"{meta['n_helices']} helices, {'FINE' if meta['nonlinear'] else 'linear'} solver)",
                 fontsize=13, fontweight="bold")

    # (a) uniform twist vs count
    a = ax[0, 0]
    a.axhline(0, color="#888", lw=1)
    a.axhspan(-1, 1, color="#2ca02c", alpha=0.15, label="|twist| < 1° target")
    a.plot(uc, ut, "-o", color="#1f77b4", label="uniform end-to-end twist")
    a.plot([base_n], [next(t for c, t in zip(uc, ut) if c == base_n)], "s",
           color="#d62728", ms=11, label=f"best-guess ({base_n}/helix)")
    if cross:
        a.axvline(cross, ls="--", color="#2ca02c", label=f"twist→0 ≈ {cross:.1f}/helix")
    if spread:
        avg = sum(spread["counts"].values()) / len(spread["counts"])
        a.plot([avg], [float(spread["twist_deg"])], "*", color="#2ca02c", ms=18,
               markeredgecolor="k",
               label=f"recommended spread: {spread['twist_deg']}° @ {avg:.1f}/helix, "
                     f"bend {spread['bend_deg']}°")
    if opt:
        a.plot([], [], " ", label=f"concentrated optimum: {opt['twist_deg']}° "
               f"(1 helix @38, bend {opt.get('bend_deg')}°)")
    a.set_xlabel("skips per helix (uniform)")
    a.set_ylabel("end-to-end twist (°)")
    a.set_title("(a) Uniform density → twist")
    a.legend(fontsize=8)
    a.grid(alpha=0.3)

    # (b) rmsd + bend vs count (tradeoff)
    b = ax[0, 1]
    b.plot(uc, ur, "-o", color="#9467bd", label="deviation RMSD (nm)")
    b.plot(uc, ub, "-^", color="#ff7f0e", label="bend (°)")
    b.axvline(base_n, ls=":", color="#d62728", label=f"best-guess ({base_n})")
    if cross:
        b.axvline(cross, ls="--", color="#2ca02c", label=f"twist optimum (~{cross:.0f})")
    b.set_xlabel("skips per helix (uniform)")
    b.set_ylabel("RMSD (nm) / bend (°)")
    b.set_title("(b) Deviation + bend vs density (twist↔deviation tradeoff)")
    b.legend(fontsize=8)
    b.grid(alpha=0.3)

    # (c) per-helix twist-vs-count curves
    c = ax[1, 0]
    cmap = plt.get_cmap("viridis")
    hids = sorted(by_h)
    for i, hid in enumerate(hids):
        v = by_h[hid]
        c.plot([x for x, _, _ in v], [t for _, t, _ in v], "-", lw=1,
               color=cmap(i / max(len(hids) - 1, 1)), alpha=0.8)
    c.axhline(0, color="#888", lw=1)
    c.set_xlabel("count on the perturbed helix (others at best-guess)")
    c.set_ylabel("end-to-end twist (°)")
    c.set_title("(c) Per-helix axes — one line per helix")
    c.grid(alpha=0.3)

    # (d) per-helix authority bars
    dd = ax[1, 1]
    order = sorted(slope, key=lambda h: slope[h])
    vals = [slope[h] for h in order]
    dd.barh(range(len(order)), vals, color="#1f77b4")
    dd.set_yticks(range(len(order)))
    dd.set_yticklabels([h.replace("h_XY_", "") for h in order], fontsize=7)
    dd.set_xlabel("∂twist / ∂skip (° per added skip)")
    dd.set_title("(d) Per-helix twist authority (more negative = steers harder)")
    dd.grid(alpha=0.3, axis="x")

    fig.tight_layout(rect=[0, 0, 1, 0.97])
    fig.savefig(OUT, dpi=140)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
