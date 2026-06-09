#!/usr/bin/env python3
"""
plot_pipeline_progress.py — B_tube full pipeline health snapshot.

Broken x-axis layout:
  Left panel  : F020 restraint ladder  (0 → ~305 ps, ps scale)
  Right panel : F022 ENM production    (transition + ongoing, ns scale)

Health data sources:
  F020 — F020_health_report.jsonl + individual monitor files (existing)
  F022 transition — output/F022_transition_health.json  (written at first run)
  F022 production — output/F022_production_health_cache.jsonl
                    (per-frame cache; stale frames trigger monitor recompute)

Usage:
    python experiments/exp25_full_origami_relaxation/scripts/plot_pipeline_progress.py
    python experiments/exp25_full_origami_relaxation/scripts/plot_pipeline_progress.py \\
        --out /tmp/pipeline_progress.png
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.ticker as mticker
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
_SCRIPT       = Path(__file__).resolve()
_SCRIPTS_DIR  = _SCRIPT.parent
_PROJECT_ROOT = _SCRIPT.parents[3]
RUN_DIR = (
    _PROJECT_ROOT
    / "experiments/exp25_full_origami_relaxation/results/runs"
      "/F018_mgh_slow_release/B_tube_namd_solvated"
)
OUTPUT_DIR         = RUN_DIR / "output"
MANIFEST_PATH      = RUN_DIR / "F020_manifest.json"
HEALTH_REPORT      = OUTPUT_DIR / "F020_health_report.jsonl"
PROD_LOG           = RUN_DIR / "F022_enm_production.log"
PROD_DCD           = OUTPUT_DIR / "F022_enm_production.dcd"
TRANS_HEALTH_CACHE = OUTPUT_DIR / "F022_transition_health.json"
PROD_HEALTH_CACHE  = OUTPUT_DIR / "F022_production_health_cache.jsonl"
PSF                = RUN_DIR / "B_tube.psf"
REF_PDB            = RUN_DIR / "B_tube.pdb"
TRANS_DCD          = OUTPUT_DIR / "F022_enm_transition.dcd"

PYTHON = sys.executable
BP_MON = str(_SCRIPTS_DIR / "basepair_monitor.py")
WC_MON = str(_SCRIPTS_DIR / "watson_crick_monitor.py")

DEFAULT_OUT = OUTPUT_DIR / "pipeline_progress.png"

# ── F020 loading (from existing script) ───────────────────────────────────────

def parse_stage_name(name: str) -> dict:
    d = {"name": name, "temp": None, "k": None, "total_ps": None, "pct": None}
    m = re.search(r"_(\d+)K_", name)
    if m: d["temp"] = int(m.group(1))
    m = re.search(r"_k(\d+(?:p\d+)?)_", name)
    if m: d["k"] = float(m.group(1).replace("p", "."))
    if "_unrestrained_" in name: d["k"] = 0.0
    m = re.search(r"_(\d+)ps_", name)
    if m: d["total_ps"] = int(m.group(1))
    m = re.search(r"_p(\d+)$", name)
    if m: d["pct"] = int(m.group(1))
    return d

def load_f020_stages() -> list[dict]:
    with MANIFEST_PATH.open() as fh:
        mf = json.load(fh)
    result, cum_ps, stage_start_ps, prev_base = [], 0.0, 0.0, None
    for entry in mf["stages"]:
        name, steps = entry["name"], entry["steps"]
        d = parse_stage_name(name)
        stage_ps = d["total_ps"] if d["total_ps"] else steps * 0.001
        base = re.sub(r"_p\d+$", "", name)
        if base != prev_base:
            prev_base, stage_start_ps = base, cum_ps
        pct = d["pct"] or 100
        checkpoint_ps = stage_start_ps + stage_ps * (pct / 100)
        result.append({**d, "stage_ps": stage_ps,
                        "stage_start_ps": stage_start_ps,
                        "checkpoint_ps": checkpoint_ps})
        if pct == 100:
            cum_ps = checkpoint_ps
    return result

def load_f020_health() -> dict[str, dict]:
    records: dict[str, dict] = {}
    if HEALTH_REPORT.exists():
        for line in HEALTH_REPORT.read_text().splitlines():
            line = line.strip()
            if not line: continue
            try:
                d = json.loads(line)
                if (n := d.get("name")): records[n] = d
            except json.JSONDecodeError:
                pass
    for bp_file in sorted(OUTPUT_DIR.glob("F020_*_basepair_monitor.jsonl")):
        stage = bp_file.stem.replace("_basepair_monitor", "")
        if stage in records: continue
        lines = [l for l in bp_file.read_text().splitlines() if l.strip()]
        if not lines: continue
        try:
            bp = json.loads(lines[-1])
        except Exception:
            continue
        wc = {}
        wf = OUTPUT_DIR / f"{stage}_watson_crick_monitor.json"
        if wf.exists():
            try: wc = json.loads(wf.read_text())
            except Exception: pass
        records[stage] = {"name": stage, "c1_final": bp, "wc_final": wc, "ok": True}
    return records

def extract_health(record: dict) -> tuple[float | None, float | None]:
    c1 = wc = None
    if cf := record.get("c1_final"):
        c1 = cf.get("paired_fraction")
    if wf := record.get("wc_final"):
        wc = wf.get("ref_relative_paired_fraction")
    if c1 is None: c1 = record.get("c1_fraction")
    if wc is None: wc = record.get("wc_fraction")
    return c1, wc

def build_f020_series(stages, health):
    xs, c1s, wcs, ks, oks = [], [], [], [], []
    for s in stages:
        if s["name"] not in health: continue
        c1, wc = extract_health(health[s["name"]])
        if c1 is None or wc is None: continue
        xs.append(s["checkpoint_ps"])
        c1s.append(c1 * 100)
        wcs.append(wc * 100)
        ks.append(s["k"])
        oks.append(health[s["name"]].get("ok", True))
    return np.array(xs), np.array(c1s), np.array(wcs), np.array(ks, dtype=float), oks

# ── F022 transition health ─────────────────────────────────────────────────────

def load_f022_transition_health() -> dict | None:
    """Load from cache; populate cache from /tmp or by running monitors."""
    if TRANS_HEALTH_CACHE.exists():
        try:
            return json.loads(TRANS_HEALTH_CACHE.read_text())
        except Exception:
            pass

    # Try /tmp files written by the monitor at transition completion
    c1_file = Path("/tmp/F022_c1.jsonl")
    wc_file = Path("/tmp/F022_wc.json")

    c1, wc = None, None

    if c1_file.exists():
        lines = [l for l in c1_file.read_text().splitlines() if l.strip()]
        if lines:
            try:
                last = json.loads(lines[-1])
                c1 = last.get("paired_fraction")
            except Exception:
                pass

    if wc_file.exists():
        try:
            d = json.loads(wc_file.read_text())
            wc = d.get("ref_relative_paired_fraction")
        except Exception:
            pass

    if c1 is None and TRANS_DCD.exists():
        print("Computing F022 transition health from DCD (one-time)...")
        c1, wc = _run_monitors(TRANS_DCD, out_suffix="transition")

    if c1 is None:
        return None

    result = {"c1_fraction": c1, "wc_fraction": wc}
    TRANS_HEALTH_CACHE.write_text(json.dumps(result, indent=2))
    return result

# ── F022 production health cache ───────────────────────────────────────────────

def _dcd_frame_count(dcd_path: Path) -> int:
    try:
        import MDAnalysis as mda
        u = mda.Universe(str(PSF), str(dcd_path))
        return len(u.trajectory)
    except Exception:
        return 0

def _run_monitors(dcd_path: Path, out_suffix: str) -> tuple[float | None, float | None]:
    """Run basepair and WC monitors on dcd_path, return last-frame (c1, wc)."""
    bp_out  = Path(f"/tmp/F022_{out_suffix}_c1.jsonl")
    wc_out  = Path(f"/tmp/F022_{out_suffix}_wc.json")
    c1 = wc = None
    try:
        subprocess.run(
            [PYTHON, BP_MON,
             "--psf", str(PSF), "--pdb", str(REF_PDB),
             "--dcd", str(dcd_path),
             "--out-jsonl", str(bp_out),
             "--safe-back", "0", "--paired-max-ang", "13.0", "--min-paired", "0.90"],
            capture_output=True, timeout=1800,
        )
        if bp_out.exists():
            lines = [l for l in bp_out.read_text().splitlines() if l.strip()]
            if lines:
                c1 = json.loads(lines[-1]).get("paired_fraction")
    except Exception as e:
        print(f"  basepair_monitor failed: {e}")
    try:
        subprocess.run(
            [PYTHON, WC_MON,
             "--psf", str(PSF), "--ref-pdb", str(REF_PDB),
             "--dcd", str(dcd_path), "--out", str(wc_out)],
            capture_output=True, timeout=1800,
        )
        if wc_out.exists():
            wc = json.loads(wc_out.read_text()).get("ref_relative_paired_fraction")
    except Exception as e:
        print(f"  watson_crick_monitor failed: {e}")
    return c1, wc

def load_f022_production_health() -> list[dict]:
    """
    Return list of {frame, time_ns, c1_fraction, wc_fraction}.
    Recomputes only if the DCD has more frames than the cache.
    """
    if not PROD_DCD.exists():
        return []

    n_dcd = _dcd_frame_count(PROD_DCD)
    if n_dcd == 0:
        return []

    # Load existing cache
    cached: list[dict] = []
    if PROD_HEALTH_CACHE.exists():
        for line in PROD_HEALTH_CACHE.read_text().splitlines():
            line = line.strip()
            if line:
                try: cached.append(json.loads(line))
                except Exception: pass

    if len(cached) >= n_dcd:
        return cached  # cache is current

    # Need to recompute all frames (monitors process full DCD)
    print(f"Computing production health ({n_dcd} DCD frames)...")
    bp_out = Path("/tmp/F022_prod_c1.jsonl")
    wc_out = Path("/tmp/F022_prod_wc.json")

    c1_frames, wc_frame = [], None
    try:
        subprocess.run(
            [PYTHON, BP_MON,
             "--psf", str(PSF), "--pdb", str(REF_PDB),
             "--dcd", str(PROD_DCD),
             "--out-jsonl", str(bp_out),
             "--safe-back", "0", "--paired-max-ang", "13.0", "--min-paired", "0.90"],
            capture_output=True, timeout=3600,
        )
        if bp_out.exists():
            for line in bp_out.read_text().splitlines():
                line = line.strip()
                if line:
                    try: c1_frames.append(json.loads(line))
                    except Exception: pass
    except Exception as e:
        print(f"  basepair_monitor failed: {e}")

    try:
        subprocess.run(
            [PYTHON, WC_MON,
             "--psf", str(PSF), "--ref-pdb", str(REF_PDB),
             "--dcd", str(PROD_DCD), "--out", str(wc_out)],
            capture_output=True, timeout=3600,
        )
        if wc_out.exists():
            try: wc_frame = json.loads(wc_out.read_text())
            except Exception: pass
    except Exception as e:
        print(f"  watson_crick_monitor failed: {e}")

    # DCD timestep = 50000 steps × 2 fs = 100 ps = 0.1 ns per frame
    DCD_STEP_NS = 0.1
    records = []
    for i, bp in enumerate(c1_frames):
        wc_val = None
        if wc_frame:
            # WC monitor may output per-frame or summary; take last scalar
            wc_val = wc_frame.get("ref_relative_paired_fraction")
        records.append({
            "frame"      : i,
            "time_ns"    : (i + 1) * DCD_STEP_NS,
            "c1_fraction": bp.get("paired_fraction"),
            "wc_fraction": wc_val,
        })

    # Write cache
    PROD_HEALTH_CACHE.write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )
    return records

# ── Production log parser ──────────────────────────────────────────────────────

def parse_production_log() -> dict:
    """Extract latest elapsed ns, ns/day, step from NAMD PERFORMANCE lines."""
    result = {"elapsed_ns": 0.0, "ns_per_day": None, "step": 0}
    if not PROD_LOG.exists():
        return result
    text = PROD_LOG.read_text()
    for m in re.finditer(
        r"PERFORMANCE:\s+(\d+)\s+averaging\s+([\d.]+)\s+ns/day,\s+([\d.]+)\s+sec/step",
        text
    ):
        step, nsd, sps = int(m.group(1)), float(m.group(2)), float(m.group(3))
        result["step"]      = step
        result["elapsed_ns"] = step * 2e-6   # 2 fs/step → ns
        result["ns_per_day"] = nsd
    return result

# ── Phase band helpers ─────────────────────────────────────────────────────────

def k_color(k: float | None) -> str:
    if k is None or k == 0: return "#ffecd2"
    if k >= 10:             return "#dce9f5"
    if k >= 1:              return "#e8f0e8"
    return "#f5f0e8"

# ── Main plot ──────────────────────────────────────────────────────────────────

def make_plot(out_path: Path):
    # ── Load data ──────────────────────────────────────────────────────────────
    f020_stages = load_f020_stages()
    f020_health = load_f020_health()
    f020_xs, f020_c1, f020_wc, f020_ks, f020_oks = build_f020_series(f020_stages, f020_health)

    trans_health = load_f022_transition_health()
    prod_health  = load_f022_production_health()
    prod_stats   = parse_production_log()

    if len(f020_xs) == 0:
        print("No F020 health data found.")
        return

    # F020 endpoint in ps (right edge of left panel)
    f020_end_ps = float(f020_xs[-1]) if len(f020_xs) else 305.0
    # F022 transition occupies 0–50 ps of F022 time (shown in ns on right panel)
    TRANS_NS   = 0.05
    PROD_TOTAL_NS = 100.0

    # ── Figure: 3-row × 2-col grid ────────────────────────────────────────────
    # col 0: F020 (narrow); col 1: F022 (wide)
    # row 0: health metrics (tall); row 1: phase/k (medium); row 2: progress bar (thin)
    fig = plt.figure(figsize=(15, 8))
    gs  = fig.add_gridspec(
        3, 2,
        width_ratios=[1, 5],
        height_ratios=[3.5, 1, 0.35],
        hspace=0.06, wspace=0.04,
    )
    ax_m0 = fig.add_subplot(gs[0, 0])                         # F020 metrics
    ax_m1 = fig.add_subplot(gs[0, 1], sharey=ax_m0)           # F022 metrics
    ax_k0 = fig.add_subplot(gs[1, 0], sharex=ax_m0)           # F020 k-panel
    ax_k1 = fig.add_subplot(gs[1, 1])                          # F022 phase panel
    ax_pb = fig.add_subplot(gs[2, 1])                          # progress bar

    # ── F020: phase bands ──────────────────────────────────────────────────────
    prev_base, bands = None, []
    bdata: dict = {}
    for s in f020_stages:
        if s["name"] not in f020_health: break
        base = re.sub(r"_p\d+$", "", s["name"])
        if base != prev_base:
            if bdata:
                bands.append(bdata)
            bdata = {"x0": s["stage_start_ps"], "x1": s["checkpoint_ps"],
                     "k": s["k"], "temp": s["temp"]}
            prev_base = base
        else:
            bdata["x1"] = s["checkpoint_ps"]
    if bdata: bands.append(bdata)

    for b in bands:
        for ax in (ax_m0, ax_k0):
            ax.axvspan(b["x0"], b["x1"], color=k_color(b["k"]), alpha=0.55, zorder=0)

    # ── F020: thresholds + traces ──────────────────────────────────────────────
    ax_m0.axhline(90, color="#d44",    lw=1.0, ls="--", zorder=2)
    ax_m0.axhline(85, color="#e8860a", lw=1.0, ls=":",  zorder=2)
    ax_m0.plot(f020_xs, f020_c1, "o-", color="#1a6faf", lw=1.5, ms=4,
               label="C1'–C1' paired %", zorder=4)
    ax_m0.plot(f020_xs, f020_wc, "s-", color="#e06800", lw=1.5, ms=4,
               label="WC ref-relative %", zorder=4)
    failed = np.array([not ok for ok in f020_oks])
    if failed.any():
        ax_m0.scatter(f020_xs[failed], f020_c1[failed], marker="X",
                      s=80, color="red", zorder=5)

    # ── F020: k-panel ─────────────────────────────────────────────────────────
    k_vals = np.where(f020_ks == 0, 0.01, f020_ks)
    ax_k0.step(f020_xs, k_vals, where="post", color="#555", lw=1.5, zorder=3)
    ax_k0.fill_between(f020_xs, k_vals, step="post", alpha=0.15, color="#555")
    ax_k0.set_yscale("log")
    ax_k0.set_ylim(0.005, 30)
    ax_k0.set_yticks([0.05, 0.1, 0.5, 1, 5, 10, 20])
    ax_k0.set_yticklabels(["0.05","0.1","0.5","1","5","10","20"], fontsize=7)
    ax_k0.yaxis.set_minor_formatter(mticker.NullFormatter())
    ax_k0.set_ylabel("k (kcal/\nmol/Å²)", fontsize=8)
    ax_k0.grid(axis="y", ls=":", lw=0.5, color="#aaa")

    # ── F022: health data ──────────────────────────────────────────────────────
    # Transition point
    if trans_health:
        tc1 = (trans_health.get("c1_fraction") or 0) * 100
        twc = (trans_health.get("wc_fraction") or 0) * 100
        ax_m1.axvspan(0, TRANS_NS, color="#e0f0e0", alpha=0.5, zorder=0)
        ax_m1.scatter([TRANS_NS], [tc1], marker="o", color="#1a6faf", s=55, zorder=5,
                      label="C1' transition")
        ax_m1.scatter([TRANS_NS], [twc], marker="s", color="#e06800", s=55, zorder=5,
                      label="WC transition")

    # Production health points
    if prod_health:
        px = np.array([r["time_ns"] + TRANS_NS for r in prod_health])
        pc1 = np.array([(r["c1_fraction"] or 0) * 100 for r in prod_health])
        pwc = np.array([(r["wc_fraction"] or 0) * 100 for r in prod_health])
        ax_m1.plot(px, pc1, "o-", color="#1a6faf", lw=1.5, ms=4,
                   label="C1'–C1' paired %", zorder=4)
        ax_m1.plot(px, pwc, "s-", color="#e06800", lw=1.5, ms=4,
                   label="WC ref-relative %", zorder=4)

    # Thresholds
    ax_m1.axhline(90, color="#d44",    lw=1.0, ls="--", zorder=2, label="C1' threshold 90%")
    ax_m1.axhline(85, color="#e8860a", lw=1.0, ls=":",  zorder=2, label="WC threshold 85%")

    # Production elapsed region
    elapsed_ns = prod_stats["elapsed_ns"] + TRANS_NS
    if elapsed_ns > TRANS_NS:
        ax_m1.axvspan(TRANS_NS, elapsed_ns, color="#d8f0d8", alpha=0.25, zorder=0)

    # ── F022: phase panel ──────────────────────────────────────────────────────
    ax_k1.axvspan(0, TRANS_NS, color="#c8e8c8", alpha=0.6, zorder=0)
    ax_k1.text(TRANS_NS / 2, 0.5, "ENM\nNVT\ntransition",
               ha="center", va="center", fontsize=7, color="#444",
               transform=ax_k1.get_xaxis_transform())
    ax_k1.axvspan(TRANS_NS, PROD_TOTAL_NS, color="#d8ead8", alpha=0.35, zorder=0)
    ax_k1.text((TRANS_NS + PROD_TOTAL_NS) / 2, 0.5,
               "ENM-permanent production  (k=0.1 kcal/mol/Å², no positional restraints)",
               ha="center", va="center", fontsize=8, color="#2a5a2a",
               transform=ax_k1.get_xaxis_transform())
    ax_k1.set_yticks([])
    ax_k1.set_ylabel("phase", fontsize=8)

    # ── Progress bar ──────────────────────────────────────────────────────────
    prod_elapsed = prod_stats["elapsed_ns"]
    frac = min(prod_elapsed / PROD_TOTAL_NS, 1.0)
    ax_pb.barh(0, frac * PROD_TOTAL_NS, height=0.8, color="#4a9a4a", alpha=0.75)
    ax_pb.barh(0, PROD_TOTAL_NS, height=0.8, color="none",
               edgecolor="#888", lw=0.8)
    nsd = prod_stats["ns_per_day"]
    remaining = (PROD_TOTAL_NS - prod_elapsed) / nsd if nsd else None
    label = (
        f"{prod_elapsed:.2f} / {PROD_TOTAL_NS:.0f} ns"
        + (f"  ·  {nsd:.2f} ns/day  ·  ~{remaining:.0f} days remaining" if remaining else "")
    )
    ax_pb.text(0.02, 0, label, va="center", fontsize=8, color="#222",
               transform=ax_pb.get_yaxis_transform())
    ax_pb.set_xlim(0, PROD_TOTAL_NS)
    ax_pb.set_yticks([])
    ax_pb.set_xlabel("Production progress (ns)", fontsize=8)
    ax_pb.tick_params(axis="x", labelsize=7)

    # ── Axis limits and formatting ─────────────────────────────────────────────
    ax_m0.set_xlim(0, f020_end_ps * 1.03)
    ax_m0.set_ylim(82, 100.5)
    ax_m0.set_ylabel("Base-pair retention (%)", fontsize=10)
    ax_m0.set_xlabel("F020 sim. time (ps)", fontsize=8)
    ax_m0.tick_params(labelsize=8)
    ax_m0.grid(ls=":", lw=0.5, color="#ccc")
    ax_m0.yaxis.set_major_locator(mticker.MultipleLocator(2))

    ax_m1.set_xlim(0, PROD_TOTAL_NS)
    ax_m1.set_xlabel("F022 sim. time (ns)", fontsize=8)
    ax_m1.tick_params(axis="both", labelsize=8)
    ax_m1.tick_params(axis="y", labelleft=False)
    ax_m1.grid(ls=":", lw=0.5, color="#ccc")

    ax_k0.set_xlabel("F020 sim. time (ps)", fontsize=8)
    ax_k0.tick_params(labelsize=7)
    ax_k0.grid(axis="x", ls=":", lw=0.5, color="#ccc")

    ax_k1.set_xlim(0, PROD_TOTAL_NS)
    ax_k1.tick_params(labelsize=7)

    # ── Break marks (// between panels) ───────────────────────────────────────
    d = 0.012
    kw = dict(transform=fig.transFigure, color="#666", lw=1.2, clip_on=False)
    # Get panel boundary x in figure coords
    ax_m0_pos = ax_m0.get_position()
    x_break = ax_m0_pos.x1
    for y in [0.25, 0.75]:
        fig.lines.extend([
            plt.Line2D([x_break - d, x_break + d],
                       [y - d * 1.5, y + d * 1.5], **kw),
        ])

    # ── Stats and legend ───────────────────────────────────────────────────────
    n_pass  = sum(f020_oks)
    n_total = len(f020_oks)
    status_color = "#2a7a2a" if n_pass == n_total else "#d44"
    status_text = (
        f"F020: {n_total} checkpoints ({n_pass} pass, {n_total - n_pass} fail)\n"
        f"F022 production: {prod_elapsed:.3f} ns elapsed\n"
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    )
    ax_m1.text(0.99, 0.97, status_text, transform=ax_m1.transAxes,
               ha="right", va="top", fontsize=8,
               bbox=dict(boxstyle="round,pad=0.4", fc="white", ec=status_color, lw=1.2),
               color="#222", fontfamily="monospace")

    legend_lines = ax_m0.get_lines()[:2]
    legend_patches = [
        mpatches.Patch(color="#dce9f5", alpha=0.8, label="k ≥ 10"),
        mpatches.Patch(color="#e8f0e8", alpha=0.8, label="1 ≤ k < 10"),
        mpatches.Patch(color="#f5f0e8", alpha=0.8, label="k < 1"),
        mpatches.Patch(color="#d8ead8", alpha=0.8, label="ENM-permanent"),
        mpatches.Patch(color="#e0e0e0", alpha=0.6, label="planned"),
        plt.Line2D([0],[0], ls="--", color="#d44",    lw=1.0, label="C1' threshold 90%"),
        plt.Line2D([0],[0], ls=":",  color="#e8860a", lw=1.0, label="WC threshold 85%"),
    ]
    ax_m0.legend(handles=legend_lines + legend_patches,
                 loc="lower left", fontsize=7, framealpha=0.9, ncol=2)

    # ── Titles ────────────────────────────────────────────────────────────────
    fig.suptitle(
        "B_tube DNA origami — full pipeline health  "
        "(CHARMM36 · TIP3P · MGH · NAMD 3.0.2)",
        fontsize=12, y=0.99,
    )
    ax_m0.set_title("F020  k=20→k=4 ladder  (1 fs NPT)", fontsize=9, pad=4)
    ax_m1.set_title("F022  ENM-permanent production  (2 fs NPT, +p14 pinned)", fontsize=9, pad=4)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")
    print(f"  F020: {n_total} checkpoints | F022: {prod_elapsed:.3f} ns elapsed "
          f"| {nsd:.3f} ns/day" if nsd else "")

# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help="Output PNG path")
    args = ap.parse_args()
    make_plot(args.out)

if __name__ == "__main__":
    main()
