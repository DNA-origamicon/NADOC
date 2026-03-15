"""
Experiment 14: Compare our crossover positions to cadnano ground truth.

Rules from cadnano 6HB+18HB reference files (period=21, DX pairs spaced 1bp apart):
  VERTICAL   (same col): offset = 13
  HORIZONTAL (same row, adjacent cols):
    col_left = min(col_a, col_b)
    (col_left%2)==(row%2) → offset = 6
    (col_left%2)!=(row%2) → offset = 0

Test strategy: build one pair of each type in MY system and compare.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))

from backend.core.lattice import make_bundle_design
from backend.core.crossover_positions import valid_crossover_positions, sync_cache, clear_cache

PERIOD  = 21
LEN_BP  = 63   # 3 full periods

def expected_bps(offset, length_bp):
    """All crossover positions given an offset."""
    result = []
    bp = offset
    while bp < length_bp:
        result.append(bp)
        if bp + 1 < length_bp:
            result.append(bp + 1)
        bp += PERIOD
    return sorted(result)

def run_pair(label, cells, expect_offset):
    clear_cache()
    design = make_bundle_design(cells, LEN_BP)
    ha, hb = design.helices[0], design.helices[1]
    positions = valid_crossover_positions(ha, hb)

    our_bps = sorted(set(c.bp_a for c in positions))
    exp_bps = expected_bps(expect_offset, LEN_BP)

    match = our_bps == exp_bps
    print(f'\n{label}')
    print(f'  Cells:    {cells}')
    print(f'  Expected offset={expect_offset}: {exp_bps}')
    print(f'  Got:                             {our_bps}')
    if not match:
        missing = [b for b in exp_bps if b not in our_bps]
        extra   = [b for b in our_bps if b not in exp_bps]
        print(f'  MISSING: {missing}')
        print(f'  EXTRA:   {extra}')
    print(f'  {"PASS ✓" if match else "FAIL ✗"}')
    return match

print(f'Testing with LEN_BP={LEN_BP} ({LEN_BP/PERIOD:.1f} periods)\n')

results = []

# 1. Horizontal offset=6: col_left%2==row%2 → (0%2==0%2) → cells (0,0),(0,1)
results.append(run_pair(
    'HORIZ offset=6  [(0,0)↔(0,1)]  col_left=0%2=0, row=0%2=0 → equal',
    [(0,0),(0,1)], 6))

# 2. Horizontal offset=0: col_left%2!=row%2 → (1%2!=0%2) → cells (0,1),(0,2)
results.append(run_pair(
    'HORIZ offset=0  [(0,1)↔(0,2)]  col_left=1%2=1, row=0%2=0 → different',
    [(0,1),(0,2)], 0))

# 3. Vertical offset=13: same col → cells (0,0),(1,0)
results.append(run_pair(
    'VERT  offset=13 [(0,0)↔(1,0)]  same col',
    [(0,0),(1,0)], 13))

# 4. Verify second horizontal type: (1,0),(1,1) → col_left=0%2=0, row=1%2=1 → different → offset=0
results.append(run_pair(
    'HORIZ offset=0  [(1,0)↔(1,1)]  col_left=0%2=0, row=1%2=1 → different',
    [(1,0),(1,1)], 0))

# 5. Verify second horizontal type: (1,1),(1,2) → col_left=1%2=1, row=1%2=1 → equal → offset=6
results.append(run_pair(
    'HORIZ offset=6  [(1,1)↔(1,2)]  col_left=1%2=1, row=1%2=1 → equal',
    [(1,1),(1,2)], 6))

print(f'\n{"="*50}')
print(f'SUMMARY: {sum(results)}/{len(results)} passed')
