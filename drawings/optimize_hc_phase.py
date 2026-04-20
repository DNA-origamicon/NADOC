"""
Optimize honeycomb-lattice backbone phases to minimise backbone-bead distance
at p150 crossover sites (bp%21 ∈ {0, 20}).

Setup
-----
HC lattice with 6 helices at grid positions (0,1), (0,2), (1,2), (1,3)
(plus any additional neighbours needed to fill a 6hb model, but only the
two adjacent pairs matter for p150 crossovers):

    Pair 1: (0,2) FORWARD  ↔  (0,1) REVERSE   [col-adjacent, same row]
    Pair 2: (1,3) FORWARD  ↔  (1,2) REVERSE   [col-adjacent, same row]

Crossover bps in a 42bp model: {0, 20, 21, 41}  (period=21bp).

Two free parameters
-------------------
  phi_fwd : phase_offset [rad] at bp=0 for FORWARD helices (even parity)
  phi_rev : phase_offset [rad] at bp=0 for REVERSE helices (odd  parity)

At each crossover bp i between a FORWARD helix A and a REVERSE helix B,
the paired backbone beads are:

  Scaffold crossover:
    bead_A = cA + R · radial(phi_fwd + i·twist)           # FORWARD strand of A
    bead_B = cB + R · radial(phi_rev + i·twist + MGA)     # REVERSE  strand of B
  Staple crossover (same bp, antiparallel partner):
    bead_A = cA + R · radial(phi_fwd + i·twist + MGA)     # REVERSE  strand of A
    bead_B = cB + R · radial(phi_rev + i·twist)            # FORWARD  strand of B

where MGA = 150° (caDNAno minor-groove angle convention).

Objective: minimise sum of squared distances across all bead pairs at all
crossover bps in both pairs.

Strategy: coarse 1°×1° grid search → Nelder-Mead refinement.
"""

import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

# ── Constants (mirrors backend/core/constants.py) ─────────────────────────────
HC_R       = 1.125        # nm — caDNAno honeycomb lattice radius
HC_COL_PITCH = HC_R * math.sqrt(3)   # ≈ 1.9486 nm
HC_ROW_PITCH = 3.0 * HC_R             # = 3.375  nm
R          = 1.0          # nm — backbone bead radius from helix axis (HELIX_RADIUS)
TWIST      = math.radians(34.3)        # rad/bp — BDNA_TWIST_PER_BP_RAD
MGA        = math.radians(150.0)       # rad   — BDNA_MINOR_GROOVE_ANGLE_RAD

# Current caDNAno phase defaults (lattice.py _lattice_phase_offset)
CURRENT_FWD_DEG = 322.2
CURRENT_REV_DEG = 252.2

# p150 crossover base-pair indices in a 42bp model
XOVER_BPS = [0, 20, 21, 41]


# ── Lattice helpers ────────────────────────────────────────────────────────────

def hc_pos(row: int, col: int) -> np.ndarray:
    """XY centre of helix (row, col) on HC lattice, in nm."""
    odd = (row + col) % 2
    x = col * HC_COL_PITCH
    y = row * HC_ROW_PITCH + (HC_R if odd else 0.0)
    return np.array([x, y], dtype=float)


def radial(angle: float) -> np.ndarray:
    return np.array([math.cos(angle), math.sin(angle)])


def backbone(center: np.ndarray, phase: float, bp: int) -> np.ndarray:
    """XY backbone bead for the FORWARD strand of a helix."""
    return center + R * radial(phase + bp * TWIST)


# ── Crossover pairs ────────────────────────────────────────────────────────────
# Each pair: (center_fwd, center_rev)
# Parity rule: (row+col)%2==0 → FORWARD, else REVERSE

PAIRS = [
    (hc_pos(0, 2), hc_pos(0, 1)),   # (0,2) FORWARD  ↔  (0,1) REVERSE
    (hc_pos(1, 3), hc_pos(1, 2)),   # (1,3) FORWARD  ↔  (1,2) REVERSE
]


# ── Objective ─────────────────────────────────────────────────────────────────

def total_sq_distance(params) -> float:
    """Sum of squared backbone-bead distances at all p150 crossover sites."""
    phi_fwd, phi_rev = params
    total = 0.0

    for (cA, cB) in PAIRS:
        for i in XOVER_BPS:
            # Scaffold crossover: FORWARD strand of A  ↔  REVERSE strand of B
            bA_scaffold = backbone(cA, phi_fwd, i)
            bB_scaffold = backbone(cB, phi_rev + MGA, i)   # REVERSE = fwd + MGA
            d2 = float(np.sum((bA_scaffold - bB_scaffold) ** 2))
            total += d2

            # Staple crossover: REVERSE strand of A  ↔  FORWARD strand of B
            bA_staple = backbone(cA, phi_fwd + MGA, i)
            bB_staple = backbone(cB, phi_rev, i)
            d2 = float(np.sum((bA_staple - bB_staple) ** 2))
            total += d2

    return total


# ── Grid search ───────────────────────────────────────────────────────────────

def grid_search(step_deg: float = 1.0):
    angles = np.arange(0, 360, step_deg)
    best_cost = math.inf
    best = (0.0, 0.0)
    for fwd_deg in angles:
        for rev_deg in angles:
            cost = total_sq_distance((math.radians(fwd_deg), math.radians(rev_deg)))
            if cost < best_cost:
                best_cost = cost
                best = (fwd_deg, rev_deg)
    return best, best_cost


# ── Report ────────────────────────────────────────────────────────────────────

def report(phi_fwd: float, phi_rev: float, label: str = "") -> None:
    fwd_deg = math.degrees(phi_fwd) % 360
    rev_deg = math.degrees(phi_rev) % 360
    print(f"\n{'─'*60}")
    if label:
        print(f"  {label}")
    print(f"  phi_fwd = {fwd_deg:7.2f}°   phi_rev = {rev_deg:7.2f}°")

    total = 0.0
    for pair_idx, (cA, cB) in enumerate(PAIRS):
        pair_name = ["(0,2)↔(0,1)", "(1,3)↔(1,2)"][pair_idx]
        for i in XOVER_BPS:
            bA_s = backbone(cA, phi_fwd, i)
            bB_s = backbone(cB, phi_rev + MGA, i)
            d_scaffold = float(np.linalg.norm(bA_s - bB_s))

            bA_st = backbone(cA, phi_fwd + MGA, i)
            bB_st = backbone(cB, phi_rev, i)
            d_staple = float(np.linalg.norm(bA_st - bB_st))

            print(f"  {pair_name} bp={i:2d}  scaffold={d_scaffold:.4f} nm  "
                  f"staple={d_staple:.4f} nm")
            total += d_scaffold ** 2 + d_staple ** 2

    print(f"  Total squared distance: {total:.6f} nm²")
    print(f"{'─'*60}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("HC backbone phase optimisation")
    print(f"Constants: HC_R={HC_R} nm, R={R} nm, twist={math.degrees(TWIST):.2f}°/bp, "
          f"MGA={math.degrees(MGA):.0f}°")
    print(f"Crossover bps: {XOVER_BPS}")
    print(f"Helix pairs: {[(r'(0,2)↔(0,1)', '(1,3)↔(1,2)')][0]}")

    # Show current defaults
    report(math.radians(CURRENT_FWD_DEG), math.radians(CURRENT_REV_DEG),
           f"Current defaults: fwd={CURRENT_FWD_DEG}° rev={CURRENT_REV_DEG}°")

    # Coarse 1° grid search
    print("\nRunning 360×360 grid search …", end=" ", flush=True)
    (best_fwd_deg, best_rev_deg), grid_cost = grid_search(step_deg=1.0)
    print(f"done.  Best: fwd={best_fwd_deg:.0f}°  rev={best_rev_deg:.0f}°  "
          f"cost={grid_cost:.6f}")

    # Nelder-Mead refinement
    x0 = np.array([math.radians(best_fwd_deg), math.radians(best_rev_deg)])
    result = minimize(total_sq_distance, x0, method="Nelder-Mead",
                      options={"xatol": 1e-8, "fatol": 1e-12, "maxiter": 10_000})
    phi_fwd_opt, phi_rev_opt = result.x
    report(phi_fwd_opt, phi_rev_opt, "Optimised (Nelder-Mead)")

    fwd_opt_deg = math.degrees(phi_fwd_opt) % 360
    rev_opt_deg = math.degrees(phi_rev_opt) % 360
    print()
    print("Update in backend/core/lattice.py → _lattice_phase_offset():")
    print(f"  FORWARD: math.radians({fwd_opt_deg:.1f})")
    print(f"  REVERSE: math.radians({rev_opt_deg:.1f})")
    print()
    print("  (was: FORWARD=322.2°, REVERSE=252.2°)")


if __name__ == "__main__":
    main()
