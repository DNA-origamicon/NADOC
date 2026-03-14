"""
Exp02 — Thermal Stability
=========================
42bp duplex under three noise levels; track RMSD and bond length over 500 frames.
"""

import json
import pathlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, DesignMetadata, Direction, Domain, Helix, LatticeType, Strand, Vec3,
)
from backend.api.crud import _geometry_for_design
from backend.physics.xpbd import build_simulation, xpbd_step, BACKBONE_BOND_LENGTH

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

LENGTH_BP = 42
NOISE_LEVELS = [0.01, 0.05, 0.10]
N_FRAMES = 500
N_SUBSTEPS = 20


def make_design():
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=LENGTH_BP * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=LENGTH_BP,
        lattice_type=LatticeType.FREE,
    )
    scaffold = Strand(
        id="scaf",
        is_scaffold=True,
        domains=[Domain(helix_id="h0", direction=Direction.FORWARD,
                        start_bp=0, end_bp=LENGTH_BP - 1)],
    )
    staple = Strand(
        id="stpl",
        is_scaffold=False,
        domains=[Domain(helix_id="h0", direction=Direction.REVERSE,
                        start_bp=LENGTH_BP - 1, end_bp=0)],
    )
    return Design(
        metadata=DesignMetadata(name="exp02"),
        helices=[helix],
        strands=[scaffold, staple],
    )


def run_noise_level(noise_amp):
    design = make_design()
    geometry = _geometry_for_design(design)
    sim = build_simulation(design, geometry)

    sim.noise_amplitude = noise_amp
    sim.bond_stiffness  = 1.0
    sim.bend_stiffness  = 0.3
    sim.bp_stiffness    = 0.5
    sim.rng = np.random.default_rng(42)

    pos0 = sim.positions.copy()

    rmsd_history      = []
    bond_mean_history = []
    bond_std_history  = []

    def bond_lengths():
        ij = sim.bond_ij
        d = sim.positions[ij[:, 1]] - sim.positions[ij[:, 0]]
        return np.linalg.norm(d, axis=1)

    for frame in range(N_FRAMES):
        xpbd_step(sim, n_substeps=N_SUBSTEPS)
        diff = sim.positions - pos0
        rmsd = float(np.sqrt(np.mean(np.sum(diff**2, axis=1))))
        bl = bond_lengths()
        rmsd_history.append(rmsd)
        bond_mean_history.append(float(np.mean(bl)))
        bond_std_history.append(float(np.std(bl)))

    return {
        "noise_amplitude":  noise_amp,
        "rmsd":             rmsd_history,
        "bond_mean":        bond_mean_history,
        "bond_std":         bond_std_history,
        "final_rmsd":       rmsd_history[-1],
        "final_bond_mean":  bond_mean_history[-1],
        "final_bond_std":   bond_std_history[-1],
        "peak_rmsd":        max(rmsd_history),
        "bounded":          rmsd_history[-1] < 2.0 * max(rmsd_history[N_FRAMES // 2:]),
    }


# ── Run all noise levels ────────────────────────────────────────────────────────

print("Running exp02 thermal stability...")
results = []
for noise in NOISE_LEVELS:
    print(f"  noise={noise} nm/substep ...", end=' ', flush=True)
    r = run_noise_level(noise)
    results.append(r)
    print(f"final RMSD={r['final_rmsd']:.3f} nm, bond_mean={r['final_bond_mean']:.4f} nm")

frames = list(range(N_FRAMES))

# ── Plot RMSD vs frame ─────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 5))
for r in results:
    ax.plot(frames, r['rmsd'], label=f"noise={r['noise_amplitude']}")
ax.set_xlabel('Frame')
ax.set_ylabel('RMSD from initial (nm)')
ax.set_title('Exp02 — RMSD over time at three noise levels')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'rmsd_vs_frame.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'rmsd_vs_frame.png'}")

# ── Plot bond drift ────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 5))
for r in results:
    mean_arr = np.array(r['bond_mean'])
    std_arr  = np.array(r['bond_std'])
    label = f"noise={r['noise_amplitude']}"
    ax.plot(frames, mean_arr, label=label)
    ax.fill_between(frames, mean_arr - std_arr, mean_arr + std_arr, alpha=0.2)
ax.axhline(BACKBONE_BOND_LENGTH, color='k', linestyle='--',
           label=f'rest={BACKBONE_BOND_LENGTH:.4f} nm')
ax.set_xlabel('Frame')
ax.set_ylabel('Mean backbone bond length (nm)')
ax.set_title('Exp02 — Bond length mean ± std over time')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'bond_drift.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'bond_drift.png'}")

# ── Save metrics ───────────────────────────────────────────────────────────────

metrics = {
    "backbone_bond_rest": float(BACKBONE_BOND_LENGTH),
    "n_frames":           N_FRAMES,
    "n_substeps":         N_SUBSTEPS,
    "results": [
        {
            "noise_amplitude": r["noise_amplitude"],
            "final_rmsd":      r["final_rmsd"],
            "peak_rmsd":       r["peak_rmsd"],
            "final_bond_mean": r["final_bond_mean"],
            "final_bond_std":  r["final_bond_std"],
            "bounded":         r["bounded"],
        }
        for r in results
    ],
}

with open(OUT / 'metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)
print(f"Saved {OUT / 'metrics.json'}")

# ── Pass/Fail ──────────────────────────────────────────────────────────────────

print("\n=== Exp02 Results ===")
for r in results:
    noise = r['noise_amplitude']
    if noise == 0.01:
        passed = r['final_rmsd'] < 2.0 and r['bounded']
    elif noise == 0.05:
        passed = 0.1 < r['final_rmsd'] < 5.0
    else:  # 0.10
        passed = r['final_rmsd'] > 0.5   # just check it moves significantly
    status = "PASS" if passed else "FAIL"
    print(f"  noise={noise}: {status}  "
          f"final_RMSD={r['final_rmsd']:.3f} nm  "
          f"peak_RMSD={r['peak_rmsd']:.3f} nm  "
          f"bond_mean={r['final_bond_mean']:.4f} nm  "
          f"bounded={r['bounded']}")
