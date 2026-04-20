"""
Exp05 — Staple length distribution after autostaple.

Measures whether make_autostaple() produces staple strands within the canonical
18–50 nt window for different helix lengths.
"""

import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

import numpy as np

from backend.core.lattice import make_autostaple, make_bundle_design

# Canonical 18HB layout
CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

HELIX_LENGTHS = [42, 84, 126, 168, 252]


def strand_length(strand) -> int:
    """Total nucleotide count for a strand."""
    total = 0
    for d in strand.domains:
        lo = min(d.start_bp, d.end_bp)
        hi = max(d.start_bp, d.end_bp)
        total += hi - lo + 1
    return total


def analyse(length_bp: int) -> dict:
    design = make_bundle_design(CELLS_18HB, length_bp=length_bp)
    result = make_autostaple(design)

    staple_lengths = []
    for s in result.strands:
        if s.strand_type == "staple":
            staple_lengths.append(strand_length(s))

    lengths = np.array(staple_lengths)
    n_short  = int((lengths < 18).sum())
    n_long   = int((lengths > 50).sum())
    n_ok     = int(((lengths >= 18) & (lengths <= 50)).sum())

    return {
        "length_bp":   length_bp,
        "n_staples":   len(lengths),
        "min":         int(lengths.min()),
        "max":         int(lengths.max()),
        "mean":        float(lengths.mean()),
        "std":         float(lengths.std()),
        "n_short_lt18":n_short,
        "n_long_gt50": n_long,
        "n_ok_18_50":  n_ok,
        "pct_ok":      100.0 * n_ok / len(lengths) if len(lengths) else 0.0,
        "histogram":   np.histogram(lengths, bins=range(0, max(int(lengths.max()) + 10, 60), 5))[0].tolist(),
        "hist_edges":  list(range(0, max(int(lengths.max()) + 10, 60), 5)),
        "distribution": sorted(staple_lengths),
    }


if __name__ == "__main__":
    results = []
    print(f"{'bp':>6}  {'n':>5}  {'min':>5}  {'max':>5}  {'mean':>6}  {'<18':>5}  {'>50':>5}  {'ok%':>6}")
    print("-" * 60)
    for lbp in HELIX_LENGTHS:
        r = analyse(lbp)
        results.append(r)
        print(f"{r['length_bp']:>6}  {r['n_staples']:>5}  {r['min']:>5}  {r['max']:>5}  "
              f"{r['mean']:>6.1f}  {r['n_short_lt18']:>5}  {r['n_long_gt50']:>5}  {r['pct_ok']:>6.1f}%")

    out_dir = Path(__file__).parent / "results"
    out_dir.mkdir(exist_ok=True)
    with open(out_dir / "metrics.json", "w") as f:
        # exclude distribution list from JSON (too large)
        json.dump([{k: v for k, v in r.items() if k != "distribution"} for r in results], f, indent=2)

    # Print distribution for 126bp to understand the shape
    r126 = next(r for r in results if r["length_bp"] == 126)
    dist = r126["distribution"]
    print(f"\nLength distribution for 126 bp design ({r126['n_staples']} staples):")
    from collections import Counter
    c = Counter(dist)
    for length in sorted(c):
        bar = "█" * c[length]
        print(f"  {length:>4} nt: {bar} ({c[length]})")

    print(f"\nResults saved to {out_dir}/metrics.json")
