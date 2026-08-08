"""Tests for the headless ASSEMBLY builder (AF-7, Tier 3 Phase 1).

``backend.api.headless_assembly_build`` is the mouse-free surface over the
``/assembly/*`` routes — the assembly analog of ``headless_build``.  These pins
prove a scripted assembly (create → place inline/file parts → resolve) builds the
right structure and survives a ``.nass`` round-trip, via the new reusable oracle
``assert_assembly_roundtrip_stable``.
"""

from __future__ import annotations

import math

import pytest

from backend.api import assembly_state
from backend.api import headless_assembly_build as hab
from tests.automation_harness import (
    assert_assembly_roundtrip_stable,
    assert_binding_resolves,
    assert_gear_ratio,
    assert_instances_from_file,
    assert_instances_on_grid,
    assert_instances_on_ring,
    assert_mate_coincident,
    assert_periodic_chain_tiles,
    assert_polymer_chain,
    canonical_assembly,
    canonical_topology,
    headless_coverage_report,
)
from tests.conftest import make_6hb_design


def _two_part_assembly():
    """Active scratch assembly: two inline 6hb parts, the 2nd offset +20 nm in X."""
    hab.new_assembly("T")
    hab.add_inline_instance(make_6hb_design(), name="A")
    hab.add_inline_instance(
        make_6hb_design(),
        name="B",
        transform=hab.translation(20.0, 0.0, 0.0),
    )
    return assembly_state.get_or_404().model_copy(deep=True)


def _mated_assembly():
    """Active scratch assembly: parts A (origin) and B (+20 nm X) mated by a rigid
    joint between connectors offset ±5 nm from their part origins.  The snap pulls
    B in so the connectors meet at world (5,0,0); B's origin lands at (10,0,0)."""
    hab.new_assembly("M")
    hab.add_inline_instance(make_6hb_design(), name="A")
    hab.add_inline_instance(
        make_6hb_design(),
        name="B",
        transform=hab.translation(20.0, 0.0, 0.0),
    )
    a = assembly_state.get_or_404()
    id_a, id_b = a.instances[0].id, a.instances[1].id
    hab.add_connector(id_a, "mate_a", position=[5.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0])
    hab.add_connector(
        id_b, "mate_b", position=[-5.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0]
    )
    hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
    return assembly_state.get_or_404().model_copy(deep=True)


# ── Construction + the round-trip oracle ──────────────────────────────────────


def test_inline_assembly_roundtrips_stable():
    """A two-part inline assembly validates and survives a .nass round-trip."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(_two_part_assembly)
        assert len(reloaded.instances) == 2
        # the inline part designs travelled inside the payload
        assert all(inst.source.type == "inline" for inst in reloaded.instances)
        assert all(inst.source.design.helices for inst in reloaded.instances)


def test_placement_transform_survives_roundtrip():
    """The world transform of a placed part is preserved exactly across import."""
    with hab.assembly_scratch_session():
        a = _two_part_assembly()
        # The offset part's transform carries +20 in the translation column (idx 3).
        offset = next(i for i in a.instances if i.name == "B")
        assert offset.transform.values[3] == 20.0
        from tests.automation_harness import roundtrip_nass

        rt = roundtrip_nass(a)
        rt_offset = next(i for i in rt.instances if i.name == "B")
        assert rt_offset.transform.values[3] == 20.0


def test_canonical_assembly_is_order_independent():
    """Reordering the instance list does not change the fingerprint."""
    with hab.assembly_scratch_session():
        a = _two_part_assembly()
        b = a.model_copy(update={"instances": list(reversed(a.instances))})
        assert canonical_assembly(a) == canonical_assembly(b)


def test_canonical_assembly_distinguishes_placement():
    """Moving a part to a different transform changes the fingerprint (so the
    round-trip oracle can detect a dropped/garbled placement)."""
    with hab.assembly_scratch_session():
        a = _two_part_assembly()
        moved = a.instances[0].model_copy(
            update={"transform": hab.translation(99.0, 0.0, 0.0)}
        )
        b = a.model_copy(update={"instances": [moved, a.instances[1]]})
        assert canonical_assembly(a) != canonical_assembly(b)


# ── resolve() is a clean no-op on a jointless assembly ─────────────────────────


def test_resolve_is_noop_without_joints():
    """resolve() on a Phase-1 (jointless) assembly leaves the structure unchanged."""
    with hab.assembly_scratch_session():
        a = _two_part_assembly()
        before = canonical_assembly(a)
        after = hab.resolve()
        assert canonical_assembly(after) == before


# ── File-source placement (structural) ────────────────────────────────────────


def test_add_file_instance_records_a_file_source():
    """add_file_instance places a PartSourceFile referencing the given path."""
    with hab.assembly_scratch_session():
        hab.new_assembly("F")
        a = hab.add_file_instance("Primitives/6hb.nadoc", name="lib-part")
        assert len(a.instances) == 1
        src = a.instances[0].source
        assert src.type == "file" and src.path == "Primitives/6hb.nadoc"


# ── Mates (AF-8): define_mate snaps connectors coincident ─────────────────────


def test_mate_makes_connectors_coincident():
    """define_mate snaps the child so its connector meets the parent's."""
    with hab.assembly_scratch_session():
        a = _mated_assembly()
        joint = a.joints[0]
        assert joint.joint_type == "rigid"
        assert joint.connector_a_label == "mate_a"
        assert joint.connector_b_label == "mate_b"
        disc = assert_mate_coincident(a, joint.id)
        assert disc <= 0.01


def test_mate_coincidence_survives_resolve():
    """The mate constraint still holds after an explicit resolve()."""
    with hab.assembly_scratch_session():
        _mated_assembly()
        resolved = hab.resolve().model_copy(deep=True)
        assert_mate_coincident(resolved, resolved.joints[0].id)


def test_mated_assembly_roundtrips_stable():
    """A mated assembly validates and survives a .nass round-trip with its joint."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(_mated_assembly)
        assert len(reloaded.joints) == 1
        # the mate is still coincident on the re-imported assembly
        assert_mate_coincident(reloaded, reloaded.joints[0].id)


def test_canonical_assembly_distinguishes_a_joint():
    """Dropping the mate changes the fingerprint, so the round-trip oracle would
    catch a lost joint."""
    with hab.assembly_scratch_session():
        a = _mated_assembly()
        jointless = a.model_copy(update={"joints": []})
        assert canonical_assembly(a) != canonical_assembly(jointless)


def test_assert_mate_coincident_fires_on_unmated_parts():
    """The oracle raises if the two connectors are NOT coincident — proving its
    green can go red.  Here B is shoved +30 nm in X AFTER the mate without a
    resolve, so the connectors separate."""
    with hab.assembly_scratch_session():
        a = _mated_assembly()
        joint = a.joints[0]
        moved_b = a.instances[1].model_copy(
            update={"transform": hab.translation(30.0, 0.0, 0.0)}
        )
        broken = a.model_copy(update={"instances": [a.instances[0], moved_b]})
        with pytest.raises(AssertionError, match="not coincident"):
            assert_mate_coincident(broken, joint.id)


# ── Gears (AF-9): a gear couples two revolute mates by a ratio ─────────────────


def _geared_assembly(*, ratio: float = 2.0, invert: bool = False):
    """Active scratch assembly: a base part + two wheels, each revolute-mated to the
    base about +Z through the world origin, then gear-coupled at ``ratio``.

    Returns ``(snapshot, rel_id, joint_a_id, joint_b_id)`` where ``snapshot`` is the
    deep-copied assembly *before* any joint is driven (the ``assembly_before`` the
    gear-ratio oracle compares against)."""
    hab.new_assembly("G")
    hab.add_inline_instance(make_6hb_design(), name="base")
    hab.add_inline_instance(
        make_6hb_design(), name="wheelA", transform=hab.translation(20.0, 0.0, 0.0)
    )
    hab.add_inline_instance(
        make_6hb_design(), name="wheelB", transform=hab.translation(40.0, 0.0, 0.0)
    )
    a = assembly_state.get_or_404()
    base_id, wa_id, wb_id = a.instances[0].id, a.instances[1].id, a.instances[2].id
    # Each wheel's hub (its local origin) mates to a hub point on the base (also the
    # base's local origin) → the snap stacks both wheels on the world origin and the
    # revolute axis passes through it along +Z.
    hab.add_connector(
        base_id, "hub_a", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
    )
    hab.add_connector(
        base_id, "hub_b", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
    )
    hab.add_connector(wa_id, "axleA", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.add_connector(wb_id, "axleB", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.define_mate(
        wa_id,
        base_id,
        child_label="axleA",
        parent_label="hub_a",
        joint_type="revolute",
        axis_direction=[0.0, 0.0, 1.0],
    )
    hab.define_mate(
        wb_id,
        base_id,
        child_label="axleB",
        parent_label="hub_b",
        joint_type="revolute",
        axis_direction=[0.0, 0.0, 1.0],
    )
    a = assembly_state.get_or_404()
    joint_a_id, joint_b_id = a.joints[0].id, a.joints[1].id
    hab.define_gear(joint_a_id, joint_b_id, ratio=ratio, invert=invert)
    a = assembly_state.get_or_404()
    return a.model_copy(deep=True), a.gear_relations[0].id, joint_a_id, joint_b_id


def test_gear_drives_coupled_wheel_at_ratio():
    """Driving joint_a rotates the gear-coupled wheel by ratio× as much (geometry)."""
    with hab.assembly_scratch_session():
        before, rel_id, ja, _jb = _geared_assembly(ratio=2.0)
        hab.drive_joint(ja, math.radians(30.0))
        after = assembly_state.get_or_404()
        measured = assert_gear_ratio(before, after, rel_id, expected_ratio=2.0)
        assert abs(measured - 2.0) <= 0.02


def test_gear_fractional_ratio():
    """A ratio < 1 makes the driven wheel turn less than the driver."""
    with hab.assembly_scratch_session():
        before, rel_id, ja, _jb = _geared_assembly(ratio=0.5)
        hab.drive_joint(ja, math.radians(60.0))
        after = assembly_state.get_or_404()
        assert_gear_ratio(before, after, rel_id, expected_ratio=0.5)


def test_gear_invert_flips_direction_same_magnitude():
    """invert flips the driven joint's SIGN but not the magnitude ratio."""
    with hab.assembly_scratch_session():
        before, rel_id, ja, jb = _geared_assembly(ratio=2.0, invert=True)
        hab.drive_joint(ja, math.radians(30.0))
        after = assembly_state.get_or_404()
        # the geometric magnitude ratio is unchanged by invert
        assert_gear_ratio(before, after, rel_id, expected_ratio=2.0)
        # but the driven joint's signed value is opposite the driver's
        ja_val = next(j for j in after.joints if j.id == ja).current_value
        jb_val = next(j for j in after.joints if j.id == jb).current_value
        assert ja_val > 0 and jb_val < 0


def test_gear_requires_revolute_joints():
    """A gear over two RIGID mates is rejected by the route (400)."""
    from fastapi import HTTPException

    with hab.assembly_scratch_session():
        a, _rel_id, ja, jb = _geared_assembly()
        # rebuild with rigid mates instead
        hab.new_assembly("R")
        hab.add_inline_instance(make_6hb_design(), name="base")
        hab.add_inline_instance(
            make_6hb_design(), name="A", transform=hab.translation(20.0, 0.0, 0.0)
        )
        hab.add_inline_instance(
            make_6hb_design(), name="B", transform=hab.translation(40.0, 0.0, 0.0)
        )
        a = assembly_state.get_or_404()
        base_id, a_id, b_id = (i.id for i in a.instances)
        hab.add_connector(
            base_id, "h1", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
        )
        hab.add_connector(
            base_id, "h2", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
        )
        hab.add_connector(a_id, "c", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
        hab.add_connector(b_id, "c", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
        hab.define_mate(a_id, base_id, child_label="c", parent_label="h1")  # rigid
        hab.define_mate(b_id, base_id, child_label="c", parent_label="h2")  # rigid
        a = assembly_state.get_or_404()
        with pytest.raises(HTTPException) as exc:
            hab.define_gear(a.joints[0].id, a.joints[1].id, ratio=2.0)
        assert exc.value.status_code == 400


def test_geared_assembly_roundtrips_stable():
    """A geared assembly validates and survives a .nass round-trip WITH its gear —
    canonical_assembly now fingerprints gear relations, so a dropped gear would
    fail the round-trip oracle."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(
            lambda: _geared_assembly(ratio=2.0)[0]
        )
        assert len(reloaded.gear_relations) == 1
        assert reloaded.gear_relations[0].ratio == 2.0


def test_canonical_assembly_distinguishes_a_gear():
    """Dropping the gear changes the fingerprint (so the round-trip oracle catches a
    lost gear relation)."""
    with hab.assembly_scratch_session():
        a, _rel_id, _ja, _jb = _geared_assembly()
        gearless = a.model_copy(update={"gear_relations": []})
        assert canonical_assembly(a) != canonical_assembly(gearless)


# ── Belts (AF-9): a belt couples two revolute pulleys by their rim-radius ratio ─


def _belted_assembly(*, radius_a: float = 2.0, radius_b: float = 1.0):
    """Active scratch assembly: a base part + two wheels, each revolute-mated to the
    base about +Z through the world origin, then belt-coupled with rim radii
    ``radius_a`` / ``radius_b`` → angular ratio ``radius_a / radius_b``.

    Returns ``(snapshot, belt_rel_id, joint_a_id, joint_b_id)`` where ``snapshot`` is
    the deep-copied assembly *before* any joint is driven and ``belt_rel_id`` is the
    belt's synthetic coupling-relation id (``f"__belt__{belt.id}"``) the gear-ratio
    oracle takes.  Mirrors ``_geared_assembly`` but defines a belt, not a gear."""
    hab.new_assembly("Belt")
    hab.add_inline_instance(make_6hb_design(), name="base")
    hab.add_inline_instance(
        make_6hb_design(), name="pulleyA", transform=hab.translation(20.0, 0.0, 0.0)
    )
    hab.add_inline_instance(
        make_6hb_design(), name="pulleyB", transform=hab.translation(40.0, 0.0, 0.0)
    )
    a = assembly_state.get_or_404()
    base_id, wa_id, wb_id = a.instances[0].id, a.instances[1].id, a.instances[2].id
    hab.add_connector(
        base_id, "hub_a", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
    )
    hab.add_connector(
        base_id, "hub_b", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
    )
    hab.add_connector(wa_id, "axleA", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.add_connector(wb_id, "axleB", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.define_mate(
        wa_id,
        base_id,
        child_label="axleA",
        parent_label="hub_a",
        joint_type="revolute",
        axis_direction=[0.0, 0.0, 1.0],
    )
    hab.define_mate(
        wb_id,
        base_id,
        child_label="axleB",
        parent_label="hub_b",
        joint_type="revolute",
        axis_direction=[0.0, 0.0, 1.0],
    )
    a = assembly_state.get_or_404()
    joint_a_id, joint_b_id = a.joints[0].id, a.joints[1].id
    hab.define_belt(joint_a_id, joint_b_id, radius_a=radius_a, radius_b=radius_b)
    a = assembly_state.get_or_404()
    belt_rel_id = f"__belt__{a.belt_paths[0].id}"
    return a.model_copy(deep=True), belt_rel_id, joint_a_id, joint_b_id


def test_belt_drives_coupled_pulley_at_radius_ratio():
    """Driving pulley_a rotates the belt-coupled pulley_b by (r_a/r_b)× as much —
    the rim-radius ratio drives the coupling, via _belt_to_relation, NOT a hand-passed
    gear ratio (so this pins the belt→relation radius→ratio synthesis)."""
    with hab.assembly_scratch_session():
        before, rel_id, ja, _jb = _belted_assembly(radius_a=2.0, radius_b=1.0)
        hab.drive_joint(ja, math.radians(30.0))
        after = assembly_state.get_or_404()
        measured = assert_gear_ratio(before, after, rel_id, expected_ratio=2.0)
        assert abs(measured - 2.0) <= 0.02


def test_belt_ratio_from_unequal_radii():
    """A 3:1 rim-radius belt drives the small pulley 3× the large one."""
    with hab.assembly_scratch_session():
        before, rel_id, ja, _jb = _belted_assembly(radius_a=3.0, radius_b=1.0)
        hab.drive_joint(ja, math.radians(20.0))
        after = assembly_state.get_or_404()
        assert_gear_ratio(before, after, rel_id, expected_ratio=3.0)


def test_belt_requires_revolute_joints():
    """A belt over two RIGID mates is rejected by the route (400)."""
    from fastapi import HTTPException

    with hab.assembly_scratch_session():
        hab.new_assembly("R")
        hab.add_inline_instance(make_6hb_design(), name="base")
        hab.add_inline_instance(
            make_6hb_design(), name="A", transform=hab.translation(20.0, 0.0, 0.0)
        )
        hab.add_inline_instance(
            make_6hb_design(), name="B", transform=hab.translation(40.0, 0.0, 0.0)
        )
        a = assembly_state.get_or_404()
        base_id, a_id, b_id = (i.id for i in a.instances)
        hab.add_connector(
            base_id, "h1", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
        )
        hab.add_connector(
            base_id, "h2", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0]
        )
        hab.add_connector(a_id, "c", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
        hab.add_connector(b_id, "c", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
        hab.define_mate(a_id, base_id, child_label="c", parent_label="h1")  # rigid
        hab.define_mate(b_id, base_id, child_label="c", parent_label="h2")  # rigid
        a = assembly_state.get_or_404()
        with pytest.raises(HTTPException) as exc:
            hab.define_belt(a.joints[0].id, a.joints[1].id, radius_a=2.0, radius_b=1.0)
        assert exc.value.status_code == 400


def test_belted_assembly_roundtrips_stable():
    """A belted assembly validates and survives a .nass round-trip WITH its belt —
    canonical_assembly now fingerprints belt_paths, so a dropped belt would fail the
    round-trip oracle."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(
            lambda: _belted_assembly(radius_a=2.0, radius_b=1.0)[0]
        )
        assert len(reloaded.belt_paths) == 1
        assert reloaded.belt_paths[0].pulley_a.radius == 2.0


def test_canonical_assembly_distinguishes_a_belt():
    """Dropping the belt changes the fingerprint (so the round-trip oracle catches a
    lost belt path)."""
    with hab.assembly_scratch_session():
        a, _rel_id, _ja, _jb = _belted_assembly()
        beltless = a.model_copy(update={"belt_paths": []})
        assert canonical_assembly(a) != canonical_assembly(beltless)


# ── Polymerize (AF-9): replicate a seed mate into a chain of identical parts ───


def _polymer_seed_assembly():
    """Active scratch: two *identical* inline parts mated rigidly, B snapped to
    (10,0,0).  Both instances embed the SAME design (so ``_sources_match`` is true and
    polymerize accepts the seed), with connectors offset ±5 nm so the rigid snap pulls
    B's origin to (10,0,0) → the seed repeat ``delta`` is a pure +10 nm X translation.

    Returns ``(snapshot_before_polymerize, seed_joint_id)``."""
    design = make_6hb_design()
    hab.new_assembly("P")
    hab.add_inline_instance(design, name="A")
    hab.add_inline_instance(design, name="B", transform=hab.translation(20.0, 0.0, 0.0))
    a = assembly_state.get_or_404()
    id_a, id_b = a.instances[0].id, a.instances[1].id
    hab.add_connector(id_a, "mate_a", position=[5.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0])
    hab.add_connector(
        id_b, "mate_b", position=[-5.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0]
    )
    hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
    a = assembly_state.get_or_404()
    return a.model_copy(deep=True), a.joints[0].id


def test_polymerize_grows_chain_on_repeat_lattice():
    """Forward polymerize to length 4 adds 2 copies, each on the seed's delta lattice."""
    with hab.assembly_scratch_session():
        before, seed_jid = _polymer_seed_assembly()
        hab.polymerize(seed_jid, count=4, direction="forward")
        after = assembly_state.get_or_404()
        assert len(after.instances) == 4  # seed pair (2) + 2 new copies
        delta = assert_polymer_chain(before, after, seed_jid, count=4)
        # the repeat is the +10 nm X translation the mate produced
        assert abs(float(delta[0, 3]) - 10.0) <= 0.01


def test_polymerize_longer_chain():
    """A length-6 forward chain places 4 new copies, all on the lattice."""
    with hab.assembly_scratch_session():
        before, seed_jid = _polymer_seed_assembly()
        hab.polymerize(seed_jid, count=6, direction="forward")
        after = assembly_state.get_or_404()
        assert len(after.instances) == 6
        assert_polymer_chain(before, after, seed_jid, count=6)


def test_polymerize_count_2_is_noop():
    """count == 2 is the existing pair — polymerize adds nothing."""
    with hab.assembly_scratch_session():
        before, seed_jid = _polymer_seed_assembly()
        hab.polymerize(seed_jid, count=2, direction="forward")
        after = assembly_state.get_or_404()
        assert len(after.instances) == 2
        assert_polymer_chain(before, after, seed_jid, count=2)


def test_polymerize_requires_identical_parts():
    """The route 422s if the seed mate joins two structurally-different parts."""
    from fastapi import HTTPException
    from tests.conftest import make_18hb_design

    with hab.assembly_scratch_session():
        hab.new_assembly("Mixed")
        hab.add_inline_instance(make_6hb_design(), name="A")
        hab.add_inline_instance(
            make_18hb_design(), name="B", transform=hab.translation(20.0, 0.0, 0.0)
        )
        a = assembly_state.get_or_404()
        id_a, id_b = a.instances[0].id, a.instances[1].id
        hab.add_connector(
            id_a, "mate_a", position=[5.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0]
        )
        hab.add_connector(
            id_b, "mate_b", position=[-5.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0]
        )
        hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
        a = assembly_state.get_or_404()
        with pytest.raises(HTTPException) as exc:
            hab.polymerize(a.joints[0].id, count=4)
        assert exc.value.status_code == 422


def test_polymerized_assembly_roundtrips_stable():
    """A polymerized chain validates and survives a .nass round-trip with all its new
    instances + seam joints — canonical_assembly fingerprints them, so a dropped copy
    would fail the round-trip oracle."""

    def _build():
        _before, seed_jid = _polymer_seed_assembly()
        hab.polymerize(seed_jid, count=4, direction="forward")
        return assembly_state.get_or_404().model_copy(deep=True)

    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(_build)
        assert len(reloaded.instances) == 4
        assert len(reloaded.joints) == 3  # seed mate + 2 replicated chain joints


# ── Overhang bindings (AF-9, cross-part WC metadata) ──────────────────────────


def _design_with_overhang(oh_id: str, sequence: str):
    """A part design carrying a real Helix + Strand whose domain tags ``oh_id``,
    plus the matching OverhangSpec (which auto-populates one sub-domain).

    ``grid_pos`` is set so ``canonical_topology`` (which sorts on it) works — the
    AF-5 ``grid_pos=None`` TypeError trap.  The id suffix (``_5p``/``_3p``) drives
    the strand direction, so the two parts get distinct canonical topologies."""
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import (
        Design,
        Direction,
        Domain,
        Helix,
        OverhangSpec,
        Strand,
        StrandType,
        Vec3,
    )

    length_bp = 8
    helix_id, strand_id = f"hx_{oh_id}", f"str_{oh_id}"
    helix = Helix(
        id=helix_id,
        grid_pos=(0, 0),
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0,
        length_bp=length_bp,
    )
    direction = Direction.FORWARD if oh_id.endswith("_5p") else Direction.REVERSE
    strand = Strand(
        id=strand_id,
        domains=[
            Domain(
                helix_id=helix_id,
                start_bp=0,
                end_bp=length_bp - 1,
                direction=direction,
                overhang_id=oh_id,
            )
        ],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(
        id=oh_id, helix_id=helix_id, strand_id=strand_id, sequence=sequence, label=oh_id
    )
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _bound_assembly():
    """Active scratch assembly: parts A/B each with one overhang, bound cross-part.

    Returns ``(before_bind_snapshot, after_bind_assembly, binding_id, sub_a, sub_b)``."""
    hab.new_assembly("Bind")
    da = _design_with_overhang("oh-A_5p", "ACGTACGT")
    db = _design_with_overhang("oh-B_3p", "GGGGCCCC")
    hab.add_inline_instance(da, name="PartA")
    hab.add_inline_instance(db, name="PartB", transform=hab.translation(10.0, 0.0, 0.0))
    a = assembly_state.get_or_404()
    ia, ib = a.instances[0], a.instances[1]
    sub_a = ia.source.design.overhangs[0].sub_domains[0].id
    sub_b = ib.source.design.overhangs[0].sub_domains[0].id
    before = a.model_copy(deep=True)
    hab.bind_overhangs(
        ia.id,
        ib.id,
        overhang_a_id="oh-A_5p",
        sub_domain_a_id=sub_a,
        overhang_b_id="oh-B_3p",
        sub_domain_b_id=sub_b,
    )
    after = assembly_state.get_or_404().model_copy(deep=True)
    return before, after, after.overhang_bindings[0].id, sub_a, sub_b


def test_bind_overhangs_resolves():
    """A headless binding's two endpoints each resolve to a real overhang sub-domain."""
    with hab.assembly_scratch_session():
        _before, after, bid, _sa, _sb = _bound_assembly()
        assert len(after.overhang_bindings) == 1
        assert_binding_resolves(after, bid)


def test_bound_assembly_roundtrips_stable_and_resolves():
    """A bound assembly validates, survives a .nass round-trip WITH its binding
    (canonical_assembly now fingerprints overhang_bindings), and the binding's
    endpoints still resolve against the re-imported part designs."""
    captured = {}

    def _build():
        _before, after, bid, _sa, _sb = _bound_assembly()
        captured["bid"] = bid
        return after

    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(_build)
        assert len(reloaded.overhang_bindings) == 1
        # the binding survived AND still points at live sub-domains post-import
        assert_binding_resolves(reloaded, captured["bid"])


def test_unbind_restores_fingerprint():
    """bind then unbind returns the assembly's canonical fingerprint to its
    pre-bind state (the binding inverse), and the binding is gone."""
    with hab.assembly_scratch_session():
        before, after, bid, _sa, _sb = _bound_assembly()
        assert canonical_assembly(after) != canonical_assembly(before)
        hab.unbind_overhangs(bid)
        unbound = assembly_state.get_or_404()
        assert unbound.overhang_bindings == []
        assert canonical_assembly(unbound) == canonical_assembly(before)


def test_canonical_assembly_distinguishes_a_binding():
    """A dropped/absent binding changes the fingerprint, so the round-trip oracle
    catches a binding lost across save/load."""
    with hab.assembly_scratch_session():
        _before, after, _bid, _sa, _sb = _bound_assembly()
        bindingless = after.model_copy(update={"overhang_bindings": []})
        assert canonical_assembly(after) != canonical_assembly(bindingless)


def test_patch_binding_changes_mode_and_fingerprint():
    """Patching binding_mode is reflected in both the model and the fingerprint."""
    with hab.assembly_scratch_session():
        _before, after, bid, _sa, _sb = _bound_assembly()
        assert after.overhang_bindings[0].binding_mode == "duplex"
        before_fp = canonical_assembly(after)
        hab.patch_binding(bid, binding_mode="toehold")
        patched = assembly_state.get_or_404()
        assert patched.overhang_bindings[0].binding_mode == "toehold"
        assert canonical_assembly(patched) != before_fp


def test_bind_overhangs_unknown_subdomain_404():
    """A binding referencing a non-existent sub-domain is rejected by the route."""
    from fastapi import HTTPException

    with hab.assembly_scratch_session():
        before, _after, _bid, _sa, _sb = _bound_assembly()
        # restart clean so only the bogus bind is attempted
        hab.new_assembly("Bind2")
        da = _design_with_overhang("oh-A_5p", "ACGTACGT")
        db = _design_with_overhang("oh-B_3p", "GGGGCCCC")
        hab.add_inline_instance(da, name="PartA")
        hab.add_inline_instance(
            db, name="PartB", transform=hab.translation(10.0, 0.0, 0.0)
        )
        a = assembly_state.get_or_404()
        sub_a = a.instances[0].source.design.overhangs[0].sub_domains[0].id
        with pytest.raises(HTTPException) as exc:
            hab.bind_overhangs(
                a.instances[0].id,
                a.instances[1].id,
                overhang_a_id="oh-A_5p",
                sub_domain_a_id=sub_a,
                overhang_b_id="oh-B_3p",
                sub_domain_b_id="not-a-real-subdomain",
            )
        assert exc.value.status_code == 404


# ── AF-10: parametric layout helpers (grid / ring) ───────────────────────────


def test_place_grid_lands_on_lattice():
    """place_grid drops rows×cols copies on the exact regular grid."""
    with hab.assembly_scratch_session():
        hab.new_assembly("Grid")
        part = make_6hb_design()
        hab.place_grid(part, 2, 3, pitch=15.0)
        a = assembly_state.get_or_404()
        assert len(a.instances) == 6
        assert_instances_on_grid(a, 2, 3, pitch=15.0)


def test_place_grid_distinct_row_pitch_and_roundtrips():
    """A rectangular grid (distinct row/col pitch) lands on the lattice AND
    survives a .nass round-trip with its 6 instances intact."""
    with hab.assembly_scratch_session():

        def build():
            hab.new_assembly("GridRT")
            hab.place_grid(make_6hb_design(), 2, 3, pitch=12.0, row_pitch=8.0)
            return assembly_state.get_or_404().model_copy(deep=True)

        reloaded = assert_assembly_roundtrip_stable(build)
        assert len(reloaded.instances) == 6
        assert_instances_on_grid(reloaded, 2, 3, pitch=12.0, row_pitch=8.0)


def test_place_ring_lands_on_ring():
    """place_ring drops n copies on the ring of the requested radius at even step."""
    with hab.assembly_scratch_session():
        hab.new_assembly("Ring")
        hab.place_ring(make_6hb_design(), 6, radius=20.0)
        a = assembly_state.get_or_404()
        assert len(a.instances) == 6
        assert_instances_on_ring(a, 6, radius=20.0)


def test_place_ring_offset_center_plane_and_roundtrips():
    """A ring in the XZ plane about an offset centre lands correctly AND survives a
    .nass round-trip."""
    with hab.assembly_scratch_session():

        def build():
            hab.new_assembly("RingRT")
            hab.place_ring(
                make_6hb_design(),
                5,
                radius=14.0,
                plane="XZ",
                center=(0.0, 30.0, 0.0),
            )
            return assembly_state.get_or_404().model_copy(deep=True)

        reloaded = assert_assembly_roundtrip_stable(build)
        assert len(reloaded.instances) == 5
        assert_instances_on_ring(
            reloaded,
            5,
            radius=14.0,
            plane="XZ",
            center=(0.0, 30.0, 0.0),
        )


# ── AF-12 follow-up: file-backed parametric layout (grid / ring by reference) ──


def _save_6hb(tmp_path):
    """Save a validated 6hb primitive as an absolute-path .nadoc (absolute so it
    resolves for both the from_file load AND the .nass round-trip flatten)."""
    saved = make_6hb_design()
    path = tmp_path / "primitive.nadoc"
    path.write_text(saved.to_json(), encoding="utf-8")
    return str(path), saved


def test_place_file_grid_lands_on_lattice_and_references_file(tmp_path):
    """place_file_grid drops rows×cols copies on the exact grid, and EVERY slot is a
    genuine file reference to the saved primitive (not rows·cols embedded copies)."""
    path, saved = _save_6hb(tmp_path)
    with hab.assembly_scratch_session():
        hab.new_assembly("FileGrid")
        hab.place_file_grid(path, 2, 3, pitch=15.0)
        a = assembly_state.get_or_404()
        assert len(a.instances) == 6
        assert all(i.source.type == "file" for i in a.instances)
        assert_instances_on_grid(a, 2, 3, pitch=15.0)  # lattice
        assert assert_instances_from_file(a, canonical_topology(saved)) == 6  # source


def test_place_file_grid_roundtrips_stable(tmp_path):
    """A file-backed rectangular grid lands on the lattice, every slot references the
    primitive, AND the whole thing survives a .nass round-trip."""
    path, saved = _save_6hb(tmp_path)
    with hab.assembly_scratch_session():

        def build():
            hab.new_assembly("FileGridRT")
            hab.place_file_grid(path, 2, 3, pitch=12.0, row_pitch=8.0)
            return assembly_state.get_or_404().model_copy(deep=True)

        reloaded = assert_assembly_roundtrip_stable(build)
        assert len(reloaded.instances) == 6
        assert_instances_on_grid(reloaded, 2, 3, pitch=12.0, row_pitch=8.0)
        assert_instances_from_file(reloaded, canonical_topology(saved))


def test_place_file_ring_lands_on_ring_and_references_file(tmp_path):
    """place_file_ring drops n copies on the ring, every slot a file reference."""
    path, saved = _save_6hb(tmp_path)
    with hab.assembly_scratch_session():
        hab.new_assembly("FileRing")
        hab.place_file_ring(path, 6, radius=20.0)
        a = assembly_state.get_or_404()
        assert len(a.instances) == 6
        assert_instances_on_ring(a, 6, radius=20.0)
        assert assert_instances_from_file(a, canonical_topology(saved)) == 6


# ── Periodic polymerize (single-part, derived repeat) ─────────────────────────


def _seam_for(h, L: int):
    """A periodic seam wrapping helix *h*'s far end onto its near end (low↔high bp).

    A forward strand presents its 3' at high bp / 5' at low bp; a reverse strand is
    antiparallel.  Mirrors ``tests/test_periodic_polymer.py``'s helper.
    """
    from backend.core.models import Direction, ForcedLigation

    if h.direction == Direction.FORWARD:
        return ForcedLigation(
            three_prime_helix_id=h.id,
            three_prime_bp=L - 1,
            three_prime_direction=Direction.FORWARD,
            five_prime_helix_id=h.id,
            five_prime_bp=0,
            five_prime_direction=Direction.FORWARD,
            is_periodic_seam=True,
        )
    return ForcedLigation(
        three_prime_helix_id=h.id,
        three_prime_bp=0,
        three_prime_direction=Direction.REVERSE,
        five_prime_helix_id=h.id,
        five_prime_bp=L - 1,
        five_prime_direction=Direction.REVERSE,
        is_periodic_seam=True,
    )


def _periodic_seed_design(L: int = 42, *, periodic: bool = True):
    """A 2-helix honeycomb bundle marked with ``is_periodic_seam`` end-to-end seams,
    so ``derive_periodic_delta`` can recover its repeat transform from one instance."""
    from backend.core.lattice import make_bundle_design
    from backend.core.models import LatticeType

    d = make_bundle_design(
        [(0, 0), (0, 1)], L, lattice_type=LatticeType.HONEYCOMB, strand_filter="both"
    )
    if periodic:
        d.forced_ligations = [_seam_for(d.helices[0], L), _seam_for(d.helices[1], L)]
    return d


def _periodic_chain(L: int = 42, *, count: int = 4, direction: str = "forward"):
    """Active scratch assembly: one periodic seed part, polymerized to ``count`` copies."""
    hab.new_assembly("Ring")
    hab.add_inline_instance(_periodic_seed_design(L), name="Seg")
    seed_id = assembly_state.get_or_404().instances[0].id
    hab.polymerize_periodic(seed_id, count=count, direction=direction)
    return assembly_state.get_or_404().model_copy(deep=True)


def test_periodic_polymerize_tiles_chain():
    """The derived repeat unit tiles the chain seamlessly at every junction."""
    with hab.assembly_scratch_session():
        a = _periodic_chain(count=4)
        assert len(a.instances) == 4
        out = assert_periodic_chain_tiles(a)
        assert out["n_junctions"] == 3
        # straight bundle → pure axial translation repeat, ~no rotation
        assert out["angle_deg"] < 1.0


def test_periodic_chain_both_directions_tiles():
    """direction='both' still tiles — the step magnitude is direction-agnostic."""
    with hab.assembly_scratch_session():
        a = _periodic_chain(count=5, direction="both")
        assert len(a.instances) == 5
        assert_periodic_chain_tiles(a)


def test_periodic_chain_roundtrips_stable():
    """A polymerized periodic chain validates and survives a .nass round-trip."""
    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(lambda: _periodic_chain(count=4))
        assert len(reloaded.instances) == 4


def test_periodic_polymerize_requires_a_seam():
    """A part with no periodic seam 422s (no repeat transform to derive)."""
    import pytest as _pytest
    from fastapi import HTTPException

    with hab.assembly_scratch_session():
        hab.new_assembly("NoSeam")
        hab.add_inline_instance(_periodic_seed_design(42, periodic=False), name="Plain")
        seed_id = assembly_state.get_or_404().instances[0].id
        with _pytest.raises(HTTPException) as exc:
            hab.polymerize_periodic(seed_id, count=4)
        assert exc.value.status_code == 422


# ── Coverage flip ─────────────────────────────────────────────────────────────


def test_assembly_routes_now_covered():
    """AF-7 flipped create/add-instance/resolve/import; AF-8 adds connector + mate;
    AF-9 adds gear-relations + the joint-drive PATCH + belt-paths + polymerize +
    the overhang-binding CRUD; the periodic straggler adds polymerize-periodic."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert {
        "create_assembly",
        "add_instance",
        "resolve_assembly",
        "import_assembly",
        "add_connector",
        "create_mate",
        "create_gear_relation",
        "patch_joint",
        "create_belt_path",
        "polymerize_assembly",
        "polymerize_periodic_assembly",
        "create_assembly_overhang_binding",
        "patch_assembly_overhang_binding",
        "delete_assembly_overhang_binding",
    } <= covered
