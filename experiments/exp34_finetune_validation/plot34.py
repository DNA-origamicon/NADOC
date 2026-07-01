"""exp34 plots — per-run annotated profile PNGs + a combined overview.

For EACH run (one row in results.json) renders ``results/profiles/png/<label>.png``: the cumulative
twist-error profile (the experiment's objective) over the curvature-error profile, sharing the
axial position axis, with a WATSON–CRICK HEALTH annotation box (bp-pair retention, FENE safety,
energy convergence, healthy verdict) so a melted/clashed run is never mistaken for a flat one.
Also writes ``results/profile_overview.png`` overlaying every healthy run's twist profile.

Importable (``regenerate()`` is called by the driver after each sim) AND standalone — run it any
time to (re)build all PNGs from the persisted results.json + profile JSONs (no GPU, no re-sim):

    python plot34.py
"""
from __future__ import annotations

import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = pathlib.Path(__file__).parent
RESULTS_DIR = HERE / "results"
RESULTS_JSON = RESULTS_DIR / "results.json"
PROFILE_DIR = RESULTS_DIR / "profiles"
PNG_DIR = PROFILE_DIR / "png"
OVERVIEW = RESULTS_DIR / "profile_overview.png"


def _load(path: pathlib.Path):
    return json.loads(path.read_text()) if path.exists() else None


def _twist_path(label: str) -> pathlib.Path:
    return PROFILE_DIR / f"{label}.json"


def _curv_path(label: str) -> pathlib.Path:
    return PROFILE_DIR / f"curv_{label}.json"


def _series_path(label: str) -> pathlib.Path:
    return PROFILE_DIR / f"twistseries_{label}.json"


def _wc_health_text(rec: dict) -> tuple[str, str]:
    """(annotation string, colour) summarising Watson–Crick / structural health of a run."""
    healthy = rec.get("healthy")
    bp = rec.get("bp_retained")
    lines = [
        f"WC bp-retained: {bp*100:.1f}%" if isinstance(bp, (int, float)) else "WC bp-retained: n/a",
        f"FENE-safe: {rec.get('fene_safe')}  (n_over={rec.get('n_fene_over', '?')})",
        f"max backbone stretch: {rec.get('max_backbone_stretch_nm', '?')} nm",
        f"energy converged: {rec.get('energy_converged')}",
        f"HEALTHY: {healthy}",
    ]
    if rec.get("health_reason"):
        lines.append(f"reason: {rec['health_reason'][:48]}")
    colour = "#1b7837" if healthy else ("#b2182b" if healthy is False else "#777777")
    return "\n".join(lines), colour


def save_run_png(rec: dict) -> pathlib.Path | None:
    """Annotated per-run PNG: twist-error profile + curvature-error profile + WC-health box."""
    label = rec.get("label")
    if not label:
        return None
    twist = _load(_twist_path(label))
    if not twist:
        return None
    curv = _load(_curv_path(label))
    series = _load(_series_path(label))
    PNG_DIR.mkdir(parents=True, exist_ok=True)

    # row 0 cumulative twist profile + row 1 curvature profile share the position axis;
    # row 2 (per-frame twist time series) is independent (x = frame index).
    fig = plt.figure(figsize=(9, 10))
    gs = fig.add_gridspec(3, 1, height_ratios=[2, 1, 1.6], hspace=0.32)
    axt = fig.add_subplot(gs[0])
    axc = fig.add_subplot(gs[1], sharex=axt)
    axs = fig.add_subplot(gs[2])
    xs = [p["position_bp"] for p in twist]
    yt = [p["cum_twist_diff"] for p in twist]
    profmax = max((abs(v) for v in yt), default=0.0)
    axt.axhline(0, color="#444", lw=0.8, ls="--", label="flat-zero target")
    axt.plot(xs, yt, "-o", ms=3, color="#2166ac", label="cum twist error (sim−analytic)")
    # mark the worst |profile| point — the objective metric
    if yt:
        iworst = max(range(len(yt)), key=lambda i: abs(yt[i]))
        axt.plot(xs[iworst], yt[iworst], "v", ms=10, color="#b2182b",
                 label=f"max|profile| = {profmax:.1f}°")
    twist_diff = rec.get("twist_diff")
    title = (f"{label}   |   {rec.get('total_skips', '?')} skips   |   "
             f"net twist {twist_diff}°   max|profile| {rec.get('twist_profile_max', profmax)}°")
    axt.set_title(title, fontsize=10)
    axt.set_ylabel("cumulative twist error (deg)")
    axt.grid(alpha=0.25); axt.legend(fontsize=8, loc="best")

    if curv:
        xc = [p["position_bp"] for p in curv]
        yc = [p["cum_curv_diff"] for p in curv]
        axc.plot(xc, yc, "-o", ms=3, color="#762a83",
                 label=f"cum curvature error  (Δcurv {rec.get('curvature_diff', '?')})")
        axc.legend(fontsize=8, loc="best")
    else:
        axc.text(0.5, 0.5, f"curvature profile not saved\n(Δcurv scalar = {rec.get('curvature_diff', '?')})",
                 ha="center", va="center", transform=axc.transAxes, fontsize=9, color="#762a83")
    axc.axhline(0, color="#444", lw=0.8, ls="--")
    axc.set_ylabel("cum curvature err (deg)")
    axc.set_xlabel("position along bundle (bp, axis-projected)")
    axc.grid(alpha=0.25)

    # row 2 — per-FRAME twist (the τ / N_eff sampling diagnostic)
    _twist_series_panel(axs, series, rec)

    # WC / structural-health annotation box (anchored to the top profile panel)
    text, colour = _wc_health_text(rec)
    axt.text(1.012, 0.98, text, transform=axt.transAxes, fontsize=8, va="top", ha="left",
             family="monospace",
             bbox=dict(boxstyle="round", fc="white", ec=colour, lw=2))
    out = PNG_DIR / f"{label}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def save_twistseries_png(rec: dict) -> pathlib.Path | None:
    """Single-panel per-frame twist PNG (for burn-in runs that have a series but no spatial
    profile): the time series + equilibration burn-in cutoff + equilibrated mean ± SEM."""
    label = rec.get("label")
    series = _load(_series_path(label or ""))
    if not series:
        return None
    PNG_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 5))
    _twist_series_panel(ax, series, rec)
    eq = rec.get("equilibrated") or {}
    ax.set_title(f"{label}  |  {rec.get('total_skips')} skips  |  "
                 f"EQUILIBRATED twist {eq.get('mean')}° ± {eq.get('sem')}°  "
                 f"(burn-in {eq.get('t0_frames')}f, N_eff {eq.get('n_eff')})", fontsize=10)
    out = PNG_DIR / f"{label}.png"
    fig.savefig(out, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return out


def _twist_series_panel(ax, series: dict | None, rec: dict) -> None:
    """Per-frame differential twist over the trajectory, with the time-mean ± SEM band, the
    twist-on-time-AVERAGE-structure line (the current single-number estimator), and a stats box
    (τ_int, N_eff/N, std, SEM) — the diagnostic for 'is the 8M run long enough to resolve twist?'."""
    if not series or not series.get("twist_per_frame"):
        ax.text(0.5, 0.5, "per-frame twist series not saved for this run",
                ha="center", va="center", transform=ax.transAxes, fontsize=9, color="#888")
        ax.set_ylabel("per-frame twist (deg)"); ax.set_xlabel("production frame")
        return
    y = series["twist_per_frame"]
    st = series.get("stats") or {}
    mean = st.get("mean", 0.0); sem = st.get("sem", 0.0); std = st.get("std", 0.0)
    tau = st.get("tau_int"); neff = st.get("n_eff"); n = series.get("n_frames", len(y))
    x = list(range(len(y)))
    ax.axhline(0, color="#444", lw=0.8, ls="--")
    ax.plot(x, y, "-", lw=0.8, color="#2166ac", alpha=0.85, label="per-frame twist (sim−analytic)")
    ax.axhline(mean, color="#b2182b", lw=1.6, label=f"time-mean {mean:.1f}° ± SEM {sem:.1f}°")
    ax.axhspan(mean - sem, mean + sem, color="#b2182b", alpha=0.15)
    onmean = series.get("twist_on_mean_structure")
    if onmean is not None:
        ax.axhline(onmean, color="#1b7837", lw=1.4, ls=":",
                   label=f"twist on time-AVG structure {onmean:.1f}° (current estimator)")
    # equilibration burn-in cutoff + post-burn-in mean (the trustworthy number)
    eq = series.get("equilibrated") or {}
    eqs = eq.get("stats") or {}
    t0 = eq.get("t0")
    if t0 is not None and eqs.get("mean") is not None:
        ax.axvline(t0, color="#444", lw=1.2, ls="-.")
        ax.axvspan(0, t0, color="#999", alpha=0.12)
        ax.text(t0, ax.get_ylim()[1], " burn-in", fontsize=7, va="top", color="#444")
        em, es = eqs["mean"], eqs.get("sem", 0.0)
        ax.plot([t0, len(y)], [em, em], color="#2ca25f", lw=2.0,
                label=f"EQUILIBRATED {em:.1f}° ± {es:.1f}° (post burn-in, N_eff {eqs.get('n_eff', 0):.0f})")
    ax.set_ylabel("per-frame twist (deg)")
    ax.set_xlabel("production frame")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="upper left")
    box = (f"τ_int = {tau:.1f} frames\nN_eff = {neff:.1f} / {n}\n"
           f"std (per-frame) = {std:.1f}°\nSEM (corr.) = {sem:.1f}°\n"
           f"naive std/√N = {std / (n ** 0.5):.1f}°" if tau is not None else "")
    if box:
        under = neff is not None and neff < 20
        ax.text(1.012, 0.98, box, transform=ax.transAxes, fontsize=8, va="top", ha="left",
                family="monospace",
                bbox=dict(boxstyle="round", fc="#fff4f4" if under else "white",
                          ec="#b2182b" if under else "#777", lw=2))


def save_overview(records: list[dict]) -> None:
    ok = [r for r in records if r.get("status") == "ok" and _twist_path(r.get("label", "")).exists()]
    if not ok:
        return
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.axhline(0, color="#444", lw=0.8, ls="--")
    cmap = plt.get_cmap("tab10")
    for i, rec in enumerate(ok):
        twist = _load(_twist_path(rec["label"]))
        xs = [p["position_bp"] for p in twist]
        ys = [p["cum_twist_diff"] for p in twist]
        bp = rec.get("bp_retained")
        wc = f"WC {bp*100:.0f}%" if isinstance(bp, (int, float)) else "WC n/a"
        hmark = "" if rec.get("healthy") else "  ⚠UNHEALTHY"
        ls = "-" if rec.get("healthy") else ":"
        ax.plot(xs, ys, ls, color=cmap(i % 10), lw=1.6,
                label=f"{rec['label']}  ({rec.get('total_skips')}sk, net {rec.get('twist_diff')}°, "
                      f"max {rec.get('twist_profile_max')}°, {wc}){hmark}")
    ax.set_xlabel("position along bundle (bp, axis-projected)")
    ax.set_ylabel("cumulative twist error (deg)")
    ax.set_title("exp34 — twist-error profiles (solid=healthy, dotted=unhealthy)")
    ax.grid(alpha=0.25); ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    fig.savefig(OVERVIEW, dpi=120)
    plt.close(fig)


def regenerate() -> None:
    """Rebuild every per-run PNG + the overview from the persisted results + profile JSONs."""
    records = _load(RESULTS_JSON) or []
    for rec in records:
        if rec.get("status") == "ok":
            save_run_png(rec)
    save_overview(records)


if __name__ == "__main__":
    regenerate()
    print(f"[plot34] wrote PNGs to {PNG_DIR} and {OVERVIEW}")
