"""
Square lattice integration tests.

Covers:
  SQ-1  Extrusion — make_bundle_design + make_bundle_continuation for SQUARE
  SQ-2  Geometry  — nucleotide_positions uses 30°/bp twist, correct XY spacing
"""

from __future__ import annotations

import math


from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HELIX_RADIUS,
    SQUARE_COL_PITCH,
    SQUARE_TWIST_PER_BP_DEG,
    SQUARE_TWIST_PER_BP_RAD,
)

from backend.core.geometry import nucleotide_positions
from backend.core.lattice import (
    make_bundle_continuation,
    make_bundle_design,
    square_cell_direction,
    square_position,
)
from backend.core.models import Design, Direction, LatticeType, StrandType


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sq_2x4(length_bp: int = 32) -> Design:
    """Return a 2-row × 4-col square lattice design (8 helices, all cells valid)."""
    cells = [(r, c) for r in range(2) for c in range(4)]
    return make_bundle_design(
        cells, length_bp, name="SQ-2x4", lattice_type=LatticeType.SQUARE
    )


def _sq_4hb(length_bp: int = 32) -> Design:
    """Minimal 4-helix square bundle — 2 rows × 2 cols."""
    cells = [(0, 0), (0, 1), (1, 0), (1, 1)]
    return make_bundle_design(
        cells, length_bp, name="SQ-4HB", lattice_type=LatticeType.SQUARE
    )


# ── SQ-1  Extrusion ────────────────────────────────────────────────────────────

class TestSquareExtrusion:
    def test_make_bundle_design_creates_square_design(self):
        d = _sq_2x4()
        assert d.lattice_type == LatticeType.SQUARE

    def test_all_cells_valid_no_holes(self):
        """Square lattice has no holes — 2×4 grid gives 8 helices."""
        d = _sq_2x4()
        assert len(d.helices) == 8

    def test_helix_xy_positions(self):
        """Helix XY positions use SQUARE_COL_PITCH grid with no stagger."""
        d = _sq_2x4()
        hmap = {h.id: h for h in d.helices}
        for row in range(2):
            for col in range(4):
                h = hmap[f"h_XY_{row}_{col}"]
                x, y = square_position(row, col)
                assert abs(h.axis_start.x - x) < 1e-9, f"x mismatch ({row},{col})"
                assert abs(h.axis_start.y - y) < 1e-9, f"y mismatch ({row},{col})"

    def test_helix_spacing_uniform(self):
        """Adjacent helices are exactly SQUARE_COL_PITCH apart in X."""
        d = _sq_2x4()
        hmap = {h.id: h for h in d.helices}
        h00 = hmap["h_XY_0_0"]
        h01 = hmap["h_XY_0_1"]
        dx = abs(h01.axis_start.x - h00.axis_start.x)
        assert abs(dx - SQUARE_COL_PITCH) < 1e-9

    def test_scaffold_directions_antiparallel(self):
        """Adjacent cells must have antiparallel scaffold directions."""
        for row in range(2):
            for col in range(3):
                d0 = square_cell_direction(row, col)
                d1 = square_cell_direction(row, col + 1)
                assert d0 != d1, f"cells ({row},{col}) and ({row},{col+1}) should be antiparallel"

    def test_helix_stores_square_twist(self):
        """Every helix created for a square design stores the 30°/bp twist."""
        d = _sq_4hb()
        for h in d.helices:
            assert abs(h.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9, (
                f"Helix {h.id} has wrong twist {h.twist_per_bp_rad}"
            )

    def test_continuation_preserves_square_twist(self):
        """Continuing a square design creates helices with correct twist."""
        d = _sq_4hb(length_bp=32)
        cells = [(0, 0), (0, 1), (1, 0), (1, 1)]
        offset = d.helices[0].axis_end.z
        d2 = make_bundle_continuation(d, cells, 32, plane="XY", offset_nm=offset)
        for h in d2.helices:
            assert abs(h.twist_per_bp_rad - SQUARE_TWIST_PER_BP_RAD) < 1e-9, (
                f"Continuation helix {h.id} has wrong twist"
            )

    def test_strand_count_both_strands(self):
        """Each helix gets one scaffold and one staple."""
        d = _sq_4hb()
        scaf = [s for s in d.strands if s.strand_type == StrandType.SCAFFOLD]
        stpl = [s for s in d.strands if s.strand_type == StrandType.STAPLE]
        assert len(scaf) == 4
        assert len(stpl) == 4

    def test_make_bundle_segment_rejects_honeycomb_cells_on_square(self):
        """make_bundle_segment should NOT reject cells for square lattice
        (all cells are valid, so a 'honeycomb hole' cell like (0,2) is fine)."""
        from backend.core.lattice import make_bundle_segment
        d = _sq_4hb()
        # (0, 2) would be a hole in honeycomb — fine in square
        d2 = make_bundle_segment(d, [(0, 2)], 32, plane="XY")
        assert any(h.id.startswith("h_XY_0_2") for h in d2.helices)


# ── SQ-2  Geometry (nucleotide positions use 30°/bp twist) ────────────────────

class TestSquareGeometry:
    def test_twist_matches_constant(self):
        """nucleotide_positions for a square helix should advance SQUARE_TWIST_PER_BP_DEG per bp."""
        d = _sq_4hb()
        h = d.helices[0]
        nucs = {(n.bp_index, n.direction): n for n in nucleotide_positions(h)}

        ax, ay = h.axis_start.x, h.axis_start.y
        def angle_at(bp: int) -> float:
            pos = nucs[(bp, Direction.FORWARD)].position
            return math.atan2(pos[1] - ay, pos[0] - ax)

        delta_deg = math.degrees((angle_at(1) - angle_at(0)) % (2 * math.pi))
        assert abs(delta_deg - SQUARE_TWIST_PER_BP_DEG) < 1e-4, (
            f"Expected {SQUARE_TWIST_PER_BP_DEG}°/bp twist, got {delta_deg:.4f}°"
        )

    def test_helix_radius_correct(self):
        """Backbone beads should sit at HELIX_RADIUS from the axis."""
        d = _sq_4hb()
        h = d.helices[0]
        ax, ay = h.axis_start.x, h.axis_start.y
        for n in nucleotide_positions(h):
            r = math.hypot(n.position[0] - ax, n.position[1] - ay)
            assert abs(r - HELIX_RADIUS) < 1e-6, (
                f"bp={n.bp_index} radius={r:.4f} expected {HELIX_RADIUS}"
            )

    def test_rise_per_bp_correct(self):
        """Consecutive bp should be BDNA_RISE_PER_BP apart along Z."""
        d = _sq_4hb()
        h = d.helices[0]
        nucs = {(n.bp_index, n.direction): n for n in nucleotide_positions(h)}
        for bp in range(h.length_bp - 1):
            z0 = nucs[(bp,     Direction.FORWARD)].position[2]
            z1 = nucs[(bp + 1, Direction.FORWARD)].position[2]
            assert abs((z1 - z0) - BDNA_RISE_PER_BP) < 1e-6, (
                f"Rise at bp={bp}: {z1-z0:.4f} nm, expected {BDNA_RISE_PER_BP}"
            )

    def test_square_vs_honeycomb_different_positions(self):
        """Square and honeycomb designs with same cells produce different XY positions."""
        sq_cells = [(0, 0), (0, 1)]
        d_sq = make_bundle_design(sq_cells, 12, lattice_type=LatticeType.SQUARE)
        d_hc = make_bundle_design(sq_cells, 12, lattice_type=LatticeType.HONEYCOMB)
        # (0,0) is the same in both, but (0,1) differs
        h_sq = next(h for h in d_sq.helices if "0_1" in h.id)
        h_hc = next(h for h in d_hc.helices if "0_1" in h.id)
        # Honeycomb col pitch ≈ 1.949 nm; square col pitch = 2.25 nm (HONEYCOMB_HELIX_SPACING)
        assert abs(h_sq.axis_start.x - h_hc.axis_start.x) > 0.1, (
            "Square and honeycomb x positions should differ for col=1"
        )



