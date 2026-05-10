"""
base_pairing.py — Base pair integrity analysis for the periodic cell MD run.

Measures C1'...C1' inter-strand distance for each base pair over the DCD
trajectory as a proxy for Watson-Crick pairing integrity.  In canonical
B-DNA the C1'...C1' distance is ~10.4 Å; values > 13 Å indicate melted or
severely distorted pairs.

Approach
--------
1. Identify the 504 base-pair partners from the static PDB: for each C1'
   atom, find the nearest C1' atom on a *different* strand within [8.5, 13] Å.
   (Same-strand neighbours are always < 7 Å; cross-strand paired bases are
   ~10–11 Å; unpaired contacts are > 13 Å.)
2. Track those paired distances for every DCD frame.
3. Compute fraction of pairs with d < PAIRED_MAX per frame and plot.

Usage
-----
    python experiments/exp23_periodic_cell_benchmark/base_pairing.py [options]

Defaults to the exp23 run directory.  Safe to run while NAMD is writing
(reads a safe-capped subset of frames by default).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from scipy.spatial import cKDTree

import MDAnalysis as mda

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCRIPT = Path(__file__).parent
_RUN    = _SCRIPT / "results" / "periodic_cell_run"

DEFAULT_PSF = _RUN / "B_tube_periodic_1x.psf"
DEFAULT_PDB = _RUN / "B_tube_periodic_1x.pdb"
DEFAULT_DCD = _RUN / "output" / "B_tube_periodic_1x.dcd"
DEFAULT_OUT = _SCRIPT / "results" / "base_pairing.png"

# ── Pairing criteria ──────────────────────────────────────────────────────────

SEARCH_LO   =  8.5   # Å — minimum cross-strand C1'...C1' for a true pair
SEARCH_HI   = 13.0   # Å — maximum for initial pair identification
PAIRED_MAX  = 12.0   # Å — operational paired/melted threshold (runtime check)
STRIDE      =  1     # analyse every Nth frame (increase to speed up long runs)

# ── Step 1: identify base-pair partners from static PDB ──────────────────────

def _c1p_from_universe(u: mda.Universe):
    """Return an AtomGroup of all DNA C1' atoms."""
    sel = u.select_atoms("name C1'")
    if not len(sel):
        # Fallback for prime-char encoding issues in older MDAnalysis
        sel = u.select_atoms("name C1X")
    return sel


def build_pairs(pdb_path: Path, psf_path: Path) -> tuple[np.ndarray, np.ndarray, int]:
    """
    Identify base-pair partners from PDB coordinates.

    Returns
    -------
    idx_i, idx_j  : int arrays — MDAnalysis local indices into the C1' selection
    n_paired      : number of pairs found (expected: 504 for B_tube 1×)
    """
    u   = mda.Universe(str(psf_path), str(pdb_path))
    c1p = _c1p_from_universe(u)
    if not len(c1p):
        raise RuntimeError("No C1' atoms found — check PSF/PDB residue names.")

    pos    = c1p.positions                   # (N, 3) Å
    segids = c1p.atoms.segids                # MDAnalysis segment IDs
    n      = len(pos)

    print(f"C1' atoms found: {n}")
    unique_segs = np.unique(segids)
    print(f"Unique segments: {unique_segs.tolist()}")

    # Use k-d tree to find all pairs within SEARCH_HI
    tree   = cKDTree(pos)
    pairs_i, pairs_j = [], []
    used   = np.zeros(n, dtype=bool)

    # Greedy nearest-neighbour assignment on cross-strand pairs
    # (works because C1'...C1' pairing geometry is well-separated from stacking)
    for i in range(n):
        if used[i]:
            continue
        neighbors = tree.query_ball_point(pos[i], SEARCH_HI)
        cands = []
        for j in neighbors:
            if j <= i or used[j] or segids[j] == segids[i]:
                continue
            d = np.linalg.norm(pos[i] - pos[j])
            if d >= SEARCH_LO:
                cands.append((d, j))
        if not cands:
            continue
        cands.sort()
        j = cands[0][1]
        pairs_i.append(i)
        pairs_j.append(j)
        used[i] = used[j] = True

    idx_i = np.array(pairs_i, dtype=int)
    idx_j = np.array(pairs_j, dtype=int)
    print(f"Base pairs identified: {len(idx_i)}")

    if len(idx_i) == 0:
        raise RuntimeError(
            "No base pairs found.  Check SEARCH_LO/SEARCH_HI or residue naming."
        )

    # Sanity: distance distribution at frame 0
    d0 = np.linalg.norm(pos[idx_i] - pos[idx_j], axis=1)
    print(f"Initial C1'...C1' distances: "
          f"mean={d0.mean():.2f}  median={np.median(d0):.2f}  "
          f"min={d0.min():.2f}  max={d0.max():.2f}  (Å)")

    return idx_i, idx_j


# ── Step 2: iterate DCD frames ────────────────────────────────────────────────

def analyse_trajectory(
    psf_path: Path,
    dcd_path: Path,
    idx_i: np.ndarray,
    idx_j: np.ndarray,
    stride: int = STRIDE,
    safe_frames_back: int = 3,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    For each frame, compute per-pair C1'...C1' distances and aggregate metrics.

    Returns (times_ns, frac_paired, mean_dist, pct10, pct90)
    """
    u   = mda.Universe(str(psf_path), str(dcd_path))
    c1p = _c1p_from_universe(u)

    n_frames  = len(u.trajectory)
    safe_end  = max(1, n_frames - safe_frames_back)
    dt_ps     = u.trajectory.dt   # MDAnalysis in ps
    if dt_ps <= 0:
        # Fall back: estimate from total frames / ~13.47 ns
        dt_ps = 13_470.0 / n_frames
        print(f"  ⚠ DCD dt unset; using estimated dt = {dt_ps:.3f} ps/frame")
    else:
        print(f"  DCD dt = {dt_ps:.3f} ps/frame  ({n_frames} total frames, "
              f"safe cap at frame {safe_end})")

    times, frac_p, mean_d, p10, p90 = [], [], [], [], []

    for ts in u.trajectory[0:safe_end:stride]:
        pos  = c1p.positions
        diff = pos[idx_i] - pos[idx_j]

        # Minimum-image correction for orthogonal PBC (wrapAll on in NAMD)
        box = ts.dimensions  # [lx, ly, lz, alpha, beta, gamma]
        if box is not None and len(box) >= 3:
            L = box[:3]
            diff -= L * np.round(diff / L)

        d    = np.sqrt((diff * diff).sum(axis=1))

        times.append(ts.frame * dt_ps * 1e-3)   # ns
        frac_p.append((d < PAIRED_MAX).mean())
        mean_d.append(d.mean())
        p10.append(np.percentile(d, 10))
        p90.append(np.percentile(d, 90))

        if ts.frame % 100 == 0:
            print(f"  frame {ts.frame:5d}  t={times[-1]:.4f} ns  "
                  f"paired={frac_p[-1]*100:.1f}%  mean_d={mean_d[-1]:.2f} Å")

    return (np.array(times), np.array(frac_p),
            np.array(mean_d), np.array(p10), np.array(p90))


# ── Step 3: plot ──────────────────────────────────────────────────────────────

def _running_mean(x: np.ndarray, w: int) -> np.ndarray:
    if w <= 1 or len(x) < w:
        return x
    return np.convolve(x, np.ones(w) / w, mode="same")


def make_figure(
    times_ns: np.ndarray,
    frac_paired: np.ndarray,
    mean_dist: np.ndarray,
    p10: np.ndarray,
    p90: np.ndarray,
    n_pairs: int,
    out_path: Path,
) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

    smooth_w = max(1, len(times_ns) // 50)
    last_t   = float(times_ns[-1]) if len(times_ns) else 0.0
    last_f   = float(frac_paired[-1]) if len(frac_paired) else 0.0

    fig.suptitle(
        f"B_tube periodic cell — base pair integrity over {last_t:.3f} ns\n"
        f"({n_pairs} C1'…C1' pairs; PAIRED_MAX = {PAIRED_MAX:.1f} Å; "
        f"final paired fraction = {last_f*100:.1f}%)",
        fontsize=12, fontweight="bold",
    )

    # ── Panel 1: fraction paired ──────────────────────────────────────────────
    ax = axes[0]
    ax.plot(times_ns, frac_paired * 100, color="tab:blue", alpha=0.3,
            linewidth=0.8, label="raw")
    ax.plot(times_ns, _running_mean(frac_paired, smooth_w) * 100, color="tab:blue",
            linewidth=2.0, label=f"running mean (w={smooth_w})")
    ax.axhline(100, color="green", linestyle="--", linewidth=1.0, alpha=0.5,
               label="100% paired (ideal)")
    ax.set_ylabel("Base pairs intact (%)")
    ax.set_ylim(-5, 105)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    _annotate(ax, f"final: {last_f*100:.1f}%  mean: {frac_paired.mean()*100:.1f}%")

    # ── Panel 2: C1'…C1' distances ────────────────────────────────────────────
    ax = axes[1]
    ax.fill_between(times_ns, p10, p90, alpha=0.2, color="tab:orange",
                    label=f"10–90th pct")
    ax.plot(times_ns, mean_dist, color="tab:orange", alpha=0.35,
            linewidth=0.8, label="mean raw")
    ax.plot(times_ns, _running_mean(mean_dist, smooth_w), color="tab:orange",
            linewidth=2.0, label="mean smooth")
    ax.axhline(10.4, color="green", linestyle="--", linewidth=1.0, alpha=0.6,
               label="ideal B-DNA (10.4 Å)")
    ax.axhline(PAIRED_MAX, color="red", linestyle=":", linewidth=1.0, alpha=0.6,
               label=f"paired threshold ({PAIRED_MAX:.0f} Å)")
    ax.set_xlabel("Time (ns)")
    ax.set_ylabel("C1'…C1' distance (Å)")
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.xaxis.set_major_formatter(ticker.FormatStrFormatter("%.3f"))

    plt.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def _annotate(ax, text: str) -> None:
    ax.text(0.02, 0.05, text, transform=ax.transAxes, fontsize=9,
            verticalalignment="bottom",
            bbox=dict(boxstyle="round,pad=0.3", facecolor="white", alpha=0.8))


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Base pair integrity analysis")
    p.add_argument("--psf", type=Path, default=DEFAULT_PSF)
    p.add_argument("--pdb", type=Path, default=DEFAULT_PDB)
    p.add_argument("--dcd", type=Path, default=DEFAULT_DCD)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--stride", type=int, default=STRIDE,
                   help="Analyse every Nth frame (default 1 = all frames)")
    p.add_argument("--safe-back", type=int, default=3,
                   help="Skip last N frames (avoid partial writes from live simulation)")
    args = p.parse_args()

    for path, label in [(args.psf, "PSF"), (args.pdb, "PDB"), (args.dcd, "DCD")]:
        if not path.exists():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            sys.exit(1)

    print("=== Base pair identification ===")
    idx_i, idx_j = build_pairs(args.pdb, args.psf)
    n_pairs = len(idx_i)

    print("\n=== Trajectory analysis ===")
    times, frac, mean_d, p10, p90 = analyse_trajectory(
        args.psf, args.dcd, idx_i, idx_j,
        stride=args.stride, safe_frames_back=args.safe_back,
    )

    print(f"\n=== Summary ===")
    print(f"Frames analysed : {len(times)}")
    print(f"Time range      : {times[0]:.4f} – {times[-1]:.4f} ns")
    print(f"Paired fraction : {frac.mean()*100:.1f}% mean,  {frac[-1]*100:.1f}% final")
    print(f"Mean C1'…C1'    : {mean_d.mean():.2f} Å mean,  {mean_d[-1]:.2f} Å final")

    make_figure(times, frac, mean_d, p10, p90, n_pairs, args.out)


if __name__ == "__main__":
    main()
