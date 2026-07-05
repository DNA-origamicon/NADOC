"""exp39 (G2) analysis — is per-helix authority predictable from cross-section geometry?

Reads results/authority.csv + routing_audit.json and tests the candidate laws:
  * ∂bend/∂skip  ∝ moment arm r_h        (bimetallic: magnitude grows with distance off-axis)
  * ∂twist/∂skip vs (r_h, N, D)          (per-tube ~uniform; across tubes scales with size)
Writes results/SUMMARY.md and results/exp39_authority.png.
"""
from __future__ import annotations

import csv
import json
import math
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load():
    with open(os.path.join(RES, "authority.csv")) as f:
        rows = [r for r in csv.DictReader(f)]
    for r in rows:
        for k in ("r_nm", "dtwist_per_skip", "dbend_per_skip"):
            r[k] = float(r[k]) if r[k] not in ("", "None") else float("nan")
        r["D"] = int(r["D"]); r["n_helices"] = int(r["n_helices"])
        r["hollow"] = r["hollow"] in ("True", "true", "1")
    return rows


def corr(xs, ys):
    pts = [(x, y) for x, y in zip(xs, ys) if not (math.isnan(x) or math.isnan(y))]
    if len(pts) < 3:
        return float("nan")
    xs, ys = zip(*pts)
    n = len(xs); mx = sum(xs) / n; my = sum(ys) / n
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs)); sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return float("nan")
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def main():
    rows = load()
    audit = json.load(open(os.path.join(RES, "routing_audit.json")))
    # Exclude routing-FLAGGED tubes from the law fits (e.g. solid_d3 = 2 disjoint scaffolds) — their
    # topology is wrong, so their authority numbers are not trustworthy.  Still shown in the audit.
    flagged = {t for t, a in audit.items() if a["flags"]}
    rows = [r for r in rows if r["tube"] not in flagged]
    tubes = sorted({r["tube"] for r in rows},
                   key=lambda t: (not t.startswith("hollow"), t))

    L = ["# exp39 (G2) — hollow-tube per-helix authority vs geometry\n",
         "## Routing audit (every generated tube)\n",
         "| tube | D | hollow | helices | crossovers | mesh nodes | nonadj xo | nick@xo | flags |",
         "|---|--:|:--:|--:|--:|--:|--:|:--:|---|"]
    for t, a in audit.items():
        L.append(f"| {t} | {a['D']} | {a['hollow']} | {a['n_helices']} | {a['n_crossovers']} | "
                 f"{a['mesh_nodes']} | {a['nonadjacent_xo']} | {a['nick_on_xo_error']} | "
                 f"{'; '.join(a['flags']) or 'clean'} |")
    L.append("\n*(nick@xo = staple nick on a crossover — a GENERAL square-autostaple limitation, "
             "present on solid too; not hollow-specific. nonadj xo = crossover across the hollow, "
             "the real red flag — must be 0.)*\n")

    # ∂bend/∂skip vs r_h — per tube (bimetallic → |dbend| grows with r)
    L.append("## Law 1: ∂bend/∂skip vs moment arm r_h (per tube)\n")
    L.append("| tube | corr(r, |dbend|) | max|dbend| | r range (nm) |")
    L.append("|---|--:|--:|---|")
    for t in tubes:
        tr = [r for r in rows if r["tube"] == t]
        c = corr([r["r_nm"] for r in tr], [abs(r["dbend_per_skip"]) for r in tr])
        rr = [r["r_nm"] for r in tr]
        L.append(f"| {t} | {c:+.2f} | {max(abs(r['dbend_per_skip']) for r in tr):.2f} | "
                 f"{min(rr):.1f}–{max(rr):.1f} |")

    # ∂twist/∂skip — per-tube mean/spread + scaling vs helix count N
    L.append("\n## Law 2: ∂twist/∂skip — per-tube mean (does it scale with size?)\n")
    L.append("| tube | D | N helices | mean dtwist/skip | std | mean·N |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for t in tubes:
        tr = [r for r in rows if r["tube"] == t]
        vals = [r["dtwist_per_skip"] for r in tr]
        mean = sum(vals) / len(vals)
        std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        N = tr[0]["n_helices"]
        L.append(f"| {t} | {tr[0]['D']} | {N} | {mean:.3f} | {std:.3f} | {mean*N:.2f} |")
    L.append("\n*(If `mean·N` is ~constant across tubes, ∂twist/∂skip ∝ 1/N — the cross-section "
             "scaling exp37/exp36 saw: more helices share the torsional load, so each skip steers "
             "twist less.)*\n")

    open(os.path.join(RES, "SUMMARY.md"), "w").write("\n".join(L) + "\n")
    print("wrote SUMMARY.md")

    # ── plot ────────────────────────────────────────────────────────────────────────────────
    fig, ax = plt.subplots(1, 2, figsize=(13, 5.2))
    cmap = plt.get_cmap("viridis")
    for i, t in enumerate(tubes):
        tr = [r for r in rows if r["tube"] == t]
        col = cmap(i / max(len(tubes) - 1, 1))
        ax[0].scatter([r["r_nm"] for r in tr], [r["dbend_per_skip"] for r in tr],
                      color=col, label=t, s=28)
    ax[0].axhline(0, color="#888", lw=1)
    ax[0].set_xlabel("moment arm r_h (nm)"); ax[0].set_ylabel("∂bend/∂skip (°)")
    ax[0].set_title("(a) Bend authority vs moment arm (bimetallic)")
    ax[0].legend(fontsize=7); ax[0].grid(alpha=0.3)

    Ns, means, mns = [], [], []
    for t in tubes:
        tr = [r for r in rows if r["tube"] == t]
        vals = [r["dtwist_per_skip"] for r in tr]
        Ns.append(tr[0]["n_helices"]); means.append(sum(vals) / len(vals))
    ax[1].scatter(Ns, means, c="#1f77b4", s=45)
    for t, N, m in zip(tubes, Ns, means):
        ax[1].annotate(t.replace("_", " "), (N, m), fontsize=7,
                       textcoords="offset points", xytext=(4, 3))
    xs = sorted(set(Ns))
    k = sum(m * n for m, n in zip(means, Ns)) / len(Ns)   # fit mean ≈ k/N
    ax[1].plot(xs, [k / n for n in xs], "--", color="#d62728", label=f"k/N fit (k={k:.1f})")
    ax[1].set_xlabel("helix count N"); ax[1].set_ylabel("mean ∂twist/∂skip (°)")
    ax[1].set_title("(b) Twist authority vs helix count")
    ax[1].legend(fontsize=8); ax[1].grid(alpha=0.3)

    fig.suptitle("exp39 (G2) — per-helix skip authority vs cross-section geometry (SQ tubes)",
                 fontweight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(os.path.join(RES, "exp39_authority.png"), dpi=140)
    print("wrote exp39_authority.png")


if __name__ == "__main__":
    main()
