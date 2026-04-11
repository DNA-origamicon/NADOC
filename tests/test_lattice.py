"""
Tests for backend/core/lattice.py — honeycomb lattice geometry and bundle generation.
"""

import math

import pytest

from backend.core.constants import (
    BDNA_RISE_PER_BP,
    BDNA_TWIST_PER_BP_DEG,
    HONEYCOMB_COL_PITCH,
    HONEYCOMB_HELIX_SPACING,
    HONEYCOMB_LATTICE_RADIUS,
    HONEYCOMB_ROW_PITCH,
)
from backend.core.lattice import (
    honeycomb_cell_value,
    honeycomb_position,
    is_valid_honeycomb_cell,
    ligate_new_strands,
    make_bundle_continuation,
    make_bundle_design,
    make_bundle_segment,
    scaffold_direction_for_cell,
)
from backend.core.models import Direction, LatticeType


# ── Cell value and validity rules ─────────────────────────────────────────────


def test_cell_value_formula():
    """cell_value = (row + col) % 2 — parity only, no holes."""
    assert honeycomb_cell_value(0, 0) == 0   # even parity → FORWARD
    assert honeycomb_cell_value(0, 1) == 1   # odd  parity → REVERSE
    assert honeycomb_cell_value(1, 0) == 1   # odd  parity → REVERSE
    assert honeycomb_cell_value(1, 1) == 0   # even parity → FORWARD
    assert honeycomb_cell_value(2, 0) == 0   # even parity → FORWARD (was hole)
    assert honeycomb_cell_value(2, 1) == 1   # odd  parity → REVERSE
    assert honeycomb_cell_value(2, 2) == 0   # even parity → FORWARD (was hole)


def test_all_cells_valid():
    """All cells are valid — no holes in cadnano2's coordinate system."""
    for r in range(6):
        for c in range(6):
            assert is_valid_honeycomb_cell(r, c) is True


def test_scaffold_direction_even_parity_is_forward():
    """Even-parity cells (row+col even) have FORWARD scaffold."""
    assert scaffold_direction_for_cell(0, 0) == Direction.FORWARD
    assert scaffold_direction_for_cell(1, 1) == Direction.FORWARD
    assert scaffold_direction_for_cell(2, 0) == Direction.FORWARD
    assert scaffold_direction_for_cell(0, 4) == Direction.FORWARD


def test_scaffold_direction_odd_parity_is_reverse():
    """Odd-parity cells (row+col odd) have REVERSE scaffold."""
    assert scaffold_direction_for_cell(0, 1) == Direction.REVERSE
    assert scaffold_direction_for_cell(1, 0) == Direction.REVERSE
    assert scaffold_direction_for_cell(1, 2) == Direction.REVERSE
    assert scaffold_direction_for_cell(2, 1) == Direction.REVERSE


def test_adjacent_valid_cells_are_antiparallel():
    """Every pair of cells at HELIX_SPACING distance have opposite directions."""
    from backend.core.constants import HONEYCOMB_HELIX_SPACING
    rows, cols = 8, 12
    violations = []
    for c in range(cols):
        for r in range(rows):
            x0, y0 = honeycomb_position(r, c)
            for dr in range(-2, 3):
                for dc in range(-2, 3):
                    r2, c2 = r + dr, c + dc
                    if r2 < 0 or c2 < 0 or r2 >= rows or c2 >= cols:
                        continue
                    x2, y2 = honeycomb_position(r2, c2)
                    if abs(math.hypot(x2 - x0, y2 - y0) - HONEYCOMB_HELIX_SPACING) < 0.02:
                        if scaffold_direction_for_cell(r, c) == scaffold_direction_for_cell(r2, c2):
                            violations.append(((r, c), (r2, c2)))
    assert violations == []


# ── Honeycomb positions ───────────────────────────────────────────────────────


def test_origin_at_0_0():
    """Cell (0,0) is at the origin (even parity, no stagger)."""
    x, y = honeycomb_position(0, 0)
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(0.0)


def test_odd_parity_cell_offset():
    """Cell (0,1) has odd parity → x = COL_PITCH, y = +LATTICE_RADIUS (stagger above row 0)."""
    x, y = honeycomb_position(0, 1)
    assert x == pytest.approx(HONEYCOMB_COL_PITCH)
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
    """HONEYCOMB_ROW_PITCH = 3 × LATTICE_RADIUS (cadnano2 convention)."""
    assert HONEYCOMB_ROW_PITCH == pytest.approx(3.0 * HONEYCOMB_LATTICE_RADIUS)


def test_adjacent_row_distance():
    """Odd cell and the even cell one row up (same column) are HONEYCOMB_HELIX_SPACING apart.

    Standard coords: (0,1) is odd (y=+HC_R=+1.125) and (1,1) is even
    (y=+HC_ROW_PITCH=+3.375).  The vertical gap is exactly 2.25 nm = HELIX_SPACING.
    Same-column cells with the same parity (e.g. (0,0) and (1,0), both even)
    are 4.5 nm apart and are NOT adjacent.
    """
    x0, y0 = honeycomb_position(0, 1)  # odd cell
    x1, y1 = honeycomb_position(1, 1)  # even cell, one row below
    dist = math.hypot(x1 - x0, y1 - y0)
    assert dist == pytest.approx(HONEYCOMB_HELIX_SPACING, rel=1e-4)


def test_interior_helix_has_three_neighbours():
    """An interior helix (2, 3) should have exactly 3 neighbours at HELIX_SPACING.

    HC is a 3-connected lattice — each cell has exactly 3 neighbours.
    """
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
    assert nn == 3


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


def test_bundle_phase_offset_forward():
    """FORWARD helices get phase_offset=90°+½·twist (cadnano base + HJ correction)."""
    design = make_bundle_design([(0, 0)], length_bp=21)  # (0,0) → even parity → FORWARD
    h = design.helices[0]
    assert h.phase_offset == pytest.approx(math.radians(90.0 + BDNA_TWIST_PER_BP_DEG / 2))


def test_bundle_phase_offset_reverse():
    """REVERSE helices get phase_offset=60°+½·twist (cadnano base + HJ correction)."""
    design = make_bundle_design([(1, 0)], length_bp=21)  # (1,0) → odd parity → REVERSE
    h = design.helices[0]
    assert h.phase_offset == pytest.approx(math.radians(60.0 + BDNA_TWIST_PER_BP_DEG / 2))


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


def test_bundle_direction_r2c1():
    """Cell (2,1): parity (2+1)%2=1 → odd → REVERSE scaffold."""
    design = make_bundle_design([(2, 1)], length_bp=21)
    domain = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD).domains[0]
    assert domain.direction == Direction.REVERSE


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


def test_bundle_segment_negative_length():
    """Negative length_bp: new helix extends in -axis direction (axis_end.z < axis_start.z)."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 0.0
    result = make_bundle_segment(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    new_helix = next(h for h in result.helices if h.id != base.helices[0].id)
    assert new_helix.length_bp == 21
    assert new_helix.axis_start.z == pytest.approx(offset)
    assert new_helix.axis_end.z   == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)


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
    # With global bp indexing, the new segment at offset_nm=42*rise has bp_start=42
    assert scaf.domains[1].start_bp  == 42
    assert scaf.domains[1].end_bp    == 62


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


def test_continuation_negative_length_fresh_cell():
    """Negative length_bp on a fresh cell: new helix extends in -axis direction."""
    base   = make_bundle_design([(0, 1)], length_bp=42, plane="XY")   # different cell
    offset = 0.0
    result = make_bundle_continuation(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    new_helix = next(h for h in result.helices if h.id not in {h2.id for h2 in base.helices})
    assert new_helix.length_bp == 21
    assert new_helix.axis_start.z == pytest.approx(offset)
    assert new_helix.axis_end.z   == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)


def test_continuation_negative_length_forward():
    """Negative length_bp when existing helix ends at offset: new helix extends in -axis direction."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP   # axis_end.z of base helix (forward continuation point)
    result = make_bundle_continuation(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    new_helix = next(h for h in result.helices if h.id not in {h2.id for h2 in base.helices})
    assert new_helix.length_bp == 21
    assert new_helix.axis_start.z == pytest.approx(offset)
    assert new_helix.axis_end.z   == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)


# ── 18HB autostaple tests ──────────────────────────────────────────────────────

_CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]

# New canonical 18HB cell layout — 3×6 grid (cadnano2 coordinate system).
_CELLS_18HB = [(r, c) for r in range(3) for c in range(6)]



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
    """All 18 cells in the canonical 18HB layout must be valid (all cells are valid in cadnano2 system)."""
    for row, col in _CELLS_18HB:
        assert is_valid_honeycomb_cell(row, col)


def test_18hb_design_has_18_helices():
    """make_bundle_design must create exactly 18 helices for the 18HB cell set."""
    design = make_bundle_design(_CELLS_18HB, length_bp=42)
    assert len(design.helices) == 18


# ── Nick placement (Stage 2 autostaple) tests ──────────────────────────────────


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
    """6-helix bundle: ring of 6 adjacent cells (cadnano2 coordinate system)."""
    return make_bundle_design(list(_CELLS_6HB), length_bp=length_bp)


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

CELLS_18HB = list(_CELLS_18HB)
CELLS_6HB  = list(_CELLS_6HB)


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


def test_scaffold_extrude_staggered_each_subgroup_extended_by_exact_amount():
    """Each subgroup is extended by exactly length_bp, NOT to a global flush plane."""
    design = _make_staggered_4hb(long_bp=220, short_bp=200)  # 10bp gap at each end
    result  = scaffold_extrude_near(design, length_bp=10)
    result  = scaffold_extrude_far(result,  length_bp=10)

    # Subgroup near ends: long helices at 0 → -10*RISE; short helix at 10*RISE → 0
    lo_vals = sorted({round(_helix_axis_lo(h, "XY") / BDNA_RISE_PER_BP) for h in result.helices})
    hi_vals = sorted({round(_helix_axis_hi(h, "XY") / BDNA_RISE_PER_BP) for h in result.helices})
    assert lo_vals == [-10, 0], f"Unexpected near-end bp positions: {lo_vals}"
    assert hi_vals == [220, 230], f"Unexpected far-end bp positions: {hi_vals}"


def test_scaffold_extrude_staggered_offset_helix_extended_exactly_length_bp():
    """The offset helix is extended by exactly length_bp, not more."""
    design = _make_staggered_4hb(long_bp=220, short_bp=200)  # 10bp gap at each end
    h_before = next(h for h in design.helices if h.id == "h_XY_0_1")
    lo_before = _helix_axis_lo(h_before, "XY")

    result = scaffold_extrude_near(design, length_bp=10)
    h_after = next(h for h in result.helices if h.id == "h_XY_0_1")
    ext_bp = round(
        (lo_before - _helix_axis_lo(h_after, "XY")) / BDNA_RISE_PER_BP
    )
    assert ext_bp == 10, f"Expected h_XY_0_1 extended exactly 10 bp at near end, got {ext_bp}"


def test_scaffold_extrude_staggered_far_offset_helix_extended_exactly_length_bp():
    """The offset helix is extended by exactly length_bp at the far end as well."""
    design = _make_staggered_4hb(long_bp=220, short_bp=200)
    h_before = next(h for h in design.helices if h.id == "h_XY_0_1")
    hi_before = _helix_axis_hi(h_before, "XY")

    result = scaffold_extrude_far(design, length_bp=10)
    h_after = next(h for h in result.helices if h.id == "h_XY_0_1")
    ext_bp = round(
        (_helix_axis_hi(h_after, "XY") - hi_before) / BDNA_RISE_PER_BP
    )
    assert ext_bp == 10, f"Expected h_XY_0_1 extended exactly 10 bp at far end, got {ext_bp}"


@pytest.mark.skip(
    reason=(
        "seam-only routing: seam routing requires a Hamiltonian path where all "
        "full-span↔partial cross-Z transitions fall at odd indices. With the new "
        "cadnano2 3-neighbour topology the rectangular _CELLS_6HB block embedded "
        "in the centre of the 3×6 _CELLS_18HB grid produces no such path. "
        "Cell sets need redesigning for the new topology before re-enabling."
    )
)
def test_seam_line_continuation_crossovers_are_coplanar():
    """
    6HB 42bp extended in-place to an 18HB 142bp continuation design.
    After auto_scaffold seam + scaffold_add_end_crossovers, every cross-helix
    domain transition in the scaffold must have both endpoints at the same
    physical Z position (within 1.5bp tolerance).

    A ~42bp Z-gap indicates the seam crossover used the same local bp index on
    both helices without accounting for their different Z-starts.
    """
    from backend.core.lattice import (
        make_bundle_design,
        make_bundle_continuation,
        auto_scaffold,
        scaffold_add_end_crossovers,
    )
    from backend.core.geometry import helix_axis_point
    from backend.core.models import StrandType

    # Reuse the canonical cell sets defined at module level
    design = make_bundle_design(_CELLS_6HB, length_bp=42)
    offset = 42 * BDNA_RISE_PER_BP
    # extend_inplace=True: the 6 existing helices grow from 42→142bp; 12 new
    # helices are added starting at z=offset with length_bp=100.
    design = make_bundle_continuation(
        design, _CELLS_18HB, length_bp=100, offset_nm=offset, extend_inplace=True
    )

    result = auto_scaffold(design, mode="seam_line")
    result = scaffold_add_end_crossovers(result)

    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1, f"Expected 1 scaffold strand, got {len(scaffolds)}"

    scaffold  = scaffolds[0]
    helix_map = {h.id: h for h in result.helices}
    TOLERANCE = BDNA_RISE_PER_BP * 1.5   # ≈ 0.5 nm

    for i in range(len(scaffold.domains) - 1):
        d1, d2 = scaffold.domains[i], scaffold.domains[i + 1]
        if d1.helix_id == d2.helix_id:
            continue   # same-helix domain boundary — not a crossover

        h1, h2 = helix_map[d1.helix_id], helix_map[d2.helix_id]
        pos1   = helix_axis_point(h1, d1.end_bp)
        pos2   = helix_axis_point(h2, d2.start_bp)
        z_gap  = abs(pos1[2] - pos2[2])

        assert z_gap <= TOLERANCE, (
            f"Crossover {d1.helix_id}@bp{d1.end_bp} → {d2.helix_id}@bp{d2.start_bp}: "
            f"Z gap = {z_gap:.3f} nm ({z_gap / BDNA_RISE_PER_BP:.1f} bp), "
            f"expected ≤ {TOLERANCE:.3f} nm. "
            f"Seam crossover used local bp without accounting for different Z-starts."
        )


@pytest.mark.skip(
    reason=(
        "seam-only routing: 6hb_then_18hb.nadoc uses cell pairs adjacent under the "
        "old 6-neighbour HC topology. In the new cadnano2 3-neighbour system several "
        "helices are isolated (no graph edges), making a Hamiltonian path impossible. "
        "Needs a new example file built with cadnano2-adjacent cells."
    )
)
def test_6hb_then_18hb_one_scaffold_strand_after_routing():
    """Auto scaffold seam + end crossovers on the 6hb_then_18hb example must
    produce exactly one scaffold strand spanning all 18 helices."""
    from pathlib import Path
    from backend.core.models import Design, StrandType
    from backend.core.lattice import auto_scaffold, scaffold_add_end_crossovers

    raw = Path("Examples/6hb_then_18hb.nadoc").read_text()
    design = Design.model_validate_json(raw)

    result = auto_scaffold(design, mode="seam_line")
    result = scaffold_add_end_crossovers(result)

    scaffolds = [s for s in result.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) == 1, (
        f"Expected 1 scaffold strand, got {len(scaffolds)}. "
        "A cross-Z transition must land at a seam-pair position (odd index)."
    )

    # Verify it visits all 18 helices
    visited = {d.helix_id for s in scaffolds for d in s.domains}
    assert len(visited) == 18, f"Expected 18 unique helices, got {len(visited)}: {visited}"


# ── Gap-continuation (merged helix) tests ────────────────────────────────────


def _make_gap_multi_domain():
    """Build a 6HB (full-span) + 12 18HB-only helices design with a gap between two 18HB domains.

    Returns (design, cells_18hb_only) where cells_18hb_only are the 12 cells in the
    18HB section but NOT in the 6HB section.
    """
    # CELLS_18HB uses lists; normalise to tuples for set operations.
    cells_18hb_t = [tuple(c) for c in CELLS_18HB]
    cells_6hb_t  = set(CELLS_6HB)  # already tuples
    cells_18hb_only = [c for c in cells_18hb_t if c not in cells_6hb_t]

    d0 = make_bundle_design(list(CELLS_6HB), length_bp=352)   # 6 full-span helices
    d1 = make_bundle_continuation(d0, cells_18hb_only, 100,   # first 18HB domain
                                   plane="XY", offset_nm=14.028)
    d2 = make_bundle_continuation(d1, cells_18hb_only, 84,    # second domain → gap-merged
                                   plane="XY", offset_nm=75.484)
    return d2, cells_18hb_only


def test_gap_continuation_no_suffix_ids():
    """Helices at same cell in a gap-continuation design share the base ID (no _0 suffix)."""
    d2, _ = _make_gap_multi_domain()

    # All helix IDs must have exactly 3 underscores (h_XY_r_c), no _0 suffix.
    bad = [h.id for h in d2.helices if h.id.count("_") > 3]
    assert not bad, f"Found helix IDs with extra suffix (gap-continuation bug): {bad}"

    # The 12 18HB-only helices must be merged (length > 100 but < 352).
    merged = [h for h in d2.helices if 100 < h.length_bp < 352]
    assert len(merged) == 12, f"Expected 12 merged helices, got {len(merged)}"


def test_gap_continuation_merged_helix_span():
    """Merged helix spans both scaffold regions correctly."""
    from backend.core.constants import BDNA_RISE_PER_BP
    d2, _ = _make_gap_multi_domain()

    local_bp_offset = round((75.484 - 14.028) / BDNA_RISE_PER_BP)
    expected_len = local_bp_offset + 84

    for h in d2.helices:
        if 100 < h.length_bp < 352:
            assert h.length_bp == expected_len, (
                f"{h.id}: expected length {expected_len}, got {h.length_bp}"
            )
            assert abs(h.axis_end.z - (14.028 + expected_len * BDNA_RISE_PER_BP)) < 0.01, (
                f"{h.id}: axis_end.z mismatch"
            )




# ─────────────────────────────────────────────────────────────────────────────
# resize_strand_ends tests
# ─────────────────────────────────────────────────────────────────────────────

from backend.core.lattice import resize_strand_ends


def _make_simple_design():
    """2-helix bundle with 42 bp, returns design and one staple strand."""
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=42)
    # Pick the first staple strand
    staple = next(s for s in design.strands if s.strand_type.value == "staple")
    return design, staple


def test_resize_strand_ends_extend_3p_within_helix():
    """Extending a 3' end within existing helix bounds increases end_bp by delta."""
    design, staple = _make_simple_design()
    # Find a strand that has only one domain so we can predict the result easily
    single_domain_staple = next(
        (s for s in design.strands
         if s.strand_type.value == "staple" and len(s.domains) == 1),
        None,
    )
    # If no single-domain staple, just use any staple
    if single_domain_staple is None:
        single_domain_staple = staple

    helix = next(h for h in design.helices if h.id == single_domain_staple.domains[-1].helix_id)
    term_dom = single_domain_staple.domains[-1]

    # Only extend if there is room
    helix_end_bp = helix.bp_start + helix.length_bp - 1
    if term_dom.end_bp + 3 > helix_end_bp:
        pytest.skip("no room to extend within helix bounds in this design")

    original_end_bp = term_dom.end_bp
    result = resize_strand_ends(design, [{
        "strand_id": single_domain_staple.id,
        "helix_id":  helix.id,
        "end":       "3p",
        "delta_bp":  3,
    }])

    updated_strand = next(s for s in result.strands if s.id == single_domain_staple.id)
    updated_helix  = next(h for h in result.helices if h.id == helix.id)

    assert updated_strand.domains[-1].end_bp == original_end_bp + 3
    # Helix unchanged when extension is within bounds
    assert updated_helix.length_bp == helix.length_bp
    assert updated_helix.bp_start == helix.bp_start


def test_resize_strand_ends_grow_helix_forward():
    """Extending past helix end grows axis_end and length_bp."""
    design, _ = _make_simple_design()
    # Pick a staple on the first helix
    helix = design.helices[0]
    staple = next(
        s for s in design.strands
        if s.strand_type.value == "staple"
        and any(d.helix_id == helix.id for d in s.domains)
        and s.domains[-1].helix_id == helix.id
    )
    term_dom = staple.domains[-1]
    helix_end_bp = helix.bp_start + helix.length_bp - 1

    # Force delta such that new_bp > helix_end_bp
    delta = (helix_end_bp - term_dom.end_bp) + 5   # 5 bp past the helix end

    orig_axis_end_z = helix.axis_end.z

    result = resize_strand_ends(design, [{
        "strand_id": staple.id,
        "helix_id":  helix.id,
        "end":       "3p",
        "delta_bp":  delta,
    }])

    updated_strand = next(s for s in result.strands if s.id == staple.id)
    updated_helix  = next(h for h in result.helices if h.id == helix.id)

    expected_new_end_bp = term_dom.end_bp + delta
    assert updated_strand.domains[-1].end_bp == expected_new_end_bp
    assert updated_helix.length_bp == helix.length_bp + 5
    # axis_end moves forward along helix axis (the 42-bp helix runs along +Z)
    import math
    expected_dz = 5 * BDNA_RISE_PER_BP
    assert math.isclose(updated_helix.axis_end.z, orig_axis_end_z + expected_dz, abs_tol=1e-6)


def test_resize_strand_ends_trim_3p():
    """Trimming a 3' end decreases end_bp and total nucleotide count."""
    design, _ = _make_simple_design()
    # Choose any staple whose terminal domain has length ≥ 3 bp
    staple = next(
        (s for s in design.strands
         if s.strand_type.value == "staple"
         and abs(s.domains[-1].end_bp - s.domains[-1].start_bp) + 1 >= 3),
        None,
    )
    if staple is None:
        pytest.skip("no suitable staple strand found in this design")

    helix = next(h for h in design.helices if h.id == staple.domains[-1].helix_id)
    original_end_bp = staple.domains[-1].end_bp

    result = resize_strand_ends(design, [{
        "strand_id": staple.id,
        "helix_id":  helix.id,
        "end":       "3p",
        "delta_bp":  -2,
    }])

    updated_strand = next(s for s in result.strands if s.id == staple.id)
    assert updated_strand.domains[-1].end_bp == original_end_bp - 2


# ── Inline-overhang reconciliation tests ─────────────────────────────────────


def _make_single_helix_scaffolded():
    """
    One helix (50 bp), FORWARD scaffold covering bp 0-41, FORWARD staple bp 5-35.
    Helix is longer than scaffold so extension into overhang territory doesn't
    require growing the helix axis.
    """
    import math as _math
    from backend.core.models import Design, Helix, Strand, Domain, StrandType, Direction, Vec3
    helix = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=50 * BDNA_RISE_PER_BP),
        length_bp=50,
        bp_start=0,
        phase_offset=0.0,
        twist_per_bp_rad=_math.radians(34.3),
    )
    scaffold = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
    )
    staple = Strand(
        id="stap",
        strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h0", start_bp=5, end_bp=35, direction=Direction.FORWARD)],
    )
    return Design(helices=[helix], strands=[scaffold, staple])


def test_resize_inline_overhang_created_on_3p_extension():
    """Extending a 3' end past scaffold coverage splits the domain and adds an OverhangSpec."""
    design = _make_single_helix_scaffolded()
    result = resize_strand_ends(design, [{
        "strand_id": "stap",
        "helix_id":  "h0",
        "end":       "3p",
        "delta_bp":  +10,   # end_bp: 35 → 45; scaffold ends at 41 → 4 bp overhang
    }])

    staple = next(s for s in result.strands if s.id == "stap")
    # Domain was split: scaffold portion + overhang portion
    assert len(staple.domains) == 2, "domain should be split into scaffold + overhang"
    scaf_dom, ovhg_dom = staple.domains
    assert scaf_dom.end_bp       == 41,  "scaffold portion ends at scaffold boundary"
    assert scaf_dom.overhang_id  is None
    assert ovhg_dom.start_bp     == 42,  "overhang portion starts just past scaffold"
    assert ovhg_dom.end_bp       == 45
    assert ovhg_dom.overhang_id  is not None
    # OverhangSpec added
    assert len(result.overhangs) == 1
    spec = result.overhangs[0]
    assert spec.helix_id  == "h0"
    assert spec.strand_id == "stap"
    assert spec.id        == ovhg_dom.overhang_id


def test_resize_inline_overhang_grows_on_second_extension():
    """A second extension from an already-overhanging state extends the overhang domain."""
    design = _make_single_helix_scaffolded()
    # First drag: extend 3' by 10
    d1 = resize_strand_ends(design, [{"strand_id": "stap", "helix_id": "h0",
                                       "end": "3p", "delta_bp": +10}])
    # Second drag: extend by 3 more (end_bp 45 → 48)
    d2 = resize_strand_ends(d1, [{"strand_id": "stap", "helix_id": "h0",
                                   "end": "3p", "delta_bp": +3}])

    staple = next(s for s in d2.strands if s.id == "stap")
    assert len(staple.domains) == 2
    ovhg_dom = staple.domains[-1]
    assert ovhg_dom.end_bp       == 48,  "overhang extended to bp 48"
    assert ovhg_dom.overhang_id  is not None
    assert len(d2.overhangs)     == 1


def test_resize_inline_overhang_removed_when_trimmed_back():
    """Trimming a previously-overhanging end back inside scaffold removes the split and OverhangSpec."""
    design = _make_single_helix_scaffolded()
    # First drag: create overhang (end_bp 35 → 45)
    d1 = resize_strand_ends(design, [{"strand_id": "stap", "helix_id": "h0",
                                       "end": "3p", "delta_bp": +10}])
    assert len(d1.overhangs) == 1

    # Second drag: trim back well inside scaffold (end_bp 45 → 37)
    d2 = resize_strand_ends(d1, [{"strand_id": "stap", "helix_id": "h0",
                                   "end": "3p", "delta_bp": -8}])

    staple = next(s for s in d2.strands if s.id == "stap")
    assert len(staple.domains)       == 1,  "split domains should be merged back"
    assert staple.domains[0].end_bp  == 37
    assert staple.domains[0].overhang_id is None
    assert len(d2.overhangs)         == 0,  "OverhangSpec should be removed"


# ── autodetect_overhangs tests ─────────────────────────────────────────────────

from backend.core.lattice import autodetect_overhangs
import math as _math


def _design_with_scaffold_free_overhang_helix():
    """Design with two helices: h0 (scaffold+staple) and h_ext (staple-only).

    A single staple spans both: its 5' end is on h_ext (scaffold-free), its
    3' end is on h0 (scaffold-covered).  This simulates what happens after a
    user extrudes a staple-only helix and force-connects the ends with 'X'.
    """
    from backend.core.models import (
        Design, Helix, Strand, Domain, StrandType, Direction, Vec3, DesignMetadata,
    )
    h0 = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=42 * BDNA_RISE_PER_BP),
        length_bp=42,
        bp_start=0,
        phase_offset=0.0,
        twist_per_bp_rad=_math.radians(34.3),
    )
    h_ext = Helix(
        id="h_ext",
        axis_start=Vec3(x=5, y=0, z=0),
        axis_end=Vec3(x=5, y=0, z=8 * BDNA_RISE_PER_BP),
        length_bp=8,
        bp_start=0,
        phase_offset=0.0,
        twist_per_bp_rad=_math.radians(34.3),
    )
    scaffold = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
    )
    # Staple: 5' on h_ext (scaffold-free), 3' on h0
    staple = Strand(
        id="stap",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h_ext", start_bp=7, end_bp=0, direction=Direction.REVERSE),
            Domain(helix_id="h0",    start_bp=0, end_bp=20, direction=Direction.REVERSE),
        ],
    )
    return Design(
        helices=[h0, h_ext],
        strands=[scaffold, staple],
        metadata=DesignMetadata(name="test"),
    )


def test_autodetect_overhangs_tags_scaffold_free_terminal():
    """autodetect_overhangs tags the 5' terminal domain on a scaffold-free helix."""
    design = _design_with_scaffold_free_overhang_helix()
    result = autodetect_overhangs(design)

    staple = next(s for s in result.strands if s.id == "stap")
    term_5p = staple.domains[0]
    assert term_5p.helix_id   == "h_ext"
    assert term_5p.overhang_id == "ovhg_inline_stap_5p"
    assert len(result.overhangs) == 1
    spec = result.overhangs[0]
    assert spec.id        == "ovhg_inline_stap_5p"
    assert spec.helix_id  == "h_ext"
    assert spec.strand_id == "stap"


def test_autodetect_overhangs_scaffold_covered_end_untouched():
    """autodetect_overhangs does not tag the 3' end that is on a scaffold-covered helix."""
    design = _design_with_scaffold_free_overhang_helix()
    result = autodetect_overhangs(design)

    staple = next(s for s in result.strands if s.id == "stap")
    term_3p = staple.domains[-1]
    assert term_3p.helix_id     == "h0"
    assert term_3p.overhang_id  is None


def test_autodetect_overhangs_idempotent():
    """Running autodetect_overhangs twice must not create duplicate OverhangSpecs."""
    design = _design_with_scaffold_free_overhang_helix()
    d1 = autodetect_overhangs(design)
    d2 = autodetect_overhangs(d1)
    assert len(d2.overhangs) == len(d1.overhangs) == 1


def test_autodetect_overhangs_skips_isolated_staple():
    """A staple entirely on a scaffold-free helix (not anchored to the bundle) is not tagged."""
    from backend.core.models import (
        Design, Helix, Strand, Domain, StrandType, Direction, Vec3, DesignMetadata,
    )
    h0 = Helix(
        id="h0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=42 * BDNA_RISE_PER_BP),
        length_bp=42,
        bp_start=0,
        phase_offset=0.0,
        twist_per_bp_rad=_math.radians(34.3),
    )
    scaffold = Strand(
        id="scaf",
        strand_type=StrandType.SCAFFOLD,
        domains=[Domain(helix_id="h0", start_bp=0, end_bp=41, direction=Direction.FORWARD)],
    )
    # Isolated staple — entirely on scaffold-free helix h_iso (no h0 domain)
    h_iso = Helix(
        id="h_iso",
        axis_start=Vec3(x=10, y=0, z=0),
        axis_end=Vec3(x=10, y=0, z=8 * BDNA_RISE_PER_BP),
        length_bp=8,
        bp_start=0,
        phase_offset=0.0,
        twist_per_bp_rad=_math.radians(34.3),
    )
    iso_staple = Strand(
        id="iso",
        strand_type=StrandType.STAPLE,
        domains=[Domain(helix_id="h_iso", start_bp=7, end_bp=0, direction=Direction.REVERSE)],
    )
    design = Design(
        helices=[h0, h_iso],
        strands=[scaffold, iso_staple],
        metadata=DesignMetadata(name="test"),
    )
    result = autodetect_overhangs(design)
    iso = next(s for s in result.strands if s.id == "iso")
    assert iso.domains[0].overhang_id is None
    assert len(result.overhangs) == 0


def test_autodetect_overhangs_preserves_existing_overhangs():
    """autodetect_overhangs preserves pre-existing OverhangSpecs."""
    from backend.core.models import OverhangSpec
    design = _design_with_scaffold_free_overhang_helix()
    # Pre-set an unrelated overhang
    existing = OverhangSpec(id="ovhg_other", helix_id="h0", strand_id="scaf")
    design = design.model_copy(update={"overhangs": [existing]})
    result = autodetect_overhangs(design)
    ids = {o.id for o in result.overhangs}
    assert "ovhg_other" in ids
    assert "ovhg_inline_stap_5p" in ids


# ── ligate_new_strands diagnostic tests ──────────────────────────────────────


def _strand_endpoints(design):
    """Return a dict of strand_id → {type, domains: [{helix, dir, 5p, 3p}, ...]}."""
    out = {}
    for s in design.strands:
        doms = []
        for d in s.domains:
            doms.append({
                "helix": d.helix_id,
                "dir": d.direction.value,
                "5p": d.start_bp,
                "3p": d.end_bp,
            })
        out[s.id] = {"type": s.strand_type.value, "domains": doms}
    return out


def test_ligate_after_segment_merges_across_coaxial_helices():
    """make_bundle_segment creates a NEW helix at the same cell — ligation joins
    across coaxial helix IDs via grid_pos matching.

    Before the fix, ligation only searched the same helix_id and missed the
    adjacent strand.  Now it searches all coaxial helices at the same lattice
    cell, so the 4 post-extrude strands collapse to 2.
    """
    base = make_bundle_design([(0, 0)], length_bp=42)
    before = _strand_endpoints(base)

    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0)], length_bp=42, offset_nm=offset)

    # Identify new strand IDs
    old_ids = {s.id for s in base.strands}
    new_ids = {s.id for s in result.strands if s.id not in old_ids}
    assert len(new_ids) >= 2, f"Expected new scaffold+staple, got {new_ids}"

    after_pre_ligate = _strand_endpoints(result)

    # 4 strands before ligation (2 original + 2 new)
    assert len(result.strands) == 4

    # Attempt ligation
    ligated = ligate_new_strands(result, new_ids)
    after_post_ligate = _strand_endpoints(ligated)

    # Coaxial ligation: new strands are absorbed into the originals.
    # scaffold: scaf_XY_0_0 (bp 0-41 on h_XY_0_0) + (bp 42-83 on h_XY_0_0_0) → 1 strand, 2 domains
    # staple:   stpl_XY_0_0 (bp 41-0 on h_XY_0_0) + (bp 83-42 on h_XY_0_0_0) → 1 strand, 2 domains
    assert len(ligated.strands) == 2, (
        f"Expected 2 strands after ligation, got {len(ligated.strands)}"
    )

    # Verify merged scaffold: 2 domains on different helices, spanning full range
    scaf = next(s for s in ligated.strands if s.strand_type.value == "scaffold")
    assert len(scaf.domains) == 2, f"Expected 2 domains (cross-helix), got {len(scaf.domains)}"
    assert scaf.domains[0].helix_id != scaf.domains[1].helix_id, "Domains must be on different helices"
    assert scaf.domains[0].start_bp == 0
    assert scaf.domains[0].end_bp == 41
    assert scaf.domains[1].start_bp == 42
    assert scaf.domains[1].end_bp == 83

    # Verify merged staple: 2 domains on different helices
    stpl = next(s for s in ligated.strands if s.strand_type.value == "staple")
    assert len(stpl.domains) == 2, f"Expected 2 domains (cross-helix), got {len(stpl.domains)}"
    # REVERSE staple: 3' end first then 5' end, so domain order is original then new
    all_bps = {d.start_bp for d in stpl.domains} | {d.end_bp for d in stpl.domains}
    assert min(all_bps) == 0
    assert max(all_bps) == 83

    # Print diagnostic info (visible with pytest -s)
    print("\n=== SEGMENT EXTRUDE: STRAND ENDPOINTS ===")
    old_hid = base.helices[0].id
    new_hid = next(h.id for h in result.helices if h.id != old_hid)
    print(f"Old helix: {old_hid}   New helix: {new_hid}")
    print(f"BEFORE extrude ({len(base.strands)} strands):")
    for sid, info in before.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")
    print(f"AFTER extrude, BEFORE ligate ({len(result.strands)} strands):")
    for sid, info in after_pre_ligate.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")
    print(f"AFTER ligate ({len(ligated.strands)} strands):")
    for sid, info in after_post_ligate.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")


def test_ligate_after_continuation_non_inplace():
    """make_bundle_continuation with extend_inplace=False creates a new helix
    and appends domains to existing strands — ligation has no new IDs to process.
    """
    base = make_bundle_design([(0, 0)], length_bp=42)

    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_continuation(
        base, [(0, 0)], length_bp=42, offset_nm=offset,
        extend_inplace=False,
    )

    old_ids = {s.id for s in base.strands}
    new_ids = {s.id for s in result.strands if s.id not in old_ids}

    # No NEW strands — continuation appended to existing ones.
    assert len(new_ids) == 0
    # Strands now have 2 domains (on different helices).
    for s in result.strands:
        assert len(s.domains) == 2, f"{s.id} should have 2 domains"
        assert s.domains[0].helix_id != s.domains[1].helix_id


def test_continuation_inplace_merges_domains():
    """make_bundle_continuation with extend_inplace=True (the API default) extends
    the existing helix and MERGES adjacent domains into one.

    This is the scenario the user hits when extruding from a blunt end in 3D:
    the API request model defaults extend_inplace=True, so the backend extends
    the helix axis and appends domains on the SAME helix.  _merge_adjacent_domains
    collapses them into a single domain.
    """
    base = make_bundle_design([(0, 0)], length_bp=42)
    before = _strand_endpoints(base)

    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_continuation(
        base, [(0, 0)], length_bp=42, offset_nm=offset,
        extend_inplace=True,
    )

    after = _strand_endpoints(result)

    print("\n=== CONTINUATION IN-PLACE: STRAND ENDPOINTS ===")
    print(f"BEFORE extrude ({len(base.strands)} strands):")
    for sid, info in before.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")
    print(f"AFTER continuation in-place ({len(result.strands)} strands):")
    for sid, info in after.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")

    # Same strand count — continuation appended to existing strands.
    assert len(result.strands) == len(base.strands)

    # Each strand should have exactly 1 domain after merging (same helix, adjacent bp).
    for s in result.strands:
        assert len(s.domains) == 1, (
            f"{s.id} should have 1 merged domain, got {len(s.domains)}: "
            + ", ".join(f"{d.helix_id} {d.direction.value} [{d.start_bp}..{d.end_bp}]" for d in s.domains)
        )

    # Verify the merged scaffold domain spans full range (0-83).
    scaf = next(s for s in result.strands if s.strand_type.value == "scaffold")
    assert scaf.domains[0].start_bp == 0
    assert scaf.domains[0].end_bp == 83

    # Verify the merged staple domain spans full range.
    stpl = next(s for s in result.strands if s.strand_type.value == "staple")
    assert min(stpl.domains[0].start_bp, stpl.domains[0].end_bp) == 0
    assert max(stpl.domains[0].start_bp, stpl.domains[0].end_bp) == 83


def test_ligate_after_continuation_gap_cell():
    """Gap continuation creates NEW strands on the existing helix — ligation can work here.

    When a helix at the same cell ends BELOW offset (gap), continuation extends
    the helix axis but creates separate new strands.  These new strands ARE on
    the same helix as existing strands, so ligation should merge them.
    """
    base = make_bundle_design([(0, 0)], length_bp=42)
    before = _strand_endpoints(base)

    # Leave a gap: base ends at 42*RISE, but we extrude from 84*RISE (skip 42bp gap)
    gap_offset = 84 * BDNA_RISE_PER_BP
    result = make_bundle_continuation(
        base, [(0, 0)], length_bp=42, offset_nm=gap_offset,
    )

    old_ids = {s.id for s in base.strands}
    new_ids = {s.id for s in result.strands if s.id not in old_ids}

    after_pre_ligate = _strand_endpoints(result)

    ligated = ligate_new_strands(result, new_ids)
    after_post_ligate = _strand_endpoints(ligated)

    print("\n=== GAP CONTINUATION: STRAND ENDPOINTS ===")
    print(f"New strand IDs: {new_ids}")
    for hid in sorted({h.id for h in result.helices}):
        h = next(x for x in result.helices if x.id == hid)
        print(f"  Helix {hid}: bp_start={h.bp_start} length_bp={h.length_bp} "
              f"→ bp {h.bp_start}..{h.bp_start + h.length_bp - 1}")
    print(f"BEFORE extrude ({len(base.strands)} strands):")
    for sid, info in before.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")
    print(f"AFTER continuation, BEFORE ligate ({len(result.strands)} strands):")
    for sid, info in after_pre_ligate.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")
    print(f"AFTER ligate ({len(ligated.strands)} strands):")
    for sid, info in after_post_ligate.items():
        for d in info["domains"]:
            print(f"  {sid} ({info['type']}) on {d['helix']} {d['dir']}: 5'={d['5p']}  3'={d['3p']}")

    # Gap strands are on the SAME helix but NOT adjacent (42bp gap).
    # Ligation should NOT merge them.
    assert len(ligated.strands) == len(result.strands), (
        "Gap continuation: strands are not adjacent, ligation should be a no-op"
    )

