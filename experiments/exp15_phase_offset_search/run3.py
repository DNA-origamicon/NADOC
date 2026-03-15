"""
Targeted test: phi_fwd=90, phi_rev=210 based on geometric analysis.

Key insight: with all-positive twist, the FORWARD backbone on FORWARD cell at bp=0
should point EAST (toward the adjacent cell on the right). This gives phi_fwd=90°.
For the REVERSE cell, at bp=0, the staple (FORWARD bead) should point toward the
adjacent FORWARD cell. For HORIZ-6 pair (0,0)↔(0,1), this direction is 120°,
giving phi_rev = 120°... but let's check all pairs numerically.

Also test the analytical result from memory notes:
  FORWARD: 90° (correct per notes)
  REVERSE: 150° (claimed correct in memory/notes — "fix: change 330° → 150°")
"""
import math, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from backend.core.constants import (
    BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD as T,
    HELIX_RADIUS as R, HONEYCOMB_COL_PITCH, HONEYCOMB_ROW_PITCH, HONEYCOMB_LATTICE_RADIUS
)

MINOR = math.radians(120.0)
THRESHOLD = 0.75

def honeycomb_xy(row, col):
    x = col * HONEYCOMB_COL_PITCH
    y = row * HONEYCOMB_ROW_PITCH + (HONEYCOMB_LATTICE_RADIUS if col % 2 == 0 else 0)
    return x, y

ha_xy = honeycomb_xy(0, 0)  # FORWARD
hb_xy = honeycomb_xy(0, 1)  # REVERSE
hc_xy = honeycomb_xy(0, 2)  # FORWARD
hd_xy = honeycomb_xy(1, 0)  # REVERSE

def bead_pos(hx, hy, phase, bp, is_rev_bead):
    """XY position of backbone bead. is_rev_bead=True → add MINOR_GROOVE_ANGLE."""
    theta = phase + bp * T + (MINOR if is_rev_bead else 0)
    return hx + R * math.sin(theta), hy - R * math.cos(theta)

def dist(hx_a, hy_a, phase_a, is_rev_a, hx_b, hy_b, phase_b, is_rev_b, bp):
    ax, ay = bead_pos(hx_a, hy_a, phase_a, bp, is_rev_a)
    bx, by = bead_pos(hx_b, hy_b, phase_b, bp, is_rev_b)
    return math.sqrt((ax-bx)**2 + (ay-by)**2)

def profile(hx_a, hy_a, pf_a, rv_a, hx_b, hy_b, pf_b, rv_b, N=63):
    return [(i, dist(hx_a,hy_a,pf_a,rv_a, hx_b,hy_b,pf_b,rv_b, i)) for i in range(N)]

def valid_bps(profile_data, threshold):
    return [i for i,d in profile_data if d < threshold]

def show_pair(label, hx_a, hy_a, pf_a, rv_a, hx_b, hy_b, pf_b, rv_b, expected_bps_mod21):
    prof = profile(hx_a, hy_a, pf_a, rv_a, hx_b, hy_b, pf_b, rv_b)
    vbps = valid_bps(prof, THRESHOLD)
    min_bp, min_d = min(prof, key=lambda x: x[1])
    print(f"  {label}: min bp={min_bp} d={min_d:.4f}  valid={vbps[:10]}...")
    vmod = sorted(set(b % 21 for b in vbps))
    print(f"    valid mod 21: {vmod}  expected: {expected_bps_mod21}")

def test(label, phi_fwd_deg, phi_rev_deg):
    pf = math.radians(phi_fwd_deg)
    pr = math.radians(phi_rev_deg)
    print(f"\n=== {label}: phi_fwd={phi_fwd_deg}° phi_rev={phi_rev_deg}° ===")
    # Staple = REVERSE bead on FORWARD cell; FORWARD bead on REVERSE cell
    show_pair("HORIZ-6 (0,0)↔(0,1) staple-staple",
              *ha_xy, pf, True,   # REVERSE bead on FORWARD cell
              *hb_xy, pr, False,  # FORWARD bead on REVERSE cell
              [6, 7])
    show_pair("HORIZ-0 (0,1)↔(0,2) staple-staple",
              *hb_xy, pr, False,  # FORWARD bead on REVERSE cell
              *hc_xy, pf, True,   # REVERSE bead on FORWARD cell
              [0, 1, 20])  # 0 and 20 are the DX pair (20≡-1 mod 21)
    show_pair("VERT-13  (0,0)↔(1,0) staple-staple",
              *ha_xy, pf, True,   # REVERSE bead on FORWARD cell
              *hd_xy, pr, False,  # FORWARD bead on REVERSE cell
              [13, 14])

# Test from memory notes:
test("Memory note claim", 90, 150)

# Test from my geometric analysis (FORWARD=90°, REVERSE=120°):
test("Geometric analysis", 90, 120)

# Current values in lattice.py:
test("Current lattice.py", 42, 342)

# Fine-grained search for best result:
print("\n\n=== Fine-grained search (1° steps) ===")
best_score = 1e9
best_p = None
for pf_d in range(0, 360):
    for pr_d in range(0, 360):
        pf = math.radians(pf_d)
        pr = math.radians(pr_d)
        # HORIZ-6: staple-staple
        prof1 = profile(*ha_xy, pf, True, *hb_xy, pr, False, 63)
        v1 = valid_bps(prof1, THRESHOLD)
        if not v1: continue
        # HORIZ-0: staple-staple
        prof2 = profile(*hb_xy, pr, False, *hc_xy, pf, True, 63)
        v2 = valid_bps(prof2, THRESHOLD)
        if not v2: continue
        # VERT-13: staple-staple
        prof3 = profile(*ha_xy, pf, True, *hd_xy, pr, False, 63)
        v3 = valid_bps(prof3, THRESHOLD)
        if not v3: continue

        # Score: how close are valid bps to expected mod 21?
        # HORIZ-6: expect {6,7}; HORIZ-0: expect {0,1,20}; VERT-13: expect {13,14}
        m1 = set(b % 21 for b in v1)
        m2 = set(b % 21 for b in v2)
        m3 = set(b % 21 for b in v3)

        hit1 = len({6,7} & m1)
        hit2 = len({0,1,20} & m2)
        hit3 = len({13,14} & m3)
        score = -(hit1 + hit2 + hit3)  # negative = fewer hits = worse

        if score < best_score:
            best_score = score
            best_p = (pf_d, pr_d, sorted(m1), sorted(m2), sorted(m3))

if best_p:
    pf_d, pr_d, m1, m2, m3 = best_p
    print(f"Best: phi_fwd={pf_d}° phi_rev={pr_d}° hits={-best_score}")
    print(f"  HORIZ-6 mod21: {m1}  (want [6,7])")
    print(f"  HORIZ-0 mod21: {m2}  (want [0,1,20])")
    print(f"  VERT-13 mod21: {m3}  (want [13,14])")
