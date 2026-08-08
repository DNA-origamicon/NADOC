"""Driver tests for the declarative build-spec interpreter (AF-11, Tier 4).

``backend.api.headless_spec_build`` lowers a spec to a sequence of real headless
wrapper calls.  These pin the two properties that make it trustworthy as text-to-DNA
groundwork: (1) a spec-built structure survives a round-trip (it's a valid, stable
build), and (2) it is byte-for-byte identical — in canonical topology — to the
equivalent hand-call wrapper sequence (the interpreter is a faithful façade, not a
re-implementation).  The faithfulness pin is the new reusable oracle
``assert_spec_matches_calls``.
"""

from __future__ import annotations

import json
import math
import stat

import pytest
from fastapi import HTTPException

from backend.api import assembly_state
from backend.api import headless_assembly_build as hab
from backend.api import headless_build as hb
from backend.api import headless_oxdna_build as hox
from backend.api import headless_spec_build as hs
from backend.api import state as design_state
from backend.core.build_spec import BuildSpecError
from backend.core.models import LatticeType
from backend.core.oxdna_health import check_relaxed_constraint
from backend.core.oxdna_job import OxdnaStatus
from tests.automation_harness import (
    assert_assembly_roundtrip_stable,
    assert_circular_disc,
    assert_converges_to_constraint,
    assert_crossover_extra_bases,
    assert_deformation_angle,
    assert_gear_ratio,
    assert_instances_from_file,
    assert_instances_on_grid,
    assert_instances_on_ring,
    assert_mate_coincident,
    assert_part_from_file,
    assert_part_from_primitive,
    assert_part_is_circular_disc,
    assert_polymer_chain,
    assert_roundtrip_stable,
    assert_spec_constraints_reported,
    assert_spec_matches_calls,
    canonical_topology,
    geometric_nucleotide_count,
    roundtrip_nadoc,
)
from tests.conftest import SIX_HB_CELLS, TEETH_CELLS, TEETH_PASSES, make_6hb_design

# The multi-frame mock oxDNA binary source (a constant, not a fixture — a cross-module
# fixture import trips ruff F811; the same pattern test_headless_oxdna_build uses to
# borrow _MOCK_OXDNA from test_oxdna_relaxation).
from tests.test_headless_oxdna_build import _MOCK_OXDNA_TRAJ

_CELLS = [list(c) for c in SIX_HB_CELLS]


# ── design interpreter ────────────────────────────────────────────────────────


def test_design_spec_builds_6hb():
    spec = {
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"}],
    }
    d = hs.build_design(spec)
    assert len(d.helices) == 6
    # the build carries a real, replayable feature log (drove the real wrapper)
    assert [e.op_kind for e in d.feature_log] == ["bundle-create"]


def test_design_spec_matches_hand_calls():
    """A bundle spec builds the SAME canonical topology as make_6hb_design()."""
    spec = {
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"}],
    }
    assert_spec_matches_calls(
        lambda: hs.build_design(spec), make_6hb_design, kind="design"
    )


def test_teeth_spec_matches_hand_calls():
    """A bundle + extrude-passes spec reproduces the teeth fixture's hand build."""
    rise = hb.BDNA_RISE_PER_BP
    ops = [
        {
            "op": "bundle",
            "cells": [list(c) for c in TEETH_CELLS],
            "length_bp": 42,
            "name": "teeth",
        }
    ]
    for i, n in enumerate(TEETH_PASSES, start=1):
        ops.append(
            {
                "op": "extrude",
                "cells": [list(c) for c in TEETH_CELLS[:n]],
                "length_bp": 42,
                "offset_nm": round(i * 42 * rise, 3),
            }
        )
    spec = {"lattice": "square", "ops": ops}

    def hand():
        return hb.build_bundle(
            TEETH_CELLS,
            42,
            lattice=LatticeType.SQUARE,
            name="teeth",
            passes=TEETH_PASSES,
        )

    assert_spec_matches_calls(lambda: hs.build_design(spec), hand, kind="design")


def test_design_spec_roundtrips_stable():
    spec = {
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": _CELLS, "length_bp": 42}],
    }
    assert_roundtrip_stable(lambda: hs.build_design(spec))


def test_design_spec_nick_ligate_is_identity():
    """nick then ligate (declarative, by grid_pos) restores the base topology."""
    base = {
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}],
    }
    nicked = {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42},
            {"op": "nick", "helix": [0, 1], "bp_index": 20, "direction": "forward"},
            {"op": "ligate", "helix": [0, 1], "bp_index": 20, "direction": "forward"},
        ],
    }
    assert canonical_topology(hs.build_design(nicked)) == canonical_topology(
        hs.build_design(base)
    )


def test_design_spec_nick_alone_changes_topology():
    """A nick (without the ligate) really mutates — proves the inverse test isn't vacuous."""
    base = {
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}],
    }
    nicked = {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42},
            {"op": "nick", "helix": [0, 1], "bp_index": 20, "direction": "forward"},
        ],
    }
    assert canonical_topology(hs.build_design(nicked)) != canonical_topology(
        hs.build_design(base)
    )


def test_nick_unknown_grid_pos_raises():
    spec = {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": [[0, 1]], "length_bp": 42},
            {"op": "nick", "helix": [9, 9], "bp_index": 5, "direction": "forward"},
        ],
    }
    with pytest.raises(BuildSpecError, match="no helix at grid position"):
        hs.build_design(spec)


def test_build_design_is_isolated():
    """A spec build runs in a scratch session — the default doc is untouched."""
    hb.new_design(LatticeType.HONEYCOMB)
    before = len(design_state.get_or_404().helices)
    hs.build_design(
        {
            "lattice": "honeycomb",
            "ops": [{"op": "bundle", "cells": _CELLS, "length_bp": 42}],
        }
    )
    assert len(design_state.get_or_404().helices) == before


# ── deformation ops: bend / twist (AF-11 Phase 2) ─────────────────────────────
# NB: canonical_topology is BLIND to a deformation overlay (it lives outside the
# strand graph, like a loop/skip — the AF-3 lesson), so assert_spec_matches_calls
# confirms only that the underlying bundle topology is faithful. The load-bearing
# pin that the bend/twist op actually flowed through to the geometry is the
# geometric assert_deformation_angle below.


def _bend_spec(kappa=2.0):
    return {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": [[0, 0]], "length_bp": 84, "name": "B"},
            {
                "op": "bend",
                "plane_a_bp": 20,
                "plane_b_bp": 60,
                "curvature_deg_per_bp": kappa,
            },
        ],
    }


def test_bend_spec_matches_hand_calls():
    """A bend spec builds the same bundle topology as the equivalent hand calls.
    (Weak by itself for the bend — canonical_topology can't see the deformation —
    but it pins the bundle plumbing; the angle is pinned separately below.)"""

    def hand():
        with hb.scratch_session(LatticeType.HONEYCOMB):
            hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
            hb.add_bend(20, 60, curvature_deg_per_bp=2.0)
            return design_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_design(_bend_spec()), hand, kind="design"
    )


def test_bend_spec_realises_requested_curvature():
    """The bend op in the spec actually rotates the deformed frame by κ × (b − a)°
    — proves the parameter flowed spec → parser → hb.add_bend → DeformationOp."""
    d = hs.build_design(_bend_spec(kappa=2.0))
    assert d.feature_log[-1].feature_type == "deformation"
    assert_deformation_angle(d, 20, 60, 2.0 * (60 - 20), ref_helix_id=d.helices[0].id)


def test_twist_spec_total_degrees_realises_angle():
    """A twist spec (total_degrees) rotates the frame about its axis by θ°."""
    spec = {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": [[0, 0]], "length_bp": 84, "name": "B"},
            {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60, "total_degrees": 90},
        ],
    }
    d = hs.build_design(spec)
    assert_deformation_angle(d, 20, 60, 90.0, ref_helix_id=d.helices[0].id)


def test_twist_spec_degrees_per_nm_realises_rate():
    """A twist spec (degrees_per_nm) rotates by r × span_nm degrees."""
    from backend.core.constants import BDNA_RISE_PER_BP

    rate = 30.0
    spec = {
        "lattice": "honeycomb",
        "ops": [
            {"op": "bundle", "cells": [[0, 0]], "length_bp": 84, "name": "B"},
            {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60, "degrees_per_nm": rate},
        ],
    }
    d = hs.build_design(spec)
    expected = rate * (60 - 20) * BDNA_RISE_PER_BP
    assert_deformation_angle(d, 20, 60, expected, ref_helix_id=d.helices[0].id)


# ── loop/skip op (AF-11 Phase 2) ──────────────────────────────────────────────
# A loop/skip mark lives on Helix.loop_skips, OUTSIDE the strand graph — so
# canonical_topology (and assert_spec_matches_calls) is BLIND to it (the AF-3
# lesson). The load-bearing pin that the mark actually flowed spec → parser →
# hb.loop_skip → geometry is the GEOMETRIC nucleotide count, not the canonical
# fingerprint. The first test below documents that assert_spec_matches_calls
# passes (bundle plumbing faithful) while being unable to see the loop on its own.


def _base_loop_spec():
    return {
        "lattice": "honeycomb",
        "ops": [{"op": "bundle", "cells": [[0, 0]], "length_bp": 42, "name": "L"}],
    }


def _loop_spec(bp, delta):
    spec = _base_loop_spec()
    spec["ops"].append(
        {"op": "loop_skip", "helix": [0, 0], "bp_index": bp, "delta": delta}
    )
    return spec


def test_loop_skip_spec_matches_bundle_topology():
    """A loop_skip spec builds the same bundle topology as the equivalent hand calls.
    (Weak by itself — canonical_topology can't see the loop/skip mark — but it pins
    the bundle plumbing; the geometric effect is pinned separately below.)"""
    base = hs.build_design(_base_loop_spec())
    bp = base.helices[0].bp_start + 14

    def hand():
        with hb.scratch_session(LatticeType.HONEYCOMB):
            d = hb.create_bundle([(0, 0)], 42, lattice=LatticeType.HONEYCOMB, name="L")
            hb.loop_skip(d.helices[0].id, d.helices[0].bp_start + 14, +1)
            return design_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_design(_loop_spec(bp, +1)), hand, kind="design"
    )


def test_loop_spec_adds_one_bp_of_geometry():
    """A loop (+1) op in a spec adds exactly one bp of geometry to its helix
    (one nucleotide per strand) — proves delta flowed spec → parser → hb.loop_skip."""
    base = hs.build_design(_base_loop_spec())
    h = base.helices[0]
    looped = hs.build_design(_loop_spec(h.bp_start + 14, +1))
    hid = next(
        hh.id for hh in looped.helices if tuple(hh.grid_pos) == tuple(h.grid_pos)
    )
    assert (
        geometric_nucleotide_count(looped, hid) - geometric_nucleotide_count(base, h.id)
    ) == 2
    # the mark really landed in the spec-built design
    assert any(ls.delta for hh in looped.helices for ls in hh.loop_skips)


def test_skip_spec_removes_one_bp_of_geometry():
    """A skip (−1) op in a spec removes exactly one bp of geometry from its helix."""
    base = hs.build_design(_base_loop_spec())
    h = base.helices[0]
    skipped = hs.build_design(_loop_spec(h.bp_start + 14, -1))
    hid = next(
        hh.id for hh in skipped.helices if tuple(hh.grid_pos) == tuple(h.grid_pos)
    )
    assert (
        geometric_nucleotide_count(skipped, hid)
        - geometric_nucleotide_count(base, h.id)
    ) == -2


def test_loop_skip_spec_survives_roundtrip():
    """A spec-built loop/skip mark persists through a .nadoc save/load.

    canonical_topology is blind to loop/skips, so a structure round-trip can't prove
    persistence — the geometric count is what catches a silently-dropped mark."""
    base = hs.build_design(_base_loop_spec())
    looped = hs.build_design(_loop_spec(base.helices[0].bp_start + 14, +1))
    reloaded = roundtrip_nadoc(looped)
    assert geometric_nucleotide_count(reloaded) == geometric_nucleotide_count(looped)
    assert any(ls.delta for hh in reloaded.helices for ls in hh.loop_skips)


# ── crossover_extra_bases op ──────────────────────────────────────────────────
# Extra bases are single-stranded inserts at a placed crossover junction
# (Crossover.extra_bases) — junction METADATA outside the strand graph, so (like a
# loop/skip mark) canonical_topology / assert_spec_matches_calls are BLIND to them: the
# load-bearing pin is assert_crossover_extra_bases, which reads extra_bases back off the
# built design.  The op needs crossovers placed first → every spec routes (auto_scaffold
# + auto_crossover) before annotating.


def _xover_base_spec():
    """A routed square bundle with real (staple) crossovers placed."""
    return _routed_spec()


def test_crossover_extra_bases_spec_is_non_vacuous():
    """Before any extra-bases op, the routed design carries crossovers but none has
    extra bases — so the pins below are can-go-red, not vacuous."""
    base = hs.build_design(_xover_base_spec())
    assert base.crossovers, (
        "fixture must place crossovers for these pins to mean anything"
    )
    assert all(x.extra_bases is None for x in base.crossovers)


def test_crossover_extra_bases_bulk_all_spec():
    """A bulk crossover_extra_bases (filter=all) sets the sequence on every crossover —
    pinned by reading extra_bases back (canonical_topology is blind to it)."""
    spec = _xover_base_spec()
    spec["ops"].append(
        {"op": "crossover_extra_bases", "sequence": "TT", "filter": "all"}
    )
    built = hs.build_design(spec)
    assert_crossover_extra_bases(built, "TT", crossover_filter="all")


def test_crossover_extra_bases_bulk_staple_spec():
    """A bulk set filtered to staple crossovers annotates exactly those and leaves any
    other junction type untouched (the bled-onto-wrong-type can-go-red guard)."""
    spec = _xover_base_spec()
    spec["ops"].append(
        {"op": "crossover_extra_bases", "sequence": "TTT", "filter": "staple"}
    )
    built = hs.build_design(spec)
    assert_crossover_extra_bases(built, "TTT", crossover_filter="staple")


def test_crossover_extra_bases_precise_spec():
    """A precise set targets ONE junction by its two helix cells + bp index and hits
    exactly that crossover (others stay None) — addressing survives rebuild (no uuids)."""
    routed = hs.build_design(_xover_base_spec())
    xo = routed.crossovers[0]
    gp = {h.id: list(h.grid_pos) for h in routed.helices}
    spec = _xover_base_spec()
    spec["ops"].append(
        {
            "op": "crossover_extra_bases",
            "helix_a": gp[xo.half_a.helix_id],
            "helix_b": gp[xo.half_b.helix_id],
            "bp_index": xo.half_a.index,
            "sequence": "AT",
        }
    )
    built = hs.build_design(spec)
    assert_crossover_extra_bases(built, "AT", expected_count=1)


def test_crossover_extra_bases_matches_hand_calls():
    """The spec drives the SAME wrappers as the hand sequence — topology is identical
    (assert_spec_matches_calls is blind to extra_bases, so this pins the façade is
    faithful for everything BUT the metadata; the value itself is pinned above)."""

    def hand():
        with hb.scratch_session(LatticeType.SQUARE):
            hb.create_bundle(TEETH_CELLS, 96, lattice=LatticeType.SQUARE, name="sq")
            hb.auto_scaffold(seamless=False)
            hb.auto_crossover()
            hb.set_crossover_extra_bases_bulk("GC", crossover_filter="all")
            return design_state.get_or_404().model_copy(deep=True)

    spec = _xover_base_spec()
    spec["ops"].append(
        {"op": "crossover_extra_bases", "sequence": "GC", "filter": "all"}
    )
    spec_built = assert_spec_matches_calls(
        lambda: hs.build_design(spec), hand, kind="design"
    )
    # and the metadata the fingerprint can't see really landed
    assert_crossover_extra_bases(spec_built, "GC", crossover_filter="all")


def test_crossover_extra_bases_clear_is_inverse():
    """Setting then clearing ("") extra bases restores the no-extra-bases baseline."""
    spec = _xover_base_spec()
    spec["ops"].append(
        {"op": "crossover_extra_bases", "sequence": "TT", "filter": "all"}
    )
    spec["ops"].append({"op": "crossover_extra_bases", "sequence": "", "filter": "all"})
    built = hs.build_design(spec)
    assert all(x.extra_bases is None for x in built.crossovers)


def test_crossover_extra_bases_requires_crossovers():
    """Targeting a junction that doesn't exist (no crossovers placed) raises — the op
    annotates placed junctions, it does not create them."""
    spec = {
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"},
            {"op": "crossover_extra_bases", "sequence": "TT", "filter": "all"},
        ],
    }
    with pytest.raises(HTTPException):
        hs.build_design(spec)


def test_crossover_extra_bases_both_modes_rejected():
    """A spec giving BOTH a filter and a location is a parse error (ambiguous addressing)."""
    with pytest.raises(BuildSpecError):
        hs.build_design(
            {
                "lattice": "square",
                "ops": [
                    {
                        "op": "crossover_extra_bases",
                        "sequence": "TT",
                        "filter": "all",
                        "helix_a": [0, 0],
                        "helix_b": [1, 0],
                        "bp_index": 8,
                    },
                ],
            }
        )


def test_crossover_extra_bases_bad_sequence_rejected():
    """A sequence with a non-ACGTN base is a parse error."""
    with pytest.raises(BuildSpecError):
        hs.build_design(
            {
                "lattice": "square",
                "ops": [
                    {"op": "crossover_extra_bases", "sequence": "TX", "filter": "all"}
                ],
            }
        )


def test_crossover_extra_bases_bad_filter_rejected():
    """An unknown filter is a parse error."""
    with pytest.raises(BuildSpecError):
        hs.build_design(
            {
                "lattice": "square",
                "ops": [
                    {"op": "crossover_extra_bases", "sequence": "TT", "filter": "loops"}
                ],
            }
        )


# ── circle_segment op (AF-11 Phase 2) ─────────────────────────────────────────
# Unlike loop_skip/bend/twist, circle_segment ADDS real helices + strands to the
# strand graph — so canonical_topology CAN see it and assert_spec_matches_calls is
# LOAD-BEARING here (a dropped disc would fail the faithfulness pin). The geometric
# assert_circular_disc (AF-4) additionally pins that the radius→geometry path is
# faithful end-to-end.


def _circle_spec(radius=10.6):
    return {"lattice": "square", "ops": [{"op": "circle_segment", "radius_nm": radius}]}


def test_circle_segment_spec_matches_hand_calls():
    """A circle_segment spec builds the SAME canonical topology as the hand call
    (it adds real strands, so the faithful-façade pin is load-bearing here)."""

    def hand():
        with hb.scratch_session(LatticeType.SQUARE):
            hb.circle_segment(10.6)
            return design_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_design(_circle_spec()), hand, kind="design"
    )


@pytest.mark.parametrize("radius", [8.0, 10.6, 14.0])
def test_circle_segment_spec_builds_a_disc_of_the_requested_radius(radius):
    """The spec-built disc's placed geometry traces a circle of the requested radius
    — proves radius_nm flowed spec → parser → hb.circle_segment → placed helices."""
    d = hs.build_design(_circle_spec(radius))
    assert d.feature_log[-1].op_kind == "circle-segment"
    assert_circular_disc(d, radius)


def test_circle_segment_spec_roundtrips_stable():
    assert_roundtrip_stable(lambda: hs.build_design(_circle_spec()))


# ── bulk routing ops: auto_scaffold / auto_crossover / full_autostaple ─────────
# Unlike loop_skip/bend/twist, these ADD strands (a scaffold strand, crossover
# domain-transitions, broken/merged staples) the strand graph fingerprint sees — so
# canonical_topology CAN see them and assert_spec_matches_calls is LOAD-BEARING here:
# the hand reference runs the REAL auto ops, so if the driver silently dropped one,
# the spec build would diverge and the golden pin would go red.

_TEETH = [list(c) for c in TEETH_CELLS]


def _routed_spec(*, seamless=False):
    return {
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"},
            {"op": "auto_scaffold", "seamless": seamless},
            {"op": "auto_crossover"},
        ],
    }


def test_auto_scaffold_crossover_spec_matches_hand_calls():
    """A bundle → auto_scaffold → auto_crossover spec builds the SAME canonical
    topology as the equivalent hand calls — load-bearing, since the auto ops add
    real strands the fingerprint sees (a dropped op would diverge from the hand build)."""

    def hand():
        with hb.scratch_session(LatticeType.SQUARE):
            hb.create_bundle(TEETH_CELLS, 96, lattice=LatticeType.SQUARE, name="sq")
            hb.auto_scaffold(seamless=False)
            hb.auto_crossover()
            return design_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_design(_routed_spec()), hand, kind="design"
    )


def test_auto_scaffold_crossover_spec_changes_topology_vs_bundle():
    """The routing ops visibly change the strand graph vs a bare bundle — so the
    faithfulness pin above is non-vacuous (it's not comparing two bare bundles)."""
    bare = hs.build_design(
        {
            "lattice": "square",
            "ops": [{"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"}],
        }
    )
    routed = hs.build_design(_routed_spec())
    assert canonical_topology(routed) != canonical_topology(bare)
    # the routing ran end-to-end and left a replayable log
    assert [e.op_kind for e in routed.feature_log][0] == "bundle-create"
    assert len(routed.feature_log) >= 3  # bundle + scaffold + crossover entries


def test_full_autostaple_spec_matches_hand_calls():
    """A bundle → auto_scaffold → full_autostaple spec builds the SAME canonical
    topology as the equivalent hand calls (full_autostaple assigns sequence, places
    crossovers, breaks+merges staples — all visible to the fingerprint)."""

    def hand():
        with hb.scratch_session(LatticeType.SQUARE):
            hb.create_bundle(TEETH_CELLS, 96, lattice=LatticeType.SQUARE, name="sq")
            hb.auto_scaffold()
            hb.full_autostaple()
            return design_state.get_or_404().model_copy(deep=True)

    spec = {
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"},
            {"op": "auto_scaffold"},
            {"op": "full_autostaple"},
        ],
    }
    assert_spec_matches_calls(lambda: hs.build_design(spec), hand, kind="design")


def test_full_autostaple_spec_roundtrips_stable():
    """A fully-routed spec design (scaffold + full_autostaple) is well-formed and
    survives a .nadoc round-trip. (auto_crossover alone leaves staples nicked at
    crossovers — non-physical until broken/merged — so the complete autostaple is the
    valid round-trip target.)"""
    spec = {
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"},
            {"op": "auto_scaffold"},
            {"op": "full_autostaple"},
        ],
    }
    assert_roundtrip_stable(lambda: hs.build_design(spec))


# ── apply_loop_skips op (AF-11 Phase 2 — unblocked by auto_crossover) ──────────
# apply_loop_skips bakes the design's deformations (+ SQUARE periodic skips) into
# concrete loop/skip marks. Its route needs crossovers placed — which auto_crossover
# now produces in the same spec. Like loop_skip, the marks live OUTSIDE the strand
# graph, so canonical_topology (and assert_spec_matches_calls) is BLIND to them: the
# load-bearing pin is the AF-3 per-helix geometric conservation law (each helix's
# nucleotide count changes by exactly twice its net loop/skip delta).


def _pre_apply_spec():
    """The routed SQUARE substrate apply_loop_skips runs on (no apply op yet)."""
    return {
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"},
            {"op": "auto_scaffold"},
            {"op": "auto_crossover"},
        ],
    }


def _apply_loop_skips_spec():
    spec = _pre_apply_spec()
    spec["ops"].append({"op": "apply_loop_skips"})
    return spec


def test_apply_loop_skips_spec_honors_marks_per_helix():
    """apply_loop_skips in a spec bakes the SQUARE periodic-skip pattern, and each
    helix's geometry changes by exactly 2 × its net mark delta — proving the marks
    flowed spec → parser → hb.apply_loop_skip_deformations → geometry helix-by-helix
    (which assert_spec_matches_calls can't see: the marks live outside the strand graph)."""
    before = hs.build_design(_pre_apply_spec())
    after = hs.build_design(_apply_loop_skips_spec())

    assert after.feature_log[-1].op_kind == "apply-loop-skips"
    # Guard: the op actually placed marks (else the conservation law is vacuous).
    assert any(ls.delta for h in after.helices for ls in h.loop_skips)
    before_by_grid = {tuple(h.grid_pos): h.id for h in before.helices}
    for h in after.helices:
        net = sum(ls.delta for ls in h.loop_skips)
        bhid = before_by_grid[tuple(h.grid_pos)]
        diff = geometric_nucleotide_count(after, h.id) - geometric_nucleotide_count(
            before, bhid
        )
        assert diff == 2 * net, (
            f"helix {h.id}: geometry changed by {diff}, marks net {net} (×2 expected)"
        )


def test_apply_loop_skips_spec_requires_crossovers():
    """Without crossovers, apply_loop_skips' route 400s — so a spec that applies on a
    bare bundle fails at build time (proves the op runs the real route, not a no-op)."""
    spec = {
        "lattice": "square",
        "ops": [
            {"op": "bundle", "cells": _TEETH, "length_bp": 96, "name": "sq"},
            {"op": "apply_loop_skips"},
        ],
    }
    with pytest.raises(HTTPException):
        hs.build_design(spec)


# ── assembly interpreter ──────────────────────────────────────────────────────

_BEAM_SPEC = {
    "lattice": "honeycomb",
    "ops": [{"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"}],
}


def test_assembly_spec_grid_matches_hand_calls():
    spec = {
        "kind": "assembly",
        "name": "G",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [
            {"op": "place_grid", "part": "beam", "rows": 2, "cols": 3, "pitch": 10.0}
        ],
    }

    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("G")
            hab.place_grid(make_6hb_design(), 2, 3, pitch=10.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_assembly(spec), hand, kind="assembly")


def test_assembly_spec_grid_roundtrips_stable():
    spec = {
        "kind": "assembly",
        "name": "G",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [
            {"op": "place_grid", "part": "beam", "rows": 2, "cols": 3, "pitch": 10.0}
        ],
    }
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(lambda: hs.build_assembly(spec))


def test_assembly_spec_ring_roundtrips_stable():
    spec = {
        "kind": "assembly",
        "name": "R",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [{"op": "place_ring", "part": "beam", "n": 5, "radius": 15.0}],
    }
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(lambda: hs.build_assembly(spec))


def _mate_spec():
    return {
        "kind": "assembly",
        "name": "M",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [
            {
                "op": "add_part",
                "part": "beam",
                "ref": "A",
                "connectors": [
                    {"label": "mate_a", "position": [5, 0, 0], "normal": [1, 0, 0]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "B",
                "transform": [20, 0, 0],
                "connectors": [
                    {"label": "mate_b", "position": [-5, 0, 0], "normal": [-1, 0, 0]}
                ],
            },
            {
                "op": "mate",
                "child": "B",
                "parent": "A",
                "child_label": "mate_b",
                "parent_label": "mate_a",
            },
        ],
    }


def test_assembly_spec_mate_matches_hand_calls():
    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("M")
            hab.add_inline_instance(make_6hb_design(), name="A")
            hab.add_inline_instance(
                make_6hb_design(), name="B", transform=hab.translation(20, 0, 0)
            )
            a = assembly_state.get_or_404()
            id_a, id_b = a.instances[0].id, a.instances[1].id
            hab.add_connector(id_a, "mate_a", position=[5, 0, 0], normal=[1, 0, 0])
            hab.add_connector(id_b, "mate_b", position=[-5, 0, 0], normal=[-1, 0, 0])
            hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_assembly(_mate_spec()), hand, kind="assembly"
    )


def test_assembly_spec_mate_is_coincident():
    """The mate the interpreter built actually snaps its connectors coincident."""
    a = hs.build_assembly(_mate_spec())
    assert len(a.joints) == 1
    with hab.assembly_scratch_session():
        assembly_state.set_assembly(a)
        assert_mate_coincident(a, a.joints[0].id)


def test_assembly_spec_mate_roundtrips_stable():
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(lambda: hs.build_assembly(_mate_spec()))


# ── file-backed parts (AF-12 — build from a saved validated primitive) ─────────
# The motivating use case: hand-author + experimentally validate a part (real topology
# = ground truth), save it as a .nadoc, then let automation place/articulate copies by
# REFERENCE. A {"from_file": …} part is fingerprinted by canonical_assembly as
# ("file", path, sha256) ONLY — the fingerprint never loads the design behind the path —
# so assert_spec_matches_calls catches a dropped/wrong-path from_file but is BLIND to
# whether the path resolves to the INTENDED validated topology. assert_part_from_file is
# the load-bearing pin: it loads the design the instance actually references and compares
# its canonical_topology to the saved primitive's.


def _file_part_spec(path):
    """A saved primitive (by file path) mated to an inline beam — instance + articulate a
    validated part exactly as the motivating use case describes."""
    return {
        "kind": "assembly",
        "name": "F",
        "parts": {
            "saved": {"from_file": path},
            "beam": _BEAM_SPEC,
        },
        "ops": [
            {
                "op": "add_part",
                "part": "saved",
                "ref": "S",
                "connectors": [
                    {"label": "s", "position": [5, 0, 0], "normal": [1, 0, 0]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "B",
                "transform": [20, 0, 0],
                "connectors": [
                    {"label": "b", "position": [-5, 0, 0], "normal": [-1, 0, 0]}
                ],
            },
            {
                "op": "mate",
                "child": "B",
                "parent": "S",
                "child_label": "b",
                "parent_label": "s",
            },
        ],
    }


def _save_primitive(tmp_path, design):
    path = tmp_path / "primitive.nadoc"
    path.write_text(design.to_json(), encoding="utf-8")
    return str(path)


def test_assembly_spec_from_file_uses_validated_topology(tmp_path):
    """THE AUGMENT: a {"from_file": …} part instances the saved design by reference, and
    the instance resolves to EXACTLY that file's validated topology. Load-bearing because
    canonical_assembly keys a file source by path only and never loads the design — only
    this proves the from_file grammar wired the right path through to a real, loadable,
    topology-bearing instance."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    a = hs.build_assembly(_file_part_spec(path))
    file_inst = next(i for i in a.instances if i.source.type == "file")
    assert file_inst.source.path == path  # the wired reference
    resolved = assert_part_from_file(a, file_inst.id, canonical_topology(saved))
    assert canonical_topology(resolved) == canonical_topology(saved)


def test_assembly_spec_from_file_oracle_fires_on_wrong_topology(tmp_path):
    """can-go-red: a stale/edited/wrong primitive resolves to a DIFFERENT topology than
    expected → the oracle catches the silent substitution canonical_assembly can't."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    a = hs.build_assembly(_file_part_spec(path))
    file_inst = next(i for i in a.instances if i.source.type == "file")
    other = hs.build_design(  # a 2-helix bundle — a genuinely different topology
        {
            "lattice": "honeycomb",
            "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}],
        }
    )
    with pytest.raises(AssertionError, match="DIFFERENT topology"):
        assert_part_from_file(a, file_inst.id, canonical_topology(other))


def test_assembly_spec_from_file_oracle_rejects_inline_instance(tmp_path):
    """can-go-red: pointed at the INLINE beam (an embedded copy, not a file reference)
    the oracle refuses — it pins the from_file grammar, not just any matching topology."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    a = hs.build_assembly(_file_part_spec(path))
    inline_inst = next(i for i in a.instances if i.source.type == "inline")
    with pytest.raises(AssertionError, match="not file-backed"):
        assert_part_from_file(a, inline_inst.id, canonical_topology(make_6hb_design()))


def test_assembly_spec_from_file_roundtrips_stable(tmp_path):
    """The file source survives a .nass round-trip (path + sha resolve, flatten ok) —
    the from_file reference is durable, not a build-time-only convenience."""
    path = _save_primitive(tmp_path, make_6hb_design())
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(
            lambda: hs.build_assembly(_file_part_spec(path))
        )


# ── file-backed parametric layout (AF-12 follow-up — place_grid/place_ring by ref) ──
# A {"from_file": …} part may now be placed by place_grid / place_ring (not only
# add_part): the driver loops add_file_instance per slot, so the saved validated .nadoc
# travels as a path reference per copy. assert_instances_on_grid/_on_ring pin the LATTICE
# but never load the design; assert_instances_from_file is the load-bearing source pin —
# every slot resolves to the saved primitive's topology (catches a slot that embedded an
# inline copy or substituted a wrong path).


def test_assembly_spec_file_grid_places_and_references(tmp_path):
    """A file-backed place_grid lands rows×cols copies on the lattice, each a genuine
    reference to the saved primitive."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    spec = {
        "kind": "assembly",
        "name": "FG",
        "parts": {"saved": {"from_file": path}},
        "ops": [
            {"op": "place_grid", "part": "saved", "rows": 2, "cols": 3, "pitch": 11.0}
        ],
    }
    a = hs.build_assembly(spec)
    assert len(a.instances) == 6
    assert all(i.source.type == "file" for i in a.instances)
    assert_instances_on_grid(a, 2, 3, pitch=11.0)
    assert assert_instances_from_file(a, canonical_topology(saved)) == 6


def test_assembly_spec_file_ring_places_and_references(tmp_path):
    """A file-backed place_ring lands n copies on the ring, each a file reference."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    spec = {
        "kind": "assembly",
        "name": "FR",
        "parts": {"saved": {"from_file": path}},
        "ops": [{"op": "place_ring", "part": "saved", "n": 5, "radius": 16.0}],
    }
    a = hs.build_assembly(spec)
    assert len(a.instances) == 5
    assert_instances_on_ring(a, 5, radius=16.0)
    assert assert_instances_from_file(a, canonical_topology(saved)) == 5


def test_assembly_spec_file_grid_roundtrips_stable(tmp_path):
    """The file-backed grid survives a .nass round-trip with all slots still referencing
    the primitive."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    spec = {
        "kind": "assembly",
        "name": "FGRT",
        "parts": {"saved": {"from_file": path}},
        "ops": [
            {"op": "place_grid", "part": "saved", "rows": 2, "cols": 2, "pitch": 10.0}
        ],
    }
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(lambda: hs.build_assembly(spec))
    assert_instances_from_file(reloaded, canonical_topology(saved))


# ── catalog-named part (AF-12 Phase 2 — from_primitive) ────────────────────────
# The text-to-design rung: reference a curated, pre-validated catalog primitive by the
# SAME name the "Add Primitive" UI shows ({"from_primitive": "6hb_primitive"}), without
# knowing where its .nadoc lives. The driver resolves the name → the catalog primitive's
# saved .nadoc path, then lowers it through the EXACT from_file machinery (one path
# reference per copy). The new, load-bearing piece over from_file is the name→catalog-path
# RESOLVER: assert_part_from_primitive independently re-resolves the name through the
# catalog and proves the instance is that exact primitive's validated topology — a name
# silently mapped to the wrong/renamed primitive is invisible to canonical_assembly.


def _save_catalog_primitive(primitives_dir, name, design):
    """Drop a posed .nadoc into a tmp catalog dir under the catalog NAME (stem)."""
    p = primitives_dir / f"{name}.nadoc"
    p.write_text(design.to_json(), encoding="utf-8")
    return p


def _primitive_part_spec(name):
    """A catalog primitive (by name) mated to an inline beam — instance + articulate a
    curated validated part exactly as the text-to-design use case describes."""
    return {
        "kind": "assembly",
        "name": "P",
        "parts": {
            "saved": {"from_primitive": name},
            "beam": _BEAM_SPEC,
        },
        "ops": [
            {
                "op": "add_part",
                "part": "saved",
                "ref": "S",
                "connectors": [
                    {"label": "s", "position": [5, 0, 0], "normal": [1, 0, 0]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "B",
                "transform": [20, 0, 0],
                "connectors": [
                    {"label": "b", "position": [-5, 0, 0], "normal": [-1, 0, 0]}
                ],
            },
            {
                "op": "mate",
                "child": "B",
                "parent": "S",
                "child_label": "b",
                "parent_label": "s",
            },
        ],
    }


def _two_helix_design():
    """A genuinely different topology from the 6hb (for the wrong-name red-test)."""
    return hs.build_design(
        {
            "lattice": "honeycomb",
            "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}],
        }
    )


def test_assembly_spec_from_primitive_uses_catalog_topology(tmp_path):
    """THE AUGMENT: a {"from_primitive": "<name>"} part resolves its catalog NAME to the
    saved primitive and instances it by reference, resolving to EXACTLY that primitive's
    validated topology. Load-bearing because canonical_assembly keys a file source by path
    only and never loads the design — only this proves the name→catalog-path RESOLVER picked
    the right primitive (and wired a real, loadable, topology-bearing reference)."""
    saved = make_6hb_design()
    _save_catalog_primitive(tmp_path, "beam_six", saved)
    a = hs.build_assembly(_primitive_part_spec("beam_six"), primitives_dir=tmp_path)
    file_inst = next(i for i in a.instances if i.source.type == "file")
    resolved = assert_part_from_primitive(a, file_inst.id, "beam_six", tmp_path)
    assert canonical_topology(resolved) == canonical_topology(saved)


def test_assembly_spec_from_primitive_oracle_fires_on_wrong_name(tmp_path):
    """can-go-red: asserting the instance came from a DIFFERENT catalog primitive than it
    actually did → the oracle re-resolves that other name, loads its topology, and catches
    the mismatch canonical_assembly can't see."""
    _save_catalog_primitive(tmp_path, "beam_six", make_6hb_design())
    _save_catalog_primitive(tmp_path, "beam_two", _two_helix_design())
    a = hs.build_assembly(_primitive_part_spec("beam_six"), primitives_dir=tmp_path)
    file_inst = next(i for i in a.instances if i.source.type == "file")
    with pytest.raises(AssertionError, match="DIFFERENT topology"):
        assert_part_from_primitive(a, file_inst.id, "beam_two", tmp_path)


def test_assembly_spec_from_primitive_oracle_rejects_unknown_name(tmp_path):
    """can-go-red: asked to re-resolve a name absent from the catalog, the oracle refuses
    rather than passing vacuously (the build itself would also have raised for this name)."""
    _save_catalog_primitive(tmp_path, "beam_six", make_6hb_design())
    a = hs.build_assembly(_primitive_part_spec("beam_six"), primitives_dir=tmp_path)
    file_inst = next(i for i in a.instances if i.source.type == "file")
    with pytest.raises(AssertionError, match="catalog has no primitive"):
        assert_part_from_primitive(a, file_inst.id, "nope_missing", tmp_path)


def test_assembly_spec_from_primitive_unknown_name_fails_build(tmp_path):
    """An unknown catalog name fails the BUILD with a clear BuildSpecError (the parser is
    catalog-agnostic, so name validity is checked at build time), not a silent empty part."""
    _save_catalog_primitive(tmp_path, "beam_six", make_6hb_design())
    with pytest.raises(BuildSpecError, match="no catalog primitive named 'ghost'"):
        hs.build_assembly(_primitive_part_spec("ghost"), primitives_dir=tmp_path)


def test_assembly_spec_from_primitive_roundtrips_stable(tmp_path):
    """The catalog-resolved file source survives a .nass round-trip — the from_primitive
    reference is durable, lowering to the same path reference from_file does."""
    _save_catalog_primitive(tmp_path, "beam_six", make_6hb_design())
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(
            lambda: hs.build_assembly(
                _primitive_part_spec("beam_six"), primitives_dir=tmp_path
            )
        )


def test_assembly_spec_primitive_grid_places_and_references(tmp_path):
    """A catalog primitive may be laid out by place_grid (it folds into the from_file path,
    so per-slot references), each slot resolving to the named primitive's topology."""
    saved = make_6hb_design()
    _save_catalog_primitive(tmp_path, "beam_six", saved)
    spec = {
        "kind": "assembly",
        "name": "PG",
        "parts": {"saved": {"from_primitive": "beam_six"}},
        "ops": [
            {"op": "place_grid", "part": "saved", "rows": 2, "cols": 3, "pitch": 11.0}
        ],
    }
    a = hs.build_assembly(spec, primitives_dir=tmp_path)
    assert len(a.instances) == 6
    assert all(i.source.type == "file" for i in a.instances)
    assert_instances_on_grid(a, 2, 3, pitch=11.0)
    assert assert_instances_from_file(a, canonical_topology(saved)) == 6


# ── parametric catalog primitive (AF-12 Phase 2b — from_primitive + params) ────
# The next text-to-design rung: a {"from_primitive": "<circle>", "params": {"radius_nm": R}}
# part is NOT file-referenced like a static primitive — the driver re-derives the disc at the
# requested radius (lowering to the SAME single circle_segment op a hand-authored spec uses)
# and embeds it INLINE. So the load-bearing pin is geometric: assert_part_is_circular_disc
# loads the embedded design and proves the placed helices trace a circle of the requested
# radius — the params.radius_nm → footprint → build → placed-geometry path through the
# assembly layer, which canonical_assembly (blind to circularity) cannot see.


def _save_circle_primitive(
    primitives_dir, name="disc_primitive", default_radius_nm=10.0
):
    """Drop a parametric circle catalog primitive (metadata.primitive_kind='circle', SQUARE)
    into a tmp catalog dir. Its saved geometry is just the default-radius disc; the spec's
    requested radius re-derives a fresh disc generatively, so only the metadata + placement
    (plane / min_chord_bp) of this saved file are load-bearing."""
    design = hs.build_design(
        {
            "lattice": "square",
            "ops": [{"op": "circle_segment", "radius_nm": default_radius_nm}],
        }
    )
    raw = json.loads(design.to_json())
    raw.setdefault("metadata", {})["primitive_kind"] = "circle"
    p = primitives_dir / f"{name}.nadoc"
    p.write_text(json.dumps(raw), encoding="utf-8")
    return p


def _circle_part_spec(name, radius_nm):
    """A parametric circle primitive (by name + radius) mated to an inline beam — instance a
    generatively-built disc exactly as the text-to-design use case describes."""
    return {
        "kind": "assembly",
        "name": "C",
        "parts": {
            "disc": {"from_primitive": name, "params": {"radius_nm": radius_nm}},
            "beam": _BEAM_SPEC,
        },
        "ops": [
            {
                "op": "add_part",
                "part": "disc",
                "ref": "D",
                "connectors": [
                    {"label": "d", "position": [5, 0, 0], "normal": [1, 0, 0]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "B",
                "transform": [40, 0, 0],
                "connectors": [
                    {"label": "b", "position": [-5, 0, 0], "normal": [-1, 0, 0]}
                ],
            },
            {
                "op": "mate",
                "child": "B",
                "parent": "D",
                "child_label": "b",
                "parent_label": "d",
            },
        ],
    }


def test_assembly_spec_parametric_circle_builds_disc(tmp_path):
    """THE AUGMENT: a {"from_primitive": "<circle>", "params": {"radius_nm": R}} part is built
    GENERATIVELY at the requested radius and embedded inline; the placed disc is a circle of
    radius ≈ R. Load-bearing because canonical_assembly keys the inline source by its embedded
    topology fingerprint, blind to whether that geometry is actually circular of radius R."""
    _save_circle_primitive(tmp_path, "disc_primitive", default_radius_nm=10.0)
    a = hs.build_assembly(
        _circle_part_spec("disc_primitive", 14.0), primitives_dir=tmp_path
    )
    disc = next(i for i in a.instances if i.name == "disc")
    assert disc.source.type == "inline", (
        "a parametric circle must be embedded inline, not file-backed"
    )
    assert_part_is_circular_disc(a, disc.id, 14.0)


def test_assembly_spec_parametric_circle_honors_requested_radius(tmp_path):
    """The radius is the spec author's knob, NOT the catalog default: a default-10 nm catalog
    disc instanced with radius_nm=20 yields a ~20 nm disc (catches a driver that ignored
    params and re-used the saved default radius)."""
    _save_circle_primitive(tmp_path, "disc_primitive", default_radius_nm=10.0)
    a = hs.build_assembly(
        _circle_part_spec("disc_primitive", 20.0), primitives_dir=tmp_path
    )
    disc = next(i for i in a.instances if i.name == "disc")
    assert_part_is_circular_disc(a, disc.id, 20.0)


def test_parametric_circle_oracle_fires_on_wrong_radius(tmp_path):
    """can-go-red: asserting the wrong radius → the geometric circularity/radius oracle fails
    (the property check canonical_assembly is blind to)."""
    _save_circle_primitive(tmp_path, "disc_primitive", default_radius_nm=10.0)
    a = hs.build_assembly(
        _circle_part_spec("disc_primitive", 14.0), primitives_dir=tmp_path
    )
    disc = next(i for i in a.instances if i.name == "disc")
    with pytest.raises(AssertionError, match="radius"):
        assert_part_is_circular_disc(a, disc.id, 30.0)


def test_parametric_circle_oracle_fires_on_file_backed(tmp_path):
    """can-go-red: pointed at a STATIC (file-backed) instance, the inline guard fires — a
    parametric primitive that resolved to a file path would be the wrong build path (the saved
    default-radius disc instead of the requested one)."""
    _save_catalog_primitive(tmp_path, "beam_six", make_6hb_design())
    a = hs.build_assembly(_primitive_part_spec("beam_six"), primitives_dir=tmp_path)
    file_inst = next(i for i in a.instances if i.source.type == "file")
    with pytest.raises(AssertionError, match="not inline-backed"):
        assert_part_is_circular_disc(a, file_inst.id, 14.0)


def test_parametric_circle_requires_radius(tmp_path):
    """A circle-kind primitive with no radius_nm param fails the BUILD (the spec must declare
    its parametric intent — no silent fallback to the catalog default)."""
    _save_circle_primitive(tmp_path, "disc_primitive", default_radius_nm=10.0)
    spec = {
        "kind": "assembly",
        "name": "C",
        "parts": {"disc": {"from_primitive": "disc_primitive"}},
        "ops": [{"op": "add_part", "part": "disc"}],
    }
    with pytest.raises(BuildSpecError, match="requires a 'radius_nm' param"):
        hs.build_assembly(spec, primitives_dir=tmp_path)


def test_static_primitive_rejects_params(tmp_path):
    """Handing params to a STATIC (non-parametric) catalog primitive is meaningless and fails
    the build — params are only for parametric kinds."""
    _save_catalog_primitive(tmp_path, "beam_six", make_6hb_design())
    spec = {
        "kind": "assembly",
        "name": "C",
        "parts": {"saved": {"from_primitive": "beam_six", "params": {"radius_nm": 12}}},
        "ops": [{"op": "add_part", "part": "saved"}],
    }
    with pytest.raises(BuildSpecError, match="takes no params"):
        hs.build_assembly(spec, primitives_dir=tmp_path)


def test_assembly_spec_parametric_circle_roundtrips_stable(tmp_path):
    """The generatively-built inline disc survives a .nass round-trip (it's a valid, stable
    embedded part, lowering exactly as an inline DesignSpec part does)."""
    _save_circle_primitive(tmp_path, "disc_primitive", default_radius_nm=10.0)
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(
            lambda: hs.build_assembly(
                _circle_part_spec("disc_primitive", 14.0), primitives_dir=tmp_path
            )
        )


def _file_grid_spec(path):
    return {
        "kind": "assembly",
        "name": "FG",
        "parts": {"saved": {"from_file": path}},
        "ops": [
            {"op": "place_grid", "part": "saved", "rows": 1, "cols": 2, "pitch": 10.0}
        ],
    }


def test_instances_from_file_oracle_fires_on_wrong_topology(tmp_path):
    """can-go-red: a layout whose slots resolve to a DIFFERENT topology than expected is
    caught — the source pin every lattice oracle is blind to."""
    saved = make_6hb_design()
    a = hs.build_assembly(_file_grid_spec(_save_primitive(tmp_path, saved)))
    other = hs.build_design(
        {
            "lattice": "honeycomb",
            "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}],
        }
    )
    with pytest.raises(AssertionError, match="DIFFERENT topology"):
        assert_instances_from_file(a, canonical_topology(other))


def test_instances_from_file_oracle_rejects_inline_slot(tmp_path):
    """can-go-red: a layout where ONE slot is an embedded inline copy (defeating the
    by-reference purpose) is caught — a one-slot pin on the first instance would miss it."""
    saved = make_6hb_design()
    path = _save_primitive(tmp_path, saved)
    with hab.assembly_scratch_session():
        hab.new_assembly("Mixed")
        hab.place_file_grid(path, 1, 2, pitch=10.0)  # two file slots
        hab.add_inline_instance(make_6hb_design(), name="rogue")  # one embedded copy
        a = assembly_state.get_or_404().model_copy(deep=True)
    with pytest.raises(AssertionError, match="not file-backed"):
        assert_instances_from_file(a, canonical_topology(saved))


def test_instances_from_file_oracle_rejects_empty_selection(tmp_path):
    """can-go-red: an empty selection is a vacuous pass — the non-vacuity guard fires."""
    saved = make_6hb_design()
    a = hs.build_assembly(_file_grid_spec(_save_primitive(tmp_path, saved)))
    with pytest.raises(AssertionError, match="selected no instances"):
        assert_instances_from_file(a, canonical_topology(saved), instance_ids=[])


# ── gear op (AF-11 Phase 2 — assembly relations cluster) ──────────────────────
# A gear is a coupling relation; canonical_assembly DOES fingerprint gear_relations
# (the 5-tuple), so unlike loop_skip/bend/twist, assert_spec_matches_calls is
# LOAD-BEARING here (a dropped/rewired gear fails it). The geometric load-bearing
# pin that the gear actually DRIVES its coupled body is assert_gear_ratio: drive
# one side via the spec-built assembly and measure the other wheel's rotation.


def _geared_spec(*, ratio=2.0, invert=False):
    """A base + two wheels, each revolute-mated to the base about +Z, gear-coupled.
    Mirrors the AF-9 ``_geared_assembly`` hand fixture, declaratively."""
    gear = {"op": "gear", "joint_a": "ja", "joint_b": "jb", "ratio": ratio}
    if invert:
        gear["invert"] = True
    return {
        "kind": "assembly",
        "name": "G",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [
            {
                "op": "add_part",
                "part": "beam",
                "ref": "base",
                "connectors": [
                    {"label": "hub_a", "position": [0, 0, 0], "normal": [0, 0, 1]},
                    {"label": "hub_b", "position": [0, 0, 0], "normal": [0, 0, 1]},
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "wa",
                "transform": [20, 0, 0],
                "connectors": [
                    {"label": "axleA", "position": [0, 0, 0], "normal": [0, 0, 1]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "wb",
                "transform": [40, 0, 0],
                "connectors": [
                    {"label": "axleB", "position": [0, 0, 0], "normal": [0, 0, 1]}
                ],
            },
            {
                "op": "mate",
                "child": "wa",
                "parent": "base",
                "child_label": "axleA",
                "parent_label": "hub_a",
                "joint_type": "revolute",
                "axis_direction": [0, 0, 1],
                "ref": "ja",
            },
            {
                "op": "mate",
                "child": "wb",
                "parent": "base",
                "child_label": "axleB",
                "parent_label": "hub_b",
                "joint_type": "revolute",
                "axis_direction": [0, 0, 1],
                "ref": "jb",
            },
            gear,
        ],
    }


def test_gear_spec_matches_hand_calls():
    """A gear spec builds the SAME canonical assembly as the equivalent hand calls.
    Load-bearing for a gear (unlike bend/twist/loop_skip) — canonical_assembly
    fingerprints gear_relations, so a dropped/rewired gear would fail this."""

    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("G")
            base = make_6hb_design()
            hab.add_inline_instance(base, name="base")
            hab.add_inline_instance(
                base, name="wa", transform=hab.translation(20, 0, 0)
            )
            hab.add_inline_instance(
                base, name="wb", transform=hab.translation(40, 0, 0)
            )
            a = assembly_state.get_or_404()
            base_id, wa_id, wb_id = (i.id for i in a.instances)
            hab.add_connector(base_id, "hub_a", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(base_id, "hub_b", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(wa_id, "axleA", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(wb_id, "axleB", position=[0, 0, 0], normal=[0, 0, 1])
            hab.define_mate(
                wa_id,
                base_id,
                child_label="axleA",
                parent_label="hub_a",
                joint_type="revolute",
                axis_direction=[0, 0, 1],
            )
            hab.define_mate(
                wb_id,
                base_id,
                child_label="axleB",
                parent_label="hub_b",
                joint_type="revolute",
                axis_direction=[0, 0, 1],
            )
            ja, jb = (j.id for j in assembly_state.get_or_404().joints)
            hab.define_gear(ja, jb, ratio=2.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_assembly(_geared_spec()), hand, kind="assembly"
    )


@pytest.mark.parametrize("ratio", [2.0, 0.5])
def test_gear_spec_drives_coupled_wheel_at_ratio(ratio):
    """Driving one joint of the spec-built gear rotates the coupled wheel by ratio×
    — proves ratio flowed spec → parser → hab.define_gear → propagated kinematics."""
    a = hs.build_assembly(_geared_spec(ratio=ratio))
    assert len(a.gear_relations) == 1
    rel = a.gear_relations[0]
    with hab.assembly_scratch_session():
        assembly_state.set_assembly(a)
        before = assembly_state.get_or_404().model_copy(deep=True)
        hab.drive_joint(rel.joint_a_id, math.radians(30.0))
        after = assembly_state.get_or_404()
        assert_gear_ratio(before, after, rel.id, expected_ratio=ratio)


def test_geared_spec_roundtrips_stable():
    """A spec-built geared assembly survives a .nass round-trip WITH its gear."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(
            lambda: hs.build_assembly(_geared_spec())
        )
    assert len(reloaded.gear_relations) == 1
    assert reloaded.gear_relations[0].ratio == 2.0


# ── belt op (AF-11 Phase 2 — assembly relations cluster, sub-op 2) ─────────────
# A belt is a coupling relation too; canonical_assembly fingerprints belt_paths (the
# 5-tuple), so — exactly like a gear — assert_spec_matches_calls is LOAD-BEARING (a
# dropped/rewired belt fails it). The kinematic pin that the belt actually DRIVES its
# coupled pulley is the SAME assert_gear_ratio oracle, handed the belt's synthetic
# coupling-relation id (f"__belt__{belt.id}") and expected_ratio = radius_a/radius_b —
# proving the belt→relation radius→ratio synthesis works (NOT a hand-passed ratio).


def _belted_spec(*, radius_a=2.0, radius_b=1.0):
    """A base + two pulleys, each revolute-mated to the base about +Z, belt-coupled.
    Mirrors the AF-9 ``_belted_assembly`` hand fixture, declaratively."""
    return {
        "kind": "assembly",
        "name": "B",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [
            {
                "op": "add_part",
                "part": "beam",
                "ref": "base",
                "connectors": [
                    {"label": "hub_a", "position": [0, 0, 0], "normal": [0, 0, 1]},
                    {"label": "hub_b", "position": [0, 0, 0], "normal": [0, 0, 1]},
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "pa",
                "transform": [20, 0, 0],
                "connectors": [
                    {"label": "axleA", "position": [0, 0, 0], "normal": [0, 0, 1]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "pb",
                "transform": [40, 0, 0],
                "connectors": [
                    {"label": "axleB", "position": [0, 0, 0], "normal": [0, 0, 1]}
                ],
            },
            {
                "op": "mate",
                "child": "pa",
                "parent": "base",
                "child_label": "axleA",
                "parent_label": "hub_a",
                "joint_type": "revolute",
                "axis_direction": [0, 0, 1],
                "ref": "ja",
            },
            {
                "op": "mate",
                "child": "pb",
                "parent": "base",
                "child_label": "axleB",
                "parent_label": "hub_b",
                "joint_type": "revolute",
                "axis_direction": [0, 0, 1],
                "ref": "jb",
            },
            {
                "op": "belt",
                "joint_a": "ja",
                "joint_b": "jb",
                "radius_a": radius_a,
                "radius_b": radius_b,
            },
        ],
    }


def test_belt_spec_matches_hand_calls():
    """A belt spec builds the SAME canonical assembly as the equivalent hand calls.
    Load-bearing for a belt (like a gear) — canonical_assembly fingerprints
    belt_paths, so a dropped/rewired belt would fail this."""

    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("B")
            base = make_6hb_design()
            hab.add_inline_instance(base, name="base")
            hab.add_inline_instance(
                base, name="pa", transform=hab.translation(20, 0, 0)
            )
            hab.add_inline_instance(
                base, name="pb", transform=hab.translation(40, 0, 0)
            )
            a = assembly_state.get_or_404()
            base_id, pa_id, pb_id = (i.id for i in a.instances)
            hab.add_connector(base_id, "hub_a", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(base_id, "hub_b", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(pa_id, "axleA", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(pb_id, "axleB", position=[0, 0, 0], normal=[0, 0, 1])
            hab.define_mate(
                pa_id,
                base_id,
                child_label="axleA",
                parent_label="hub_a",
                joint_type="revolute",
                axis_direction=[0, 0, 1],
            )
            hab.define_mate(
                pb_id,
                base_id,
                child_label="axleB",
                parent_label="hub_b",
                joint_type="revolute",
                axis_direction=[0, 0, 1],
            )
            ja, jb = (j.id for j in assembly_state.get_or_404().joints)
            hab.define_belt(ja, jb, radius_a=2.0, radius_b=1.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_assembly(_belted_spec()), hand, kind="assembly"
    )


@pytest.mark.parametrize("radius_a,radius_b", [(2.0, 1.0), (3.0, 1.0)])
def test_belt_spec_drives_coupled_pulley_at_radius_ratio(radius_a, radius_b):
    """Driving one pulley of the spec-built belt rotates the coupled pulley by
    radius_a/radius_b× — proves the radii flowed spec → parser → hab.define_belt →
    _belt_to_relation → propagated kinematics (NOT a hand-passed gear ratio)."""
    a = hs.build_assembly(_belted_spec(radius_a=radius_a, radius_b=radius_b))
    assert len(a.belt_paths) == 1
    belt = a.belt_paths[0]
    rel_id = f"__belt__{belt.id}"
    with hab.assembly_scratch_session():
        assembly_state.set_assembly(a)
        before = assembly_state.get_or_404().model_copy(deep=True)
        hab.drive_joint(belt.pulley_a.joint_id, math.radians(30.0))
        after = assembly_state.get_or_404()
        assert_gear_ratio(before, after, rel_id, expected_ratio=radius_a / radius_b)


def test_belted_spec_roundtrips_stable():
    """A spec-built belted assembly survives a .nass round-trip WITH its belt."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(
            lambda: hs.build_assembly(_belted_spec())
        )
    assert len(reloaded.belt_paths) == 1
    assert reloaded.belt_paths[0].pulley_a.radius == 2.0


# ── polymerize op (AF-11 Phase 2 — assembly relations cluster, sub-op 3) ───────
# Polymerize replicates a SINGLE seed mate into a chain of identical parts. Like
# gear/belt (and unlike loop_skip/bend/twist) the new copies + seam joints live in
# canonical_assembly, so assert_spec_matches_calls is LOAD-BEARING (a dropped copy or
# chain joint fails it). The geometric progression — that the copies actually march
# along the seed mate's repeat delta — is the orthogonal pin assert_polymer_chain adds.


def _polymerize_spec(*, count=4, direction="forward"):
    """A seed pair of identical parts, rigidly mated (B snapped so the seed repeat
    delta is a +10 nm X translation), then polymerized into a chain of ``count``.
    Mirrors the AF-9 ``_polymer_seed_assembly`` hand fixture, declaratively."""
    return {
        "kind": "assembly",
        "name": "P",
        "parts": {"beam": _BEAM_SPEC},
        "ops": [
            {
                "op": "add_part",
                "part": "beam",
                "ref": "A",
                "connectors": [
                    {"label": "t", "position": [5, 0, 0], "normal": [1, 0, 0]}
                ],
            },
            {
                "op": "add_part",
                "part": "beam",
                "ref": "B",
                "transform": [20, 0, 0],
                "connectors": [
                    {"label": "t", "position": [-5, 0, 0], "normal": [-1, 0, 0]}
                ],
            },
            {
                "op": "mate",
                "child": "B",
                "parent": "A",
                "child_label": "t",
                "parent_label": "t",
                "ref": "seed",
            },
            {
                "op": "polymerize",
                "joint": "seed",
                "count": count,
                "direction": direction,
            },
        ],
    }


def test_polymerize_spec_matches_hand_calls():
    """A polymerize spec builds the SAME canonical assembly as the equivalent hand
    calls. Load-bearing here (like gear/belt, unlike loop_skip/bend/twist) —
    canonical_assembly fingerprints instances + joints, so a dropped copy or replicated
    chain joint would fail this."""

    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("P")
            beam = make_6hb_design()
            hab.add_inline_instance(beam, name="A")
            hab.add_inline_instance(beam, name="B", transform=hab.translation(20, 0, 0))
            a = assembly_state.get_or_404()
            id_a, id_b = a.instances[0].id, a.instances[1].id
            hab.add_connector(id_a, "t", position=[5, 0, 0], normal=[1, 0, 0])
            hab.add_connector(id_b, "t", position=[-5, 0, 0], normal=[-1, 0, 0])
            hab.define_mate(id_b, id_a, child_label="t", parent_label="t")
            seed = assembly_state.get_or_404().joints[0].id
            hab.polymerize(seed, count=4, direction="forward")
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(
        lambda: hs.build_assembly(_polymerize_spec()), hand, kind="assembly"
    )


@pytest.mark.parametrize("count", [4, 6])
def test_polymerize_spec_lays_chain_on_repeat_lattice(count):
    """The spec-built chain places count-2 copies on the seed mate's delta lattice —
    proves count/direction flowed spec → parser → hab.polymerize and that the copies
    are a geometric progression (which assert_spec_matches_calls, structure-only,
    can't show: it sees that N instances exist, not that they march along the repeat)."""
    a = hs.build_assembly(_polymerize_spec(count=count, direction="forward"))
    assert len(a.instances) == count
    seed = a.joints[0]  # the seed mate; polymerize appends the chain joints after it
    seed_pair = {seed.instance_a_id, seed.instance_b_id}
    before = a.model_copy(
        update={
            "instances": [i for i in a.instances if i.id in seed_pair],
            "joints": [seed],
        }
    )
    delta = assert_polymer_chain(before, a, seed.id, count=count)
    # the repeat is the +10 nm X translation the seed mate's connector snap produced
    assert abs(float(delta[0, 3]) - 10.0) <= 0.01


def test_polymerized_spec_roundtrips_stable():
    """A spec-built polymer chain survives a .nass round-trip WITH all its copies +
    replicated seam joints — canonical_assembly fingerprints them, so a dropped copy
    would fail the round-trip oracle."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(
            lambda: hs.build_assembly(_polymerize_spec(count=4))
        )
    assert len(reloaded.instances) == 4
    assert len(reloaded.joints) == 3  # seed mate + 2 replicated chain joints


# ── declarative relaxed-structure constraints (AF-13 P3 → grammar) ─────────────
# build_and_check_design lowers a design spec's `constraints` block to
# check_relaxed_constraint verdicts against an oxDNA relaxation.  Against the mock
# (identity "relaxation" → the mean structure reproduces the design geometry) the
# verdicts are deterministic, so the spec path's verdict must equal a hand-driven
# check_relaxed_constraint — the load-bearing pin, because assert_spec_matches_calls
# (the canonical fingerprint) is blind to a physical-layer verdict.


@pytest.fixture
def mock_oxdna_traj(tmp_path, monkeypatch):
    """The multi-frame mock oxDNA binary (frames = steps//100) bound via $OXDNA_BIN —
    a production run pools frames into a mean structure + confidence."""
    p = tmp_path / "mock_oxdna_traj.py"
    p.write_text(_MOCK_OXDNA_TRAJ)
    p.chmod(p.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("OXDNA_BIN", str(p))
    return p


# A fully-sequenced (M13 scaffold + WC staples) 6hb the spec produces — oxDNA rejects
# any undefined base, so the design must be routed + sequenced (full_autostaple).
_SEQUENCED_OPS = [
    {"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"},
    {"op": "auto_scaffold"},
    {"op": "full_autostaple", "scaffold_name": "M13mp18"},
]


def _hand_verdict(design, constraint, workspace, *, steps=6000):
    """Relax `design` by hand → report one constraint (runtime-id landmarks) — the
    independent reference the grammar's reported verdict must match."""
    job = hox.run_relaxation(design, workspace, min_bp_retained=0.0)
    assert job.status is OxdnaStatus.completed, job.error
    hox.append_production(job.job_id, workspace, steps=steps)
    hox.wait_for_terminal(job.job_id, workspace)
    rmsf = hox.read_flexibility_map(job.job_id, workspace)
    return check_relaxed_constraint(constraint, rmsf)


def test_build_and_check_no_constraints_skips_relaxation():
    """A spec with no `constraints` block reports no verdicts and runs no oxDNA (the
    workspace is never touched), so it needs no mock binary."""
    result = hs.build_and_check_design(
        {"lattice": "honeycomb", "ops": _SEQUENCED_OPS}, "/no/such/workspace"
    )
    assert result["verdicts"] == []
    assert len(result["design"].helices) == 6


def test_build_and_check_reports_radius_of_gyration(tmp_path, mock_oxdna_traj):
    """The grammar's `constraints` block reports the SAME radius_of_gyration verdict a
    hand-driven check_relaxed_constraint does — the load-bearing pin (the canonical
    fingerprint cannot see a physical-layer verdict)."""
    constraint = {"measure": "radius_of_gyration", "target_nm": 100.0, "tol_nm": 200.0}
    spec = {"lattice": "honeycomb", "ops": _SEQUENCED_OPS, "constraints": [constraint]}
    spec_result = hs.build_and_check_design(
        spec, tmp_path, steps=6000, min_bp_retained=0.0
    )
    # hand reference: same build, relax by hand, report the same (landmark-free) constraint
    hand = _hand_verdict(
        hs.build_design({"lattice": "honeycomb", "ops": _SEQUENCED_OPS}),
        constraint,
        tmp_path,
    )
    assert_spec_constraints_reported(spec_result, [hand])
    # the wide tolerance certifies a met verdict at full confidence (6000 // 100 frames)
    assert spec_result["verdicts"][0]["status"] == "met"
    assert spec_result["verdicts"][0]["n_frames"] == 60


def test_build_and_check_resolves_end_to_end_landmarks(tmp_path, mock_oxdna_traj):
    """end_to_end landmarks name a helix by grid_pos; the driver resolves them to the
    built design's runtime helix ids and reports the same verdict a hand check (with
    runtime-id landmarks) does — proving landmark resolution, not just attach+report."""
    spec_lm = [
        {"helix": [0, 1], "bp_index": 0, "direction": "forward"},
        {"helix": [0, 1], "bp_index": 40, "direction": "forward"},
    ]
    constraint = {
        "measure": "end_to_end",
        "landmarks": spec_lm,
        "target_nm": 100.0,
        "tol_nm": 200.0,
    }
    spec = {"lattice": "honeycomb", "ops": _SEQUENCED_OPS, "constraints": [constraint]}
    spec_result = hs.build_and_check_design(
        spec, tmp_path, steps=6000, min_bp_retained=0.0
    )
    # hand reference: resolve grid (0,1) → runtime id on a hand build, same bp landmarks
    hand_design = hs.build_design({"lattice": "honeycomb", "ops": _SEQUENCED_OPS})
    hid = next(h.id for h in hand_design.helices if tuple(h.grid_pos) == (0, 1))
    hand_constraint = {
        "measure": "end_to_end",
        "target_nm": 100.0,
        "tol_nm": 200.0,
        "landmarks": [(hid, 0, "FORWARD"), (hid, 40, "FORWARD")],
    }
    hand = _hand_verdict(hand_design, hand_constraint, tmp_path)
    assert_spec_constraints_reported(spec_result, [hand])
    # the spec landmark resolved to a real, non-degenerate measurement
    assert spec_result["verdicts"][0]["measured_nm"] > 1.0


def test_build_and_check_unknown_grid_pos_raises(tmp_path):
    """A constraint landmark naming a grid cell no op created fails FAST (before any
    oxDNA run, so no mock binary is needed) — the analog of nick/ligate's
    unknown-grid_pos guard."""
    constraint = {
        "measure": "end_to_end",
        "target_nm": 1.0,
        "tol_nm": 1.0,
        "landmarks": [
            {"helix": [9, 9], "bp_index": 0, "direction": "forward"},
            {"helix": [9, 9], "bp_index": 5, "direction": "forward"},
        ],
    }
    spec = {"lattice": "honeycomb", "ops": _SEQUENCED_OPS, "constraints": [constraint]}
    with pytest.raises(BuildSpecError, match="no helix is there"):
        hs.build_and_check_design(spec, tmp_path, min_bp_retained=0.0)


# ── the optimize block: a knob lowered to the closed iterate_to_constraint loop ──
# build_and_optimize_design varies a bend-curvature knob until the relaxed end-to-end
# lands on target — a CLOSED convergence loop the canonical fingerprint can't see, so
# assert_converges_to_constraint is the load-bearing pin (mirrors AF-13 P4's capstone,
# now driven entirely from a declarative spec).  Identity mock → the relaxed mean
# reproduces the design geometry, so the bend (a real topology edit) is what moves the
# measured end-to-end, exactly as a GPU run's physics would.  Probed monotone profile on
# h_XY_1_2 (bp0 fwd → bp41 rev): kappa 2.0 -> 12.68 nm, 2.5 -> 12.06, 3.0 -> 11.32.

# A fully-sequenced 6hb with a bend op (index 1) whose curvature is the knob.  The bend
# survives auto_scaffold + full_autostaple (it's a geometric overlay, independent of the
# strand routing the sequencing does).
_OPT_BEND_OPS = [
    {"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"},
    {"op": "bend", "plane_a_bp": 2, "plane_b_bp": 39, "curvature_deg_per_bp": 2.0},
    {"op": "auto_scaffold"},
    {"op": "full_autostaple", "scaffold_name": "M13mp18"},
]
_OPT_LANDMARKS = [
    {"helix": [1, 2], "bp_index": 0, "direction": "forward"},
    {"helix": [1, 2], "bp_index": 41, "direction": "reverse"},
]


def _optimize_spec(*, target=12.0, tol=0.5, initial=2.0, min_confidence=50):
    return {
        "lattice": "honeycomb",
        "ops": _OPT_BEND_OPS,
        "optimize": {
            "knob": {
                "op": 1,
                "param": "curvature_deg_per_bp",
                "lo": 0.0,
                "hi": 4.0,
                "initial": initial,
                "response": "decreasing",
            },
            "constraint": {
                "measure": "end_to_end",
                "landmarks": _OPT_LANDMARKS,
                "target_nm": target,
                "tol_nm": tol,
                "min_confidence": min_confidence,
            },
        },
    }


def test_build_and_optimize_converges(tmp_path, mock_oxdna_traj):
    """THE AUGMENT: the optimize block lowers a bend-curvature knob to the closed
    iterate_to_constraint loop and converges the relaxed end-to-end onto the target,
    every verdict confidence-gated.  assert_converges_to_constraint is load-bearing
    here: assert_spec_matches_calls (the canonical fingerprint) is blind both to the
    bend overlay and to a physical-layer convergence — only this proves the grammar
    lowered the knob + constraint to a real, converging loop."""
    result = hs.build_and_optimize_design(
        _optimize_spec(target=12.0, tol=0.5, initial=2.0),
        tmp_path,
        production_steps=6000,
        min_bp_retained=0.0,
    )
    assert_converges_to_constraint(
        result, target_nm=12.0, tol_nm=0.5, min_confidence=50
    )
    assert result["status"] == "met"
    # the declared 'decreasing' sense → deterministic bisection: 2.0 (12.68, too high)
    # → 3.0 (11.32, too low) → 2.5 (12.06, met).  Proves the grammar lowered the
    # monotone response to the correct bisection direction, not just "a loop ran".
    assert result["knob"]["value"] == pytest.approx(2.5)
    assert len(result["iterations"]) == 3
    assert all(it["production_rounds"] == 1 for it in result["iterations"])


def test_build_and_optimize_oracle_fires_on_unreachable(tmp_path, mock_oxdna_traj):
    """can-go-red: a target below any reachable end-to-end (the profile bottoms at
    ~9.58 nm) → the loop exhausts its budget and the convergence oracle raises."""
    result = hs.build_and_optimize_design(
        _optimize_spec(target=2.0, tol=0.3, initial=2.0),
        tmp_path,
        max_iterations=5,
        production_steps=6000,
        min_bp_retained=0.0,
    )
    assert result["status"] == "exhausted"
    with pytest.raises(AssertionError, match="did not converge"):
        assert_converges_to_constraint(
            result, target_nm=2.0, tol_nm=0.3, min_confidence=50
        )


def test_build_and_optimize_oracle_fires_on_vacuous(tmp_path, mock_oxdna_traj):
    """can-go-red: an initial knob that already meets the constraint → the loop
    'converges' on attempt 0 with no adjustment, and the non-vacuity guard fires."""
    result = hs.build_and_optimize_design(
        _optimize_spec(target=12.06, tol=0.5, initial=2.5),
        tmp_path,
        production_steps=6000,
        min_bp_retained=0.0,
    )
    assert result["status"] == "met"
    with pytest.raises(AssertionError, match="vacuous|FIRST attempt"):
        assert_converges_to_constraint(
            result, target_nm=12.06, tol_nm=0.5, min_confidence=50
        )


def test_build_and_optimize_requires_optimize_block(tmp_path):
    """A spec with no optimize block raises at parse time (before any build/relax) —
    build_and_check_design is the attach+report path, this is the knob path."""
    with pytest.raises(BuildSpecError, match="requires an 'optimize' block"):
        hs.build_and_optimize_design(
            {"lattice": "honeycomb", "ops": _OPT_BEND_OPS},
            tmp_path,
            min_bp_retained=0.0,
        )


# ── coverage: this driver wraps no new route (composition-sugar item) ──────────


def test_spec_build_adds_no_coverage():
    """AF-11 composes already-covered wrappers — like AF-10, it moves the oracle
    count, not the route-coverage count."""
    from tests.automation_harness import headless_coverage_report

    # crossover_extra_bases added the single + batch extra-bases PATCH routes: 39 -> 41.
    # AF-14 Phase 1's place_cluster_joint added one route (add_joint): 34 → 35;
    # the full_sequence feature added assign_staple_sequences: 35 → 36;
    # the periodic straggler added polymerize_periodic_assembly: 36 → 37;
    # AF-25's seek_features added /design/features/seek: 37 → 38;
    # AF-26's return_to_latest added /design/loadouts/{id}/select: 38 → 39.
    # crossover_extra_bases added the single + batch extra-bases PATCH routes: 39 → 41.
    # AF-27's connect_overhangs added create_overhang_connection: 41 → 42.
    # The hinge flexible-relax added flexible_relax: 42 → 43.
    # AF-31's place_crossover + delete_crossover added both: 43 → 45.
    # AF-32's force_ligate + delete_forced_ligation added both: 45 → 47.
    # AF-30's strand_end_resize added strand-end-resize: 47 → 48.
    # AF-27 P2's relax_overhang_connection + relax_bond added both: 48 → 50.
    # end-to-root binder added create_connection_version + apply_connection_version: 50 → 52.
    # AF-38's relax_overhang_binding + relax_end_to_root added both: 52 → 54.
    # Unifying direct connections (2026-06-30) dropped the /relax-end-to-root route +
    # its wrapper; relax_overhang_binding now covers both direct types (54 → 53).
    # Proposal-B duplex graph (2026-06-30): connect_duplex added /design/duplexes/connect: 53 → 54.
    # add_strand_extension added /design/extensions (fluorophore/modification): 54 → 55.
    # relax_duplex added /design/duplexes/{id}/relax (bound-duplex relax): 55 → 56.
    # AF-37's direct-binding CREATION added create/patch/delete_overhang_binding
    # + split_sub_domain + patch_sub_domain: 56 → 61.
    assert headless_coverage_report()["covered"] == 61
