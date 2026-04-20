"""
Exp06 — Scaffold-staple crossover exclusion zone audit.

Checks whether make_autostaple() places staple crossovers within 5 bp of
scaffold crossovers on the same helix pair (canonical caDNAno exclusion rule).
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from backend.core.lattice import make_autostaple, make_bundle_design

CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

EXCLUSION_BP = 5  # canonical caDNAno rule


def find_scaffold_crossovers(design) -> dict[tuple, list[int]]:
    """
    Return {(ha_id, hb_id): [bp, ...]} for all scaffold crossovers.
    A scaffold crossover is a domain boundary where consecutive domains
    in the same scaffold strand are on different helices.
    """
    crossovers: dict[tuple, list[int]] = {}
    for strand in design.strands:
        if strand.strand_type == "staple":
            continue
        domains = strand.domains
        for i in range(len(domains) - 1):
            d0, d1 = domains[i], domains[i + 1]
            if d0.helix_id == d1.helix_id:
                continue
            # Crossover exits d0 at its 3' end (end_bp) and enters d1 at its 5' end (start_bp).
            bp = d0.end_bp  # bp on the "from" helix
            pair = tuple(sorted([d0.helix_id, d1.helix_id]))
            crossovers.setdefault(pair, []).append(bp)
    return crossovers


def find_staple_crossovers(design) -> dict[tuple, list[int]]:
    """
    Return {(ha_id, hb_id): [bp, ...]} for all staple crossovers.
    """
    crossovers: dict[tuple, list[int]] = {}
    for strand in design.strands:
        if strand.strand_type == "scaffold":
            continue
        domains = strand.domains
        for i in range(len(domains) - 1):
            d0, d1 = domains[i], domains[i + 1]
            if d0.helix_id == d1.helix_id:
                continue
            bp = d0.end_bp
            pair = tuple(sorted([d0.helix_id, d1.helix_id]))
            crossovers.setdefault(pair, []).append(bp)
    return crossovers


if __name__ == "__main__":
    design = make_bundle_design(CELLS_18HB, length_bp=42)
    result = make_autostaple(design)

    scaf_xovers = find_scaffold_crossovers(result)
    stpl_xovers = find_staple_crossovers(result)

    print("Scaffold crossovers per pair:")
    for pair, bps in sorted(scaf_xovers.items()):
        print(f"  {pair[0]} ↔ {pair[1]}: scaffold bp={sorted(bps)}")

    print("\nStaple crossovers per pair:")
    for pair, bps in sorted(stpl_xovers.items()):
        print(f"  {pair[0]} ↔ {pair[1]}: staple  bp={sorted(bps)}")

    print(f"\nChecking exclusion zone ({EXCLUSION_BP} bp):")
    violations = []
    checked_pairs = 0
    for pair in set(list(scaf_xovers.keys()) + list(stpl_xovers.keys())):
        s_bps = scaf_xovers.get(pair, [])
        t_bps = stpl_xovers.get(pair, [])
        if not s_bps or not t_bps:
            continue
        checked_pairs += 1
        for sbp in s_bps:
            for tbp in t_bps:
                gap = abs(sbp - tbp)
                if gap < EXCLUSION_BP:
                    violations.append({
                        "pair": list(pair),
                        "scaffold_bp": sbp,
                        "staple_bp": tbp,
                        "gap": gap,
                    })
                    print(f"  VIOLATION: pair {pair[0]}↔{pair[1]} scaffold@{sbp} staple@{tbp} gap={gap} < {EXCLUSION_BP}")

    print(f"\nPairs with both scaffold + staple crossovers: {checked_pairs}")
    print(f"Violations (gap < {EXCLUSION_BP} bp): {len(violations)}")
    if not violations:
        print("  ✓ No violations — exclusion zone is respected.")
    else:
        print("  ✗ Violations found — exclusion zone NOT enforced.")

    metrics = {
        "helix_length_bp": 42,
        "exclusion_zone_bp": EXCLUSION_BP,
        "n_scaffold_crossover_pairs": len(scaf_xovers),
        "n_staple_crossover_pairs": len(stpl_xovers),
        "pairs_checked": checked_pairs,
        "n_violations": len(violations),
        "violations": violations,
        "scaffold_crossovers": {str(k): v for k, v in scaf_xovers.items()},
        "staple_crossovers":  {str(k): v for k, v in stpl_xovers.items()},
    }

    out = Path(__file__).parent / "results"
    out.mkdir(exist_ok=True)
    with open(out / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)

    print(f"\nResults saved to {out}/metrics.json")
