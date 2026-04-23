#!/usr/bin/env python3
"""Check production run progress and write progress.png."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np


def _read_xvg(path: Path) -> tuple[np.ndarray, np.ndarray]:
    times, vals = [], []
    for line in path.read_text().splitlines():
        if line.startswith(("#", "@")):
            continue
        parts = line.split()
        if len(parts) >= 2:
            times.append(float(parts[0]))
            vals.append(float(parts[1]))
    return np.array(times), np.array(vals)


def _gmx_energy(edr: Path, term: str, out: Path) -> tuple[np.ndarray, np.ndarray] | None:
    r = subprocess.run(
        ["gmx", "energy", "-f", str(edr), "-o", str(out)],
        input=f"{term}\n0\n",
        capture_output=True, text=True,
    )
    if r.returncode != 0 or not out.exists():
        return None
    return _read_xvg(out)


def _xtc_frame_count(xtc: Path) -> int:
    r = subprocess.run(
        ["gmx", "check", "-f", str(xtc)],
        capture_output=True, text=True,
    )
    for line in r.stderr.splitlines() + r.stdout.splitlines():
        if "Step" in line and "#frames" in line:
            continue
        if line.strip().startswith("Step"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    pass
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", nargs="?",
                        default="runs/crossover_parameterization/T0/nominal_c36")
    parser.add_argument("-o", "--output", default=None,
                        help="Output PNG path (default: <run_dir>/progress.png)")
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    edr = run_dir / "prod.edr"
    xtc = run_dir / "prod.xtc"
    out_png = Path(args.output) if args.output else run_dir / "progress.png"

    if not edr.exists():
        sys.exit(f"No prod.edr in {run_dir} — simulation not started?")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)

        temp_data   = _gmx_energy(edr, "Temperature",   tmpdir / "temp.xvg")
        epot_data   = _gmx_energy(edr, "Potential",     tmpdir / "epot.xvg")
        press_data  = _gmx_energy(edr, "Pressure",      tmpdir / "press.xvg")
        dens_data   = _gmx_energy(edr, "Density",       tmpdir / "dens.xvg")

    # Progress from XTC frames
    n_frames = _xtc_frame_count(xtc) if xtc.exists() else 0
    dt_ps = 20.0  # production write interval
    sim_ns = n_frames * dt_ps / 1000.0
    total_ns = 200.0
    pct = 100.0 * sim_ns / total_ns

    # Figure
    fig = plt.figure(figsize=(12, 8))
    fig.suptitle(
        f"T0 CHARMM36 production — {sim_ns:.1f} / {total_ns:.0f} ns  ({pct:.1f}%)",
        fontsize=13, fontweight="bold",
    )

    gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.4, wspace=0.35)

    panels = [
        (temp_data,  "Temperature (K)",   "tab:red",   gs[0, 0]),
        (epot_data,  "Potential (kJ/mol)", "tab:blue",  gs[0, 1]),
        (press_data, "Pressure (bar)",     "tab:green", gs[1, 0]),
        (dens_data,  "Density (kg/m³)",    "tab:purple",gs[1, 1]),
    ]

    for data, ylabel, color, gpos in panels:
        ax = fig.add_subplot(gpos)
        if data is not None:
            t_ns = data[0] / 1000.0
            ax.plot(t_ns, data[1], color=color, linewidth=0.6, alpha=0.8)
            # running mean
            if len(data[1]) > 50:
                w = max(1, len(data[1]) // 50)
                rm = np.convolve(data[1], np.ones(w)/w, mode="valid")
                ax.plot(t_ns[w-1:], rm, color="black", linewidth=1.2)
        ax.set_xlabel("Time (ns)")
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)

    # Progress bar at bottom
    ax_bar = fig.add_axes([0.1, 0.02, 0.8, 0.025])
    ax_bar.barh(0, pct, height=1, color="steelblue")
    ax_bar.barh(0, 100 - pct, left=pct, height=1, color="lightgrey")
    ax_bar.set_xlim(0, 100)
    ax_bar.set_yticks([])
    ax_bar.set_xlabel(f"Progress: {pct:.1f}%")

    fig.savefig(str(out_png), dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Wrote {out_png}")
    print(f"  XTC frames : {n_frames}  ({sim_ns:.1f} ns / {total_ns:.0f} ns = {pct:.1f}%)")
    if temp_data is not None:
        print(f"  Temperature: {temp_data[1][-1]:.1f} K (last frame)")
    if epot_data is not None:
        print(f"  Potential  : {epot_data[1][-1]:.0f} kJ/mol (last frame)")


if __name__ == "__main__":
    main()
