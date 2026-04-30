"""Tests for backend/core/seamless_router.py"""
from __future__ import annotations

import pathlib

import pytest

from backend.core.lattice import make_bundle_design
from backend.core.models import Design, Direction, LatticeType, StrandType
from backend.core.seamless_router import SeamlessResult, auto_scaffold_seamless

FIXTURES = pathlib.Path(__file__).parent / "fixtures"

# ── Cell layouts ──────────────────────────────────────────────────────────────

CELLS_2HB = [(0, 0), (0, 1)]
CELLS_4HB = [(0, 0), (0, 1), (0, 2), (0, 3)]
CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]
CELLS_4SQ = [(0, 0), (0, 1), (1, 0), (1, 1)]


def _scaf_strands(design: Design):
    return [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]


def _make_two_group_design() -> Design:
    """4HB HC where (0,0)/(0,1) have scaffold [0,41] and (0,2)/(0,3) have [0,83].

    Two coverage-signature groups force a bridge HJ between them.
    """
    base = make_bundle_design(CELLS_4HB, length_bp=84)
    arm_ids = {h.id for h in base.helices if h.grid_pos in [(0, 0), (0, 1)]}
    new_strands = []
    for s in base.strands:
        if s.strand_type == StrandType.SCAFFOLD and s.domains[0].helix_id in arm_ids:
            dom = s.domains[0]
            if dom.direction == Direction.FORWARD:
                new_dom = dom.model_copy(update={"end_bp": 41})
            else:
                new_dom = dom.model_copy(update={"start_bp": 41})
            new_strands.append(s.model_copy(update={"domains": [new_dom]}))
        else:
            new_strands.append(s)
    return base.copy_with(strands=new_strands)


# ── Single-section crossover count tests ──────────────────────────────────────

def test_seamless_2hb_hc():
    design = make_bundle_design(CELLS_2HB, length_bp=42)
    updated, result = auto_scaffold_seamless(design)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 1
    assert result.bridge_xovers == 0


def test_seamless_4hb_hc():
    design = make_bundle_design(CELLS_4HB, length_bp=84)
    updated, result = auto_scaffold_seamless(design)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 3
    assert result.bridge_xovers == 0


def test_seamless_6hb_hc():
    design = make_bundle_design(CELLS_6HB, length_bp=84)
    updated, result = auto_scaffold_seamless(design)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 5
    assert result.bridge_xovers == 0


def test_seamless_4hb_sq():
    design = make_bundle_design(CELLS_4SQ, length_bp=32, lattice_type=LatticeType.SQUARE)
    updated, result = auto_scaffold_seamless(design)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 3
    assert result.bridge_xovers == 0


# ── Structural invariant tests ────────────────────────────────────────────────

def test_scaffold_visits_each_helix_at_most_twice():
    """Each helix should have at most 2 seamless crossovers (in + out).

    Bridge helices may have 4 (in + out for each section's zig-zag) — not
    counted here since the single-section 4HB has no bridges.
    """
    design = make_bundle_design(CELLS_4HB, length_bp=84)
    updated, result = auto_scaffold_seamless(design)

    xover_count: dict[str, int] = {}
    for xo in updated.crossovers:
        for hid in (xo.half_a.helix_id, xo.half_b.helix_id):
            xover_count[hid] = xover_count.get(hid, 0) + 1

    for hid, count in xover_count.items():
        assert count <= 2, (
            f"Helix {hid} has {count} crossovers; expected ≤2 in a single-section design."
        )


def test_scaffold_is_linear():
    """No scaffold strand should wrap around (circular) after seamless routing."""
    design = make_bundle_design(CELLS_6HB, length_bp=84)
    updated, _ = auto_scaffold_seamless(design)
    for s in _scaf_strands(updated):
        if len(s.domains) > 1:
            first, last = s.domains[0], s.domains[-1]
            assert not (
                first.helix_id == last.helix_id and first.start_bp == last.end_bp
            ), f"Circular scaffold strand detected: {s.id}"


def test_total_crossover_count_2hb():
    """2HB: exactly 1 scaffold crossover total in design."""
    design = make_bundle_design(CELLS_2HB, length_bp=42)
    updated, _ = auto_scaffold_seamless(design)
    scaf_xovers = [
        xo for xo in updated.crossovers
        if xo.process_id and "seamless" in xo.process_id
    ]
    assert len(scaf_xovers) == 1


def test_total_crossover_count_6hb():
    """6HB: exactly 5 scaffold crossovers total in design."""
    design = make_bundle_design(CELLS_6HB, length_bp=84)
    updated, _ = auto_scaffold_seamless(design)
    scaf_xovers = [
        xo for xo in updated.crossovers
        if xo.process_id and "seamless" in xo.process_id
    ]
    assert len(scaf_xovers) == 5


# ── Multi-section test ────────────────────────────────────────────────────────

def test_two_group_design_has_bridge_xovers():
    """2-group design: bridge HJ placed, all helices touched by a crossover."""
    design = _make_two_group_design()
    updated, result = auto_scaffold_seamless(design)
    assert result.bridge_xovers > 0, "Expected bridge crossovers for 2-group design"
    assert result.end_xovers > 0, "Expected zig-zag crossovers for 2-group design"

    all_hids = {h.id for h in updated.helices}
    touched = set()
    for xo in updated.crossovers:
        touched.add(xo.half_a.helix_id)
        touched.add(xo.half_b.helix_id)
    assert touched == all_hids, (
        f"These helices had no crossovers: {all_hids - touched}"
    )


def test_teeth_closing_zig():
    """teeth.nadoc: closing zig across tooth tips (h_XY_2_2 ↔ h_XY_2_3) enabled
    by bridge HJ breaking circularity → exactly 4 scaffold strands."""
    design = Design.model_validate_json(
        (FIXTURES / "teeth.nadoc").read_text()
    )
    design = design.copy_with(crossovers=[])
    updated, result = auto_scaffold_seamless(design)

    assert not result.warnings, result.warnings
    assert result.bridge_xovers == 6, f"Expected 6 bridge xovers, got {result.bridge_xovers}"

    scaf_strands = _scaf_strands(updated)
    assert len(scaf_strands) == 4, (
        f"Expected 4 scaffold strands, got {len(scaf_strands)}"
    )
