"""Headless (mouse-free) design construction — backend/api/headless_build.py.

These pin the two properties that make the module worth having over a direct
core-builder call: (1) builds carry a real, replayable feature log identical to
the UI's, and (2) a one-shot build is isolated — it never disturbs the active
document or its undo history.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

import backend.api.doc_context as dc
from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.lattice import overhang_candidate_error
from backend.core.models import LatticeType
from tests.conftest import SIX_HB_CELLS, TEETH_CELLS, TEETH_PASSES


def _staple_termini(d):
    """(helix_id, bp, direction, is_five_prime) for every staple 5′ and 3′ end."""
    out = []
    for s in d.strands:
        if not str(s.strand_type).upper().endswith("STAPLE"):
            continue
        first, last = s.domains[0], s.domains[-1]
        out.append((first.helix_id, first.start_bp, first.direction, True))
        out.append((last.helix_id, last.end_bp, last.direction, False))
    return out


def _hc_neighbors(r, c):
    offs = [(-1, 0), (0, -1), (0, 1)] if (r + c) % 2 == 0 else [(0, -1), (0, 1), (1, 0)]
    return [(r + dr, c + dc) for dr, dc in offs]


def test_build_bundle_records_feature_log():
    """teeth = one bundle-create + five extrude-continuation entries, in order."""
    d = hb.build_bundle(
        TEETH_CELLS, 42, lattice=LatticeType.SQUARE, name="teeth", passes=TEETH_PASSES,
    )
    assert [e.op_kind for e in d.feature_log] == (
        ["bundle-create"] + ["extrude-continuation"] * len(TEETH_PASSES)
    )
    # The extrude params are the replayable record: offsets are i × len × rise.
    offsets = [e.params.get("offset_nm") for e in d.feature_log[1:]]
    assert offsets == [14.028, 28.056, 42.084, 56.112, 70.14]


def test_single_create_has_one_entry():
    d = hb.build_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
    assert len(d.feature_log) == 1
    assert d.feature_log[0].op_kind == "bundle-create"
    assert len(d.helices) == 6


def test_extrude_segment_appends_fresh_disconnected_helices():
    """The segment mode (the slice tool's "append a fresh segment", distinct from
    continuation) adds NEW helices at fresh cells and logs ``extrude-segment`` — the
    headless equivalent of the sidebar's segment extrude, so an agent can build
    multi-segment structures programmatically."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        far = [(r + 20, c) for r, c in SIX_HB_CELLS]   # fresh cells, well clear of the bundle
        d = hb.extrude_segment(far, 42, offset_nm=0.0)
        assert len(d.helices) == 12                    # 6 original + 6 fresh
        assert {h.grid_pos for h in d.helices} == set(SIX_HB_CELLS) | set(far)
        assert d.feature_log[-1].op_kind == "extrude-segment"


def test_build_on_non_default_plane():
    """The plane is a first-class build parameter (the sidebar's "Extrude from"
    dropdown → XY/XZ/YZ).  A build on XZ produces XZ-keyed helices, confirming the
    programmatic surface can target any origin plane, not just the XY default."""
    d = hb.build_bundle(
        SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, plane="XZ", name="6hb-xz",
    )
    assert len(d.helices) == 6
    assert all(h.id.startswith("h_XZ_") for h in d.helices)


def test_build_bundle_does_not_disturb_default_document():
    """A one-shot build runs in a throwaway doc and cleans up after itself."""
    before = design_state.peek_design(dc.DEFAULT_DOC_ID)
    hb.build_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB)
    after = design_state.peek_design(dc.DEFAULT_DOC_ID)
    assert after is before  # default session object identity unchanged
    # No scratch sessions leaked into the registry.
    assert not any(doc.startswith("__headless_build_") for doc in design_state.list_doc_ids())


# ── Auto-op wrappers: scaffold routing → crossovers → staple breaking ──────────────

def test_auto_op_chain_routes_a_full_18hb():
    """create_bundle → auto_scaffold → auto_crossover → auto_break composes into a
    fully-routed precursor, recording each op in the feature log."""
    from tests.conftest import EIGHTEEN_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(EIGHTEEN_HB_CELLS, 388, lattice=LatticeType.HONEYCOMB, name="18hb")
        d = hb.auto_scaffold(seamless=False)
        scaffold = [s for s in d.strands if str(s.strand_type).upper().endswith("SCAFFOLD")]
        assert len(scaffold) == 1  # routed to a single strand

        d = hb.auto_crossover()
        assert len(d.crossovers) > 0

        d = hb.auto_break()
        assert [e.op_kind for e in d.feature_log] == [
            "bundle-create", "auto-scaffold-seamed", "auto-crossover", "auto-break",
        ]


def test_overhang_extrude_places_a_valid_candidate():
    """A routed 6hb has valid overhang candidates; extruding into one adds an
    overhang + helix and logs the op.  Cells the UI tool would not offer are
    skipped (the endpoint rejects them — see the rejection test below)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        d = hb.auto_break()
        hobj = {h.id: h for h in d.helices}
        occ = {h.grid_pos for h in d.helices}
        placed = None
        for hid, bp, dirn, is5 in _staple_termini(d):
            r, c = hobj[hid].grid_pos
            for nr, nc in _hc_neighbors(r, c):
                if (nr, nc) in occ:
                    continue
                try:
                    placed = hb.overhang_extrude(
                        hid, bp, direction=dirn, is_five_prime=is5,
                        neighbor_row=nr, neighbor_col=nc, length_bp=8,
                    )
                except HTTPException:
                    continue  # gate rejected this cell — try the next
                break
            if placed is not None:
                break
        assert placed is not None
        assert len(placed.overhangs) == 1
        assert placed.feature_log[-1].op_kind == "overhang-extrude"


def test_overhang_extrude_rejects_a_non_candidate_placement():
    """The endpoint gate rejects a placement the UI tool would not offer (backbone
    bead faces away from the target cell) with HTTP 400 — so headless / direct-API
    generation can't create overhangs at invalid positions."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        d = hb.auto_break()
        hobj = {h.id: h for h in d.helices}
        occ = {h.grid_pos for h in d.helices}
        bad = None
        for hid, bp, dirn, is5 in _staple_termini(d):
            r, c = hobj[hid].grid_pos
            for nr, nc in _hc_neighbors(r, c):
                if (nr, nc) in occ:
                    continue
                if overhang_candidate_error(d, hobj[hid], bp, dirn, nr, nc) is not None:
                    bad = (hid, bp, dirn, is5, nr, nc)
                    break
            if bad is not None:
                break
        assert bad is not None, "expected at least one non-candidate site on a routed 6hb"
        hid, bp, dirn, is5, nr, nc = bad
        with pytest.raises(HTTPException) as exc:
            hb.overhang_extrude(
                hid, bp, direction=dirn, is_five_prime=is5,
                neighbor_row=nr, neighbor_col=nc, length_bp=8,
            )
        assert exc.value.status_code == 400


def test_adjacent_nick_overhangs_are_independently_placeable():
    """Regression: placing a short overhang must NOT suppress the candidate one bp
    beyond it (its nick-pair sibling).  The helix axis end-cap — one base-rise past
    the last nucleotide — was wrongly counted as occupying the cell, so the sibling's
    arrow/candidate vanished.  Both must stay placeable and share the cell's helix."""
    from backend.core.validator import validate_design

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        hb.auto_merge()
        d = design_state.get_or_404()
        hobj = {h.id: h for h in d.helices}
        ring = set(SIX_HB_CELLS)

        # Find a nick pair: two staple ends at adjacent bps on one main helix, both
        # facing the same vacant cell.
        facing = {}
        for hid, bp, dirn, is5 in _staple_termini(d):
            if hobj[hid].grid_pos not in ring:
                continue
            for nr, nc in _hc_neighbors(*hobj[hid].grid_pos):
                if (nr, nc) in ring:
                    continue
                if overhang_candidate_error(d, hobj[hid], bp, dirn, nr, nc) is None:
                    facing.setdefault((hid, (nr, nc)), []).append((bp, dirn, is5))
        pair = None
        for (hid, cell), lst in facing.items():
            ends = sorted(lst)
            for i in range(len(ends) - 1):
                if ends[i + 1][0] == ends[i][0] + 1:
                    pair = (hid, cell, ends[i], ends[i + 1])
                    break
            if pair:
                break
        assert pair is not None, "expected an adjacent nick pair facing one cell on a routed 6hb"
        hid, (nr, nc), (bp_a, dir_a, is5_a), (bp_b, dir_b, is5_b) = pair

        hb.overhang_extrude(hid, bp_a, direction=dir_a, is_five_prime=is5_a,
                            neighbor_row=nr, neighbor_col=nc, length_bp=8)
        d = design_state.get_or_404()
        h_after = {h.id: h for h in d.helices}[hid]
        # The sibling one bp away must REMAIN a candidate (this was the bug).
        assert overhang_candidate_error(d, h_after, bp_b, dir_b, nr, nc) is None
        # And it must actually place — sharing the cell's helix — with valid topology.
        hb.overhang_extrude(hid, bp_b, direction=dir_b, is_five_prime=is5_b,
                            neighbor_row=nr, neighbor_col=nc, length_bp=8)
        d = design_state.get_or_404()
        cell_of = {h.id: h.grid_pos for h in d.helices}
        assert sum(1 for o in d.overhangs if cell_of[o.helix_id] == (nr, nc)) == 2
        assert all(r.ok for r in validate_design(d).results)


def test_fill_all_overhang_candidates_saturates_and_stays_valid():
    """Filling every main-bundle overhang candidate (re-scanning until none remain)
    yields a valid design with overhangs STACKED along Z (more than one per cell) and
    zero candidates left — the fill-until-saturated behaviour the full-auto demo uses."""
    from backend.core.validator import validate_design

    ring = set(SIX_HB_CELLS)
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        hb.auto_merge()

        placed = 0
        while True:
            d = design_state.get_or_404()
            hobj = {h.id: h for h in d.helices}
            progressed = False
            for hid, bp, dirn, is5 in _staple_termini(d):
                if hobj[hid].grid_pos not in ring:
                    continue  # only extrude FROM the main bundle, not overhang tips
                for nr, nc in _hc_neighbors(*hobj[hid].grid_pos):
                    if (nr, nc) in ring:
                        continue
                    try:
                        hb.overhang_extrude(hid, bp, direction=dirn, is_five_prime=is5,
                                            neighbor_row=nr, neighbor_col=nc, length_bp=8)
                    except HTTPException:
                        continue
                    placed += 1
                    progressed = True
                    break
                if progressed:
                    break
            if not progressed:
                break

        # Stacked beyond one-per-cell (the whole point of the per-Z occupancy).
        assert placed > len(SIX_HB_CELLS)
        d = design_state.get_or_404()
        assert all(r.ok for r in validate_design(d).results)
        # Saturated: no main-bundle candidate remains.
        hobj = {h.id: h for h in d.helices}
        remaining = [
            (hid, bp, nr, nc)
            for hid, bp, dirn, is5 in _staple_termini(d)
            if hobj[hid].grid_pos in ring
            for nr, nc in _hc_neighbors(*hobj[hid].grid_pos)
            if (nr, nc) not in ring
            and overhang_candidate_error(d, hobj[hid], bp, dirn, nr, nc) is None
        ]
        assert remaining == []


def test_make_18hb_routed_design_is_deterministic():
    """The routed builder reproduces the same topology every call — required for
    tests that pin routed specifics against it."""
    from tests.conftest import make_18hb_routed_design

    def sig(d):
        return sorted(
            (s.strand_type.value, tuple((dm.helix_id, dm.start_bp, dm.end_bp) for dm in s.domains))
            for s in d.strands
        )
    assert sig(make_18hb_routed_design()) == sig(make_18hb_routed_design())
