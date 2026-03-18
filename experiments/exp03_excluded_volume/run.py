"""
Exp03 — Excluded Volume
=======================
Two parallel 42bp duplexes at 2.25 nm separation, high noise (0.08 nm/substep).
Verify EV constraints prevent inter-helix bead penetration.
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
    Design, DesignMetadata, Direction, Domain, Helix, LatticeType, Strand, StrandType, Vec3,
)
from backend.api.crud import _geometry_for_design
from backend.physics.xpbd import (
    build_simulation, xpbd_step, EXCLUDED_VOLUME_DIST,
)

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

LENGTH_BP  = 42
N_FRAMES   = 300
N_SUBSTEPS = 20
NOISE      = 0.08

# ── Build two-helix design ─────────────────────────────────────────────────────

sep = HONEYCOMB_HELIX_SPACING   # 2.25 nm

h0 = Helix(
    id="h0",
    axis_start=Vec3(x=0.0,  y=0.0, z=0.0),
    axis_end=Vec3(x=0.0,  y=0.0, z=LENGTH_BP * BDNA_RISE_PER_BP),
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

scaf0 = Strand(id="scaf0", strand_type=StrandType.SCAFFOLD,
               domains=[Domain(helix_id="h0", direction=Direction.FORWARD,
                               start_bp=0, end_bp=LENGTH_BP - 1)])
stpl0 = Strand(id="stpl0", strand_type=StrandType.STAPLE,
               domains=[Domain(helix_id="h0", direction=Direction.REVERSE,
                               start_bp=LENGTH_BP - 1, end_bp=0)])
scaf1 = Strand(id="scaf1", strand_type=StrandType.SCAFFOLD,
               domains=[Domain(helix_id="h1", direction=Direction.REVERSE,
                               start_bp=LENGTH_BP - 1, end_bp=0)])
stpl1 = Strand(id="stpl1", strand_type=StrandType.STAPLE,
               domains=[Domain(helix_id="h1", direction=Direction.FORWARD,
                               start_bp=0, end_bp=LENGTH_BP - 1)])

design = Design(
    metadata=DesignMetadata(name="exp03"),
    helices=[h0, h1],
    strands=[scaf0, stpl0, scaf1, stpl1],
)

geometry = _geometry_for_design(design)
sim = build_simulation(design, geometry)

sim.noise_amplitude = NOISE
sim.bond_stiffness  = 1.0
sim.bend_stiffness  = 0.3
sim.bp_stiffness    = 0.5
sim.rng = np.random.default_rng(42)

# ── Identify which particles belong to each helix ─────────────────────────────

idx_h0 = [i for i, (hid, bp, d) in enumerate(sim.particles) if hid == "h0"]
idx_h1 = [i for i, (hid, bp, d) in enumerate(sim.particles) if hid == "h1"]
idx_h0 = np.array(idx_h0, dtype=np.int32)
idx_h1 = np.array(idx_h1, dtype=np.int32)

print(f"h0 particles: {len(idx_h0)}, h1 particles: {len(idx_h1)}")

# ── Run simulation ─────────────────────────────────────────────────────────────

min_dist_history       = []
violation_count_history = []

for frame in range(N_FRAMES):
    xpbd_step(sim, n_substeps=N_SUBSTEPS)

    pos_h0 = sim.positions[idx_h0]  # (Nh0, 3)
    pos_h1 = sim.positions[idx_h1]  # (Nh1, 3)

    # Pairwise distances between h0 and h1 beads
    # diff[i,j] = pos_h1[j] - pos_h0[i]
    diff = pos_h1[np.newaxis, :, :] - pos_h0[:, np.newaxis, :]  # (Nh0, Nh1, 3)
    dists = np.linalg.norm(diff, axis=2)  # (Nh0, Nh1)

    min_d      = float(np.min(dists))
    violations = int(np.sum(dists < EXCLUDED_VOLUME_DIST))

    min_dist_history.append(min_d)
    violation_count_history.append(violations)

    if frame % 50 == 0:
        print(f"  frame {frame:3d}: min_dist={min_d:.4f} nm, violations={violations}")

# ── Plot min inter-helix distance ──────────────────────────────────────────────

frames = list(range(N_FRAMES))

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(frames, min_dist_history, label='min inter-helix distance')
ax.axhline(EXCLUDED_VOLUME_DIST, color='r', linestyle='--',
           label=f'EV threshold = {EXCLUDED_VOLUME_DIST} nm')
ax.set_xlabel('Frame')
ax.set_ylabel('Min distance (nm)')
ax.set_title('Exp03 — Minimum inter-helix bead distance over time')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'min_dist_vs_frame.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'min_dist_vs_frame.png'}")

# ── Plot violation count ───────────────────────────────────────────────────────

fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(frames, violation_count_history, color='r', label='EV violations')
ax.set_xlabel('Frame')
ax.set_ylabel('Violation count')
ax.set_title('Exp03 — EV violations per frame (< 0.6 nm inter-helix pairs)')
ax.legend()
fig.tight_layout()
fig.savefig(OUT / 'violations_vs_frame.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'violations_vs_frame.png'}")

# ── Save metrics ───────────────────────────────────────────────────────────────

total_violations = sum(violation_count_history)
max_violations   = max(violation_count_history)
min_of_min       = min(min_dist_history)
mean_min         = float(np.mean(min_dist_history))

metrics = {
    "ev_threshold_nm":    EXCLUDED_VOLUME_DIST,
    "helix_separation_nm": sep,
    "noise_amplitude":    NOISE,
    "n_frames":           N_FRAMES,
    "n_substeps":         N_SUBSTEPS,
    "total_violations":   total_violations,
    "max_violations_per_frame": max_violations,
    "min_inter_helix_dist_nm": min_of_min,
    "mean_min_inter_helix_dist_nm": mean_min,
    "ev_holds": total_violations == 0,
}

with open(OUT / 'metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)
print(f"Saved {OUT / 'metrics.json'}")

# ── Pass/Fail ──────────────────────────────────────────────────────────────────

passed = (total_violations == 0) and (min_of_min >= EXCLUDED_VOLUME_DIST)
status = "PASS" if passed else "FAIL"

print(f"\n=== Exp03 Result: {status} ===")
print(f"  Total EV violations (frames): {total_violations}")
print(f"  Max violations in a single frame: {max_violations}")
print(f"  Min inter-helix distance ever: {min_of_min:.4f} nm  (threshold {EXCLUDED_VOLUME_DIST})")
print(f"  Mean min inter-helix distance: {mean_min:.4f} nm")
