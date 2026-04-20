"""
For each pair type, find the phase_offset that minimizes distance at the CADNANO expected bp.
Also check: what does our current code actually produce for these pairs?
"""
import math, sys, os, numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from backend.core.constants import (
    BDNA_TWIST_PER_BP_RAD as T, HELIX_RADIUS as R,
    HONEYCOMB_COL_PITCH, HONEYCOMB_ROW_PITCH, HONEYCOMB_LATTICE_RADIUS
)

MINOR = math.radians(120.0)
THRESHOLD = 0.75

def honeycomb_xy(row, col):
    x = col * HONEYCOMB_COL_PITCH
    y = row * HONEYCOMB_ROW_PITCH + (HONEYCOMB_LATTICE_RADIUS if col % 2 == 0 else 0)
    return x, y

ha = honeycomb_xy(0, 0)  # FORWARD: val=0
hb = honeycomb_xy(0, 1)  # REVERSE: val=1
hc = honeycomb_xy(0, 2)  # FORWARD: val=0
hd = honeycomb_xy(1, 0)  # REVERSE: val=1

def bead(hxy, phase, bp, is_rev):
    t = phase + bp * T + (MINOR if is_rev else 0)
    return hxy[0] + R*math.sin(t), hxy[1] - R*math.cos(t)

def d_staple(h_fwd, pf, h_rev, pr, bp):
    """Staple-staple distance at bp: REVERSE bead on FORWARD cell vs FORWARD bead on REVERSE cell."""
    ax, ay = bead(h_fwd, pf, bp, True)   # REVERSE bead on FORWARD cell
    bx, by = bead(h_rev, pr, bp, False)  # FORWARD bead on REVERSE cell
    return math.sqrt((ax-bx)**2 + (ay-by)**2)

# For each pair, show the distance profile at cadnano's expected bp positions
def analyze_pair(label, h_fwd, pf, h_rev, pr, expected_bps):
    print(f"\n{label}  (phi_fwd={math.degrees(pf):.0f}°, phi_rev={math.degrees(pr):.0f}°)")
    for bp in expected_bps:
        d = d_staple(h_fwd, pf, h_rev, pr, bp)
        status = "✓" if d < THRESHOLD else "✗"
        print(f"  bp={bp:2d}: d={d:.4f} nm {status}")
    # Full profile mod 21
    prof = [(i, d_staple(h_fwd, pf, h_rev, pr, i)) for i in range(63)]
    valid = [(i%21, d) for i,d in prof if d < THRESHOLD]
    if valid:
        by_pos = {}
        for pos, d in valid:
            if pos not in by_pos or d < by_pos[pos]:
                by_pos[pos] = d
        print(f"  Valid mod21: {sorted(by_pos.keys())} (min dist: {min(by_pos.values()):.4f})")
    else:
        min_bp, min_d = min(prof, key=lambda x: x[1])
        print(f"  No valid positions. Min: bp={min_bp} d={min_d:.4f}")

print("=== Current lattice.py values (42°, 342°) ===")
pf_cur = math.radians(42.0)
pr_cur = math.radians(342.0)
analyze_pair("HORIZ-6 (0,0)↔(0,1)", ha, pf_cur, hb, pr_cur, [6, 7, 8])
analyze_pair("HORIZ-0 (0,1)↔(0,2)", hc, pf_cur, hb, pr_cur, [0, 1, 20, 21])  # note: FORWARD=hc, REVERSE=hb
analyze_pair("VERT-13 (0,0)↔(1,0)", ha, pf_cur, hd, pr_cur, [13, 14, 15])

print("\n\n=== Find phi_fwd that places VERT-13 minimum at bp=13 ===")
# For VERT pair: REVERSE bead on FORWARD helix at ha, FORWARD bead on REVERSE helix at hd
# Δ = hd - ha = (0, 2.25), angle=90° [atan2(2.25, 0) = 90°]
# Min condition: REVERSE bead angle θ_A = 180° (facing north toward hd)
# θ_A = pf + 120° + 13*T = 180°
# → pf = 180° - 120° - 13*T = 60° - 13*34.3° = 60° - 445.9° = -385.9° ≡ -25.9° ≡ 334.1°
pf_vert = math.radians(180 - 120 - math.degrees(13*T) % 360)
pf_vert = (180 - 120 - math.degrees(13*T)) % 360
pf_vert_rad = math.radians(pf_vert)
print(f"phi_fwd for VERT-13 min at bp=13: {pf_vert:.1f}°")

# And for FORWARD bead on REVERSE helix to face south (toward ha):
# θ_B = pr + 13*T = 0° [facing south = 0°, since (0,-1) = (sin(0°),-cos(0°))]
# → pr = -13*T mod 360
pr_vert = (-math.degrees(13*T)) % 360
pr_vert_rad = math.radians(pr_vert)
print(f"phi_rev for VERT-13 min at bp=13: {pr_vert:.1f}°")

analyze_pair("VERT-13 with computed phases", ha, pf_vert_rad, hd, pr_vert_rad, [13, 14])
analyze_pair("HORIZ-6 with VERT-derived phases", ha, pf_vert_rad, hb, pr_vert_rad, [6, 7])
analyze_pair("HORIZ-0 with VERT-derived phases", hc, pf_vert_rad, hb, pr_vert_rad, [0, 1, 20])

print("\n\n=== Analytical: require HORIZ-6 min at bp=6 AND VERT-13 min at bp=13 ===")
# HORIZ-6: θ_A = pf + 120° + 6*T = 60° (face east-south = 60°, direction ha→hb)
# → pf = 60° - 120° - 6*34.3° = -60° - 205.8° = -265.8° ≡ 94.2°
pf_h6 = (60 - 120 - math.degrees(6*T)) % 360
pf_h6_rad = math.radians(pf_h6)
print(f"phi_fwd for HORIZ-6 min at bp=6: {pf_h6:.1f}°")

# From VERT-13: pf = 334.1° above. But from HORIZ-6: pf = 94.2°. Inconsistent.
# The two conditions require different pf. The average?
pf_avg = ((pf_h6 + pf_vert) / 2) % 360
print(f"Average phi_fwd: {pf_avg:.1f}°")

# Now for phi_rev: from HORIZ-6 direction ha→hb = (1.9486,-1.125) = 330°
# FORWARD bead on REVERSE helix at bp=6 should face hb→ha direction = 150°
# θ_B = pr + 6*T = 150° → pr = 150° - 205.8° = -55.8° ≡ 304.2°
pr_h6 = (150 - math.degrees(6*T)) % 360
pr_h6_rad = math.radians(pr_h6)
print(f"phi_rev for HORIZ-6 min at bp=6: {pr_h6:.1f}°")

# From VERT-13 above: pr = 54.1° (= (-13*34.3°) % 360 = -445.9° % 360 = -445.9+720=274.1... wait)
pr_vert2 = (-math.degrees(13*T)) % 360
print(f"phi_rev for VERT-13 min at bp=13 (facing south θ_B=0°): {pr_vert2:.1f}°")
# Hmm: FORWARD bead on REVERSE helix at hd should face hd→ha = (0,-2.25) = south
# For backbone direction (sin θ, -cos θ) ∝ (0,-1): sin θ=0, -cos θ=-1 → cos θ=1 → θ=0°
# θ_B = pr + 13*T = 0° → pr = -13*34.3° mod 360 = -445.9° + 2*360 = 274.1°
# Actually: (-445.9) % 360 = 360 - 445.9 + 360 = no... -445.9 + 2*360 = 274.1°
print(f"Reconciling: pr_h6={pr_h6:.1f}°, pr_vert={(-math.degrees(13*T))%360:.1f}°")

# Test with pf=94.2°, pr=304.2° (HORIZ-6 centered)
analyze_pair("HORIZ-6 with optimal phases", ha, pf_h6_rad, hb, pr_h6_rad, [6, 7])
analyze_pair("HORIZ-0 with HORIZ-6 phases", hc, pf_h6_rad, hb, pr_h6_rad, [0, 1, 20])
analyze_pair("VERT-13 with HORIZ-6 phases", ha, pf_h6_rad, hd, pr_h6_rad, [13, 14])
