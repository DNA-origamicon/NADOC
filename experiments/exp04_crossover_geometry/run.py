"""
Exp04 — Crossover Geometry
===========================
Two 21bp duplexes connected by a staple crossover at bp=10.
Compare mobility (mean displacement from initial) near crossover vs. free ends.
"""

import json
import pathlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.core.constants import BDNA_RISE_PER_BP, HONEYCOMB_HELIX_SPACING
from backend.core.models import (
    Design, DesignMetadata, Direction, Domain, Helix, LatticeType, Strand, Vec3,
)
from backend.api.crud import _geometry_for_design
from backend.physics.xpbd import build_simulation, xpbd_step

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

LENGTH_BP    = 21
CROSSOVER_BP = 10
N_FRAMES     = 200
N_SUBSTEPS   = 20
NOISE        = 0.05

sep = HONEYCOMB_HELIX_SPACING   # 2.25 nm

# ── Build two-helix crossover design ──────────────────────────────────────────
#
#   scaffold0:       FORWARD h0 bp 0-20   (scaffold, goes 5'→3' left to right)
#   scaffold1:       FORWARD h1 bp 0-20   (scaffold, same direction)
#   staple_h0_left:  REVERSE h0 bp 20-11  (5'→3' = high→low bp, right-to-left)
#   staple_crossover: two domains:
#       domain_a: REVERSE h0 bp 10-0     (5'→3' from bp10 to bp0 on h0)
#       domain_b: REVERSE h1 bp 0-10     (5'→3' from bp0 to bp10 on h1)
#   staple_h1_right: REVERSE h1 bp 11-20  (5'→3' = low→high, but REVERSE means end→start)
#
# Note: for REVERSE strands, start_bp = 5' end (higher bp index for REVERSE),
#       end_bp = 3' end (lower bp index for REVERSE).

h0 = Helix(
    id="h0",
    axis_start=Vec3(x=0.0, y=0.0, z=0.0),
    axis_end=Vec3(x=0.0, y=0.0, z=LENGTH_BP * BDNA_RISE_PER_BP),
    phase_offset=0.0,
    length_bp=LENGTH_BP,
    lattice_type=LatticeType.FREE,
)
h1 = Helix(
    id="h1",
    axis_start=Vec3(x=sep, y=0.0, z=0.0),
    axis_end=Vec3(x=sep, y=0.0, z=LENGTH_BP * BDNA_RISE_PER_BP),
    phase_offset=0.0,
    length_bp=LENGTH_BP,
    lattice_type=LatticeType.FREE,
)

scaffold0 = Strand(
    id="scaf0", is_scaffold=True,
    domains=[Domain(helix_id="h0", direction=Direction.FORWARD,
                    start_bp=0, end_bp=LENGTH_BP - 1)],
)
scaffold1 = Strand(
    id="scaf1", is_scaffold=True,
    domains=[Domain(helix_id="h1", direction=Direction.FORWARD,
                    start_bp=0, end_bp=LENGTH_BP - 1)],
)
# Staple on h0 right of crossover: REVERSE, 5' at bp20, 3' at bp11
staple_h0_left = Strand(
    id="stpl_h0_left", is_scaffold=False,
    domains=[Domain(helix_id="h0", direction=Direction.REVERSE,
                    start_bp=LENGTH_BP - 1, end_bp=CROSSOVER_BP + 1)],
)
# Staple crossover: REVERSE, starts at bp10 on h0, continues to bp10 on h1
staple_crossover = Strand(
    id="stpl_xover", is_scaffold=False,
    domains=[
        Domain(helix_id="h0", direction=Direction.REVERSE,
               start_bp=CROSSOVER_BP, end_bp=0),
        Domain(helix_id="h1", direction=Direction.REVERSE,
               start_bp=0, end_bp=CROSSOVER_BP),
    ],
)
# Staple on h1 right of crossover: REVERSE, 5' at bp11, 3' at bp20
staple_h1_right = Strand(
    id="stpl_h1_right", is_scaffold=False,
    domains=[Domain(helix_id="h1", direction=Direction.REVERSE,
                    start_bp=CROSSOVER_BP + 1, end_bp=LENGTH_BP - 1)],
)

design = Design(
    metadata=DesignMetadata(name="exp04"),
    helices=[h0, h1],
    strands=[scaffold0, scaffold1, staple_h0_left, staple_crossover, staple_h1_right],
)

geometry = _geometry_for_design(design)
sim = build_simulation(design, geometry)

print(f"Particles: {len(sim.particles)}")
print(f"Backbone bonds: {len(sim.bond_ij)}")
print(f"BP bonds: {len(sim.bp_bond_ij)}")

# Print crossover bond length (the inter-helix backbone bond)
# The crossover bond connects h0:bp10:REVERSE → h1:bp0:REVERSE (or h1:bp0→h1:bp10
# depending on direction ordering). Let's find the longest backbone bond.
bl_all = np.linalg.norm(
    sim.positions[sim.bond_ij[:, 1]] - sim.positions[sim.bond_ij[:, 0]], axis=1
)
print(f"Backbone bond lengths: min={np.min(bl_all):.4f}, max={np.max(bl_all):.4f}, "
      f"mean={np.mean(bl_all):.4f} nm")
print(f"Longest bond (crossover): {np.max(bl_all):.4f} nm")

sim.noise_amplitude = NOISE
sim.bond_stiffness  = 1.0
sim.bend_stiffness  = 0.3
sim.bp_stiffness    = 0.5
sim.rng = np.random.default_rng(42)

pos0 = sim.positions.copy()

# ── Build per-bp displacement accumulator for h0 FORWARD strand ───────────────

# Index map: (helix_id, bp_index, direction) → particle index
bp_disp = {bp: [] for bp in range(LENGTH_BP)}

# ── Run simulation ─────────────────────────────────────────────────────────────

for frame in range(N_FRAMES):
    xpbd_step(sim, n_substeps=N_SUBSTEPS)

    for bp in range(LENGTH_BP):
        key = ("h0", bp, "FORWARD")
        idx = sim.index_map.get(key)
        if idx is not None:
            disp = float(np.linalg.norm(sim.positions[idx] - pos0[idx]))
            bp_disp[bp].append(disp)

# ── Compute mean displacement per bp ──────────────────────────────────────────

bp_indices     = sorted(bp_disp.keys())
mean_disp      = [float(np.mean(bp_disp[bp])) if bp_disp[bp] else 0.0 for bp in bp_indices]
std_disp       = [float(np.std(bp_disp[bp]))  if bp_disp[bp] else 0.0 for bp in bp_indices]

# ── Plot mobility vs bp ────────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 5))
ax.bar(bp_indices, mean_disp, yerr=std_disp, capsize=3,
       color='steelblue', alpha=0.7, label='h0 FORWARD mean displacement')
ax.axvline(CROSSOVER_BP, color='r', linestyle='--',
           label=f'crossover bp={CROSSOVER_BP}')
ax.axvspan(CROSSOVER_BP - 2, CROSSOVER_BP + 2, alpha=0.15, color='red',
           label='crossover region (±2 bp)')
ax.set_xlabel('bp index')
ax.set_ylabel('Mean displacement from initial (nm)')
ax.set_title('Exp04 — Mobility vs bp position (h0 FORWARD strand, 200 frames)')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'mobility_vs_bp.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'mobility_vs_bp.png'}")

# ── Compute metrics ────────────────────────────────────────────────────────────

near_xover_bp   = list(range(max(0, CROSSOVER_BP - 2), min(LENGTH_BP, CROSSOVER_BP + 3)))
end_bp_low      = list(range(0, 5))
end_bp_high     = list(range(LENGTH_BP - 5, LENGTH_BP))

mean_near = float(np.mean([mean_disp[bp] for bp in near_xover_bp]))
mean_ends = float(np.mean([mean_disp[bp] for bp in end_bp_low + end_bp_high]))

metrics = {
    "crossover_bp":         CROSSOVER_BP,
    "n_frames":             N_FRAMES,
    "noise_amplitude":      NOISE,
    "mean_disp_near_xover": mean_near,
    "mean_disp_free_ends":  mean_ends,
    "mobility_ratio_ends_over_xover": mean_ends / mean_near if mean_near > 0 else None,
    "crossover_is_stiffer": mean_near < mean_ends,
    "per_bp_mean_disp":     dict(zip(bp_indices, mean_disp)),
    "per_bp_std_disp":      dict(zip(bp_indices, std_disp)),
}

with open(OUT / 'metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)
print(f"Saved {OUT / 'metrics.json'}")

# ── Pass/Fail ──────────────────────────────────────────────────────────────────

passed = metrics["crossover_is_stiffer"]
status = "PASS" if passed else "FAIL"

print(f"\n=== Exp04 Result: {status} ===")
print(f"  Mean displacement near crossover (bp {near_xover_bp[0]}-{near_xover_bp[-1]}): "
      f"{mean_near:.4f} nm")
print(f"  Mean displacement at free ends:                                       "
      f"{mean_ends:.4f} nm")
ratio_str = f"{mean_ends/mean_near:.2f}x" if mean_near > 0 else "N/A"
print(f"  Mobility ratio (ends / crossover): {ratio_str}")
print(f"  Crossover region is stiffer: {metrics['crossover_is_stiffer']}")
