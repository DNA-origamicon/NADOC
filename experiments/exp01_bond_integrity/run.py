"""
Exp01 — Bond Integrity
======================
Perturb a 42bp duplex by ±0.5 nm, relax 100 XPBD steps (no noise),
verify backbone bond lengths recover to rest.
"""

import json
import pathlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is on path
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Design, DesignMetadata, Direction, Domain, Helix, LatticeType, Strand, Vec3,
)
from backend.api.crud import _geometry_for_design
from backend.physics.xpbd import build_simulation, xpbd_step, BACKBONE_BOND_LENGTH

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

# ── Build a 42bp single-helix design ──────────────────────────────────────────

LENGTH_BP = 42

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

design = Design(
    metadata=DesignMetadata(name="exp01"),
    helices=[helix],
    strands=[scaffold, staple],
)

geometry = _geometry_for_design(design)
sim = build_simulation(design, geometry)

# ── Record t=0 bond lengths ────────────────────────────────────────────────────

def bond_lengths(positions, bond_ij):
    d = positions[bond_ij[:, 1]] - positions[bond_ij[:, 0]]
    return np.linalg.norm(d, axis=1)

pos0 = sim.positions.copy()
bl0 = bond_lengths(pos0, sim.bond_ij)

# ── Perturb ────────────────────────────────────────────────────────────────────

rng = np.random.default_rng(42)
sim.positions += rng.uniform(-0.5, 0.5, sim.positions.shape)
bl_perturbed = bond_lengths(sim.positions, sim.bond_ij)

# ── Relax ──────────────────────────────────────────────────────────────────────

sim.noise_amplitude = 0.0
sim.bond_stiffness  = 1.0

for _ in range(100):
    xpbd_step(sim, n_substeps=20)

bl_final = bond_lengths(sim.positions, sim.bond_ij)

# ── Plot ───────────────────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(8, 5))
bins = np.linspace(0.3, 1.2, 60)
ax.hist(bl0,         bins=bins, alpha=0.6, label='t=0 (geometric)')
ax.hist(bl_perturbed, bins=bins, alpha=0.6, label='perturbed ±0.5 nm')
ax.hist(bl_final,    bins=bins, alpha=0.6, label='final (100 XPBD steps)')
ax.axvline(BACKBONE_BOND_LENGTH, color='k', linestyle='--', label=f'rest={BACKBONE_BOND_LENGTH:.4f} nm')
ax.set_xlabel('Bond length (nm)')
ax.set_ylabel('Count')
ax.set_title('Exp01 — Backbone bond length distribution')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'bond_lengths.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'bond_lengths.png'}")

# ── Metrics ───────────────────────────────────────────────────────────────────

def stage_metrics(bl, label):
    return {
        "stage":  label,
        "mean":   float(np.mean(bl)),
        "std":    float(np.std(bl)),
        "min":    float(np.min(bl)),
        "max":    float(np.max(bl)),
        "max_deviation_from_rest": float(np.max(np.abs(bl - BACKBONE_BOND_LENGTH))),
    }

metrics = {
    "n_bonds":           int(len(sim.bond_ij)),
    "backbone_bond_rest": float(BACKBONE_BOND_LENGTH),
    "stages": [
        stage_metrics(bl0,          "geometric"),
        stage_metrics(bl_perturbed, "perturbed"),
        stage_metrics(bl_final,     "final"),
    ],
}

with open(OUT / 'metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)
print(f"Saved {OUT / 'metrics.json'}")

# ── Pass/Fail ─────────────────────────────────────────────────────────────────

mean_deviation = abs(np.mean(bl_final) - np.mean(bl0))
max_deviation  = float(np.max(np.abs(bl_final - BACKBONE_BOND_LENGTH)))

passed = mean_deviation < 0.01 and max_deviation < 0.05
status = "PASS" if passed else "FAIL"

print(f"\n=== Exp01 Result: {status} ===")
print(f"  Geometric mean bond:   {np.mean(bl0):.5f} nm")
print(f"  Perturbed mean bond:   {np.mean(bl_perturbed):.5f} nm")
print(f"  Final mean bond:       {np.mean(bl_final):.5f} nm")
print(f"  Mean deviation from t=0: {mean_deviation:.5f} nm  (threshold 0.01)")
print(f"  Max deviation from rest: {max_deviation:.5f} nm  (threshold 0.05)")
