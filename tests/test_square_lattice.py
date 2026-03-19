"""
Square lattice integration tests.

Covers:
  SQ-1  Extrusion — make_bundle_design + make_bundle_continuation for SQUARE
  SQ-2  Geometry  — nucleotide_positions uses 30°/bp twist, correct XY spacing
  SQ-3  Prebreak  — produces 8-bp fragments (not 7)
  SQ-4  Crossover detection — valid crossovers found between adjacent square-lattice helices
  SQ-5  3D distance validation — backbone-to-backbone distance at crossover ≤ 0.75 nm
"""

from __future__ import annotations

import math

import pytest

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HELIX_RADIUS,
    SQUARE_COL_PITCH,
    SQUARE_CROSSOVER_PERIOD,
    SQUARE_ROW_PITCH,
    SQUARE_TWIST_PER_BP_DEG,
    SQUARE_TWIST_PER_BP_RAD,
)
from backend.core.crossover_positions import MAX_CROSSOVER_REACH_NM, valid_crossover_positions
from backend.core.geometry import nucleotide_positions
from backend.core.lattice import (
    make_bundle_continuation,
    make_bundle_design,
    make_prebreak,
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


# ── SQ-3  Prebreak (8-bp period) ──────────────────────────────────────────────

class TestSquarePrebreak:
    def test_prebreak_period_is_8(self):
        """Prebreak on a square design should create 8-bp staple fragments."""
        d = _sq_4hb(length_bp=32)
        d = make_prebreak(d)
        for s in d.strands:
            if s.strand_type == StrandType.STAPLE:
                # Each domain should be at most 8 bp long.
                for dom in s.domains:
                    span = abs(dom.end_bp - dom.start_bp) + 1
                    assert span <= SQUARE_CROSSOVER_PERIOD, (
                        f"Staple domain span={span} exceeds period {SQUARE_CROSSOVER_PERIOD}"
                    )

    def test_prebreak_produces_correct_fragment_count(self):
        """32 bp / 8 = 4 fragments per staple (one strand per helix after prebreak)."""
        d = _sq_4hb(length_bp=32)
        d = make_prebreak(d)
        staple_strands = [s for s in d.strands if s.strand_type == StrandType.STAPLE]
        # Prebreak creates nicks; each 32-bp staple → 4 × 8-bp fragments = 4 strands.
        # Each helix has one staple direction, so 4 helices × 4 fragments = 16 staple strands.
        assert len(staple_strands) == 16, (
            f"Expected 16 staple fragments (4 helices × 4), got {len(staple_strands)}"
        )

    def test_honeycomb_prebreak_period_unchanged(self):
        """Prebreak on honeycomb still uses 7-bp period (regression guard)."""
        # Use row=0 only — all col values are valid honeycomb cells in row 0.
        cells = [(0, 0), (0, 1), (0, 2), (0, 3)]
        d = make_bundle_design(cells, 28, lattice_type=LatticeType.HONEYCOMB)
        d = make_prebreak(d)
        for s in d.strands:
            if s.strand_type == StrandType.STAPLE:
                for dom in s.domains:
                    span = abs(dom.end_bp - dom.start_bp) + 1
                    assert span <= 7, (
                        f"Honeycomb staple domain span={span} exceeds 7"
                    )


# ── SQ-4 + SQ-5  Crossover detection & 3-D distance ──────────────────────────

class TestSquareCrossoverPositions:
    def _east_west_pair(self, length_bp: int = 24):
        """Return (FORWARD helix at col=0, REVERSE helix at col=1)."""
        d = make_bundle_design([(0, 0), (0, 1)], length_bp, lattice_type=LatticeType.SQUARE)
        hmap = {h.id: h for h in d.helices}
        return hmap["h_XY_0_0"], hmap["h_XY_0_1"]

    def _north_south_pair(self, length_bp: int = 24):
        """Return (FORWARD helix at row=0, REVERSE helix at row=1) in the same column."""
        d = make_bundle_design([(0, 0), (1, 0)], length_bp, lattice_type=LatticeType.SQUARE)
        hmap = {h.id: h for h in d.helices}
        return hmap["h_XY_0_0"], hmap["h_XY_1_0"]

    def test_ew_crossovers_exist(self):
        """East–West adjacent helices must have at least one valid crossover."""
        ha, hb = self._east_west_pair()
        candidates = valid_crossover_positions(ha, hb)
        assert len(candidates) > 0, "No E–W crossover candidates found"

    def test_ns_crossovers_exist(self):
        """North–South adjacent helices must have at least one valid crossover."""
        ha, hb = self._north_south_pair()
        candidates = valid_crossover_positions(ha, hb)
        assert len(candidates) > 0, "No N–S crossover candidates found"

    def test_ew_crossover_distance_within_reach(self):
        """All E–W crossover candidates must be within MAX_CROSSOVER_REACH_NM."""
        ha, hb = self._east_west_pair()
        candidates = valid_crossover_positions(ha, hb)
        for c in candidates:
            assert c.distance_nm <= MAX_CROSSOVER_REACH_NM, (
                f"E–W crossover at bp_a={c.bp_a}/bp_b={c.bp_b} "
                f"distance={c.distance_nm:.4f} nm exceeds {MAX_CROSSOVER_REACH_NM}"
            )

    def test_ns_crossover_distance_within_reach(self):
        """All N–S crossover candidates must be within MAX_CROSSOVER_REACH_NM."""
        ha, hb = self._north_south_pair()
        candidates = valid_crossover_positions(ha, hb)
        for c in candidates:
            assert c.distance_nm <= MAX_CROSSOVER_REACH_NM, (
                f"N–S crossover at bp_a={c.bp_a}/bp_b={c.bp_b} "
                f"distance={c.distance_nm:.4f} nm exceeds {MAX_CROSSOVER_REACH_NM}"
            )

    def test_ew_crossover_bp_positions_are_periodic(self):
        """E–W crossover bp positions should repeat with period ≤ 32 (one full square period)."""
        ha, hb = self._east_west_pair(length_bp=96)
        candidates = valid_crossover_positions(ha, hb)
        bps = sorted({c.bp_a for c in candidates})
        if len(bps) >= 2:
            gaps = [bps[i+1] - bps[i] for i in range(len(bps) - 1)]
            # Allow gap up to 32 bp (one full 32-bp square lattice period)
            for g in gaps:
                assert g <= 32, f"Unexpectedly large gap between crossover positions: {g} bp"

    def test_ew_crossover_3d_distance_matches_geometry(self):
        """Verify E–W crossover distances by recomputing from actual backbone positions."""
        ha, hb = self._east_west_pair()
        nucs_a = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(ha)}
        nucs_b = {(n.bp_index, n.direction): n.position for n in nucleotide_positions(hb)}
        import numpy as np
        for c in valid_crossover_positions(ha, hb):
            pos_a = nucs_a.get((c.bp_a, c.direction_a))
            pos_b = nucs_b.get((c.bp_b, c.direction_b))
            if pos_a is None or pos_b is None:
                continue
            recomputed = float(np.linalg.norm(pos_a - pos_b))
            assert abs(recomputed - c.distance_nm) < 1e-4, (
                f"Stored distance {c.distance_nm:.4f} ≠ recomputed {recomputed:.4f}"
            )

    def test_8hb_all_pairs_have_crossovers(self):
        """Every adjacent pair in an 8-helix square design should have crossovers."""
        d = _sq_2x4(length_bp=32)
        hmap = {h.id: h for h in d.helices}

        adjacent_pairs = []
        for row in range(2):
            for col in range(4):
                # E neighbor
                if col + 1 < 4:
                    adjacent_pairs.append((f"h_XY_{row}_{col}", f"h_XY_{row}_{col+1}"))
                # S neighbor
                if row + 1 < 2:
                    adjacent_pairs.append((f"h_XY_{row}_{col}", f"h_XY_{row+1}_{col}"))

        for id_a, id_b in adjacent_pairs:
            ha, hb = hmap[id_a], hmap[id_b]
            candidates = valid_crossover_positions(ha, hb)
            assert len(candidates) > 0, (
                f"No crossovers found between {id_a} and {id_b}"
            )
