"""
Loop/Skip Calculator — Phase 7 topological deformation engine.

Translates user-specified bend or twist parameters into concrete loop (+1) and
skip (−1) modifications on helix bp positions, following the physical mechanism
established by Dietz, Douglas & Shih (Science 2009).

Physical mechanism
──────────────────
B-DNA in a honeycomb bundle has 10.5 bp/turn.  Consecutive crossover planes are
spaced 7 bp apart (7 × 34.286°/bp ≈ 240° = one crossover-neighbour angular
interval).  Each **array cell** — the 7-bp segment between adjacent planes — is
the atomic unit of modification.

  Deletion (skip, δ = −1): cell becomes 6 bp.  Local twist = 6 × 34.3° = 205.7°
    instead of 240° → locally OVERTWISTED → exerts left-handed torque and a
    tensile pull on neighbours → global left-handed twist; if asymmetric across
    cross-section → global bend toward the deletion side.

  Insertion (loop, δ = +1): cell becomes 8 bp.  Local twist = 274.3° instead of
    240° → locally UNDERTWISTED → right-handed torque and compressive push →
    global right-handed twist; bend away from the insertion side.

Constraints (from Dietz et al.):
  6 bp/turn ≤ effective twist density ≤ 15 bp/turn per helix at any cell.
  Equivalent: cell bp count ∈ [4, 10] (i.e., −3 ≤ δ_per_cell ≤ +3).

Minimum achievable bend radius for a bundle with maximum cross-section offset
r_max (nm):
  R_min = 7 × r_max / 3   (≈ 5.25 nm for a 3-row honeycomb, matching paper)

Curvature formula (elastic continuum model):
  κ = 1/R = Σ_i(ΔL_i × r_i) / (L_nom × Σ_i(r_i²))

  where  ΔL_i   = total length change for helix i over the segment (nm)
                 = Σ_cells δ_i × RISE_PER_BP
         r_i    = helix cross-section offset in bend direction (nm)
         L_nom  = n_cells × 7 × RISE_PER_BP  (nominal segment length, nm)

API
───
  twist_loop_skips(design, segment_helices, plane_a_bp, plane_b_bp,
                   target_twist_deg) → dict[helix_id, list[LoopSkip]]

  bend_loop_skips(design, segment_helices, plane_a_bp, plane_b_bp,
                  radius_nm, direction_deg) → dict[helix_id, list[LoopSkip]]

  apply_loop_skips(design, modifications) → Design
      Merges the computed loop/skip map into the Design topology.  Overwrites
      any existing loop_skips in the affected helix objects within the segment.

  clear_all_loop_skips(design) → Design
      Remove every loop_skip from every helix.  Used by Update Routing to
      start from a clean slate before recomputing.

  clear_orphaned_loop_skips(design) → Design
      Remove loop_skips at bp positions not covered by any strand domain on
      that helix (e.g. after strand edits that leave stale marks behind).

  validate_loop_skip_limits(n_del_per_cell, n_ins_per_cell) → None | raises
  min_bend_radius_nm(segment_helices, plane_a_bp, plane_b_bp) → float
  max_twist_deg(n_cells, n_helices) → float
  predict_global_twist_deg(modifications) → float
  predict_radius_nm(design_or_helices, modifications, plane_a_bp, plane_b_bp)
      → float
"""

from __future__ import annotations

import math
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Direction, Helix, LoopSkip

if TYPE_CHECKING:
    from backend.core.models import Design

# ── Constants ─────────────────────────────────────────────────────────────────

# Local twist values for the Dietz/Douglas/Shih (2009) loop-skip mechanism.
# Intentionally distinct from constants.py's geometry-layer _LOOP_SKIP_TWIST_PER_BP_DEG
# (34.3°/bp): the paper's mechanism uses an exact 10.5 bp/turn → 34.286°/bp →
# 240° per 7-bp array cell. Mixing the two values would shift cell twist by 0.1°
# per cell and compound across long segments. Module-private to prevent reuse.
_LOOP_SKIP_BP_PER_TURN: float = 10.5
_LOOP_SKIP_TWIST_PER_BP_DEG: float = 360.0 / _LOOP_SKIP_BP_PER_TURN   # ≈ 34.286 °/bp
CELL_BP_DEFAULT: int = 7                                    # default cell size
CELL_TWIST_DEG: float = CELL_BP_DEFAULT * _LOOP_SKIP_TWIST_PER_BP_DEG  # ≈ 240°

# Per-cell modification limits (from Dietz et al. — 6≤T≤15 bp/turn constraint)
# Cell bp count range: [4, 10], so |delta| ≤ 3 per cell.
MAX_DELTA_PER_CELL: int = 3

# ── Feasibility thresholds (twist density, bp/turn) ─────────────────────────────
# HARD limit (block / "physically unachievable"): outside 6–15 bp/turn you cannot
# place the marks — this is the geometric ceiling, equivalent to |δ| > 3 per cell
# (MAX_DELTA_PER_CELL). Re-expressed here in bp/turn for the classifier.
HARD_BP_PER_TURN_MIN: float = 6.0
HARD_BP_PER_TURN_MAX: float = 15.0

# SOFT limit (warn / "low folding yield expected"): outside 9–12 bp/turn the
# structure can still be built but folds with reduced yield. From Lee Tin Wah
# et al., "Automated design of 3D DNA origami with non-rasterized 2D curvature"
# (Sci. Adv. 9, 2023): "placing crossovers such that all sections of the DNA
# helices are between 9 and 12 bp per turn will help to maintain a high yield."
# Tight rings "form poorly because of being highly strained due to the low
# radius of curvature"; a 90° bend retains ~1–8% broken base pairs in MD.
RECOMMENDED_BP_PER_TURN_MIN: float = 9.0
RECOMMENDED_BP_PER_TURN_MAX: float = 12.0

# Per-cell delta corresponding to the recommended window:
#   bp/turn = (7 + δ) × 10.5 / 7  ⇒  9 bp/turn → δ = −1,  12 bp/turn → δ = +1.
# So the high-yield band is roughly |δ_per_cell| ≤ 1 (vs the hard limit of 3).
RECOMMENDED_DELTA_PER_CELL: int = 1

# Float tolerance for inclusive boundary comparisons (exactly 9/12/6/15 bp/turn).
_BP_PER_TURN_EPS: float = 1e-9


class DeformationFeasibility(str, Enum):
    """Verdict for a requested bend/twist's local loop/skip density."""

    OK = "ok"        # inside the 9–12 bp/turn high-yield window
    WARN = "warn"    # outside 9–12 but inside 6–15 → low folding yield expected
    BLOCK = "block"  # outside 6–15 bp/turn → physically unachievable

# ── Geometry helpers ──────────────────────────────────────────────────────────


def _helix_cross_section_offset(
    helix: Helix,
    centroid: np.ndarray,
    tangent: np.ndarray,
) -> np.ndarray:
    """
    Return the cross-section offset vector for *helix* (perpendicular to
    *tangent*, measured from *centroid*).
    """
    start = helix.axis_start.to_array()
    raw = start - centroid
    return raw - np.dot(raw, tangent) * tangent


def _bundle_centroid_and_tangent(
    helices: list[Helix],
) -> tuple[np.ndarray, np.ndarray]:
    """Return (centroid, unit_tangent) for the given helix list."""
    if not helices:
        return np.zeros(3), np.array([0.0, 0.0, 1.0])
    starts = np.array([h.axis_start.to_array() for h in helices])
    centroid = starts.mean(axis=0)
    h0 = helices[0]
    axis = h0.axis_end.to_array() - h0.axis_start.to_array()
    norm = np.linalg.norm(axis)
    tangent = axis / norm if norm > 1e-12 else np.array([0.0, 0.0, 1.0])
    return centroid, tangent


def _cell_boundaries(plane_a_bp: int, plane_b_bp: int) -> list[tuple[int, int]]:
    """Return list of (cell_start, cell_end) for complete 7-bp cells."""
    cells: list[tuple[int, int]] = []
    bp = plane_a_bp
    while bp + CELL_BP_DEFAULT <= plane_b_bp:
        cells.append((bp, bp + CELL_BP_DEFAULT))
        bp += CELL_BP_DEFAULT
    return cells


def _active_intervals_for_helices(
    design: "Design",
    helix_ids: set[str],
) -> list[tuple[int, int]]:
    """
    Return sorted, merged bp intervals that are *double-stranded* on any helix in
    *helix_ids*.

    A position is double-stranded when it is covered by a domain on the FORWARD
    track AND a domain on the REVERSE track of the same helix.  Single-stranded
    scaffold domains (scaffold extends past the last crossover with no paired
    staple) are excluded — skips and loops only make physical sense in dsDNA.

    Each interval is (start_inclusive, end_exclusive).
    """
    # Per-helix FORWARD and REVERSE raw intervals (exclusive end).
    fwd: dict[str, list[tuple[int, int]]] = {hid: [] for hid in helix_ids}
    rev: dict[str, list[tuple[int, int]]] = {hid: [] for hid in helix_ids}
    for strand in design.strands:
        for domain in strand.domains:
            if domain.helix_id not in helix_ids:
                continue
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp) + 1  # exclusive
            if domain.direction == Direction.FORWARD:
                fwd[domain.helix_id].append((lo, hi))
            else:
                rev[domain.helix_id].append((lo, hi))

    def _merge(ivls: list[tuple[int, int]]) -> list[tuple[int, int]]:
        if not ivls:
            return []
        ivls = sorted(ivls)
        m: list[list[int]] = [list(ivls[0])]
        for a, b in ivls[1:]:
            if a <= m[-1][1]:
                m[-1][1] = max(m[-1][1], b)
            else:
                m.append([a, b])
        return [(a, b) for a, b in m]

    def _intersect(
        a_ivls: list[tuple[int, int]],
        b_ivls: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        ai = bi = 0
        while ai < len(a_ivls) and bi < len(b_ivls):
            lo = max(a_ivls[ai][0], b_ivls[bi][0])
            hi = min(a_ivls[ai][1], b_ivls[bi][1])
            if lo < hi:
                result.append((lo, hi))
            if a_ivls[ai][1] < b_ivls[bi][1]:
                ai += 1
            else:
                bi += 1
        return result

    # Compute dsDNA intervals per helix, then merge across all requested helices.
    all_ds: list[tuple[int, int]] = []
    for hid in helix_ids:
        ds = _intersect(_merge(fwd[hid]), _merge(rev[hid]))
        all_ds.extend(ds)

    if not all_ds:
        return []
    all_ds.sort()
    merged: list[list[int]] = [list(all_ds[0])]
    for a, b in all_ds[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def _cells_from_active_intervals(
    intervals: list[tuple[int, int]],
    plane_a: int,
    plane_b: int,
) -> list[tuple[int, int]]:
    """
    Return cells from ``_cell_boundaries(plane_a, plane_b)`` that fall entirely
    within an active interval.

    Cells are aligned to *plane_a* (same as the original ``_cell_boundaries`` output),
    preserving exact bp positions for helices with full coverage.

    Returns [] when the helix has no DNA in [plane_a, plane_b] — those helices receive
    no loop/skip modifications rather than having mods redirected to adjacent DNA.
    """
    result: list[tuple[int, int]] = []
    for c_start, c_end in _cell_boundaries(plane_a, plane_b):
        for ivl_start, ivl_end in intervals:
            if ivl_start <= c_start and c_end <= ivl_end:
                result.append((c_start, c_end))
                break
    return result


# ── Limit helpers ──────────────────────────────────────────────────────────────


def validate_loop_skip_limits(
    n_del_per_cell: float,
    n_ins_per_cell: float,
    label: str = "",
) -> None:
    """
    Raise ValueError if the per-cell modification density violates the
    6–15 bp/turn constraint (i.e. exceeds ±3 bp per cell).

    Args:
        n_del_per_cell: average deletions per array cell (non-negative).
        n_ins_per_cell: average insertions per array cell (non-negative).
        label: optional context string for the error message.
    """
    if n_del_per_cell > MAX_DELTA_PER_CELL:
        raise ValueError(
            f"{'[' + label + '] ' if label else ''}"
            f"Deletion density {n_del_per_cell:.2f} bp/cell exceeds "
            f"maximum {MAX_DELTA_PER_CELL} (minimum 4 bp/cell = 6 bp/turn)."
        )
    if n_ins_per_cell > MAX_DELTA_PER_CELL:
        raise ValueError(
            f"{'[' + label + '] ' if label else ''}"
            f"Insertion density {n_ins_per_cell:.2f} bp/cell exceeds "
            f"maximum {MAX_DELTA_PER_CELL} (maximum 10 bp/cell = 15 bp/turn)."
        )


def min_bend_radius_nm(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    direction_deg: float = 0.0,
) -> float:
    """
    Minimum achievable bend radius (nm) for *segment_helices* given the
    ±3 bp/cell modification limit.

    Formula: R_min = 7 × r_max / 3  where r_max is the maximum cross-section
    offset of any helix in the bend direction.

    If all helices lie on the neutral axis, returns inf (can't bend).
    """
    if not segment_helices:
        return math.inf
    centroid, tangent = _bundle_centroid_and_tangent(segment_helices)
    phi = math.radians(direction_deg)
    bend_hat = np.array([math.cos(phi), math.sin(phi), 0.0])
    # Project onto the plane perpendicular to tangent
    bend_hat = bend_hat - np.dot(bend_hat, tangent) * tangent
    bn = np.linalg.norm(bend_hat)
    if bn < 1e-12:
        return math.inf
    bend_hat /= bn

    offsets = [
        abs(np.dot(_helix_cross_section_offset(h, centroid, tangent), bend_hat))
        for h in segment_helices
    ]
    r_max = max(offsets)
    if r_max < 1e-9:
        return math.inf
    return CELL_BP_DEFAULT * r_max / MAX_DELTA_PER_CELL


def max_twist_deg(n_cells: int) -> float:
    """
    Maximum achievable |twist| (degrees) over *n_cells* array cells with
    uniform deletions or insertions (3 per cell maximum).

    Positive value = max left-handed (deletions); same magnitude for right.
    """
    return n_cells * MAX_DELTA_PER_CELL * _LOOP_SKIP_TWIST_PER_BP_DEG


# ── Feasibility classification ─────────────────────────────────────────────────


def classify_local_density(
    signed_delta_per_cell: float,
) -> tuple[DeformationFeasibility, float]:
    """
    Classify a *signed* per-cell loop/skip density into OK / WARN / BLOCK and
    return the implied local twist density.

    The 7-bp array cell becomes ``7 + signed_delta`` bp, so::

        local_bp_per_turn = (CELL_BP_DEFAULT + signed_delta) × 10.5 / CELL_BP_DEFAULT

    Sign matters because the high-yield window is asymmetric in delta-space:
    deletions (δ < 0, overtwist) leave the 9–12 band at 9 bp/turn (δ = −1) while
    insertions (δ > 0, undertwist) leave it at 12 bp/turn (δ = +1). The caller
    must pass the worst (most-strained) helix's signed density.

    Boundaries are inclusive: exactly 9/12 bp/turn → OK, exactly 6/15 → WARN.
    """
    local_bp_per_turn = (
        (CELL_BP_DEFAULT + signed_delta_per_cell)
        * _LOOP_SKIP_BP_PER_TURN
        / CELL_BP_DEFAULT
    )
    if (
        local_bp_per_turn < HARD_BP_PER_TURN_MIN - _BP_PER_TURN_EPS
        or local_bp_per_turn > HARD_BP_PER_TURN_MAX + _BP_PER_TURN_EPS
    ):
        return DeformationFeasibility.BLOCK, local_bp_per_turn
    if (
        local_bp_per_turn < RECOMMENDED_BP_PER_TURN_MIN - _BP_PER_TURN_EPS
        or local_bp_per_turn > RECOMMENDED_BP_PER_TURN_MAX + _BP_PER_TURN_EPS
    ):
        return DeformationFeasibility.WARN, local_bp_per_turn
    return DeformationFeasibility.OK, local_bp_per_turn


def _bend_params_to_radius_nm(curvature_deg_per_bp: float) -> float:
    """
    Convert a ``BendParams.curvature_deg_per_bp`` (κ) into a radius of curvature
    in nm, matching the geometric layer exactly (``deformation.py`` uses
    ``R = RISE_PER_BP / radians(κ)``).

    Returns inf for a (near-)zero curvature — an unbent, infinite-radius arc.
    The radius is plane-independent: κ alone fixes the curvature; the window
    length [plane_a, plane_b] only scales the *total* bend angle, not the radius.
    """
    kappa_rad = math.radians(abs(curvature_deg_per_bp))
    if kappa_rad < 1e-9:
        return math.inf
    return BDNA_RISE_PER_BP / kappa_rad


def classify_deformation(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    op_type: str,
    params,
    *,
    design: "Design | None" = None,
) -> dict:
    """
    Predict the per-cell loop/skip density a bend or twist ``DeformationOp`` will
    require, and classify it OK / WARN / BLOCK — WITHOUT mutating anything.

    Reuses the exact conversion / per-cell math that ``twist_loop_skips`` and
    ``bend_loop_skips`` use at realization time, so the warning always agrees
    with what Apply will actually do (no drift). Never raises on WARN/BLOCK —
    the verdict is carried in the returned ``status`` field.

    Args:
        segment_helices: helices spanning the deformation window.
        plane_a_bp, plane_b_bp: bp window the op acts on.
        op_type: 'twist' | 'bend'.
        params: a ``TwistParams`` or ``BendParams``.
        design: optional, for dsDNA-aware per-helix cell scoping (bend).

    Returns a dict with keys: status, op_type, local_bp_per_turn,
    max_abs_delta_per_cell, n_cells, requested_twist_deg, max_twist_deg,
    requested_radius_nm, min_bend_radius_nm, message.
    """
    n_cells = len(_cell_boundaries(plane_a_bp, plane_b_bp))

    result = {
        "status": DeformationFeasibility.OK.value,
        "op_type": op_type,
        "local_bp_per_turn": _LOOP_SKIP_BP_PER_TURN,
        "max_abs_delta_per_cell": 0.0,
        "n_cells": n_cells,
        "requested_twist_deg": None,
        "max_twist_deg": None,
        "requested_radius_nm": None,
        "min_bend_radius_nm": None,
        "message": "",
    }

    if n_cells == 0 or not segment_helices:
        result["message"] = "Segment too short for any 7-bp array cell — no marks placed."
        return result

    if op_type == "twist":
        # Mirror crud.py twist conversion: total_degrees | degrees_per_nm.
        target_deg = getattr(params, "total_degrees", None)
        if target_deg is None:
            dpn = getattr(params, "degrees_per_nm", None)
            if dpn is None:
                result["message"] = "No twist specified."
                return result
            length_nm = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP
            target_deg = dpn * length_nm

        total_mods = target_deg / _LOOP_SKIP_TWIST_PER_BP_DEG
        # +twist (left-handed) → deletions → cell loses bp → signed delta < 0.
        signed_delta = -total_mods / n_cells
        status, bp_per_turn = classify_local_density(signed_delta)
        max_twist = max_twist_deg(n_cells)

        result.update(
            status=status.value,
            local_bp_per_turn=bp_per_turn,
            max_abs_delta_per_cell=abs(total_mods) / n_cells,
            requested_twist_deg=target_deg,
            max_twist_deg=max_twist,
        )
        if status is DeformationFeasibility.BLOCK:
            result["message"] = (
                f"Twist {target_deg:.0f}° exceeds maximum {max_twist:.0f}° over "
                f"{n_cells} cells ({bp_per_turn:.1f} bp/turn outside 6–15) — unachievable."
            )
        elif status is DeformationFeasibility.WARN:
            result["message"] = (
                f"Local density {bp_per_turn:.1f} bp/turn outside recommended "
                f"9–12 — low folding yield expected."
            )
        return result

    # ── bend ──
    radius_nm = _bend_params_to_radius_nm(
        getattr(params, "curvature_deg_per_bp", 0.0)
    )
    direction_deg = getattr(params, "direction_deg", 0.0)
    min_radius = min_bend_radius_nm(segment_helices, plane_a_bp, plane_b_bp, direction_deg)
    result["requested_radius_nm"] = None if math.isinf(radius_nm) else radius_nm
    result["min_bend_radius_nm"] = None if math.isinf(min_radius) else min_radius

    if math.isinf(radius_nm):
        result["message"] = "No bend curvature specified."
        return result

    # Worst-case signed per-cell density across helices (same math as realization).
    per_helix = _bend_per_cell_deltas(
        segment_helices, plane_a_bp, plane_b_bp, radius_nm, direction_deg, design=design
    )
    worst_status = DeformationFeasibility.OK
    worst_bp_per_turn = _LOOP_SKIP_BP_PER_TURN
    worst_rank = (-1, 0.0)  # (severity, |deviation from 10.5|)
    max_abs = 0.0
    for _h_id, delta_sign, n_mods, h_cells in per_helix:
        h_n_cells = len(h_cells)
        if h_n_cells == 0 or n_mods == 0:
            continue
        signed_delta = delta_sign * (n_mods / h_n_cells)
        max_abs = max(max_abs, abs(signed_delta))
        status, bp_per_turn = classify_local_density(signed_delta)
        # Rank by (severity, deviation) so local_bp_per_turn is the most-strained
        # helix's density even when every helix is still OK.
        rank = (_SEVERITY[status], abs(bp_per_turn - _LOOP_SKIP_BP_PER_TURN))
        if rank > worst_rank:
            worst_rank = rank
            worst_status = status
            worst_bp_per_turn = bp_per_turn

    result.update(
        status=worst_status.value,
        local_bp_per_turn=worst_bp_per_turn,
        max_abs_delta_per_cell=max_abs,
    )
    if worst_status is DeformationFeasibility.BLOCK:
        min_txt = f"{min_radius:.1f}" if not math.isinf(min_radius) else "∞"
        result["message"] = (
            f"Bend radius {radius_nm:.1f} nm below minimum {min_txt} nm "
            f"({worst_bp_per_turn:.1f} bp/turn outside 6–15) — unachievable."
        )
    elif worst_status is DeformationFeasibility.WARN:
        result["message"] = (
            f"Local density {worst_bp_per_turn:.1f} bp/turn outside recommended "
            f"9–12 — low folding yield expected."
        )
    return result


_SEVERITY = {
    DeformationFeasibility.OK: 0,
    DeformationFeasibility.WARN: 1,
    DeformationFeasibility.BLOCK: 2,
}


# ── Twist loop/skip computation ────────────────────────────────────────────────


def twist_loop_skips(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    target_twist_deg: float,
    *,
    design: "Design | None" = None,
) -> dict[str, list[LoopSkip]]:
    """
    Compute loop/skip modifications to produce *target_twist_deg* of global
    twist over the segment [plane_a_bp, plane_b_bp].

    Convention:
      target_twist_deg > 0 → left-handed (deletions / skips)
      target_twist_deg < 0 → right-handed (insertions / loops)

    Each modification (skip or loop) contributes ±_LOOP_SKIP_TWIST_PER_BP_DEG °
    of unrelieved angular misalignment per array cell, which the bundle
    relieves as global twist.

    Modifications are distributed as evenly as possible across cells using
    a Bresenham-style integer distribution (no rounding accumulation).

    Returns:
        dict mapping helix_id → sorted list of LoopSkip objects.

    Raises:
        ValueError if |target_twist_deg| exceeds the per-cell limit.
    """
    global_cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(global_cells)

    if n_cells == 0:
        return {h.id: [] for h in segment_helices}

    # Total modifications needed (signed; positive = deletions, negative = loops)
    # Each modification = ±_LOOP_SKIP_TWIST_PER_BP_DEG angular change
    total_mods = target_twist_deg / _LOOP_SKIP_TWIST_PER_BP_DEG
    n_del_total = max(0.0, total_mods)
    n_ins_total = max(0.0, -total_mods)

    # Per-cell density check (global — same n_mods for every helix)
    validate_loop_skip_limits(
        n_del_total / n_cells,
        n_ins_total / n_cells,
        label=f"twist {target_twist_deg:.1f}°",
    )

    n_del = round(n_del_total)
    n_ins = round(n_ins_total)
    delta = -1 if n_del > 0 else +1
    n_mods = n_del if n_del > 0 else n_ins

    result: dict[str, list[LoopSkip]] = {h.id: [] for h in segment_helices}

    for h in segment_helices:
        # Compute per-helix active cells; fall back to global cells when design is absent.
        if design is not None:
            h_intervals = _active_intervals_for_helices(design, {h.id})
            h_cells = _cells_from_active_intervals(h_intervals, plane_a_bp, plane_b_bp)
        else:
            h_cells = global_cells
        h_n_cells = len(h_cells)
        if h_n_cells == 0:
            continue

        # Scale mod count to the fraction of the segment this helix actually spans.
        # A helix covering only part of [plane_a_bp, plane_b_bp] should receive
        # proportionally fewer modifications, not the full global count crammed into
        # fewer cells (which would cluster marks at the helix's left edge).
        h_n_mods = round(n_mods * h_n_cells / n_cells)
        if h_n_mods == 0:
            continue

        # Bresenham distribution across this helix's cells.
        cell_mod_counts = [0] * h_n_cells
        for i in range(h_n_mods):
            cell_idx = (i * h_n_cells) // h_n_mods
            cell_mod_counts[cell_idx] += 1

        for cell_idx, count in enumerate(cell_mod_counts):
            if count == 0:
                continue
            cell_start, cell_end = h_cells[cell_idx]
            cell_len = cell_end - cell_start
            for j in range(count):
                bp_pos = cell_start + (j * cell_len) // count
                result[h.id].append(LoopSkip(bp_index=bp_pos, delta=delta))

        result[h.id].sort(key=lambda ls: ls.bp_index)

    return result


# ── Bend loop/skip computation ─────────────────────────────────────────────────


def _bend_per_cell_deltas(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    radius_nm: float,
    direction_deg: float = 0.0,
    *,
    design: "Design | None" = None,
) -> list[tuple[str, int, int, list[tuple[int, int]]]]:
    """
    Compute, per helix, the loop/skip count required for a bend of *radius_nm*,
    WITHOUT validating limits or placing marks.

    Shared by ``bend_loop_skips`` (which validates + Bresenham-distributes) and
    ``classify_deformation`` (which classifies the density) so the two never
    disagree about what a given bend requires.

    Returns a list of ``(helix_id, delta_sign, n_mods, h_cells)`` for every helix
    that needs at least one modification. ``delta_sign`` is +1 (insertions/outer
    arc) or −1 (deletions/inner arc); ``n_mods`` is the total bp change; ``h_cells``
    is that helix's list of (start, end) array cells.
    """
    global_cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(global_cells)
    if n_cells == 0 or not segment_helices:
        return []

    # Pre-compute per-helix active cells so they can be reused for centroid.
    if design is not None:
        h_cells_map: dict[str, list[tuple[int, int]]] | None = {
            h.id: _cells_from_active_intervals(
                _active_intervals_for_helices(design, {h.id}),
                plane_a_bp, plane_b_bp,
            )
            for h in segment_helices
        }
        active_for_centroid = [h for h in segment_helices if h_cells_map[h.id]]
        centroid_helices = active_for_centroid if active_for_centroid else segment_helices
    else:
        h_cells_map = None
        centroid_helices = segment_helices

    centroid, tangent = _bundle_centroid_and_tangent(centroid_helices)

    # Bend direction unit vector in the cross-section plane.
    phi = math.radians(direction_deg)
    raw_bend = np.array([math.cos(phi), math.sin(phi), 0.0])
    raw_bend = raw_bend - np.dot(raw_bend, tangent) * tangent
    bn = np.linalg.norm(raw_bend)
    if bn < 1e-12:
        return []  # Degenerate: bend direction parallel to axis
    bend_hat = raw_bend / bn

    curvature = 1.0 / radius_nm

    out: list[tuple[str, int, int, list[tuple[int, int]]]] = []
    for h in segment_helices:
        h_cells = h_cells_map[h.id] if h_cells_map is not None else global_cells
        h_n_cells = len(h_cells)
        if h_n_cells == 0:
            continue

        cs_offset = _helix_cross_section_offset(h, centroid, tangent)
        r_i = float(np.dot(cs_offset, bend_hat))  # nm; signed

        # Helix's own arc length so partially-spanning helices get proportionally
        # fewer modifications instead of clustering them at the left edge.
        h_L_nom = h_n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP  # nm

        # bend_hat points toward the centre of curvature (inner side); r_i > 0 is
        # the inner (shorter) arc → needs deletions, so negate delta_L.
        delta_L = -h_L_nom * r_i * curvature
        delta_bp_total = round(delta_L / BDNA_RISE_PER_BP)
        if delta_bp_total == 0:
            continue

        delta_sign = 1 if delta_bp_total > 0 else -1
        out.append((h.id, delta_sign, abs(delta_bp_total), h_cells))

    return out


def bend_loop_skips(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    radius_nm: float,
    direction_deg: float = 0.0,
    *,
    design: "Design | None" = None,
) -> dict[str, list[LoopSkip]]:
    """
    Compute per-helix loop/skip modifications to produce a bend of radius
    *radius_nm* in direction *direction_deg* (degrees, 0 = +X in cross-section)
    over the segment [plane_a_bp, plane_b_bp].

    Physical model:
      Each helix at cross-section offset r_i (nm, in bend direction) requires
      an effective arc-length change of ΔL_i = L_nom × r_i / R over the segment.
      This is achieved by Δ_bp_i = round(ΔL_i / RISE_PER_BP) total bp changes.
      Those Δ_bp_i modifications are distributed evenly across the n_cells cells
      of that helix.

    Positive r_i (outer side): insertions → longer arc.
    Negative r_i (inner side): deletions → shorter arc.

    The gradient of insertions (outer) and deletions (inner) automatically
    cancels the net torsional contribution (left-hand torque from deletions ≈
    right-hand torque from insertions), yielding near-pure bend.

    Returns:
        dict mapping helix_id → sorted list of LoopSkip objects.

    Raises:
        ValueError if the required modification density at any helix exceeds
        ±3 bp/cell (radius_nm < min_bend_radius_nm).
    """
    result: dict[str, list[LoopSkip]] = {h.id: [] for h in segment_helices}

    for h_id, delta_sign, n_mods, h_cells in _bend_per_cell_deltas(
        segment_helices, plane_a_bp, plane_b_bp, radius_nm, direction_deg, design=design
    ):
        h_n_cells = len(h_cells)

        # Per-cell density check (using this helix's cell count).
        n_del_cell = n_mods / h_n_cells if delta_sign < 0 else 0.0
        n_ins_cell = n_mods / h_n_cells if delta_sign > 0 else 0.0
        validate_loop_skip_limits(
            n_del_cell,
            n_ins_cell,
            label=f"helix {h_id} R={radius_nm:.1f}nm dir={direction_deg:.0f}°",
        )

        # Bresenham distribution across this helix's cells.
        cell_mod_counts = [0] * h_n_cells
        for i in range(n_mods):
            cell_idx = (i * h_n_cells) // n_mods
            cell_mod_counts[cell_idx] += 1

        for cell_idx, count in enumerate(cell_mod_counts):
            if count == 0:
                continue
            cell_start, cell_end = h_cells[cell_idx]
            cell_len = cell_end - cell_start
            for j in range(count):
                bp_pos = cell_start + (j * cell_len) // count
                result[h_id].append(LoopSkip(bp_index=bp_pos, delta=delta_sign))

        result[h_id].sort(key=lambda ls: ls.bp_index)

    return result


# ── Prediction (inverse check) ─────────────────────────────────────────────────


def predict_global_twist_deg(
    modifications: dict[str, list[LoopSkip]],
) -> float:
    """
    Predict the global twist angle (degrees) accumulated from *modifications*.

    Formula: twist = (net_del − net_ins) × _LOOP_SKIP_TWIST_PER_BP_DEG
      where net_del and net_ins are the average counts across all helices.

    Positive = left-handed, negative = right-handed.
    """
    if not modifications:
        return 0.0
    net_per_helix: list[float] = []
    for ls_list in modifications.values():
        net = sum(ls.delta for ls in ls_list)
        net_per_helix.append(float(-net))   # delta=-1 → del → +twist
    avg_net = float(np.mean(net_per_helix))
    return avg_net * _LOOP_SKIP_TWIST_PER_BP_DEG


def predict_radius_nm(
    segment_helices: list[Helix],
    modifications: dict[str, list[LoopSkip]],
    plane_a_bp: int,
    plane_b_bp: int,
    direction_deg: float = 0.0,
) -> float:
    """
    Predict the radius of curvature (nm) that *modifications* will produce.

    Uses the elastic continuum formula:
      κ = Σ_i(ΔL_i × r_i) / (L_nom × Σ_i(r_i²))

    where:
      ΔL_i  = total effective length change for helix i (bp × RISE_PER_BP)
      r_i   = cross-section offset in *direction_deg* direction (nm)
      L_nom = n_cells × 7 × RISE_PER_BP

    Returns inf if Σ(r_i²) ≈ 0 (all helices on neutral axis) or if the
    net curvature is negligible.
    """
    cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(cells)
    if n_cells == 0 or not segment_helices:
        return math.inf

    centroid, tangent = _bundle_centroid_and_tangent(segment_helices)
    phi = math.radians(direction_deg)
    raw_bend = np.array([math.cos(phi), math.sin(phi), 0.0])
    raw_bend = raw_bend - np.dot(raw_bend, tangent) * tangent
    bn = np.linalg.norm(raw_bend)
    if bn < 1e-12:
        return math.inf
    bend_hat = raw_bend / bn

    L_nom = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP

    numerator = 0.0
    denominator = 0.0
    for h in segment_helices:
        cs_offset = _helix_cross_section_offset(h, centroid, tangent)
        r_i = float(np.dot(cs_offset, bend_hat))
        denominator += r_i ** 2

        ls_list = modifications.get(h.id, [])
        delta_bp = sum(ls.delta for ls in ls_list)
        delta_L = delta_bp * BDNA_RISE_PER_BP
        numerator += delta_L * r_i

    if abs(denominator) < 1e-12 or abs(numerator) < 1e-12:
        return math.inf

    kappa = numerator / (L_nom * denominator)
    if abs(kappa) < 1e-12:
        return math.inf
    return abs(1.0 / kappa)


# ── Apply modifications to Design ─────────────────────────────────────────────


def apply_loop_skips(
    design: "Design",
    modifications: dict[str, list[LoopSkip]],
) -> "Design":
    """
    Return a new Design with *modifications* applied to the relevant helices.

    For each helix_id in *modifications*, this replaces the helix's
    loop_skips with the provided list (merging: existing entries outside
    the modification range are preserved; entries inside are overwritten).

    Does NOT push to the undo stack — callers must do that via state.py.
    """

    new_helices = []
    for h in design.helices:
        if h.id not in modifications:
            new_helices.append(h)
            continue
        new_ls = modifications[h.id]
        # Build a dict of existing loop_skips, overwrite with new ones
        existing = {ls.bp_index: ls for ls in h.loop_skips}
        for ls in new_ls:
            existing[ls.bp_index] = ls
        merged = sorted(existing.values(), key=lambda x: x.bp_index)
        new_helices.append(h.model_copy(update={"loop_skips": merged}))

    return design.copy_with(helices=new_helices)


SQ_SKIP_PERIOD_DEFAULT = 48
"""Canonical square-lattice de-twist skip period (one deletion per 48 bp per helix).
The self-consistency tuning loop (skip_twist_tuning.py) treats this as the seed knob
and validates/adjusts it against the simulated mean structure."""


def sq_lattice_periodic_skips(
    design: "Design", skip_period: int = SQ_SKIP_PERIOD_DEFAULT,
) -> dict[str, list[LoopSkip]]:
    """Return one skip per ``skip_period`` bp on every helix of a square-lattice design.

    Skips are staggered by helix index so no two helices share the same
    cross-sectional slice: offset_i = (i * skip_period) // N.  ``skip_period`` defaults
    to the canonical 48 bp (caller behaviour unchanged); the skip-twist tuning loop
    varies it to drive the simulated global twist to match the straight analytic
    depiction.

    Positions that already carry a loop_skip are left unchanged (the caller
    adds these mods *before* deformation mods so deformation results win on
    conflict).
    """
    from backend.core.models import LatticeType

    if design.lattice_type != LatticeType.SQUARE:
        return {}
    if skip_period < 1:
        raise ValueError(f"skip_period must be >= 1, got {skip_period}")

    SKIP_PERIOD = int(skip_period)
    helices = sorted(design.helices, key=lambda h: h.id)
    n = len(helices)
    if n == 0:
        return {}

    result: dict[str, list[LoopSkip]] = {}
    for i, helix in enumerate(helices):
        offset = (i * SKIP_PERIOD) // n
        existing_bps = {ls.bp_index for ls in helix.loop_skips}

        # dsDNA intervals for this helix (GLOBAL, exclusive end).
        # Skips must only be placed where both tracks carry a domain — single-
        # stranded scaffold overhangs at helix ends would otherwise get marks.
        ds_ivls = _active_intervals_for_helices(design, {helix.id})

        skips: list[LoopSkip] = []
        # Iterate in LOCAL space [0, length_bp) but store GLOBAL bp_index
        # (= bp_start + local).  All other bp coordinates in the system
        # (domain start_bp/end_bp, deformation modifications) are GLOBAL.
        bp_local = offset
        while bp_local < helix.length_bp:
            bp_global = helix.bp_start + bp_local
            in_ds = any(lo <= bp_global < hi for lo, hi in ds_ivls)
            if bp_global not in existing_bps and in_ds:
                skips.append(LoopSkip(bp_index=bp_global, delta=-1))
            bp_local += SKIP_PERIOD
        if skips:
            result[helix.id] = skips

    return result


def clear_loop_skips(
    design: "Design",
    helix_ids: list[str],
    plane_a_bp: int,
    plane_b_bp: int,
) -> "Design":
    """
    Return a new Design with all loop_skips in [plane_a_bp, plane_b_bp)
    removed from the specified helices.
    """

    new_helices = []
    target_ids = set(helix_ids)
    for h in design.helices:
        if h.id not in target_ids:
            new_helices.append(h)
            continue
        kept = [
            ls for ls in h.loop_skips
            if not (plane_a_bp <= ls.bp_index < plane_b_bp)
        ]
        new_helices.append(h.model_copy(update={"loop_skips": kept}))

    return design.copy_with(helices=new_helices)


def clear_all_loop_skips(design: "Design") -> "Design":
    """Return a new Design with all loop_skips removed from every helix."""
    new_helices = [
        h.model_copy(update={"loop_skips": []}) if h.loop_skips else h
        for h in design.helices
    ]
    return design.copy_with(helices=new_helices)


def clear_orphaned_loop_skips(design: "Design") -> "Design":
    """Return a new Design with loop_skips removed at bp positions not covered
    by any strand domain on that helix."""
    raw: dict[str, list[tuple[int, int]]] = {}
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            raw.setdefault(domain.helix_id, []).append((lo, hi))

    coverage: dict[str, list[tuple[int, int]]] = {}
    for hid, ivls in raw.items():
        ivls.sort()
        merged: list[list[int]] = [list(ivls[0])]
        for lo, hi in ivls[1:]:
            if lo <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], hi)
            else:
                merged.append([lo, hi])
        coverage[hid] = [(a, b) for a, b in merged]

    def _is_covered(hid: str, bp: int) -> bool:
        for lo, hi in coverage.get(hid, []):
            if bp < lo:
                break
            if bp <= hi:
                return True
        return False

    new_helices = []
    for h in design.helices:
        if not h.loop_skips:
            new_helices.append(h)
            continue
        kept = [ls for ls in h.loop_skips if _is_covered(h.id, ls.bp_index)]
        new_helices.append(
            h if len(kept) == len(h.loop_skips)
            else h.model_copy(update={"loop_skips": kept})
        )
    return design.copy_with(helices=new_helices)
