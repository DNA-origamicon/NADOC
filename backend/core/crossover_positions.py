"""
Geometric layer — valid crossover position computation.

Ground truth reference: drawings/lattice_ground_truth.png
  HC staple crossover positions (per 21-bp period, by NN pair type):
    p330 (FORWARD→REVERSE angle 330°): bp = {0, 20}
    p90  (FORWARD→REVERSE angle  90°): bp = {13, 14}
    p210 (FORWARD→REVERSE angle 210°): bp = {6, 7}
  SQ staple crossover positions (per 32-bp period, by NN pair type):
    pE (FORWARD→East  neighbor): bp = {0, 31}
    pN (FORWARD→North neighbor): bp = {7, 8}
    pW (FORWARD→West  neighbor): bp = {15, 16}
    pS (FORWARD→South neighbor): bp = {23, 24}

Honeycomb and square-lattice helix pairs use lookup tables (h_{PLANE}_{ROW}_{COL} IDs).
All other pairs fall back to geometry-based distance computation.

Results are cached per helix-pair and automatically invalidated whenever the
set of helix IDs in the design changes.  This makes repeated calls to
get_all_valid_crossovers() after strand-only edits (crossover placement, nicks)
essentially free; only extrusion or undo/redo of extrusion triggers recomputation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP, HONEYCOMB_HELIX_SPACING, SQUARE_TWIST_PER_BP_RAD
from backend.core.geometry import nucleotide_positions
from backend.core.models import Design, Direction, Helix

# Maximum backbone-to-backbone distance for a viable crossover, in nm.
MAX_CROSSOVER_REACH_NM: float = 0.75


def _helix_bp_count(helix: Helix) -> int:
    """Active bp count derived from axis geometry.

    Works correctly for all three helix conventions:
    - native   (bp_start=0,  length_bp=active_count)
    - caDNAno  (bp_start=first_active, length_bp=full_array_length)
    - hybrid   (bp_start=first_active, length_bp=active_count)

    The formula ``length_bp - bp_start`` gives the wrong count for hybrid helices.
    The axis length always spans exactly the active bp range, so rounding it gives
    the correct count regardless of how bp_start and length_bp are stored.
    """
    ax = np.array([
        helix.axis_end.x - helix.axis_start.x,
        helix.axis_end.y - helix.axis_start.y,
        helix.axis_end.z - helix.axis_start.z,
    ], dtype=float)
    return round(float(np.linalg.norm(ax)) / BDNA_RISE_PER_BP)


def _helix_axis_bp_start(helix: Helix) -> int:
    """Return the global bp index at which this helix's axis_start resides.

    For caDNAno-imported helices: axis_start.z == bp_start * RISE, so this
    returns helix.bp_start (consistent with the stored field).

    For native continuation helices: bp_start is always 0 but axis_start.z
    may be non-zero (e.g. 14.028 nm for a helix beginning at bp 42).  This
    function derives the correct geometric offset from the axis, so that two
    helices with different physical starting positions get different effective
    bp starts even when both store bp_start=0.
    """
    ax = np.array([
        helix.axis_end.x - helix.axis_start.x,
        helix.axis_end.y - helix.axis_start.y,
        helix.axis_end.z - helix.axis_start.z,
    ], dtype=float)
    length = float(np.linalg.norm(ax))
    if length < 1e-12:
        return helix.bp_start
    hat = ax / length
    start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z], dtype=float)
    return round(float(np.dot(start, hat)) / BDNA_RISE_PER_BP)

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


# ── Honeycomb lattice lookup table ────────────────────────────────────────────
#
# Staple crossover positions repeat every 21 bp.  The pair type is determined
# by the angle (CCW from +X) from the FORWARD-type helix centre to the
# REVERSE-type helix centre.  See drawings/lattice_ground_truth.png.
#
#   p330  (angle ≈ 330°, e.g. (0,0)→(0,1)): bp = {0, 20}
#   p90   (angle ≈  90°, e.g. (0,0)→(1,0)): bp = {13, 14}
#   p210  (angle ≈ 210°, e.g. (0,2)→(0,1)): bp = {6, 7}
#
# Staple strand per helix type:
#   FORWARD-type helix (val=0): staple is on the REVERSE strand
#   REVERSE-type helix (val=1): staple is on the FORWARD strand

_HC_PERIOD: int = 21

_HC_OFFSETS: dict[str, list[int]] = {
    'p330': [0, 20],
    'p90':  [13, 14],
    'p210': [6, 7],
}

_HC_HELIX_RE = re.compile(r'^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)$')


def _hc_row_col(helix_id: str) -> tuple[int, int] | None:
    m = _HC_HELIX_RE.match(helix_id)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _hc_cell_value(row: int, col: int) -> int:
    return (row + col % 2) % 3   # 0=FORWARD, 1=REVERSE, 2=HOLE


def _hc_pair_type(x_fwd: float, y_fwd: float, x_rev: float, y_rev: float) -> str | None:
    """Classify pair type from FORWARD-helix XY position to REVERSE-helix XY position."""
    angle = math.degrees(math.atan2(y_rev - y_fwd, x_rev - x_fwd)) % 360
    if 80 <= angle <= 100:
        return 'p90'
    if 200 <= angle <= 220:
        return 'p210'
    if 320 <= angle <= 340:
        return 'p330'
    return None


def _honeycomb_lattice_crossovers(
    helix_a: Helix,
    helix_b: Helix,
) -> list[CrossoverCandidate]:
    """Return staple crossover candidates for an HC helix pair via lookup table."""
    rc_a = _hc_row_col(helix_a.id)
    rc_b = _hc_row_col(helix_b.id)
    if rc_a is None or rc_b is None:
        return []

    val_a = _hc_cell_value(*rc_a)
    val_b = _hc_cell_value(*rc_b)
    if val_a == 2 or val_b == 2:
        return []
    if val_a == val_b:   # same type — no valid staple crossover
        return []

    # Orient so fwd_helix is the FORWARD-type (val=0)
    if val_a == 0:
        fwd_helix, rev_helix = helix_a, helix_b
        dir_a, dir_b = Direction.REVERSE, Direction.FORWARD
    else:
        fwd_helix, rev_helix = helix_b, helix_a
        dir_a, dir_b = Direction.FORWARD, Direction.REVERSE

    # Guard: only apply lookup table for genuine nearest-neighbor pairs.
    dx = rev_helix.axis_start.x - fwd_helix.axis_start.x
    dy = rev_helix.axis_start.y - fwd_helix.axis_start.y
    dist = math.sqrt(dx * dx + dy * dy)
    if dist > HONEYCOMB_HELIX_SPACING * 1.05:
        return []

    ptype = _hc_pair_type(
        fwd_helix.axis_start.x, fwd_helix.axis_start.y,
        rev_helix.axis_start.x, rev_helix.axis_start.y,
    )
    if ptype is None:
        return []

    offsets = _HC_OFFSETS[ptype]
    # Use the geometric bp start (derived from axis_start position) rather than
    # helix.bp_start, which is 0 for all native designs including continuation
    # helices that physically begin part-way along the Z axis.
    a_start = _helix_axis_bp_start(helix_a)
    b_start = _helix_axis_bp_start(helix_b)
    overlap_lo = max(a_start, b_start)
    # exclusive upper bound: axis_bp_start + length_bp gives last valid global
    # bp + 1 for both native (bp_start=0, length_bp=count) and caDNAno designs
    # (axis_bp_start == stored bp_start, length_bp - stored_bp_start == count).
    overlap_hi = min(
        a_start + _helix_bp_count(helix_a),
        b_start + _helix_bp_count(helix_b),
    )

    candidates: list[CrossoverCandidate] = []
    for base_bp in offsets:  # local offset in [0..period-1]
        local_lo = overlap_lo - max(a_start, 0)  # local index of overlap start on helix_a
        delta = (base_bp - local_lo % _HC_PERIOD) % _HC_PERIOD
        global_bp = overlap_lo + delta
        while global_bp < overlap_hi:
            # Convert physical global bp → per-helix stored bp index.
            # For caDNAno designs: a_start == helix.bp_start, so bp_a == global_bp.
            # For native continuation helices: bp_start == 0, a_start > 0, so
            # bp_a = global_bp - a_start (correct local index into the helix array).
            stored_bp_a = global_bp - a_start + helix_a.bp_start
            stored_bp_b = global_bp - b_start + helix_b.bp_start
            candidates.append(CrossoverCandidate(
                bp_a=stored_bp_a,
                bp_b=stored_bp_b,
                distance_nm=0.0,
                direction_a=dir_a,
                direction_b=dir_b,
            ))
            global_bp += _HC_PERIOD
    return candidates


# ── Square lattice lookup table ────────────────────────────────────────────────
#
# Staple crossover positions repeat every 32 bp (= 3 full turns).  The pair
# type is determined by the direction FROM the FORWARD-type helix TO the
# REVERSE-type helix.  See drawings/lattice_ground_truth.png.
#
#   pE  (FORWARD → East  neighbour): bp = {0, 31}
#   pN  (FORWARD → North neighbour): bp = {7, 8}
#   pW  (FORWARD → West  neighbour): bp = {15, 16}
#   pS  (FORWARD → South neighbour): bp = {23, 24}

_SQ_PERIOD: int = 32

_SQ_OFFSETS: dict[str, list[int]] = {
    'pE': [0, 31],
    'pN': [7, 8],
    'pW': [15, 16],
    'pS': [23, 24],
}

_SQ_HELIX_RE = re.compile(r'^h_(?:XY|XZ|YZ)_(-?\d+)_(-?\d+)$')


def _sq_row_col(helix_id: str) -> tuple[int, int] | None:
    m = _SQ_HELIX_RE.match(helix_id)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _square_lattice_crossovers(
    helix_a: Helix,
    helix_b: Helix,
) -> list[CrossoverCandidate]:
    """Return staple crossover candidates for a SQ helix pair via lookup table."""
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

    # Orient so fwd_helix is the FORWARD-type ((row+col)%2==0)
    a_fwd = (row_a + col_a) % 2 == 0
    if a_fwd:
        fwd_helix, rev_helix = helix_a, helix_b
        dir_a, dir_b = Direction.REVERSE, Direction.FORWARD
        fdr, fdc = dr, dc
    else:
        fwd_helix, rev_helix = helix_b, helix_a
        dir_a, dir_b = Direction.FORWARD, Direction.REVERSE
        fdr, fdc = -dr, -dc

    # Direction from FORWARD to REVERSE → pair type
    if   fdc ==  1: ptype = 'pE'
    elif fdc == -1: ptype = 'pW'
    elif fdr == -1: ptype = 'pN'
    else:           ptype = 'pS'

    offsets = _SQ_OFFSETS[ptype]

    a_start = _helix_axis_bp_start(helix_a)
    b_start = _helix_axis_bp_start(helix_b)
    overlap_lo = max(a_start, b_start)
    overlap_hi = min(
        a_start + _helix_bp_count(helix_a),
        b_start + _helix_bp_count(helix_b),
    )

    candidates: list[CrossoverCandidate] = []
    for base_bp in offsets:
        local_lo = overlap_lo - max(a_start, 0)
        delta = (base_bp - local_lo % _SQ_PERIOD) % _SQ_PERIOD
        global_bp = overlap_lo + delta
        while global_bp < overlap_hi:
            stored_bp_a = global_bp - a_start + helix_a.bp_start
            stored_bp_b = global_bp - b_start + helix_b.bp_start
            candidates.append(CrossoverCandidate(
                bp_a=stored_bp_a,
                bp_b=stored_bp_b,
                distance_nm=0.0,
                direction_a=dir_a,
                direction_b=dir_b,
            ))
            global_bp += _SQ_PERIOD

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

    sq_a = abs(helix_a.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9 and _sq_row_col(helix_a.id) is not None
    sq_b = abs(helix_b.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9 and _sq_row_col(helix_b.id) is not None
    if sq_a and sq_b:
        result = _square_lattice_crossovers(helix_a, helix_b)
    elif _hc_row_col(helix_a.id) is not None and _hc_row_col(helix_b.id) is not None:
        result = _honeycomb_lattice_crossovers(helix_a, helix_b)
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
    a_start = _helix_axis_bp_start(helix_a)
    b_start = _helix_axis_bp_start(helix_b)
    NAN3  = np.array([np.nan, np.nan, np.nan], dtype=float)

    # pos_x[dir_idx, bp, xyz] — NaN where the nucleotide doesn't exist
    # Iterate local indices 0..N-1 but look up by global bp (a_start+i).
    pos_a = np.array([[nucs_a.get((a_start + i, d), NAN3) for i in range(len_a)] for d in directions])
    pos_b = np.array([[nucs_b.get((b_start + i, d), NAN3) for i in range(len_b)] for d in directions])

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
    for local_a, local_b in np.argwhere(min_dists <= MAX_CROSSOVER_REACH_NM):
        ci      = int(best_combo[local_a, local_b])
        da, db  = dir_combos[ci]
        raw.append(CrossoverCandidate(
            bp_a=int(local_a) + a_start,
            bp_b=int(local_b) + b_start,
            distance_nm=round(float(min_dists[local_a, local_b]), 6),
            direction_a=da,
            direction_b=db,
        ))

    return _filter_local_minima(raw)
