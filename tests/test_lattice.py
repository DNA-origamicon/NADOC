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


def test_bundle_phase_offset_forward_is_76():
    """FORWARD helices get phase_offset=76.3° (42° + 34.3° = one twist step shift so bp=0 has correct orientation)."""
    design = make_bundle_design([(0, 0)], length_bp=21)  # (0,0) → value 0 → FORWARD
    h = design.helices[0]
    assert h.phase_offset == pytest.approx(math.radians(76.3))


def test_bundle_phase_offset_reverse_is_16():
    """REVERSE helices get phase_offset=16.3° (342° + 34.3° = one twist step shift so bp=0 has correct orientation)."""
    design = make_bundle_design([(1, 0)], length_bp=21)  # (1,0) → value 1 → REVERSE
    h = design.helices[0]
    assert h.phase_offset == pytest.approx(math.radians(16.3))


def test_bundle_one_scaffold_one_staple_per_helix():
    """Each helix contributes exactly one scaffold and one staple strand."""
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=21)
    scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
    staples   = [s for s in design.strands if s.strand_type == StrandType.STAPLE]
    assert len(scaffolds) == 2
    assert len(staples)   == 2


def test_bundle_staple_direction_opposite_scaffold():
    """Placeholder staple runs in the direction opposite to the scaffold."""
    for cell in [(0, 0), (0, 1), (1, 0)]:
        design = make_bundle_design([cell], length_bp=21)
        scaf  = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
        stapl = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
        assert scaf.domains[0].direction != stapl.domains[0].direction


def test_bundle_forward_strand_at_value_zero():
    """Cell (0,0) has cell_value=0 → FORWARD scaffold."""
    design = make_bundle_design([(0, 0)], length_bp=21)
    strand = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    domain = strand.domains[0]
    assert domain.direction == Direction.FORWARD
    assert domain.start_bp == 0
    assert domain.end_bp == 20


def test_bundle_reverse_strand_at_value_one():
    """Cell (0,1) has cell_value=1 → REVERSE scaffold."""
    design = make_bundle_design([(0, 1)], length_bp=21)
    strand = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    domain = strand.domains[0]
    assert domain.direction == Direction.REVERSE
    assert domain.start_bp == 20
    assert domain.end_bp == 0


def test_bundle_corrected_direction_r2c1():
    """Cell (2,1) has cell_value=0 → FORWARD (was REVERSE under old parity rule)."""
    design = make_bundle_design([(2, 1)], length_bp=21)
    domain = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD).domains[0]
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
    scaf = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
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
    scaf = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
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
    """Synthetic 2-helix design for algorithm unit tests.

    Cells (0,0) FORWARD / (0,1) REVERSE.  The REVERSE helix is patched to
    phase_offset=330° so that staple-staple crossover candidates exist between
    the two helices.  This is intentional: these tests verify crossover-placement
    algorithms, not the production honeycomb geometry.  With the corrected
    geometry (REVERSE phase=150°), adjacent helices have only scaffold-scaffold
    crossovers; 330° restores the legacy staple-facing geometry needed by the
    algorithm tests.
    """
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=length_bp)
    new_helices = [
        h.model_copy(update={"phase_offset": math.radians(330.0)})
        if h.id == "h_XY_0_1"
        else h
        for h in design.helices
    ]
    return design.model_copy(update={"helices": new_helices})


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
        if s_a and s_b and s_a.strand_type == StrandType.STAPLE and s_b.strand_type == StrandType.STAPLE:
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

    orig_scaffolds  = {s.id: s for s in design.strands if s.strand_type == StrandType.SCAFFOLD}
    result_scaffolds = {s.id: s for s in result.strands if s.strand_type == StrandType.SCAFFOLD}
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
         and not any(s.strand_type == StrandType.SCAFFOLD for s in design.strands
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
        if s.strand_type == StrandType.SCAFFOLD:
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


def test_same_strand_crossover_creates_two_strands():
    """Second in-register crossover on the same helix pair (same-strand case) produces +1 strand."""
    from backend.core.models import Direction
    # Use in-register crossover positions at bp=7 and bp=28 (known valid positions
    # for the 42bp two-helix bundle with default phase offsets).
    design = _two_helix_design(length_bp=42)
    ha, hb = design.helices[0], design.helices[1]
    dir_a, dir_b = Direction.REVERSE, Direction.FORWARD  # staple directions for (0,0)/(0,1)

    # First crossover at bp=7: two separate staple strands merge into one spanning both helices.
    d1 = make_staple_crossover(design, ha.id, 7, dir_a, hb.id, 7, dir_b)
    staple_count_1 = sum(1 for s in d1.strands if s.strand_type == StrandType.STAPLE)
    assert staple_count_1 == 2  # merged outer + short inner

    # Second crossover at bp=28: both positions are on the merged outer strand → same-strand.
    d2 = make_staple_crossover(d1, ha.id, 28, dir_a, hb.id, 28, dir_b)
    staple_count_2 = sum(1 for s in d2.strands if s.strand_type == StrandType.STAPLE)
    # Merged strand is split into two → total staples increases by 1.
    assert staple_count_2 == 3


def test_same_strand_crossover_preserves_nucleotide_count():
    """Same-strand crossover must not gain or lose nucleotides."""
    from backend.core.models import Direction

    def _count_nucs(d):
        return sum(abs(dom.end_bp - dom.start_bp) + 1
                   for s in d.strands for dom in s.domains)

    design = _two_helix_design(length_bp=42)
    ha, hb = design.helices[0], design.helices[1]
    dir_a, dir_b = Direction.REVERSE, Direction.FORWARD

    d1 = make_staple_crossover(design, ha.id, 7, dir_a, hb.id, 7, dir_b)
    d2 = make_staple_crossover(d1, ha.id, 28, dir_a, hb.id, 28, dir_b)
    assert _count_nucs(d2) == _count_nucs(design)


def test_auto_crossover_places_crossovers_throughout_long_helix():
    """make_auto_crossover must place crossovers across the full helix, not just near bp=0."""
    from backend.core.lattice import make_auto_crossover
    length_bp = 200
    design = _two_helix_design(length_bp=length_bp)
    result = make_auto_crossover(design)

    # Collect all bp positions where a staple strand crosses between helices.
    ha_id = design.helices[0].id
    hb_id = design.helices[1].id
    crossover_bp: list[int] = []
    for s in result.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            continue
        for i in range(len(s.domains) - 1):
            d0, d1 = s.domains[i], s.domains[i + 1]
            # A crossover is a domain transition that changes helix.
            if d0.helix_id != d1.helix_id:
                crossover_bp.append(d0.end_bp)

    assert len(crossover_bp) >= 8, (
        f"Expected ≥8 crossovers for {length_bp}bp helix pair, got {len(crossover_bp)}: {sorted(crossover_bp)}"
    )
    # Crossovers must be spread across the helix, not clustered at the start.
    assert max(crossover_bp) > length_bp * 0.5, (
        f"No crossovers in the second half of the helix: max={max(crossover_bp)}"
    )


# ── 18HB autostaple tests ──────────────────────────────────────────────────────

_CELLS_6HB = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 1)]

# New canonical 18HB cell layout (see drawings/honeycomb_proposed.png).
_CELLS_18HB = [
    (0, 0), (0, 1), (1, 0),
    (0, 2), (1, 2), (2, 1),
    (3, 1), (3, 0), (4, 0),
    (5, 1), (4, 2), (3, 2),
    (3, 3), (3, 4), (3, 5),
    (2, 5), (1, 4), (2, 3),
]



def _build_scaffold_positions(design):
    """Return set of (helix_id, bp, direction) tuples for all scaffold nucleotides."""
    positions = set()
    for strand in design.strands:
        if strand.strand_type == StrandType.STAPLE:
            continue
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                positions.add((domain.helix_id, bp, domain.direction))
    return positions


def _count_crossover_transitions(design):
    """Count domain transitions that cross between different helices (crossover junctions)."""
    count = 0
    for s in design.strands:
        for i in range(len(s.domains) - 1):
            if s.domains[i].helix_id != s.domains[i + 1].helix_id:
                count += 1
    return count


def test_18hb_all_cells_valid():
    """All 18 cells in the canonical 18HB layout must be non-hole cells."""
    for row, col in _CELLS_18HB:
        assert is_valid_honeycomb_cell(row, col), (
            f"Cell ({row},{col}) is a hole — not a valid 18HB cell."
        )


def test_18hb_design_has_18_helices():
    """make_bundle_design must create exactly 18 helices for the 18HB cell set."""
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    assert len(design.helices) == 18


def test_18hb_adjacent_pairs_found():
    """All 21 geometrically adjacent helix pairs must have in-register crossover candidates.

    With the half-bp CW phase offsets (FORWARD=42°, REVERSE=342°), adjacent
    honeycomb helices have staple-staple in-register crossovers (scaffold beads
    are 60° apart giving ~1.25 nm minimum, above the valid threshold; staple
    beads are 180° apart giving ~0.25 nm minimum).  The test verifies that each
    pair produces at least one in-register candidate within the end-margin window.
    """
    from backend.core.crossover_positions import valid_crossover_positions
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    helices = design.helices

    # Identify all geometrically adjacent pairs (centre-to-centre ≈ HONEYCOMB_HELIX_SPACING).
    adjacent_pairs = []
    for i in range(len(helices)):
        for j in range(i + 1, len(helices)):
            ha, hb = helices[i], helices[j]
            sep = math.hypot(
                ha.axis_start.x - hb.axis_start.x,
                ha.axis_start.y - hb.axis_start.y,
            )
            if abs(sep - HONEYCOMB_HELIX_SPACING) < 0.05:
                adjacent_pairs.append((ha, hb))

    assert len(adjacent_pairs) == 21, (
        f"Expected 21 adjacent pairs in 18HB layout, got {len(adjacent_pairs)}"
    )

    for ha, hb in adjacent_pairs:
        cands = valid_crossover_positions(ha, hb)
        in_reg = [
            c for c in cands
            if c.bp_a == c.bp_b
            and 3 <= c.bp_a < 39
        ]
        assert in_reg, (
            f"No in-register crossover found for pair {ha.id} <-> {hb.id}"
        )


def test_18hb_auto_crossover_places_all_crossovers():
    """make_auto_crossover must place ≥42 crossover transitions across the 18HB layout.

    42 = 21 adjacent pairs × 2 crossovers each (DX motif).
    """
    from backend.core.lattice import make_auto_crossover
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    result = make_auto_crossover(design)
    n_crossovers = _count_crossover_transitions(result)
    assert n_crossovers >= 42, (
        f"Expected ≥42 crossover transitions after auto_crossover, got {n_crossovers}"
    )


def test_18hb_autostaple_no_scaffold_crossovers():
    """Auto crossover must never place a crossover involving scaffold strands."""
    from backend.core.lattice import make_auto_crossover
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    result = make_auto_crossover(design)
    scaffold_pos = _build_scaffold_positions(result)
    for s in result.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            continue
        for i in range(len(s.domains) - 1):
            d0, d1 = s.domains[i], s.domains[i + 1]
            if d0.helix_id != d1.helix_id:
                # d0.end_bp is the exit point on helix d0.helix_id
                assert (d0.helix_id, d0.end_bp, d0.direction) not in scaffold_pos, (
                    f"Staple crossover at scaffold position ({d0.helix_id}, {d0.end_bp}, {d0.direction})"
                )


def test_18hb_autostaple_preserves_nucleotide_count():
    """Auto crossover must not gain or lose nucleotides."""
    from backend.core.lattice import make_auto_crossover
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    result = make_auto_crossover(design)

    def _total_nucs(d):
        return sum(
            abs(dom.end_bp - dom.start_bp) + 1
            for s in d.strands
            for dom in s.domains
        )

    assert _total_nucs(result) == _total_nucs(design), (
        "Autostaple changed the total nucleotide count"
    )


def test_18hb_autostaple_min_spacing_respected():
    """Canonical DX crossovers: within-pair gap=1 is allowed; between-pair gap must be >=5."""
    from backend.core.lattice import make_auto_crossover
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    result = make_auto_crossover(design)

    # Gather all crossover-exit bp positions per helix
    helix_crossover_bps: dict[str, list[int]] = {}
    for s in result.strands:
        for i in range(len(s.domains) - 1):
            d0, d1 = s.domains[i], s.domains[i + 1]
            if d0.helix_id != d1.helix_id:
                helix_crossover_bps.setdefault(d0.helix_id, []).append(d0.end_bp)

    # Canonical DX motif pairs crossovers 1 bp apart (e.g. {6,7} or {13,14}).
    # Between distinct DX pairs the gap must be >= 5 bp (canonical plan positions are
    # 6bp apart, but actual domain exit bps can shift ±1 due to the half-open
    # REVERSE b_left.end_bp = bp_b+1 encoding).
    for helix_id, bps in helix_crossover_bps.items():
        bps_sorted = sorted(bps)
        for k in range(len(bps_sorted) - 1):
            gap = bps_sorted[k + 1] - bps_sorted[k]
            if gap == 1:
                continue  # within-DX-pair gap — expected
            assert gap >= 5, (
                f"Crossovers on {helix_id} at bps {bps_sorted[k]} and {bps_sorted[k+1]} "
                f"are {gap}bp apart (expected 1 for DX pair or >=5 between pairs)"
            )


def test_18hb_autostaple_reversed_order_same_strand():
    """make_staple_crossover must handle same-strand crossover when b-domain precedes a-domain."""
    from backend.core.lattice import make_auto_crossover, make_staple_crossover
    from backend.core.models import Direction
    # Build a 2-crossover scenario on the (0,0)-(1,0) pair which has only bp=21.
    # Then use the (1,0)-(2,1) pair at bp=14 to test reversed domain order.
    design = make_bundle_design([(0, 0), (1, 0), (2, 1)], length_bp=42)
    # Place crossover between (0,0) and (1,0) at bp=21 first
    # h(0,0): FORWARD scaffold → REVERSE staple; h(1,0): REVERSE scaffold → FORWARD staple
    d1 = make_staple_crossover(design, "h_XY_0_0", 21, Direction.REVERSE,
                               "h_XY_1_0", 21, Direction.FORWARD)
    # Now place crossover between (1,0) and (2,1) at bp=14 — may trigger reversed-order case
    # h(2,1): FORWARD scaffold → REVERSE staple
    d2 = make_staple_crossover(d1, "h_XY_1_0", 14, Direction.FORWARD,
                               "h_XY_2_1", 14, Direction.REVERSE)
    # Nucleotide count must be preserved
    def _nucs(d):
        return sum(abs(dom.end_bp - dom.start_bp) + 1 for s in d.strands for dom in s.domains)
    assert _nucs(d2) == _nucs(design)


# ── make_half_crossover tests ──────────────────────────────────────────────────

from backend.core.lattice import make_half_crossover


def _nucs(design):
    return sum(abs(dom.end_bp - dom.start_bp) + 1 for s in design.strands for dom in s.domains)


def test_half_crossover_normal_returns_design():
    """make_half_crossover returns a Design object."""
    from backend.core.models import Design
    design = _two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_half_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    assert isinstance(result, Design)


def test_half_crossover_preserves_nucleotide_count():
    """Nucleotide count must be unchanged after a half-crossover."""
    design = _two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_half_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    assert _nucs(result) == _nucs(design)


def test_half_crossover_normal_increases_strand_count():
    """Normal half-crossover: strand_a is rerouted; b_left and a_right become free strands.
    Net change: 2 strands become 3 (or 2 if one piece is zero-length)."""
    design = _two_helix_design()
    before = len(design.strands)
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)
    result = make_half_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    after = len(result.strands)
    assert after >= before  # may be +1 or +2 depending on edge positions


def test_half_crossover_scaffold_rejected():
    """make_half_crossover must raise ValueError if a scaffold position is targeted."""
    design = _two_helix_design()
    ha = design.helices[0]
    from backend.core.models import Direction
    import pytest
    with pytest.raises(ValueError):
        make_half_crossover(design, ha.id, 10, Direction.FORWARD,
                            ha.id, 10, Direction.FORWARD)


def test_half_then_companion_equivalent_to_full_crossover():
    """Placing both halves of a DX junction should yield the same nucleotide count
    as a single make_staple_crossover call."""
    from backend.core.models import Direction
    design = _two_helix_design(42)
    ha, hb = design.helices[0], design.helices[1]
    candidates = valid_crossover_positions(ha, hb)

    # Find a staple-only candidate with room for a companion (not at boundary)
    nuc_info: dict = {}
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                nuc_info[(domain.helix_id, bp, domain.direction)] = strand

    cand = None
    for c in candidates:
        s_a = nuc_info.get((ha.id, c.bp_a, c.direction_a))
        s_b = nuc_info.get((hb.id, c.bp_b, c.direction_b))
        if s_a and s_b and s_a.strand_type == StrandType.STAPLE and s_b.strand_type == StrandType.STAPLE:
            cand = c
            break

    if cand is None:
        pytest.skip("No usable staple candidate")

    # Half 1 (AB)
    d1 = make_half_crossover(design, ha.id, cand.bp_a, cand.direction_a,
                             hb.id, cand.bp_b, cand.direction_b)
    assert _nucs(d1) == _nucs(design)

    # Companion bp positions
    dir_a_val = cand.direction_a
    dir_b_val = cand.direction_b
    comp_bp_a = cand.bp_a + (1 if dir_a_val == Direction.FORWARD else -1)
    comp_bp_b = cand.bp_b + (-1 if dir_b_val == Direction.FORWARD else 1)

    # Half 2 (BA) — endpoint-join or normal
    try:
        d2 = make_half_crossover(d1, hb.id, comp_bp_b, dir_b_val,
                                 ha.id, comp_bp_a, dir_a_val)
        assert _nucs(d2) == _nucs(design)
    except ValueError:
        pass  # companion may be at a domain boundary that makes it unreachable


def test_half_crossover_endpoint_join():
    """Placing the companion half after the first creates an endpoint-join if the pieces
    line up correctly — nucleotide count must still be preserved."""
    from backend.core.models import Direction
    design = _two_helix_design(42)
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_candidate(design)

    # First half
    d1 = make_half_crossover(design, ha_id, bp_a, dir_a, hb_id, bp_b, dir_b)
    assert _nucs(d1) == _nucs(design)

    # Second half (companion) — may be endpoint-join
    comp_bp_a = bp_a + (1 if dir_a == Direction.FORWARD else -1)
    comp_bp_b = bp_b + (-1 if dir_b == Direction.FORWARD else 1)
    try:
        d2 = make_half_crossover(d1, hb_id, comp_bp_b, dir_b, ha_id, comp_bp_a, dir_a)
        assert _nucs(d2) == _nucs(design)
    except (ValueError, RuntimeError):
        pass  # companion position may not be reachable in this test design


# ── Loop / circular strand detection tests ────────────────────────────────────

from backend.core.validator import _is_loop_strand, validate_design
from backend.core.models import Strand, Domain, Direction, StrandType


def _make_domain(helix_id, start_bp, end_bp, direction):
    return Domain(helix_id=helix_id, start_bp=start_bp, end_bp=end_bp, direction=direction)


def test_is_loop_strand_linear_is_not_loop():
    """A plain linear strand should NOT be flagged as a loop."""
    s = Strand(id="s1", domains=[_make_domain("h0", 0, 41, Direction.FORWARD)], strand_type=StrandType.STAPLE)
    assert not _is_loop_strand(s)


def test_is_loop_strand_two_domains_linear_not_loop():
    """Two sequential domains on different helices — linear strand — not a loop."""
    s = Strand(id="s1", domains=[
        _make_domain("h0", 0, 20, Direction.FORWARD),
        _make_domain("h1", 20, 0,  Direction.REVERSE),
    ], strand_type=StrandType.STAPLE)
    assert not _is_loop_strand(s)


def test_is_loop_strand_position_overlap_detected():
    """A strand that visits the same bp position twice should be flagged as a loop."""
    s = Strand(id="s1", domains=[
        _make_domain("h0", 0, 20, Direction.FORWARD),
        _make_domain("h0", 15, 0, Direction.FORWARD),  # overlaps bp 15-20
    ], strand_type=StrandType.STAPLE)
    assert _is_loop_strand(s)


def test_is_loop_strand_terminal_adjacency_detected():
    """A strand whose 3′ end is adjacent to its 5′ start on the same helix+direction."""
    # FORWARD: if domain[-1].end_bp + 1 == domain[0].start_bp → loop
    s = Strand(id="s1", domains=[
        _make_domain("h0", 10, 20, Direction.FORWARD),  # 5' starts at 10
        _make_domain("h0", 21, 30, Direction.FORWARD),  # 3' ends at 30; but wait, need 30+1 == 10?
    ], strand_type=StrandType.STAPLE)
    # Not a loop — ends at 30, start at 10, not adjacent.
    assert not _is_loop_strand(s)

    # Create a case where last.end_bp + 1 == first.start_bp
    s2 = Strand(id="s2", domains=[
        _make_domain("h0", 10, 20, Direction.FORWARD),
    ], strand_type=StrandType.STAPLE)
    # Single domain: 3' at 20, 5' at 10, same helix — 20+1=21 ≠ 10, not a loop.
    assert not _is_loop_strand(s2)

    # Construct a true terminal-adjacency loop
    s3 = Strand(id="s3", domains=[
        _make_domain("h0", 5, 20, Direction.FORWARD),   # 5' at 5
        _make_domain("h1", 20, 5, Direction.REVERSE),   # crosses to h1
        _make_domain("h0", 4, 4, Direction.FORWARD),    # 3' at 4 → 4+1=5 == start of domain[0]
    ], strand_type=StrandType.STAPLE)
    assert _is_loop_strand(s3)


def test_validate_design_detects_loop_strand():
    """validate_design should include a loop-strand error when one exists."""
    # Build a design and manually inject a self-overlapping strand.
    design = _two_helix_design()
    loop = Strand(id="loop_stpl", domains=[
        _make_domain("h_XY_0_0", 0, 20, Direction.REVERSE),
        _make_domain("h_XY_0_0", 15, 0, Direction.REVERSE),  # overlaps
    ], strand_type=StrandType.STAPLE)
    from backend.core.models import Design
    design_with_loop = Design(
        metadata=design.metadata,
        lattice_type=design.lattice_type,
        helices=design.helices,
        strands=design.strands + [loop],
        crossovers=design.crossovers,
    )
    report = validate_design(design_with_loop)
    loop_results = [r for r in report.results if "loop_stpl" in r.message or "Circular" in r.message]
    assert loop_results, "Expected a loop/circular strand validation error"
    assert any(not r.ok for r in loop_results)


def test_validate_design_no_loop_in_clean_bundle():
    """A fresh 2-helix bundle should have no loop strands in the validation report."""
    design = _two_helix_design()
    report = validate_design(design)
    loop_results = [r for r in report.results if "Circular" in r.message]
    assert not loop_results, "Fresh bundle should have no circular strands"


# ── Nick placement (Stage 2 autostaple) tests ──────────────────────────────────


def test_nick_plan_for_strand_targets_correct_length():
    """compute_nick_plan_for_strand breaks a long strand into ~target_length pieces."""
    from backend.core.lattice import compute_nick_plan_for_strand, make_auto_crossover
    # Use 18HB at 126bp — produces zigzag strands well over 50 nt
    design = make_bundle_design(_CELLS_18HB, length_bp=126)
    result = make_auto_crossover(design)
    # Find the longest non-scaffold strand
    def _len(s):
        return sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains)
    long_strand = max((s for s in result.strands if s.strand_type == StrandType.STAPLE), key=_len)
    assert _len(long_strand) > 21, "18HB 126bp should produce multi-segment zigzag strands"
    # With 7-bp prebreak, strands are naturally shorter; use max_length=28 so
    # compute_nick_plan_for_strand has something to cut.
    nicks = compute_nick_plan_for_strand(long_strand, preferred_lengths=[14], min_length=7, max_length=28)
    # Must produce at least one nick for a long strand
    assert len(nicks) >= 1, "Expected nicks for a strand longer than max_length=28"
    # Every nick must specify valid fields
    for n in nicks:
        assert "helix_id" in n and "bp_index" in n and "direction" in n


def test_make_nicks_for_autostaple_all_strands_in_canonical_range():
    """After make_nicks_for_autostaple no staple strand should exceed max_length (60 nt)."""
    from backend.core.lattice import make_auto_crossover, make_nicks_for_autostaple
    for length_bp in [42, 84, 126]:
        design = make_bundle_design(_CELLS_18HB, length_bp=length_bp)
        after_xovers = make_auto_crossover(design)
        final = make_nicks_for_autostaple(after_xovers)

        def _len(s):
            return sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains)

        too_long = [
            _len(s) for s in final.strands
            if s.strand_type == StrandType.STAPLE and _len(s) > 60
        ]
        assert not too_long, (
            f"18HB {length_bp}bp: strands > 60 nt after nicks: {too_long}"
        )


def test_make_nicks_preserves_nucleotide_count():
    """make_nicks_for_autostaple must not gain or lose nucleotides."""
    from backend.core.lattice import make_auto_crossover, make_nicks_for_autostaple
    design = make_bundle_design(_CELLS_18HB, length_bp=126)
    after_xovers = make_auto_crossover(design)
    final = make_nicks_for_autostaple(after_xovers)

    def _total_nucs(d):
        return sum(abs(dom.end_bp - dom.start_bp) + 1 for s in d.strands for dom in s.domains)

    assert _total_nucs(after_xovers) == _total_nucs(final), \
        "Nick placement must not change total nucleotide count"


def test_autostaple_no_unexpected_short_stubs():
    """Autostaple must not produce stubs < 18 nt (DX 2-nt inner strands are expected artifacts)."""
    from backend.core.lattice import make_auto_crossover
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    result = make_auto_crossover(design)

    def _len(s):
        return sum(abs(d.end_bp - d.start_bp) + 1 for d in s.domains)

    # Small loop strands (≤14 nt) are valid crossover products (HORIZ-A 14-nt loops).
    short = [_len(s) for s in result.strands if s.strand_type == StrandType.STAPLE and 14 < _len(s) < 18]
    assert not short, (
        f"Found {len(short)} unexpected short stubs after autostaple: {short}"
    )


def test_auto_crossover_domain_lengths_multiples_of_7():
    """All staple domains after auto_crossover must be ≥7 nt and a multiple of 7."""
    from backend.core.lattice import make_auto_crossover

    def _domain_len(d):
        return abs(d.end_bp - d.start_bp) + 1

    for cells, label in [(_CELLS_6HB, "6HB"), (_CELLS_18HB, "18HB")]:
        design = make_bundle_design(cells, length_bp=42)
        result = make_auto_crossover(design)
        violations = []
        for s in result.strands:
            if s.strand_type == StrandType.SCAFFOLD:
                continue
            for d in s.domains:
                length = _domain_len(d)
                if length < 7 or length % 7 != 0:
                    violations.append(
                        f"{label} strand={s.id} domain={d.helix_id}[{d.start_bp}→{d.end_bp}] len={length}"
                    )
        assert not violations, (
            f"Domain length violations (must be ≥7 and multiple of 7):\n"
            + "\n".join(violations)
        )


def test_has_sandwich_unit():
    """_has_sandwich correctly identifies sandwich and non-sandwich patterns."""
    from backend.core.lattice import _has_sandwich
    assert _has_sandwich([14, 7, 14])        # classic sandwich
    assert _has_sandwich([7, 14, 7, 14, 7])  # multiple sandwiches
    assert not _has_sandwich([14, 7, 7])     # short domain only on right → ok
    assert not _has_sandwich([7, 7, 14])     # short domain only on left → ok
    assert not _has_sandwich([7, 7, 7])      # all equal → ok
    assert not _has_sandwich([14, 14])       # two domains → no interior → ok
    assert not _has_sandwich([7])            # single domain → ok


def test_nick_plan_avoids_sandwich():
    """compute_nick_plan_for_strand must not produce sandwich-violating segments."""
    from backend.core.lattice import (
        compute_nick_plan_for_strand, _has_sandwich, _strand_domain_lens,
        _strand_nucleotide_positions,
    )
    from backend.core.models import Direction

    # Build a synthetic strand: [14bp on A] + [7bp on B] + [14bp on A] = 35 nt
    # This is already a sandwich [14, 7, 14].  At 35 nt it's below max_length=60
    # so the tool must fix it via sandwich-aware nicking.
    a = "h_XY_0_0"
    b = "h_XY_0_1"
    strand = Strand(id="test_sw", domains=[
        _make_domain(a, 13, 0, Direction.REVERSE),   # 14 bp
        _make_domain(b, 0, 6, Direction.FORWARD),    # 7 bp
        _make_domain(a, 28, 15, Direction.REVERSE),  # 14 bp
    ])

    nicks = compute_nick_plan_for_strand(strand, preferred_lengths=[21], min_length=14, max_length=42)
    positions = _strand_nucleotide_positions(strand)
    # Simulate the split: collect segment slices between nicks (sorted ascending by index).
    nick_indices = []
    for n in nicks:
        for i, (h, bp, d) in enumerate(positions):
            if h == n["helix_id"] and bp == n["bp_index"] and d == n["direction"]:
                nick_indices.append(i)
                break
    nick_indices.sort()

    boundaries = [0] + [i + 1 for i in nick_indices] + [len(positions)]
    for seg_start, seg_end in zip(boundaries, boundaries[1:]):
        seg = positions[seg_start:seg_end]
        lens = _strand_domain_lens(seg)
        assert not _has_sandwich(lens), (
            f"Segment with domain lengths {lens} is a sandwich after nick plan"
        )



# ── Scaffold routing tests ─────────────────────────────────────────────────────

from backend.core.lattice import (
    auto_scaffold,
    compute_scaffold_routing,
    _helix_adjacency_graph,
    _greedy_hamiltonian_path,
)


def _make_2hb(length_bp: int = 42):
    """Minimal 2-helix bundle: cells (0,0) FORWARD and (0,1) REVERSE."""
    return make_bundle_design([(0, 0), (0, 1)], length_bp=length_bp)


def _make_6hb(length_bp: int = 42):
    """6-helix bundle in a line: 3 adjacent pairs."""
    cells = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
    return make_bundle_design(cells, length_bp=length_bp)


# ── Adjacency graph ──────────────────────────────────────────────────────────


def test_adjacency_graph_2hb():
    """Both helices of a 2HB are mutually adjacent."""
    design = _make_2hb()
    adj = _helix_adjacency_graph(design)
    ids = {h.id for h in design.helices}
    for hid in ids:
        assert set(adj[hid]) == ids - {hid}, f"{hid} should be adjacent to the other helix"


def test_adjacency_graph_isolated_helix():
    """A single helix has no neighbours."""
    design = make_bundle_design([(0, 0)], length_bp=42)
    # Even-N check is in auto_scaffold, not adjacency graph — single helix is fine here.
    adj = _helix_adjacency_graph(design)
    assert adj[design.helices[0].id] == []


def test_adjacency_graph_sorted_by_distance():
    """Neighbours are sorted nearest-first by XY distance."""
    # 6HB: helix at (0,0) has two neighbours; nearest one should come first.
    design = _make_6hb()
    adj = _helix_adjacency_graph(design)
    h0 = design.helices[0]
    neighbours = adj[h0.id]
    if len(neighbours) >= 2:
        helices_by_id = {h.id: h for h in design.helices}
        cx, cy = h0.axis_start.x, h0.axis_start.y
        dists = [
            (helices_by_id[nb].axis_start.x - cx) ** 2
            + (helices_by_id[nb].axis_start.y - cy) ** 2
            for nb in neighbours
        ]
        assert dists == sorted(dists), "Neighbours should be sorted by distance"


# ── Greedy path ──────────────────────────────────────────────────────────────


def test_greedy_path_2hb_visits_all():
    """Greedy path on 2HB visits both helices."""
    design = _make_2hb()
    adj = _helix_adjacency_graph(design)
    path = _greedy_hamiltonian_path(adj, design.helices[0].id)
    assert path is not None
    assert set(path) == {h.id for h in design.helices}
    assert len(path) == 2


def test_greedy_path_no_repeats():
    """Greedy path on 6HB visits each helix exactly once."""
    design = _make_6hb()
    adj = _helix_adjacency_graph(design)
    path = _greedy_hamiltonian_path(adj, design.helices[0].id)
    assert path is not None
    assert len(path) == len(design.helices)
    assert len(set(path)) == len(path), "Path must not repeat helices"


def test_greedy_path_none_when_stuck():
    """Returns None when the greedy walk cannot visit all nodes."""
    # Fabricate an adjacency where node 'a' connects only to 'b',
    # 'b' connects to 'a' and 'c', but 'c' has no edge back (non-symmetric — contrived).
    adj = {'a': ['b'], 'b': ['a'], 'c': []}
    path = _greedy_hamiltonian_path(adj, 'a')
    assert path is None


# ── compute_scaffold_routing ─────────────────────────────────────────────────


def test_compute_scaffold_routing_2hb():
    """Returns a 2-element path for a 2HB."""
    design = _make_2hb()
    path = compute_scaffold_routing(design)
    assert path is not None
    assert len(path) == 2
    assert set(path) == {h.id for h in design.helices}


def test_compute_scaffold_routing_starts_from_first_helix():
    """Path always starts from design.helices[0]."""
    design = _make_2hb()
    path = compute_scaffold_routing(design)
    assert path[0] == design.helices[0].id


def test_compute_scaffold_routing_single_helix():
    """Single helix returns a 1-element list (trivial path)."""
    design = make_bundle_design([(0, 0)], length_bp=42)
    path = compute_scaffold_routing(design)
    assert path == [design.helices[0].id]


def test_compute_scaffold_routing_empty_design():
    """Empty design returns an empty list."""
    from backend.core.models import Design, DesignMetadata, LatticeType
    empty = Design(
        metadata=DesignMetadata(name="empty"),
        lattice_type=LatticeType.HONEYCOMB,
        helices=[],
        strands=[],
    )
    path = compute_scaffold_routing(empty)
    assert path == []


# ── auto_scaffold — seam_line mode ───────────────────────────────────────────


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_auto_scaffold_seam_line_produces_single_scaffold():
    """After seam-line routing, exactly one scaffold strand spans all helices."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="seam_line")
    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1
    helix_ids_in_scaffold = {d.helix_id for d in scaffolds[0].domains}
    assert helix_ids_in_scaffold == {h.id for h in design.helices}


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_auto_scaffold_seam_line_domain_count_2hb():
    """2HB seam-line: scaffold has exactly 2 domains (one per helix)."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="seam_line")
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    assert len(scaffold.domains) == 2


@pytest.mark.skip(reason="seam-only routing: nick_offset / single scaffold suspended")
def test_auto_scaffold_seam_line_five_prime_respects_nick_offset():
    """5′ end of scaffold is nick_offset bp from helix-1's terminal (FORWARD case)."""
    design = _make_2hb(length_bp=42)
    # Helix 0 is (0,0) → FORWARD: 5' normally at bp=0; with nick_offset=7, at bp=7.
    result = auto_scaffold(design, mode="seam_line", nick_offset=7)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    first_domain = scaffold.domains[0]
    assert first_domain.helix_id == design.helices[0].id
    assert first_domain.start_bp == 7, (
        f"5′ end should be at bp=7, got {first_domain.start_bp}"
    )


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_auto_scaffold_seam_line_replaces_old_scaffolds():
    """Old per-helix scaffold strands are removed after routing."""
    design = _make_2hb(length_bp=42)
    old_scaf_ids = {s.id for s in design.strands if s.strand_type == StrandType.SCAFFOLD}
    result = auto_scaffold(design, mode="seam_line")
    # Exactly one scaffold remains; old IDs should mostly be gone (first is reused).
    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1
    # Staples should still be present
    staples = [s for s in result.strands if s.strand_type == StrandType.STAPLE]
    assert len(staples) == 2  # 2HB has 2 staple strands


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_auto_scaffold_seam_line_total_nucleotides_conserved():
    """Total nucleotide count covered by the scaffold should not exceed helix capacity."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="seam_line")
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    total_nts = sum(
        abs(d.end_bp - d.start_bp) + 1 for d in scaffold.domains
    )
    # With nick_offset=7, the first domain starts at bp=7, so max is 42-7 + 42 = 77 nt
    assert total_nts <= 2 * 42


# ── auto_scaffold — end_to_end mode ─────────────────────────────────────────


def test_auto_scaffold_end_to_end_produces_single_scaffold():
    """After end-to-end routing, exactly one scaffold strand exists."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="end_to_end")
    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1


def test_auto_scaffold_end_to_end_full_domains():
    """End-to-end domains cover each helix from (nick_offset or 0) to full terminal."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="end_to_end", nick_offset=7)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    assert len(scaffold.domains) == 2
    # First domain starts at nick_offset
    first = scaffold.domains[0]
    assert first.start_bp == 7  # FORWARD helix: 5' at bp=7
    assert first.end_bp   == 41  # 3' at bp=41 (full length - 1)
    # Second domain is full-span REVERSE: 5' at bp=41, 3' at bp=0
    second = scaffold.domains[1]
    assert second.start_bp == 41
    assert second.end_bp   == 0


def test_auto_scaffold_end_to_end_five_prime_at_nick_offset():
    """5′ end of end-to-end scaffold is nick_offset bp from helix-1 terminal."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="end_to_end", nick_offset=5)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    assert scaffold.domains[0].start_bp == 5


# ── auto_scaffold — validation ───────────────────────────────────────────────


def test_auto_scaffold_odd_helix_count_raises():
    """auto_scaffold raises ValueError for designs with an odd number of helices."""
    design = make_bundle_design([(0, 0), (0, 1), (1, 0)], length_bp=42)
    with pytest.raises(ValueError, match="even"):
        auto_scaffold(design)


def test_auto_scaffold_invalid_mode_raises():
    """auto_scaffold raises ValueError for unknown mode."""
    design = _make_2hb(length_bp=42)
    with pytest.raises(ValueError, match="Unknown scaffold routing mode"):
        auto_scaffold(design, mode="zigzag")


def test_auto_scaffold_preserves_helix_count():
    """auto_scaffold does not add or remove helices."""
    design = _make_2hb(length_bp=42)
    result = auto_scaffold(design, mode="seam_line")
    assert len(result.helices) == len(design.helices)


def test_auto_scaffold_preserves_deformations():
    """auto_scaffold preserves existing deformations on the design."""
    from backend.core.models import BendParams, DeformationOp
    design = _make_2hb(length_bp=42)
    op = DeformationOp(type="bend", plane_a_bp=0, plane_b_bp=41, affected_helix_ids=[], params=BendParams(angle_deg=30.0))
    design = design.model_copy(update={"deformations": [op]})
    result = auto_scaffold(design, mode="seam_line")
    assert result.deformations == design.deformations


# ── Helpers for seam_bp tests ─────────────────────────────────────────────────

CELLS_18HB = [
    [0, 0], [0, 1], [1, 0],
    [0, 2], [1, 2], [2, 1],
    [3, 1], [3, 0], [4, 0],
    [5, 1], [4, 2], [3, 2],
    [3, 3], [3, 4], [3, 5],
    [2, 5], [1, 4], [2, 3],
]

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]


def _assert_single_scaffold_all_helices(result, design):
    """Assert exactly one scaffold strand covering every helix exactly once."""
    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1, (
        f"Expected 1 scaffold, got {len(scaffolds)}: "
        + str([s.id for s in scaffolds])
    )
    scaffold = scaffolds[0]
    covered = [d.helix_id for d in scaffold.domains]
    assert len(covered) == len(design.helices), (
        f"Expected {len(design.helices)} domains, got {len(covered)}"
    )
    assert len(set(covered)) == len(covered), (
        f"Scaffold visits a helix more than once: {covered}"
    )
    assert set(covered) == {h.id for h in design.helices}, (
        f"Scaffold does not cover all helices. Missing: "
        + str({h.id for h in design.helices} - set(covered))
    )


# ── 6HB 1200bp seam_bp tests ─────────────────────────────────────────────────


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_6hb_1200bp_seam_auto_produces_single_scaffold():
    """6HB 1200bp without seam_bp: single scaffold covering all 6 helices."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line")
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_6hb_1200bp_seam_near_start():
    """6HB 1200bp seam_bp=17 (first valid crossover position): single scaffold."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=17)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_6hb_1200bp_seam_at_59():
    """6HB 1200bp seam_bp=59: single scaffold covering all 6 helices."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=59)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_6hb_1200bp_seam_at_midpoint():
    """6HB 1200bp seam_bp=595 (~midpoint): single scaffold covering all 6 helices."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=595)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_6hb_1200bp_seam_at_600():
    """6HB 1200bp seam_bp=600: single scaffold covering all 6 helices."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=600)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_6hb_1200bp_seam_near_end():
    """6HB 1200bp seam_bp=1100 (near terminal): single scaffold covering all 6 helices."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=1100)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: loop/seam alternation removed")
def test_6hb_1200bp_seam_crossover_near_seam():
    """6HB 1200bp seam_bp=59: seam (odd-pair) crossovers should be close to seam_bp.

    Loop/seam topology: even pairs = loop (near far end), odd pairs = seam.
    Domain[1] ends at the first seam crossover exit (pair 1, odd).
    """
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=59)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    # Domain[0] ends at the loop crossover (near L-1-loop_size), not seam.
    # Domain[1] ends at the first seam crossover (pair 1, odd-indexed).
    seam_domain = scaffold.domains[1]
    assert abs(seam_domain.end_bp - 59) <= 21, (
        f"Seam crossover bp={seam_domain.end_bp} should be within 21bp of seam=59"
    )


@pytest.mark.skip(reason="seam-only routing: loop crossovers removed")
def test_6hb_1200bp_loop_crossover_near_far_end():
    """6HB 1200bp: loop (even-pair) crossovers should be near the far end of the helix."""
    design = make_bundle_design(CELLS_6HB, length_bp=1200)
    result = auto_scaffold(design, mode="seam_line", seam_bp=600, loop_size=7)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    # Domain[0] ends at the first loop crossover (pair 0, FORWARD helix).
    # Target = L-1-loop_size = 1199-7 = 1192 (nearest valid with margin≥9).
    loop_domain = scaffold.domains[0]
    assert loop_domain.end_bp > 1200 // 2, (
        f"Loop crossover bp={loop_domain.end_bp} should be in upper half of helix"
    )


# ── 18HB 400bp seam_bp tests ──────────────────────────────────────────────────


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_auto_produces_single_scaffold():
    """18HB 400bp without seam_bp: single scaffold covering all 18 helices."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line")
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_at_59():
    """18HB 400bp seam_bp=59: single scaffold covering all 18 helices."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line", seam_bp=59)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_at_midpoint():
    """18HB 400bp seam_bp=196 (~midpoint): single scaffold covering all 18 helices."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line", seam_bp=196)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_at_200():
    """18HB 400bp seam_bp=200: single scaffold covering all 18 helices."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line", seam_bp=200)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_at_350():
    """18HB 400bp seam_bp=350 (near terminal): single scaffold covering all 18 helices."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line", seam_bp=350)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_at_17():
    """18HB 400bp seam_bp=17 (near start): single scaffold covering all 18 helices."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line", seam_bp=17)
    _assert_single_scaffold_all_helices(result, design)


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_seam_no_duplicate_helix_ids():
    """18HB 400bp: scaffold domain helix_ids are all distinct across seam positions."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    for seam_bp in [17, 59, 100, 196, 280, 350]:
        result = auto_scaffold(design, mode="seam_line", seam_bp=seam_bp)
        scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
        covered = [d.helix_id for d in scaffold.domains]
        assert len(set(covered)) == 18, (
            f"seam_bp={seam_bp}: scaffold visits a helix more than once. "
            f"Got {len(covered)} domains for {len(set(covered))} unique helices."
        )


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_produces_18_domains():
    """18HB 400bp seam-line scaffold has exactly 18 domains (one per helix)."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line", seam_bp=196)
    scaffold = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    assert len(scaffold.domains) == 18


@pytest.mark.skip(reason="seam-only routing: single continuous scaffold suspended")
def test_18hb_400bp_only_one_scaffold_strand_after_routing():
    """18HB 400bp: exactly one scaffold strand in design after routing (no leftovers)."""
    design = make_bundle_design(CELLS_18HB, length_bp=400)
    result = auto_scaffold(design, mode="seam_line")
    scaffold_count = sum(1 for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    assert scaffold_count == 1, f"Expected 1 scaffold, found {scaffold_count}"


# ── scaffold_extrude_near / scaffold_extrude_far ─────────────────────────────


from backend.core.lattice import (
    scaffold_extrude_near,
    scaffold_extrude_far,
    _helix_axis_lo,
    _helix_axis_hi,
)
from backend.core.models import Helix, Vec3, StrandType


def _make_staggered_4hb(long_bp: int = 220, short_bp: int = 200):
    """4HB where h_XY_0_1 is (long_bp - short_bp) bp shorter at each end.

    All four helices start at z=0 except h_XY_0_1, which starts at
    gap_nm and ends gap_nm earlier — mimicking a helix that was created with
    the wrong length compared to its neighbours.
    """
    CELLS = [(0, 0), (0, 1), (1, 0), (1, 2)]
    base = make_bundle_design(CELLS, length_bp=long_bp)
    gap_nm = ((long_bp - short_bp) // 2) * BDNA_RISE_PER_BP

    new_helices = []
    for h in base.helices:
        if h.id == "h_XY_0_1":
            new_helices.append(h.model_copy(update={
                "axis_start": Vec3(x=h.axis_start.x, y=h.axis_start.y,
                                   z=h.axis_start.z + gap_nm),
                "axis_end":   Vec3(x=h.axis_end.x,   y=h.axis_end.y,
                                   z=h.axis_end.z   - gap_nm),
                "length_bp": short_bp,
            }))
        else:
            new_helices.append(h)

    new_strands = []
    for s in base.strands:
        updated_domains = []
        for d in s.domains:
            if d.helix_id == "h_XY_0_1":
                if d.direction == Direction.REVERSE:
                    updated_domains.append(d.model_copy(update={
                        "start_bp": short_bp - 1, "end_bp": 0}))
                else:
                    updated_domains.append(d.model_copy(update={
                        "start_bp": 0, "end_bp": short_bp - 1}))
            else:
                updated_domains.append(d)
        new_strands.append(s.model_copy(update={"domains": updated_domains}))

    return base.model_copy(update={
        "helices":     new_helices,
        "strands":     new_strands,
        "deformations": base.deformations,
    })


def test_scaffold_extrude_uniform_extends_by_length_bp():
    """Uniform bundle: each helix extended by exactly length_bp in each direction."""
    design = make_bundle_design([(0, 0), (0, 1), (1, 0), (1, 2)], length_bp=100)
    before_lo = min(_helix_axis_lo(h, "XY") for h in design.helices)
    before_hi = max(_helix_axis_hi(h, "XY") for h in design.helices)

    result = scaffold_extrude_near(design, length_bp=10)
    result = scaffold_extrude_far(result,  length_bp=10)

    after_lo = min(_helix_axis_lo(h, "XY") for h in result.helices)
    after_hi = max(_helix_axis_hi(h, "XY") for h in result.helices)

    assert abs(after_lo - (before_lo - 10 * BDNA_RISE_PER_BP)) < 1e-6
    assert abs(after_hi - (before_hi + 10 * BDNA_RISE_PER_BP)) < 1e-6

    lo_vals = [_helix_axis_lo(h, "XY") for h in result.helices]
    hi_vals = [_helix_axis_hi(h, "XY") for h in result.helices]
    assert max(lo_vals) - min(lo_vals) < 1e-6, f"Near ends not flush: {lo_vals}"
    assert max(hi_vals) - min(hi_vals) < 1e-6, f"Far ends not flush:  {hi_vals}"


def test_scaffold_extrude_staggered_helix_flush_after_extension():
    """Offset helix is extended further so ALL helices reach the same target planes."""
    design = _make_staggered_4hb(long_bp=220, short_bp=200)
    result  = scaffold_extrude_near(design, length_bp=10)
    result  = scaffold_extrude_far(result,  length_bp=10)

    lo_vals = [_helix_axis_lo(h, "XY") for h in result.helices]
    hi_vals = [_helix_axis_hi(h, "XY") for h in result.helices]
    assert max(lo_vals) - min(lo_vals) < 1e-6, \
        f"Near ends not flush after extension: {lo_vals}"
    assert max(hi_vals) - min(hi_vals) < 1e-6, \
        f"Far ends not flush after extension: {hi_vals}"


def test_scaffold_extrude_staggered_offset_helix_extended_more():
    """The short helix is extended by 20bp (not 10bp) to compensate its 10bp head-start."""
    design = _make_staggered_4hb(long_bp=220, short_bp=200)  # 10bp gap at each end
    h_before = next(h for h in design.helices if h.id == "h_XY_0_1")
    lo_before = _helix_axis_lo(h_before, "XY")

    result = scaffold_extrude_near(design, length_bp=10)
    h_after = next(h for h in result.helices if h.id == "h_XY_0_1")
    ext_bp = round(
        (lo_before - _helix_axis_lo(h_after, "XY")) / BDNA_RISE_PER_BP
    )
    assert ext_bp == 20, f"Expected h_XY_0_1 extended 20 bp at near end, got {ext_bp}"


def test_scaffold_extrude_staggered_far_offset_helix_extended_more():
    """The short helix is extended by 20bp at the far end as well."""
    design = _make_staggered_4hb(long_bp=220, short_bp=200)
    h_before = next(h for h in design.helices if h.id == "h_XY_0_1")
    hi_before = _helix_axis_hi(h_before, "XY")

    result = scaffold_extrude_far(design, length_bp=10)
    h_after = next(h for h in result.helices if h.id == "h_XY_0_1")
    ext_bp = round(
        (_helix_axis_hi(h_after, "XY") - hi_before) / BDNA_RISE_PER_BP
    )
    assert ext_bp == 20, f"Expected h_XY_0_1 extended 20 bp at far end, got {ext_bp}"
