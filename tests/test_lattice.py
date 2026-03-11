"""
Tests for backend/core/lattice.py — honeycomb lattice geometry and bundle generation.
"""

import math

import pytest

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_HELIX_SPACING,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
)
from backend.core.lattice import (
    honeycomb_cell_value,
    honeycomb_position,
    is_valid_honeycomb_cell,
    make_bundle_continuation,
    make_bundle_design,
    make_bundle_segment,
    scaffold_direction_for_cell,
)
from backend.core.models import Direction, LatticeType


# ── Cell value and validity rules ─────────────────────────────────────────────


def test_cell_value_formula():
    """cell_value = (row + col%2) % 3."""
    assert honeycomb_cell_value(0, 0) == 0   # FORWARD
    assert honeycomb_cell_value(0, 1) == 1   # REVERSE
    assert honeycomb_cell_value(1, 0) == 1   # REVERSE
    assert honeycomb_cell_value(2, 1) == 0   # FORWARD
    assert honeycomb_cell_value(2, 0) == 2   # hole
    assert honeycomb_cell_value(1, 1) == 2   # hole
    assert honeycomb_cell_value(1, 3) == 2   # hole
    assert honeycomb_cell_value(2, 2) == 2   # hole


def test_valid_cell_rejects_holes():
    """Hole cells (value==2) are not valid helix positions."""
    assert is_valid_honeycomb_cell(0, 0) is True
    assert is_valid_honeycomb_cell(0, 1) is True
    assert is_valid_honeycomb_cell(2, 0) is False
    assert is_valid_honeycomb_cell(1, 1) is False
    assert is_valid_honeycomb_cell(2, 2) is False


def test_scaffold_direction_value_zero_is_forward():
    """Cells with cell_value==0 have FORWARD scaffold."""
    assert scaffold_direction_for_cell(0, 0) == Direction.FORWARD   # value 0
    assert scaffold_direction_for_cell(2, 1) == Direction.FORWARD   # value 0
    assert scaffold_direction_for_cell(3, 0) == Direction.FORWARD   # value 0


def test_scaffold_direction_value_one_is_reverse():
    """Cells with cell_value==1 have REVERSE scaffold."""
    assert scaffold_direction_for_cell(0, 1) == Direction.REVERSE   # value 1
    assert scaffold_direction_for_cell(1, 0) == Direction.REVERSE   # value 1
    assert scaffold_direction_for_cell(1, 2) == Direction.REVERSE   # value 1


def test_adjacent_valid_cells_are_antiparallel():
    """Every pair of valid cells at HELIX_SPACING distance have opposite directions."""
    from backend.core.constants import HONEYCOMB_HELIX_SPACING
    rows, cols = 8, 12
    violations = []
    for c in range(cols):
        for r in range(rows):
            if not is_valid_honeycomb_cell(r, c):
                continue
            x0, y0 = honeycomb_position(r, c)
            for dr in range(-3, 4):
                for dc in range(-2, 3):
                    r2, c2 = r + dr, c + dc
                    if r2 < 0 or c2 < 0 or r2 >= rows or c2 >= cols:
                        continue
                    if not is_valid_honeycomb_cell(r2, c2):
                        continue
                    x2, y2 = honeycomb_position(r2, c2)
                    if abs(math.hypot(x2 - x0, y2 - y0) - HONEYCOMB_HELIX_SPACING) < 0.02:
                        if scaffold_direction_for_cell(r, c) == scaffold_direction_for_cell(r2, c2):
                            violations.append(((r, c), (r2, c2)))
    assert violations == []


# ── Honeycomb positions ───────────────────────────────────────────────────────


def test_origin_at_0_0():
    """Cell (0,0) with even column → x=0, y=LATTICE_RADIUS."""
    x, y = honeycomb_position(0, 0)
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(HONEYCOMB_LATTICE_RADIUS)


def test_col_pitch():
    """Adjacent columns (same row) separated by HONEYCOMB_COL_PITCH in x."""
    x0, _ = honeycomb_position(0, 0)
    x1, _ = honeycomb_position(0, 1)
    assert abs(x1 - x0) == pytest.approx(HONEYCOMB_COL_PITCH)


def test_col_pitch_constant_value():
    """HONEYCOMB_COL_PITCH = LATTICE_RADIUS * sqrt(3)."""
    expected = HONEYCOMB_LATTICE_RADIUS * math.sqrt(3)
    assert HONEYCOMB_COL_PITCH == pytest.approx(expected)


def test_helix_spacing_equals_2_x_lattice_radius():
    """Centre-to-centre for adjacent columns = 2 × LATTICE_RADIUS = 2.25 nm."""
    assert HONEYCOMB_HELIX_SPACING == pytest.approx(2 * HONEYCOMB_LATTICE_RADIUS)


def test_adjacent_col_distance():
    """3D distance between (0,0) and (0,1) equals HONEYCOMB_HELIX_SPACING."""
    x0, y0 = honeycomb_position(0, 0)
    x1, y1 = honeycomb_position(0, 1)
    dist = math.hypot(x1 - x0, y1 - y0)
    assert dist == pytest.approx(HONEYCOMB_HELIX_SPACING, rel=1e-4)


def test_row_pitch_constant_value():
    """HONEYCOMB_ROW_PITCH = 2 × LATTICE_RADIUS = HELIX_SPACING (triangular close-packing)."""
    assert HONEYCOMB_ROW_PITCH == pytest.approx(2.0 * HONEYCOMB_LATTICE_RADIUS)


def test_adjacent_row_distance():
    """Same-column, adjacent-row helices are also HONEYCOMB_HELIX_SPACING apart."""
    x0, y0 = honeycomb_position(0, 0)
    x1, y1 = honeycomb_position(1, 0)
    dist = math.hypot(x1 - x0, y1 - y0)
    assert dist == pytest.approx(HONEYCOMB_HELIX_SPACING, rel=1e-4)


def test_interior_helix_has_six_neighbours():
    """An interior helix (2, 3) should have 6 neighbours at HELIX_SPACING."""
    row, col = 2, 3
    x0, y0 = honeycomb_position(row, col)
    nn = 0
    for dr in range(-2, 3):
        for dc in range(-3, 4):
            if dr == 0 and dc == 0:
                continue
            xn, yn = honeycomb_position(row + dr, col + dc)
            if abs(math.hypot(xn - x0, yn - y0) - HONEYCOMB_HELIX_SPACING) < 0.02:
                nn += 1
    assert nn == 6


# ── make_bundle_design ────────────────────────────────────────────────────────


def test_single_cell_bundle():
    design = make_bundle_design([(0, 0)], length_bp=42)
    assert len(design.helices) == 1
    assert len(design.strands) == 2  # 1 scaffold + 1 staple placeholder


def test_bundle_helix_ids():
    """Default plane is XY, so IDs are h_XY_{row}_{col}."""
    design = make_bundle_design([(0, 0), (0, 1), (1, 0)], length_bp=21)
    ids = {h.id for h in design.helices}
    assert ids == {"h_XY_0_0", "h_XY_0_1", "h_XY_1_0"}


def test_bundle_strand_ids():
    """Scaffold IDs are scaf_{plane}_{row}_{col}; staple IDs are stpl_{plane}_{row}_{col}."""
    design = make_bundle_design([(0, 0)], length_bp=21)
    strand_ids = {s.id for s in design.strands}
    assert "scaf_XY_0_0" in strand_ids
    assert "stpl_XY_0_0" in strand_ids


def test_bundle_helix_length():
    length_bp = 42
    design = make_bundle_design([(0, 0)], length_bp=length_bp)
    h = design.helices[0]
    expected_z = length_bp * BDNA_RISE_PER_BP
    assert h.axis_end.z == pytest.approx(expected_z)
    assert h.axis_start.z == pytest.approx(0.0)


def test_bundle_lattice_type():
    design = make_bundle_design([(0, 0)], length_bp=21)
    assert design.lattice_type == LatticeType.HONEYCOMB


def test_bundle_phase_offset_forward_is_315():
    """FORWARD helices (cell_value==0) get phase_offset=315° for crossover alignment."""
    design = make_bundle_design([(0, 0)], length_bp=21)  # (0,0) → value 0 → FORWARD
    h = design.helices[0]
    assert h.phase_offset == pytest.approx(math.radians(315.0))


def test_bundle_phase_offset_reverse_is_zero():
    """REVERSE helices (cell_value==1) get phase_offset=0."""
    design = make_bundle_design([(1, 0)], length_bp=21)  # (1,0) → value 1 → REVERSE
    h = design.helices[0]
    assert h.phase_offset == pytest.approx(0.0)


def test_bundle_one_scaffold_one_staple_per_helix():
    """Each helix contributes exactly one scaffold and one staple strand."""
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=21)
    scaffolds = [s for s in design.strands if s.is_scaffold]
    staples   = [s for s in design.strands if not s.is_scaffold]
    assert len(scaffolds) == 2
    assert len(staples)   == 2


def test_bundle_staple_direction_opposite_scaffold():
    """Placeholder staple runs in the direction opposite to the scaffold."""
    for cell in [(0, 0), (0, 1), (1, 0)]:
        design = make_bundle_design([cell], length_bp=21)
        scaf  = next(s for s in design.strands if s.is_scaffold)
        stapl = next(s for s in design.strands if not s.is_scaffold)
        assert scaf.domains[0].direction != stapl.domains[0].direction


def test_bundle_forward_strand_at_value_zero():
    """Cell (0,0) has cell_value=0 → FORWARD scaffold."""
    design = make_bundle_design([(0, 0)], length_bp=21)
    strand = next(s for s in design.strands if s.is_scaffold)
    domain = strand.domains[0]
    assert domain.direction == Direction.FORWARD
    assert domain.start_bp == 0
    assert domain.end_bp == 20


def test_bundle_reverse_strand_at_value_one():
    """Cell (0,1) has cell_value=1 → REVERSE scaffold."""
    design = make_bundle_design([(0, 1)], length_bp=21)
    strand = next(s for s in design.strands if s.is_scaffold)
    domain = strand.domains[0]
    assert domain.direction == Direction.REVERSE
    assert domain.start_bp == 20
    assert domain.end_bp == 0


def test_bundle_corrected_direction_r2c1():
    """Cell (2,1) has cell_value=0 → FORWARD (was REVERSE under old parity rule)."""
    design = make_bundle_design([(2, 1)], length_bp=21)
    domain = next(s for s in design.strands if s.is_scaffold).domains[0]
    assert domain.direction == Direction.FORWARD


def test_bundle_rejects_hole_cell():
    """Cells with cell_value==2 (holes) raise ValueError."""
    with pytest.raises(ValueError, match="not valid honeycomb"):
        make_bundle_design([(2, 0)], length_bp=21)

    with pytest.raises(ValueError, match="not valid honeycomb"):
        make_bundle_design([(1, 1)], length_bp=21)


def test_empty_cells_raises():
    with pytest.raises(ValueError, match="cells list"):
        make_bundle_design([], length_bp=21)


def test_invalid_length_raises():
    with pytest.raises(ValueError, match="length_bp"):
        make_bundle_design([(0, 0)], length_bp=0)


# ── Plane parameter tests ─────────────────────────────────────────────────────


def test_default_plane_is_xy():
    """Default plane is XY — helices run along Z (backward compat)."""
    design = make_bundle_design([(0, 0)], length_bp=42)
    h = design.helices[0]
    expected_z = 42 * BDNA_RISE_PER_BP
    # axis_start.z == 0, axis_end.z == length_nm
    assert h.axis_start.z == pytest.approx(0.0)
    assert h.axis_end.z   == pytest.approx(expected_z)
    # x and y are non-zero (from honeycomb_position), not the helix direction
    assert h.axis_start.x == h.axis_end.x
    assert h.axis_start.y == h.axis_end.y


def test_plane_xy_explicit():
    """Explicit plane='XY' matches default."""
    d1 = make_bundle_design([(0, 1)], length_bp=21)
    d2 = make_bundle_design([(0, 1)], length_bp=21, plane="XY")
    h1, h2 = d1.helices[0], d2.helices[0]
    assert h1.axis_start.x == pytest.approx(h2.axis_start.x)
    assert h1.axis_start.y == pytest.approx(h2.axis_start.y)
    assert h1.axis_start.z == pytest.approx(h2.axis_start.z)
    assert h1.axis_end.z   == pytest.approx(h2.axis_end.z)


def test_plane_xz_helix_along_y():
    """XZ plane: helices run along Y. axis_start.y==0, axis_end.y==length_nm."""
    length_bp = 42
    design = make_bundle_design([(0, 0)], length_bp=length_bp, plane="XZ")
    h = design.helices[0]
    expected_len = length_bp * BDNA_RISE_PER_BP
    assert h.axis_start.y == pytest.approx(0.0)
    assert h.axis_end.y   == pytest.approx(expected_len)
    # x and z are fixed (lattice coords), not the helix direction
    assert h.axis_start.x == pytest.approx(h.axis_end.x)
    assert h.axis_start.z == pytest.approx(h.axis_end.z)


def test_plane_yz_helix_along_x():
    """YZ plane: helices run along X. axis_start.x==0, axis_end.x==length_nm."""
    length_bp = 42
    design = make_bundle_design([(0, 0)], length_bp=length_bp, plane="YZ")
    h = design.helices[0]
    expected_len = length_bp * BDNA_RISE_PER_BP
    assert h.axis_start.x == pytest.approx(0.0)
    assert h.axis_end.x   == pytest.approx(expected_len)
    # y and z are fixed (lattice coords), not the helix direction
    assert h.axis_start.y == pytest.approx(h.axis_end.y)
    assert h.axis_start.z == pytest.approx(h.axis_end.z)


def test_plane_ids_include_plane_name():
    """Helix IDs include the plane name to avoid collisions across planes."""
    xy_design = make_bundle_design([(0, 0)], length_bp=21, plane="XY")
    xz_design = make_bundle_design([(0, 0)], length_bp=21, plane="XZ")
    yz_design = make_bundle_design([(0, 0)], length_bp=21, plane="YZ")
    assert xy_design.helices[0].id == "h_XY_0_0"
    assert xz_design.helices[0].id == "h_XZ_0_0"
    assert yz_design.helices[0].id == "h_YZ_0_0"


def test_invalid_plane_raises():
    """An unknown plane string raises ValueError."""
    with pytest.raises(ValueError, match="plane"):
        make_bundle_design([(0, 0)], length_bp=21, plane="AB")


# ── offset_nm and signed length_bp ────────────────────────────────────────────


def test_bundle_with_offset_nm():
    """offset_nm shifts axis_start (and axis_end) along the plane normal."""
    offset = 5.0
    design = make_bundle_design([(0, 0)], length_bp=42, plane="XY", offset_nm=offset)
    h = design.helices[0]
    expected_end = offset + 42 * BDNA_RISE_PER_BP
    assert h.axis_start.z == pytest.approx(offset)
    assert h.axis_end.z   == pytest.approx(expected_end)


def test_bundle_with_offset_xz_plane():
    """offset_nm for XZ plane shifts along Y axis."""
    offset = 3.5
    design = make_bundle_design([(0, 0)], length_bp=21, plane="XZ", offset_nm=offset)
    h = design.helices[0]
    assert h.axis_start.y == pytest.approx(offset)
    assert h.axis_end.y   == pytest.approx(offset + 21 * BDNA_RISE_PER_BP)


def test_bundle_negative_length_xy():
    """Negative length_bp: axis_end.z < axis_start.z; helix.length_bp is the magnitude."""
    design = make_bundle_design([(0, 0)], length_bp=-42, plane="XY")
    h = design.helices[0]
    assert h.length_bp == 42
    assert h.axis_start.z == pytest.approx(0.0)
    assert h.axis_end.z   == pytest.approx(-42 * BDNA_RISE_PER_BP)


def test_bundle_negative_length_offset():
    """Negative length with offset: axis runs from offset backwards."""
    offset = 10.0
    design = make_bundle_design([(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    h = design.helices[0]
    assert h.length_bp == 21
    assert h.axis_start.z == pytest.approx(offset)
    assert h.axis_end.z   == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)


def test_bundle_negative_length_zero_raises():
    """length_bp=0 raises ValueError (magnitude must be >= 1)."""
    with pytest.raises(ValueError, match="length_bp"):
        make_bundle_design([(0, 0)], length_bp=0)


def test_bundle_strand_bp_uses_actual_length():
    """start_bp / end_bp use abs(length_bp), not the raw signed value."""
    design = make_bundle_design([(0, 0)], length_bp=-42, plane="XY")
    scaf = next(s for s in design.strands if s.is_scaffold)
    dom  = scaf.domains[0]
    # Cell (0,0) is FORWARD: start_bp=0, end_bp=41
    assert dom.start_bp == 0
    assert dom.end_bp   == 41


# ── make_bundle_segment ────────────────────────────────────────────────────────


def test_bundle_segment_appends_helices():
    """make_bundle_segment adds new helices to an existing design."""
    base = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0)], length_bp=42, plane="XY", offset_nm=offset)
    assert len(result.helices) == 2
    assert len(result.strands) == 4   # 2 scaffold + 2 staple


def test_bundle_segment_unique_ids():
    """Segment helix/strand IDs do not collide with the base design."""
    base = make_bundle_design([(0, 0)], length_bp=42)
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0)], length_bp=42, offset_nm=offset)
    ids = [h.id for h in result.helices]
    assert len(set(ids)) == len(ids), "Helix IDs must be unique"
    strand_ids = [s.id for s in result.strands]
    assert len(set(strand_ids)) == len(strand_ids), "Strand IDs must be unique"


def test_bundle_segment_correct_offset():
    """Segment helix axis_start matches the supplied offset_nm."""
    base   = make_bundle_design([(0, 0)], length_bp=42)
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0)], length_bp=21, offset_nm=offset)
    new_helix = result.helices[-1]
    assert new_helix.axis_start.z == pytest.approx(offset)
    assert new_helix.axis_end.z   == pytest.approx(offset + 21 * BDNA_RISE_PER_BP)


def test_bundle_segment_multiple_cells():
    """Segment with multiple cells generates one helix per cell."""
    base   = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0), (0, 1)], length_bp=21, offset_nm=offset)
    assert len(result.helices) == 4   # 2 base + 2 new


def test_bundle_segment_preserves_existing_helices():
    """Existing helices and strands are untouched."""
    base   = make_bundle_design([(0, 0)], length_bp=42)
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0)], length_bp=21, offset_nm=offset)
    assert result.helices[0].id == base.helices[0].id
    assert result.helices[0].axis_start.z == pytest.approx(0.0)


def test_bundle_segment_rejects_invalid_cell():
    """Hole cells in the segment raise ValueError."""
    base = make_bundle_design([(0, 0)], length_bp=42)
    with pytest.raises(ValueError, match="not valid honeycomb"):
        make_bundle_segment(base, [(2, 0)], length_bp=21)


# ── make_bundle_continuation ───────────────────────────────────────────────────


def test_continuation_fresh_cell_creates_new_strands():
    """A cell with no helix ending at offset creates new scaffold + staple (same as segment)."""
    # Blank design — no existing helices for cell (0,0)
    base   = make_bundle_design([(0, 1)], length_bp=42)   # different cell
    offset = 0.0
    result = make_bundle_continuation(base, [(0, 0)], length_bp=21, offset_nm=offset)
    # New helix added
    assert len(result.helices) == 2
    # New strands added (scaffold + staple for fresh cell)
    assert len(result.strands) == 4


def test_continuation_extends_existing_strands():
    """A cell whose helix ends at offset appends a domain to existing strands."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP   # axis_end.z of base helix
    result = make_bundle_continuation(base, [(0, 0)], length_bp=21, plane="XY", offset_nm=offset)
    # One new helix
    assert len(result.helices) == 2
    # Strand count unchanged — domains were appended to existing strands
    assert len(result.strands) == 2
    # Each existing strand now has 2 domains
    for strand in result.strands:
        assert len(strand.domains) == 2


def test_continuation_new_helix_placed_at_offset():
    """The continuation helix starts at offset_nm and extends by length_bp."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_continuation(base, [(0, 0)], length_bp=21, plane="XY", offset_nm=offset)
    new_helix = result.helices[-1]
    assert new_helix.axis_start.z == pytest.approx(offset)
    assert new_helix.axis_end.z   == pytest.approx(offset + 21 * BDNA_RISE_PER_BP)


def test_continuation_domain_direction_preserved():
    """The appended domain has the same direction as the original domain."""
    from backend.core.models import Direction
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")  # (0,0) → FORWARD scaffold
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_continuation(base, [(0, 0)], length_bp=21, plane="XY", offset_nm=offset)
    # scaffold strand at (0,0) is FORWARD; its new domain should also be FORWARD
    scaf = next(s for s in result.strands if s.is_scaffold)
    assert scaf.domains[1].direction == Direction.FORWARD
    assert scaf.domains[1].start_bp  == 0
    assert scaf.domains[1].end_bp    == 20


def test_continuation_mixed_fresh_and_continuation():
    """A mix of continuation + fresh cells is handled correctly in one call."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP
    # (0,0) has a helix ending at offset → continuation; (0,1) is fresh
    result = make_bundle_continuation(base, [(0, 0), (0, 1)], length_bp=21, plane="XY", offset_nm=offset)
    # 3 helices: original + continuation + fresh
    assert len(result.helices) == 3
    # 2 original strands (extended) + 2 new strands for fresh cell (0,1)
    assert len(result.strands) == 4
    # Original strands still have 2 domains each
    orig_strand_ids = {s.id for s in base.strands}
    for s in result.strands:
        if s.id in orig_strand_ids:
            assert len(s.domains) == 2


def test_continuation_rejects_invalid_cell():
    """Hole cells raise ValueError."""
    base = make_bundle_design([(0, 0)], length_bp=42)
    with pytest.raises(ValueError, match="not valid honeycomb"):
        make_bundle_continuation(base, [(2, 0)], length_bp=21)


# ── make_staple_crossover tests (DTP-4) ───────────────────────────────────────

from backend.core.crossover_positions import valid_crossover_positions
from backend.core.lattice import make_staple_crossover


def _two_helix_design(length_bp: int = 42):
    """Return a 2-helix XY bundle at cells (0,0) and (0,1).

    (0,0): FORWARD scaffold / REVERSE staple
    (0,1): REVERSE scaffold / FORWARD staple
    """
    return make_bundle_design([(0, 0), (0, 1)], length_bp=length_bp)


def _first_staple_candidate(design):
    """Return the first valid crossover candidate that involves only staple strands."""
    from backend.core.models import Direction
    from backend.core.geometry import nucleotide_positions

    ha, hb = design.helices[0], design.helices[1]
    candidates = valid_crossover_positions(ha, hb)

    # Build a nucleotide-info lookup to find which strand is at each position
    nuc_info: dict = {}
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                nuc_info[(domain.helix_id, bp, domain.direction)] = strand

    for c in candidates:
        s_a = nuc_info.get((ha.id, c.bp_a, c.direction_a))
        s_b = nuc_info.get((hb.id, c.bp_b, c.direction_b))
        if s_a and s_b and not s_a.is_scaffold and not s_b.is_scaffold:
            return ha.id, c.bp_a, c.direction_a, hb.id, c.bp_b, c.direction_b

    raise RuntimeError("No staple-only crossover candidate found in 2-helix design")


def test_staple_crossover_returns_design():
    """make_staple_crossover returns a Design."""
    from backend.core.models import Design
    design = _two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_staple_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    assert isinstance(result, Design)


def test_staple_crossover_preserves_helix_count():
    """Crossover does not add or remove helices."""
    design = _two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_staple_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    assert len(result.helices) == len(design.helices)


def test_staple_crossover_nucleotide_count_preserved():
    """Total nucleotide count across all strands must not change."""
    def _count_nucs(d):
        total = 0
        for s in d.strands:
            for dom in s.domains:
                total += abs(dom.end_bp - dom.start_bp) + 1
        return total

    design = _two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_staple_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    assert _count_nucs(result) == _count_nucs(design)


def test_staple_crossover_scaffold_unchanged():
    """Scaffold strands must not be touched by a staple crossover."""
    design = _two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_staple_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)

    orig_scaffolds  = {s.id: s for s in design.strands if s.is_scaffold}
    result_scaffolds = {s.id: s for s in result.strands if s.is_scaffold}
    assert orig_scaffolds.keys() == result_scaffolds.keys()
    for sid, orig in orig_scaffolds.items():
        new = result_scaffolds[sid]
        assert orig.domains == new.domains


def test_staple_crossover_domain_split_forward():
    """For a FORWARD staple at (0,0): a_left ends at bp_a, b_right starts at bp_b."""
    from backend.core.models import Direction
    design = _two_helix_design()
    ha, hb = design.helices[0], design.helices[1]
    candidates = valid_crossover_positions(ha, hb)

    # Find a candidate where direction_a is FORWARD
    cand = next(
        (c for c in candidates
         if c.direction_a == Direction.FORWARD
         and not any(s.is_scaffold for s in design.strands
                     if any(d.helix_id == ha.id and d.direction == Direction.FORWARD for d in s.domains))),
        None,
    )
    if cand is None:
        pytest.skip("No FORWARD staple candidate on helix_a")

    # Identify if the forward strand at ha is scaffold (it is in (0,0))
    # So actually (0,0) FORWARD is scaffold → skip, use hb FORWARD
    # (0,1) FORWARD is staple; find candidates where direction_b == FORWARD
    cand = next(
        (c for c in candidates if c.direction_b == Direction.FORWARD),
        None,
    )
    if cand is None:
        pytest.skip("No FORWARD direction_b candidate")

    result = make_staple_crossover(design, ha.id, cand.bp_a, cand.direction_a,
                                   hb.id, cand.bp_b, cand.direction_b)

    # Find the strand whose first two domains span the split
    for s in result.strands:
        if s.is_scaffold:
            continue
        for i, dom in enumerate(s.domains):
            if dom.helix_id == ha.id and dom.end_bp == cand.bp_a:
                # a_left found — next domain should be b_right starting at bp_b
                if i + 1 < len(s.domains):
                    assert s.domains[i + 1].helix_id == hb.id
                    assert s.domains[i + 1].start_bp == cand.bp_b


def test_staple_crossover_rejects_scaffold():
    """Passing a bp covered by a scaffold strand raises ValueError."""
    from backend.core.models import Direction
    design = _two_helix_design()
    ha = design.helices[0]
    # (0,0) scaffold is FORWARD; bp 10 direction FORWARD is scaffold
    hb = design.helices[1]
    # Get any valid candidate on the non-scaffold direction to have a valid second position
    candidates = valid_crossover_positions(ha, hb)
    cand = candidates[0]
    # Force direction_a = FORWARD (scaffold on ha)
    with pytest.raises(ValueError, match="scaffold"):
        make_staple_crossover(design, ha.id, 10, Direction.FORWARD,
                              hb.id, cand.bp_b, cand.direction_b)


def test_staple_crossover_rejects_same_strand():
    """Crossover positions on the same strand raise ValueError."""
    from backend.core.models import Direction
    design = _two_helix_design()
    ha = design.helices[0]
    # REVERSE staple at (0,0) covers all bp on ha in REVERSE direction
    # Trying to cross it with itself
    with pytest.raises(ValueError, match="same strand"):
        make_staple_crossover(design, ha.id, 10, Direction.REVERSE,
                              ha.id, 20, Direction.REVERSE)


def test_staple_crossover_rejects_missing_strand():
    """Passing a bp with no covering strand raises ValueError."""
    from backend.core.models import Direction
    design = _two_helix_design()
    ha = design.helices[0]
    hb = design.helices[1]
    # bp 9999 is well beyond the helix length
    with pytest.raises(ValueError):
        make_staple_crossover(design, ha.id, 9999, Direction.FORWARD,
                              hb.id, 0, Direction.FORWARD)
