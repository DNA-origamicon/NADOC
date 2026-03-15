"""
Geometric layer — valid crossover position computation.

Valid positions are computed from actual nucleotide geometry using NumPy
broadcasting: any backbone bead on helix_a within MAX_CROSSOVER_REACH_NM of
any backbone bead on helix_b is a candidate.  A local-minimum filter then keeps
only the geometrically best position per "crossover region" (within a 2-bp window).

Results are cached per helix-pair and automatically invalidated whenever the
set of helix IDs in the design changes.  This makes repeated calls to
get_all_valid_crossovers() after strand-only edits (crossover placement, nicks)
essentially free; only extrusion or undo/redo of extrusion triggers recomputation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.core.geometry import nucleotide_positions
from backend.core.models import Design, Direction, Helix

# Maximum backbone-to-backbone distance for a viable crossover, in nm.
MAX_CROSSOVER_REACH_NM: float = 0.75

# ── Per-pair result cache ──────────────────────────────────────────────────────
# Key: canonical (min_id, max_id) helix-ID pair.
# Invalidated when design helix-ID set changes (sync_cache compares frozensets).

_cache: dict[tuple[str, str], list[CrossoverCandidate]] = {}  # type: ignore[name-defined]
_cached_helix_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class CrossoverCandidate:
    """A valid crossover position between two helices."""
    bp_a: int
    bp_b: int
    distance_nm: float
    direction_a: Direction
    direction_b: Direction


# ── Cache management ───────────────────────────────────────────────────────────

def sync_cache(design: Design) -> None:
    """
    Invalidate stale cache entries when the design's helix set has changed.
    Call once at the start of get_all_valid_crossovers().
    """
    global _cached_helix_ids
    current_ids = frozenset(h.id for h in design.helices)
    if current_ids != _cached_helix_ids:
        _cache.clear()
        _cached_helix_ids = current_ids


def clear_cache() -> None:
    """Force-clear the entire cache (e.g. on design load from disk)."""
    global _cached_helix_ids
    _cache.clear()
    _cached_helix_ids = frozenset()


# ── Main entry point ───────────────────────────────────────────────────────────

def valid_crossover_positions(
    helix_a: Helix,
    helix_b: Helix,
) -> list[CrossoverCandidate]:
    """
    Return all (bp_a, bp_b) pairs where any backbone bead on helix_a is within
    MAX_CROSSOVER_REACH_NM of any backbone bead on helix_b.

    Uses geometry-based computation so results are correct for NADOC's actual
    phase_offset values rather than caDNAno's hardcoded offsets.

    Results are memoised per canonical helix-ID pair.  Call sync_cache(design)
    before iterating all pairs so stale entries are cleared when helices change.
    """
    key = (helix_a.id, helix_b.id) if helix_a.id <= helix_b.id else (helix_b.id, helix_a.id)
    if key in _cache:
        return _cache[key]

    result = _compute_vectorised(helix_a, helix_b)
    _cache[key] = result
    return result


# ── Local-minimum filter ───────────────────────────────────────────────────────

# Within a window of this many bp on BOTH helices, only the closest candidate
# is kept.  Prevents "fringe" positions (e.g. bp=20/22 at 0.715 nm right next
# to bp=21/21 at 0.518 nm) from showing as extra spurious markers.
_LOCAL_MIN_WINDOW: int = 2


def _filter_local_minima(candidates: list[CrossoverCandidate]) -> list[CrossoverCandidate]:
    """
    Greedy local-minimum suppression, applied independently per direction pair.

    Within each (direction_a, direction_b) group, sort by distance ascending and
    accept a candidate only if no already-accepted candidate in that group is
    within _LOCAL_MIN_WINDOW bp on both helices.  This retains one representative
    per "crossover region" — the geometrically best position — and discards nearby
    higher-distance alternatives (e.g. bp=20/22 at 0.715 nm next to bp=21/21 at
    0.518 nm).

    Grouping by direction is critical: a scaffold-scaffold close approach at one bp
    must not suppress a nearby staple-staple close approach at a different bp.
    """
    groups: dict[tuple, list[CrossoverCandidate]] = {}
    for c in candidates:
        key = (c.direction_a, c.direction_b)
        groups.setdefault(key, []).append(c)

    accepted: list[CrossoverCandidate] = []
    for group in groups.values():
        # Sort: equal-bp (diagonal) candidates first, then by distance ascending.
        # When an off-diagonal minimum (e.g. bp_a=0, bp_b=1 at 0.34 nm) and a diagonal
        # candidate (e.g. bp_a=1, bp_b=1 at 0.65 nm) fall in the same local window,
        # the diagonal one wins.  Equal-bp positions are the physically correct crossover
        # sites: both backbone beads are at the same axial height, making the crossover
        # junction geometrically symmetric.
        group_sorted = sorted(group, key=lambda c: (c.bp_a != c.bp_b, c.distance_nm))
        group_accepted: list[CrossoverCandidate] = []
        for c in group_sorted:
            for a in group_accepted:
                if abs(c.bp_a - a.bp_a) <= _LOCAL_MIN_WINDOW and abs(c.bp_b - a.bp_b) <= _LOCAL_MIN_WINDOW:
                    break
            else:
                group_accepted.append(c)
        accepted.extend(group_accepted)
    return accepted


# ── Vectorised computation ─────────────────────────────────────────────────────

def _compute_vectorised(helix_a: Helix, helix_b: Helix) -> list[CrossoverCandidate]:
    """
    Compute crossover candidates for one helix pair using NumPy broadcasting.

    Builds (2, N_bp, 3) position arrays for each helix (one slice per direction),
    then computes all four direction-combination distance matrices simultaneously,
    keeping the best (minimum) direction pair per (bp_a, bp_b) cell.
    """
    directions = [Direction.FORWARD, Direction.REVERSE]

    nucs_a = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(helix_a)}
    nucs_b = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(helix_b)}

    len_a = helix_a.length_bp
    len_b = helix_b.length_bp
    NAN3  = np.array([np.nan, np.nan, np.nan], dtype=float)

    # pos_x[dir_idx, bp, xyz] — NaN where the nucleotide doesn't exist
    pos_a = np.array([[nucs_a.get((bp, d), NAN3) for bp in range(len_a)] for d in directions])
    pos_b = np.array([[nucs_b.get((bp, d), NAN3) for bp in range(len_b)] for d in directions])

    valid_a = ~np.any(np.isnan(pos_a), axis=2)  # (2, len_a)
    valid_b = ~np.any(np.isnan(pos_b), axis=2)  # (2, len_b)

    # (4, len_a, len_b) — one slice per direction combination
    all_dists: np.ndarray = np.full((4, len_a, len_b), np.inf, dtype=float)
    dir_combos: list[tuple[Direction, Direction]] = []

    for ci, (ia, da) in enumerate(zip(range(2), directions)):
        for ib, db in enumerate(directions):
            idx = ia * 2 + ib
            pa  = pos_a[ia]  # (len_a, 3)
            pb  = pos_b[ib]  # (len_b, 3)

            diff = pa[:, np.newaxis, :] - pb[np.newaxis, :, :]   # (len_a, len_b, 3)
            d    = np.linalg.norm(diff, axis=2)                  # (len_a, len_b)

            mask = (
                np.outer(~valid_a[ia], np.ones(len_b, dtype=bool)) |
                np.outer(np.ones(len_a, dtype=bool), ~valid_b[ib])
            )
            d[mask] = np.inf
            all_dists[idx] = d
            dir_combos.append((da, db))

    best_combo = np.argmin(all_dists, axis=0)  # (len_a, len_b)
    min_dists  = all_dists[
        best_combo,
        np.arange(len_a)[:, None],
        np.arange(len_b)[None, :],
    ]  # (len_a, len_b)

    raw: list[CrossoverCandidate] = []
    for bp_a, bp_b in np.argwhere(min_dists <= MAX_CROSSOVER_REACH_NM):
        ci      = int(best_combo[bp_a, bp_b])
        da, db  = dir_combos[ci]
        raw.append(CrossoverCandidate(
            bp_a=int(bp_a),
            bp_b=int(bp_b),
            distance_nm=round(float(min_dists[bp_a, bp_b]), 6),
            direction_a=da,
            direction_b=db,
        ))

    return _filter_local_minima(raw)
