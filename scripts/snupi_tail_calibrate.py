"""Calibrate the ssDNA tail chain's bending rigidity against the WLC — the source of
``snupi_material.SS_EI_DISCRETE_FACTOR`` (phase SS-2).

**Why a calibration is needed at all.**  The continuum identity ``EI = k_BT · L_p`` holds in the
limit where the discretisation is much finer than the persistence length.  An ssDNA tail is the
opposite regime: one bead per nucleotide gives a bond ``b = 0.68 nm`` while ssDNA's persistence
length is ``L_p = 0.67 nm``, so ``b/L_p ≈ 1.01`` — the chain is discretised AT its own persistence
length.  The discrete chain is therefore stiffer than the identity predicts, and the bending
rigidity has to be corrected so the chain's *emergent* statistics match real ssDNA.

**The method: PIVOT Monte Carlo.**  Sampling this by molecular dynamics is a trap.  A polymer's
long-wavelength bending modes relax orders of magnitude more slowly than its local bond angles, so
a Langevin run (or a local-move MC) converges ``⟨cos θ⟩`` quickly while leaving the global
conformation frozen near its starting shape.  The signature is unmistakable once you look for it:
the tangent correlation ``⟨u_i·u_{i+k}⟩`` PLATEAUS at a finite value instead of decaying to zero,
and ``⟨R_ee²⟩`` comes out several-fold too large.  (Both of those bit this phase before the pivot
sampler was written; see memory/project_snupi_ssdna.md, SS-2.)

A pivot move rotates every node beyond node ``i`` — positions AND triads — rigidly about node ``i``.
Because the corotational energy is frame-indifferent, everything beyond the pivot moves rigidly and
its energy is unchanged: exactly ONE element, ``(i, i+1)``, changes energy.  So the move is O(1) to
evaluate and it decorrelates the global conformation in a handful of moves.  With it, the tangent
correlation decays to zero as a worm-like chain must, and ``⟨R_ee²⟩`` converges.

Run:  uv run python scripts/snupi_tail_calibrate.py
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.physics.snupi_material import (        # noqa: E402
    SS_CONTOUR_PER_NT,
    SS_PERSISTENCE_NM,
)
from backend.physics.snupi_tails import (        # noqa: E402
    pivot_sample_chain,
    wlc_mean_square_end_to_end,
)

KT = 4.142
B = SS_CONTOUR_PER_NT


def lp_from_r2(r2: float, n: int, b: float = B) -> float:
    """Invert the WLC ⟨R²⟩(L_p) relation for L_p (monotone → bisection)."""
    lo, hi = 1e-4, 100.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if wlc_mean_square_end_to_end(n, l_p=mid, b=b) < r2:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _mean_lp(n_bond: int, ei: float, seeds: int, sweeps: int) -> tuple[float, float, np.ndarray]:
    """⟨R²⟩-derived L_p averaged over independent seeds, + its standard error + the tangent decay."""
    runs = [pivot_sample_chain(n_bond, ei, n_sweep=sweeps, seed=s) for s in range(seeds)]
    r2s = np.array([r["r2"] for r in runs])
    lps = np.array([lp_from_r2(float(r["r2"]), n_bond) for r in runs])
    sem = float(lps.std(ddof=1) / math.sqrt(seeds)) if seeds > 1 else 0.0
    return float(lps.mean()), sem, np.mean([r["corr"] for r in runs], axis=0), float(r2s.mean())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sweeps", type=int, default=20000)
    ap.add_argument("--seeds", type=int, default=3)
    args = ap.parse_args()

    ei0 = KT * SS_PERSISTENCE_NM
    print(f"continuum identity: EI = k_BT·L_p = {ei0:.4f} pN·nm²  (assumes b << L_p)")
    print(f"reality:            b = {B} nm, L_p = {SS_PERSISTENCE_NM} nm"
          f"  ->  b/L_p = {B/SS_PERSISTENCE_NM:.2f}   (nowhere near the continuum limit)")
    print(f"sampler: pivot MC, {args.sweeps} sweeps x {args.seeds} seeds\n")

    print("── scan: emergent L_p of the discrete chain vs its bending rigidity (n = 16) ──")
    print(f"{'EI':>7} {'factor':>7} | {'<R2>':>8} {'L_p,eff':>8} {'±sem':>6} | <u·u>(k=1,2,4,8)")
    xs, ys = [], []
    for factor in (1.0, 0.8, 0.65, 0.5, 0.4):
        lp, sem, c, r2 = _mean_lp(16, ei0 * factor, args.seeds, args.sweeps)
        xs.append(factor)
        ys.append(lp)
        print(f"{ei0*factor:7.3f} {factor:7.2f} | {r2:8.3f} {lp:8.3f} {sem:6.3f} | "
              f"{c[1]:6.3f} {c[2]:6.3f} {c[4]:6.3f} {c[8]:6.3f}")

    # Least squares on L_p(factor) — the scan is MC-noisy, so fit the trend rather than
    # interpolating between two points (which is what an earlier pass did, and it was unstable).
    A = np.vstack([np.array(xs), np.ones(len(xs))]).T
    slope, intercept = np.linalg.lstsq(A, np.array(ys), rcond=None)[0]
    best = (SS_PERSISTENCE_NM - intercept) / slope
    resid = np.array(ys) - (slope * np.array(xs) + intercept)
    print(f"\nfit: L_p,eff = {slope:.4f}·factor + {intercept:.4f}   (residual rms {resid.std():.4f} nm)")
    print(f"-> SS_EI_DISCRETE_FACTOR reproducing L_p = {SS_PERSISTENCE_NM} nm:  {best:.3f}")
    print(f"   i.e. EI = {ei0*best:.3f} pN·nm²  ({1/best:.2f}x softer than the continuum identity)")

    print("\n── verification at the calibrated factor, across VoltronCore's real tail lengths ──")
    print(f"{'n_nt':>5} | {'<R2> sim':>9} {'<R2> WLC':>9} {'L_p,eff':>8} {'err':>7}")
    for n in (3, 8, 12, 16, 28):
        lp, _sem, _c, r2 = _mean_lp(n, ei0 * best, args.seeds, args.sweeps)
        wlc = wlc_mean_square_end_to_end(n)
        print(f"{n:5d} | {r2:9.3f} {wlc:9.3f} {lp:8.3f} {(r2-wlc)/wlc:+6.1%}")


if __name__ == "__main__":
    main()
