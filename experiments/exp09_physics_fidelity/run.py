"""
Exp09 — Physics render speed vs structural fidelity.

Goal: characterise the trade-off between XPBD substeps/frame (render speed)
and structural quality (B-DNA constraint satisfaction) across 3 design sizes.

Metrics:
  - render_fps:         achieved frames per second (1 / wall-time per xpbd_step call)
  - bond_rmsd:          RMS deviation of backbone bond lengths from rest lengths (nm)
  - second_bond_rmsd:   RMS deviation of 2nd-neighbor bonds from rest (nm)
  - bp_rmsd:            RMS deviation of base-pair bonds from rest (nm)
  - stacking_rmsd:      RMS deviation of stacking bonds from rest (nm)
  - total_energy:       sum of squared constraint violations (see sim_energy)

Protocol:
  For each design size × substep count:
    1. Build SimState with noise_amplitude=0.04 nm (moderate thermal motion).
    2. Run 100 warm-up steps (discarded).
    3. Run 100 timed steps, record wall time + structural metrics.
    4. Report mean fps and mean structural metrics.

Hypothesis:
  - fps drops linearly with n_substeps (each substep applies all constraint passes).
  - bond_rmsd drops quickly with n_substeps (backbone is stiff).
  - bp_rmsd drops more slowly (base-pair bonds compete with thermal noise).
  - A good operating point balances fps ≥ 10 with bond_rmsd < 0.02 nm.
"""

import sys
import json
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.core.lattice import make_bundle_design, make_autostaple, make_nicks_for_autostaple
from backend.core.models import Direction
from backend.physics.xpbd import build_simulation, xpbd_step, sim_energy

# ── Design configurations ─────────────────────────────────────────────────────

# Small: 4-helix square (4 cells), 42 bp — fast sanity check
CELLS_SMALL = [(0, 0), (0, 1), (1, 0), (1, 2)]

# Medium: 18HB, 84 bp — typical working design
CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

# Large: 18HB, 252 bp — stress test
DESIGNS = [
    ("small_4hb_42bp",   CELLS_SMALL, 42),
    ("medium_18hb_84bp", CELLS_18HB,  84),
    ("large_18hb_252bp", CELLS_18HB,  252),
]

SUBSTEP_COUNTS = [1, 2, 5, 10, 20, 40]

WARMUP_STEPS  = 50
MEASURE_STEPS = 100
NOISE_AMP     = 0.04   # nm — moderate thermal motion


# ── Bond RMSD helpers ─────────────────────────────────────────────────────────

def _bond_rmsd(pos: np.ndarray, ij: np.ndarray, rest: np.ndarray) -> float:
    if len(ij) == 0:
        return 0.0
    d    = pos[ij[:, 1]] - pos[ij[:, 0]]
    dist = np.linalg.norm(d, axis=1)
    return float(np.sqrt(np.mean((dist - rest) ** 2)))


def measure_fidelity(sim) -> dict:
    pos = sim.positions
    return {
        "bond_rmsd":     _bond_rmsd(pos, sim.bond_ij,          sim.bond_rest),
        "bend_rmsd":     _bond_rmsd(pos, sim.second_bond_ij,   sim.second_bond_rest),
        "bp_rmsd":       _bond_rmsd(pos, sim.bp_bond_ij,       sim.bp_bond_rest),
        "stacking_rmsd": _bond_rmsd(pos, sim.stacking_bond_ij, sim.stacking_bond_rest),
        "total_energy":  sim_energy(sim),
    }


# ── Single experiment run ─────────────────────────────────────────────────────

def run_single(cells, length_bp: int, n_substeps: int) -> dict:
    # Build design with autostaple (full pipeline)
    design = make_bundle_design(cells, length_bp=length_bp)
    design = make_autostaple(design, min_end_margin=9)
    design = make_nicks_for_autostaple(design)

    # Build geometry dict (minimal — just backbone positions)
    from backend.core.geometry import nucleotide_positions
    geometry = []
    for helix in design.helices:
        for nuc in nucleotide_positions(helix):
            geometry.append({
                "helix_id":         helix.id,
                "bp_index":         nuc.bp_index,
                "direction":        nuc.direction.value,
                "backbone_position": list(nuc.position),
            })

    sim = build_simulation(design, geometry)
    sim.noise_amplitude = NOISE_AMP
    n_particles = len(sim.positions)

    # Warm-up
    for _ in range(WARMUP_STEPS):
        xpbd_step(sim, n_substeps=n_substeps)

    # Measurement
    times = []
    metrics_list = []
    for _ in range(MEASURE_STEPS):
        t0 = time.perf_counter()
        xpbd_step(sim, n_substeps=n_substeps)
        t1 = time.perf_counter()
        times.append(t1 - t0)
        metrics_list.append(measure_fidelity(sim))

    mean_ms  = float(np.mean(times)) * 1000
    mean_fps = 1.0 / float(np.mean(times))

    avg_metrics = {k: float(np.mean([m[k] for m in metrics_list]))
                   for k in metrics_list[0]}

    return {
        "n_particles": n_particles,
        "n_substeps":  n_substeps,
        "mean_ms":     mean_ms,
        "mean_fps":    mean_fps,
        **avg_metrics,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 70)
    print("Exp09 — Physics render speed vs structural fidelity")
    print("=" * 70)

    results = []

    for name, cells, length_bp in DESIGNS:
        print(f"\n{'─'*60}")
        print(f"Design: {name}  ({length_bp} bp)")
        print(f"{'substeps':>10}  {'fps':>8}  {'ms/step':>8}  "
              f"{'bond Δ':>8}  {'bp Δ':>8}  {'stack Δ':>8}  {'energy':>10}")
        print(f"{'─'*10}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*10}")

        design_results = []
        for n_sub in SUBSTEP_COUNTS:
            r = run_single(cells, length_bp, n_sub)
            r["design"] = name
            r["length_bp"] = length_bp
            results.append(r)
            design_results.append(r)

            print(
                f"{n_sub:>10}  {r['mean_fps']:>8.1f}  {r['mean_ms']:>8.2f}  "
                f"{r['bond_rmsd']*1000:>8.3f}  {r['bp_rmsd']*1000:>8.3f}  "
                f"{r['stacking_rmsd']*1000:>8.3f}  {r['total_energy']:>10.4f}"
            )

        # Find best operating point: fps >= 10 with lowest bond_rmsd
        viable = [r for r in design_results if r["mean_fps"] >= 10.0]
        if viable:
            best = min(viable, key=lambda r: r["bond_rmsd"])
            print(f"\n  → Best @ ≥10fps: {best['n_substeps']} substeps  "
                  f"({best['mean_fps']:.1f} fps, bond_rmsd={best['bond_rmsd']*1000:.3f} pm)")
        else:
            worst = min(design_results, key=lambda r: r["mean_ms"])
            print(f"\n  → No config achieves 10fps. Fastest: "
                  f"{worst['n_substeps']} substeps ({worst['mean_fps']:.1f} fps)")

    # Save results
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    with open(out / "metrics.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved → {out}/metrics.json")
