"""
Exp11 — Bend Loop/Skip: Radius vs Cross-Section Gradient
==========================================================
Validate that bend_loop_skips() produces per-helix modifications that
correctly predict curvature via the elastic continuum formula, matching
the geometry of the Dietz et al. (2009) 3-by-6 bundle.

Geometry: 6 helices in 3 rows × 2 cols, bend in +Y direction.
Segment: 15 cells × 7 bp = 105 bp.
"""

import json
import math
import pathlib
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.loop_skip_calculator import (
    BDNA_TWIST_PER_BP_DEG,
    CELL_BP_DEFAULT,
    MAX_DELTA_PER_CELL,
    _cell_boundaries,
    bend_loop_skips,
    min_bend_radius_nm,
    predict_radius_nm,
)
from backend.core.models import Helix, LoopSkip, Vec3

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

# ── Bundle geometry ───────────────────────────────────────────────────────────
# 3 rows × 2 cols honeycomb cross-section, matching Dietz 3-by-6 geometry.
# Bend direction: +Y (across the 3-row axis)

HONEYCOMB_ROW_PITCH = 2.25    # nm, row spacing
HONEYCOMB_COL_PITCH = 1.9486  # nm, col pitch
LENGTH_BP = 105               # 15 cells of 7 bp
PLANE_A = 0
PLANE_B = LENGTH_BP
DIRECTION_DEG = 90.0          # bend in +Y direction

rows_y = [0.0, HONEYCOMB_ROW_PITCH, 2 * HONEYCOMB_ROW_PITCH]
cols_x = [0.0, HONEYCOMB_COL_PITCH]

helices = [
    Helix(
        id=f"h_r{r}_c{c}",
        axis_start=Vec3(x=x, y=y, z=0.0),
        axis_end=Vec3(x=x, y=y, z=LENGTH_BP * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=LENGTH_BP,
    )
    for r, y in enumerate(rows_y)
    for c, x in enumerate(cols_x)
]

N_CELLS = len(_cell_boundaries(PLANE_A, PLANE_B))   # = 15
R_MIN   = min_bend_radius_nm(helices, PLANE_A, PLANE_B, DIRECTION_DEG)
L_NOM   = N_CELLS * CELL_BP_DEFAULT * BDNA_RISE_PER_BP  # nm

# ── Compute cross-section offsets ─────────────────────────────────────────────
from backend.core.loop_skip_calculator import _bundle_centroid_and_tangent, _helix_cross_section_offset
import numpy as np_mod

centroid, tangent = _bundle_centroid_and_tangent(helices)
phi = math.radians(DIRECTION_DEG)
bend_raw = np_mod.array([math.cos(phi), math.sin(phi), 0.0])
bend_hat = bend_raw - np_mod.dot(bend_raw, tangent) * tangent
bend_hat /= np_mod.linalg.norm(bend_hat)

offsets = {
    h.id: float(np_mod.dot(_helix_cross_section_offset(h, centroid, tangent), bend_hat))
    for h in helices
}  # helix_id → r_i (nm), signed

# ── Sweep target radii ────────────────────────────────────────────────────────
# Radii from just above R_min to 100 nm, logarithmically spaced, plus Dietz points.
# Also test violation below R_min.

dietz_radii_nm = [6.0, 10.0, 16.1, 25.0, 40.0, 64.0]  # from Dietz Fig 3 (approx)
test_radii = sorted(set([
    round(R_MIN * 1.01, 2),   # just above limit
    7.0, 8.0, 10.0, 12.0, 15.0, 20.0, 30.0, 50.0, 100.0,
]))

records = []
for r_target in test_radii:
    try:
        mods = bend_loop_skips(helices, PLANE_A, PLANE_B, radius_nm=r_target, direction_deg=DIRECTION_DEG)
        r_predicted = predict_radius_nm(helices, mods, PLANE_A, PLANE_B, DIRECTION_DEG)

        per_helix = {}
        for h in helices:
            ls_list = mods.get(h.id, [])
            n_del = sum(1 for ls in ls_list if ls.delta == -1)
            n_ins = sum(1 for ls in ls_list if ls.delta == +1)
            total_bp_change = sum(ls.delta for ls in ls_list)
            # Effective twist density: cell bp = 7 + total_bp_change/n_cells
            effective_cell_bp = CELL_BP_DEFAULT + total_bp_change / N_CELLS
            bp_per_turn = 10.5 * CELL_BP_DEFAULT / effective_cell_bp if effective_cell_bp > 0 else float('inf')
            per_helix[h.id] = {
                "r_i_nm":          offsets[h.id],
                "n_del":           n_del,
                "n_ins":           n_ins,
                "total_bp_change": total_bp_change,
                "del_per_cell":    n_del / N_CELLS,
                "ins_per_cell":    n_ins / N_CELLS,
                "bp_per_turn":     bp_per_turn,
            }
        records.append({
            "target_radius_nm":    r_target,
            "predicted_radius_nm": r_predicted if r_predicted != math.inf else None,
            "relative_error":      abs(r_predicted - r_target) / r_target if r_predicted != math.inf else None,
            "per_helix":           per_helix,
            "error":               None,
        })
    except ValueError as exc:
        records.append({
            "target_radius_nm":    r_target,
            "predicted_radius_nm": None,
            "relative_error":      None,
            "per_helix":           None,
            "error":               str(exc),
        })

# Check limit enforcement (request below R_min)
limit_raised = False
try:
    bend_loop_skips(helices, PLANE_A, PLANE_B, radius_nm=R_MIN * 0.4, direction_deg=DIRECTION_DEG)
except ValueError:
    limit_raised = True

# ── Metrics ───────────────────────────────────────────────────────────────────
valid = [r for r in records if r['error'] is None and r['predicted_radius_nm'] is not None]
rel_errors = [r['relative_error'] for r in valid]
mean_rel_error = float(np_mod.mean(rel_errors)) if rel_errors else float('nan')
max_rel_error  = float(max(rel_errors)) if rel_errors else float('nan')

# Monotonicity: total mods per helix should increase as radius decreases
# Check on the innermost helix (most negative r_i)
inner_id = min(offsets, key=lambda k: offsets[k])
inner_counts = [r['per_helix'][inner_id]['n_del'] for r in valid]
inner_radii  = [r['target_radius_nm'] for r in valid]
# monotonically: smaller radius → more modifications
monotone = all(
    inner_counts[i] >= inner_counts[i+1]
    for i in range(len(inner_counts) - 1)
    if inner_radii[i] > inner_radii[i+1]
)

metrics = {
    "n_cells":            N_CELLS,
    "L_nom_nm":           L_NOM,
    "R_min_nm":           R_MIN,
    "mean_relative_error": mean_rel_error,
    "max_relative_error":  max_rel_error,
    "limit_enforcement_raised": limit_raised,
    "monotone_inner_helix": monotone,
    "records":            records,
}
with open(OUT / 'metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)

# ── Plot ──────────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(14, 11))
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.42, wspace=0.38)

ax_main   = fig.add_subplot(gs[0, :])
ax_twist  = fig.add_subplot(gs[1, 0])
ax_count  = fig.add_subplot(gs[1, 1])

# Main: target vs predicted radius (log scale)
t_vals = [r['target_radius_nm'] for r in valid]
p_vals = [r['predicted_radius_nm'] for r in valid]

if t_vals:
    ax_main.scatter(t_vals, p_vals, s=60, color='#1565c0', zorder=5, label='Predicted radius')
    lims = (min(t_vals) * 0.8, max(t_vals) * 1.2)
    ax_main.plot(lims, lims, 'k--', lw=1.2, label='Ideal y = x')
    ax_main.set_xscale('log')
    ax_main.set_yscale('log')
    ax_main.set_xlim(lims)
    ax_main.set_ylim(lims)
ax_main.axvline(R_MIN, color='#e53935', lw=2, linestyle='--', label=f'R_min = {R_MIN:.2f} nm')
ax_main.set_xlabel('Target radius of curvature (nm)', fontsize=11)
ax_main.set_ylabel('Predicted radius (nm)', fontsize=11)
ax_main.set_title(
    f'Exp11 — Bend loop/skip: target vs predicted radius\n'
    f'3-row × 2-col honeycomb, {N_CELLS} cells, bend in +Y direction\n'
    f'Mean relative error: {mean_rel_error*100:.1f}%   Max: {max_rel_error*100:.1f}%   '
    f'Limit: {"✓ PASS" if limit_raised else "✗ FAIL"}',
    fontsize=11)
ax_main.legend(fontsize=9, loc='upper left')

# Per-helix twist density vs target radius
helix_colors = ['#c62828', '#e53935', '#e57373', '#1565c0', '#1976d2', '#42a5f5']
helix_labels = [
    f"{h.id} (r={offsets[h.id]:+.2f} nm)" for h in helices
]
for idx, h in enumerate(helices):
    bpts  = [r['per_helix'][h.id]['bp_per_turn'] for r in valid]
    radii = [r['target_radius_nm'] for r in valid]
    color = helix_colors[idx % len(helix_colors)]
    ax_twist.plot(radii, bpts, 'o-', color=color, ms=5, lw=1.2, label=helix_labels[idx])

ax_twist.axhline(10.5, color='k', lw=1.2, linestyle='--', label='10.5 bp/turn (B-DNA)')
ax_twist.axhline(6.0,  color='#e53935', lw=1, linestyle=':', alpha=0.7, label='6 bp/turn (limit)')
ax_twist.axhline(15.0, color='#e53935', lw=1, linestyle=':', alpha=0.7, label='15 bp/turn (limit)')
ax_twist.set_xscale('log')
ax_twist.set_xlabel('Target radius (nm)', fontsize=10)
ax_twist.set_ylabel('Effective twist density (bp/turn)', fontsize=10)
ax_twist.set_title('Twist density per helix', fontsize=11)
ax_twist.legend(fontsize=7, loc='upper right', ncol=1)
ax_twist.set_ylim(4, 18)

# Modification counts per helix vs target radius
for idx, h in enumerate(helices):
    n_del = [r['per_helix'][h.id]['n_del'] for r in valid]
    n_ins = [r['per_helix'][h.id]['n_ins'] for r in valid]
    radii = [r['target_radius_nm'] for r in valid]
    color = helix_colors[idx % len(helix_colors)]
    net   = [ins - del_ for ins, del_ in zip(n_ins, n_del)]  # positive = ins
    ax_count.plot(radii, net, 'o-', color=color, ms=5, lw=1.2, label=helix_labels[idx])

ax_count.axhline(0, color='k', lw=1, linestyle='--')
ax_count.axvline(R_MIN, color='#e53935', lw=1.5, linestyle='--', alpha=0.7)
ax_count.set_xscale('log')
ax_count.set_xlabel('Target radius (nm)', fontsize=10)
ax_count.set_ylabel('Net modifications (ins − del)', fontsize=10)
ax_count.set_title('Modification count per helix\n(+= loops, −= skips)', fontsize=11)
ax_count.legend(fontsize=7, loc='upper left', ncol=1)

fig.tight_layout()
fig.savefig(OUT / 'bend_radius_calibration.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'bend_radius_calibration.png'}")

# ── Pass/Fail ─────────────────────────────────────────────────────────────────
# Thresholds: mean relative error < 30%, max < 50%, limit enforced, monotone
passed = (
    mean_rel_error < 0.30 and
    max_rel_error  < 0.50 and
    limit_raised and
    monotone
)
status = "PASS" if passed else "FAIL"
print(f"\n=== Exp11 Result: {status} ===")
print(f"  R_min: {R_MIN:.2f} nm  (Dietz observed: ~6 nm)")
print(f"  Mean relative error:  {mean_rel_error*100:.1f}%  (threshold < 30%)")
print(f"  Max relative error:   {max_rel_error*100:.1f}%  (threshold < 50%)")
print(f"  Limit enforcement:    {'✓ PASS' if limit_raised else '✗ FAIL'}")
print(f"  Inner helix monotone: {'✓ PASS' if monotone else '✗ FAIL'}")
for r in valid:
    print(f"    R_target={r['target_radius_nm']:6.1f} nm → R_predicted={r['predicted_radius_nm']:6.1f} nm  "
          f"(err={r['relative_error']*100:.1f}%)")
