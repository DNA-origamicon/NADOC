"""
Geometric layer — valid crossover position computation.

For two helices, computes all (bp_a, bp_b) index pairs where the minimum
backbone-to-backbone distance between any strand combination is within reach
for a physical crossover junction.

This is the implementation of DTP-2: pre-computed valid positions as clickable
markers only; no register gauge.  The algorithm is purely geometric and does
not assume a lattice type, so it is valid for FREE, HONEYCOMB, and SQUARE
designs.

Each CrossoverCandidate now also records the strand *directions* (FORWARD or
REVERSE) on each helix that produced the minimum distance, so callers know
exactly which strands to operate on when placing a crossover.
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
    direction_a: Direction  # strand direction on helix_a that is closest
    direction_b: Direction  # strand direction on helix_b that is closest


def valid_crossover_positions(
    helix_a: Helix,
    helix_b: Helix,
) -> List[CrossoverCandidate]:
    """
    Return all (bp_a, bp_b) pairs where any backbone bead on helix_a at bp_a
    is within MAX_CROSSOVER_REACH_NM of any backbone bead on helix_b at bp_b.

    Checks all four strand-direction combinations (FORWARD/REVERSE × FORWARD/REVERSE)
    and records the minimum distance per (bp_a, bp_b) pair along with which
    direction combination produced that minimum.

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
        for bp_b in range(helix_b.length_bp):
            min_dist = float('inf')
            best_da = Direction.FORWARD
            best_db = Direction.FORWARD

            for da in directions:
                pa = nucs_a.get((bp_a, da))
                if pa is None:
                    continue
                for db in directions:
                    pb = nucs_b.get((bp_b, db))
                    if pb is None:
                        continue
                    dist = float(np.linalg.norm(pa - pb))
                    if dist < min_dist:
                        min_dist = dist
                        best_da = da
                        best_db = db

            if min_dist <= MAX_CROSSOVER_REACH_NM:
                candidates.append(CrossoverCandidate(
                    bp_a=bp_a,
                    bp_b=bp_b,
                    distance_nm=round(min_dist, 6),
                    direction_a=best_da,
                    direction_b=best_db,
                ))

    return candidates
