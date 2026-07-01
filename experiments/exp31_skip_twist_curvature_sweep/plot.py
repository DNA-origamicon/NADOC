"""Live results plot for the skip-count → twist & curvature sweep (exp31).

Builds ONE composite ``results/skip_twist_curvature.png`` containing:
  * net twist vs total skip count (one series per placement strategy),
  * integrated curvature vs total skip count, and
  * a grid of the DETAILED per-run twist-vs-position profiles (cumulative twist along the
    bundle at ~24-bp resolution, with the uniform-twist linear reference overlaid so a kink
    = a local correction site stands out).

Summary panels read ``results/results.json``; the profile small-multiples read
``results/profiles/*.csv`` (written per run by run.py / backfill_profiles.py).  Safe to call
repeatedly while the driver runs (read-only) and runnable standalone (``python plot.py``).
"""
from __future__ import annotations

import csv
import json
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt

HERE = pathlib.Path(__file__).parent
RESULTS = HERE / "results" / "results.json"
PROFILE_DIR = HERE / "results" / "profiles"
PNG = HERE / "results" / "skip_twist_curvature.png"

_COLORS = {"uniform": "#1f77b4", "incremental": "#2ca02c", "deviation": "#d62728"}
_LABELS = {"uniform": "A · uniform restagger",
           "incremental": "B · incremental gap",
           "deviation": "C · deviation-guided"}
_ORDER = {"uniform": 0, "incremental": 1, "deviation": 2}


def _series(records, strategy, ykey):
    # Exclude structures the end-of-run health check flagged (healthy is False) so the analysis
    # never plots a metric from a melted/clashed structure; healthy True/None/absent are kept.
    pts = [(r["total_skips"], r.get(ykey)) for r in records
           if r.get("strategy") == strategy and r.get("status") == "ok"
           and r.get("healthy") is not False and r.get(ykey) is not None]
    pts.sort()
    return [p[0] for p in pts], [p[1] for p in pts]


def _parse_label(stem: str):
    """'uniform_d-4' → ('uniform', -4); tolerant of unexpected names."""
    if "_d" not in stem:
        return stem, 0
    strat, _, d = stem.rpartition("_d")
    try:
        return strat, int(d)
    except ValueError:
        return strat, 0


def _load_profiles_by_strategy():
    """{strategy: [(delta, [(position_bp, cum_twist_diff), …]), …]} sorted by delta."""
    out: dict[str, list] = {}
    if not PROFILE_DIR.exists():
        return out
    for csv_path in PROFILE_DIR.glob("*.csv"):
        strat, delta = _parse_label(csv_path.stem)
        pts = []
        with csv_path.open() as f:
            for row in csv.DictReader(f):
                pts.append((float(row["position_bp"]), float(row["cum_twist_diff"])))
        if pts:
            out.setdefault(strat, []).append((delta, pts))
    for s in out:
        out[s].sort(key=lambda t: t[0])
    return out


def regenerate(results_path=RESULTS, png_path=PNG) -> bool:
    results_path, png_path = pathlib.Path(results_path), pathlib.Path(png_path)
    if not results_path.exists():
        return False
    records = json.loads(results_path.read_text() or "[]")
    if not records:
        return False
    png_path.parent.mkdir(parents=True, exist_ok=True)

    baseline = next((r["total_skips"] for r in records if r.get("delta") == 0), None)
    strategies = [s for s in ("uniform", "incremental", "deviation")
                  if any(r.get("strategy") == s for r in records)]
    prof_by_strat = _load_profiles_by_strategy()
    skips_of = {(r["strategy"], r["delta"]): r["total_skips"] for r in records}
    # Diverging color scale shared across the profile panels: Δ<0 (fewer skips) → blue,
    # Δ>0 (more skips) → red, baseline → grey — so a legend reads consistently everywhere.
    all_deltas = sorted({d for v in prof_by_strat.values() for d, _ in v})
    dmax = max((abs(d) for d in all_deltas), default=1) or 1
    norm = mcolors.Normalize(vmin=-dmax, vmax=dmax)
    cmap = plt.cm.coolwarm
    prof_strats = [s for s in ("uniform", "incremental", "deviation") if s in prof_by_strat]
    n_prof = len(prof_strats)

    # OBJECTIVE metric: max |cumulative twist| anywhere along the profile (→ 0 = flat-zero
    # everywhere, the real goal — not just zero net/endpoint twist).  Computed from the profiles.
    def _flatness_series(strat):
        pts = sorted((skips_of.get((strat, d)), max((abs(y) for _, y in p), default=0.0))
                     for d, p in prof_by_strat.get(strat, []) if skips_of.get((strat, d)) is not None)
        return [a for a, _ in pts], [b for _, b in pts]

    ncol = max(1, n_prof)
    total_rows = 3 + (1 if n_prof else 0)
    fig = plt.figure(figsize=(5.2 * ncol, 4.0 * 3 + (4.0 if n_prof else 0)))
    gs = fig.add_gridspec(total_rows, ncol,
                          height_ratios=[1.4, 1.4, 1.4] + ([1.5] if n_prof else []))

    # ── summary panels (full width) ──────────────────────────────────────────────
    ax_f = fig.add_subplot(gs[0, :])   # the OBJECTIVE
    ax_t = fig.add_subplot(gs[1, :])
    ax_c = fig.add_subplot(gs[2, :])
    # flatness panel (its own series source = profiles)
    for s in strategies:
        xs, ys = _flatness_series(s)
        if xs:
            ax_f.plot(xs, ys, "-o", color=_COLORS[s], label=_LABELS[s], markersize=5)
    ax_f.axhline(0.0, color="0.6", lw=0.8, ls="--")
    if baseline is not None:
        ax_f.axvline(baseline, color="0.6", lw=0.8, ls=":")
    ax_f.set_ylabel("max |cumulative twist| (deg)")
    ax_f.set_title("OBJECTIVE — profile flatness: max |twist| along bundle (→ 0 = straight everywhere)")
    ax_f.grid(True, alpha=0.25)
    ax_f.legend(loc="best", fontsize=9)
    for ax, ykey, ylab, title in (
        (ax_t, "twist_diff", "net twist (deg)", "Net (endpoint) twist vs skip count — hides front/back cancellation"),
        (ax_c, "curvature_diff", "integrated curvature (deg/nm)",
         "Curvature (bending guard) vs skip count"),
    ):
        for s in strategies:
            xs, ys = _series(records, s, ykey)
            if xs:
                ax.plot(xs, ys, "-o", color=_COLORS[s], label=_LABELS[s], markersize=5)
        ax.axhline(0.0, color="0.6", lw=0.8, ls="--")
        if baseline is not None:
            ax.axvline(baseline, color="0.6", lw=0.8, ls=":")
        ax.set_ylabel(ylab)
        ax.set_title(title)
        ax.grid(True, alpha=0.25)
    ax_c.set_xlabel("total skips  (= 18 × Δ from baseline)")

    # ── twist-vs-position profiles: ONE panel per strategy, Δ overlaid + colour-coded ──
    for j, strat in enumerate(prof_strats):
        ax = fig.add_subplot(gs[3, j])
        for delta, pts in prof_by_strat[strat]:
            xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
            sk = skips_of.get((strat, delta))
            lbl = f"Δ{delta:+d}" + (f" ({sk})" if sk is not None else "")
            ax.plot(xs, ys, "-o", color=cmap(norm(delta)), markersize=3, lw=1.4, label=lbl)
        ax.axhline(0.0, color="0.85", lw=0.6)
        ax.set_title(f"{_LABELS.get(strat, strat)} — twist profile")
        ax.set_xlabel("position along bundle (bp, axis-projected)")
        if j == 0:
            ax.set_ylabel("cumulative twist (deg)")
        ax.grid(True, alpha=0.25)
        ax.legend(fontsize=7, title="Δ (total skips)", ncol=2, loc="best")

    title = "exp31 — skip count vs twist & curvature (3×6×400 SQ)"
    if n_prof:
        title += "  +  twist-vs-position profiles (24-bp bins, Δ overlaid per strategy)"
    fig.suptitle(title, fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.99))
    fig.savefig(png_path, dpi=130)
    plt.close(fig)
    return True


if __name__ == "__main__":
    ok = regenerate()
    print(f"wrote {PNG}" if ok else f"nothing to plot (no records in {RESULTS})")
