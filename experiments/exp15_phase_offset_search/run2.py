"""
Test whether REVERSE helices need negative twist in our model.

From cadnano 6HB analysis:
  h0 (FORWARD, (0,1.125)) ↔ h5 (REVERSE, (1.9486,0)): staple xovers at bp=6 and 7
  h1 (REVERSE, (1.9486,0)) ↔ h2 (FORWARD, (3.8971,1.125)): staple xovers at bp=0 and 20
  h0 (FORWARD, (0,1.125)) ↔ h1 (REVERSE, (0,3.375)): staple xovers at bp=13 and 14

Note: h1 is at same XY as h5 for the "col=13 → but different rows".
Actually h1 (row=12,col=13): x=13*1.9486, y=12*2.25+0=27 -- NO, these are NOT at (0,..),(1.9486,..).
The 6HB cells in cadnano use THEIR row/col, not mine.

My cells in the experiment use MY indexing:
  My (row=0,col=0) FORWARD  = cadnano h0 equivalent
  My (row=0,col=1) REVERSE  = cadnano h5 equivalent (horizontal neighbor)
  My (row=1,col=0) REVERSE  = cadnano h1 equivalent (vertical neighbor)
  My (row=0,col=2) FORWARD  = ... further neighbor

Key test: does negative twist for REVERSE helices produce the right crossover positions?
"""
import math, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from backend.core.constants import (
    BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD as T,
    HELIX_RADIUS as R, HONEYCOMB_COL_PITCH, HONEYCOMB_ROW_PITCH, HONEYCOMB_LATTICE_RADIUS
)

def honeycomb_xy(row, col):
    x = col * HONEYCOMB_COL_PITCH
    y = row * HONEYCOMB_ROW_PITCH + (HONEYCOMB_LATTICE_RADIUS if col % 2 == 0 else 0)
    return x, y

def bead_xy(hx, hy, phase, bp, twist_sign=+1):
    """Backbone bead XY position. twist_sign=+1 for FORWARD cells, -1 for REVERSE."""
    theta = phase + bp * T * twist_sign
    return hx + R * math.sin(theta), hy - R * math.cos(theta)

def dist_xy(hx_a, hy_a, phase_a, sign_a, dir_a,
            hx_b, hy_b, phase_b, sign_b, dir_b, bp):
    """Distance between two backbone beads at same bp.
    dir_a/b: 0=FORWARD bead, 1=REVERSE bead (REVERSE adds MINOR_GROOVE_ANGLE=120°)
    """
    MINOR = math.radians(120.0)
    angle_a = phase_a + bp * T * sign_a + (MINOR if dir_a == 1 else 0)
    angle_b = phase_b + bp * T * sign_b + (MINOR if dir_b == 1 else 0)
    ax = hx_a + R * math.sin(angle_a)
    ay = hy_a - R * math.cos(angle_a)
    bx = hx_b + R * math.sin(angle_b)
    by = hy_b - R * math.cos(angle_b)
    return math.sqrt((ax-bx)**2 + (ay-by)**2)

def find_min_bp(hxa, hya, pa, sa, da, hxb, hyb, pb, sb, db, N=63):
    """Return (min_bp, min_dist) for same-bp distance over N bps."""
    dists = [dist_xy(hxa, hya, pa, sa, da, hxb, hyb, pb, sb, db, i) for i in range(N)]
    i = min(range(N), key=lambda i: dists[i])
    return i, dists[i]

# Helix centres for MY cell system
ha_xy = honeycomb_xy(0, 0)  # FORWARD (val=0)
hb_xy = honeycomb_xy(0, 1)  # REVERSE (val=1) -- horizontal neighbor
hc_xy = honeycomb_xy(0, 2)  # FORWARD (val=0) -- 2nd horizontal
hd_xy = honeycomb_xy(1, 0)  # REVERSE (val=1) -- vertical neighbor

print(f"FORWARD (0,0): {ha_xy}")
print(f"REVERSE (0,1): {hb_xy}")
print(f"FORWARD (0,2): {hc_xy}")
print(f"REVERSE (1,0): {hd_xy}")

# Expected from cadnano:
# HORIZ pair (0,0)↔(0,1): staple xovers at bp=6 and 7 (from h5 perspective at 6, h0 at 7)
# HORIZ pair (0,1)↔(0,2): staple xovers at bp=0 and 20 (h2 at 0, h1 at 20)
# VERT  pair (0,0)↔(1,0): staple xovers at bp=13 and 14

# Staple on FORWARD cell = REVERSE bead (dir=1)
# Staple on REVERSE cell = FORWARD bead (dir=0)

# Sign convention test: standard (all +1) vs reverse (-1 for REVERSE cells)
print("\n" + "="*60)
print("Testing: all POSITIVE twist")
print("="*60)

# Try to find best φ_fwd, φ_rev for all-positive-twist model
from itertools import product

def test_phases(phi_fwd_deg, phi_rev_deg, twist_sign_fwd=1, twist_sign_rev=1):
    pf = math.radians(phi_fwd_deg)
    pr = math.radians(phi_rev_deg)

    # Pair 1: HORIZ (0,0)↔(0,1) -- FORWARD→REVERSE
    # Staple: REVERSE bead on (0,0) ↔ FORWARD bead on (0,1)
    bp1_fwd, d1_fwd = find_min_bp(*ha_xy, pf, twist_sign_fwd, 1,  # REVERSE bead on FORWARD cell
                                    *hb_xy, pr, twist_sign_rev, 0)  # FORWARD bead on REVERSE cell

    # Pair 2: HORIZ (0,1)↔(0,2) -- REVERSE→FORWARD
    bp2_fwd, d2_fwd = find_min_bp(*hb_xy, pr, twist_sign_rev, 0,  # FORWARD bead on REVERSE cell
                                    *hc_xy, pf, twist_sign_fwd, 1)  # REVERSE bead on FORWARD cell

    # Pair 3: VERT (0,0)↔(1,0) -- FORWARD→REVERSE
    bp3_fwd, d3_fwd = find_min_bp(*ha_xy, pf, twist_sign_fwd, 1,  # REVERSE bead on FORWARD cell
                                    *hd_xy, pr, twist_sign_rev, 0)  # FORWARD bead on REVERSE cell
    return bp1_fwd, d1_fwd, bp2_fwd, d2_fwd, bp3_fwd, d3_fwd

THRESHOLD = 0.75

# Quick scan
best_score = 1e9
best_params = None
for phi_fwd in range(0, 360, 2):
    for phi_rev in range(0, 360, 2):
        bp1, d1, bp2, d2, bp3, d3 = test_phases(phi_fwd, phi_rev, 1, 1)
        if d1 > THRESHOLD or d2 > THRESHOLD or d3 > THRESHOLD:
            continue
        # HORIZ-6: min at 6 or 7
        # HORIZ-0: min at 0 or 20 (=21-1)
        # VERT-13: min at 13 or 14
        s1 = min(abs(bp1-6), abs(bp1-7))
        s2 = min(abs(bp2-0), abs(bp2-20))
        s3 = min(abs(bp3-13), abs(bp3-14))
        score = s1 + s2 + s3
        if score < best_score:
            best_score = score
            best_params = (phi_fwd, phi_rev, bp1, d1, bp2, d2, bp3, d3)

if best_params:
    pf, pr, b1,d1,b2,d2,b3,d3 = best_params
    print(f"Best (all +twist): φ_fwd={pf}° φ_rev={pr}° score={best_score}")
    print(f"  HORIZ-6: bp={b1} d={d1:.4f}  HORIZ-0: bp={b2} d={d2:.4f}  VERT-13: bp={b3} d={d3:.4f}")
else:
    print("No solution found within threshold.")

print("\n" + "="*60)
print("Testing: NEGATIVE twist for REVERSE cells")
print("="*60)

best_score2 = 1e9
best_params2 = None
for phi_fwd in range(0, 360, 2):
    for phi_rev in range(0, 360, 2):
        bp1, d1, bp2, d2, bp3, d3 = test_phases(phi_fwd, phi_rev, +1, -1)
        if d1 > THRESHOLD or d2 > THRESHOLD or d3 > THRESHOLD:
            continue
        s1 = min(abs(bp1-6), abs(bp1-7))
        s2 = min(abs(bp2-0), abs(bp2-20))
        s3 = min(abs(bp3-13), abs(bp3-14))
        score = s1 + s2 + s3
        if score < best_score2:
            best_score2 = score
            best_params2 = (phi_fwd, phi_rev, bp1, d1, bp2, d2, bp3, d3)

if best_params2:
    pf, pr, b1,d1,b2,d2,b3,d3 = best_params2
    print(f"Best (REVERSE -twist): φ_fwd={pf}° φ_rev={pr}° score={best_score2}")
    print(f"  HORIZ-6: bp={b1} d={d1:.4f}  HORIZ-0: bp={b2} d={d2:.4f}  VERT-13: bp={b3} d={d3:.4f}")
else:
    print("No solution found within threshold.")
