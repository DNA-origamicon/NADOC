"""
Nearest-neighbour geometry validation for honeycomb and square lattice designs.

Two properties are checked for every helix in a design:

1. **Nearest-neighbour count** — every helix within HELIX_SPACING ± tolerance
   is an antiparallel crossover partner.  For a honeycomb design, no helix
   may have *more* than 3 valid neighbours; interior helices have exactly 3.
   For a square design, interior helices have exactly 4.

2. **Angular distribution** — the angles from each helix to its nearest
   neighbours must reflect the lattice geometry:

   * Honeycomb (3 neighbours): all three angular gaps ≈ 120°.
     This is the defining signature of the honeycomb lattice — the hole cells
     break 4-connectivity down to 3, with uniform 120° spacing.

   * Square (4 neighbours): all four angular gaps ≈ 90°.

3. **Antiparallel constraint** — every nearest neighbour must have the
   opposite scaffold direction.

These tests run on native NADOC designs (make_bundle_design) and are also
re-used as geometry assertions for caDNAno-imported designs once the importer
is available (the ``_assert_neighbor_geometry`` helper is importable).

Expected angular gaps summary
-----------------------------
Honeycomb interior:  [120°, 120°, 120°]
Square interior:     [ 90°,  90°,  90°,  90°]
"""

from __future__ import annotations

import math
from typing import NamedTuple

import pytest

from backend.core.constants import (
    HONEYCOMB_HELIX_SPACING,
    SQUARE_HELIX_SPACING,
)
from backend.core.lattice import (
    LatticeType,
    make_bundle_design,
    scaffold_direction_for_cell,
    square_cell_direction,
)
from backend.core.models import Design, Direction

# ── Tolerance ──────────────────────────────────────────────────────────────────

DIST_TOL  = 0.02   # nm  — rounding / float noise in position computation
ANGLE_TOL = 1.0    # degrees

# ── Cell layouts ───────────────────────────────────────────────────────────────

# 18 valid honeycomb cells (matches _CELLS_18HB in test_lattice.py)
CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]

# 6-cell honeycomb bundle — small, all edges checked
CELLS_6HB = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 1)]

# 3×4 square grid — interior row has 2 fully-connected helices
CELLS_SQ_3X4 = [(r, c) for r in range(3) for c in range(4)]

# ── Geometry helpers ───────────────────────────────────────────────────────────


def _xy(design: Design) -> dict[str, tuple[float, float]]:
    """Map helix_id → (x, y) cross-section position from axis_start."""
    return {h.id: (h.axis_start.x, h.axis_start.y) for h in design.helices}


def _nearest_neighbours(
    hid: str,
    xy: dict[str, tuple[float, float]],
    spacing: float,
    tol: float = DIST_TOL,
) -> list[str]:
    """Return IDs of all helices within *spacing + tol* nm of *hid*."""
    x0, y0 = xy[hid]
    return [
        bid for bid, (x, y) in xy.items()
        if bid != hid and math.hypot(x - x0, y - y0) <= spacing + tol
    ]


def _angles_deg(
    hid: str,
    nbr_ids: list[str],
    xy: dict[str, tuple[float, float]],
) -> list[float]:
    """Return sorted angles (0–360°) from *hid* to each neighbour."""
    x0, y0 = xy[hid]
    angles = [
        math.degrees(math.atan2(xy[b][1] - y0, xy[b][0] - x0)) % 360
        for b in nbr_ids
    ]
    return sorted(angles)


def _circular_gaps(angles: list[float]) -> list[float]:
    """Return sorted circular gaps between consecutive sorted angles."""
    if len(angles) < 2:
        return []
    gaps = []
    for i in range(len(angles)):
        gap = (angles[(i + 1) % len(angles)] - angles[i]) % 360
        gaps.append(gap)
    return sorted(gaps)


def _scaffold_direction(design: Design, hid: str) -> Direction:
    """Return the scaffold Direction for a helix (from its first strand domain)."""
    for strand in design.strands:
        for domain in strand.domains:
            if domain.helix_id == hid:
                return domain.direction
    raise ValueError(f"No strand domain found for helix {hid}")


# ── Public assertion helper (reusable by cadnano import tests) ─────────────────


class NeighbourResult(NamedTuple):
    helix_id: str
    n_neighbours: int
    gaps: list[float]   # sorted circular gaps (degrees)


def _assert_neighbour_geometry(
    design: Design,
    expected_spacing: float,
    expected_interior_count: int,
    expected_gap: float,
    label: str,
) -> list[NeighbourResult]:
    """Assert nearest-neighbour geometry for every helix in *design*.

    Parameters
    ----------
    design:
        The design under test.
    expected_spacing:
        Helix centre-to-centre distance (nm).
    expected_interior_count:
        Neighbour count for a "fully connected" interior helix
        (3 for honeycomb, 4 for square).
    expected_gap:
        Expected angular gap between consecutive neighbours for fully connected
        helices (120° for honeycomb, 90° for square).
    label:
        Prefix for assertion messages.

    Returns
    -------
    List of NeighbourResult for each helix, for further inspection in tests.
    """
    xy = _xy(design)
    dir_map = {h.id: _scaffold_direction(design, h.id) for h in design.helices}
    results: list[NeighbourResult] = []
    failures: list[str] = []

    for h in design.helices:
        hid    = h.id
        nbrs   = _nearest_neighbours(hid, xy, expected_spacing)
        angles = _angles_deg(hid, nbrs, xy)
        gaps   = _circular_gaps(angles)

        results.append(NeighbourResult(hid, len(nbrs), gaps))

        # ── 1. No helix may exceed the lattice maximum ────────────────────
        if len(nbrs) > expected_interior_count:
            failures.append(
                f"  {label} helix {hid}: "
                f"has {len(nbrs)} neighbours > max {expected_interior_count}"
            )
            continue

        # ── 2. All neighbours are antiparallel ────────────────────────────
        for bid in nbrs:
            if dir_map[bid] == dir_map[hid]:
                failures.append(
                    f"  {label} helix {hid}: neighbour {bid} is PARALLEL "
                    f"(both {dir_map[hid].name})"
                )

        # ── 3. Fully-connected helices have uniform angular gaps ──────────
        if len(nbrs) == expected_interior_count and len(gaps) >= 2:
            for gap in gaps:
                if abs(gap - expected_gap) > ANGLE_TOL:
                    failures.append(
                        f"  {label} helix {hid}: angular gap {gap:.1f}° "
                        f"!≈ expected {expected_gap}° "
                        f"(angles={[f'{a:.1f}' for a in angles]})"
                    )

    assert not failures, (
        f"{label}: {len(failures)} geometry failure(s):\n" + "\n".join(failures)
    )
    return results


# ── Honeycomb tests ────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def design_18hb():
    return make_bundle_design(CELLS_18HB, length_bp=126)


@pytest.fixture(scope="module")
def design_6hb():
    return make_bundle_design(CELLS_6HB, length_bp=42)


def test_honeycomb_no_helix_exceeds_3_neighbours(design_18hb):
    """No honeycomb helix may have more than 3 nearest neighbours."""
    xy = _xy(design_18hb)
    violations: list[str] = []
    for h in design_18hb.helices:
        nbrs = _nearest_neighbours(h.id, xy, HONEYCOMB_HELIX_SPACING)
        if len(nbrs) > 3:
            violations.append(f"  {h.id}: {len(nbrs)} neighbours")
    assert not violations, (
        f"Helices with more than 3 nearest neighbours:\n" + "\n".join(violations)
    )


def test_honeycomb_interior_helices_have_3_neighbours(design_18hb):
    """Helices fully surrounded by design cells must have exactly 3 neighbours."""
    xy      = _xy(design_18hb)
    cell_set = set(CELLS_18HB)
    results  = _assert_neighbour_geometry(
        design_18hb,
        HONEYCOMB_HELIX_SPACING,
        expected_interior_count=3,
        expected_gap=120.0,
        label="18HB HC",
    )
    # At least some helices must be interior (otherwise the design is degenerate)
    interior = [r for r in results if r.n_neighbours == 3]
    assert len(interior) >= 1, (
        "18HB design has no interior helices (all edge/corner) — "
        "cell layout may be wrong"
    )


def test_honeycomb_6hb_geometry_valid(design_6hb):
    """6HB design: all neighbour pairs are antiparallel and at correct distance.

    The 6HB layout used here is all-edge (no helix has all 3 honeycomb
    neighbours present in the design), so the angular-gap check does not
    fire.  The distance and antiparallel checks still apply to every pair.
    """
    results = _assert_neighbour_geometry(
        design_6hb,
        HONEYCOMB_HELIX_SPACING,
        expected_interior_count=3,
        expected_gap=120.0,
        label="6HB HC",
    )
    # All 6 helices in this layout are edge helices (0–2 neighbours each)
    assert all(r.n_neighbours <= 2 for r in results), (
        "Expected all 6HB helices to be edge helices (≤2 neighbours) "
        "for this cell layout"
    )


def test_honeycomb_angular_gaps_are_120_degrees(design_18hb):
    """All interior honeycomb helices must have uniform 120° angular gaps."""
    xy      = _xy(design_18hb)
    failures: list[str] = []
    for h in design_18hb.helices:
        nbrs = _nearest_neighbours(h.id, xy, HONEYCOMB_HELIX_SPACING)
        if len(nbrs) != 3:
            continue   # edge/corner helices — skip gap check
        angles = _angles_deg(h.id, nbrs, xy)
        gaps   = _circular_gaps(angles)
        for gap in gaps:
            if abs(gap - 120.0) > ANGLE_TOL:
                failures.append(
                    f"  {h.id}: gap {gap:.2f}° ≠ 120° "
                    f"(neighbours={nbrs}, angles={[f'{a:.1f}' for a in angles]})"
                )
    assert not failures, (
        f"Interior helices with non-120° gaps:\n" + "\n".join(failures)
    )


def test_honeycomb_all_neighbours_are_antiparallel(design_18hb):
    """Every nearest neighbour pair must be antiparallel (opposite scaffold direction)."""
    xy      = _xy(design_18hb)
    dir_map = {h.id: _scaffold_direction(design_18hb, h.id) for h in design_18hb.helices}
    failures: list[str] = []
    for h in design_18hb.helices:
        nbrs = _nearest_neighbours(h.id, xy, HONEYCOMB_HELIX_SPACING)
        for bid in nbrs:
            if dir_map[bid] == dir_map[h.id]:
                failures.append(
                    f"  {h.id} ({dir_map[h.id].name}) ↔ {bid} ({dir_map[bid].name})"
                )
    assert not failures, (
        "Parallel nearest-neighbour pairs found:\n" + "\n".join(failures)
    )


def test_honeycomb_neighbour_distances_exact(design_18hb):
    """Every nearest-neighbour pair must be separated by exactly HONEYCOMB_HELIX_SPACING."""
    xy      = _xy(design_18hb)
    failures: list[str] = []
    for h in design_18hb.helices:
        x0, y0 = xy[h.id]
        nbrs    = _nearest_neighbours(h.id, xy, HONEYCOMB_HELIX_SPACING)
        for bid in nbrs:
            x1, y1 = xy[bid]
            d = math.hypot(x1 - x0, y1 - y0)
            if abs(d - HONEYCOMB_HELIX_SPACING) > DIST_TOL:
                failures.append(
                    f"  {h.id} ↔ {bid}: dist={d:.5f} nm "
                    f"(expected {HONEYCOMB_HELIX_SPACING} nm)"
                )
    assert not failures, (
        "Nearest-neighbour distances not equal to HONEYCOMB_HELIX_SPACING:\n"
        + "\n".join(failures)
    )


# ── Square lattice tests ───────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def design_sq_3x4():
    return make_bundle_design(
        CELLS_SQ_3X4,
        length_bp=64,
        lattice_type=LatticeType.SQUARE,
    )


def test_square_interior_helices_have_4_neighbours(design_sq_3x4):
    """Interior square-lattice helices must have exactly 4 nearest neighbours."""
    results = _assert_neighbour_geometry(
        design_sq_3x4,
        SQUARE_HELIX_SPACING,
        expected_interior_count=4,
        expected_gap=90.0,
        label="SQ 3×4",
    )
    interior = [r for r in results if r.n_neighbours == 4]
    assert len(interior) >= 2, (
        f"Expected ≥2 interior helices in a 3×4 grid, found {len(interior)}"
    )


def test_square_angular_gaps_are_90_degrees(design_sq_3x4):
    """All interior square-lattice helices must have uniform 90° angular gaps."""
    xy      = _xy(design_sq_3x4)
    failures: list[str] = []
    for h in design_sq_3x4.helices:
        nbrs = _nearest_neighbours(h.id, xy, SQUARE_HELIX_SPACING)
        if len(nbrs) != 4:
            continue   # edge/corner helices
        angles = _angles_deg(h.id, nbrs, xy)
        gaps   = _circular_gaps(angles)
        for gap in gaps:
            if abs(gap - 90.0) > ANGLE_TOL:
                failures.append(
                    f"  {h.id}: gap {gap:.2f}° ≠ 90° "
                    f"(angles={[f'{a:.1f}' for a in angles]})"
                )
    assert not failures, (
        "Interior square helices with non-90° gaps:\n" + "\n".join(failures)
    )


def test_square_all_neighbours_are_antiparallel(design_sq_3x4):
    """Every nearest neighbour pair in the square lattice must be antiparallel."""
    xy      = _xy(design_sq_3x4)
    dir_map = {h.id: _scaffold_direction(design_sq_3x4, h.id) for h in design_sq_3x4.helices}
    failures: list[str] = []
    for h in design_sq_3x4.helices:
        nbrs = _nearest_neighbours(h.id, xy, SQUARE_HELIX_SPACING)
        for bid in nbrs:
            if dir_map[bid] == dir_map[h.id]:
                failures.append(
                    f"  {h.id} ({dir_map[h.id].name}) ↔ {bid} ({dir_map[bid].name})"
                )
    assert not failures, (
        "Parallel nearest-neighbour pairs found in square lattice:\n"
        + "\n".join(failures)
    )


def test_square_neighbour_distances_exact(design_sq_3x4):
    """Every nearest-neighbour pair in the square lattice is at SQUARE_HELIX_SPACING."""
    xy      = _xy(design_sq_3x4)
    failures: list[str] = []
    for h in design_sq_3x4.helices:
        x0, y0 = xy[h.id]
        nbrs    = _nearest_neighbours(h.id, xy, SQUARE_HELIX_SPACING)
        for bid in nbrs:
            x1, y1 = xy[bid]
            d = math.hypot(x1 - x0, y1 - y0)
            if abs(d - SQUARE_HELIX_SPACING) > DIST_TOL:
                failures.append(
                    f"  {h.id} ↔ {bid}: dist={d:.5f} nm "
                    f"(expected {SQUARE_HELIX_SPACING} nm)"
                )
    assert not failures, (
        "Nearest-neighbour distances not equal to SQUARE_HELIX_SPACING:\n"
        + "\n".join(failures)
    )


# ── Honeycomb lattice symmetry check ──────────────────────────────────────────


def test_honeycomb_lattice_is_not_square_grid():
    """Confirm honeycomb and square have distinguishable angular gap patterns.

    This test exists to document the geometry: a honeycomb lattice has
    non-uniform angular gaps (all 120° for degree-3 nodes) while a square
    lattice has uniform 90° gaps.  They are NOT the same even though both
    use HELIX_SPACING = 2.25 nm centre-to-centre.
    """
    hc_design = make_bundle_design(CELLS_18HB, length_bp=42)
    sq_design  = make_bundle_design(CELLS_SQ_3X4, length_bp=42, lattice_type=LatticeType.SQUARE)

    xy_hc = _xy(hc_design)
    xy_sq = _xy(sq_design)

    # Pick one interior honeycomb helix (any with 3 neighbours)
    hc_interior = next(
        (h.id for h in hc_design.helices
         if len(_nearest_neighbours(h.id, xy_hc, HONEYCOMB_HELIX_SPACING)) == 3),
        None,
    )
    assert hc_interior is not None, "No interior honeycomb helix found"
    hc_gaps = _circular_gaps(_angles_deg(
        hc_interior,
        _nearest_neighbours(hc_interior, xy_hc, HONEYCOMB_HELIX_SPACING),
        xy_hc,
    ))
    assert len(hc_gaps) == 3 and all(abs(g - 120.0) <= ANGLE_TOL for g in hc_gaps), (
        f"Honeycomb interior helix {hc_interior} does not have 3×120° gaps: {hc_gaps}"
    )

    # Pick one interior square helix (any with 4 neighbours)
    sq_interior = next(
        (h.id for h in sq_design.helices
         if len(_nearest_neighbours(h.id, xy_sq, SQUARE_HELIX_SPACING)) == 4),
        None,
    )
    assert sq_interior is not None, "No interior square helix found"
    sq_gaps = _circular_gaps(_angles_deg(
        sq_interior,
        _nearest_neighbours(sq_interior, xy_sq, SQUARE_HELIX_SPACING),
        xy_sq,
    ))
    assert len(sq_gaps) == 4 and all(abs(g - 90.0) <= ANGLE_TOL for g in sq_gaps), (
        f"Square interior helix {sq_interior} does not have 4×90° gaps: {sq_gaps}"
    )


# ── Placeholder tests for caDNAno-imported designs ────────────────────────────
# These tests will be activated once backend/core/cadnano.py is implemented.
# They import the module only at call time so the rest of the file runs cleanly.

try:
    import backend.core.cadnano as cadnano  # noqa: F401
    _CADNANO_AVAILABLE = True
except ImportError:
    _CADNANO_AVAILABLE = False
    cadnano = None  # type: ignore[assignment]


@pytest.fixture(scope="module")
def design_cadnano_18hb_seam():
    if not _CADNANO_AVAILABLE:
        pytest.skip("cadnano importer not yet implemented")
    import json
    import os
    path = os.path.join(
        os.path.dirname(__file__), "..", "Examples", "cadnano",
        "18hb_symm_p7249_21_even_spacing_sequential_coloring.json",
    )
    with open(path) as f:
        data = json.load(f)
    from backend.core.cadnano import import_cadnano
    return import_cadnano(data)


@pytest.mark.skipif(not _CADNANO_AVAILABLE, reason="cadnano importer not yet implemented")
def test_cadnano_18hb_honeycomb_neighbour_geometry(design_cadnano_18hb_seam):
    """Imported 18HB caDNAno design must have correct honeycomb neighbour geometry."""
    _assert_neighbour_geometry(
        design_cadnano_18hb_seam,
        HONEYCOMB_HELIX_SPACING,
        expected_interior_count=3,
        expected_gap=120.0,
        label="cadnano 18HB seam",
    )


@pytest.mark.skipif(not _CADNANO_AVAILABLE, reason="cadnano importer not yet implemented")
def test_cadnano_18hb_all_neighbours_antiparallel(design_cadnano_18hb_seam):
    """All nearest-neighbour pairs in the imported 18HB must be antiparallel."""
    if not _CADNANO_AVAILABLE:
        pytest.skip("cadnano importer not yet implemented")
    xy      = _xy(design_cadnano_18hb_seam)
    dir_map = {
        h.id: _scaffold_direction(design_cadnano_18hb_seam, h.id)
        for h in design_cadnano_18hb_seam.helices
    }
    failures: list[str] = []
    for h in design_cadnano_18hb_seam.helices:
        nbrs = _nearest_neighbours(h.id, xy, HONEYCOMB_HELIX_SPACING)
        for bid in nbrs:
            if dir_map[bid] == dir_map[h.id]:
                failures.append(
                    f"  {h.id} ({dir_map[h.id].name}) ↔ {bid} ({dir_map[bid].name})"
                )
    assert not failures, (
        "Parallel nearest-neighbour pairs in cadnano import:\n" + "\n".join(failures)
    )
