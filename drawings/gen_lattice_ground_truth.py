"""
Generate lattice_ground_truth.png — ground-truth reference for NADOC HC and SQ lattice geometry.

Two panels:
  Left:  Honeycomb lattice — cell positions, scaffold/staple backbone directions at bp=0,
         and NN pair types (p90 / p210 / p330) with staple crossover bp annotations.
  Right: Square lattice — cell positions, scaffold/staple backbone directions at bp=0,
         and neighbor crossover bp positions per direction (N/S/E/W).

Run from repo root:
    uv run python drawings/gen_lattice_ground_truth.py
"""

import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Circle
from matplotlib.lines import Line2D

# ── Shared constants ──────────────────────────────────────────────────────────

BG         = '#0d1117'
COLOR_FWD  = '#2979c4'   # FORWARD cell fill
COLOR_REV  = '#b04060'   # REVERSE cell fill
COLOR_HOLE = '#1e242c'   # hole fill
COLOR_TEXT = '#e6edf3'
COLOR_DIM  = '#6e7681'
SCAF_FWD   = '#a8d8ff'   # scaffold arrow, FORWARD cell
SCAF_REV   = '#f0a0b0'   # scaffold arrow, REVERSE cell
STPL_COLOR = '#ffd54f'   # staple arrow

# HC phase offsets (degrees) — FORWARD=322.2°, REVERSE=252.2°
HC_PHASE_FWD = 322.2
HC_PHASE_REV = 252.2

# SQ phase offsets (degrees) — FORWARD=345°, REVERSE=285°
SQ_PHASE_FWD = 345.0
SQ_PHASE_REV = 285.0

MINOR_GROOVE = 120.0     # degrees

# HC NN pair colours
P330_COLOR = '#00e5ff'
P90_COLOR  = '#76ff03'
P210_COLOR = '#ff6d00'

# SQ neighbor colours
SQ_E_COLOR = '#00e5ff'
SQ_N_COLOR = '#76ff03'
SQ_W_COLOR = '#ff6d00'
SQ_S_COLOR = '#d500f9'


def backbone_dir(phase_deg):
    """World XY direction of backbone bead at angle phase_deg.
    backbone_direction(θ) = (sin θ, −cos θ) for helices along +Z.
    """
    r = math.radians(phase_deg)
    return math.sin(r), -math.cos(r)


def draw_arrow(ax, cx, cy, dx, dy, color, length, lw=2.0, scale=14):
    ax.annotate(
        '',
        xy=(cx + dx * length, cy + dy * length),
        xytext=(cx, cy),
        arrowprops=dict(arrowstyle='->', color=color, lw=lw, mutation_scale=scale),
        zorder=8,
    )


# ── Honeycomb helpers ─────────────────────────────────────────────────────────

HC_LATTICE_R = 1.125
HC_COL_PITCH = HC_LATTICE_R * math.sqrt(3)   # ≈ 1.9486 nm
HC_ROW_PITCH = 2.25                            # nm
HC_CIRCLE_R  = HC_LATTICE_R * 0.80


def hc_cell_value(row, col):
    return (row + col % 2) % 3   # 0=FORWARD, 1=REVERSE, 2=HOLE


def hc_xy(row, col):
    x = col * HC_COL_PITCH
    y = row * HC_ROW_PITCH + (HC_LATTICE_R if (col % 2) == 0 else 0.0)
    return x, y


def draw_hc_panel(ax, rows=4, cols=5):
    ax.set_facecolor(BG)
    ax.set_aspect('equal')

    ARROW_L = HC_CIRCLE_R * 0.65

    # ── NN pair outlines ──────────────────────────────────────────────────────
    valid = [(r, c) for r in range(rows) for c in range(cols) if hc_cell_value(r, c) != 2]

    drawn_pairs = set()
    for r1, c1 in valid:
        v1 = hc_cell_value(r1, c1)
        if v1 != 0:   # only iterate from FORWARD helices
            continue
        x1, y1 = hc_xy(r1, c1)
        for r2, c2 in valid:
            v2 = hc_cell_value(r2, c2)
            if v2 != 1:
                continue
            x2, y2 = hc_xy(r2, c2)
            dist = math.hypot(x2 - x1, y2 - y1)
            if abs(dist - 2.25) > 0.05:
                continue
            angle_deg = math.degrees(math.atan2(y2 - y1, x2 - x1))
            angle_norm = angle_deg % 360

            # Classify pair type
            if 80 <= angle_norm <= 100:
                ptype, pcolor, label, xover_bps = 'p90',  P90_COLOR,  'p90\n{13,14}', '{13,14}'
            elif 200 <= angle_norm <= 220:
                ptype, pcolor, label, xover_bps = 'p210', P210_COLOR, 'p210\n{6,7}',  '{6,7}'
            elif 320 <= angle_norm <= 340:
                ptype, pcolor, label, xover_bps = 'p330', P330_COLOR, 'p330\n{0,20}', '{0,20}'
            else:
                continue

            pair_key = (min((r1,c1),(r2,c2)), max((r1,c1),(r2,c2)), ptype)
            if pair_key in drawn_pairs:
                continue
            drawn_pairs.add(pair_key)

            # Draw connecting line
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            ax.plot([x1, x2], [y1, y2], color=pcolor, lw=2.5, alpha=0.55, zorder=2)

            # Label at midpoint
            perp_x = -(y2 - y1) / dist
            perp_y =  (x2 - x1) / dist
            lx = mx + perp_x * 0.38
            ly = my + perp_y * 0.38
            ax.text(lx, ly, xover_bps, ha='center', va='center',
                    fontsize=6.5, color=pcolor, fontweight='bold', zorder=9)

    # ── Cells ─────────────────────────────────────────────────────────────────
    for row in range(rows):
        for col in range(cols):
            val = hc_cell_value(row, col)
            x, y = hc_xy(row, col)

            if val == 2:
                c = Circle((x, y), HC_CIRCLE_R * 0.45, color=COLOR_HOLE,
                           linewidth=0.8, linestyle='--', fill=True, zorder=4)
                ax.add_patch(c)
                ax.text(x, y, f'({row},{col})\nHOLE', ha='center', va='center',
                        fontsize=5, color=COLOR_DIM, zorder=5)
                continue

            face = COLOR_FWD if val == 0 else COLOR_REV
            c = Circle((x, y), HC_CIRCLE_R, color=face, alpha=0.85,
                       linewidth=0, zorder=4)
            ax.add_patch(c)

            # Scaffold and staple arrows.
            # phase_offset is always the FORWARD strand angle.
            # FORWARD cell: scaffold = FORWARD strand (phase), staple = REVERSE strand (phase+120°)
            # REVERSE cell: scaffold = REVERSE strand (phase+120°), staple = FORWARD strand (phase)
            phase = HC_PHASE_FWD if val == 0 else HC_PHASE_REV
            fwd_phase = phase
            rev_phase = phase + MINOR_GROOVE

            if val == 0:
                scaf_phase, stpl_phase = fwd_phase, rev_phase
            else:
                scaf_phase, stpl_phase = rev_phase, fwd_phase

            sdx, sdy = backbone_dir(scaf_phase)
            tdx, tdy = backbone_dir(stpl_phase)

            scaf_col = SCAF_FWD if val == 0 else SCAF_REV
            draw_arrow(ax, x, y, sdx, sdy, scaf_col, ARROW_L, lw=2.4)
            draw_arrow(ax, x, y, tdx, tdy, STPL_COLOR, ARROW_L * 0.75, lw=1.5, scale=11)

            # Labels
            dtype = 'FWD' if val == 0 else 'REV'
            ax.text(x, y + HC_CIRCLE_R * 0.55, f'({row},{col})', ha='center', va='center',
                    fontsize=6.5, fontweight='bold', color=COLOR_TEXT, zorder=9)
            ax.text(x, y - HC_CIRCLE_R * 0.45, dtype, ha='center', va='center',
                    fontsize=6, color=face, zorder=9)

    # ── Axis formatting ───────────────────────────────────────────────────────
    xs = [hc_xy(r, c)[0] for r, c in valid]
    ys = [hc_xy(r, c)[1] for r, c in valid]
    pad = HC_CIRCLE_R * 2.5
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)

    ax.set_title('Honeycomb Lattice\nphase: FWD=322.2° REV=252.2°  |  cell rule: (row + col%2) % 3',
                 color=COLOR_TEXT, fontsize=9, pad=8)
    ax.tick_params(colors=COLOR_DIM)
    ax.set_xlabel('X (nm)', color=COLOR_DIM, fontsize=8)
    ax.set_ylabel('Y (nm)', color=COLOR_DIM, fontsize=8)
    for sp in ax.spines.values():
        sp.set_color(COLOR_DIM)

    # Legend
    handles = [
        mpatches.Patch(color=COLOR_FWD, label='FORWARD cell (val=0)'),
        mpatches.Patch(color=COLOR_REV, label='REVERSE cell (val=1)'),
        Line2D([0],[0], color=SCAF_FWD, lw=2, marker='>', ms=7, label=f'Scaffold (FWD phase={HC_PHASE_FWD}°)'),
        Line2D([0],[0], color=SCAF_REV, lw=2, marker='>', ms=7, label=f'Scaffold (REV phase={HC_PHASE_REV}°)'),
        Line2D([0],[0], color=STPL_COLOR, lw=1.5, marker='>', ms=6, label='Staple (phase + 120°)'),
        Line2D([0],[0], color=P330_COLOR, lw=2.5, label='p330 pair → staple xovers {0,20}/21bp'),
        Line2D([0],[0], color=P90_COLOR,  lw=2.5, label='p90  pair → staple xovers {13,14}/21bp'),
        Line2D([0],[0], color=P210_COLOR, lw=2.5, label='p210 pair → staple xovers {6,7}/21bp'),
    ]
    ax.legend(handles=handles, loc='lower left', fontsize=6.5,
              framealpha=0.2, labelcolor=COLOR_TEXT,
              facecolor='#161b22', edgecolor=COLOR_DIM)


# ── Square lattice helpers ────────────────────────────────────────────────────

SQ_SPACING = 2.25   # nm, centre-to-centre
SQ_CIRCLE_R = SQ_SPACING * 0.35


def sq_cell_dir(row, col):
    return 0 if (row + col) % 2 == 0 else 1   # 0=FORWARD, 1=REVERSE


def sq_xy(row, col):
    return col * SQ_SPACING, row * SQ_SPACING


# SQ staple crossover offsets per 32-bp period, from FORWARD helix perspective
SQ_FWD_OFFSETS = {'E': [0, 31], 'N': [7, 8], 'W': [15, 16], 'S': [23, 24]}
SQ_REV_OFFSETS = {'W': [0, 31], 'S': [7, 8], 'E': [15, 16], 'N': [23, 24]}

DIR_COLORS = {'E': SQ_E_COLOR, 'N': SQ_N_COLOR, 'W': SQ_W_COLOR, 'S': SQ_S_COLOR}
DIR_DELTA  = {'E': (1,0), 'N': (0,1), 'W': (-1,0), 'S': (0,-1)}


def draw_sq_panel(ax, rows=4, cols=4):
    ax.set_facecolor(BG)
    ax.set_aspect('equal')

    ARROW_L = SQ_CIRCLE_R * 0.80

    # ── NN pair crossover labels ───────────────────────────────────────────────
    drawn_pairs = set()
    for row in range(rows):
        for col in range(cols):
            val = sq_cell_dir(row, col)
            offsets_map = SQ_FWD_OFFSETS if val == 0 else SQ_REV_OFFSETS
            x1, y1 = sq_xy(row, col)

            for direction, (dc, dr) in DIR_DELTA.items():
                r2, c2 = row + dr, col + dc
                if not (0 <= r2 < rows and 0 <= c2 < cols):
                    continue
                pair_key = tuple(sorted([(row, col), (r2, c2)]))
                if pair_key in drawn_pairs:
                    continue
                drawn_pairs.add(pair_key)

                x2, y2 = sq_xy(r2, c2)
                pcolor = DIR_COLORS[direction]
                bps = offsets_map.get(direction, [])
                if not bps:
                    continue

                ax.plot([x1, x2], [y1, y2], color=pcolor, lw=2.0, alpha=0.45, zorder=2)

                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                dxn = x2 - x1; dyn = y2 - y1
                dist = math.hypot(dxn, dyn)
                perp_x = -dyn / dist; perp_y = dxn / dist
                lx = mx + perp_x * 0.35
                ly = my + perp_y * 0.35
                ax.text(lx, ly, '{' + ','.join(map(str, bps)) + '}/32', ha='center', va='center',
                        fontsize=6, color=pcolor, fontweight='bold', zorder=9)

    # ── Cells ─────────────────────────────────────────────────────────────────
    for row in range(rows):
        for col in range(cols):
            val = sq_cell_dir(row, col)
            x, y = sq_xy(row, col)
            face = COLOR_FWD if val == 0 else COLOR_REV
            c = Circle((x, y), SQ_CIRCLE_R, color=face, alpha=0.85, linewidth=0, zorder=4)
            ax.add_patch(c)

            # Same logic as HC: phase_offset is the FORWARD strand angle.
            phase = SQ_PHASE_FWD if val == 0 else SQ_PHASE_REV
            fwd_phase = phase
            rev_phase = phase + MINOR_GROOVE

            if val == 0:
                scaf_phase, stpl_phase = fwd_phase, rev_phase
            else:
                scaf_phase, stpl_phase = rev_phase, fwd_phase

            sdx, sdy = backbone_dir(scaf_phase)
            tdx, tdy = backbone_dir(stpl_phase)

            scaf_col = SCAF_FWD if val == 0 else SCAF_REV
            draw_arrow(ax, x, y, sdx, sdy, scaf_col, ARROW_L, lw=2.2)
            draw_arrow(ax, x, y, tdx, tdy, STPL_COLOR, ARROW_L * 0.70, lw=1.4, scale=11)

            dtype = 'FWD' if val == 0 else 'REV'
            ax.text(x, y + SQ_CIRCLE_R * 0.55, f'({row},{col})', ha='center', va='center',
                    fontsize=6.5, fontweight='bold', color=COLOR_TEXT, zorder=9)
            ax.text(x, y - SQ_CIRCLE_R * 0.45, dtype, ha='center', va='center',
                    fontsize=6, color=face, zorder=9)

    # ── Axis formatting ───────────────────────────────────────────────────────
    valid = [(r, c) for r in range(rows) for c in range(cols)]
    xs = [sq_xy(r, c)[0] for r, c in valid]
    ys = [sq_xy(r, c)[1] for r, c in valid]
    pad = SQ_CIRCLE_R * 3.0
    ax.set_xlim(min(xs) - pad, max(xs) + pad)
    ax.set_ylim(min(ys) - pad, max(ys) + pad)

    ax.set_title('Square Lattice\nphase: FWD=345° REV=285°  |  cell rule: (row+col)%2 == 0 → FWD',
                 color=COLOR_TEXT, fontsize=9, pad=8)
    ax.tick_params(colors=COLOR_DIM)
    ax.set_xlabel('X (nm)', color=COLOR_DIM, fontsize=8)
    ax.set_ylabel('Y (nm)', color=COLOR_DIM, fontsize=8)
    for sp in ax.spines.values():
        sp.set_color(COLOR_DIM)

    handles = [
        mpatches.Patch(color=COLOR_FWD, label='FORWARD cell'),
        mpatches.Patch(color=COLOR_REV, label='REVERSE cell'),
        Line2D([0],[0], color=SCAF_FWD, lw=2, marker='>', ms=7, label=f'Scaffold (FWD phase={SQ_PHASE_FWD}°)'),
        Line2D([0],[0], color=SCAF_REV, lw=2, marker='>', ms=7, label=f'Scaffold (REV phase={SQ_PHASE_REV}°)'),
        Line2D([0],[0], color=STPL_COLOR, lw=1.5, marker='>', ms=6, label='Staple (phase + 120°)'),
        Line2D([0],[0], color=SQ_E_COLOR, lw=2, label='E neighbor → {0,31}/32bp'),
        Line2D([0],[0], color=SQ_N_COLOR, lw=2, label='N neighbor → {7,8}/32bp'),
        Line2D([0],[0], color=SQ_W_COLOR, lw=2, label='W neighbor → {15,16}/32bp'),
        Line2D([0],[0], color=SQ_S_COLOR, lw=2, label='S neighbor → {23,24}/32bp'),
    ]
    ax.legend(handles=handles, loc='lower left', fontsize=6.5,
              framealpha=0.2, labelcolor=COLOR_TEXT,
              facecolor='#161b22', edgecolor=COLOR_DIM)


# ── Compose figure ────────────────────────────────────────────────────────────

fig, (ax_hc, ax_sq) = plt.subplots(1, 2, figsize=(18, 10), facecolor=BG)

draw_hc_panel(ax_hc, rows=4, cols=5)
draw_sq_panel(ax_sq, rows=4, cols=4)

fig.suptitle(
    'NADOC Lattice Ground Truth  —  backbone directions at bp=0  (looking down +Z)',
    color='#f0e050', fontsize=13, fontweight='bold', y=0.98,
)

fig.tight_layout(rect=[0, 0, 1, 0.97])

out = 'drawings/lattice_ground_truth.png'
fig.savefig(out, dpi=150, facecolor=BG, bbox_inches='tight')
print(f'Saved {out}')
