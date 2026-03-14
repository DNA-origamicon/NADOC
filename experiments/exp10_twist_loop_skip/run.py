"""
Exp10 — Twist Loop/Skip Calibration
=====================================
Validate that twist_loop_skips() produces modifications linearly proportional
to the target twist angle, correctly representing the Dietz et al. (2009)
mechanism where each deleted/inserted bp contributes ±34.286° of unrelieved
angular strain that the bundle relieves as global twist.

Cross-check against Dietz calibration points:
  "10 bp/turn" design: 6 deletions/helix over 18 cells → 205.71° predicted
  "11 bp/turn" design: 6 insertions/helix over 18 cells → −205.71° predicted
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
    max_twist_deg,
    predict_global_twist_deg,
    twist_loop_skips,
    _cell_boundaries,
)
from backend.core.models import Direction, Domain, Helix, LatticeType, Strand, Vec3, Design, DesignMetadata

OUT = pathlib.Path(__file__).parent / 'results'
OUT.mkdir(exist_ok=True)

# ── Bundle geometry: 6 helices in a 2-col × 3-row honeycomb cross-section ────
#  Matches the column width of the Dietz 10-by-6 bundle (one 6-helix slice)

HONEYCOMB_ROW_PITCH = 2.25   # nm
HONEYCOMB_COL_PITCH = 1.9486  # nm (= 1.125 × √3)
LENGTH_BP = 126               # 18 cells of 7 bp each

helix_positions = [
    (0, row * HONEYCOMB_ROW_PITCH)        # col 0
    for row in range(3)
] + [
    (HONEYCOMB_COL_PITCH, row * HONEYCOMB_ROW_PITCH + HONEYCOMB_ROW_PITCH / 2)  # col 1
    for row in range(3)
]

helices = [
    Helix(
        id=f"h{i}",
        axis_start=Vec3(x=x, y=y, z=0.0),
        axis_end=Vec3(x=x, y=y, z=LENGTH_BP * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=LENGTH_BP,
    )
    for i, (x, y) in enumerate(helix_positions)
]

N_CELLS = len(_cell_boundaries(0, LENGTH_BP))       # = 18
MAX_TWIST = max_twist_deg(N_CELLS)                   # = 18 × 3 × 34.286° ≈ 1851.4°
TWIST_PER_BP_DEG = BDNA_TWIST_PER_BP_DEG            # ≈ 34.286°

# ── Sweep target twist angles ─────────────────────────────────────────────────
# Test 18 positive values from 0 to MAX_TWIST, plus 6 negative, plus the Dietz points.

dietz_10bpt = 6 * TWIST_PER_BP_DEG      # ≈ 205.71° (10 bp/turn, 6 dels)
dietz_11bpt = -6 * TWIST_PER_BP_DEG     # ≈ −205.71° (11 bp/turn, 6 ins)

targets_pos = np.linspace(0, MAX_TWIST * 0.99, 19)      # 0…MAX (19 points)
targets_neg = np.linspace(-MAX_TWIST * 0.99, 0, 19)[:-1]  # −MAX…0 (18 points, excl 0)
all_targets = np.concatenate([targets_neg, targets_pos])

records = []
for target in all_targets:
    try:
        mods = twist_loop_skips(helices, 0, LENGTH_BP, target_twist_deg=float(target))
        predicted = predict_global_twist_deg(mods)
        n_mods_per_helix = len(mods[helices[0].id])
        delta_sign = (mods[helices[0].id][0].delta if mods[helices[0].id] else 0)
        max_spacing = 0
        bp_indices = sorted(ls.bp_index for ls in mods[helices[0].id])
        if len(bp_indices) > 1:
            spacings = [bp_indices[i+1] - bp_indices[i] for i in range(len(bp_indices)-1)]
            max_spacing = max(spacings) - min(spacings)
        records.append({
            "target_deg":       float(target),
            "predicted_deg":    float(predicted),
            "residual_deg":     float(predicted - target),
            "n_mods_per_helix": n_mods_per_helix,
            "delta_sign":       int(delta_sign),
            "max_spacing_irregularity": int(max_spacing),
            "error": None,
        })
    except ValueError as exc:
        records.append({
            "target_deg": float(target),
            "predicted_deg": None,
            "residual_deg": None,
            "n_mods_per_helix": None,
            "delta_sign": None,
            "max_spacing_irregularity": None,
            "error": str(exc),
        })

# Dietz calibration check
dietz_mods_10bpt = twist_loop_skips(helices, 0, LENGTH_BP, target_twist_deg=dietz_10bpt)
dietz_mods_11bpt = twist_loop_skips(helices, 0, LENGTH_BP, target_twist_deg=dietz_11bpt)

dietz_calibration = {
    "10bpt_target_deg":    float(dietz_10bpt),
    "10bpt_predicted_deg": float(predict_global_twist_deg(dietz_mods_10bpt)),
    "10bpt_n_del_per_helix": len(dietz_mods_10bpt[helices[0].id]),
    "10bpt_del_per_3cells":  len(dietz_mods_10bpt[helices[0].id]) / (N_CELLS / 3),
    "11bpt_target_deg":    float(dietz_11bpt),
    "11bpt_predicted_deg": float(predict_global_twist_deg(dietz_mods_11bpt)),
    "11bpt_n_ins_per_helix": len(dietz_mods_11bpt[helices[0].id]),
}

# ── Limit enforcement check ───────────────────────────────────────────────────
limit_raised = False
try:
    twist_loop_skips(helices, 0, LENGTH_BP, target_twist_deg=MAX_TWIST + 1.0)
except ValueError:
    limit_raised = True

# ── Metrics ───────────────────────────────────────────────────────────────────
valid = [r for r in records if r["error"] is None]
targets_v  = np.array([r["target_deg"]    for r in valid])
predicted_v = np.array([r["predicted_deg"] for r in valid])
residuals   = np.array([r["residual_deg"]  for r in valid])

# R² of predicted vs target (ideal = 1.0)
ss_res = float(np.sum((predicted_v - targets_v) ** 2))
ss_tot = float(np.sum((targets_v - np.mean(targets_v)) ** 2))
r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

max_residual   = float(np.max(np.abs(residuals)))
mean_residual  = float(np.mean(np.abs(residuals)))

metrics = {
    "n_cells":          N_CELLS,
    "max_twist_deg":    float(MAX_TWIST),
    "twist_per_bp_deg": TWIST_PER_BP_DEG,
    "r_squared":        r_squared,
    "max_abs_residual": max_residual,
    "mean_abs_residual": mean_residual,
    "limit_enforcement_raised": limit_raised,
    "dietz_calibration": dietz_calibration,
    "records":          records,
}
with open(OUT / 'metrics.json', 'w') as f:
    json.dump(metrics, f, indent=2)

# ── Plot ──────────────────────────────────────────────────────────────────────

fig = plt.figure(figsize=(12, 10))
gs = gridspec.GridSpec(2, 2, figure=fig, hspace=0.38, wspace=0.35)

ax_main   = fig.add_subplot(gs[0, :])
ax_resid  = fig.add_subplot(gs[1, 0])
ax_dietz  = fig.add_subplot(gs[1, 1])

# Main: predicted vs target
ax_main.scatter(targets_v, predicted_v, s=25, color='#1976d2', alpha=0.7, label='Computed modifications')
xlim = (min(targets_v) - 50, max(targets_v) + 50)
ax_main.plot(xlim, xlim, 'k--', lw=1.2, label='Ideal y = x')
ax_main.axhline(0, color='gray', lw=0.5)
ax_main.axvline(0, color='gray', lw=0.5)

# Mark Dietz calibration points
ax_main.axvline(dietz_10bpt, color='#e53935', lw=1.5, linestyle=':', alpha=0.8, label=f'Dietz 10bp/turn ({dietz_10bpt:.1f}°)')
ax_main.axvline(dietz_11bpt, color='#43a047', lw=1.5, linestyle=':', alpha=0.8, label=f'Dietz 11bp/turn ({dietz_11bpt:.1f}°)')

ax_main.set_xlim(xlim)
ax_main.set_ylim(xlim)
ax_main.set_xlabel('Target global twist (°)', fontsize=11)
ax_main.set_ylabel('Predicted global twist (°)', fontsize=11)
ax_main.set_title(
    f'Exp10 — Twist loop/skip calibration  (R² = {r_squared:.6f})\n'
    f'6-helix bundle, {N_CELLS} array cells, ±{MAX_DELTA_PER_CELL} bp/cell max',
    fontsize=12)
ax_main.legend(fontsize=9, loc='upper left')
ax_main.text(0.02, 0.82,
    f'Max |residual|: {max_residual:.2f}°  (= {max_residual/TWIST_PER_BP_DEG:.2f} × 34.3°)\n'
    f'Mean |residual|: {mean_residual:.2f}°\n'
    f'Limit enforcement: {"✓ PASS" if limit_raised else "✗ FAIL"}',
    transform=ax_main.transAxes, fontsize=9, verticalalignment='top',
    bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))

# Residual panel
ax_resid.scatter(targets_v, residuals, s=25, color='#7b1fa2', alpha=0.7)
ax_resid.axhline(0, color='k', lw=1)
ax_resid.axhline(+TWIST_PER_BP_DEG, color='#e53935', lw=1, linestyle='--', alpha=0.7, label=f'+34.3°')
ax_resid.axhline(-TWIST_PER_BP_DEG, color='#e53935', lw=1, linestyle='--', alpha=0.7, label=f'−34.3°')
ax_resid.set_xlabel('Target (°)', fontsize=10)
ax_resid.set_ylabel('Predicted − Target (°)', fontsize=10)
ax_resid.set_title('Rounding residual', fontsize=11)
ax_resid.legend(fontsize=8)

# Dietz comparison table
ax_dietz.axis('off')
col_labels = ['Parameter', 'Dietz 10bp/turn', 'Dietz 11bp/turn', 'Expected']
rows = [
    ['Target (°)',       f'{dietz_10bpt:.2f}',   f'{dietz_11bpt:.2f}',  '±205.71'],
    ['Predicted (°)',    f'{dietz_calibration["10bpt_predicted_deg"]:.2f}',
                         f'{dietz_calibration["11bpt_predicted_deg"]:.2f}',  '≈ target'],
    ['Mods/helix',       str(dietz_calibration['10bpt_n_del_per_helix']),
                         str(dietz_calibration['11bpt_n_ins_per_helix']),  '6'],
    ['Mod type',         'skip (del)',            'loop (ins)',           'del / ins'],
    ['T_eff (bp/turn)',  f'{10.5 * 120/126:.2f}', f'{10.5 * 132/126:.2f}', '10.0 / 11.0'],
    ['Paper observed',   '235±32 nm half-period', '286±48 nm half-period', 'twist ribbons'],
]
tbl = ax_dietz.table(
    cellText=rows,
    colLabels=col_labels,
    cellLoc='center',
    loc='center',
)
tbl.auto_set_font_size(False)
tbl.set_fontsize(8.5)
tbl.scale(1, 1.45)
ax_dietz.set_title('Dietz calibration comparison', fontsize=11, pad=10)

fig.tight_layout()
fig.savefig(OUT / 'twist_calibration.png', dpi=150)
plt.close(fig)
print(f"Saved {OUT / 'twist_calibration.png'}")

# ── Pass/Fail ─────────────────────────────────────────────────────────────────
passed = (
    r_squared > 0.999 and
    max_residual <= TWIST_PER_BP_DEG and
    limit_raised and
    dietz_calibration['10bpt_n_del_per_helix'] == 6 and
    dietz_calibration['11bpt_n_ins_per_helix'] == 6
)
status = "PASS" if passed else "FAIL"
print(f"\n=== Exp10 Result: {status} ===")
print(f"  R² (predicted vs target): {r_squared:.6f}  (threshold > 0.999)")
print(f"  Max |residual|: {max_residual:.2f}°  (threshold ≤ {TWIST_PER_BP_DEG:.2f}°)")
print(f"  Limit enforcement raises ValueError: {limit_raised}")
print(f"  Dietz 10bp/turn n_del/helix: {dietz_calibration['10bpt_n_del_per_helix']}  (expected 6)")
print(f"  Dietz 11bp/turn n_ins/helix: {dietz_calibration['11bpt_n_ins_per_helix']}  (expected 6)")
