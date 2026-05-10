"""
check_progress.py — Live health monitor for periodic cell NAMD production run.

Parses the NAMD log, extracts ENERGY lines, and writes a 4-panel PNG:
  • Temperature (K)
  • Potential energy (kcal/mol)
  • Pressure (bar)
  • Box volume (Å³)

Usage:
    python experiments/exp23_periodic_cell_benchmark/check_progress.py [--log PATH] [--out PATH]

Defaults:
    --log  experiments/exp23_periodic_cell_benchmark/results/production_namd.log
    --out  experiments/exp23_periodic_cell_benchmark/results/health_metrics.png

Safe to run while NAMD is running — reads the log as plain text (no locking).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

ROOT      = Path(__file__).parents[2]
RESULTS   = Path(__file__).parent / "results"
RUN_DIR   = RESULTS / "periodic_cell_run"
LOG_PATH  = RUN_DIR / "output" / "production_namd.log"
OUT_PATH  = RESULTS / "health_metrics.png"
BP_PATH   = RESULTS / "base_pairing_nvt.png"

TIMESTEP_FS = 2.0   # fs per NAMD step


# ── Parser ────────────────────────────────────────────────────────────────────

def _col_indices(etitle_line: str) -> dict[str, int]:
    """Return {field_name: 0-based index} from an ETITLE line."""
    fields = etitle_line.split()
    # fields[0] == "ETITLE:", fields[1..] are column names
    return {name: i - 1 for i, name in enumerate(fields) if i >= 1}


def parse_log(log_path: Path) -> dict[str, np.ndarray]:
    """Parse NAMD log; return arrays keyed by field name (MD steps only)."""
    col_idx: dict[str, int] = {}
    rows: list[list[float]] = []

    text = log_path.read_text(errors="replace")
    for line in text.splitlines():
        if line.startswith("ETITLE:"):
            col_idx = _col_indices(line)
        elif line.startswith("ENERGY:"):
            vals = line.split()[1:]   # strip "ENERGY:"
            try:
                row = [float(v) for v in vals]
            except ValueError:
                continue
            rows.append(row)

    if not rows or not col_idx:
        return {}

    arr = np.array(rows)

    # Skip minimisation steps (TEMP == 0)
    temp_col = col_idx.get("TEMP", 11)
    md_mask  = arr[:, temp_col] > 0
    if not md_mask.any():
        # All minimisation — still return to show what we have
        md_mask = np.ones(len(arr), dtype=bool)

    arr = arr[md_mask]
    return {name: arr[:, idx] for name, idx in col_idx.items() if idx < arr.shape[1]}


# ── Plots ─────────────────────────────────────────────────────────────────────

_TARGET = {
    "TEMP":     310.0,
    "PRESSURE": 1.01325,
}

def _running_mean(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) < w:
        return x
    kernel = np.ones(w) / w
    return np.convolve(x, kernel, mode="same")


def make_figure(data: dict[str, np.ndarray], out_path: Path, n_steps_total: int) -> None:
    ts      = data.get("TS",       np.array([]))
    time_ns = ts * TIMESTEP_FS * 1e-6

    panels = [
        ("TEMP",     "Temperature (K)",        "tab:red",    310.0),
        ("POTENTIAL","Potential energy (kcal/mol)", "tab:blue",  None),
        ("PRESSURE", "Pressure (bar)",          "tab:green",  1.01325),
        ("VOLUME",   "Volume (Å³)",             "tab:purple", None),
    ]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    axes = axes.flatten()

    sim_ns_done  = float(time_ns[-1]) if len(time_ns) else 0.0
    sim_ns_total = n_steps_total * TIMESTEP_FS * 1e-6
    pct_done     = 100.0 * sim_ns_done / sim_ns_total if sim_ns_total > 0 else 0.0
    n_frames     = len(ts)

    fig.suptitle(
        f"B_tube periodic cell production run\n"
        f"{sim_ns_done:.3f} / {sim_ns_total:.1f} ns  ({pct_done:.1f}%)  —  {n_frames:,} energy frames",
        fontsize=13, fontweight="bold",
    )

    smooth_w = max(1, n_frames // 100)   # ~1% of frames for running mean

    for ax, (field, ylabel, color, target) in zip(axes, panels):
        y = data.get(field)
        if y is None or len(y) == 0:
            ax.set_visible(False)
            continue

        ax.plot(time_ns, y, color=color, alpha=0.35, linewidth=0.6, label="raw")
        if len(y) >= 5:
            ax.plot(time_ns, _running_mean(y, smooth_w), color=color,
                    linewidth=1.6, label=f"mean (w={smooth_w})")
        if target is not None:
            ax.axhline(target, color="k", linestyle="--", linewidth=1.0,
                       alpha=0.6, label=f"target {target}")

        ax.set_xlabel("Time (ns)")
        ax.set_ylabel(ylabel)
        ax.legend(fontsize=8, loc="upper right")
        ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%.3f"))

        # Stats annotation
        mean_v = float(np.mean(y))
        std_v  = float(np.std(y))
        last_v = float(y[-1])
        ax.text(0.02, 0.04,
                f"mean={mean_v:.2f}  σ={std_v:.2f}  last={last_v:.2f}",
                transform=ax.transAxes, fontsize=8,
                verticalalignment="bottom",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.7))
        ax.grid(True, alpha=0.3)

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="NAMD periodic cell health monitor")
    parser.add_argument("--log", type=Path, default=LOG_PATH,
                        help="NAMD log file to parse")
    parser.add_argument("--out", type=Path, default=OUT_PATH,
                        help="Output PNG path")
    parser.add_argument("--prod-steps", type=int, default=25_000_000,
                        help="Total production steps (for progress %%)")
    parser.add_argument("--dcd", type=Path, default=RUN_DIR / "output" / "B_tube_periodic_1x.dcd",
                        help="DCD trajectory for optional base-pairing analysis")
    parser.add_argument("--bp-out", type=Path, default=BP_PATH,
                        help="Output PNG for base pairing plot")
    args = parser.parse_args()

    if not args.log.exists():
        print(f"Log not found: {args.log}", file=sys.stderr)
        sys.exit(1)

    data = parse_log(args.log)
    if not data:
        print("No ENERGY lines found yet (minimisation may still be running).")
        sys.exit(0)

    ts      = data.get("TS", np.array([]))
    time_ns = ts * TIMESTEP_FS * 1e-6
    sim_ns_done = float(time_ns[-1]) if len(time_ns) else 0.0

    print(f"Frames parsed : {len(ts):,}")
    print(f"Sim time done : {sim_ns_done:.4f} ns")
    print(f"Progress      : {100*sim_ns_done / (args.prod_steps*TIMESTEP_FS*1e-6):.2f}%")

    for field in ("TEMP", "POTENTIAL", "PRESSURE", "VOLUME"):
        y = data.get(field)
        if y is not None and len(y):
            print(f"  {field:<12}: mean={np.mean(y):>14.3f}  σ={np.std(y):>10.3f}  last={y[-1]:>14.3f}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    make_figure(data, args.out, args.prod_steps)

    # ── Base pairing check ────────────────────────────────────────────────────
    dcd = args.dcd
    psf = RUN_DIR / "B_tube_periodic_1x.psf"
    pdb = RUN_DIR / "B_tube_periodic_1x.pdb"
    if dcd.exists() and psf.exists() and pdb.exists():
        print(f"\nRunning base pairing analysis on {dcd} …")
        try:
            import importlib.util, sys as _sys
            _spec = importlib.util.spec_from_file_location(
                "base_pairing",
                Path(__file__).parent / "base_pairing.py",
            )
            _bp = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_bp)
            build_pairs       = _bp.build_pairs
            analyse_trajectory = _bp.analyse_trajectory
            bp_figure         = _bp.make_figure
            idx_i, idx_j = build_pairs(pdb, psf)
            times, frac, mean_d, p10, p90 = analyse_trajectory(
                psf, dcd, idx_i, idx_j, safe_frames_back=2
            )
            if len(times):
                bp_out = args.bp_out
                bp_out.parent.mkdir(parents=True, exist_ok=True)
                bp_figure(times, frac, mean_d, p10, p90, len(idx_i), bp_out)
        except Exception as e:
            print(f"  Base pairing analysis skipped: {e}")
    else:
        print(f"\nDCD not found yet — skipping base pairing ({dcd})")

    print(f"\nOutput PNGs:")
    print(f"  Health metrics : {args.out}")
    print(f"  Base pairing   : {args.bp_out}")


if __name__ == "__main__":
    main()
