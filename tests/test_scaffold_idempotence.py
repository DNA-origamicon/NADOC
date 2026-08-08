"""ISSUE-9 — autoscaffold must be idempotent: N routes == 1 route.

Before the fix, every re-route read its OWN previous output as the face to extend
from and ratcheted the helices outward.  Measured on the plain bundle below:
helices 168 -> 189 -> 199 -> 210 bp and crossovers 6 -> 9 -> 12 over three routes,
unbounded, and persisted to the .nadoc.  It was NOT teeth-specific — it hit any
design; teeth is merely where it was visible (the extension intrudes into the
inter-tooth gaps).  See backend/core/scaffold_reset.py.

Every assertion here goes red against the pre-fix source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.models import Design, StrandType
from backend.core.scaffold_reset import (
    reset_scaffold_to_structure,
    structural_intervals,
)
from backend.core.seamed_router import auto_scaffold_seamed
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.lattice import make_bundle_design

FIXTURES = Path(__file__).parent / "fixtures"
CELLS_4HB = [(0, 0), (0, 1), (1, 0), (1, 1)]


def _load(name: str) -> Design:
    j = json.loads((FIXTURES / name).read_text())
    return Design.model_validate(j.get("design", j))


def _topology(d: Design) -> dict:
    """The design's routed shape: helix extents + scaffold domains + crossover sites.

    Exactly what the ISSUE-9 dossier asked to pin ("same domains/faces/crossovers").
    Strand ids are deliberately excluded — a re-route legitimately mints new ids for
    the strands it merges; only the topology must be stable.
    """
    helices = sorted(
        (str(h.grid_pos), h.bp_start, h.length_bp, round(h.phase_offset, 9))
        for h in d.helices
    )
    domains = sorted(
        (dom.helix_id, dom.start_bp, dom.end_bp, str(dom.direction))
        for s in d.strands
        if s.strand_type == StrandType.SCAFFOLD and not s.is_reference
        for dom in s.domains
    )
    xovers = sorted(
        tuple(
            sorted(
                [(h.helix_id, h.index, str(h.strand)) for h in (xo.half_a, xo.half_b)]
            )
        )
        for xo in d.crossovers
    )
    n_scaf = sum(
        1
        for s in d.strands
        if s.strand_type == StrandType.SCAFFOLD and not s.is_reference
    )
    return {
        "helices": helices,
        "domains": domains,
        "xovers": xovers,
        "n_scaffold_strands": n_scaf,
    }


def _staple_spans(d: Design) -> dict:
    return structural_intervals(d)


# ── The core property, on the design shapes that actually exist ───────────────


@pytest.mark.parametrize(
    "router",
    [
        pytest.param(lambda d: auto_scaffold_seamed(d)[0], id="seamed"),
        pytest.param(lambda d: auto_scaffold_seamless(d)[0], id="seamless"),
    ],
)
def test_reroute_is_idempotent_on_a_plain_bundle(router):
    """A plain 4HB bundle — NO teeth, NO sections. The bug was never teeth-specific."""
    once = router(make_bundle_design(CELLS_4HB, length_bp=168))
    twice = router(once.model_copy(deep=True))
    thrice = router(twice.model_copy(deep=True))

    assert _topology(twice) == _topology(once), "2nd route changed the design"
    assert _topology(thrice) == _topology(once), "3rd route changed the design"


@pytest.mark.parametrize("fixture", ["teeth_unrouted.nadoc", "10-6-10hb_seamed.nadoc"])
def test_reroute_is_idempotent_on_multisection_designs(fixture):
    """Teeth + dumbbell: the sections are carried by the STAPLES (gaps and all)."""
    once = auto_scaffold_seamed(_load(fixture))[0]
    twice = auto_scaffold_seamed(once.model_copy(deep=True))[0]

    assert _topology(twice) == _topology(once)


def test_reroute_never_grows_the_helices():
    """The ratchet, stated directly: re-routing must not extend a helix any further."""
    once = auto_scaffold_seamed(make_bundle_design(CELLS_4HB, length_bp=168))[0]
    twice = auto_scaffold_seamed(once.model_copy(deep=True))[0]

    before = {h.id: h.length_bp for h in once.helices}
    after = {h.id: h.length_bp for h in twice.helices}
    assert after == before, f"helices grew on re-route: {before} -> {after}"


def test_reroute_does_not_accumulate_crossovers():
    """Pre-fix these went 6 -> 9 -> 12: only the seam xovers were being cleared, the
    bare `create_near_ends`/`create_far_ends` end-turns survived every clear."""
    once = auto_scaffold_seamed(make_bundle_design(CELLS_4HB, length_bp=168))[0]
    twice = auto_scaffold_seamed(once.model_copy(deep=True))[0]
    thrice = auto_scaffold_seamed(twice.model_copy(deep=True))[0]

    assert len(twice.crossovers) == len(once.crossovers)
    assert len(thrice.crossovers) == len(once.crossovers)


def test_reroute_still_yields_a_single_scaffold_strand():
    """Guard against 'idempotent but broken' — a reset that produced the wrong seed
    converged to a fixed point of 5 scaffold strands instead of 1."""
    once = auto_scaffold_seamed(make_bundle_design(CELLS_4HB, length_bp=168))[0]
    twice = auto_scaffold_seamed(once.model_copy(deep=True))[0]

    assert _topology(once)["n_scaffold_strands"] == 1
    assert _topology(twice)["n_scaffold_strands"] == 1


# ── The reset itself ─────────────────────────────────────────────────────────


def test_reset_restores_a_routed_design_to_its_fresh_seed():
    """reset(route(fresh)) == fresh, field for field. This is WHY N == 1."""
    fresh = make_bundle_design(CELLS_4HB, length_bp=168)
    routed = auto_scaffold_seamed(fresh.model_copy(deep=True))[0]
    reseeded, warnings = reset_scaffold_to_structure(routed)

    assert _topology(reseeded) == _topology(fresh)
    assert warnings, "a reset that actually retracted something should say so"


def test_reset_is_a_noop_on_a_never_routed_design():
    fresh = make_bundle_design(CELLS_4HB, length_bp=168)
    reseeded, warnings = reset_scaffold_to_structure(fresh.model_copy(deep=True))

    assert _topology(reseeded) == _topology(fresh)
    assert warnings == []


def test_reset_never_touches_the_staples():
    """Staples ARE the structure — the oracle the whole fix rests on. If routing or
    resetting could move them, the clean extent would not be recoverable."""
    fresh = make_bundle_design(CELLS_4HB, length_bp=168)
    before = _staple_spans(fresh)

    routed = auto_scaffold_seamed(fresh.model_copy(deep=True))[0]
    assert _staple_spans(routed) == before, "routing moved the staples"

    reseeded, _ = reset_scaffold_to_structure(routed)
    assert _staple_spans(reseeded) == before, "reset moved the staples"


def test_reset_bails_out_on_forced_ligations():
    """A manual fixed-edge topology is not derivable from the staples, so the reset
    must refuse rather than destroy it — and must say why."""
    d = _load("teeth_unrouted.nadoc")
    routed = auto_scaffold_seamed(d)[0]
    with_forced = routed.model_copy(
        update={
            "forced_ligations": [fl for fl in (routed.forced_ligations or [])]
            or ["sentinel"]
        }
    )

    reseeded, warnings = reset_scaffold_to_structure(with_forced)

    assert _topology(reseeded) == _topology(with_forced), "reset must not touch it"
    assert any("forced ligation" in w.lower() for w in warnings)


def test_reset_does_not_grow_a_deliberately_short_scaffold():
    """A scaffold shorter than its staples was never routed there — the reset clamps
    INTO the staple intervals, it does not fill them.  (This is what keeps the
    two-group seamless fixture, whose arms carry a short scaffold, working.)"""
    from backend.core.models import Direction

    base = make_bundle_design(CELLS_4HB, length_bp=84)
    arm = {h.id for h in base.helices if h.grid_pos in [(0, 0), (0, 1)]}
    strands = []
    for s in base.strands:
        if s.strand_type == StrandType.SCAFFOLD and s.domains[0].helix_id in arm:
            dom = s.domains[0]
            upd = (
                {"end_bp": 41}
                if dom.direction == Direction.FORWARD
                else {"start_bp": 41}
            )
            strands.append(
                s.model_copy(update={"domains": [dom.model_copy(update=upd)]})
            )
        else:
            strands.append(s)
    short = base.copy_with(strands=strands)

    reseeded, _ = reset_scaffold_to_structure(short)

    for s in reseeded.strands:
        if s.strand_type != StrandType.SCAFFOLD or s.is_reference:
            continue
        dom = s.domains[0]
        if dom.helix_id in arm:
            assert max(dom.start_bp, dom.end_bp) == 41, "reset grew a short scaffold"
