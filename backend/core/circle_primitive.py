"""Parametric *circle* (flat disc) primitive — pure geometry.

A "circle" building block is a flat disc of DNA: a single row of parallel
helices whose **lengths** trace the chord profile of a circle. Helix at column
offset ``x`` (nm) from centre gets length ``2·√(R²−x²)`` nm, rounded to an even
number of base pairs so it can be trimmed symmetrically about the disc's mid
plane. The disc therefore lives in the plane that *contains* the helix axis
(column direction × along-helix direction), one helix-layer thick.

This module is the testable heart of the feature: it turns a radius (nm) into a
footprint (lattice cells + per-cell bp lengths) and reports how circular the
result is. It is pure — no IO, no Design, no lattice mutation. The placement
builder (:func:`backend.core.lattice.make_circle_segment`) consumes the cells +
lengths; the catalog surfaces the default radius; the validation test asserts the
circularity metric here.

Layering: core (L1). Frontend mirrors this in
``frontend/src/scene/circle_primitive_logic.js`` — both are pinned to the same
numeric oracle so JS-side preview and Python-side build never diverge.
"""

from __future__ import annotations

import math

from backend.core.constants import BDNA_RISE_PER_BP, SQUARE_COL_PITCH

# Default floor: a column is included only if its ideal chord is at least this
# many bp. Matches the hand-built ``small_circle.nadoc`` (16-bp end helices) and
# keeps the disc edge clean rather than tapering to 2-bp slivers.
DEFAULT_MIN_CHORD_BP = 16


def column_lengths(
    radius_nm: float,
    *,
    col_pitch_nm: float = SQUARE_COL_PITCH,
    rise_nm: float = BDNA_RISE_PER_BP,
    min_chord_bp: int = DEFAULT_MIN_CHORD_BP,
) -> list[tuple[int, int]]:
    """Return ``[(col_offset, length_bp), …]`` for a disc of ``radius_nm``.

    ``col_offset`` is the signed integer column index relative to the centre
    column (0 = centre, the longest chord). Columns are symmetric about 0 and the
    disc is centred *on* a column (odd count), giving a true diameter helix.

    Each length is the even-bp rounding of the chord ``2·√(R²−x²)`` at that
    column's physical offset ``x = col_offset · col_pitch``. A column is dropped
    when its rounded chord is below ``min_chord_bp`` (the edge cutoff). Even
    lengths let the helix be centred symmetrically about the disc mid plane.

    Empty when ``radius_nm`` is too small to admit even the centre column.
    """
    if radius_nm <= 0:
        return []
    max_col = int(radius_nm / col_pitch_nm) + 1
    out: list[tuple[int, int]] = []
    for col in range(-max_col, max_col + 1):
        x = col * col_pitch_nm
        if abs(x) >= radius_nm:
            continue
        chord_nm = 2.0 * math.sqrt(radius_nm * radius_nm - x * x)
        bp = int(round(chord_nm / rise_nm))
        bp -= bp % 2  # force even → symmetric trim about centre
        if bp >= min_chord_bp:
            out.append((col, bp))
    return out


def circle_footprint(
    radius_nm: float,
    *,
    plane: str = "XY",
    col_pitch_nm: float = SQUARE_COL_PITCH,
    rise_nm: float = BDNA_RISE_PER_BP,
    min_chord_bp: int = DEFAULT_MIN_CHORD_BP,
) -> dict | None:
    """Assemble a placement footprint for a disc of ``radius_nm``.

    Returns a dict (or None when no column qualifies):
      ``cells``        — ``[[row, col], …]`` lattice cells, a single row (row 0)
                         with columns ``0 … N-1`` (caller translates to cursor).
      ``cell_lengths`` — per-cell bp length, parallel to ``cells``.
      ``anchor_cell``  — ``[0, 0]`` (lowest col); what snaps to the cursor.
      ``radius_nm`` / ``plane`` / ``min_chord_bp`` — echoed for the builder.
    """
    cols = column_lengths(
        radius_nm,
        col_pitch_nm=col_pitch_nm,
        rise_nm=rise_nm,
        min_chord_bp=min_chord_bp,
    )
    if not cols:
        return None
    # Re-base column offsets to 0…N-1 so the footprint is a clean single row.
    cells = [[0, i] for i in range(len(cols))]
    cell_lengths = [bp for _, bp in cols]
    # Anchor on the CENTRE column (the longest chord) so the cursor sits at the disc's
    # midpoint — the point where the disc touches the slice plane — not at the first
    # helix. The disc is centre-symmetric (odd N) so this is the exact middle.
    anchor_cell = [0, (len(cols) - 1) // 2]
    return {
        "cells": cells,
        "cell_lengths": cell_lengths,
        "anchor_cell": anchor_cell,
        "radius_nm": radius_nm,
        "plane": plane,
        "min_chord_bp": min_chord_bp,
    }


def implied_radii(
    cell_lengths: list[int],
    *,
    col_pitch_nm: float = SQUARE_COL_PITCH,
    rise_nm: float = BDNA_RISE_PER_BP,
) -> list[float]:
    """Per-column implied radius ``√(x² + (L/2)²)`` for a centred disc.

    For a perfect circle every column returns the same value; the spread of this
    list is the circularity error. Assumes ``cell_lengths`` is centre-symmetric
    (a contiguous row), so column offsets run ``-(N-1)/2 … +(N-1)/2``.
    """
    n = len(cell_lengths)
    if n == 0:
        return []
    centre = (n - 1) / 2.0
    out: list[float] = []
    for i, length in enumerate(cell_lengths):
        x = (i - centre) * col_pitch_nm
        half_nm = length * rise_nm / 2.0
        out.append(math.sqrt(x * x + half_nm * half_nm))
    return out


def circularity_spread(
    cell_lengths: list[int],
    *,
    col_pitch_nm: float = SQUARE_COL_PITCH,
    rise_nm: float = BDNA_RISE_PER_BP,
) -> float:
    """Max − min implied radius (nm). 0 = perfect circle; larger = less circular."""
    radii = implied_radii(cell_lengths, col_pitch_nm=col_pitch_nm, rise_nm=rise_nm)
    if not radii:
        return 0.0
    return max(radii) - min(radii)


def fit_radius(
    cell_lengths: list[int],
    *,
    col_pitch_nm: float = SQUARE_COL_PITCH,
    rise_nm: float = BDNA_RISE_PER_BP,
) -> float:
    """Best-fit radius (nm) for an existing centred length profile.

    Mean of the per-column implied radii — used to derive the default radius from
    the hand-built ``small_circle.nadoc`` so the default "corresponds" to it.
    """
    radii = implied_radii(cell_lengths, col_pitch_nm=col_pitch_nm, rise_nm=rise_nm)
    if not radii:
        return 0.0
    return sum(radii) / len(radii)
