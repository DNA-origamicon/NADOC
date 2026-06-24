"""Headless (mouse-free) design construction — backend/api/headless_build.py.

These pin the two properties that make the module worth having over a direct
core-builder call: (1) builds carry a real, replayable feature log identical to
the UI's, and (2) a one-shot build is isolated — it never disturbs the active
document or its undo history.
"""

from __future__ import annotations

import collections

import pytest
from fastapi import HTTPException

import backend.api.doc_context as dc
from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.core.lattice import overhang_candidate_error
from backend.core.models import Direction, LatticeType
from backend.core.validator import validate_design
from tests.automation_harness import (
    assert_circular_disc,
    assert_cluster_in_feature_log,
    assert_feature_seek,
    assert_cluster_translated,
    assert_deformation_angle,
    assert_fully_sequenced,
    assert_geometric_length_delta,
    assert_inverse_pair,
    assert_on_deformed_frame,
    assert_roundtrip_stable,
    canonical_topology,
    geometric_nucleotide_count,
    headless_coverage_report,
    roundtrip_nadoc,
)
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


def _place_one_overhang(d):
    """Extrude one valid staple overhang on a routed/broken bundle; return the
    design.  Mirrors test_overhang_extrude_places_a_valid_candidate's search."""
    hobj = {h.id: h for h in d.helices}
    occ = {h.grid_pos for h in d.helices}
    for hid, bp, dirn, is5 in _staple_termini(d):
        r, c = hobj[hid].grid_pos
        for nr, nc in _hc_neighbors(r, c):
            if (nr, nc) in occ:
                continue
            try:
                return hb.overhang_extrude(
                    hid, bp, direction=dirn, is_five_prime=is5,
                    neighbor_row=nr, neighbor_col=nc, length_bp=8,
                )
            except HTTPException:
                continue
    return None


def test_af25_feature_seek_scrubs_timeline_faithfully():
    """AF-25 — headless feature-log SEEK + non-destructive-scrub oracle.

    Build a multi-entry timeline (bundle → auto-scaffold → assign-scaffold-sequence
    → overhang), recording the build fingerprint forward after each op, then prove
    ``hb.seek_features`` scrubs to each point faithfully, non-destructively, and
    reversibly — and that seeking BEFORE an op drops its effect (overhang gone,
    sequences cleared)."""
    from backend.core.oxdna_staleness import design_build_fingerprint as _fp
    from backend.physics.oxdna_interface import count_undefined_bases

    def _all_undefined(d):
        undef, total = count_undefined_bases(d, exclude_reference=True)
        return total > 0 and undef == total

    def _scaffold_sequenced(d):
        undef, total = count_undefined_bases(d, exclude_reference=True)
        return total > 0 and undef < total

    with hb.scratch_session(LatticeType.HONEYCOMB):
        d0 = hb.create_bundle(SIX_HB_CELLS, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        pos_bundle = len(d0.feature_log) - 1
        fp_bundle = _fp(d0)

        d1 = hb.auto_scaffold(seamless=False)
        pos_scaffold = len(d1.feature_log) - 1
        fp_scaffold = _fp(d1)

        # break staples so there are nick termini to extrude an overhang from
        hb.auto_crossover()
        hb.auto_break()

        d2 = hb.assign_scaffold_sequence()
        pos_seq = len(d2.feature_log) - 1
        fp_seq = _fp(d2)

        d3 = _place_one_overhang(d2)
        assert d3 is not None, "expected at least one valid overhang site on a routed 6hb"
        assert len(d3.overhangs) == 1
        pos_overhang = len(d3.feature_log) - 1
        fp_overhang = _fp(d3)

        # all four ops are distinct build states → a real, scrubable timeline
        assert len({fp_bundle, fp_scaffold, fp_seq, fp_overhang}) == 4

        # auto_crossover/auto_break logged entries sit between assign-seq's
        # recorded position and the overhang; record positions forward so the
        # oracle's checkpoints stay valid regardless of how many entries those add.
        n0 = assert_feature_seek(
            hb.seek_features,
            [
                # before scaffold routing: bundle only, no overhang
                (pos_bundle, fp_bundle, lambda d: len(d.overhangs) == 0),
                # routed but unsequenced: every base still undefined
                (pos_scaffold, fp_scaffold, _all_undefined),
                # scaffold sequenced, overhang not yet placed
                (pos_seq, fp_seq, lambda d: len(d.overhangs) == 0 and _scaffold_sequenced(d)),
                # latest: the overhang is present
                (pos_overhang, fp_overhang, lambda d: len(d.overhangs) == 1),
            ],
        )
        assert n0 == len(d3.feature_log)
        # explicitly: the seek did NOT truncate the log (non-destructive vs revert)
        assert len(hb.seek_features(-1).feature_log) == n0


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


# ── Strand-edit wrappers: nick / ligate / delete (AF-2) ───────────────────────────
# These pin the wrappers with the *reusable* inverse-pair oracle (the AF-2 augment):
# nick then ligate must restore the exact topology fingerprint, and the oracle's
# built-in "forward actually changed something" guard means a wrapper that silently
# no-ops can't pass.  delete is pinned by the canonical strand-set subtraction.


def _single_forward_domain_strand(d):
    """Pick a strand that is one FORWARD domain ≥4 bp long — a clean nick site."""
    for s in d.strands:
        if len(s.domains) == 1:
            dm = s.domains[0]
            if dm.direction == Direction.FORWARD and dm.end_bp - dm.start_bp >= 4:
                return s
    raise AssertionError("no single-FORWARD-domain strand found in fixture")


def test_nick_then_ligate_is_topology_identity():
    """nick(h, bp, dir) then ligate(h, bp, dir) restores the design unchanged.

    Uses the reusable inverse-pair oracle shipped with AF-2 — it both proves the
    round-trip is identity AND that the nick really split the strand (mid-state
    topology differs), so a wrapper that didn't actually nick would fail.
    """
    with hb.scratch_session(LatticeType.HONEYCOMB):
        start = hb.create_bundle(
            SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb",
        ).model_copy(deep=True)
        s = _single_forward_domain_strand(start)
        dm = s.domains[0]
        h, bp = dm.helix_id, dm.start_bp + (dm.end_bp - dm.start_bp) // 2

        assert_inverse_pair(
            start,
            forward=lambda: hb.nick(h, bp, Direction.FORWARD),
            inverse=lambda: hb.ligate(h, bp, Direction.FORWARD),
        )


def test_nick_splits_into_two_fragments():
    """The nick wrapper actually adds a strand (one fragment becomes two)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d0 = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        n_before = len(d0.strands)
        s = _single_forward_domain_strand(d0)
        dm = s.domains[0]
        d1 = hb.nick(dm.helix_id, dm.start_bp + 5, Direction.FORWARD)
        assert len(d1.strands) == n_before + 1
        assert d1.feature_log[-1].children[-1].op_subtype == "nick"


def test_delete_strand_removes_exactly_that_strand_and_validates():
    """delete_strand drops exactly one strand: the canonical strand set loses that
    one entry, everything else is untouched, and the result still validates."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d0 = hb.create_bundle(
            SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb",
        ).model_copy(deep=True)
        victim = _single_forward_domain_strand(d0)
        before = collections.Counter(canonical_topology(d0)[1])

        d1 = hb.delete_strand(victim.id)
        after = collections.Counter(canonical_topology(d1)[1])

        assert validate_design(d1).passed
        assert victim.id not in {s.id for s in d1.strands}
        # Exactly one canonical strand entry removed; helices untouched.
        removed = before - after
        assert sum(removed.values()) == 1
        assert canonical_topology(d0)[0] == canonical_topology(d1)[0]


def test_delete_strand_result_survives_roundtrip():
    """A design with a strand deleted still round-trips stably (reuses AF-1)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d0 = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        victim = _single_forward_domain_strand(d0)
        deleted = hb.delete_strand(victim.id).model_copy(deep=True)
    assert_roundtrip_stable(lambda: deleted)


def test_nick_ligate_delete_flip_routes_to_covered():
    """The three wrappers register their routes as covered (function-identity audit)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert {"add_nick", "ligate_strand", "delete_strand"} <= covered


# ── Loop/skip wrappers (AF-3) ─────────────────────────────────────────────────────


def test_loop_adds_one_bp_of_geometry():
    """A loop (+1) adds exactly one bp of geometry to its helix (one nuc per strand)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        h = d.helices[0]
        bp = h.bp_start + 14   # interior, on a cell boundary, away from the edges
        start = d.model_copy(deep=True)
        looped = assert_geometric_length_delta(
            start, lambda: hb.loop_skip(h.id, bp, +1), +1, helix_id=h.id,
        )
        assert looped.feature_log[-1].children[-1].op_subtype == "loop-skip-insert"


def test_skip_removes_one_bp_of_geometry():
    """A skip (−1) removes exactly one bp of geometry from its helix."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        h = d.helices[0]
        bp = h.bp_start + 14
        start = d.model_copy(deep=True)
        assert_geometric_length_delta(
            start, lambda: hb.loop_skip(h.id, bp, -1), -1, helix_id=h.id,
        )


def test_loop_then_remove_restores_geometry():
    """delta=0 removes a prior mark — the loop's own inverse restores the baseline."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        h = d.helices[0]
        bp = h.bp_start + 14
        looped = hb.loop_skip(h.id, bp, +1).model_copy(deep=True)
        # Removing the mark (delta=0) takes the geometry back down by one bp.
        assert_geometric_length_delta(
            looped, lambda: hb.loop_skip(h.id, bp, 0), -1, helix_id=h.id,
        )


def test_loop_survives_roundtrip():
    """A loop/skip mark persists through a .nadoc save/load.

    canonical_topology (and so assert_roundtrip_stable) is blind to loop/skips —
    they live on the helix, not in the strand graph — so the geometric count is the
    oracle that proves the mark was not silently dropped on import.
    """
    with hb.scratch_session(LatticeType.HONEYCOMB):
        d = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        h = d.helices[0]
        built = hb.loop_skip(h.id, h.bp_start + 14, +1).model_copy(deep=True)
    reloaded = roundtrip_nadoc(built)
    assert geometric_nucleotide_count(reloaded) == geometric_nucleotide_count(built)
    assert any(ls.delta for hh in reloaded.helices for ls in hh.loop_skips)


def test_apply_deformations_geometry_honors_marks_per_helix():
    """apply-deformations bakes marks the geometry layer honours helix-by-helix.

    On a routed SQUARE design the route applies the periodic-skip pattern (one
    skip / 48 bp / helix) — mechanical and deterministic, no bend/twist sign
    reasoning.  The conservation law: each helix's geometric nucleotide count must
    change by exactly twice its net loop/skip delta.  The global net delta may be
    large, but the per-helix check is what proves no mark leaks between helices or
    is dropped.
    """
    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(TEETH_CELLS, 96, lattice=LatticeType.SQUARE, name="sq")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        before = design_state.get_or_404().model_copy(deep=True)

        result = hb.apply_loop_skip_deformations()

        assert result.feature_log[-1].op_kind == "apply-loop-skips"
        # Guard: the op actually placed marks (else the conservation law is vacuous).
        assert any(ls.delta for h in result.helices for ls in h.loop_skips)
        for h in result.helices:
            net = sum(ls.delta for ls in h.loop_skips)
            diff = (geometric_nucleotide_count(result, h.id)
                    - geometric_nucleotide_count(before, h.id))
            assert diff == 2 * net, (
                f"helix {h.id}: geometry changed by {diff}, marks net {net} (×2 expected)"
            )


def test_loop_skip_apply_deformations_flip_routes_to_covered():
    """The two AF-3 wrappers register their routes as covered (function-identity)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert {"insert_loop_skip", "apply_loop_skips_from_deformations"} <= covered


# ── Parametric circle wrapper (AF-4) ──────────────────────────────────────────────


@pytest.mark.parametrize("radius", [6.0, 8.0, 10.6, 14.0, 20.0])
def test_circle_segment_builds_a_disc_of_the_requested_radius(radius):
    """circle_segment(R) places a disc whose *built geometry* traces a circle of
    radius ≈ R.

    The geometric oracle reads the placed helices' axis spans (not a stored field),
    so this pins the whole headless path radius→footprint→route→builder→geometry —
    not just the footprint math the pure circle tests already cover.
    """
    with hb.scratch_session(LatticeType.SQUARE):
        d = hb.circle_segment(radius)
        assert d.feature_log[-1].op_kind == "circle-segment"
        assert_circular_disc(d, radius)


def test_circle_segment_result_survives_roundtrip():
    """A placed disc still validates and round-trips stably (reuses AF-1)."""
    with hb.scratch_session(LatticeType.SQUARE):
        built = hb.circle_segment(10.6).model_copy(deep=True)
    assert_roundtrip_stable(lambda: built)


def test_circle_segment_radius_too_small_raises():
    """A radius below the min-chord floor admits no helix → ValueError, no mutation."""
    with hb.scratch_session(LatticeType.SQUARE):
        with pytest.raises(ValueError, match="too small"):
            hb.circle_segment(0.5)
        assert design_state.get_or_404().helices == []


def test_circle_segment_is_additive_over_existing_dna():
    """The disc adds to an existing design without disturbing prior helices."""
    with hb.scratch_session(LatticeType.SQUARE):
        base = hb.create_bundle([(0, 0)], 42, lattice=LatticeType.SQUARE, name="seed")
        n_before = len(base.helices)
        d = hb.circle_segment(8.0)
        assert len(d.helices) > n_before
        assert (0, 0) in {tuple(h.grid_pos) for h in d.helices}


def test_circle_segment_flips_route_to_covered():
    """The wrapper registers /design/circle-segment as covered (function-identity)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "add_circle_segment" in covered


def test_assert_circular_disc_fires_on_a_non_circular_profile():
    """Load-bearing red-test: the oracle raises when the helix lengths aren't circular.

    Build a real disc, then mangle one helix's length so the profile is no longer a
    circle — the oracle must catch it (a green that can go red).
    """
    with hb.scratch_session(LatticeType.SQUARE):
        d = hb.circle_segment(10.6).model_copy(deep=True)
    # Stretch the longest (centre) helix far past its chord → spread blows up.
    centre = max(d.helices, key=lambda h: abs(h.axis_end.z - h.axis_start.z))
    centre.axis_end.z += 5.0
    with pytest.raises(AssertionError, match="not circular"):
        assert_circular_disc(d, 10.6)


# ── Deformed-continuation wrapper (AF-5) ──────────────────────────────────────────


def _bend_active(curvature_deg_per_bp: float = 2.0):
    """Bend the active design's middle (planes at bp 20–60). Bend construction has
    no headless wrapper yet (AF-6), so this drives the route handler directly."""
    from backend.api.routes_deformation import AddDeformationBody, add_deformation
    add_deformation(AddDeformationBody(
        type="bend", plane_a_bp=20, plane_b_bp=60,
        params={"kind": "bend", "curvature_deg_per_bp": curvature_deg_per_bp,
                "direction_deg": 0.0},
    ))


def test_deformed_continuation_lands_on_the_deformed_frame():
    """A continuation appended onto a bent far end sits on the deformed cross-section
    frame (and is displaced from where a straight extrude would land).

    The oracle reads the placed helices' geometry, pinning the whole headless path
    source_bp→deformed-frame→route→builder→placed geometry.
    """
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
        ref = design_state.get_or_404().helices[0].id
        _bend_active()
        before = design_state.get_or_404().model_copy(deep=True)
        after = hb.bundle_deformed_continuation([(0, 0)], 21, source_bp=84, ref_helix_id=ref)
        assert after.feature_log[-1].op_kind == "extrude-deformed-continuation"
        assert_on_deformed_frame(before, after, 84, [(0, 0)], ref_helix_id=ref)


def test_deformed_continuation_flips_route_to_covered():
    """The wrapper registers /design/bundle-deformed-continuation as covered."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "add_bundle_deformed_continuation" in covered


# ── Deformation bend/twist wrappers (AF-6) ────────────────────────────────────────


def _bundle_for_deformation():
    """Fresh straight 84-bp single-cell bundle; returns its ref helix id."""
    hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
    return design_state.get_or_404().helices[0].id


def test_add_bend_realises_requested_curvature():
    """add_bend(κ over [a,b]) rotates the deformed frame by κ × (b − a)°.

    Pins the whole headless path request→route→DeformationOp→deformed frame against
    the user-meaningful knob (the curvature), magnitude-only.
    """
    with hb.scratch_session(LatticeType.HONEYCOMB):
        ref = _bundle_for_deformation()
        kappa = 2.0
        d = hb.add_bend(20, 60, curvature_deg_per_bp=kappa)
        assert d.feature_log[-1].feature_type == "deformation"
        assert_deformation_angle(d, 20, 60, kappa * (60 - 20), ref_helix_id=ref)


def test_add_bend_large_angle_unwraps_past_180():
    """A 200° bend (κ=5 over 40 bp) reads as 200°, not folded to 160°."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        ref = _bundle_for_deformation()
        d = hb.add_bend(20, 60, curvature_deg_per_bp=5.0, direction_deg=45.0)
        assert_deformation_angle(d, 20, 60, 200.0, ref_helix_id=ref)


def test_add_twist_total_degrees_realises_requested_angle():
    """add_twist(total_degrees=θ) rotates the frame about its axis by θ°."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        ref = _bundle_for_deformation()
        d = hb.add_twist(20, 60, total_degrees=90.0)
        assert d.feature_log[-1].feature_type == "deformation"
        assert_deformation_angle(d, 20, 60, 90.0, ref_helix_id=ref)


def test_add_twist_large_angle_unwraps_past_360():
    """A 540° twist reads as 540°, not folded to 180° (the per-step sum unwraps)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        ref = _bundle_for_deformation()
        d = hb.add_twist(20, 60, total_degrees=540.0)
        assert_deformation_angle(d, 20, 60, 540.0, ref_helix_id=ref)


def test_add_twist_degrees_per_nm_realises_rate():
    """add_twist(degrees_per_nm=r) rotates by r × span_nm degrees."""
    from backend.core.constants import BDNA_RISE_PER_BP

    with hb.scratch_session(LatticeType.HONEYCOMB):
        ref = _bundle_for_deformation()
        rate = 30.0
        d = hb.add_twist(20, 60, degrees_per_nm=rate)
        expected = rate * (60 - 20) * BDNA_RISE_PER_BP
        assert_deformation_angle(d, 20, 60, expected, ref_helix_id=ref)


def test_add_twist_requires_exactly_one_spec():
    """Passing both / neither of total_degrees / degrees_per_nm raises (no mutation)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        _bundle_for_deformation()
        with pytest.raises(ValueError, match="exactly one"):
            hb.add_twist(20, 60)
        with pytest.raises(ValueError, match="exactly one"):
            hb.add_twist(20, 60, total_degrees=90.0, degrees_per_nm=30.0)
        assert design_state.get_or_404().deformations == []


def test_deformation_flips_route_to_covered():
    """The wrappers register POST /design/deformation as covered (function-identity)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "add_deformation" in covered


# ── clusters (AF-15 Phase 1 — rigid-body grouping + DISPLAY-layer pose) ─────────
# A cluster pose is a DISPLAY-layer rigid displacement applied by the geometry kernel,
# never a topology edit (the three-layer law). canonical_topology is BLIND to it (like
# loop/skip marks + bend/twist overlays), so assert_roundtrip_stable is necessary but
# NOT load-bearing for the pose — the geometric assert_cluster_translated is, measuring
# that the cluster's helix axes actually shift by the requested translation.

def _bundle_two_helix_cluster():
    """Active scratch: a 6hb bundle with a named cluster over its first 2 helices.
    Returns (snapshot_before_pose, cluster_id)."""
    hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
    design = design_state.get_or_404()
    cluster_helix_ids = [design.helices[0].id, design.helices[1].id]
    hb.add_cluster("armA", cluster_helix_ids)
    cid = design_state.get_or_404().cluster_transforms[-1].id
    return design_state.get_or_404().model_copy(deep=True), cid


def test_add_cluster_creates_named_cluster():
    """add_cluster creates a non-default cluster holding the requested helices."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        before, cid = _bundle_two_helix_cluster()
        cluster = next(c for c in before.cluster_transforms if c.id == cid)
        assert cluster.name == "armA" and not cluster.is_default
        assert len(cluster.helix_ids) == 2
        # identity pose at birth
        assert cluster.translation == [0.0, 0.0, 0.0]
        assert cluster.rotation == [0.0, 0.0, 0.0, 1.0]


@pytest.mark.parametrize("translation", [[10.0, 0.0, 0.0], [0.0, -7.5, 3.0]])
def test_transform_cluster_translates_only_cluster_geometry(translation):
    """A pure-translation pose shifts the cluster's helix axes by exactly the vector,
    and leaves every non-cluster helix put — proves the pose flows through the geometry
    kernel (which canonical_topology can't show)."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        before, cid = _bundle_two_helix_cluster()
        hb.transform_cluster(cid, translation=translation)
        after = design_state.get_or_404()
        moved = assert_cluster_translated(before, after, cid, translation=translation)
        assert moved == 2  # only the two clustered helices


def test_clustered_pose_survives_roundtrip():
    """A built + clustered + posed design validates and survives a .nadoc round-trip
    with the pose intact — re-running the geometric oracle on the reloaded design proves
    persistence (canonical_topology is blind to the pose, so it can't)."""
    def _build():
        _before, cid = _bundle_two_helix_cluster()
        hb.transform_cluster(cid, translation=[10.0, 0.0, 0.0])
        return design_state.get_or_404().model_copy(deep=True)

    with hb.scratch_session(LatticeType.HONEYCOMB):
        posed = _build()
        cid = posed.cluster_transforms[-1].id
        reloaded = assert_roundtrip_stable(lambda: posed)
        # the pose persisted as a field …
        rc = next(c for c in reloaded.cluster_transforms if c.id == cid)
        assert rc.translation == [10.0, 0.0, 0.0]
        # … and still drives the geometry after the round-trip (vs an identity-pose base)
        identity_base = reloaded.model_copy(update={
            "cluster_transforms": [
                c.model_copy(update={"translation": [0.0, 0.0, 0.0]}) if c.id == cid else c
                for c in reloaded.cluster_transforms
            ]
        })
        assert_cluster_translated(identity_base, reloaded, cid, translation=[10.0, 0.0, 0.0])


def test_cluster_routes_flip_to_covered():
    """The wrappers register POST /design/cluster + PATCH /design/cluster/{id} as
    covered (function-identity), coverage 32 → 34."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert {"add_cluster", "update_cluster"} <= covered


# ── AF-16: loggable cluster creation ───────────────────────────────────────────
# add_cluster(log=True) appends a cluster_create feature-log entry so a generated
# multi-bar part's construction history can replay the *grouping* step. canonical_topology
# is blind to clusters, so the feature-log entry is the only thing that proves the grouping
# persisted across a .nadoc round-trip — assert_cluster_in_feature_log is the load-bearing pin.

def test_add_cluster_log_records_feature_log_entry():
    """add_cluster(log=True) appends a cluster_create entry naming the cluster + its
    exact helix set."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        design = design_state.get_or_404()
        cluster_helix_ids = [design.helices[0].id, design.helices[1].id]
        hb.add_cluster("armA", cluster_helix_ids, log=True)
        after = design_state.get_or_404()
        cid = after.cluster_transforms[-1].id
        entry = assert_cluster_in_feature_log(after, cid)
        assert entry.name == "armA"
        assert set(entry.helix_ids) == set(cluster_helix_ids)


def test_add_cluster_log_survives_roundtrip():
    """The cluster_create entry survives a .nadoc round-trip — the only proof the grouping
    persisted, since canonical_topology can't see clusters."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        design = design_state.get_or_404()
        cluster_helix_ids = [design.helices[0].id, design.helices[1].id]
        hb.add_cluster("armA", cluster_helix_ids, log=True)
        built = design_state.get_or_404().model_copy(deep=True)
        cid = built.cluster_transforms[-1].id
        reloaded = roundtrip_nadoc(built)
        assert_cluster_in_feature_log(reloaded, cid, expect_helix_ids=cluster_helix_ids)


def test_add_cluster_default_does_not_log():
    """add_cluster without log=True (the default, backward-compatible) appends NO
    cluster_create entry — so the existing capstone/tests are unaffected and the oracle
    can go red on an unlogged build."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        design = design_state.get_or_404()
        cluster_helix_ids = [design.helices[0].id, design.helices[1].id]
        hb.add_cluster("armA", cluster_helix_ids)  # default: log=False
        after = design_state.get_or_404()
        cid = after.cluster_transforms[-1].id
        assert not any(
            getattr(e, "feature_type", None) == "cluster_create" for e in after.feature_log
        )
        with pytest.raises(AssertionError, match="created without logging"):
            assert_cluster_in_feature_log(after, cid)


# ── Full sequencing automation (assign scaffold + WC-complement staples) ───────

def _routed_6hb():
    """A 6hb auto-scaffolded to a single scaffold (so the staple complement covers
    every staple) — the routed-origami starting point for full sequencing."""
    hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
    hb.auto_scaffold()
    return design_state.get_or_404()


def test_full_sequence_leaves_no_undefined_bases():
    """full_sequence on a routed single-scaffold 6hb assigns the scaffold sequence +
    WC-complements every staple → zero undefined bases, all WC-correct."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        _routed_6hb()
        sequenced = hb.full_sequence()
        # The oracle proves both: nothing left 'N' AND staples are WC-complementary.
        checked = assert_fully_sequenced(sequenced)
        assert checked > 0


def test_assign_staple_sequences_requires_scaffold_sequence():
    """assign_staple_sequences alone (no scaffold sequence yet) 422s — it drives the
    real route, which demands an assigned scaffold first."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        _routed_6hb()
        with pytest.raises(HTTPException) as exc:
            hb.assign_staple_sequences()
        assert exc.value.status_code == 422


def test_full_sequence_survives_roundtrip():
    """A fully-sequenced design stays fully sequenced through a .nadoc save/load."""
    with hb.scratch_session(LatticeType.HONEYCOMB):
        _routed_6hb()
        sequenced = hb.full_sequence().model_copy(deep=True)
    reloaded = roundtrip_nadoc(sequenced)
    assert_fully_sequenced(reloaded)


def test_full_sequence_flips_assign_staples_route_to_covered():
    """The assign_staple_sequences wrapper registers its route as covered
    (function-identity audit)."""
    rep = headless_coverage_report()
    covered = {r["endpoint"] for r in rep["covered_routes"]}
    assert "assign_staple_sequences_endpoint" in covered
