"""Validation tests for placing a primitive onto a design.

A primitive's cross-section is dropped as an additive ``bundle-segment`` whose
footprint cells are the primitive's, translated so the anchor helix lands on the
chosen lattice cell. Two things must hold:

1. **General addition** — the placement builds the right footprint, is recorded as a
   revertable feature-log entry, and is additive (existing DNA untouched).
2. **Shape preservation under allowed snaps** — on honeycomb, the placement only
   preserves the primitive's physical cross-section AND per-helix scaffold polarity
   when the shift ``dRow+dCol`` is even (matching anchor parity). The frontend only
   *offers* such snaps; these tests pin the geometric contract that makes that the
   right rule, and demonstrate the distortion an odd shift would cause.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import (
    honeycomb_position,
    make_bundle_design,
    make_bundle_segment,
    scaffold_direction_for_cell,
)
from backend.core.models import Design
from backend.core.primitive_catalog import derive_placement_spec

client = TestClient(app)

# 6hb closed-ring footprint + anchor, from the real primitive design.
SIX_HB = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
SIX_HB_ANCHOR = (0, 1)
_PRIMITIVE_6HB = Path("workspace/Primitives/6hb_primitive.nadoc")

# 6hb_primitive.nadoc is a hand-built reference design under workspace/, not checked
# into the repo — skip the test that reads it when absent (fresh clone / CI / second
# computer) instead of erroring with FileNotFoundError.
_skip_if_no_6hb = pytest.mark.skipif(
    not _PRIMITIVE_6HB.exists(),
    reason=f"primitive fixture missing: {_PRIMITIVE_6HB} (hand-built, not in repo)",
)


@pytest.fixture(autouse=True)
def reset_state():
    yield
    design_state.close_session()


def _translate(cells, anchor, dst):
    drow, dcol = dst[0] - anchor[0], dst[1] - anchor[1]
    return [(r + drow, c + dcol) for r, c in cells]


def _rel_shape(cells):
    """Relative XY geometry of a footprint, anchored at its first cell (rounded)."""
    x0, y0 = honeycomb_position(*cells[0])
    return [(round(honeycomb_position(r, c)[0] - x0, 4),
             round(honeycomb_position(r, c)[1] - y0, 4)) for r, c in cells]


def _directions(cells):
    return [scaffold_direction_for_cell(r, c).value for r, c in cells]


# ── 1. General primitive-addition validation ──────────────────────────────────

@_skip_if_no_6hb
def test_derive_placement_spec_matches_real_6hb_primitive():
    design = json.loads(_PRIMITIVE_6HB.read_text())
    spec = derive_placement_spec(design)
    assert [tuple(c) for c in spec["cells"]] == SIX_HB
    assert tuple(spec["anchor_cell"]) == SIX_HB_ANCHOR
    assert spec["length_bp"] == 42
    assert spec["lattice"] == "HONEYCOMB"


def test_place_primitive_into_empty_builds_footprint_and_is_revertable():
    """Placing the 6hb primitive onto an empty design via the segment route builds
    all 6 helices at the (translated) footprint and leaves a revertable log entry."""
    design_state.set_design(Design())   # empty workspace
    cells = _translate(SIX_HB, SIX_HB_ANCHOR, (2, 3))   # even shift (allowed)
    r = client.post("/api/design/bundle-segment", json={
        "cells": [list(c) for c in cells], "length_bp": 42, "plane": "XY",
        "strand_filter": "both", "ligate_adjacent": True,
    })
    assert r.status_code == 201
    d = design_state.get_or_404()
    assert {tuple(h.grid_pos) for h in d.helices} == set(cells)
    assert len(d.feature_log) == 1
    assert d.feature_log[-1].op_kind == "extrude-segment"

    # Revert removes the placement entirely → back to the empty workspace.
    rv = client.post("/api/design/features/0/revert")
    assert rv.status_code == 200
    assert design_state.get_or_404().helices == []


def test_place_primitive_is_additive_over_existing_dna():
    """A primitive dropped onto a populated design adds to it (existing helix kept)."""
    base = make_bundle_design([(0, 0)], length_bp=42)
    design_state.set_design(base)
    cells = _translate(SIX_HB, SIX_HB_ANCHOR, (4, 5))   # away from (0,0), even shift
    r = client.post("/api/design/bundle-segment", json={
        "cells": [list(c) for c in cells], "length_bp": 42, "plane": "XY",
    })
    assert r.status_code == 201
    grid = {tuple(h.grid_pos) for h in design_state.get_or_404().helices}
    assert (0, 0) in grid                       # original untouched
    assert set(cells).issubset(grid)            # primitive added
    assert len(grid) == 1 + len(cells)


# ── 2. Shape preservation under allowed (even) snaps ───────────────────────────

@pytest.mark.parametrize("dst", [(0, 1), (2, 1), (0, 3), (2, 3), (1, 2)])  # all even shifts
def test_allowed_even_shift_preserves_cross_section_and_polarity(dst):
    placed = _translate(SIX_HB, SIX_HB_ANCHOR, dst)
    assert _rel_shape(placed) == _rel_shape(SIX_HB)          # congruent geometry
    assert _directions(placed) == _directions(SIX_HB)        # per-helix scaffold polarity preserved


@pytest.mark.parametrize("dst", [(0, 2), (1, 1), (0, 0), (2, 0)])  # odd shifts (hover parity ≠ anchor)
def test_forbidden_odd_shift_distorts_shape_and_flips_polarity(dst):
    placed = _translate(SIX_HB, SIX_HB_ANCHOR, dst)
    assert _rel_shape(placed) != _rel_shape(SIX_HB)          # geometry distorted (the "I")
    assert _directions(placed) == [_flip(d) for d in _directions(SIX_HB)]   # every polarity flipped


def _flip(direction: str) -> str:
    return "REVERSE" if direction == "FORWARD" else "FORWARD"


def test_built_segment_geometry_matches_predicted_shape_for_allowed_shift():
    """End-to-end: the helices an even-shifted placement actually builds are congruent
    to the primitive's cross-section (proves the snap rule lines up with make_bundle_segment)."""
    placed = _translate(SIX_HB, SIX_HB_ANCHOR, (2, 3))
    design = make_bundle_segment(Design(), placed, length_bp=42, plane="XY")
    by_cell = {tuple(h.grid_pos): h for h in design.helices}
    built = [(by_cell[c].axis_start.x, by_cell[c].axis_start.y) for c in placed]
    x0, y0 = built[0]
    built_rel = [(round(x - x0, 4), round(y - y0, 4)) for x, y in built]   # subtract raw, round once
    assert built_rel == _rel_shape(SIX_HB)
