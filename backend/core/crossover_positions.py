"""
Geometric layer — valid crossover position computation.

For two helices, computes all (bp_a, bp_b) index pairs where the minimum
backbone-to-backbone distance between any strand combination is within reach
for a physical crossover junction.

This is the implementation of DTP-2: pre-computed valid positions as clickable
markers only; no register gauge.  The algorithm is purely geometric and does
not assume a lattice type, so it is valid for FREE, HONEYCOMB, and SQUARE
designs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from backend.core.geometry import nucleotide_positions
from backend.core.models import Direction, Helix

# Maximum backbone-to-backbone distance for a viable crossover, in nm.
# Standard oxDNA convention: ≤ 0.6–0.7 nm for a relaxed junction.
MAX_CROSSOVER_REACH_NM: float = 0.75


@dataclass(frozen=True)
class CrossoverCandidate:
    """A valid crossover position between two helices."""
    bp_a: int           # bp index on helix_a
    bp_b: int           # bp index on helix_b
    distance_nm: float  # minimum backbone-to-backbone distance (nm)


def valid_crossover_positions(
    helix_a: Helix,
    helix_b: Helix,
) -> List[CrossoverCandidate]:
    """
    Return all (bp_a, bp_b) pairs where any backbone bead on helix_a at bp_a
    is within MAX_CROSSOVER_REACH_NM of any backbone bead on helix_b at bp_b.

    Checks all four strand-direction combinations (FORWARD/REVERSE × FORWARD/REVERSE)
    and records the minimum distance per (bp_a, bp_b) pair.

    Pure function — does not modify either Helix.
    """
    # Build position lookup: (bp_index, Direction) → backbone position array
    nucs_a = {
        (n.bp_index, n.direction): n.position
        for n in nucleotide_positions(helix_a)
    }
    nucs_b = {
        (n.bp_index, n.direction): n.position
        for n in nucleotide_positions(helix_b)
    }

    directions = [Direction.FORWARD, Direction.REVERSE]
    candidates: List[CrossoverCandidate] = []

    for bp_a in range(helix_a.length_bp):
        pos_a_list = [nucs_a[bp_a, d] for d in directions if (bp_a, d) in nucs_a]
        if not pos_a_list:
            continue

        for bp_b in range(helix_b.length_bp):
            pos_b_list = [nucs_b[bp_b, d] for d in directions if (bp_b, d) in nucs_b]
            if not pos_b_list:
                continue

            min_dist = min(
                float(np.linalg.norm(pa - pb))
                for pa in pos_a_list
                for pb in pos_b_list
            )

            if min_dist <= MAX_CROSSOVER_REACH_NM:
                candidates.append(CrossoverCandidate(
                    bp_a=bp_a,
                    bp_b=bp_b,
                    distance_nm=round(min_dist, 6),
                ))

    return candidates
