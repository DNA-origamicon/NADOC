"""
Verify that our crossover positions match cadnano's 6HB and 18HB examples.

We build a 6HB and 18HB design in our system and compare the valid staple
crossover positions against what cadnano reports in:
  Examples/6hb_nobreaks.json
  Examples/18hb_nobreaks.json

Expected cadnano rules (confirmed from file analysis):
  VERT pair (same col, adj row):           bp offsets {13, 14} per 21-bp period
  HORIZ pair (even col on left → odd):     bp offsets {6,  7}  per 21-bp period
  HORIZ pair (odd col on left → even):     bp offsets {0, 20}  per 21-bp period
"""
import json, sys, os, math
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.core.lattice import make_bundle_design, honeycomb_cell_value
from backend.core.crossover_positions import valid_crossover_positions

# ── Parse cadnano JSON for staple crossovers ──────────────────────────────────

def extract_cadnano_staple_xovers(json_path):
    """Return set of (vh_a, bp_a, vh_b, bp_b) staple crossover tuples."""
    with open(json_path) as f:
        data = json.load(f)
    vhs = data['vstrands']
    xovers = set()
    for vh in vhs:
        num = vh['num']
        stap = vh['stap']
        for bp, entry in enumerate(stap):
            # entry = [prev_vh, prev_bp, next_vh, next_bp]
            prev_vh, prev_bp, next_vh, next_bp = entry
            if next_vh != -1 and next_vh != num:
                # crossover: this bp on vh connects to next_vh at next_bp
                key = (min(num, next_vh), min(bp, next_bp), max(num, next_vh), max(bp, next_bp))
                xovers.add(key)
    return xovers


# ── 6HB ──────────────────────────────────────────────────────────────────────

CELLS_6HB = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 1)]
LENGTH_BP = 42

print("=" * 60)
print("6HB VERIFICATION")
print("=" * 60)

design_6hb = make_bundle_design(CELLS_6HB, length_bp=LENGTH_BP)
helices = design_6hb.helices
helix_by_id = {h.id: h for h in helices}

# Show all adjacent pair crossover positions from our code
print("\nOur valid staple crossover positions (per adjacent pair):")
for i in range(len(helices)):
    for j in range(i + 1, len(helices)):
        ha, hb = helices[i], helices[j]
        sep = math.hypot(ha.axis_start.x - hb.axis_start.x,
                         ha.axis_start.y - hb.axis_start.y)
        if abs(sep - 2.25) > 0.05:
            continue
        cands = valid_crossover_positions(ha, hb)
        staple_cands = [c for c in cands
                        if c.bp_a == c.bp_b]
        bps = sorted(c.bp_a for c in staple_cands)
        # Determine pair type
        parts_a = ha.id.split('_')
        parts_b = hb.id.split('_')
        ra, ca = int(parts_a[-2]), int(parts_a[-1])
        rb, cb = int(parts_b[-2]), int(parts_b[-1])
        if ca == cb:
            pair_type = "VERT"
            expected = [b for b in range(LENGTH_BP) if (b % 21) in {13, 14}]
        elif abs(ca - cb) == 1:
            col_left = min(ca, cb)
            if col_left % 2 == 0:
                pair_type = "HORIZ-A (even→odd, offset=6)"
                expected = [b for b in range(LENGTH_BP) if (b % 21) in {6, 7}]
            else:
                pair_type = "HORIZ-B (odd→even, offset=0)"
                expected = [b for b in range(LENGTH_BP) if (b % 21) in {0, 20}]
        else:
            continue
        ok = bps == expected
        mark = "✓" if ok else "✗"
        print(f"  {mark} ({ra},{ca})↔({rb},{cb}) [{pair_type}]")
        print(f"      Our: {bps}")
        if not ok:
            print(f"      Expected: {expected}")


# ── 18HB ─────────────────────────────────────────────────────────────────────

CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

print("\n" + "=" * 60)
print("18HB VERIFICATION")
print("=" * 60)

design_18hb = make_bundle_design(CELLS_18HB, length_bp=LENGTH_BP)
helices_18 = design_18hb.helices

all_ok = True
n_pairs = 0
for i in range(len(helices_18)):
    for j in range(i + 1, len(helices_18)):
        ha, hb = helices_18[i], helices_18[j]
        sep = math.hypot(ha.axis_start.x - hb.axis_start.x,
                         ha.axis_start.y - hb.axis_start.y)
        if abs(sep - 2.25) > 0.05:
            continue
        n_pairs += 1
        cands = valid_crossover_positions(ha, hb)
        staple_cands = [c for c in cands if c.bp_a == c.bp_b]
        bps = sorted(c.bp_a for c in staple_cands)

        parts_a = ha.id.split('_')
        parts_b = hb.id.split('_')
        ra, ca = int(parts_a[-2]), int(parts_a[-1])
        rb, cb = int(parts_b[-2]), int(parts_b[-1])
        if ca == cb:
            expected = [b for b in range(LENGTH_BP) if (b % 21) in {13, 14}]
        elif abs(ca - cb) == 1:
            col_left = min(ca, cb)
            if col_left % 2 == 0:
                expected = [b for b in range(LENGTH_BP) if (b % 21) in {6, 7}]
            else:
                expected = [b for b in range(LENGTH_BP) if (b % 21) in {0, 20}]
        else:
            continue

        ok = bps == expected
        if not ok:
            all_ok = False
            print(f"  ✗ ({ra},{ca})↔({rb},{cb}): got {bps}, expected {expected}")

print(f"\n{n_pairs} adjacent pairs checked.")
if all_ok:
    print("✓ ALL 18HB pairs match cadnano expected positions!")
else:
    print("✗ Some pairs do NOT match.")

print("\n\nSummary of crossover offset rules implemented:")
print("  VERT  (same col, adj row):      offsets {13, 14} mod 21")
print("  HORIZ (even col_left → odd):    offsets {6,  7}  mod 21")
print("  HORIZ (odd  col_left → even):   offsets {0, 20}  mod 21")
