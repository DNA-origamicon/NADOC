"""
Experiment: autocrossover placement correctness for 6HB at different lattice locations.

Two 6HB designs are tested:
  - RING_1_1: cells ringing hole (1,1)  — the canonical CELLS_6HB
  - RING_2_2: cells ringing hole (2,2)  — translated 6HB

For each design at 420 bp we run the full workflow:
  auto_scaffold (end_to_end) → make_prebreak → make_auto_crossover

Then we verify:
  1. Every expected crossover position from the HC lookup table has a placed
     cross-helix domain transition in the final strand topology.
  2. No extra cross-helix transitions exist at positions not in the table.
  3. The distribution of crossovers is uniform across the helix length
     (no clustering / stopping before the far end).

Run from repo root:
    uv run python experiments/exp_crossover_placement_6hb.py
"""

from __future__ import annotations

import math
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.crossover_positions import valid_crossover_positions
from backend.core.lattice import (
    auto_scaffold,
    make_auto_crossover,
    make_bundle_design,
    make_prebreak,
)
from backend.core.models import Direction, StrandType

# ── Cell layouts ──────────────────────────────────────────────────────────────

RING_1_1 = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 1)]   # hole at (1,1)
RING_2_2 = [(1, 2), (2, 1), (2, 3), (3, 1), (3, 2), (3, 3)]   # hole at (2,2)

LENGTH_BP = 420

# ── Helpers ───────────────────────────────────────────────────────────────────


def _placed_xovers(design) -> dict[tuple[str, str], set[int]]:
    """Return {(helix_a_id, helix_b_id): {bp, ...}} for every cross-helix
    domain transition in the strand topology (canonical order: a < b by id)."""
    placed: dict[tuple[str, str], set[int]] = defaultdict(set)
    for strand in design.strands:
        if strand.strand_type == StrandType.SCAFFOLD:
            continue
        for i in range(len(strand.domains) - 1):
            d0, d1 = strand.domains[i], strand.domains[i + 1]
            if d0.helix_id == d1.helix_id:
                continue
            # Crossover bp is the 3' end of d0
            bp = d0.end_bp
            ha, hb = sorted([d0.helix_id, d1.helix_id])
            placed[(ha, hb)].add(bp)
    return placed


def _expected_xovers(helices) -> dict[tuple[str, str], list[int]]:
    """Return expected crossover bp positions for every NN pair per lookup table."""
    expected: dict[tuple[str, str], list[int]] = {}
    hlist = list(helices)
    for i in range(len(hlist)):
        for j in range(i + 1, len(hlist)):
            ha, hb = hlist[i], hlist[j]
            candidates = valid_crossover_positions(ha, hb)
            if candidates:
                key = tuple(sorted([ha.id, hb.id]))
                expected[key] = sorted(set(c.bp_a for c in candidates))
    return expected


def _pair_label(ha_id: str, hb_id: str) -> str:
    def rc(hid):
        parts = hid.split("_")
        return f"({parts[2]},{parts[3]})"
    a, b = sorted([ha_id, hb_id])
    return f"{rc(a)}↔{rc(b)}"


def run_experiment(cells: list[tuple[int, int]], label: str) -> bool:
    """Run full workflow and verify crossover placement. Returns True if all pass."""
    print(f"\n{'='*60}")
    print(f"  {label}  —  cells={[str(c) for c in cells]}  length={LENGTH_BP}bp")
    print(f"{'='*60}")

    design = make_bundle_design(cells, length_bp=LENGTH_BP)
    design = auto_scaffold(design, mode="end_to_end")
    design = make_prebreak(design)
    design = make_auto_crossover(design)

    helices_by_id = {h.id: h for h in design.helices}
    expected = _expected_xovers(design.helices)
    placed   = _placed_xovers(design)

    # Classify each expected position as hit or miss
    all_pass = True
    pair_summary: list[str] = []

    for key, exp_bps in sorted(expected.items()):
        ha_id, hb_id = key
        got_bps = placed.get(key, set())
        hits   = [bp for bp in exp_bps if bp in got_bps]
        misses = [bp for bp in exp_bps if bp not in got_bps]
        extras = sorted(got_bps - set(exp_bps))

        status = "OK" if not misses and not extras else "FAIL"
        if status == "FAIL":
            all_pass = False

        pair_label = _pair_label(ha_id, hb_id)
        line = (f"  [{status}] {pair_label:20s}  "
                f"expected={len(exp_bps)}  hits={len(hits)}  "
                f"misses={len(misses)}  extras={len(extras)}")
        pair_summary.append((status, line, misses, extras))

    # Print pair results
    for status, line, misses, extras in pair_summary:
        print(line)
        if misses:
            # Show first/last few missing bps and check for cutoff pattern
            missing_str = str(misses[:6]) + ("..." if len(misses) > 6 else "")
            print(f"           MISSING bps: {missing_str}")
            # Check if misses are concentrated in the high-bp region
            if misses:
                cutoff = misses[0]
                print(f"           First miss at bp={cutoff}  (last expected bp={misses[-1]})")
        if extras:
            print(f"           EXTRA bps: {extras[:6]}")

    # Distribution check: verify crossovers spread uniformly along helix
    print()
    print("  Distribution check (crossovers per 21-bp window):")
    combined_bps = sorted(bp for bps in placed.values() for bp in bps)
    window = 21
    counts = defaultdict(int)
    for bp in combined_bps:
        counts[bp // window] += 1
    windows_with_none = [i for i in range(LENGTH_BP // window)
                         if counts[i] == 0]
    if windows_with_none:
        all_pass = False
        print(f"  [FAIL] Windows with 0 crossovers: {windows_with_none}")
    else:
        min_c = min(counts.values()) if counts else 0
        max_c = max(counts.values()) if counts else 0
        print(f"  [OK]   All {LENGTH_BP // window} windows covered  "
              f"(min={min_c}, max={max_c} xovers per window)")

    print()
    print(f"  RESULT: {'PASS' if all_pass else 'FAIL'}")
    return all_pass


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = [
        run_experiment(RING_1_1, "6HB around hole (1,1)"),
        run_experiment(RING_2_2, "6HB around hole (2,2)"),
    ]
    print(f"\n{'='*60}")
    print(f"  Overall: {'ALL PASS' if all(results) else 'FAILURES DETECTED'}")
    sys.exit(0 if all(results) else 1)
