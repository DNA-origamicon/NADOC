"""exp32 results plot — convergence of profile-guided refinement.

Top: the OBJECTIVE (max |cumulative twist| = profile flatness) and net twist vs round, with the
tolerance line + total-skip count.  Bottom: per-round twist-vs-position profiles overlaid
(colour-coded by round) so you watch the profile flatten toward zero.
"""
from __future__ import annotations

import csv
import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.cm as cm
import matplotlib.pyplot as plt

HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results" / "results.json"
PROFILE_DIR = HERE / "results" / "profiles"
PNG = HERE / "results" / "profile_refine.png"


def save_profile(profile, path, ykey) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["position_bp", ykey])
        for p in profile:
            w.writerow([p["position_bp"], p[ykey]])


def _load_round_profiles(prefix, ykey):
    """[(round, [(position_bp, value), …]), …] for round_*.csv (twist) or curv_round_*.csv."""
    out = []
    if PROFILE_DIR.exists():
        for f in PROFILE_DIR.glob(f"{prefix}*.csv"):
            rnd = int(f.stem.split("_")[-1])
            pts = [(float(r["position_bp"]), float(r[ykey])) for r in csv.DictReader(f.open())]
            if pts:
                out.append((rnd, pts))
    out.sort()
    return out


def regenerate(results_path=RESULTS, png_path=PNG, tol=5.0) -> bool:
    results_path, png_path = pathlib.Path(results_path), pathlib.Path(png_path)
    if not results_path.exists():
        return False
    recs = [r for r in json.loads(results_path.read_text() or "[]") if r.get("status") == "ok"]
    if not recs:
        return False
    png_path.parent.mkdir(parents=True, exist_ok=True)
    recs.sort(key=lambda r: r["round"])
    rounds = [r["round"] for r in recs]
    flat = [r.get("twist_profile_max") for r in recs]
    net = [r.get("twist_diff") for r in recs]
    skips = [r.get("total_skips") for r in recs]
    profiles = _load_round_profiles("round_", "cum_twist_diff")
    curv_profiles = _load_round_profiles("curv_round_", "cum_curv_diff")

    fig, (ax0, ax1, ax2) = plt.subplots(3, 1, figsize=(9, 13))
    ax0.plot(rounds, flat, "-o", color="#d62728", label="OBJECTIVE: max |cum twist| (flatness)")
    ax0.plot(rounds, net, "-o", color="#1f77b4", label="net (endpoint) twist")
    ax0.axhline(tol, color="0.6", ls="--", lw=1, label=f"tolerance {tol:g}°")
    ax0.axhline(0.0, color="0.85", lw=0.7)
    for x, s in zip(rounds, skips):
        ax0.annotate(f"{s}", (x, flat[rounds.index(x)]), textcoords="offset points",
                     xytext=(0, 6), fontsize=7, color="0.4", ha="center")
    ax0.set_xlabel("refinement round"); ax0.set_ylabel("twist (deg)")
    ax0.set_title("exp32 — profile-guided refinement convergence (labels = total skips)")
    ax0.grid(True, alpha=0.25); ax0.legend(fontsize=9)

    cmap = cm.viridis
    for ax, profs, ylab, title in (
        (ax1, profiles, "cumulative twist (deg)",
         "TWIST profile per round (→ flat-zero = straight, untwisted)"),
        (ax2, curv_profiles, "cumulative bending (deg)",
         "CURVATURE profile per round (→ flat-zero = straight axis; slope = local curvature)"),
    ):
        n = max(1, len(profs))
        for k, (rnd, pts) in enumerate(profs):
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            ax.plot(xs, ys, "-o", ms=3, color=cmap(k / n), label=f"round {rnd}")
        ax.axhline(0.0, color="0.85", lw=0.7)
        ax.set_xlabel("position along bundle (bp, axis-projected)")
        ax.set_ylabel(ylab); ax.set_title(title)
        ax.grid(True, alpha=0.25)
        if profs:
            ax.legend(fontsize=8, ncol=2)

    fig.tight_layout(); fig.savefig(png_path, dpi=130); plt.close(fig)
    return True


if __name__ == "__main__":
    print(f"wrote {PNG}" if regenerate() else "nothing to plot")
