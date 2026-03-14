"""
Generate honeycomb_bp0_truth.png — NADOC ground-truth backbone orientations at bp=0.

These orientations represent the backbone bead positions at the midpoint between
bp=-1 and bp=0 (i.e. half a base-pair offset = 18° CW from the "pure bp=0" positions).
This is the canonical starting phase used in NADOC initial extrusions.

Angles (looking down +Z, backbone direction = (sin θ, −cos θ)):
  FORWARD cells (blue, val=0):
    phase_offset = 42°  → FORWARD (scaffold) strand at 42°
                        → REVERSE (staple)   strand at 42° + 120° = 162°
  REVERSE cells (red, val=1):
    phase_offset = 342° → FORWARD (staple)   strand at 342°
                        → REVERSE (scaffold) strand at 342° + 120° = 102°

Run from repo root:
    uv run python drawings/gen_honeycomb_bp0_truth.py
"""

import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle
from matplotlib.lines import Line2D

# ── Constants (must match backend/core/constants.py) ─────────────────────────
LATTICE_RADIUS  = 1.125
ROW_PITCH       = 2.25
COL_PITCH       = LATTICE_RADIUS * math.sqrt(3)

# NADOC bp=0 phase offsets (half-bp CW shift applied)
PHASE_FORWARD = math.radians(42.0)   # FORWARD cell scaffold at 42°
PHASE_REVERSE = math.radians(342.0)  # REVERSE  cell scaffold at 342°+120°=102°
MINOR_GROOVE  = math.radians(120.0)  # REVERSE strand = FORWARD + 120° CCW

def cell_value(row, col):
    return (row + col % 2) % 3   # 0=FORWARD, 1=REVERSE, 2=HOLE

def cell_xy(row, col):
    x = col * COL_PITCH
    y = row * ROW_PITCH + (LATTICE_RADIUS if (col % 2) == 0 else 0.0)
    return x, y

# ── Preset cell sets ──────────────────────────────────────────────────────────
CELLS_6HB = {
    (0, 0), (0, 1), (1, 0),
    (2, 1), (0, 2), (1, 2),
}
CELLS_18HB = {
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
}

CIRCLE_R = LATTICE_RADIUS * 0.88

COLOR_FWD   = '#2979c4'
COLOR_REV   = '#b04060'
COLOR_HOLE  = '#141922'
COLOR_6HB   = '#f5a623'
COLOR_18HB  = '#3ddc84'
COLOR_TEXT  = '#e6edf3'
COLOR_DIM   = '#30363d'
BG          = '#0d1117'

ARROW_FWD   = '#a8d8ff'
ARROW_REV   = '#f0a0b0'
STPL_COLOR  = '#ffd54f'
ARROW_LEN   = CIRCLE_R * 0.55


def _draw_arrow(ax, cx, cy, dx, dy, color, lw=2.2, scale=18):
    ax.annotate(
        '',
        xy=(cx + dx * ARROW_LEN, cy + dy * ARROW_LEN),
        xytext=(cx, cy),
        xycoords='data', textcoords='data',
        arrowprops=dict(arrowstyle='->', color=color, lw=lw, mutation_scale=scale),
        zorder=7,
    )


def draw(ax, rows, cols, show_rings=True):
    ax.set_facecolor(BG)

    for row in range(rows):
        for col in range(cols):
            val = cell_value(row, col)
            x, y = cell_xy(row, col)

            if val == 2:
                c = Circle((x, y), CIRCLE_R * 0.55, color=COLOR_HOLE,
                           linewidth=0.8, linestyle='--', fill=True, zorder=1)
                ax.add_patch(c)
                ax.text(x, y, f'hole\n{row},{col}',
                        ha='center', va='center', fontsize=5.5,
                        color=COLOR_DIM, zorder=2)
                continue

            face = COLOR_FWD if val == 0 else COLOR_REV
            c = Circle((x, y), CIRCLE_R, color=face, alpha=0.85,
                       linewidth=0, zorder=2)
            ax.add_patch(c)

            if show_rings:
                if (row, col) in CELLS_18HB:
                    ring = Circle((x, y), CIRCLE_R + 0.09, fill=False,
                                  edgecolor=COLOR_18HB, linewidth=2.8, zorder=4)
                    ax.add_patch(ring)
                if (row, col) in CELLS_6HB:
                    r_offset = 0.18 if (row, col) in CELLS_18HB else 0.09
                    ring6 = Circle((x, y), CIRCLE_R + r_offset, fill=False,
                                   edgecolor=COLOR_6HB, linewidth=2.2,
                                   linestyle=(0, (4, 2)), zorder=5)
                    ax.add_patch(ring6)

            if val == 0:
                # FORWARD cell: scaffold = FORWARD strand at 42°, staple = REVERSE at 162°
                fwd_angle = PHASE_FORWARD
                rev_angle = fwd_angle + MINOR_GROOVE
                scaf_dx, scaf_dy = math.sin(fwd_angle), -math.cos(fwd_angle)
                stpl_dx, stpl_dy = math.sin(rev_angle), -math.cos(rev_angle)
                scaf_col = ARROW_FWD
                scaf_label = f'scaf {math.degrees(fwd_angle):.0f}°'
                stpl_label = f'stpl {math.degrees(rev_angle):.0f}°'
            else:
                # REVERSE cell: scaffold = REVERSE strand at 102°, staple = FORWARD at 342°
                fwd_angle = PHASE_REVERSE
                rev_angle = fwd_angle + MINOR_GROOVE
                scaf_dx, scaf_dy = math.sin(rev_angle), -math.cos(rev_angle)
                stpl_dx, stpl_dy = math.sin(fwd_angle), -math.cos(fwd_angle)
                scaf_col = ARROW_REV
                scaf_label = f'scaf {math.degrees(rev_angle % 360):.0f}°'
                stpl_label = f'stpl {math.degrees(fwd_angle):.0f}°'

            _draw_arrow(ax, x, y, scaf_dx, scaf_dy, scaf_col, lw=2.4)
            _draw_arrow(ax, x, y, stpl_dx, stpl_dy, STPL_COLOR, lw=1.6, scale=14)

            ax.text(x, y + 0.70, f'{row},{col}',
                    ha='center', va='center',
                    fontsize=7.5, fontweight='bold',
                    color=COLOR_TEXT, zorder=8)
            ax.text(x, y - 0.30, scaf_label,
                    ha='center', va='center',
                    fontsize=5.0, color=scaf_col, zorder=6)
            ax.text(x, y - 0.44, stpl_label,
                    ha='center', va='center',
                    fontsize=5.0, color=STPL_COLOR, zorder=6)


fig, axes = plt.subplots(1, 2, figsize=(18, 11),
                          facecolor=BG,
                          gridspec_kw={'width_ratios': [1, 1.8]})

ax6 = axes[0]
ax6.set_facecolor(BG)
draw(ax6, rows=4, cols=4)
xs6 = [cell_xy(r, c)[0] for r, c in CELLS_6HB]
ys6 = [cell_xy(r, c)[1] for r, c in CELLS_6HB]
pad = CIRCLE_R * 1.8
ax6.set_xlim(min(xs6) - pad, max(xs6) + pad)
ax6.set_ylim(min(ys6) - pad, max(ys6) + pad)
ax6.set_aspect('equal')
ax6.set_title('6HB — 6 cells', color=COLOR_TEXT, fontsize=11, pad=10)
ax6.tick_params(colors=COLOR_DIM, labelsize=8)
ax6.set_xlabel('column × col_pitch (nm)', color=COLOR_DIM, fontsize=8)
ax6.set_ylabel('row × row_pitch + stagger (nm)', color=COLOR_DIM, fontsize=8)
ax6.spines[:].set_color(COLOR_DIM)

ax18 = axes[1]
ax18.set_facecolor(BG)
draw(ax18, rows=6, cols=6)
xs18 = [cell_xy(r, c)[0] for r, c in CELLS_18HB]
ys18 = [cell_xy(r, c)[1] for r, c in CELLS_18HB]
ax18.set_xlim(min(xs18) - pad, max(xs18) + pad)
ax18.set_ylim(min(ys18) - pad, max(ys18) + pad)
ax18.set_aspect('equal')
ax18.set_title('18HB — 18 cells', color=COLOR_TEXT, fontsize=11, pad=10)
ax18.tick_params(colors=COLOR_DIM, labelsize=8)
ax18.set_xlabel('column × col_pitch (nm)', color=COLOR_DIM, fontsize=8)
ax18.set_ylabel('row × row_pitch + stagger (nm)', color=COLOR_DIM, fontsize=8)
ax18.spines[:].set_color(COLOR_DIM)

for ax, rows_, cols_ in [(ax6, 4, 4), (ax18, 6, 6)]:
    ax.set_xticks([col * COL_PITCH for col in range(cols_)])
    ax.set_xticklabels([f'c{c}\n{c*COL_PITCH:.2f}' for c in range(cols_)],
                       fontsize=7, color=COLOR_DIM)
    yticks = sorted({cell_xy(r, c)[1]
                     for r in range(rows_) for c in range(cols_)
                     if cell_value(r, c) != 2})
    ax.set_yticks(yticks)
    ax.set_yticklabels([f'{y:.2f}' for y in yticks], fontsize=6.5, color=COLOR_DIM)

legend_handles = [
    mpatches.Patch(color=COLOR_FWD,  label='FORWARD cell (val=0)  phase_offset=42°'),
    mpatches.Patch(color=COLOR_REV,  label='REVERSE cell  (val=1)  phase_offset=342°'),
    mpatches.Patch(color=COLOR_HOLE, label='HOLE (val=2) — excluded'),
    Line2D([0], [0], color=ARROW_FWD, linewidth=2.5, marker='>', markersize=8,
           label='Scaffold FORWARD cell: FORWARD strand at 42°'),
    Line2D([0], [0], color=ARROW_REV, linewidth=2.5, marker='>', markersize=8,
           label='Scaffold REVERSE cell: REVERSE strand at 102°'),
    Line2D([0], [0], color=STPL_COLOR, linewidth=1.8, marker='>', markersize=7,
           label='Staple: FORWARD cell 162° / REVERSE cell 342°  (scaffold +120° CCW)'),
    mpatches.Patch(edgecolor=COLOR_6HB,  facecolor='none', linewidth=2,
                   linestyle='--', label='6HB preset'),
    mpatches.Patch(edgecolor=COLOR_18HB, facecolor='none', linewidth=2,
                   label='18HB preset'),
]
fig.legend(handles=legend_handles, loc='lower center', ncol=4,
           fontsize=9, framealpha=0.15,
           labelcolor=COLOR_TEXT, facecolor='#161b22',
           edgecolor=COLOR_DIM, bbox_to_anchor=(0.5, 0.01))

rule = (
    'Cell rule: val = (row + col%2) % 3   |   '
    'col_pitch = 1.125×√3 ≈ 1.9486 nm   |   row_pitch = 2.25 nm   |   '
    'half-bp CW offset = 18°'
)
fig.text(0.5, 0.965, rule,
         ha='center', va='top', fontsize=8,
         color='#8b949e', transform=fig.transFigure)
fig.text(0.5, 0.985,
         'NADOC Honeycomb — Ground-Truth bp=0 Orientations  '
         '(phase_offset_F=42°, phase_offset_R=342°, looking down +Z)',
         ha='center', va='top', fontsize=11, fontweight='bold',
         color='#f0e050', transform=fig.transFigure)

fig.tight_layout(rect=[0, 0.07, 1, 0.96])

out = 'drawings/honeycomb_bp0_truth.png'
fig.savefig(out, dpi=150, facecolor=BG, bbox_inches='tight')
print(f'Saved {out}')
