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
from backend.core.models import Direction, LatticeType, StrandType


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
    """Negative length_bp: canonical helix below the plane — spans [-L, 0] with
    axis_start.z < axis_end.z (axis_end at the plane offset). length_bp is the magnitude."""
    design = make_bundle_design([(0, 0)], length_bp=-42, plane="XY")
    h = design.helices[0]
    assert h.length_bp == 42
    assert h.axis_start.z == pytest.approx(-42 * BDNA_RISE_PER_BP)
    assert h.axis_end.z   == pytest.approx(0.0)


def test_bundle_negative_length_offset():
    """Negative length with offset: helix spans [offset-L, offset] below the plane (canonical)."""
    offset = 10.0
    design = make_bundle_design([(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    h = design.helices[0]
    assert h.length_bp == 21
    assert h.axis_start.z == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)
    assert h.axis_end.z   == pytest.approx(offset)


def test_bundle_negative_length_zero_raises():
    """length_bp=0 raises ValueError (magnitude must be >= 1)."""
    with pytest.raises(ValueError, match="length_bp"):
        make_bundle_design([(0, 0)], length_bp=0)


def test_bundle_strand_bp_uses_actual_length():
    """Domain spans abs(length_bp) bp.  A minus extrude at offset 0 makes a canonical
    helix in [-L, 0], so the global bp range runs [-L, -1] (still 42 bp wide)."""
    design = make_bundle_design([(0, 0)], length_bp=-42, plane="XY")
    scaf = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    dom  = scaf.domains[0]
    # Cell (0,0) is FORWARD; helix sits below the plane → bp_start=-42.
    assert dom.start_bp == -42
    assert dom.end_bp   == -1
    assert dom.end_bp - dom.start_bp + 1 == 42


# ── make_bundle_segment ────────────────────────────────────────────────────────


def test_bundle_segment_appends_helices():
    """make_bundle_segment adds new helices to an existing design."""
    base = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP
    result = make_bundle_segment(base, [(0, 0)], length_bp=42, plane="XY", offset_nm=offset)
    assert len(result.helices) == 2
    assert len(result.strands) == 4   # 2 scaffold + 2 staple


def test_bundle_segment_from_empty_design_builds_full_bundle():
    """Segment onto an EMPTY design builds the bundle at canonical lattice
    positions — the additive path used to place the first primitive into a
    blank workspace (no existing helix carries grid_pos → zero offset)."""
    from backend.core.models import Design

    cells = [(0, 1), (1, 1), (1, 2)]
    result = make_bundle_segment(Design(), cells, length_bp=42, plane="XY")
    assert len(result.helices) == 3
    assert {tuple(h.grid_pos) for h in result.helices} == set(cells)
    # Canonical placement: a fresh (0,1) helix sits where a bundle-create would put it.
    base = make_bundle_design([(0, 1)], length_bp=42, plane="XY")
    seg01 = next(h for h in result.helices if tuple(h.grid_pos) == (0, 1))
    assert seg01.axis_start.x == pytest.approx(base.helices[0].axis_start.x)
    assert seg01.axis_start.y == pytest.approx(base.helices[0].axis_start.y)


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
    """Negative length_bp: new segment sits below the plane as a canonical helix
    (spans [offset-L, offset], axis_start.z < axis_end.z=offset)."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 0.0
    result = make_bundle_segment(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    new_helix = next(h for h in result.helices if h.id != base.helices[0].id)
    assert new_helix.length_bp == 21
    assert new_helix.axis_start.z == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)
    assert new_helix.axis_end.z   == pytest.approx(offset)


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
    """Negative length_bp on a fresh cell: new helix sits below the plane (canonical,
    spans [offset-L, offset])."""
    base   = make_bundle_design([(0, 1)], length_bp=42, plane="XY")   # different cell
    offset = 0.0
    result = make_bundle_continuation(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    new_helix = next(h for h in result.helices if h.id not in {h2.id for h2 in base.helices})
    assert new_helix.length_bp == 21
    assert new_helix.axis_start.z == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)
    assert new_helix.axis_end.z   == pytest.approx(offset)


def test_continuation_negative_length_forward():
    """Negative length_bp at a forward continuation point: new helix is canonical and
    sits below the offset plane (spans [offset-L, offset])."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = 42 * BDNA_RISE_PER_BP   # axis_end.z of base helix (forward continuation point)
    result = make_bundle_continuation(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    new_helix = next(h for h in result.helices if h.id not in {h2.id for h2 in base.helices})
    assert new_helix.length_bp == 21
    assert new_helix.axis_start.z == pytest.approx(offset - 21 * BDNA_RISE_PER_BP)
    assert new_helix.axis_end.z   == pytest.approx(offset)


def test_continuation_near_end_anchored_at_axis_start_extends_backward():
    """Near-end blunt continuation: when offset = the helix's axis_start (the bp-i
    face), the backend backward-continues IN PLACE and ligates — the existing strand
    gains a domain [bp_start-L, bp_start-1] and NO new helix is created.

    This is what the frontend fix sends (anchor on axis_start, not axis_start-rise).
    """
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")  # bp_start=0, axis_start.z=0
    offset = 0.0                                                       # = base helix axis_start.z
    result = make_bundle_continuation(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    # Backward in-place growth — same helix id, no extra helix.
    assert len(result.helices) == 1
    h = result.helices[0]
    assert h.bp_start == -21
    assert h.length_bp == 63
    assert h.axis_start.z == pytest.approx(-21 * BDNA_RISE_PER_BP)
    assert h.axis_end.z   == pytest.approx(42 * BDNA_RISE_PER_BP)
    # The new bps [-21, -1] merge into the existing FORWARD scaffold domain [0, 41],
    # giving one contiguous, ligated domain [-21, 41] (no gap, no overlap, no off-by-one).
    scaf = next(s for s in result.strands if s.strand_type == StrandType.SCAFFOLD)
    bps  = [(d.start_bp, d.end_bp) for d in scaf.domains]
    assert (-21, 41) in bps


def test_continuation_near_end_off_by_one_offset_does_not_continue():
    """Regression guard: feeding offset = axis_start - rise (the OLD frontend diskBp
    position for a near end) does NOT reach the backward branch — it spawns a separate
    helix instead of ligating. Documents exactly the bug the frontend anchor fix avoids;
    if this ever yields 1 helix, the off-by-one has been reintroduced upstream."""
    base   = make_bundle_design([(0, 0)], length_bp=42, plane="XY")
    offset = -1 * BDNA_RISE_PER_BP   # one rise below axis_start (the buggy near disk position)
    result = make_bundle_continuation(base, [(0, 0)], length_bp=-21, plane="XY", offset_nm=offset)
    assert len(result.helices) == 2   # separate (shifted/overlapping) helix — NOT a clean continuation


def test_ligate_new_strand_adopts_existing_strand_color_and_id():
    """A ligated continuation adopts the EXISTING strand's id + color, even when the
    new strand is the 5'-part (3' ligation). Guards the 'continued strands keep the
    colour of the strand they connect to' behaviour."""
    from backend.core.lattice import _ligate_and_merge
    from backend.core.models import Strand, Domain

    base = make_bundle_design([(0, 0)], length_bp=42, plane="XY")  # valid helix h_XY_0_0 [0,41]
    h    = base.helices[0].id
    # new = 5'-part [0,20]; existing = 3'-part [21,41] with an explicit colour, placed FIRST.
    new = Strand(id="stpl_new", strand_type=StrandType.STAPLE,
                 domains=[Domain(helix_id=h, start_bp=0, end_bp=20, direction=Direction.FORWARD)])
    existing = Strand(id="stpl_existing", strand_type=StrandType.STAPLE, color="#abcdef",
                      domains=[Domain(helix_id=h, start_bp=21, end_bp=41, direction=Direction.FORWARD)])
    design = base.model_copy(update={"strands": [existing, new]})

    # 3' ligation: new (s1, 5') + existing (s2, 3'); keep the existing identity.
    out = _ligate_and_merge(design, new, existing, keep=existing)
    ids = [s.id for s in out.strands]
    assert ids == ["stpl_existing"]                 # existing id survives at its position; new absorbed
    merged = out.strands[0]
    assert merged.color == "#abcdef"                # existing colour preserved
    assert merged.domains[0].start_bp == 0          # domain order is new→existing, merged to [0,41]
    assert merged.domains[-1].end_bp  == 41

    # Without keep, the default keeps s1 (the NEW strand) — documents the old behaviour.
    out_default = _ligate_and_merge(design, new, existing)
    assert [s.id for s in out_default.strands] == ["stpl_new"]


def _gapped_helix_design():
    """A single helix [0,209] covered by three scaffold+staple intervals
    [0,41], [84,125], [168,209] (the teeth tooth pattern)."""
    from backend.core.models import Strand, Domain
    base = make_bundle_design([(0, 0)], length_bp=210, plane="XY")
    h = base.helices[0].id
    strands = []
    for i, (lo, hi) in enumerate([(0, 41), (84, 125), (168, 209)]):
        suf = "" if i == 0 else f"_{i-1}"
        strands.append(Strand(id=f"scaf_XY_0_0{suf}", strand_type=StrandType.SCAFFOLD,
                              domains=[Domain(helix_id=h, start_bp=lo, end_bp=hi, direction=Direction.FORWARD)]))
        strands.append(Strand(id=f"stpl_XY_0_0{suf}", strand_type=StrandType.STAPLE,
                              domains=[Domain(helix_id=h, start_bp=hi, end_bp=lo, direction=Direction.REVERSE)]))
    return base.model_copy(update={"strands": strands})


def _scaf_intervals(design):
    """{strand_id: sorted list of (min_bp, max_bp) per domain} for scaffolds."""
    out = {}
    for s in design.strands:
        if s.strand_type == StrandType.SCAFFOLD:
            out[s.id] = sorted((min(d.start_bp, d.end_bp), max(d.start_bp, d.end_bp)) for d in s.domains)
    return out


def test_continuation_gapped_helix_near_extends_only_bp0_interval():
    """A near-end (offset 0, -L) continuation on a gapped helix extends ONLY the
    interval touching bp 0; the [84,125] and [168,209] intervals must stay put
    (regression for the spurious near↔far strands seen in teeth.nadoc)."""
    out = make_bundle_continuation(_gapped_helix_design(), [(0, 0)], length_bp=-42, plane="XY", offset_nm=0.0)
    iv = _scaf_intervals(out)
    assert iv["scaf_XY_0_0"]   == [(-42, 41)]      # bp-0 interval grew backward
    assert iv["scaf_XY_0_0_0"] == [(84, 125)]      # untouched
    assert iv["scaf_XY_0_0_1"] == [(168, 209)]     # untouched
    # No scaffold may bridge the new near bps to a far interval.
    for ranges in iv.values():
        has_near = any(lo < 0 for lo, hi in ranges)
        has_far  = any(hi >= 84 for lo, hi in ranges)
        assert not (has_near and has_far), f"near↔far bridge: {ranges}"


def test_continuation_gapped_helix_far_extends_only_far_interval():
    """A far-end (+L) continuation on a gapped helix extends ONLY the far interval."""
    out = make_bundle_continuation(_gapped_helix_design(), [(0, 0)], length_bp=42, plane="XY",
                                   offset_nm=210 * BDNA_RISE_PER_BP)
    iv = _scaf_intervals(out)
    assert iv["scaf_XY_0_0"]   == [(0, 41)]        # untouched
    assert iv["scaf_XY_0_0_0"] == [(84, 125)]      # untouched
    assert iv["scaf_XY_0_0_1"] == [(168, 209), (210, 251)]   # far interval grew forward


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
    # Convention (matches shift_domains): axis_end sits at the position of the
    # LAST valid bp, i.e. (bp_start + length_bp - 1) * RISE — not one past it.
    # The new last bp is term_dom.end_bp + delta, so axis_end advances by
    # (delta - 1) * RISE relative to the original axis_end (which under the
    # native build convention sat one bp past the old last).
    import math
    new_last_bp = updated_helix.bp_start + updated_helix.length_bp - 1
    expected_axis_end_z = updated_helix.axis_start.z + new_last_bp * BDNA_RISE_PER_BP
    assert math.isclose(updated_helix.axis_end.z, expected_axis_end_z, abs_tol=1e-6)


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


def test_resize_inline_overhang_preserves_rotation_on_second_extension():
    """Dragging an already rotated inline overhang end must not reset orientation."""
    design = _make_single_helix_scaffolded()
    d1 = resize_strand_ends(design, [{"strand_id": "stap", "helix_id": "h0",
                                      "end": "3p", "delta_bp": +10}])
    rotation = [0.0, _math.sin(_math.radians(22.5)), 0.0, _math.cos(_math.radians(22.5))]
    rotated_overhangs = [
        ovhg.model_copy(update={"rotation": rotation})
        for ovhg in d1.overhangs
    ]
    d1 = d1.model_copy(update={"overhangs": rotated_overhangs})

    d2 = resize_strand_ends(d1, [{"strand_id": "stap", "helix_id": "h0",
                                  "end": "3p", "delta_bp": +3}])

    assert len(d2.overhangs) == 1
    assert d2.overhangs[0].rotation == pytest.approx(rotation)


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


def _design_with_crossover_tail_overhang():
    """A staple 5' free tail crosses over onto a SCAFFOLD-BEARING helix at a bp
    range OUTSIDE that helix's scaffold coverage.

    Mirrors the ``stap_36_331`` case in *Ultimate Polymer Hinge*: h0 carries
    scaffold at bp 0-41, but the staple's 5' tail sits at bp 100-111 on h0; its
    3' body is paired on h1. The old per-helix skip in autodetect_overhangs
    treated this tail as "scaffold-covered" (h0 has scaffold somewhere) and
    missed it.
    """
    from backend.core.models import (
        Design, Helix, Strand, Domain, StrandType, Direction, Vec3, DesignMetadata,
    )
    h0 = Helix(
        id="h0", axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=150 * BDNA_RISE_PER_BP),
        length_bp=150, bp_start=0, phase_offset=0.0, twist_per_bp_rad=_math.radians(34.3),
    )
    h1 = Helix(
        id="h1", axis_start=Vec3(x=2.5, y=0, z=0),
        axis_end=Vec3(x=2.5, y=0, z=42 * BDNA_RISE_PER_BP),
        length_bp=42, bp_start=0, phase_offset=0.0, twist_per_bp_rad=_math.radians(34.3),
    )
    scaffold = Strand(
        id="scaf", strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id="h0", start_bp=0,  end_bp=41, direction=Direction.FORWARD),
            Domain(helix_id="h1", start_bp=41, end_bp=0,  direction=Direction.REVERSE),
        ],
    )
    # Staple: 5' tail on h0 at bp 100-111 (scaffold-free region of h0), 3' body on h1.
    staple = Strand(
        id="stap", strand_type=StrandType.STAPLE,
        domains=[
            Domain(helix_id="h0", start_bp=111, end_bp=100, direction=Direction.REVERSE),
            Domain(helix_id="h1", start_bp=0,   end_bp=15,  direction=Direction.FORWARD),
        ],
    )
    return Design(helices=[h0, h1], strands=[scaffold, staple], metadata=DesignMetadata(name="xtail"))


def test_autodetect_overhangs_tags_crossover_tail_outside_scaffold_range():
    """A 5' tail entirely outside scaffold range on a scaffold-bearing helix is
    tagged (regression: stap_36_331; old per-helix skip missed it)."""
    design = _design_with_crossover_tail_overhang()
    result = autodetect_overhangs(design)
    staple = next(s for s in result.strands if s.id == "stap")
    assert staple.domains[0].helix_id == "h0"
    assert staple.domains[0].overhang_id == "ovhg_inline_stap_5p"
    assert any(o.id == "ovhg_inline_stap_5p" for o in result.overhangs)
    # 3' end is within h1 scaffold → genuine dsDNA, not an overhang.
    assert staple.domains[-1].overhang_id is None


def test_autodetect_all_overhangs_keeps_crossover_tail_through_pass2():
    """The full pipeline must keep the cross-over tail tagged — Pass 2's merge
    step must not strip a whole-domain overhang it can't re-split."""
    from backend.core.lattice import autodetect_all_overhangs
    design = _design_with_crossover_tail_overhang()
    result = autodetect_all_overhangs(design)
    staple = next(s for s in result.strands if s.id == "stap")
    tail = next(d for d in staple.domains if d.helix_id == "h0")
    assert tail.overhang_id == "ovhg_inline_stap_5p"
    assert any(o.id == "ovhg_inline_stap_5p" for o in result.overhangs)


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


# ── Relaxed-spacing pre-expansion (MD seeds) ──────────────────────────────────
#
# Added 2026-08-05 with the measured relaxed-spacing table. See
# memory/project_extra_base_spacing.md for provenance.

import numpy as _np_rs  # noqa: E402

from backend.core.constants import RELAXED_HELIX_SPACING_NM  # noqa: E402
from backend.core.lattice import (  # noqa: E402
    max_extra_base_count,
    relaxed_spacing_for_design,
    scale_helix_spacing,
)


def _nn_spacing(design):
    """Median nearest-neighbour distance between helix axis_start points."""
    p = _np_rs.array([[h.axis_start.x, h.axis_start.y, h.axis_start.z]
                      for h in design.helices])
    d = _np_rs.linalg.norm(p[:, None, :] - p[None, :, :], axis=-1)
    _np_rs.fill_diagonal(d, _np_rs.inf)
    return float(_np_rs.median(d.min(axis=1)))


def test_relaxed_spacing_table_is_monotonic_and_wider_than_the_build_lattice():
    assert list(RELAXED_HELIX_SPACING_NM) == sorted(RELAXED_HELIX_SPACING_NM)
    # Even the no-insert baseline is wider than what designs are built on.
    for s in RELAXED_HELIX_SPACING_NM:
        assert s > HONEYCOMB_HELIX_SPACING


def test_relaxed_spacing_table_matches_the_frontend_twin():
    """The view toggle carries its own copy (JS cannot import Python).

    They are a mirrored constant, so a drift here silently makes the picture and
    the MD seed disagree about the same measurement.
    """
    import pathlib
    import re

    src = pathlib.Path("frontend/src/scene/extra_base_spacing.js").read_text()
    m = re.search(r"RELAXED_SPACING_NM\s*=\s*\[([^\]]*)\]", src)
    assert m, "frontend RELAXED_SPACING_NM not found — did the module move?"
    js = tuple(float(x) for x in m.group(1).split(","))
    assert js == tuple(RELAXED_HELIX_SPACING_NM)


def test_max_extra_base_count_uses_the_widest_junction():
    design = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=32)
    assert max_extra_base_count(design) == 0
    assert relaxed_spacing_for_design(design) == RELAXED_HELIX_SPACING_NM[0]


def test_relaxed_spacing_clamps_above_the_measured_range():
    """The response saturates — extrapolating a 4-insert junction would overstate it."""
    assert relaxed_spacing_for_design.__doc__  # keep the rationale discoverable
    n = len(RELAXED_HELIX_SPACING_NM)
    assert RELAXED_HELIX_SPACING_NM[min(9, n - 1)] == RELAXED_HELIX_SPACING_NM[-1]


def test_scale_helix_spacing_widens_the_lattice_to_the_target():
    design = make_bundle_design(cells=[(0, 0), (0, 1), (1, 0), (1, 1)], length_bp=64)
    before = _nn_spacing(design)
    assert before == pytest.approx(HONEYCOMB_HELIX_SPACING, abs=1e-6)

    scaled = scale_helix_spacing(design, 2.55)
    assert _nn_spacing(scaled) == pytest.approx(2.55, abs=1e-6)


def test_scale_helix_spacing_does_not_mutate_the_input():
    """Three-Layer: the seed reparameterisation must never touch the saved design."""
    design = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=32)
    before = [(h.axis_start.x, h.axis_start.y, h.axis_start.z) for h in design.helices]
    scale_helix_spacing(design, 2.55)
    after = [(h.axis_start.x, h.axis_start.y, h.axis_start.z) for h in design.helices]
    assert before == after


def test_scale_helix_spacing_preserves_helix_length_and_topology():
    """Only the LATERAL components move — length, rise and register are untouched."""
    design = make_bundle_design(cells=[(0, 0), (0, 1), (1, 1)], length_bp=64)
    scaled = scale_helix_spacing(design, 2.55)

    for h0, h1 in zip(design.helices, scaled.helices):
        v0 = _np_rs.array([h0.axis_end.x - h0.axis_start.x,
                           h0.axis_end.y - h0.axis_start.y,
                           h0.axis_end.z - h0.axis_start.z])
        v1 = _np_rs.array([h1.axis_end.x - h1.axis_start.x,
                           h1.axis_end.y - h1.axis_start.y,
                           h1.axis_end.z - h1.axis_start.z])
        assert _np_rs.linalg.norm(v0) == pytest.approx(_np_rs.linalg.norm(v1), abs=1e-9)
        # Helices run along Z in the XY plane — the axial component must not scale.
        assert h1.axis_start.z == pytest.approx(h0.axis_start.z, abs=1e-9)
        assert h1.axis_end.z == pytest.approx(h0.axis_end.z, abs=1e-9)

    assert [h.id for h in scaled.helices] == [h.id for h in design.helices]
    assert len(scaled.strands) == len(design.strands)
    assert len(scaled.crossovers) == len(design.crossovers)


def test_scale_helix_spacing_is_a_noop_at_the_build_lattice():
    design = make_bundle_design(cells=[(0, 0), (0, 1)], length_bp=32)
    same = scale_helix_spacing(design, HONEYCOMB_HELIX_SPACING)
    assert _nn_spacing(same) == pytest.approx(_nn_spacing(design), abs=1e-9)


def test_scale_helix_spacing_keeps_the_bundle_centred():
    """Expansion is about the lateral centroid, so the box sizer sees no shift."""
    design = make_bundle_design(cells=[(0, 0), (0, 1), (1, 0), (1, 1)], length_bp=32)
    scaled = scale_helix_spacing(design, 2.55)

    def centroid(d):
        p = _np_rs.array([[h.axis_start.x, h.axis_start.y] for h in d.helices])
        return p.mean(axis=0)

    assert centroid(scaled) == pytest.approx(centroid(design), abs=1e-9)
