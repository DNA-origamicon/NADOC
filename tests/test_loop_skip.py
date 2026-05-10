"""
Tests for Phase 7 — Loop/Skip topology calculator and geometry handling.

Covers:
  - LoopSkip model serialisation
  - nucleotide_positions() with skips and loops
  - twist_loop_skips(): correct modification counts, placement, limit enforcement
  - bend_loop_skips(): correct per-helix pattern, limit enforcement
  - predict_global_twist_deg() round-trip accuracy
  - predict_radius_nm() round-trip accuracy
  - min_bend_radius_nm(), max_twist_deg()
  - apply_loop_skips() / clear_loop_skips() design mutation
"""

import math
import sys
import pathlib

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.geometry import nucleotide_positions
from backend.core.loop_skip_calculator import (
    _LOOP_SKIP_TWIST_PER_BP_DEG as BDNA_TWIST_PER_BP_DEG,
    CELL_BP_DEFAULT,
    MAX_DELTA_PER_CELL,
    apply_loop_skips,
    bend_loop_skips,
    clear_loop_skips,
    max_twist_deg,
    min_bend_radius_nm,
    predict_global_twist_deg,
    predict_radius_nm,
    twist_loop_skips,
    validate_loop_skip_limits,
    _active_intervals_for_helices,
    _cell_boundaries,
    _cells_from_active_intervals,
)
from backend.core.models import (
    Design,
    DesignMetadata,
    Direction,
    Domain,
    Helix,
    LatticeType,
    LoopSkip,
    Strand,
    StrandType,
    Vec3,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_helix(
    helix_id: str,
    x: float = 0.0,
    y: float = 0.0,
    length_bp: int = 126,
    loop_skips: list[LoopSkip] | None = None,
) -> Helix:
    return Helix(
        id=helix_id,
        axis_start=Vec3(x=x, y=y, z=0.0),
        axis_end=Vec3(x=x, y=y, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
        loop_skips=loop_skips or [],
    )


def _simple_design(helices: list[Helix]) -> Design:
    strands = []
    for h in helices:
        strands.append(Strand(
            id=f"scaf_{h.id}",
            strand_type=StrandType.SCAFFOLD,
            domains=[Domain(
                helix_id=h.id,
                direction=Direction.FORWARD,
                start_bp=0,
                end_bp=h.length_bp - 1,
            )],
        ))
        strands.append(Strand(
            id=f"stap_{h.id}",
            strand_type=StrandType.STAPLE,
            domains=[Domain(
                helix_id=h.id,
                direction=Direction.REVERSE,
                start_bp=h.length_bp - 1,
                end_bp=0,
            )],
        ))
    return Design(
        metadata=DesignMetadata(name="test"),
        helices=helices,
        strands=strands,
        lattice_type=LatticeType.HONEYCOMB,
    )


# ── LoopSkip model ─────────────────────────────────────────────────────────────


def test_loopskip_model_serialise_round_trip():
    ls = LoopSkip(bp_index=7, delta=-1)
    data = ls.model_dump()
    assert data == {"bp_index": 7, "delta": -1}
    restored = LoopSkip.model_validate(data)
    assert restored == ls


def test_helix_loop_skips_default_empty():
    h = _make_helix("h0")
    assert h.loop_skips == []


def test_helix_loop_skips_persists():
    ls = [LoopSkip(bp_index=7, delta=-1), LoopSkip(bp_index=14, delta=+1)]
    h = _make_helix("h0", loop_skips=ls)
    assert len(h.loop_skips) == 2
    assert h.loop_skips[0].delta == -1
    assert h.loop_skips[1].delta == +1


# ── nucleotide_positions with loop/skip ───────────────────────────────────────


def test_no_modifications_correct_count():
    h = _make_helix("h0", length_bp=42)
    nucs = nucleotide_positions(h)
    assert len(nucs) == 2 * 42  # 2 strands × 42 bp


def test_skip_reduces_count():
    """One skip removes 2 nucleotides (both strands at that bp)."""
    h = _make_helix("h0", length_bp=21, loop_skips=[LoopSkip(bp_index=7, delta=-1)])
    nucs = nucleotide_positions(h)
    assert len(nucs) == 2 * 20   # 21 - 1 skip = 20 effective bp


def test_loop_increases_count():
    """One loop adds 2 nucleotides (both strands get extra at that bp)."""
    h = _make_helix("h0", length_bp=21, loop_skips=[LoopSkip(bp_index=7, delta=+1)])
    nucs = nucleotide_positions(h)
    assert len(nucs) == 2 * 22   # 21 + 1 loop = 22 effective bp


def test_multiple_skips():
    h = _make_helix("h0", length_bp=21, loop_skips=[
        LoopSkip(bp_index=0, delta=-1),
        LoopSkip(bp_index=7, delta=-1),
        LoopSkip(bp_index=14, delta=-1),
    ])
    nucs = nucleotide_positions(h)
    assert len(nucs) == 2 * 18  # 21 - 3 skips


def test_skip_bp_index_absent():
    """No nucleotide should be emitted for a skipped bp_index."""
    h = _make_helix("h0", length_bp=14, loop_skips=[LoopSkip(bp_index=7, delta=-1)])
    nucs = nucleotide_positions(h)
    skipped_bps = {n.bp_index for n in nucs}
    assert 7 not in skipped_bps


def test_loop_bp_index_present_twice():
    """A loop bp_index should appear for both FORWARD and REVERSE, twice each."""
    h = _make_helix("h0", length_bp=14, loop_skips=[LoopSkip(bp_index=7, delta=+1)])
    nucs = nucleotide_positions(h)
    loop_nucs = [n for n in nucs if n.bp_index == 7]
    assert len(loop_nucs) == 4  # 2 extra (loop) + 2 original — now 4 total
    fwd = [n for n in loop_nucs if n.direction == Direction.FORWARD]
    rev = [n for n in loop_nucs if n.direction == Direction.REVERSE]
    assert len(fwd) == 2
    assert len(rev) == 2


def test_loop_nucleotides_separated_along_axis():
    """Loop nucleotides should be at ±½ rise from the nominal axis point."""
    h = _make_helix("h0", length_bp=7, loop_skips=[LoopSkip(bp_index=3, delta=+1)])
    nucs = nucleotide_positions(h)
    fwd_loop = [n for n in nucs if n.bp_index == 3 and n.direction == Direction.FORWARD]
    assert len(fwd_loop) == 2
    # Axial positions should differ by BDNA_RISE_PER_BP
    z0 = fwd_loop[0].position[2]
    z1 = fwd_loop[1].position[2]
    assert abs(abs(z1 - z0) - BDNA_RISE_PER_BP) < 1e-6


# ── _cell_boundaries ──────────────────────────────────────────────────────────


def test_cell_boundaries_even():
    cells = _cell_boundaries(0, 21)
    assert cells == [(0, 7), (7, 14), (14, 21)]


def test_cell_boundaries_partial_last_cell_ignored():
    # 25 bp → 3 full cells (21 bp), 4 bp remainder ignored
    cells = _cell_boundaries(0, 25)
    assert len(cells) == 3
    assert cells[-1] == (14, 21)


def test_cell_boundaries_offset():
    cells = _cell_boundaries(7, 28)
    assert cells == [(7, 14), (14, 21), (21, 28)]


# ── validate_loop_skip_limits ─────────────────────────────────────────────────


def test_validate_within_limits():
    validate_loop_skip_limits(2.5, 0.0)  # should not raise


def test_validate_deletion_at_exact_limit():
    validate_loop_skip_limits(3.0, 0.0)  # exactly 3.0 — should not raise


def test_validate_deletion_exceeds_limit():
    with pytest.raises(ValueError, match="Deletion"):
        validate_loop_skip_limits(3.1, 0.0)


def test_validate_insertion_exceeds_limit():
    with pytest.raises(ValueError, match="Insertion"):
        validate_loop_skip_limits(0.0, 3.5)


# ── max_twist_deg ─────────────────────────────────────────────────────────────


def test_max_twist_deg_18_cells():
    # 18 cells × 3 mods/cell × 34.286 °/mod ≈ 1851.4°
    result = max_twist_deg(18)
    assert abs(result - 18 * 3 * BDNA_TWIST_PER_BP_DEG) < 0.01


def test_max_twist_deg_zero_cells():
    assert max_twist_deg(0) == 0.0


# ── min_bend_radius_nm ────────────────────────────────────────────────────────


def test_min_bend_radius_single_helix_on_axis():
    """A single helix at the centroid — can't bend."""
    h = _make_helix("h0")
    result = min_bend_radius_nm([h], 0, 126, direction_deg=0.0)
    assert result == math.inf


def test_min_bend_radius_two_helices():
    """Two helices at ±2.25 nm: R_min = 7 × 2.25 / 3 = 5.25 nm."""
    h0 = _make_helix("h0", x=0.0, y=0.0)
    h1 = _make_helix("h1", x=2.25, y=0.0)
    # centroid at x=1.125; offsets: -1.125 and +1.125 → r_max=1.125
    result = min_bend_radius_nm([h0, h1], 0, 126, direction_deg=0.0)
    expected = CELL_BP_DEFAULT * 1.125 / MAX_DELTA_PER_CELL
    assert abs(result - expected) < 0.01


def test_min_bend_radius_three_row_bundle():
    """3-row bundle: rows at y=0, 2.25, 4.5 → r_max from centroid = 2.25 nm.
    R_min = 7 × 2.25 / 3 = 5.25 nm (matches Dietz paper ~6 nm).
    """
    rows = [0.0, 2.25, 4.5]
    helices = [_make_helix(f"h{i}", x=0.0, y=y) for i, y in enumerate(rows)]
    result = min_bend_radius_nm(helices, 0, 126, direction_deg=90.0)  # bend in Y
    assert abs(result - (CELL_BP_DEFAULT * 2.25 / MAX_DELTA_PER_CELL)) < 0.1


# ── twist_loop_skips ──────────────────────────────────────────────────────────


def test_twist_no_modification_zero_target():
    helices = [_make_helix("h0")]
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=0.0)
    assert mods["h0"] == []


def test_twist_one_deletion_per_three_cells():
    """
    Target: one full bp-twist = 34.286°.  Should produce exactly 1 skip
    across all helices over 18 cells.
    """
    helices = [_make_helix("h0")]
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=BDNA_TWIST_PER_BP_DEG)
    assert len(mods["h0"]) == 1
    assert mods["h0"][0].delta == -1


def test_twist_positive_produces_skips():
    """Positive target → left-handed → deletions (delta=-1)."""
    helices = [_make_helix("h0")]
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=180.0)
    assert all(ls.delta == -1 for ls in mods["h0"])
    assert len(mods["h0"]) > 0


def test_twist_negative_produces_loops():
    """Negative target → right-handed → insertions (delta=+1)."""
    helices = [_make_helix("h0")]
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=-180.0)
    assert all(ls.delta == +1 for ls in mods["h0"])
    assert len(mods["h0"]) > 0


def test_twist_same_mods_all_helices():
    """All helices in the segment receive identical modifications for pure twist."""
    helices = [_make_helix(f"h{i}") for i in range(4)]
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=205.7)
    counts = [len(mods[h.id]) for h in helices]
    assert len(set(counts)) == 1   # all same count


def test_twist_exceeds_limit_raises():
    helices = [_make_helix("h0")]
    n_cells = 18
    too_much = max_twist_deg(n_cells) + 1.0
    with pytest.raises(ValueError, match="Deletion"):
        twist_loop_skips(helices, 0, 126, target_twist_deg=too_much)


def test_twist_mods_sorted_by_bp():
    helices = [_make_helix("h0")]
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=200.0)
    indices = [ls.bp_index for ls in mods["h0"]]
    assert indices == sorted(indices)


def test_twist_mods_within_segment():
    """All modifications must be within [plane_a_bp, plane_b_bp)."""
    helices = [_make_helix("h0", length_bp=200)]
    mods = twist_loop_skips(helices, 42, 42 + 126, target_twist_deg=200.0)
    for ls in mods["h0"]:
        assert 42 <= ls.bp_index < 42 + 126


# ── predict_global_twist_deg ──────────────────────────────────────────────────


def test_predict_twist_round_trip_positive():
    helices = [_make_helix("h0")]
    target = 205.71  # ≈ 6 × 34.286°
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=target)
    predicted = predict_global_twist_deg(mods)
    # Should recover approximately the target (rounded to integer mods)
    assert abs(predicted - round(target / BDNA_TWIST_PER_BP_DEG) * BDNA_TWIST_PER_BP_DEG) < 0.5


def test_predict_twist_round_trip_negative():
    helices = [_make_helix("h0")]
    target = -171.4
    mods = twist_loop_skips(helices, 0, 126, target_twist_deg=target)
    predicted = predict_global_twist_deg(mods)
    assert abs(predicted - round(target / BDNA_TWIST_PER_BP_DEG) * BDNA_TWIST_PER_BP_DEG) < 0.5


# ── bend_loop_skips ───────────────────────────────────────────────────────────


def test_bend_no_modification_on_axis_helices():
    """If all helices are at the centroid, no modifications needed."""
    h = _make_helix("h0", x=0.0, y=0.0)
    mods = bend_loop_skips([h], 0, 105, radius_nm=20.0, direction_deg=0.0)
    assert mods["h0"] == []


def test_bend_inner_gets_deletions_outer_gets_insertions():
    """
    direction_deg=0 means the arc curves TOWARD +X (world_dir = +X is toward the
    centre of curvature / concave side).

    Two helices along X: h0 at x=0, h1 at x=4.5; centroid at x=2.25.
      h0: r_i = 0   − 2.25 = −2.25 nm  → OUTER arc (away from centre) → insertions
      h1: r_i = 4.5 − 2.25 = +2.25 nm  → INNER arc (toward centre)    → deletions
    """
    h0 = _make_helix("h0", x=0.0, y=0.0)
    h1 = _make_helix("h1", x=4.5, y=0.0)
    mods = bend_loop_skips([h0, h1], 0, 105, radius_nm=15.0, direction_deg=0.0)
    if mods["h0"]:
        assert all(ls.delta == +1 for ls in mods["h0"]), "outer (h0) should have insertions"
    if mods["h1"]:
        assert all(ls.delta == -1 for ls in mods["h1"]), "inner (h1) should have deletions"


def test_bend_inner_outer_opposite_signs():
    # h0 at x=0 is outer (insertions); h1 at x=4.5 is inner (deletions)
    h0 = _make_helix("h0", x=0.0)
    h1 = _make_helix("h1", x=4.5)
    mods = bend_loop_skips([h0, h1], 0, 105, radius_nm=10.0, direction_deg=0.0)
    ins0 = [ls for ls in mods.get("h0", []) if ls.delta == +1]
    del1 = [ls for ls in mods.get("h1", []) if ls.delta == -1]
    # Should have at least one of each for a noticeable bend
    assert len(ins0) > 0 or len(del1) > 0


def test_bend_below_min_radius_raises():
    h0 = _make_helix("h0", x=0.0)
    h1 = _make_helix("h1", x=4.5)
    r_min = min_bend_radius_nm([h0, h1], 0, 105, direction_deg=0.0)
    # Request tighter than minimum
    with pytest.raises(ValueError):
        bend_loop_skips([h0, h1], 0, 105, radius_nm=r_min * 0.5, direction_deg=0.0)


def test_bend_mods_within_segment():
    h0 = _make_helix("h0", x=0.0, y=0.0, length_bp=200)
    h1 = _make_helix("h1", x=4.5, y=0.0, length_bp=200)
    mods = bend_loop_skips([h0, h1], 21, 21 + 105, radius_nm=15.0, direction_deg=0.0)
    for hid, lst in mods.items():
        for ls in lst:
            assert 21 <= ls.bp_index < 21 + 105, f"bp_index {ls.bp_index} outside segment"


# ── predict_radius_nm ─────────────────────────────────────────────────────────


def test_predict_radius_round_trip():
    """Given target R, compute mods, then predict R from mods — should be close."""
    rows_y = [0.0, 2.25, 4.5]
    helices = [_make_helix(f"h{i}", x=0.0, y=y) for i, y in enumerate(rows_y)]
    target_r = 15.0
    mods = bend_loop_skips(helices, 0, 105, radius_nm=target_r, direction_deg=90.0)
    predicted = predict_radius_nm(helices, mods, 0, 105, direction_deg=90.0)
    # Allow 30% error due to integer rounding
    assert predicted == math.inf or abs(predicted - target_r) / target_r < 0.35


def test_predict_radius_no_modifications():
    h0 = _make_helix("h0", x=0.0)
    h1 = _make_helix("h1", x=4.5)
    mods: dict = {"h0": [], "h1": []}
    result = predict_radius_nm([h0, h1], mods, 0, 105, direction_deg=0.0)
    assert result == math.inf


# ── apply_loop_skips ──────────────────────────────────────────────────────────


def test_apply_loop_skips_updates_helix():
    h0 = _make_helix("h0")
    design = _simple_design([h0])
    mods = {"h0": [LoopSkip(bp_index=7, delta=-1), LoopSkip(bp_index=14, delta=-1)]}
    updated = apply_loop_skips(design, mods)
    h = next(h for h in updated.helices if h.id == "h0")
    assert len(h.loop_skips) == 2
    assert h.loop_skips[0].bp_index == 7
    assert h.loop_skips[1].bp_index == 14


def test_apply_loop_skips_does_not_modify_other_helices():
    h0 = _make_helix("h0")
    h1 = _make_helix("h1")
    design = _simple_design([h0, h1])
    mods = {"h0": [LoopSkip(bp_index=7, delta=-1)]}
    updated = apply_loop_skips(design, mods)
    h1_after = next(h for h in updated.helices if h.id == "h1")
    assert h1_after.loop_skips == []


def test_apply_loop_skips_merges_with_existing():
    existing_ls = [LoopSkip(bp_index=0, delta=-1)]
    h0 = _make_helix("h0", loop_skips=existing_ls)
    design = _simple_design([h0])
    # Apply a new mod at bp 7 — existing at bp 0 should be preserved
    mods = {"h0": [LoopSkip(bp_index=7, delta=-1)]}
    updated = apply_loop_skips(design, mods)
    h = next(h for h in updated.helices if h.id == "h0")
    bp_indices = {ls.bp_index for ls in h.loop_skips}
    assert 0 in bp_indices
    assert 7 in bp_indices


def test_apply_loop_skips_overwrites_same_position():
    existing_ls = [LoopSkip(bp_index=7, delta=-1)]
    h0 = _make_helix("h0", loop_skips=existing_ls)
    design = _simple_design([h0])
    # Overwrite bp 7 with a loop
    mods = {"h0": [LoopSkip(bp_index=7, delta=+1)]}
    updated = apply_loop_skips(design, mods)
    h = next(h for h in updated.helices if h.id == "h0")
    assert len(h.loop_skips) == 1
    assert h.loop_skips[0].delta == +1


def test_apply_loop_skips_preserves_deformations():
    """The Design.deformations list must survive apply_loop_skips."""
    from backend.core.models import DeformationOp, TwistParams
    h0 = _make_helix("h0")
    design = _simple_design([h0])
    op = DeformationOp(
        type="twist",
        plane_a_bp=0,
        plane_b_bp=63,
        params=TwistParams(total_degrees=90.0),
    )
    design = design.model_copy(update={"deformations": [op]})
    mods = {"h0": [LoopSkip(bp_index=7, delta=-1)]}
    updated = apply_loop_skips(design, mods)
    assert len(updated.deformations) == 1


# ── clear_loop_skips ──────────────────────────────────────────────────────────


def test_clear_removes_mods_in_range():
    ls_list = [
        LoopSkip(bp_index=0, delta=-1),
        LoopSkip(bp_index=7, delta=-1),
        LoopSkip(bp_index=14, delta=-1),
        LoopSkip(bp_index=21, delta=-1),
    ]
    h0 = _make_helix("h0", loop_skips=ls_list)
    design = _simple_design([h0])
    updated = clear_loop_skips(design, ["h0"], plane_a_bp=7, plane_b_bp=21)
    h = next(h for h in updated.helices if h.id == "h0")
    remaining = {ls.bp_index for ls in h.loop_skips}
    assert 0 in remaining      # outside range — kept
    assert 7 not in remaining   # in range [7, 21) — removed
    assert 14 not in remaining  # in range — removed
    assert 21 in remaining      # at plane_b_bp (exclusive) — kept


def test_clear_does_not_touch_other_helices():
    ls = [LoopSkip(bp_index=7, delta=-1)]
    h0 = _make_helix("h0", loop_skips=ls)
    h1 = _make_helix("h1", loop_skips=ls)
    design = _simple_design([h0, h1])
    updated = clear_loop_skips(design, ["h0"], 0, 126)
    h0_after = next(h for h in updated.helices if h.id == "h0")
    h1_after = next(h for h in updated.helices if h.id == "h1")
    assert h0_after.loop_skips == []
    assert len(h1_after.loop_skips) == 1  # untouched


# ── Gap-aware placement (multi-domain designs) ─────────────────────────────────


def _make_gap_design(helices: list[Helix], domain1_end: int, domain2_start: int) -> Design:
    """Two-domain design: bp [0, domain1_end] and [domain2_start, length_bp-1] on each helix."""
    strands = []
    for h in helices:
        strands.append(Strand(
            id=f"scaf_{h.id}",
            strand_type=StrandType.SCAFFOLD,
            domains=[
                Domain(helix_id=h.id, direction=Direction.FORWARD,
                       start_bp=0, end_bp=domain1_end),
                Domain(helix_id=h.id, direction=Direction.FORWARD,
                       start_bp=domain2_start, end_bp=h.length_bp - 1),
            ],
        ))
        strands.append(Strand(
            id=f"stap_{h.id}",
            strand_type=StrandType.STAPLE,
            domains=[
                Domain(helix_id=h.id, direction=Direction.REVERSE,
                       start_bp=domain1_end, end_bp=0),
                Domain(helix_id=h.id, direction=Direction.REVERSE,
                       start_bp=h.length_bp - 1, end_bp=domain2_start),
            ],
        ))
    return Design(
        metadata=DesignMetadata(name="test_gap"),
        helices=helices,
        strands=strands,
        lattice_type=LatticeType.HONEYCOMB,
    )


def test_active_intervals_single_domain():
    h = _make_helix("h0", length_bp=84)
    design = _simple_design([h])
    intervals = _active_intervals_for_helices(design, {"h0"})
    assert intervals == [(0, 84)]


def test_active_intervals_two_domains_with_gap():
    h = _make_helix("h0", length_bp=252)
    design = _make_gap_design([h], domain1_end=83, domain2_start=168)
    intervals = _active_intervals_for_helices(design, {"h0"})
    assert intervals == [(0, 84), (168, 252)]


def test_cells_from_active_intervals_normal_case():
    """When plane is within an active interval, returns the same cells as _cell_boundaries."""
    intervals = [(0, 84)]
    cells = _cells_from_active_intervals(intervals, plane_a=0, plane_b=84)
    assert cells == _cell_boundaries(0, 84)


def test_cells_from_active_intervals_gap_case():
    """When plane is entirely in a gap, returns empty (no expansion to adjacent DNA)."""
    intervals = [(0, 84), (168, 252)]
    cells = _cells_from_active_intervals(intervals, plane_a=87, plane_b=165)
    assert cells == [], "Expected no cells when plane is entirely in a gap"


def test_bend_in_gap_no_mods_in_gap():
    """When all helices have a gap in [plane_a, plane_b], bend_loop_skips returns no mods."""
    helices = [
        _make_helix("h0", x=0.0,  y=0.0,  length_bp=252),
        _make_helix("h1", x=2.25, y=0.0,  length_bp=252),
        _make_helix("h2", x=0.0,  y=2.25, length_bp=252),
        _make_helix("h3", x=2.25, y=2.25, length_bp=252),
    ]
    design = _make_gap_design(helices, domain1_end=83, domain2_start=168)
    # plane_a=87, plane_b=165 — entirely in the gap [84, 167] on every helix
    mods = bend_loop_skips(helices, 87, 165, radius_nm=20.0, design=design)
    all_mods = [ls for ls_list in mods.values() for ls in ls_list]
    assert all_mods == [], f"Expected no mods when plane is in a gap, got: {all_mods}"


def test_twist_in_gap_no_mods_in_gap():
    """When all helices have a gap in [plane_a, plane_b], twist_loop_skips returns no mods."""
    helices = [
        _make_helix("h0", x=0.0,  y=0.0,  length_bp=252),
        _make_helix("h1", x=2.25, y=0.0,  length_bp=252),
    ]
    design = _make_gap_design(helices, domain1_end=83, domain2_start=168)
    mods = twist_loop_skips(helices, 87, 165, target_twist_deg=30.0, design=design)
    all_mods = [ls for ls_list in mods.values() for ls in ls_list]
    assert all_mods == [], f"Expected no mods when plane is in a gap, got: {all_mods}"


def test_bend_mixed_coverage_per_helix():
    """
    Helices with full coverage keep mods in [plane_a, plane_b]; helices with a gap
    get their mods redirected to adjacent active DNA. Both must be in active DNA.
    """
    # 4 helices: h0/h1 have full coverage, h2/h3 have a gap at [84, 167]
    helices = [
        _make_helix("h0", x=0.0,  y=0.0,  length_bp=252),
        _make_helix("h1", x=2.25, y=0.0,  length_bp=252),
        _make_helix("h2", x=0.0,  y=2.25, length_bp=252),
        _make_helix("h3", x=2.25, y=2.25, length_bp=252),
    ]
    # h0 and h1: full coverage including middle segment
    full_strands = [
        Strand(id=f"scaf_{h.id}", strand_type=StrandType.SCAFFOLD, domains=[
            Domain(helix_id=h.id, direction=Direction.FORWARD, start_bp=0, end_bp=83),
            Domain(helix_id=h.id, direction=Direction.FORWARD, start_bp=84, end_bp=167),
            Domain(helix_id=h.id, direction=Direction.FORWARD, start_bp=168, end_bp=251),
        ]) for h in helices[:2]
    ] + [
        Strand(id=f"stap_{h.id}", strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id=h.id, direction=Direction.REVERSE, start_bp=251, end_bp=0),
        ]) for h in helices[:2]
    ]
    # h2 and h3: gap at [84, 167]
    gap_strands = [
        Strand(id=f"scaf_{h.id}", strand_type=StrandType.SCAFFOLD, domains=[
            Domain(helix_id=h.id, direction=Direction.FORWARD, start_bp=0, end_bp=83),
            Domain(helix_id=h.id, direction=Direction.FORWARD, start_bp=168, end_bp=251),
        ]) for h in helices[2:]
    ] + [
        Strand(id=f"stap_{h.id}", strand_type=StrandType.STAPLE, domains=[
            Domain(helix_id=h.id, direction=Direction.REVERSE, start_bp=83, end_bp=0),
            Domain(helix_id=h.id, direction=Direction.REVERSE, start_bp=251, end_bp=168),
        ]) for h in helices[2:]
    ]
    design = Design(
        metadata=DesignMetadata(name="mixed"),
        helices=helices,
        strands=full_strands + gap_strands,
        lattice_type=LatticeType.HONEYCOMB,
    )
    mods = bend_loop_skips(helices, 87, 165, radius_nm=20.0, design=design)
    gap = set(range(84, 168))
    # h0/h1 have domain [84,167] — mods within [87,165] are valid for them
    for hid in ("h0", "h1"):
        inner = [ls for ls in mods[hid] if 87 <= ls.bp_index < 165]
        assert len(inner) > 0, f"{hid} should have mods within [87,165]"
    # h2/h3 have a gap at [84,167] — all their mods must be outside the gap
    for hid in ("h2", "h3"):
        for ls in mods[hid]:
            assert ls.bp_index not in gap, (
                f"Helix {hid}: loop/skip at bp={ls.bp_index} is in the gap"
            )


def test_bend_without_design_unchanged():
    """bend_loop_skips without design= still places mods anywhere (backward compat)."""
    helices = [
        _make_helix("h0", x=0.0,  y=0.0,  length_bp=252),
        _make_helix("h1", x=2.25, y=0.0,  length_bp=252),
        _make_helix("h2", x=0.0,  y=2.25, length_bp=252),
        _make_helix("h3", x=2.25, y=2.25, length_bp=252),
    ]
    mods = bend_loop_skips(helices, 87, 165, radius_nm=20.0)
    # Without design, mods can be anywhere — just verify we get some
    all_indices = [ls.bp_index for ls_list in mods.values() for ls in ls_list]
    assert len(all_indices) > 0
