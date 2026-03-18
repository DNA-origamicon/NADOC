"""
Exp07 — Nick placement algorithm: design, test, and benchmark.

Goal: After make_autostaple() places crossovers, add nicks to break the
resulting long zigzag strands into segments of target_length ± margin nt,
all within the canonical 18–50 nt window.

Algorithm:
  For each non-scaffold strand longer than max_length:
    Walk positions 5'→3', greedily nick every target_length nt.
    Apply nicks right-to-left (so the left piece keeps its original ID,
    allowing subsequent nicks to use the same helix_id/bp_index).
"""

import sys
import json
import time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np

from backend.core.lattice import make_autostaple, make_bundle_design, make_nick
from backend.core.models import Design, Direction

# ── Nick placement implementation ────────────────────────────────────────────


def _strand_positions(strand) -> list[tuple[str, int, "Direction"]]:
    """Return all nucleotide (helix_id, bp, direction) in 5'→3' order."""
    positions = []
    for domain in strand.domains:
        h, d = domain.helix_id, domain.direction
        if d == Direction.FORWARD:
            for bp in range(domain.start_bp, domain.end_bp + 1):
                positions.append((h, bp, d))
        else:
            for bp in range(domain.start_bp, domain.end_bp - 1, -1):
                positions.append((h, bp, d))
    return positions


def compute_nick_plan_for_strand(
    strand,
    target_length: int = 30,
    min_length: int = 18,
) -> list[dict]:
    """
    Return nick positions (helix_id, bp_index, direction) to break this strand
    into segments of min_length..max_length nt.

    Nicks are returned in REVERSE 5'→3' order so that applying them right-to-left
    keeps the original strand ID intact for subsequent nicks.
    """
    max_length: int = 50
    positions = _strand_positions(strand)
    total = len(positions)
    nicks = []
    last_break = 0  # index of first position in the current segment

    while True:
        remaining = total - last_break
        if remaining <= max_length:
            break  # current tail is within canonical 18-50 nt window

        # Ideal nick: exactly target_length into the current segment
        ideal_i = last_break + target_length - 1  # nick AFTER this index

        # Constraint: right tail must be >= min_length
        max_i = total - min_length - 1
        nick_i = min(ideal_i, max_i)
        # Constraint: left segment must be >= min_length
        nick_i = max(nick_i, last_break + min_length - 1)

        nicks.append(nick_i)
        last_break = nick_i + 1

    # Return as dicts, REVERSED so we apply right-to-left
    result = []
    for idx in reversed(nicks):
        h, bp, direction = positions[idx]
        result.append({"helix_id": h, "bp_index": bp, "direction": direction})
    return result


def make_nicks_for_autostaple(
    design: Design,
    target_length: int = 30,
    min_length: int = 18,
) -> Design:
    """Add nicks to break all long staple strands into ~target_length nt segments."""
    result = design
    for strand in design.strands:
        if strand.strand_type == "scaffold":
            continue
        nicks = compute_nick_plan_for_strand(strand, target_length, min_length)
        for nick in nicks:
            try:
                result = make_nick(
                    result,
                    nick["helix_id"],
                    nick["bp_index"],
                    nick["direction"],
                )
            except ValueError:
                pass  # skip if already at boundary or invalid
    return result


# ── Analysis helpers ──────────────────────────────────────────────────────────

CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]


def strand_length(strand) -> int:
    total = 0
    for d in strand.domains:
        lo, hi = min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)
        total += hi - lo + 1
    return total


def analyse_lengths(design: Design) -> dict:
    lengths = [strand_length(s) for s in design.strands if s.strand_type == "staple"]
    arr = np.array(lengths)
    return {
        "n_staples": len(arr),
        "min": int(arr.min()), "max": int(arr.max()),
        "mean": float(arr.mean()), "std": float(arr.std()),
        "n_short": int((arr < 18).sum()),
        "n_long":  int((arr > 50).sum()),
        "n_ok":    int(((arr >= 18) & (arr <= 50)).sum()),
        "pct_ok":  100.0 * int(((arr >= 18) & (arr <= 50)).sum()) / len(arr),
        "distribution": sorted(lengths),
    }


def run_experiment(length_bp: int, target_length: int = 30) -> dict:
    t0 = time.perf_counter()
    design = make_bundle_design(CELLS_18HB, length_bp=length_bp)
    t1 = time.perf_counter()
    after_xovers = make_autostaple(design, min_end_margin=9)  # 9 ensures stubs >= 18 nt
    t2 = time.perf_counter()
    after_nicks = make_nicks_for_autostaple(after_xovers, target_length=target_length)
    t3 = time.perf_counter()

    before = analyse_lengths(after_xovers)
    after  = analyse_lengths(after_nicks)

    return {
        "length_bp": length_bp,
        "target_length": target_length,
        "time_build_ms":   (t1 - t0) * 1000,
        "time_xover_ms":   (t2 - t1) * 1000,
        "time_nick_ms":    (t3 - t2) * 1000,
        "time_total_ms":   (t3 - t0) * 1000,
        "before_xovers": {k: v for k, v in before.items() if k != "distribution"},
        "after_nicks":   {k: v for k, v in after.items() if k != "distribution"},
        "distribution_after": after["distribution"],
    }


if __name__ == "__main__":
    print("=" * 70)
    print("Exp07 — Nick placement algorithm")
    print("=" * 70)

    results = []
    for lbp in [42, 84, 126, 168, 252]:
        r = run_experiment(lbp)
        results.append(r)
        b = r["before_xovers"]
        a = r["after_nicks"]
        print(f"\n── {lbp} bp helix  (total time: {r['time_total_ms']:.1f} ms) ──────────")
        print(f"  After crossovers: {b['n_staples']} strands, {b['min']}–{b['max']} nt, "
              f"{b['mean']:.0f} nt mean, {b['pct_ok']:.0f}% in 18–50 window")
        print(f"  After nicks:      {a['n_staples']} strands, {a['min']}–{a['max']} nt, "
              f"{a['mean']:.0f} nt mean, {a['pct_ok']:.0f}% in 18–50 window")
        print(f"  Timings: build={r['time_build_ms']:.1f}ms  xover={r['time_xover_ms']:.1f}ms  "
              f"nick={r['time_nick_ms']:.1f}ms")

    # Detailed distribution for 126 bp
    r126 = next(r for r in results if r["length_bp"] == 126)
    dist = r126["distribution_after"]
    print(f"\nDetailed distribution after nicks — 126 bp ({r126['after_nicks']['n_staples']} strands):")
    c = Counter(dist)
    for length in sorted(c):
        bar = "█" * c[length]
        flag = " ← SHORT" if length < 18 else (" ← LONG" if length > 50 else "")
        print(f"  {length:>4} nt: {bar} ({c[length]}){flag}")

    # Save results
    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    with open(out / "metrics.json", "w") as f:
        save = [{k: v for k, v in r.items() if k != "distribution_after"} for r in results]
        json.dump(save, f, indent=2)

    print(f"\nResults saved to {out}/metrics.json")

    # Final verdict
    r_all = [r["after_nicks"]["pct_ok"] for r in results]
    print(f"\n{'─'*50}")
    print(f"Overall: {min(r_all):.0f}%–{max(r_all):.0f}% of strands in 18–50 nt window")
    if min(r_all) >= 95:
        print("HYPOTHESIS CONFIRMED ✓ — nick algorithm achieves >95% canonical range")
    else:
        print("HYPOTHESIS NOT MET ✗ — further refinement needed")
