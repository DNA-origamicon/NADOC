#!/usr/bin/env python3
"""
plot_f020_progress.py — B_tube F020 pipeline health snapshot.

Reads F020_health_report.jsonl (and individual monitor files for any stages
missing from the pipeline report) and writes a PNG showing C1' and WC
reference-relative fraction vs. cumulative simulation time, with k-value
and temperature phase annotations.

Usage:
    python experiments/exp25_full_origami_relaxation/scripts/plot_f020_progress.py
    python experiments/exp25_full_origami_relaxation/scripts/plot_f020_progress.py \
        --out /tmp/f020_progress.png
"""

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
_SCRIPT = Path(__file__).resolve()
_PROJECT_ROOT = _SCRIPT.parents[3]
RUN_DIR = (
    _PROJECT_ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
      "/F018_mgh_slow_release/B_tube_namd_solvated"
)
MANIFEST_PATH = RUN_DIR / "F020_manifest.json"
HEALTH_REPORT = RUN_DIR / "output" / "F020_health_report.jsonl"
OUTPUT_DIR    = RUN_DIR / "output"

DEFAULT_OUT = RUN_DIR / "output" / "F020_progress.png"

# ── Stage name parser ──────────────────────────────────────────────────────────

def parse_name(name: str) -> dict:
    """Extract temp, k, total_ps, pct, is_npt from a stage name."""
    d = {"name": name, "temp": None, "k": None, "total_ps": None, "pct": None, "is_npt": False}

    m = re.search(r"_(\d+)K_", name)
    if m:
        d["temp"] = int(m.group(1))

    m = re.search(r"_k(\d+(?:p\d+)?)_", name)
    if m:
        d["k"] = float(m.group(1).replace("p", "."))
    if "_unrestrained_" in name:
        d["k"] = 0.0

    m = re.search(r"_(\d+)ps_", name)
    if m:
        d["total_ps"] = int(m.group(1))

    m = re.search(r"_p(\d+)$", name)
    if m:
        d["pct"] = int(m.group(1))

    if "_NPT_" in name:
        d["is_npt"] = True

    return d

# ── Manifest → ordered stage list with cumulative ps ──────────────────────────

def load_manifest() -> list[dict]:
    with MANIFEST_PATH.open() as fh:
        mf = json.load(fh)

    result = []
    cum_ps = 0.0          # running total, advanced at p100 only
    stage_start_ps = 0.0  # ps at the start of the current stage group
    prev_base = None

    for entry in mf["stages"]:
        name  = entry["name"]
        steps = entry["steps"]
        d     = parse_name(name)

        # 1 fs timestep → ps = steps * 0.001
        stage_ps = d["total_ps"] if d["total_ps"] else steps * 0.001

        base = re.sub(r"_p\d+$", "", name)
        if base != prev_base:
            prev_base       = base
            stage_start_ps  = cum_ps

        pct = d["pct"] or 100
        checkpoint_ps = stage_start_ps + stage_ps * (pct / 100)

        result.append({
            **d,
            "stage_ps"      : stage_ps,
            "stage_start_ps": stage_start_ps,
            "checkpoint_ps" : checkpoint_ps,
        })

        if pct == 100:
            cum_ps = checkpoint_ps

    return result

# ── Health report reader ───────────────────────────────────────────────────────

def _extract(record: dict) -> tuple[float | None, float | None]:
    """Return (c1_fraction, wc_rr_fraction) from a health record."""
    c1 = wc = None
    cf = record.get("c1_final")
    if cf:
        c1 = cf.get("paired_fraction")
    wf = record.get("wc_final")
    if wf:
        wc = wf.get("ref_relative_paired_fraction")
    # pipeline-written compact records
    if c1 is None: c1 = record.get("c1_fraction")
    if wc is None: wc = record.get("wc_fraction")
    return c1, wc

def load_health() -> dict[str, dict]:
    records: dict[str, dict] = {}

    # 1. pipeline health report
    if HEALTH_REPORT.exists():
        for line in HEALTH_REPORT.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if (n := d.get("name")):
                    records[n] = d
            except json.JSONDecodeError:
                pass

    # 2. individual monitor files (catches stages run outside the pipeline script)
    for bp_file in sorted(OUTPUT_DIR.glob("F020_*_basepair_monitor.jsonl")):
        stage = bp_file.stem.replace("_basepair_monitor", "")
        if stage in records:
            continue
        lines = [l for l in bp_file.read_text().splitlines() if l.strip()]
        if not lines:
            continue
        try:
            bp = json.loads(lines[-1])
        except Exception:
            continue
        wc = {}
        wf = OUTPUT_DIR / f"{stage}_watson_crick_monitor.json"
        if wf.exists():
            try:
                wc = json.loads(wf.read_text())
            except Exception:
                pass
        records[stage] = {"name": stage, "c1_final": bp, "wc_final": wc, "ok": True}

    return records

# ── Build plot data ────────────────────────────────────────────────────────────

def build_series(stages: list[dict], health: dict[str, dict]):
    """Merge manifest order with health data; return lists ready to plot."""
    xs, c1s, wcs, ks, temps, oks = [], [], [], [], [], []
    for s in stages:
        if s["name"] not in health:
            continue
        c1, wc = _extract(health[s["name"]])
        if c1 is None or wc is None:
            continue
        xs.append(s["checkpoint_ps"])
        c1s.append(c1 * 100)
        wcs.append(wc * 100)
        ks.append(s["k"])
        temps.append(s["temp"])
        oks.append(health[s["name"]].get("ok", True))
    return (
        np.array(xs), np.array(c1s), np.array(wcs),
        np.array(ks, dtype=float), np.array(temps), oks
    )

# ── Phase bands ────────────────────────────────────────────────────────────────

def compute_phase_bands(stages: list[dict], health: dict[str, dict]):
    """Return list of (x_start, x_end, temp, k, label) for completed phase bands."""
    bands = []
    prev = None
    for s in stages:
        if s["name"] not in health:
            break
        base = re.sub(r"_p\d+$", "", s["name"])
        # emit a band when the stage group changes
        if prev is not None and base != prev["base"]:
            bands.append({
                "x0"  : prev["stage_start_ps"],
                "x1"  : prev["checkpoint_ps"],
                "temp": prev["temp"],
                "k"   : prev["k"],
            })
        if prev is None or base != prev["base"]:
            prev = {"base": base, "stage_start_ps": s["stage_start_ps"],
                    "checkpoint_ps": s["checkpoint_ps"],
                    "temp": s["temp"], "k": s["k"]}
        else:
            prev["checkpoint_ps"] = s["checkpoint_ps"]
    if prev is not None:
        bands.append({
            "x0": prev["stage_start_ps"], "x1": prev["checkpoint_ps"],
            "temp": prev["temp"], "k": prev["k"],
        })
    return bands

def k_color(k: float | None) -> str:
    """Map k-value to a muted background color."""
    if k is None or k == 0:
        return "#ffecd2"   # unrestrained — warm amber
    if k >= 10:
        return "#dce9f5"   # strong restraint — cool blue
    if k >= 1:
        return "#e8f0e8"   # mid — muted green
    return "#f5f0e8"       # weak — light tan

# ── Main plot ──────────────────────────────────────────────────────────────────

def make_plot(out_path: Path):
    stages = load_manifest()
    health = load_health()
    xs, c1s, wcs, ks, temps, oks = build_series(stages, health)
    bands  = compute_phase_bands(stages, health)

    if len(xs) == 0:
        print("No completed health data found — nothing to plot.")
        return

    # ── Figure layout: top panel (metrics) + bottom panel (k-value) ───────────
    fig, (ax_main, ax_k) = plt.subplots(
        2, 1, figsize=(13, 7.5),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.08},
        sharex=True,
    )

    # ── Phase background bands ─────────────────────────────────────────────────
    for band in bands:
        color = k_color(band["k"])
        for ax in (ax_main, ax_k):
            ax.axvspan(band["x0"], band["x1"], color=color, alpha=0.55, zorder=0)

    # ── Threshold lines ────────────────────────────────────────────────────────
    ax_main.axhline(90, color="#d44", lw=1.0, ls="--", label="C1' threshold 90%", zorder=2)
    ax_main.axhline(85, color="#e8860a", lw=1.0, ls=":",  label="WC threshold 85%", zorder=2)

    # ── Metric traces ──────────────────────────────────────────────────────────
    ax_main.plot(xs, c1s, "o-", color="#1a6faf", lw=1.5, ms=4.5,
                 label="C1'–C1' paired %", zorder=4)
    ax_main.plot(xs, wcs, "s-", color="#e06800", lw=1.5, ms=4.5,
                 label="WC ref-relative %", zorder=4)

    # Mark any failed sub-stages
    failed = np.array([not ok for ok in oks])
    if failed.any():
        ax_main.scatter(xs[failed], c1s[failed], marker="X", s=80,
                        color="red", zorder=5, label="FAIL")

    # ── k-value step plot ──────────────────────────────────────────────────────
    k_vals = np.where(ks == 0, 0.01, ks)   # place unrestrained at 0.01 for log scale
    ax_k.step(xs, k_vals, where="post", color="#555", lw=1.5, zorder=3)
    ax_k.fill_between(xs, k_vals, step="post", alpha=0.15, color="#555", zorder=2)
    # mark unrestrained
    unrest_mask = ks == 0
    if unrest_mask.any():
        ax_k.scatter(xs[unrest_mask], np.full(unrest_mask.sum(), 0.01),
                     marker="*", s=80, color="#d44", zorder=5, label="unrestrained")
    ax_k.set_yscale("log")
    ax_k.set_ylabel("k\n(kcal/mol/Å²)", fontsize=9, labelpad=4)
    ax_k.set_yticks([0.01, 0.05, 0.1, 0.5, 1, 5, 10, 20])
    ax_k.set_yticklabels(["0\n(unrestr.)", "0.05", "0.1", "0.5", "1", "5", "10", "20"], fontsize=7)
    ax_k.yaxis.set_minor_formatter(mticker.NullFormatter())
    ax_k.set_ylim(0.005, 30)
    ax_k.grid(axis="y", ls=":", lw=0.5, color="#aaa")

    # ── Full pipeline "planned" x range ───────────────────────────────────────
    all_xs = [s["checkpoint_ps"] for s in stages]
    x_max = max(all_xs) if all_xs else xs[-1] + 5
    x_min = 0

    # ── Remaining planned stages (ghosted) ────────────────────────────────────
    completed_names = set(health.keys())
    remaining = [s for s in stages if s["name"] not in completed_names and s.get("k") is not None]
    if remaining:
        # shade the planned portion
        r_x0 = remaining[0]["stage_start_ps"]
        r_x1 = remaining[-1]["checkpoint_ps"]
        ax_main.axvspan(r_x0, r_x1, color="#e0e0e0", alpha=0.3, zorder=0)
        ax_k.axvspan(r_x0, r_x1, color="#e0e0e0", alpha=0.3, zorder=0)
        # ghost k-value trace for remaining
        r_xs = np.array([s["checkpoint_ps"] for s in remaining])
        r_ks = np.array([s["k"] if s["k"] > 0 else 0.01 for s in remaining])
        ax_k.step(r_xs, r_ks, where="post", color="#aaa", lw=1.0, ls="--", zorder=2)

    # ── Phase labels on top of ax_main ────────────────────────────────────────
    labeled = set()
    for band in bands:
        mid = (band["x0"] + band["x1"]) / 2
        k   = band["k"]
        t   = band["temp"]
        label = f"{t}K" if (t and k and k >= 10) else (
            f"k={k}" if k and k > 0 else "unrestr."
        )
        if label not in labeled:
            labeled.add(label)
            ax_main.text(mid, 99.6, label, ha="center", va="top",
                         fontsize=7, color="#444", clip_on=True)

    # ── Stats box ─────────────────────────────────────────────────────────────
    n_pass  = sum(oks)
    n_total = len(oks)
    last_stage = stages[[s["name"] for s in stages].index(
        max((h for h in health if any(s["name"] == h for s in stages)),
            key=lambda n: next(s["checkpoint_ps"] for s in stages if s["name"] == n),
            default=stages[0]["name"]
        )
    )]
    total_ps_done = xs[-1]
    status_color  = "#2a7a2a" if n_pass == n_total else "#d44"
    status_text   = (
        f"Completed: {n_total} checkpoints ({n_pass} pass, {n_total - n_pass} fail)\n"
        f"Simulated: {total_ps_done:.1f} ps  |  Last: {last_stage['name']}\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    ax_main.text(0.99, 0.97, status_text, transform=ax_main.transAxes,
                 ha="right", va="top", fontsize=8,
                 bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=status_color, lw=1.2),
                 color="#222", fontfamily="monospace")

    # ── Axes formatting ────────────────────────────────────────────────────────
    ax_main.set_xlim(x_min, x_max * 1.01)
    ax_main.set_ylim(82, 100.5)
    ax_main.set_ylabel("Base-pair retention (%)", fontsize=10)
    ax_main.tick_params(axis="both", labelsize=8)
    ax_main.grid(axis="both", ls=":", lw=0.5, color="#ccc")
    ax_main.yaxis.set_major_locator(mticker.MultipleLocator(2))

    ax_k.set_xlim(x_min, x_max * 1.01)
    ax_k.set_xlabel("Cumulative simulation time (ps)", fontsize=10)
    ax_k.tick_params(axis="both", labelsize=8)
    ax_k.grid(axis="x", ls=":", lw=0.5, color="#ccc")

    # ── Legend (main panel) ───────────────────────────────────────────────────
    legend_patches = [
        mpatches.Patch(color="#dce9f5", alpha=0.8, label="k ≥ 10  (NVT/NPT high-k)"),
        mpatches.Patch(color="#e8f0e8", alpha=0.8, label="1 ≤ k < 10"),
        mpatches.Patch(color="#f5f0e8", alpha=0.8, label="k < 1  (weak)"),
        mpatches.Patch(color="#ffecd2", alpha=0.8, label="unrestrained"),
        mpatches.Patch(color="#e0e0e0", alpha=0.6, label="planned (not yet run)"),
    ]
    ax_main.legend(
        handles=ax_main.get_lines()[:4] + legend_patches,
        loc="lower left", fontsize=7.5, framealpha=0.9,
        ncol=2, columnspacing=1.0,
    )

    # ── Title ─────────────────────────────────────────────────────────────────
    ax_main.set_title(
        "F020  B_tube DNA origami — k=20 → unrestrained health metrics\n"
        "CHARMM36 · TIP3P · MGH · NAMD 3.0.2 · 1 fs timestep",
        fontsize=11, pad=8,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")
    print(f"  {n_total} checkpoints | {total_ps_done:.1f} ps simulated | "
          f"{'ALL PASS' if n_pass == n_total else f'{n_total - n_pass} FAILED'}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="Output PNG path (default: output/F020_progress.png)")
    args = ap.parse_args()
    make_plot(args.out)

if __name__ == "__main__":
    main()
