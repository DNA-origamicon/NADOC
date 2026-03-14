"""
Generate honeycomb_proposed.png — shows the current 6HB and 18HB preset cell selections
overlaid on the full honeycomb lattice.

Run from the repo root:
    uv run python drawings/gen_honeycomb_proposed.py
"""

import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle, FancyArrowPatch
import numpy as np

# ── Constants (must match backend/core/constants.py) ─────────────────────────
LATTICE_RADIUS  = 1.125   # nm — per-helix spacing radius
ROW_PITCH       = 2.25    # nm
COL_PITCH       = LATTICE_RADIUS * math.sqrt(3)   # ≈ 1.9486 nm

# ── Cell value rule (matches lattice.py) ─────────────────────────────────────
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

# ── Draw grid extent ──────────────────────────────────────────────────────────
ROWS = 6   # draw rows 0..5
COLS = 8   # draw cols 0..7

CIRCLE_R = LATTICE_RADIUS * 0.88   # visual radius of each helix circle

# Colours
COLOR_FWD    = '#2979c4'   # FORWARD scaffold cells
COLOR_REV    = '#b04060'   # REVERSE scaffold cells
COLOR_HOLE   = '#141922'   # hole cells
COLOR_6HB    = '#f5a623'   # 6HB selection ring (orange)
COLOR_18HB   = '#3ddc84'   # 18HB selection ring (green)
COLOR_TEXT   = '#e6edf3'
COLOR_DIM    = '#30363d'
BG           = '#0d1117'


def draw(ax, rows, cols):
    ax.set_facecolor(BG)

    for row in range(rows):
        for col in range(cols):
            val = cell_value(row, col)
            x, y = cell_xy(row, col)

            if val == 2:
                # Hole — draw a small dim circle
                c = Circle((x, y), CIRCLE_R * 0.55, color=COLOR_HOLE,
                            linewidth=0.8, linestyle='--',
                            fill=True, zorder=1)
                ax.add_patch(c)
                ax.text(x, y, f'hole\n{row},{col}',
                        ha='center', va='center', fontsize=5.5,
                        color=COLOR_DIM, zorder=2)
                continue

            # Valid cell — filled circle coloured by direction
            face = COLOR_FWD if val == 0 else COLOR_REV
            c = Circle((x, y), CIRCLE_R, color=face, alpha=0.85,
                       linewidth=0, zorder=2)
            ax.add_patch(c)

            # 18HB highlight ring (outermost)
            if (row, col) in CELLS_18HB:
                ring = Circle((x, y), CIRCLE_R + 0.09, fill=False,
                               edgecolor=COLOR_18HB, linewidth=2.8, zorder=4)
                ax.add_patch(ring)

            # 6HB highlight ring (inside 18HB ring if also in 6HB)
            if (row, col) in CELLS_6HB:
                r_offset = 0.18 if (row, col) in CELLS_18HB else 0.09
                ring6 = Circle((x, y), CIRCLE_R + r_offset, fill=False,
                                edgecolor=COLOR_6HB, linewidth=2.2,
                                linestyle=(0, (4, 2)), zorder=5)
                ax.add_patch(ring6)

            # Direction arrow
            direction = 'FWD ↑' if val == 0 else 'REV ↓'
            dir_color = '#a8d8ff' if val == 0 else '#f0a0b0'

            # Main label: row,col
            ax.text(x, y + 0.22, f'{row},{col}',
                    ha='center', va='center',
                    fontsize=7.5, fontweight='bold',
                    color=COLOR_TEXT, zorder=6)
            ax.text(x, y - 0.24, direction,
                    ha='center', va='center',
                    fontsize=6.0, color=dir_color, zorder=6)


fig, axes = plt.subplots(1, 2, figsize=(18, 11),
                          facecolor=BG,
                          gridspec_kw={'width_ratios': [1, 1.8]})

# ── Left panel: 6HB (rows 0–2, cols 0–2) ─────────────────────────────────────
ax6 = axes[0]
ax6.set_facecolor(BG)
draw(ax6, rows=4, cols=4)

# Shade the central hole
hx, hy = cell_xy(1, 1)
ax6.text(hx, hy - 0.55, '← central\nhole', ha='center', va='top',
         fontsize=7, color=COLOR_DIM, style='italic')

# Axis limits: snug around the 6HB cells
xs6 = [cell_xy(r, c)[0] for r, c in CELLS_6HB]
ys6 = [cell_xy(r, c)[1] for r, c in CELLS_6HB]
pad = CIRCLE_R * 1.8
ax6.set_xlim(min(xs6) - pad, max(xs6) + pad)
ax6.set_ylim(min(ys6) - pad, max(ys6) + pad)
ax6.set_aspect('equal')
ax6.set_title('6HB — 6 cells\n(ring around hole (1,1))',
              color=COLOR_TEXT, fontsize=11, pad=10)
ax6.tick_params(colors=COLOR_DIM, labelsize=8)
ax6.set_xlabel('column × col_pitch (nm)', color=COLOR_DIM, fontsize=8)
ax6.set_ylabel('row × row_pitch + stagger (nm)', color=COLOR_DIM, fontsize=8)
ax6.spines[:].set_color(COLOR_DIM)

# ── Right panel: 18HB (rows 0–5, cols 0–5) ───────────────────────────────────
ax18 = axes[1]
ax18.set_facecolor(BG)
draw(ax18, rows=6, cols=6)

xs18 = [cell_xy(r, c)[0] for r, c in CELLS_18HB]
ys18 = [cell_xy(r, c)[1] for r, c in CELLS_18HB]
ax18.set_xlim(min(xs18) - pad, max(xs18) + pad)
ax18.set_ylim(min(ys18) - pad, max(ys18) + pad)
ax18.set_aspect('equal')
ax18.set_title('18HB — 18 cells\n(asymmetric layout, rows 0–5, cols 0–5)',
               color=COLOR_TEXT, fontsize=11, pad=10)
ax18.tick_params(colors=COLOR_DIM, labelsize=8)
ax18.set_xlabel('column × col_pitch (nm)', color=COLOR_DIM, fontsize=8)
ax18.set_ylabel('row × row_pitch + stagger (nm)', color=COLOR_DIM, fontsize=8)
ax18.spines[:].set_color(COLOR_DIM)

# Set tick positions to show nm values
for ax, rows_, cols_ in [(ax6, 4, 4), (ax18, 6, 6)]:
    ax.set_xticks([col * COL_PITCH for col in range(cols_)])
    ax.set_xticklabels([f'c{c}\n{c*COL_PITCH:.2f}' for c in range(cols_)],
                       fontsize=7, color=COLOR_DIM)
    # Y ticks: show representative row values
    yticks = sorted({cell_xy(r, c)[1]
                     for r in range(rows_) for c in range(cols_)
                     if cell_value(r, c) != 2})
    ax.set_yticks(yticks)
    ax.set_yticklabels([f'{y:.2f}' for y in yticks], fontsize=6.5, color=COLOR_DIM)

# ── Shared legend ─────────────────────────────────────────────────────────────
legend_handles = [
    mpatches.Patch(color=COLOR_FWD,  label='FORWARD cell  (val=0)'),
    mpatches.Patch(color=COLOR_REV,  label='REVERSE cell  (val=1)'),
    mpatches.Patch(color=COLOR_HOLE, label='HOLE          (val=2) — excluded'),
    mpatches.Patch(edgecolor=COLOR_6HB,  facecolor='none', linewidth=2,
                   linestyle='--', label='6HB preset selection'),
    mpatches.Patch(edgecolor=COLOR_18HB, facecolor='none', linewidth=2,
                   label='18HB preset selection'),
]
fig.legend(handles=legend_handles, loc='lower center', ncol=3,
           fontsize=9, framealpha=0.15,
           labelcolor=COLOR_TEXT, facecolor='#161b22',
           edgecolor=COLOR_DIM, bbox_to_anchor=(0.5, 0.01))

# ── Rule text ─────────────────────────────────────────────────────────────────
rule = (
    'Cell rule: val = (row + col%2) % 3 — 0=FORWARD, 1=REVERSE, 2=HOLE   '
    '|   col_pitch = 1.125×√3 ≈ 1.9486 nm   |   row_pitch = 2.25 nm   '
    '|   even-col stagger = +1.125 nm'
)
fig.text(0.5, 0.965, rule,
         ha='center', va='top', fontsize=8,
         color='#8b949e',
         transform=fig.transFigure)
fig.text(0.5, 0.985, 'NADOC Honeycomb Lattice — Preset Structures (current code)',
         ha='center', va='top', fontsize=11, fontweight='bold',
         color=COLOR_TEXT, transform=fig.transFigure)

fig.tight_layout(rect=[0, 0.06, 1, 0.96])

out = 'drawings/honeycomb_proposed.png'
fig.savefig(out, dpi=150, facecolor=BG, bbox_inches='tight')
print(f'Saved {out}')
