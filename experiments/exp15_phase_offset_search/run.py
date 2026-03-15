"""
Find correct phase_offset values so our geometry matches cadnano crossover positions.

For XY-plane helices along Z:
  frame[:,0] = [0,-1,0], frame[:,1] = [1,0,0]
  radial(θ) = cos(θ)*[0,-1,0] + sin(θ)*[1,0,0] = [sin(θ), -cos(θ), 0]
  backbone_XY = (hx + R*sin(θ), hy - R*cos(θ))

cadnano ground truth (period=21, DX pairs at offset and offset+1):
  HORIZ (0,0)↔(0,1): offset=6  → min dist at bp=6
  HORIZ (0,1)↔(0,2): offset=0  → min dist at bp=0
  VERT  (0,0)↔(1,0): offset=13 → min dist at bp=13

Crossover type: staple↔staple
  (0,0) FORWARD scaffold → REVERSE backbone is the staple   [angle = φ_fwd + bp*twist + 120°]
  (0,1) REVERSE scaffold → FORWARD backbone is the staple   [angle = φ_rev + bp*twist]
"""
import math
import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.core.constants import (
    BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD, HELIX_RADIUS,
    HONEYCOMB_COL_PITCH, HONEYCOMB_ROW_PITCH, HONEYCOMB_LATTICE_RADIUS,
)

MINOR = math.radians(120.0)

def honeycomb_xy(row, col):
    x = col * HONEYCOMB_COL_PITCH
    y = row * HONEYCOMB_ROW_PITCH + (HONEYCOMB_LATTICE_RADIUS if col % 2 == 0 else 0)
    return x, y

def backbone_xy(hx, hy, phase, bp):
    """XY position of backbone bead at bp, given helix centre (hx,hy) and angular phase."""
    theta = phase + bp * BDNA_TWIST_PER_BP_RAD
    return hx + HELIX_RADIUS * math.sin(theta), hy - HELIX_RADIUS * math.cos(theta)

def same_bp_dist(hx_a, hy_a, phase_a, hx_b, hy_b, phase_b, bp):
    ax, ay = backbone_xy(hx_a, hy_a, phase_a, bp)
    bx, by = backbone_xy(hx_b, hy_b, phase_b, bp)
    return math.sqrt((ax-bx)**2 + (ay-by)**2)

def find_min_bp(hx_a, hy_a, phase_a, hx_b, hy_b, phase_b, length_bp=63):
    """Return the bp index (0..length_bp-1) that gives minimum staple-staple distance."""
    dists = [same_bp_dist(hx_a, hy_a, phase_a, hx_b, hy_b, phase_b, bp) for bp in range(length_bp)]
    return int(np.argmin(dists)), min(dists)

# helix centres
ha_xy = honeycomb_xy(0, 0)  # FORWARD cell: val=0
hb_xy = honeycomb_xy(0, 1)  # REVERSE cell: val=1
hc_xy = honeycomb_xy(0, 2)  # FORWARD cell: val=0  (col=2, val=(0+0)%3=0)
hd_xy = honeycomb_xy(1, 0)  # REVERSE cell: val=1  (row=1,col=0, val=(1+0)%3=1)

print("Helix centres:")
print(f"  (0,0) FORWARD: {ha_xy}")
print(f"  (0,1) REVERSE: {hb_xy}")
print(f"  (0,2) FORWARD: {hc_xy}")
print(f"  (1,0) REVERSE: {hd_xy}")

# For FORWARD helix: scaffold=FORWARD, staple=REVERSE → staple bead angle = φ_fwd + MINOR
# For REVERSE helix: scaffold=REVERSE, staple=FORWARD → staple bead angle = φ_rev (plain phase)
# We search over φ_fwd (FORWARD phase) and derive φ_rev relationship.
# Both are free parameters, but cadnano has a specific convention we need to match.

# The cadnano convention: at bp=0 the scaffold backbone points TOWARD the adjacent scaffold helix
# (inner groove faces neighbor). Let's search φ_fwd in [0, 2π) at fine resolution.

RESOLUTION = 0.001  # radians
MIN_DIST_THRESHOLD = 0.75  # nm

print("\n=== Searching for phase_offset values ===\n")

best_score = 1e9
best_fwd = None
best_rev = None

# Grid search over FORWARD and REVERSE phase offsets independently
# Target: for each pair, staple-staple min distance is at the expected bp
# Pairs and their expected minimum bp (first occurrence, bp < 21):
# HORIZ (0,0)↔(0,1): REVERSE staple on ha ↔ FORWARD staple on hb → target bp=6
# HORIZ (0,1)↔(0,2): FORWARD staple on hb ↔ REVERSE staple on hc → target bp=0
# VERT  (0,0)↔(1,0): REVERSE staple on ha ↔ FORWARD staple on hd → target bp=13

# Iterate φ_fwd, φ_rev on 0.5° grid
step = math.radians(0.5)
results = []

for fwd_deg in range(0, 360):
    phi_fwd = math.radians(fwd_deg)
    # FORWARD helix staple = REVERSE direction → phase = phi_fwd + MINOR
    phase_ha_staple = phi_fwd + MINOR  # REVERSE backbone on ha (FORWARD cell)
    phase_hc_staple = phi_fwd + MINOR  # REVERSE backbone on hc (FORWARD cell)

    for rev_deg in range(0, 360):
        phi_rev = math.radians(rev_deg)
        # REVERSE helix staple = FORWARD direction → phase = phi_rev
        phase_hb_staple = phi_rev  # FORWARD backbone on hb (REVERSE cell)
        phase_hd_staple = phi_rev  # FORWARD backbone on hd (REVERSE cell)

        # Find minimum bp for each pair (within first period, 0..20)
        bp1, d1 = find_min_bp(*ha_xy, phase_ha_staple, *hb_xy, phase_hb_staple, 21)
        bp2, d2 = find_min_bp(*hb_xy, phase_hb_staple, *hc_xy, phase_hc_staple, 21)
        bp3, d3 = find_min_bp(*ha_xy, phase_ha_staple, *hd_xy, phase_hd_staple, 21)

        score = abs(bp1 - 6) + abs(bp2 - 0) + abs(bp3 - 13)

        if score < best_score and d1 < MIN_DIST_THRESHOLD and d2 < MIN_DIST_THRESHOLD and d3 < MIN_DIST_THRESHOLD:
            best_score = score
            best_fwd = fwd_deg
            best_rev = rev_deg
            best_dists = (d1, d2, d3)
            best_bps = (bp1, bp2, bp3)

print(f"Best FORWARD phase: {best_fwd}°  (φ_fwd = {best_fwd}°)")
print(f"Best REVERSE phase: {best_rev}°  (φ_rev = {best_rev}°)")
print(f"Score: {best_score}")
print(f"Min bp found: HORIZ-6={best_bps[0]}, HORIZ-0={best_bps[1]}, VERT-13={best_bps[2]}")
print(f"Min dists:    HORIZ-6={best_dists[0]:.4f}, HORIZ-0={best_dists[1]:.4f}, VERT-13={best_dists[2]:.4f}")
print(f"\nphase_offset values to use in lattice.py:")
print(f"  FORWARD cell: math.radians({best_fwd}.0)")
print(f"  REVERSE cell: math.radians({best_rev}.0)")
