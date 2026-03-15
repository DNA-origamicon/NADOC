"""
Generate honeycomb_bp0_crossovers.png — honeycomb lattice with each adjacent
FORWARD/REVERSE cell pair highlighted by an elliptical outline.

Each outlined pair is a location where the user can manually add a staple
crossover.  Preset rings (6HB/18HB) are omitted; pairs are the only annotation.

Run from repo root:
    uv run python drawings/gen_honeycomb_bp0_crossovers.py
"""

import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle, Ellipse
from matplotlib.lines import Line2D
import numpy as np

# ── Constants (must match backend/core/constants.py) ─────────────────────────
LATTICE_RADIUS  = 1.125
ROW_PITCH       = 2.25
COL_PITCH       = LATTICE_RADIUS * math.sqrt(3)
HELIX_SPACING   = 2.25   # centre-to-centre distance between adjacent helices

def cell_value(row, col):
    return (row + col % 2) % 3   # 0=FORWARD, 1=REVERSE, 2=HOLE

def cell_xy(row, col):
    x = col * COL_PITCH
    y = row * ROW_PITCH + (LATTICE_RADIUS if (col % 2) == 0 else 0.0)
    return x, y

CIRCLE_R = LATTICE_RADIUS * 0.88

# Colours
COLOR_FWD   = '#2979c4'
COLOR_REV   = '#b04060'
COLOR_HOLE  = '#141922'
COLOR_TEXT  = '#e6edf3'
COLOR_DIM   = '#30363d'
BG          = '#0d1117'

ARROW_FWD   = '#a8d8ff'
ARROW_REV   = '#f0a0b0'
ARROW_LEN   = CIRCLE_R * 0.55
STPL_COLOR  = '#ffd54f'

# Distinct colours for pair outlines — cycle through a palette so overlapping
# pairs (cells shared between two pairs) remain distinguishable.
PAIR_PALETTE = [
    '#00e5ff', '#76ff03', '#ff6d00', '#d500f9',
    '#ff1744', '#18ffff', '#eeff41', '#ff9100',
    '#651fff', '#00e676', '#ff4081', '#40c4ff',
]


# ── Find all adjacent FORWARD/REVERSE pairs ───────────────────────────────────

def find_crossover_pairs(rows, cols):
    """
    Return adjacent FORWARD/REVERSE pairs whose staple arrows point toward each
    other at bp=0.

    FORWARD staple direction: (sin 330°, -cos 330°) = (-0.5, -√3/2).
    A pair qualifies when dot(unit_vec_fwd→rev, fwd_staple_dir) > 0.7,
    i.e. the REVERSE cell lies in the direction the FORWARD staple points.
    (Equivalently the REVERSE staple points back toward the FORWARD cell.)
    """
    FWD_STPL = (math.sin(math.radians(330)), -math.cos(math.radians(330)))  # (-0.5, -0.866)

    valid = [
        (r, c)
        for r in range(rows)
        for c in range(cols)
        if cell_value(r, c) != 2
    ]
    pairs = []
    for i, (r1, c1) in enumerate(valid):
        for r2, c2 in valid[i + 1:]:
            v1, v2 = cell_value(r1, c1), cell_value(r2, c2)
            if {v1, v2} != {0, 1}:
                continue
            x1, y1 = cell_xy(r1, c1)
            x2, y2 = cell_xy(r2, c2)
            dist = math.hypot(x2 - x1, y2 - y1)
            if abs(dist - HELIX_SPACING) > 0.05:
                continue
            # Orient so (rf, cf) is the FORWARD cell
            if v1 == 0:
                xf, yf, xr, yr = x1, y1, x2, y2
            else:
                xf, yf, xr, yr = x2, y2, x1, y1
            ux, uy = (xr - xf) / dist, (yr - yf) / dist
            if ux * FWD_STPL[0] + uy * FWD_STPL[1] > 0.7:
                pairs.append(((r1, c1), (r2, c2)))
    return pairs


# ── Arrow helper ──────────────────────────────────────────────────────────────

def draw_arrow(ax, cx, cy, dx, dy, color, lw=2.2, scale=18):
    """Tail at (cx, cy), head pointing toward (cx+dx*L, cy+dy*L)."""
    ax.annotate(
        '',
        xy=(cx + dx * ARROW_LEN, cy + dy * ARROW_LEN),
        xytext=(cx, cy),
        xycoords='data', textcoords='data',
        arrowprops=dict(arrowstyle='->', color=color, lw=lw, mutation_scale=scale),
        zorder=8,
    )


# ── Draw ──────────────────────────────────────────────────────────────────────

ROWS, COLS = 6, 6

pairs = find_crossover_pairs(ROWS, COLS)

fig, ax = plt.subplots(figsize=(11, 12), facecolor=BG)
ax.set_facecolor(BG)

# ── 1. Pair outlines (drawn first, behind cells) ──────────────────────────────
for idx, ((r1, c1), (r2, c2)) in enumerate(pairs):
    x1, y1 = cell_xy(r1, c1)
    x2, y2 = cell_xy(r2, c2)
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    dist   = math.hypot(dx, dy)
    angle  = math.degrees(math.atan2(dy, dx))

    # Ellipse that just encloses both circles
    semi_major = dist / 2 + CIRCLE_R + 0.10
    semi_minor = CIRCLE_R + 0.18

    color = PAIR_PALETTE[idx % len(PAIR_PALETTE)]
    ell = Ellipse(
        (mx, my),
        width=2 * semi_major,
        height=2 * semi_minor,
        angle=angle,
        fill=False,
        edgecolor=color,
        linewidth=2.0,
        linestyle='-',
        alpha=0.75,
        zorder=3,
    )
    ax.add_patch(ell)

# ── 2. Cells ──────────────────────────────────────────────────────────────────
for row in range(ROWS):
    for col in range(COLS):
        val = cell_value(row, col)
        x, y = cell_xy(row, col)

        if val == 2:
            c = Circle((x, y), CIRCLE_R * 0.55, color=COLOR_HOLE,
                       linewidth=0.8, linestyle='--', fill=True, zorder=4)
            ax.add_patch(c)
            ax.text(x, y, f'hole\n{row},{col}',
                    ha='center', va='center', fontsize=5.5,
                    color=COLOR_DIM, zorder=5)
            continue

        face = COLOR_FWD if val == 0 else COLOR_REV
        c = Circle((x, y), CIRCLE_R, color=face, alpha=0.85,
                   linewidth=0, zorder=4)
        ax.add_patch(c)

        # Scaffold and staple arrows (bp=0 orientations)
        if val == 0:   # FORWARD: scaffold → east (90°), staple 120° CW → 330° SSW
            scaf_dx = math.sin(math.radians(90));  scaf_dy = -math.cos(math.radians(90))
            stpl_dx = math.sin(math.radians(330)); stpl_dy = -math.cos(math.radians(330))
        else:          # REVERSE: scaffold → west (270°), staple 120° CW → 150° NNE
            scaf_dx = math.sin(math.radians(270)); scaf_dy = -math.cos(math.radians(270))
            stpl_dx = math.sin(math.radians(150)); stpl_dy = -math.cos(math.radians(150))

        scaf_col = ARROW_FWD if val == 0 else ARROW_REV
        draw_arrow(ax, x, y, scaf_dx, scaf_dy, scaf_col, lw=2.4)
        draw_arrow(ax, x, y, stpl_dx, stpl_dy, STPL_COLOR, lw=1.6, scale=14)

        ax.text(x, y + 0.70, f'{row},{col}',
                ha='center', va='center',
                fontsize=7.5, fontweight='bold',
                color=COLOR_TEXT, zorder=9)

        scaf_label = 'scaf→' if val == 0 else '←scaf'
        stpl_label = '↙stpl' if val == 0 else '↗stpl'
        ax.text(x, y - 0.30, scaf_label,
                ha='center', va='center',
                fontsize=5.5, color=scaf_col, zorder=7)
        ax.text(x, y - 0.44, stpl_label,
                ha='center', va='center',
                fontsize=5.5, color=STPL_COLOR, zorder=7)

# ── Axis limits / formatting ──────────────────────────────────────────────────
all_valid = [(r, c) for r in range(ROWS) for c in range(COLS) if cell_value(r, c) != 2]
xs  = [cell_xy(r, c)[0] for r, c in all_valid]
ys  = [cell_xy(r, c)[1] for r, c in all_valid]
pad = CIRCLE_R * 2.0
ax.set_xlim(min(xs) - pad, max(xs) + pad)
ax.set_ylim(min(ys) - pad, max(ys) + pad)
ax.set_aspect('equal')

xticks = sorted({cell_xy(r, c)[0] for r, c in all_valid})
ax.set_xticks(xticks)
ax.set_xticklabels([f'c{c}\n{c*COL_PITCH:.2f}' for c in range(COLS)],
                   fontsize=7, color=COLOR_DIM)
yticks = sorted({cell_xy(r, c)[1] for r, c in all_valid})
ax.set_yticks(yticks)
ax.set_yticklabels([f'{y:.2f}' for y in yticks], fontsize=6.5, color=COLOR_DIM)

ax.tick_params(colors=COLOR_DIM, labelsize=8)
ax.set_xlabel('column × col_pitch (nm)', color=COLOR_DIM, fontsize=8)
ax.set_ylabel('row × row_pitch + stagger (nm)', color=COLOR_DIM, fontsize=8)
ax.spines[:].set_color(COLOR_DIM)

# ── Title and legend ──────────────────────────────────────────────────────────
rule = (
    'Cell rule: val = (row + col%2) % 3   |   '
    'col_pitch = 1.125×√3 ≈ 1.9486 nm   |   row_pitch = 2.25 nm'
)
fig.text(0.5, 0.965, rule,
         ha='center', va='top', fontsize=8,
         color='#8b949e', transform=fig.transFigure)
fig.text(0.5, 0.985,
         f'NADOC Honeycomb — Staple Crossover Pairs (bp=0 view, {len(pairs)} pairs, looking down +Z)',
         ha='center', va='top', fontsize=11, fontweight='bold',
         color='#f0e050', transform=fig.transFigure)

legend_handles = [
    mpatches.Patch(color=COLOR_FWD, label='FORWARD scaffold cell  (val=0)'),
    mpatches.Patch(color=COLOR_REV, label='REVERSE scaffold cell  (val=1)'),
    mpatches.Patch(color=COLOR_HOLE, label='HOLE  (val=2) — excluded'),
    Line2D([0], [0], color=ARROW_FWD, linewidth=2.5, marker='>', markersize=8,
           label='Scaffold (FORWARD) at bp=0: phase=90° → east'),
    Line2D([0], [0], color=ARROW_REV, linewidth=2.5, marker='<', markersize=8,
           label='Scaffold (REVERSE) at bp=0: phase=150°+120°=270° → west'),
    Line2D([0], [0], color=STPL_COLOR, linewidth=1.8, marker='>', markersize=7,
           label='Staple at bp=0: 120° CW from scaffold'),
    mpatches.Patch(edgecolor='#aaaaaa', facecolor='none', linewidth=2,
                   label='Adjacent FORWARD/REVERSE pair — staple crossover location'),
]
fig.legend(handles=legend_handles, loc='lower center', ncol=3,
           fontsize=9, framealpha=0.15,
           labelcolor=COLOR_TEXT, facecolor='#161b22',
           edgecolor=COLOR_DIM, bbox_to_anchor=(0.5, 0.01))

fig.tight_layout(rect=[0, 0.09, 1, 0.96])

out = 'drawings/honeycomb_bp0_crossovers.png'
fig.savefig(out, dpi=150, facecolor=BG, bbox_inches='tight')
print(f'Saved {out}  ({len(pairs)} pairs highlighted)')
