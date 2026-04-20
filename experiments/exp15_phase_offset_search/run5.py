"""
Find (phi_fwd, phi_rev) where all three pair types simultaneously have
staple-staple distance < 0.75nm at CADNANO expected bp positions.

cadnano target bp (first of DX pair per period):
  HORIZ-6: bp=6
  HORIZ-0: bp=0  (from h2's perspective)
  VERT-13: bp=13
"""
import math, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
from backend.core.constants import BDNA_TWIST_PER_BP_RAD as T, HELIX_RADIUS as R
MINOR = math.radians(120.0)
THRESHOLD = 0.75

# Helix centres (using constants from backend)
from backend.core.constants import HONEYCOMB_COL_PITCH, HONEYCOMB_ROW_PITCH, HONEYCOMB_LATTICE_RADIUS
def hxy(row, col):
    return col*HONEYCOMB_COL_PITCH, row*HONEYCOMB_ROW_PITCH + (HONEYCOMB_LATTICE_RADIUS if col%2==0 else 0)

ha = hxy(0,0); hb = hxy(0,1); hc = hxy(0,2); hd = hxy(1,0)

def d_staple_bp(h_fwd, pf, h_rev, pr, bp):
    """Staple-staple distance: REVERSE bead on FORWARD helix vs FORWARD bead on REVERSE helix."""
    ta = pf + bp*T + MINOR; tb = pr + bp*T
    ax, ay = h_fwd[0]+R*math.sin(ta), h_fwd[1]-R*math.cos(ta)
    bx, by = h_rev[0]+R*math.sin(tb), h_rev[1]-R*math.cos(tb)
    return math.sqrt((ax-bx)**2+(ay-by)**2)

# Grid search at 0.5° resolution
print("Searching for (phi_fwd, phi_rev) with all targets < 0.75nm...")
hits = []
for pf_d in range(0, 720, 1):  # search full 2 periods to catch all solutions
    pf = math.radians(pf_d % 360)
    for pr_d in range(0, 720, 1):
        pr = math.radians(pr_d % 360)
        d1 = d_staple_bp(ha, pf, hb, pr, 6)   # HORIZ-6
        d2 = d_staple_bp(hc, pf, hb, pr, 0)   # HORIZ-0 (note: FORWARD=hc, REVERSE=hb)
        d3 = d_staple_bp(ha, pf, hd, pr, 13)  # VERT-13
        if d1 < THRESHOLD and d2 < THRESHOLD and d3 < THRESHOLD:
            hits.append((pf_d%360, pr_d%360, d1, d2, d3))

if not hits:
    print("No solution found at 0.75nm threshold.")
    # Try with larger threshold
    for th in [0.80, 0.85, 0.90, 0.95, 1.0, 1.2, 1.5]:
        hits2 = []
        for pf_d in range(0, 360, 2):
            pf = math.radians(pf_d)
            for pr_d in range(0, 360, 2):
                pr = math.radians(pr_d)
                d1 = d_staple_bp(ha, pf, hb, pr, 6)
                d2 = d_staple_bp(hc, pf, hb, pr, 0)
                d3 = d_staple_bp(ha, pf, hd, pr, 13)
                if d1 < th and d2 < th and d3 < th:
                    hits2.append((pf_d, pr_d, d1, d2, d3, max(d1,d2,d3)))
        if hits2:
            best = min(hits2, key=lambda x: x[5])
            print(f"Threshold {th:.2f}: found {len(hits2)} solutions. Best: phi_fwd={best[0]}° phi_rev={best[1]}° max_d={best[5]:.4f}")
            print(f"  d_H6={best[2]:.4f} d_H0={best[3]:.4f} d_V13={best[4]:.4f}")
            break
else:
    print(f"Found {len(hits)} solutions!")
    # Show best (minimum max distance)
    hits.sort(key=lambda x: max(x[2],x[3],x[4]))
    print(f"Best: phi_fwd={hits[0][0]}° phi_rev={hits[0][1]}° "
          f"d_H6={hits[0][2]:.4f} d_H0={hits[0][3]:.4f} d_V13={hits[0][4]:.4f}")
    # Show all unique solutions mod 21 period
    seen = set()
    print("\nAll solutions:")
    for h in hits[:20]:
        key = (h[0]//10, h[1]//10)
        if key not in seen:
            seen.add(key)
            print(f"  phi_fwd={h[0]}° phi_rev={h[1]}°: d_H6={h[2]:.4f} d_H0={h[3]:.4f} d_V13={h[4]:.4f}")

# Also check: what if the HORIZ-0 pair uses bp=20 (not bp=0) as target?
print("\n\nSearching with HORIZ-0 target at bp=20 instead...")
hits_20 = []
for pf_d in range(0, 360):
    pf = math.radians(pf_d)
    for pr_d in range(0, 360):
        pr = math.radians(pr_d)
        d1 = d_staple_bp(ha, pf, hb, pr, 6)   # HORIZ-6
        d2 = d_staple_bp(hc, pf, hb, pr, 20)  # HORIZ-0 at bp=20
        d3 = d_staple_bp(ha, pf, hd, pr, 13)  # VERT-13
        if d1 < THRESHOLD and d2 < THRESHOLD and d3 < THRESHOLD:
            hits_20.append((pf_d, pr_d, d1, d2, d3))

if hits_20:
    hits_20.sort(key=lambda x: max(x[2],x[3],x[4]))
    print(f"Found {len(hits_20)} solutions with bp=20 target!")
    print(f"Best: phi_fwd={hits_20[0][0]}° phi_rev={hits_20[0][1]}°")
else:
    print("No solution with bp=20 target either.")
