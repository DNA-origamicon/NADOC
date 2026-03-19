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

import re
from dataclasses import dataclass

import numpy as np

from backend.core.constants import SQUARE_TWIST_PER_BP_RAD
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


# ── Square lattice lookup table ────────────────────────────────────────────────
#
# Crossover positions for the square lattice tile every 32 bp.
# For a FORWARD helix at (row, col) the staple-accessible neighbor and bp offsets
# within one 32-bp period are:
#
#   E  (row, col+1) : bp = [0, 31]
#   N  (row-1, col) : bp = [7, 8]
#   W  (row, col-1) : bp = [15, 16]
#   S  (row+1, col) : bp = [23, 24]
#
# For a REVERSE helix the same offsets apply but the neighbor mapping is rotated
# by 180° (W↔E, N↔S swap compared with FORWARD):
#
#   W  (row, col-1) : bp = [0, 31]
#   S  (row+1, col) : bp = [7, 8]
#   E  (row, col+1) : bp = [15, 16]
#   N  (row-1, col) : bp = [23, 24]

_SQ_PERIOD: int = 32

_SQ_FWD_OFFSETS: dict[str, list[int]] = {
    'E': [0, 31],
    'N': [7, 8],
    'W': [15, 16],
    'S': [23, 24],
}
_SQ_REV_OFFSETS: dict[str, list[int]] = {
    'W': [0, 31],
    'S': [7, 8],
    'E': [15, 16],
    'N': [23, 24],
}

_SQ_HELIX_RE = re.compile(r'^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)$')


def _sq_row_col(helix_id: str) -> tuple[int, int] | None:
    m = _SQ_HELIX_RE.match(helix_id)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _square_lattice_crossovers(
    helix_a: Helix,
    helix_b: Helix,
) -> list[CrossoverCandidate]:
    """Return crossover candidates for a square-lattice helix pair via lookup table."""
    rc_a = _sq_row_col(helix_a.id)
    rc_b = _sq_row_col(helix_b.id)
    if rc_a is None or rc_b is None:
        return []

    row_a, col_a = rc_a
    row_b, col_b = rc_b
    dr = row_b - row_a
    dc = col_b - col_a

    # Only direct neighbours (Manhattan distance = 1)
    if not ((abs(dr) == 1 and dc == 0) or (dr == 0 and abs(dc) == 1)):
        return []

    if   dr == -1: neighbour = 'N'
    elif dr ==  1: neighbour = 'S'
    elif dc ==  1: neighbour = 'E'
    else:          neighbour = 'W'

    a_fwd = (row_a + col_a) % 2 == 0
    offsets = (_SQ_FWD_OFFSETS if a_fwd else _SQ_REV_OFFSETS).get(neighbour, [])
    if not offsets:
        return []

    # Staple strand direction per helix direction
    dir_a = Direction.REVERSE if a_fwd else Direction.FORWARD
    b_fwd = (row_b + col_b) % 2 == 0
    dir_b = Direction.REVERSE if b_fwd else Direction.FORWARD

    nucs_a = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(helix_a)}
    nucs_b = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(helix_b)}

    candidates: list[CrossoverCandidate] = []
    max_bp = min(helix_a.length_bp, helix_b.length_bp)

    for base_bp in offsets:
        bp = base_bp
        while bp < max_bp:
            pos_a = nucs_a.get((bp, dir_a))
            pos_b = nucs_b.get((bp, dir_b))
            if pos_a is not None and pos_b is not None:
                dist = round(float(np.linalg.norm(pos_a - pos_b)), 6)
                candidates.append(CrossoverCandidate(
                    bp_a=bp,
                    bp_b=bp,
                    distance_nm=dist,
                    direction_a=dir_a,
                    direction_b=dir_b,
                ))
            bp += _SQ_PERIOD

    return candidates


# ── Main entry point ───────────────────────────────────────────────────────────

def valid_crossover_positions(
    helix_a: Helix,
    helix_b: Helix,
) -> list[CrossoverCandidate]:
    """
    Return all valid crossover positions between helix_a and helix_b.

    Square-lattice helix pairs use the 32-bp lookup table.
    All other pairs use geometry-based distance computation.

    Results are memoised per canonical helix-ID pair.  Call sync_cache(design)
    before iterating all pairs so stale entries are cleared when helices change.
    """
    key = (helix_a.id, helix_b.id) if helix_a.id <= helix_b.id else (helix_b.id, helix_a.id)
    if key in _cache:
        return _cache[key]

    sq_a = abs(helix_a.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9
    sq_b = abs(helix_b.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9
    if sq_a and sq_b:
        result = _square_lattice_crossovers(helix_a, helix_b)
    else:
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
