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

  validate_loop_skip_limits(n_del_per_cell, n_ins_per_cell) → None | raises
  min_bend_radius_nm(segment_helices, plane_a_bp, plane_b_bp) → float
  max_twist_deg(n_cells, n_helices) → float
  predict_global_twist_deg(modifications) → float
  predict_radius_nm(design_or_helices, modifications, plane_a_bp, plane_b_bp)
      → float
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP, BDNA_TWIST_PER_BP_RAD
from backend.core.models import Helix, LoopSkip, Vec3

if TYPE_CHECKING:
    from backend.core.models import Design

# ── Constants ─────────────────────────────────────────────────────────────────

# B-DNA: 10.5 bp per turn → 240° per 7-bp array cell
BDNA_BP_PER_TURN: float = 10.5
BDNA_TWIST_PER_BP_DEG: float = 360.0 / BDNA_BP_PER_TURN   # ≈ 34.286 °/bp
CELL_BP_DEFAULT: int = 7                                    # default cell size
CELL_TWIST_DEG: float = CELL_BP_DEFAULT * BDNA_TWIST_PER_BP_DEG  # ≈ 240°

# Per-cell modification limits (from Dietz et al. — 6≤T≤15 bp/turn constraint)
# Cell bp count range: [4, 10], so |delta| ≤ 3 per cell.
MAX_DELTA_PER_CELL: int = 3

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
    return n_cells * MAX_DELTA_PER_CELL * BDNA_TWIST_PER_BP_DEG


# ── Twist loop/skip computation ────────────────────────────────────────────────


def twist_loop_skips(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    target_twist_deg: float,
) -> dict[str, list[LoopSkip]]:
    """
    Compute loop/skip modifications to produce *target_twist_deg* of global
    twist over the segment [plane_a_bp, plane_b_bp].

    Convention:
      target_twist_deg > 0 → left-handed (deletions / skips)
      target_twist_deg < 0 → right-handed (insertions / loops)

    Each modification (skip or loop) contributes ±BDNA_TWIST_PER_BP_DEG °
    of unrelieved angular misalignment per array cell, which the bundle
    relieves as global twist.

    Modifications are distributed as evenly as possible across cells using
    a Bresenham-style integer distribution (no rounding accumulation).

    Returns:
        dict mapping helix_id → sorted list of LoopSkip objects.

    Raises:
        ValueError if |target_twist_deg| exceeds the per-cell limit.
    """
    cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(cells)

    if n_cells == 0:
        return {h.id: [] for h in segment_helices}

    # Total modifications needed (signed; positive = deletions, negative = loops)
    # Each modification = ±BDNA_TWIST_PER_BP_DEG angular change
    total_mods = target_twist_deg / BDNA_TWIST_PER_BP_DEG
    n_del_total = max(0.0, total_mods)
    n_ins_total = max(0.0, -total_mods)

    # Per-cell density check
    validate_loop_skip_limits(
        n_del_total / n_cells,
        n_ins_total / n_cells,
        label=f"twist {target_twist_deg:.1f}°",
    )

    n_del = round(n_del_total)
    n_ins = round(n_ins_total)
    delta = -1 if n_del > 0 else +1
    n_mods = n_del if n_del > 0 else n_ins

    # Bresenham distribution: compute per-cell counts then spread within each cell.
    # For n_mods > n_cells, some cells receive 2 or 3 modifications at distinct bp positions.
    cell_mod_counts = [0] * n_cells
    for i in range(n_mods):
        cell_idx = (i * n_cells) // n_mods
        cell_mod_counts[cell_idx] += 1

    result: dict[str, list[LoopSkip]] = {h.id: [] for h in segment_helices}
    for cell_idx, count in enumerate(cell_mod_counts):
        if count == 0:
            continue
        cell_start, cell_end = cells[cell_idx]
        cell_len = cell_end - cell_start  # = CELL_BP_DEFAULT = 7
        # Spread 'count' modifications evenly within the cell at distinct bp positions
        for j in range(count):
            bp_pos = cell_start + (j * cell_len) // count
            for h in segment_helices:
                result[h.id].append(LoopSkip(bp_index=bp_pos, delta=delta))

    # Sort each helix's list by bp_index
    for h_id in result:
        result[h_id].sort(key=lambda ls: ls.bp_index)

    return result


# ── Bend loop/skip computation ─────────────────────────────────────────────────


def bend_loop_skips(
    segment_helices: list[Helix],
    plane_a_bp: int,
    plane_b_bp: int,
    radius_nm: float,
    direction_deg: float = 0.0,
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
    cells = _cell_boundaries(plane_a_bp, plane_b_bp)
    n_cells = len(cells)

    if n_cells == 0 or not segment_helices:
        return {h.id: [] for h in segment_helices}

    centroid, tangent = _bundle_centroid_and_tangent(segment_helices)

    # Bend direction unit vector in the cross-section plane
    phi = math.radians(direction_deg)
    raw_bend = np.array([math.cos(phi), math.sin(phi), 0.0])
    raw_bend = raw_bend - np.dot(raw_bend, tangent) * tangent
    bn = np.linalg.norm(raw_bend)
    if bn < 1e-12:
        # Degenerate: bend direction parallel to axis — nothing to do
        return {h.id: [] for h in segment_helices}
    bend_hat = raw_bend / bn

    L_nom = n_cells * CELL_BP_DEFAULT * BDNA_RISE_PER_BP  # nm
    curvature = 1.0 / radius_nm

    result: dict[str, list[LoopSkip]] = {h.id: [] for h in segment_helices}

    for h in segment_helices:
        cs_offset = _helix_cross_section_offset(h, centroid, tangent)
        r_i = float(np.dot(cs_offset, bend_hat))  # nm; signed

        # Required total length change for this helix (nm)
        delta_L = L_nom * r_i * curvature

        # Convert to integer bp modifications (round to nearest)
        delta_bp_total = round(delta_L / BDNA_RISE_PER_BP)

        if delta_bp_total == 0:
            continue

        delta_sign = 1 if delta_bp_total > 0 else -1
        n_mods = abs(delta_bp_total)

        # Per-cell density check
        n_del_cell = n_mods / n_cells if delta_sign < 0 else 0.0
        n_ins_cell = n_mods / n_cells if delta_sign > 0 else 0.0
        validate_loop_skip_limits(
            n_del_cell,
            n_ins_cell,
            label=f"helix {h.id} R={radius_nm:.1f}nm dir={direction_deg:.0f}°",
        )

        # Bresenham distribution: per-cell counts, then spread within each cell
        cell_mod_counts = [0] * n_cells
        for i in range(n_mods):
            cell_idx = (i * n_cells) // n_mods
            cell_mod_counts[cell_idx] += 1

        for cell_idx, count in enumerate(cell_mod_counts):
            if count == 0:
                continue
            cell_start, cell_end = cells[cell_idx]
            cell_len = cell_end - cell_start
            for j in range(count):
                bp_pos = cell_start + (j * cell_len) // count
                result[h.id].append(LoopSkip(bp_index=bp_pos, delta=delta_sign))

        result[h.id].sort(key=lambda ls: ls.bp_index)

    return result


# ── Prediction (inverse check) ─────────────────────────────────────────────────


def predict_global_twist_deg(
    modifications: dict[str, list[LoopSkip]],
) -> float:
    """
    Predict the global twist angle (degrees) accumulated from *modifications*.

    Formula: twist = (net_del − net_ins) × BDNA_TWIST_PER_BP_DEG
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
    return avg_net * BDNA_TWIST_PER_BP_DEG


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
    from backend.core.models import Design as DesignModel

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

    return DesignModel(
        id=design.id,
        helices=new_helices,
        strands=design.strands,
        crossovers=design.crossovers,
        lattice_type=design.lattice_type,
        metadata=design.metadata,
        deformations=design.deformations,
    )


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
    from backend.core.models import Design as DesignModel

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

    return DesignModel(
        id=design.id,
        helices=new_helices,
        strands=design.strands,
        crossovers=design.crossovers,
        lattice_type=design.lattice_type,
        metadata=design.metadata,
        deformations=design.deformations,
    )
