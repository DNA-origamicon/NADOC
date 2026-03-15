"""
Exp13 — 6HB Structural Cohesion: Crossovers vs No Crossovers
=============================================================
Demonstrate that XPBD correctly models the role of crossovers as the
load-bearing topological element of DNA origami.

Experimental design
───────────────────
Both conditions start from ideal geometry (no perturbation).  Thermal noise
drives helix diffusion.  Each bead receives an independent random kick of
NOISE_AMP nm/substep.  A 42-bp helix has ~84 beads; the centroid diffuses
at rate NOISE_AMP/√84 × √N_SUBSTEPS per step — a measurable random walk
over 500 steps.

  No crossovers:  helices are independent rigid rods.  Inter-helix centroid
                  distances grow as √(steps) — pure random walk.  EV (cutoff
                  0.6 nm) never fires at the 2.25 nm lattice spacing.

  With crossovers: backbone bonds at crossover junctions (rest ~0.68 nm)
                  act as springs between adjacent helices.  When a helix
                  drifts, the crossover bond is stretched and exerts a
                  restoring force.  The bundle remains cohesive.

Metric: mean inter-helix centroid distance (adjacent pairs) and individual
        helix centroid drift from ideal position, over N_STEPS.
"""

from __future__ import annotations

import json
import pathlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.core.constants import HONEYCOMB_HELIX_SPACING
from backend.core.geometry import nucleotide_positions
from backend.core.lattice import make_bundle_design, make_half_crossover
from backend.core.crossover_positions import valid_crossover_positions
from backend.physics.xpbd import (
    DEFAULT_BOND_STIFFNESS,
    DEFAULT_BEND_STIFFNESS,
    DEFAULT_BP_STIFFNESS,
    DEFAULT_STACKING_STIFFNESS,
    build_simulation,
    xpbd_step,
)

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

# ── Experiment parameters ─────────────────────────────────────────────────────

CELLS      = [(0,0),(0,1),(1,0),(0,2),(1,2),(2,1)]
LEN_BP     = 42
N_STEPS    = 500
N_SUBSTEPS = 20
NOISE_AMP  = 0.10     # nm/substep — high enough to see centroid drift
IDEAL_DIST = HONEYCOMB_HELIX_SPACING  # 2.25 nm

# ── Build designs ─────────────────────────────────────────────────────────────

design_no_xover = make_bundle_design(CELLS, length_bp=LEN_BP, name='6HB-NoXover')

helix_ids   = [h.id for h in design_no_xover.helices]
helix_by_id = {h.id: h for h in design_no_xover.helices}
helix_pos   = {h.id: np.array([h.axis_start.x, h.axis_start.y])
               for h in design_no_xover.helices}

# Identify adjacent pairs
adj_pairs: list[tuple[str, str]] = []
for i, a in enumerate(helix_ids):
    for b in helix_ids[i+1:]:
        d = float(np.linalg.norm(helix_pos[a] - helix_pos[b]))
        if d < IDEAL_DIST * 1.05:
            adj_pairs.append((a, b))

print(f"Bundle: {len(helix_ids)} helices, {len(adj_pairs)} adjacent pairs, {LEN_BP} bp")

# ── Add crossovers ────────────────────────────────────────────────────────────

design_with_xover = design_no_xover
n_xovers = 0
xover_counts: dict[tuple[str,str], int] = {}
for ha_id, hb_id in adj_pairs:
    ha = helix_by_id[ha_id]
    hb = helix_by_id[hb_id]
    candidates = valid_crossover_positions(ha, hb)
    placed = 0
    for best in candidates[:3]:   # up to 3 crossovers per pair
        try:
            design_with_xover = make_half_crossover(
                design_with_xover,
                ha_id, best.bp_a, best.direction_a,
                hb_id, best.bp_b, best.direction_b,
            )
            n_xovers += 1
            placed += 1
        except ValueError:
            pass
    xover_counts[(ha_id, hb_id)] = placed

print(f"Added {n_xovers} crossovers ({n_xovers / max(len(adj_pairs),1):.1f} per pair)")

# ── Geometry builder ──────────────────────────────────────────────────────────

def _build_geometry(design):
    geometry = []
    for h in design.helices:
        for n in nucleotide_positions(h):
            geometry.append({
                "helix_id":          n.helix_id,
                "bp_index":          n.bp_index,
                "direction":         n.direction.value,
                "backbone_position": n.position.tolist(),
            })
    return geometry

# ── Run simulation ────────────────────────────────────────────────────────────

def _run(design, geometry, label, rng_seed=42):
    sim = build_simulation(design, geometry)
    sim.noise_amplitude    = NOISE_AMP
    sim.bond_stiffness     = DEFAULT_BOND_STIFFNESS
    sim.bend_stiffness     = DEFAULT_BEND_STIFFNESS
    sim.bp_stiffness       = DEFAULT_BP_STIFFNESS
    sim.stacking_stiffness = DEFAULT_STACKING_STIFFNESS
    sim.rng = np.random.default_rng(rng_seed)

    particle_helix = [p[0] for p in sim.particles]

    # Record initial centroid positions (ideal geometry)
    def _centroids(pos):
        cx = {}; cnt = {}
        for i, hid in enumerate(particle_helix):
            if hid not in cx:
                cx[hid] = np.zeros(2); cnt[hid] = 0
            cx[hid] += pos[i, :2]; cnt[hid] += 1
        return {hid: cx[hid] / cnt[hid] for hid in cx}

    history = {
        'step': [], 'adj_mean': [], 'adj_std': [],
        'bundle_diameter': [], 'centroid_drift': [],
        'per_helix_drift': {hid: [] for hid in helix_ids},
    }

    initial_centroids = None

    for step in range(N_STEPS + 1):
        if step > 0:
            xpbd_step(sim, n_substeps=N_SUBSTEPS)

        c = _centroids(sim.positions)
        if initial_centroids is None:
            initial_centroids = {hid: c[hid].copy() for hid in c}

        adj_dists = [
            float(np.linalg.norm(c[a] - c[b])) if a in c and b in c else IDEAL_DIST
            for a, b in adj_pairs
        ]

        all_cents = np.array([c[hid] for hid in helix_ids if hid in c])
        diam = float(np.max([
            np.linalg.norm(all_cents[i] - all_cents[j])
            for i in range(len(all_cents))
            for j in range(i+1, len(all_cents))
        ])) if len(all_cents) >= 2 else 0.0

        drifts = {
            hid: float(np.linalg.norm(c[hid] - initial_centroids[hid]))
            for hid in helix_ids if hid in c
        }
        mean_drift = float(np.mean(list(drifts.values())))

        history['step'].append(step)
        history['adj_mean'].append(float(np.mean(adj_dists)))
        history['adj_std'].append(float(np.std(adj_dists)))
        history['bundle_diameter'].append(diam)
        history['centroid_drift'].append(mean_drift)
        for hid in helix_ids:
            history['per_helix_drift'][hid].append(drifts.get(hid, 0.0))

        if step % 100 == 0:
            print(f"  [{label}] step {step:3d}  adj={np.mean(adj_dists):.3f}±{np.std(adj_dists):.3f} nm  "
                  f"drift={mean_drift:.3f} nm  diam={diam:.3f} nm")

    return history

print("\n── No crossovers ──")
hist_no  = _run(design_no_xover,  _build_geometry(design_no_xover),  'NO-XOVER',   rng_seed=42)
print("\n── With crossovers ──")
hist_yes = _run(design_with_xover, _build_geometry(design_with_xover), 'WITH-XOVER', rng_seed=42)

# ── Save metrics ──────────────────────────────────────────────────────────────

with open(OUT / 'metrics.json', 'w') as f:
    json.dump({
        "n_helices": len(helix_ids), "n_adj_pairs": len(adj_pairs),
        "n_crossovers": n_xovers, "n_steps": N_STEPS,
        "noise_amp": NOISE_AMP, "n_substeps": N_SUBSTEPS,
        "no_xover":   {k: hist_no[k]  for k in ('adj_mean','adj_std','bundle_diameter','centroid_drift')},
        "with_xover": {k: hist_yes[k] for k in ('adj_mean','adj_std','bundle_diameter','centroid_drift')},
    }, f, indent=2)

# ── Figure ────────────────────────────────────────────────────────────────────

steps     = np.array(hist_no['step'])
adj_no    = np.array(hist_no['adj_mean'])
adj_yes   = np.array(hist_yes['adj_mean'])
std_no    = np.array(hist_no['adj_std'])
std_yes   = np.array(hist_yes['adj_std'])
drift_no  = np.array(hist_no['centroid_drift'])
drift_yes = np.array(hist_yes['centroid_drift'])
diam_no   = np.array(hist_no['bundle_diameter'])
diam_yes  = np.array(hist_yes['bundle_diameter'])

C_no  = '#e53935'
C_yes = '#1e88e5'

fig = plt.figure(figsize=(14, 10))
gs  = gridspec.GridSpec(2, 2, figure=fig, hspace=0.45, wspace=0.38)

ax_adj   = fig.add_subplot(gs[0, 0])
ax_drift = fig.add_subplot(gs[0, 1])
ax_diam  = fig.add_subplot(gs[1, 0])
ax_helix = fig.add_subplot(gs[1, 1])

# ─ Panel 1: mean adjacent inter-helix distance ────────────────────────────────
ax_adj.axhline(IDEAL_DIST, color='gray', lw=1.2, ls='--', alpha=0.7,
               label=f'Ideal ({IDEAL_DIST:.2f} nm)')
ax_adj.fill_between(steps, adj_no  - std_no,  adj_no  + std_no,  color=C_no,  alpha=0.15)
ax_adj.fill_between(steps, adj_yes - std_yes, adj_yes + std_yes, color=C_yes, alpha=0.15)
ax_adj.plot(steps, adj_no,  color=C_no,  lw=2.2, label='No crossovers')
ax_adj.plot(steps, adj_yes, color=C_yes, lw=2.2, label='With crossovers')
ax_adj.set_xlabel('XPBD step', fontsize=11)
ax_adj.set_ylabel('Mean adj. inter-helix dist. (nm)', fontsize=11)
ax_adj.set_title('Inter-helix Distance Under Thermal Noise', fontsize=11)
ax_adj.legend(fontsize=9)
ax_adj.set_xlim(0, N_STEPS)

# ─ Panel 2: centroid drift (mean over all helices) ────────────────────────────
ax_drift.plot(steps, drift_no,  color=C_no,  lw=2.2, label='No crossovers')
ax_drift.plot(steps, drift_yes, color=C_yes, lw=2.2, label='With crossovers')
# Theoretical random walk for a free helix centroid
import math
n_beads_per_helix = 2 * LEN_BP  # approximate (both strands)
theory_drift = np.array([
    NOISE_AMP / math.sqrt(n_beads_per_helix) * math.sqrt(s * N_SUBSTEPS)
    for s in steps
])
ax_drift.plot(steps, theory_drift, color='gray', lw=1.2, ls=':', alpha=0.7,
              label=f'Theory: free rod (noise/√{n_beads_per_helix}×√substeps)')
ax_drift.set_xlabel('XPBD step', fontsize=11)
ax_drift.set_ylabel('Mean helix centroid drift (nm)', fontsize=11)
ax_drift.set_title('Helix Centroid Drift From Ideal Position', fontsize=11)
ax_drift.legend(fontsize=8)
ax_drift.set_xlim(0, N_STEPS)

# ─ Panel 3: bundle diameter ───────────────────────────────────────────────────
ax_diam.plot(steps, diam_no,  color=C_no,  lw=2.2, label='No crossovers')
ax_diam.plot(steps, diam_yes, color=C_yes, lw=2.2, label='With crossovers')
ax_diam.axhline(diam_no[0], color='gray', lw=0.8, ls='--', alpha=0.5, label='Initial diameter')
ax_diam.set_xlabel('XPBD step', fontsize=11)
ax_diam.set_ylabel('Bundle diameter (nm)', fontsize=11)
ax_diam.set_title('Bundle Diameter Over Time\n(max inter-centroid distance)', fontsize=11)
ax_diam.legend(fontsize=9)
ax_diam.set_xlim(0, N_STEPS)

# ─ Panel 4: per-helix drift (spaghetti plot) ─────────────────────────────────
import matplotlib.cm as cm
palette_h = cm.tab10(np.linspace(0, 0.6, len(helix_ids)))
for hi, hid in enumerate(helix_ids):
    drft_no  = np.array(hist_no['per_helix_drift'][hid])
    drft_yes = np.array(hist_yes['per_helix_drift'][hid])
    ax_helix.plot(steps, drft_no,  color=palette_h[hi], lw=1.2, ls='-',  alpha=0.7)
    ax_helix.plot(steps, drft_yes, color=palette_h[hi], lw=1.2, ls='--', alpha=0.7)

from matplotlib.lines import Line2D
ax_helix.legend(handles=[
    Line2D([0],[0], color='gray', lw=2, ls='-',  label='No crossovers (solid)'),
    Line2D([0],[0], color='gray', lw=2, ls='--', label='With crossovers (dashed)'),
], fontsize=9)
ax_helix.set_xlabel('XPBD step', fontsize=11)
ax_helix.set_ylabel('Helix centroid drift (nm)', fontsize=11)
ax_helix.set_title('Per-helix Centroid Drift\n(colors = individual helices)', fontsize=11)
ax_helix.set_xlim(0, N_STEPS)

fig.suptitle(
    f'Exp13 — 6HB Structural Cohesion: Crossovers vs No Crossovers\n'
    f'{LEN_BP} bp · {n_xovers} crossovers · noise = {NOISE_AMP} nm/substep · '
    f'{N_SUBSTEPS} substeps/step · {N_STEPS} steps',
    fontsize=10
)

fig.savefig(OUT / 'cohesion_comparison.png', dpi=150, bbox_inches='tight')
plt.close(fig)
print(f"\nSaved {OUT / 'cohesion_comparison.png'}")

# ── Pass/Fail ─────────────────────────────────────────────────────────────────

half = N_STEPS // 2
final_no_adj  = float(np.mean(adj_no[half:]))
final_yes_adj = float(np.mean(adj_yes[half:]))
no_dev        = abs(final_no_adj  - IDEAL_DIST)
yes_dev       = abs(final_yes_adj - IDEAL_DIST)

init_diam       = float(diam_no[0])
final_no_diam   = float(np.mean(diam_no[half:]))
final_yes_diam  = float(np.mean(diam_yes[half:]))
diam_growth_pct = (final_no_diam - init_diam) / init_diam * 100.0
final_no_drift  = float(drift_no[-1])
final_yes_drift = float(drift_yes[-1])

# Pass criteria:
# 1. Without crossovers: bundle diameter grows > 20% (helices drift apart)
# 2. With crossovers: bundle diameter stays smaller than the no-crossover case
# 3. Adj dist with crossovers stays closer to ideal than no-crossovers
bundle_expands    = diam_growth_pct > 20.0
xovers_restrain   = final_yes_diam < final_no_diam
xovers_closer     = yes_dev < no_dev

passed = bundle_expands and xovers_restrain and xovers_closer

status = "PASS" if passed else "FAIL"
print(f"\n=== Exp13 Result: {status} ===")
print(f"  Initial bundle diameter: {init_diam:.3f} nm")
print(f"  Final bundle diameter  — no xovers: {final_no_diam:.3f} nm  ({diam_growth_pct:+.1f}%)")
print(f"  Final bundle diameter  — with xovers: {final_yes_diam:.3f} nm")
print(f"  Bundle expands > 20% without crossovers: {bundle_expands}  ({diam_growth_pct:.1f}%)")
print(f"  Crossovers restrain diameter growth: {xovers_restrain}  ({final_yes_diam:.3f} < {final_no_diam:.3f})")
print(f"  Mean adj dist (final half) — no xovers: {final_no_adj:.3f} nm  ({no_dev:.3f} nm from ideal)")
print(f"  Mean adj dist (final half) — with xovers: {final_yes_adj:.3f} nm  ({yes_dev:.3f} nm from ideal)")
print(f"  Crossovers keep adj dist closer to ideal: {xovers_closer}  ({no_dev:.3f} → {yes_dev:.3f} nm)")
print(f"  Centroid drift — no/with: {final_no_drift:.3f} / {final_yes_drift:.3f} nm")
