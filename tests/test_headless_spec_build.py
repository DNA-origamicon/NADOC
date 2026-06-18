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

import math

import pytest

from backend.api import assembly_state
from backend.api import headless_assembly_build as hab
from backend.api import headless_build as hb
from backend.api import headless_spec_build as hs
from backend.api import state as design_state
from backend.core.build_spec import BuildSpecError
from backend.core.models import LatticeType
from tests.automation_harness import (
    assert_assembly_roundtrip_stable,
    assert_circular_disc,
    assert_deformation_angle,
    assert_gear_ratio,
    assert_mate_coincident,
    assert_roundtrip_stable,
    assert_spec_matches_calls,
    canonical_topology,
    geometric_nucleotide_count,
    roundtrip_nadoc,
)
from tests.conftest import SIX_HB_CELLS, TEETH_CELLS, TEETH_PASSES, make_6hb_design

_CELLS = [list(c) for c in SIX_HB_CELLS]


# ── design interpreter ────────────────────────────────────────────────────────

def test_design_spec_builds_6hb():
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"}]}
    d = hs.build_design(spec)
    assert len(d.helices) == 6
    # the build carries a real, replayable feature log (drove the real wrapper)
    assert [e.op_kind for e in d.feature_log] == ["bundle-create"]


def test_design_spec_matches_hand_calls():
    """A bundle spec builds the SAME canonical topology as make_6hb_design()."""
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"}]}
    assert_spec_matches_calls(lambda: hs.build_design(spec), make_6hb_design, kind="design")


def test_teeth_spec_matches_hand_calls():
    """A bundle + extrude-passes spec reproduces the teeth fixture's hand build."""
    rise = hb.BDNA_RISE_PER_BP
    ops = [{"op": "bundle", "cells": [list(c) for c in TEETH_CELLS], "length_bp": 42, "name": "teeth"}]
    for i, n in enumerate(TEETH_PASSES, start=1):
        ops.append({"op": "extrude", "cells": [list(c) for c in TEETH_CELLS[:n]],
                    "length_bp": 42, "offset_nm": round(i * 42 * rise, 3)})
    spec = {"lattice": "square", "ops": ops}

    def hand():
        return hb.build_bundle(TEETH_CELLS, 42, lattice=LatticeType.SQUARE,
                               name="teeth", passes=TEETH_PASSES)

    assert_spec_matches_calls(lambda: hs.build_design(spec), hand, kind="design")


def test_design_spec_roundtrips_stable():
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": _CELLS, "length_bp": 42}]}
    assert_roundtrip_stable(lambda: hs.build_design(spec))


def test_design_spec_nick_ligate_is_identity():
    """nick then ligate (declarative, by grid_pos) restores the base topology."""
    base = {"lattice": "honeycomb", "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}]}
    nicked = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42},
        {"op": "nick", "helix": [0, 1], "bp_index": 20, "direction": "forward"},
        {"op": "ligate", "helix": [0, 1], "bp_index": 20, "direction": "forward"},
    ]}
    assert canonical_topology(hs.build_design(nicked)) == canonical_topology(hs.build_design(base))


def test_design_spec_nick_alone_changes_topology():
    """A nick (without the ligate) really mutates — proves the inverse test isn't vacuous."""
    base = {"lattice": "honeycomb", "ops": [{"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42}]}
    nicked = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 1], [1, 1]], "length_bp": 42},
        {"op": "nick", "helix": [0, 1], "bp_index": 20, "direction": "forward"},
    ]}
    assert canonical_topology(hs.build_design(nicked)) != canonical_topology(hs.build_design(base))


def test_nick_unknown_grid_pos_raises():
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 1]], "length_bp": 42},
        {"op": "nick", "helix": [9, 9], "bp_index": 5, "direction": "forward"},
    ]}
    with pytest.raises(BuildSpecError, match="no helix at grid position"):
        hs.build_design(spec)


def test_build_design_is_isolated():
    """A spec build runs in a scratch session — the default doc is untouched."""
    hb.new_design(LatticeType.HONEYCOMB)
    before = len(design_state.get_or_404().helices)
    hs.build_design({"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": _CELLS, "length_bp": 42}]})
    assert len(design_state.get_or_404().helices) == before


# ── deformation ops: bend / twist (AF-11 Phase 2) ─────────────────────────────
# NB: canonical_topology is BLIND to a deformation overlay (it lives outside the
# strand graph, like a loop/skip — the AF-3 lesson), so assert_spec_matches_calls
# confirms only that the underlying bundle topology is faithful. The load-bearing
# pin that the bend/twist op actually flowed through to the geometry is the
# geometric assert_deformation_angle below.

def _bend_spec(kappa=2.0):
    return {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 84, "name": "B"},
        {"op": "bend", "plane_a_bp": 20, "plane_b_bp": 60, "curvature_deg_per_bp": kappa}]}


def test_bend_spec_matches_hand_calls():
    """A bend spec builds the same bundle topology as the equivalent hand calls.
    (Weak by itself for the bend — canonical_topology can't see the deformation —
    but it pins the bundle plumbing; the angle is pinned separately below.)"""
    def hand():
        with hb.scratch_session(LatticeType.HONEYCOMB):
            hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
            hb.add_bend(20, 60, curvature_deg_per_bp=2.0)
            return design_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_design(_bend_spec()), hand, kind="design")


def test_bend_spec_realises_requested_curvature():
    """The bend op in the spec actually rotates the deformed frame by κ × (b − a)°
    — proves the parameter flowed spec → parser → hb.add_bend → DeformationOp."""
    d = hs.build_design(_bend_spec(kappa=2.0))
    assert d.feature_log[-1].feature_type == "deformation"
    assert_deformation_angle(d, 20, 60, 2.0 * (60 - 20), ref_helix_id=d.helices[0].id)


def test_twist_spec_total_degrees_realises_angle():
    """A twist spec (total_degrees) rotates the frame about its axis by θ°."""
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 84, "name": "B"},
        {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60, "total_degrees": 90}]}
    d = hs.build_design(spec)
    assert_deformation_angle(d, 20, 60, 90.0, ref_helix_id=d.helices[0].id)


def test_twist_spec_degrees_per_nm_realises_rate():
    """A twist spec (degrees_per_nm) rotates by r × span_nm degrees."""
    from backend.core.constants import BDNA_RISE_PER_BP

    rate = 30.0
    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 84, "name": "B"},
        {"op": "twist", "plane_a_bp": 20, "plane_b_bp": 60, "degrees_per_nm": rate}]}
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
    return {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [[0, 0]], "length_bp": 42, "name": "L"}]}


def _loop_spec(bp, delta):
    spec = _base_loop_spec()
    spec["ops"].append({"op": "loop_skip", "helix": [0, 0], "bp_index": bp, "delta": delta})
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

    assert_spec_matches_calls(lambda: hs.build_design(_loop_spec(bp, +1)), hand, kind="design")


def test_loop_spec_adds_one_bp_of_geometry():
    """A loop (+1) op in a spec adds exactly one bp of geometry to its helix
    (one nucleotide per strand) — proves delta flowed spec → parser → hb.loop_skip."""
    base = hs.build_design(_base_loop_spec())
    h = base.helices[0]
    looped = hs.build_design(_loop_spec(h.bp_start + 14, +1))
    hid = next(hh.id for hh in looped.helices if tuple(hh.grid_pos) == tuple(h.grid_pos))
    assert (geometric_nucleotide_count(looped, hid)
            - geometric_nucleotide_count(base, h.id)) == 2
    # the mark really landed in the spec-built design
    assert any(ls.delta for hh in looped.helices for ls in hh.loop_skips)


def test_skip_spec_removes_one_bp_of_geometry():
    """A skip (−1) op in a spec removes exactly one bp of geometry from its helix."""
    base = hs.build_design(_base_loop_spec())
    h = base.helices[0]
    skipped = hs.build_design(_loop_spec(h.bp_start + 14, -1))
    hid = next(hh.id for hh in skipped.helices if tuple(hh.grid_pos) == tuple(h.grid_pos))
    assert (geometric_nucleotide_count(skipped, hid)
            - geometric_nucleotide_count(base, h.id)) == -2


def test_loop_skip_spec_survives_roundtrip():
    """A spec-built loop/skip mark persists through a .nadoc save/load.

    canonical_topology is blind to loop/skips, so a structure round-trip can't prove
    persistence — the geometric count is what catches a silently-dropped mark."""
    base = hs.build_design(_base_loop_spec())
    looped = hs.build_design(_loop_spec(base.helices[0].bp_start + 14, +1))
    reloaded = roundtrip_nadoc(looped)
    assert geometric_nucleotide_count(reloaded) == geometric_nucleotide_count(looped)
    assert any(ls.delta for hh in reloaded.helices for ls in hh.loop_skips)


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

    assert_spec_matches_calls(lambda: hs.build_design(_circle_spec()), hand, kind="design")


@pytest.mark.parametrize("radius", [8.0, 10.6, 14.0])
def test_circle_segment_spec_builds_a_disc_of_the_requested_radius(radius):
    """The spec-built disc's placed geometry traces a circle of the requested radius
    — proves radius_nm flowed spec → parser → hb.circle_segment → placed helices."""
    d = hs.build_design(_circle_spec(radius))
    assert d.feature_log[-1].op_kind == "circle-segment"
    assert_circular_disc(d, radius)


def test_circle_segment_spec_roundtrips_stable():
    assert_roundtrip_stable(lambda: hs.build_design(_circle_spec()))


# ── assembly interpreter ──────────────────────────────────────────────────────

_BEAM_SPEC = {"lattice": "honeycomb", "ops": [
    {"op": "bundle", "cells": _CELLS, "length_bp": 42, "name": "6hb"}]}


def test_assembly_spec_grid_matches_hand_calls():
    spec = {"kind": "assembly", "name": "G", "parts": {"beam": _BEAM_SPEC},
            "ops": [{"op": "place_grid", "part": "beam", "rows": 2, "cols": 3, "pitch": 10.0}]}

    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("G")
            hab.place_grid(make_6hb_design(), 2, 3, pitch=10.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_assembly(spec), hand, kind="assembly")


def test_assembly_spec_grid_roundtrips_stable():
    spec = {"kind": "assembly", "name": "G", "parts": {"beam": _BEAM_SPEC},
            "ops": [{"op": "place_grid", "part": "beam", "rows": 2, "cols": 3, "pitch": 10.0}]}
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(lambda: hs.build_assembly(spec))


def test_assembly_spec_ring_roundtrips_stable():
    spec = {"kind": "assembly", "name": "R", "parts": {"beam": _BEAM_SPEC},
            "ops": [{"op": "place_ring", "part": "beam", "n": 5, "radius": 15.0}]}
    with hab.assembly_scratch_session():
        assert_assembly_roundtrip_stable(lambda: hs.build_assembly(spec))


def _mate_spec():
    return {"kind": "assembly", "name": "M", "parts": {"beam": _BEAM_SPEC}, "ops": [
        {"op": "add_part", "part": "beam", "ref": "A",
         "connectors": [{"label": "mate_a", "position": [5, 0, 0], "normal": [1, 0, 0]}]},
        {"op": "add_part", "part": "beam", "ref": "B", "transform": [20, 0, 0],
         "connectors": [{"label": "mate_b", "position": [-5, 0, 0], "normal": [-1, 0, 0]}]},
        {"op": "mate", "child": "B", "parent": "A", "child_label": "mate_b", "parent_label": "mate_a"},
    ]}


def test_assembly_spec_mate_matches_hand_calls():
    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("M")
            hab.add_inline_instance(make_6hb_design(), name="A")
            hab.add_inline_instance(make_6hb_design(), name="B", transform=hab.translation(20, 0, 0))
            a = assembly_state.get_or_404()
            id_a, id_b = a.instances[0].id, a.instances[1].id
            hab.add_connector(id_a, "mate_a", position=[5, 0, 0], normal=[1, 0, 0])
            hab.add_connector(id_b, "mate_b", position=[-5, 0, 0], normal=[-1, 0, 0])
            hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_assembly(_mate_spec()), hand, kind="assembly")


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
    return {"kind": "assembly", "name": "G", "parts": {"beam": _BEAM_SPEC}, "ops": [
        {"op": "add_part", "part": "beam", "ref": "base", "connectors": [
            {"label": "hub_a", "position": [0, 0, 0], "normal": [0, 0, 1]},
            {"label": "hub_b", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "add_part", "part": "beam", "ref": "wa", "transform": [20, 0, 0],
         "connectors": [{"label": "axleA", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "add_part", "part": "beam", "ref": "wb", "transform": [40, 0, 0],
         "connectors": [{"label": "axleB", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "mate", "child": "wa", "parent": "base", "child_label": "axleA",
         "parent_label": "hub_a", "joint_type": "revolute", "axis_direction": [0, 0, 1], "ref": "ja"},
        {"op": "mate", "child": "wb", "parent": "base", "child_label": "axleB",
         "parent_label": "hub_b", "joint_type": "revolute", "axis_direction": [0, 0, 1], "ref": "jb"},
        gear,
    ]}


def test_gear_spec_matches_hand_calls():
    """A gear spec builds the SAME canonical assembly as the equivalent hand calls.
    Load-bearing for a gear (unlike bend/twist/loop_skip) — canonical_assembly
    fingerprints gear_relations, so a dropped/rewired gear would fail this."""
    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("G")
            base = make_6hb_design()
            hab.add_inline_instance(base, name="base")
            hab.add_inline_instance(base, name="wa", transform=hab.translation(20, 0, 0))
            hab.add_inline_instance(base, name="wb", transform=hab.translation(40, 0, 0))
            a = assembly_state.get_or_404()
            base_id, wa_id, wb_id = (i.id for i in a.instances)
            hab.add_connector(base_id, "hub_a", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(base_id, "hub_b", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(wa_id, "axleA", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(wb_id, "axleB", position=[0, 0, 0], normal=[0, 0, 1])
            hab.define_mate(wa_id, base_id, child_label="axleA", parent_label="hub_a",
                            joint_type="revolute", axis_direction=[0, 0, 1])
            hab.define_mate(wb_id, base_id, child_label="axleB", parent_label="hub_b",
                            joint_type="revolute", axis_direction=[0, 0, 1])
            ja, jb = (j.id for j in assembly_state.get_or_404().joints)
            hab.define_gear(ja, jb, ratio=2.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_assembly(_geared_spec()), hand, kind="assembly")


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
        reloaded = assert_assembly_roundtrip_stable(lambda: hs.build_assembly(_geared_spec()))
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
    return {"kind": "assembly", "name": "B", "parts": {"beam": _BEAM_SPEC}, "ops": [
        {"op": "add_part", "part": "beam", "ref": "base", "connectors": [
            {"label": "hub_a", "position": [0, 0, 0], "normal": [0, 0, 1]},
            {"label": "hub_b", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "add_part", "part": "beam", "ref": "pa", "transform": [20, 0, 0],
         "connectors": [{"label": "axleA", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "add_part", "part": "beam", "ref": "pb", "transform": [40, 0, 0],
         "connectors": [{"label": "axleB", "position": [0, 0, 0], "normal": [0, 0, 1]}]},
        {"op": "mate", "child": "pa", "parent": "base", "child_label": "axleA",
         "parent_label": "hub_a", "joint_type": "revolute", "axis_direction": [0, 0, 1], "ref": "ja"},
        {"op": "mate", "child": "pb", "parent": "base", "child_label": "axleB",
         "parent_label": "hub_b", "joint_type": "revolute", "axis_direction": [0, 0, 1], "ref": "jb"},
        {"op": "belt", "joint_a": "ja", "joint_b": "jb",
         "radius_a": radius_a, "radius_b": radius_b},
    ]}


def test_belt_spec_matches_hand_calls():
    """A belt spec builds the SAME canonical assembly as the equivalent hand calls.
    Load-bearing for a belt (like a gear) — canonical_assembly fingerprints
    belt_paths, so a dropped/rewired belt would fail this."""
    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("B")
            base = make_6hb_design()
            hab.add_inline_instance(base, name="base")
            hab.add_inline_instance(base, name="pa", transform=hab.translation(20, 0, 0))
            hab.add_inline_instance(base, name="pb", transform=hab.translation(40, 0, 0))
            a = assembly_state.get_or_404()
            base_id, pa_id, pb_id = (i.id for i in a.instances)
            hab.add_connector(base_id, "hub_a", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(base_id, "hub_b", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(pa_id, "axleA", position=[0, 0, 0], normal=[0, 0, 1])
            hab.add_connector(pb_id, "axleB", position=[0, 0, 0], normal=[0, 0, 1])
            hab.define_mate(pa_id, base_id, child_label="axleA", parent_label="hub_a",
                            joint_type="revolute", axis_direction=[0, 0, 1])
            hab.define_mate(pb_id, base_id, child_label="axleB", parent_label="hub_b",
                            joint_type="revolute", axis_direction=[0, 0, 1])
            ja, jb = (j.id for j in assembly_state.get_or_404().joints)
            hab.define_belt(ja, jb, radius_a=2.0, radius_b=1.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_assembly(_belted_spec()), hand, kind="assembly")


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
        reloaded = assert_assembly_roundtrip_stable(lambda: hs.build_assembly(_belted_spec()))
    assert len(reloaded.belt_paths) == 1
    assert reloaded.belt_paths[0].pulley_a.radius == 2.0


# ── coverage: this driver wraps no new route (composition-sugar item) ──────────

def test_spec_build_adds_no_coverage():
    """AF-11 composes already-covered wrappers — like AF-10, it moves the oracle
    count, not the route-coverage count."""
    from tests.automation_harness import headless_coverage_report
    assert headless_coverage_report()["covered"] == 32
