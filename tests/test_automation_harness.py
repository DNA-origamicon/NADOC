"""Meta-tests for the design-automation validation spine (AF-1, Tier 0).

The harness IS the validation augment for AF-1, so these tests prove the augment
itself is trustworthy:

  - the round-trip oracle PASSES on well-formed headless builds (6hb, teeth), and
  - it actually FIRES (raises) when the round-trip corrupts the design — a green
    that can't go red would prove nothing, so we inject a corrupting round-trip
    and assert it's caught; and
  - the coverage report matches the live wrappers and lists real backlog routes.
"""
from __future__ import annotations

import pytest

from backend.core.models import LatticeType, StrandType
from tests.automation_harness import (
    assert_deformation_angle,
    assert_roundtrip_stable,
    canonical_topology,
    headless_coverage_report,
    roundtrip_nadoc,
)
from tests.conftest import make_6hb_design, make_teeth_design


# ── The oracle passes on good builds ──────────────────────────────────────────

@pytest.mark.parametrize("build_fn", [make_6hb_design, make_teeth_design])
def test_roundtrip_stable_on_clean_builds(build_fn):
    """A well-formed headless build survives export→import unchanged."""
    reloaded = assert_roundtrip_stable(build_fn)
    # sanity: we got a real design back, not the empty scratch design
    assert reloaded.helices and reloaded.strands


def test_roundtrip_nadoc_preserves_topology_fingerprint():
    """roundtrip_nadoc is identity on the topology fingerprint for a clean build."""
    built = make_6hb_design()
    assert canonical_topology(roundtrip_nadoc(built)) == canonical_topology(built)


def test_roundtrip_does_not_disturb_active_session():
    """The round-trip runs in a scratch doc — the default session is untouched."""
    from backend.api import headless_build

    sentinel = headless_build.new_design()  # active design = fresh empty
    before = canonical_topology(sentinel)
    roundtrip_nadoc(make_teeth_design())
    from backend.api import state as design_state
    assert canonical_topology(design_state.get_or_404()) == before


# ── The oracle FIRES on corruption (the load-bearing meta-test) ───────────────

def _drop_a_strand_roundtrip(design):
    """A deliberately buggy round-trip: faithfully reloads, then loses one strand.

    Stands in for a real export/import bug (a strand that doesn't survive a save).
    assert_roundtrip_stable MUST notice the topology changed and raise.
    """
    reloaded = roundtrip_nadoc(design)
    # mutate the standalone copy: drop the first staple strand
    victim = next(s for s in reloaded.strands if s.strand_type != StrandType.SCAFFOLD)
    reloaded.strands = [s for s in reloaded.strands if s.id != victim.id]
    return reloaded


def test_oracle_catches_corrupted_roundtrip():
    """If the round-trip changes topology, assert_roundtrip_stable raises."""
    with pytest.raises(AssertionError, match="changed the design topology"):
        assert_roundtrip_stable(make_6hb_design, roundtrip=_drop_a_strand_roundtrip)


def test_oracle_catches_invalid_build():
    """If the build itself doesn't validate, the oracle raises before round-tripping."""
    def _build_no_scaffold():
        d = make_6hb_design()
        for s in d.strands:
            s.strand_type = StrandType.STAPLE  # no scaffold strand left → invalid
        return d

    with pytest.raises(AssertionError, match="did not validate before round-trip"):
        assert_roundtrip_stable(_build_no_scaffold)


# ── The coverage audit reflects reality ───────────────────────────────────────

def test_coverage_report_shape_and_known_wrappers():
    report = headless_coverage_report()
    assert report["total"] == report["covered"] + report["uncovered"]
    assert report["covered"] >= 11  # the wrappers headless_build ships today
    assert report["uncovered"] > 0  # the AF backlog is non-empty

    covered_paths = {r["path"] for r in report["covered_routes"]}
    # core construction wrappers must register as covered
    assert any(p.endswith("/design/bundle") for p in covered_paths)
    assert any(p.endswith("/design/auto-break") for p in covered_paths)
    assert any("auto-scaffold-seamed" in p for p in covered_paths)


def test_coverage_report_lists_real_backlog_routes():
    """A still-unwrapped backlog route shows up as uncovered.

    AF-15 Phase 1 covered POST /design/cluster + PATCH /design/cluster/{id}, so this
    re-points to /design/strand-end-resize (a drag-arrow resize op with a coord route
    — headless-reachable, a later AF candidate) — still unwrapped today.
    """
    report = headless_coverage_report()
    covered_paths = {r["path"] for r in report["covered_routes"]}
    uncovered_paths = {r["path"] for r in report["uncovered_routes"]}
    assert any(p.endswith("/design/strand-end-resize") for p in uncovered_paths)
    assert not any(p.endswith("/design/strand-end-resize") for p in covered_paths)


def test_coverage_report_marks_af2_routes_covered():
    """AF-2 flipped nick/ligate/delete-strand from uncovered → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert {"add_nick", "ligate_strand", "delete_strand"} <= covered


def test_coverage_report_marks_af6_route_covered():
    """AF-6 flipped POST /design/deformation (add_deformation) → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert "add_deformation" in covered


def test_coverage_report_marks_af7_assembly_routes_covered():
    """AF-7's new headless_assembly_build module flips the core /assembly routes."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert {"create_assembly", "add_instance", "resolve_assembly"} <= covered


def test_coverage_report_marks_af8_mate_routes_covered():
    """AF-8 flipped add_connector + create_mate → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert {"add_connector", "create_mate"} <= covered


def test_coverage_report_marks_af9_gear_routes_covered():
    """AF-9 flipped create_gear_relation + patch_joint (drive) → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert {"create_gear_relation", "patch_joint"} <= covered


def test_oxdna_coverage_report_separate_from_design_assembly():
    """AF-13's physical-layer audit (oxdna_coverage_report) is scoped to /oxdna and
    does NOT perturb the design/assembly coverage number."""
    from tests.automation_harness import oxdna_coverage_report

    # AF-25 added seek_features (37→38); AF-26 added return_to_latest/select_loadout (38→39).
    # crossover_extra_bases added the single + batch extra-bases PATCH routes (39->41).
    assert headless_coverage_report()["covered"] == 41  # /oxdna audit is separate
    ox = oxdna_coverage_report()
    assert ox["total"] == ox["covered"] + ox["uncovered"]
    covered = {r["endpoint"] for r in ox["covered_routes"]}
    # AF-26 added roll_oxdna_job_design (roll_job_to_run_state wraps it).
    assert {"create_oxdna_job", "start_oxdna_job", "append_oxdna_production",
            "roll_oxdna_job_design"} <= covered


# ── The gear-ratio oracle PASSES on a real gear and FIRES otherwise ────────────

def _geared_build(*, ratio: float = 2.0):
    """Active scratch assembly: two wheels revolute-mated to a base about +Z and
    gear-coupled at ``ratio``.  Returns ``(before_snapshot, rel_id, joint_a_id)``."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("G")
    hab.add_inline_instance(make_6hb_design(), name="base")
    hab.add_inline_instance(
        make_6hb_design(), name="wheelA", transform=hab.translation(20.0, 0.0, 0.0))
    hab.add_inline_instance(
        make_6hb_design(), name="wheelB", transform=hab.translation(40.0, 0.0, 0.0))
    a = assembly_state.get_or_404()
    base_id, wa_id, wb_id = a.instances[0].id, a.instances[1].id, a.instances[2].id
    for label in ("hub_a", "hub_b"):
        hab.add_connector(base_id, label, position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.add_connector(wa_id, "axleA", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.add_connector(wb_id, "axleB", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.define_mate(wa_id, base_id, child_label="axleA", parent_label="hub_a",
                    joint_type="revolute", axis_direction=[0.0, 0.0, 1.0])
    hab.define_mate(wb_id, base_id, child_label="axleB", parent_label="hub_b",
                    joint_type="revolute", axis_direction=[0.0, 0.0, 1.0])
    a = assembly_state.get_or_404()
    ja, jb = a.joints[0].id, a.joints[1].id
    hab.define_gear(ja, jb, ratio=ratio)
    a = assembly_state.get_or_404()
    return a.model_copy(deep=True), a.gear_relations[0].id, ja, jb


def test_gear_ratio_oracle_passes_on_real_gear():
    """assert_gear_ratio is green when the gear propagates the promised ratio."""
    import math

    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_gear_ratio

    with hab.assembly_scratch_session():
        before, rel_id, ja, _jb = _geared_build(ratio=2.0)
        hab.drive_joint(ja, math.radians(25.0))
        after = assembly_state.get_or_404()
        assert abs(assert_gear_ratio(before, after, rel_id, expected_ratio=2.0) - 2.0) <= 0.02


def test_gear_ratio_oracle_fires_when_uncoupled():
    """Red-test: if the driven body did NOT rotate, the oracle raises (the gear
    didn't propagate the ratio)."""
    import math

    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_gear_ratio

    with hab.assembly_scratch_session():
        before, rel_id, ja, jb = _geared_build(ratio=2.0)
        hab.drive_joint(ja, math.radians(25.0))
        after = assembly_state.get_or_404()
        # forcibly revert the driven wheel's transform to its undriven pose
        joint_b = next(j for j in after.joints if j.id == jb)
        driven_id = joint_b.instance_b_id
        undriven = next(i for i in before.instances if i.id == driven_id)
        patched = [undriven if i.id == driven_id else i for i in after.instances]
        broken = after.model_copy(update={"instances": patched})
        with pytest.raises(AssertionError, match="did not propagate"):
            assert_gear_ratio(before, broken, rel_id, expected_ratio=2.0)


def test_gear_ratio_oracle_fires_on_undriven():
    """Red-test: the can-go-red guard raises when nothing was driven at all."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_gear_ratio

    with hab.assembly_scratch_session():
        before, rel_id, _ja, _jb = _geared_build(ratio=2.0)
        after = assembly_state.get_or_404()  # nothing driven
        with pytest.raises(AssertionError, match="nothing was driven"):
            assert_gear_ratio(before, after, rel_id, expected_ratio=2.0)


# ── The gear-ratio oracle GENERALISES to belt-derived relations (AF-9 belts) ────

def test_coverage_report_marks_af9_belt_route_covered():
    """AF-9 belts flipped create_belt_path → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert "create_belt_path" in covered


def _belted_build(*, radius_a: float = 2.0, radius_b: float = 1.0):
    """Active scratch assembly: two pulleys revolute-mated to a base about +Z and
    belt-coupled with the given rim radii.  Returns ``(before_snapshot, belt_rel_id,
    joint_a_id, joint_b_id)`` — ``belt_rel_id`` is the synthetic ``__belt__<id>``."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("Belt")
    hab.add_inline_instance(make_6hb_design(), name="base")
    hab.add_inline_instance(
        make_6hb_design(), name="pulleyA", transform=hab.translation(20.0, 0.0, 0.0))
    hab.add_inline_instance(
        make_6hb_design(), name="pulleyB", transform=hab.translation(40.0, 0.0, 0.0))
    a = assembly_state.get_or_404()
    base_id, wa_id, wb_id = a.instances[0].id, a.instances[1].id, a.instances[2].id
    for label in ("hub_a", "hub_b"):
        hab.add_connector(base_id, label, position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.add_connector(wa_id, "axleA", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.add_connector(wb_id, "axleB", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
    hab.define_mate(wa_id, base_id, child_label="axleA", parent_label="hub_a",
                    joint_type="revolute", axis_direction=[0.0, 0.0, 1.0])
    hab.define_mate(wb_id, base_id, child_label="axleB", parent_label="hub_b",
                    joint_type="revolute", axis_direction=[0.0, 0.0, 1.0])
    a = assembly_state.get_or_404()
    ja, jb = a.joints[0].id, a.joints[1].id
    hab.define_belt(ja, jb, radius_a=radius_a, radius_b=radius_b)
    a = assembly_state.get_or_404()
    return a.model_copy(deep=True), f"__belt__{a.belt_paths[0].id}", ja, jb


def test_gear_ratio_oracle_passes_on_a_real_belt():
    """assert_gear_ratio (handed the belt's synthetic relation id + radius ratio) is
    green when the belt propagates r_a/r_b — pinning the belt→relation synthesis."""
    import math

    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_gear_ratio

    with hab.assembly_scratch_session():
        before, rel_id, ja, _jb = _belted_build(radius_a=2.0, radius_b=1.0)
        hab.drive_joint(ja, math.radians(25.0))
        after = assembly_state.get_or_404()
        assert abs(assert_gear_ratio(before, after, rel_id, expected_ratio=2.0) - 2.0) <= 0.02


def test_belt_ratio_oracle_fires_when_uncoupled():
    """Red-test: if the belt-driven pulley did NOT rotate, the oracle raises."""
    import math

    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_gear_ratio

    with hab.assembly_scratch_session():
        before, rel_id, ja, jb = _belted_build(radius_a=2.0, radius_b=1.0)
        hab.drive_joint(ja, math.radians(25.0))
        after = assembly_state.get_or_404()
        joint_b = next(j for j in after.joints if j.id == jb)
        driven_id = joint_b.instance_b_id
        undriven = next(i for i in before.instances if i.id == driven_id)
        patched = [undriven if i.id == driven_id else i for i in after.instances]
        broken = after.model_copy(update={"instances": patched})
        with pytest.raises(AssertionError, match="did not propagate"):
            assert_gear_ratio(before, broken, rel_id, expected_ratio=2.0)


# ── The polymer-chain oracle PASSES on a real chain and FIRES otherwise ────────

def test_coverage_report_marks_af9_polymerize_route_covered():
    """AF-9 polymerize flipped polymerize_assembly → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert "polymerize_assembly" in covered


def _polymer_build():
    """Active scratch assembly: two identical inline parts mated rigidly (B snapped to
    +10 nm X), then polymerized forward to length 4.  Returns ``(before_snapshot,
    seed_joint_id, after_assembly)``."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    design = make_6hb_design()
    hab.new_assembly("P")
    hab.add_inline_instance(design, name="A")
    hab.add_inline_instance(design, name="B", transform=hab.translation(20.0, 0.0, 0.0))
    a = assembly_state.get_or_404()
    id_a, id_b = a.instances[0].id, a.instances[1].id
    hab.add_connector(id_a, "mate_a", position=[5.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0])
    hab.add_connector(id_b, "mate_b", position=[-5.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0])
    hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
    before = assembly_state.get_or_404().model_copy(deep=True)
    seed_jid = before.joints[0].id
    hab.polymerize(seed_jid, count=4, direction="forward")
    return before, seed_jid, assembly_state.get_or_404().model_copy(deep=True)


def test_polymer_chain_oracle_passes_on_a_real_chain():
    """assert_polymer_chain is green when every copy sits on the seed's delta lattice."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_polymer_chain

    with hab.assembly_scratch_session():
        before, seed_jid, after = _polymer_build()
        assert_polymer_chain(before, after, seed_jid, count=4)


def test_polymer_chain_oracle_fires_on_off_lattice_copy():
    """Red-test: shoving one new copy off the repeat lattice makes the oracle raise."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_polymer_chain

    with hab.assembly_scratch_session():
        before, seed_jid, after = _polymer_build()
        new = next(i for i in after.instances
                   if i.id not in {b.id for b in before.instances})
        moved = new.model_copy(update={"transform": hab.translation(999.0, 0.0, 0.0)})
        broken = after.model_copy(update={
            "instances": [moved if i.id == new.id else i for i in after.instances]
        })
        with pytest.raises(AssertionError, match="repeat"):
            assert_polymer_chain(before, broken, seed_jid, count=4)


def test_polymer_chain_oracle_fires_vacuously_on_stacked_seed():
    """Red-test: if the seed pair is stacked (delta ≈ identity) every copy lands on the
    seed, so the can-go-red guard raises instead of passing vacuously."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_polymer_chain

    with hab.assembly_scratch_session():
        design = make_6hb_design()
        hab.new_assembly("Stacked")
        hab.add_inline_instance(design, name="A")
        hab.add_inline_instance(design, name="B", transform=hab.translation(20.0, 0.0, 0.0))
        a = assembly_state.get_or_404()
        id_a, id_b = a.instances[0].id, a.instances[1].id
        # both connectors at the part origin → the rigid snap stacks B onto A (delta ≈ I)
        hab.add_connector(id_a, "hub", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
        hab.add_connector(id_b, "hub", position=[0.0, 0.0, 0.0], normal=[0.0, 0.0, 1.0])
        hab.define_mate(id_b, id_a, child_label="hub", parent_label="hub")
        before = assembly_state.get_or_404().model_copy(deep=True)
        seed_jid = before.joints[0].id
        hab.polymerize(seed_jid, count=4, direction="forward")
        after = assembly_state.get_or_404()
        with pytest.raises(AssertionError, match="~identity"):
            assert_polymer_chain(before, after, seed_jid, count=4)


# ── The periodic-chain oracle PASSES on a real chain and FIRES otherwise ───────

def test_coverage_report_marks_periodic_polymerize_route_covered():
    """The periodic straggler flipped polymerize_periodic_assembly → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert "polymerize_periodic_assembly" in covered


def _periodic_chain_after():
    """Active scratch assembly: one periodic 2-helix seed part, polymerized forward to
    4 copies.  Returns the after-assembly snapshot."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.test_headless_assembly_build import _periodic_seed_design

    hab.new_assembly("Ring")
    hab.add_inline_instance(_periodic_seed_design(42), name="Seg")
    seed_id = assembly_state.get_or_404().instances[0].id
    hab.polymerize_periodic(seed_id, count=4, direction="forward")
    return assembly_state.get_or_404().model_copy(deep=True)


def test_periodic_chain_oracle_passes_on_a_real_chain():
    """assert_periodic_chain_tiles is green when the derived repeat tiles seamlessly."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_periodic_chain_tiles

    with hab.assembly_scratch_session():
        after = _periodic_chain_after()
        assert_periodic_chain_tiles(after)


def test_periodic_chain_oracle_fires_on_open_seam():
    """Red-test: shoving one copy off the chain opens a seam junction → the oracle raises."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_periodic_chain_tiles

    with hab.assembly_scratch_session():
        after = _periodic_chain_after()
        victim = after.instances[-1]
        moved = victim.model_copy(update={"transform": hab.translation(999.0, 0.0, 0.0)})
        broken = after.model_copy(update={
            "instances": [moved if i.id == victim.id else i for i in after.instances]
        })
        with pytest.raises(AssertionError, match="open|repeating unit"):
            assert_periodic_chain_tiles(broken)


def test_periodic_chain_oracle_fires_on_no_chain():
    """Red-test: a lone un-polymerized periodic seed has no junctions → the
    non-emptiness guard raises (nothing was tiled to prove)."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_periodic_chain_tiles
    from tests.test_headless_assembly_build import _periodic_seed_design

    with hab.assembly_scratch_session():
        hab.new_assembly("Lone")
        hab.add_inline_instance(_periodic_seed_design(42), name="Seg")
        lone = assembly_state.get_or_404()
        with pytest.raises(AssertionError, match="nothing was polymerized"):
            assert_periodic_chain_tiles(lone)


# ── The binding-resolves oracle PASSES on a real binding and FIRES otherwise ───

def test_coverage_report_marks_af9_overhang_binding_routes_covered():
    """AF-9 overhang-bindings flipped create/patch/delete → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert {
        "create_assembly_overhang_binding",
        "patch_assembly_overhang_binding",
        "delete_assembly_overhang_binding",
    } <= covered


def _binding_design(oh_id: str, sequence: str):
    """Part design with one real overhang (auto sub-domain); grid_pos set so
    canonical_topology works."""
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.models import (
        Design, Direction, Domain, Helix, OverhangSpec, Strand, StrandType, Vec3,
    )

    length_bp = 8
    helix_id, strand_id = f"hx_{oh_id}", f"str_{oh_id}"
    helix = Helix(
        id=helix_id, grid_pos=(0, 0),
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=length_bp * BDNA_RISE_PER_BP),
        phase_offset=0.0, length_bp=length_bp,
    )
    direction = Direction.FORWARD if oh_id.endswith("_5p") else Direction.REVERSE
    strand = Strand(
        id=strand_id,
        domains=[Domain(helix_id=helix_id, start_bp=0, end_bp=length_bp - 1,
                        direction=direction, overhang_id=oh_id)],
        strand_type=StrandType.STAPLE,
    )
    ovhg = OverhangSpec(id=oh_id, helix_id=helix_id, strand_id=strand_id,
                        sequence=sequence, label=oh_id)
    return Design(helices=[helix], strands=[strand], overhangs=[ovhg])


def _bound_build():
    """Active scratch assembly with one cross-part overhang binding. Returns
    ``(assembly, binding_id)``."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("Bind")
    hab.add_inline_instance(_binding_design("oh-A_5p", "ACGTACGT"), name="PartA")
    hab.add_inline_instance(_binding_design("oh-B_3p", "GGGGCCCC"), name="PartB",
                            transform=hab.translation(10.0, 0.0, 0.0))
    a = assembly_state.get_or_404()
    ia, ib = a.instances[0], a.instances[1]
    sub_a = ia.source.design.overhangs[0].sub_domains[0].id
    sub_b = ib.source.design.overhangs[0].sub_domains[0].id
    hab.bind_overhangs(
        ia.id, ib.id,
        overhang_a_id="oh-A_5p", sub_domain_a_id=sub_a,
        overhang_b_id="oh-B_3p", sub_domain_b_id=sub_b,
    )
    a = assembly_state.get_or_404()
    return a.model_copy(deep=True), a.overhang_bindings[0].id


def test_binding_resolves_oracle_passes_on_real_binding():
    """assert_binding_resolves is green when both endpoints resolve to live
    sub-domains."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_binding_resolves

    with hab.assembly_scratch_session():
        a, bid = _bound_build()
        assert_binding_resolves(a, bid)


def test_binding_resolves_oracle_fires_on_dropped_subdomain():
    """Red-test: if the binding references a sub-domain that no longer exists on the
    part, the oracle raises (the case canonical_assembly can't see)."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_binding_resolves

    with hab.assembly_scratch_session():
        a, bid = _bound_build()
        # corrupt the stored binding ref to a non-existent sub-domain id
        b = a.overhang_bindings[0].model_copy(update={"sub_domain_a_id": "ghost-sd"})
        broken = a.model_copy(update={"overhang_bindings": [b]})
        with pytest.raises(AssertionError, match="dropped sub-domain"):
            assert_binding_resolves(broken, bid)


def test_binding_resolves_oracle_fires_on_degenerate_self_pair():
    """Red-test: a binding whose two endpoints are the SAME (instance, sub-domain)
    resolves but is degenerate — the non-triviality guard raises."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_binding_resolves

    with hab.assembly_scratch_session():
        a, bid = _bound_build()
        # rewire side B to be identical to side A (still resolves, but degenerate)
        b = a.overhang_bindings[0]
        same = b.model_copy(update={
            "instance_b_id": b.instance_a_id,
            "overhang_b_id": b.overhang_a_id,
            "sub_domain_b_id": b.sub_domain_a_id,
        })
        broken = a.model_copy(update={"overhang_bindings": [same]})
        with pytest.raises(AssertionError, match="sub-domain with itself"):
            assert_binding_resolves(broken, bid)


# ── The mate-coincidence oracle PASSES on a real mate and FIRES otherwise ──────

def _mate_build():
    """Active scratch assembly with one rigid mate between ±5 nm-offset connectors."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("M")
    hab.add_inline_instance(make_6hb_design(), name="A")
    hab.add_inline_instance(
        make_6hb_design(), name="B", transform=hab.translation(20.0, 0.0, 0.0),
    )
    a = assembly_state.get_or_404()
    id_a, id_b = a.instances[0].id, a.instances[1].id
    hab.add_connector(id_a, "mate_a", position=[5.0, 0.0, 0.0], normal=[1.0, 0.0, 0.0])
    hab.add_connector(id_b, "mate_b", position=[-5.0, 0.0, 0.0], normal=[-1.0, 0.0, 0.0])
    hab.define_mate(id_b, id_a, child_label="mate_b", parent_label="mate_a")
    return assembly_state.get_or_404().model_copy(deep=True)


def test_mate_oracle_passes_on_real_mate():
    """assert_mate_coincident is green on a correctly-snapped mate."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_mate_coincident

    with hab.assembly_scratch_session():
        a = _mate_build()
        assert assert_mate_coincident(a, a.joints[0].id) <= 0.01


def test_mate_oracle_fires_on_separated_connectors():
    """If the connectors are not coincident, the oracle raises (green can go red)."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_mate_coincident

    with hab.assembly_scratch_session():
        a = _mate_build()
        moved_b = a.instances[1].model_copy(
            update={"transform": hab.translation(50.0, 0.0, 0.0)}
        )
        broken = a.model_copy(update={"instances": [a.instances[0], moved_b]})
        with pytest.raises(AssertionError, match="not coincident"):
            assert_mate_coincident(broken, a.joints[0].id)


def test_mate_oracle_vacuity_guard_fires_on_stacked_parts():
    """The non-triviality guard raises when both parts sit at the same origin, so
    connector coincidence would be vacuous."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_mate_coincident

    with hab.assembly_scratch_session():
        a = _mate_build()
        # collapse both parts onto the world origin → connectors trivially near
        stacked = [
            inst.model_copy(update={"transform": hab.translation(0.0, 0.0, 0.0)})
            for inst in a.instances
        ]
        degenerate = a.model_copy(update={"instances": stacked})
        with pytest.raises(AssertionError, match="trivial"):
            assert_mate_coincident(degenerate, a.joints[0].id)


# ── The assembly round-trip oracle PASSES on a real build and FIRES otherwise ──

def _inline_assembly():
    """Active scratch assembly: two inline 6hb parts (2nd offset +20 nm in X)."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("T")
    hab.add_inline_instance(make_6hb_design(), name="A")
    hab.add_inline_instance(
        make_6hb_design(), name="B", transform=hab.translation(20.0, 0.0, 0.0),
    )
    return assembly_state.get_or_404().model_copy(deep=True)


def test_assembly_roundtrip_stable_on_clean_build():
    """A well-formed headless assembly survives .nass export→import unchanged."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_assembly_roundtrip_stable

    with hab.assembly_scratch_session():
        reloaded = assert_assembly_roundtrip_stable(_inline_assembly)
        assert len(reloaded.instances) == 2


def _drop_an_instance_roundtrip(assembly):
    """A deliberately buggy round-trip: faithfully reloads, then loses one part.

    Stands in for a real export/import bug (a placement that doesn't survive a
    save).  assert_assembly_roundtrip_stable MUST notice the structure changed.
    """
    from tests.automation_harness import roundtrip_nass

    reloaded = roundtrip_nass(assembly)
    reloaded.instances = reloaded.instances[:-1]  # drop one placed part
    return reloaded


def test_assembly_oracle_catches_corrupted_roundtrip():
    """If the round-trip drops a part, assert_assembly_roundtrip_stable raises."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_assembly_roundtrip_stable

    with hab.assembly_scratch_session():
        with pytest.raises(AssertionError, match="changed the assembly structure"):
            assert_assembly_roundtrip_stable(
                _inline_assembly, roundtrip=_drop_an_instance_roundtrip,
            )


def test_assembly_oracle_catches_invalid_build():
    """If the build itself doesn't validate (missing file source), the oracle
    raises before round-tripping."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_assembly_roundtrip_stable

    def _build_missing_file():
        hab.new_assembly("bad")
        hab.add_file_instance("does/not/exist.nadoc", name="ghost")
        return assembly_state.get_or_404().model_copy(deep=True)

    with hab.assembly_scratch_session():
        with pytest.raises(AssertionError, match="did not validate before round-trip"):
            assert_assembly_roundtrip_stable(_build_missing_file)


# ── The deformation-angle oracle PASSES on a real bend and FIRES otherwise ─────

def _bent_bundle(kappa=2.0, plane_a=20, plane_b=60):
    """Fresh 84-bp bundle bent by κ over [plane_a, plane_b]; returns (design, ref)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
    ref = design_state.get_or_404().helices[0].id
    d = hb.add_bend(plane_a, plane_b, curvature_deg_per_bp=kappa)
    return d, ref


def test_deformation_angle_passes_on_a_real_bend():
    from backend.api import headless_build as hb

    with hb.scratch_session(LatticeType.HONEYCOMB):
        d, ref = _bent_bundle(kappa=2.0)
        got = assert_deformation_angle(d, 20, 60, 80.0, ref_helix_id=ref)
        assert abs(got - 80.0) < 1.0


def test_deformation_angle_fires_on_wrong_expected():
    """Load-bearing red-test: claiming the wrong total angle raises."""
    from backend.api import headless_build as hb

    with hb.scratch_session(LatticeType.HONEYCOMB):
        d, ref = _bent_bundle(kappa=2.0)  # really 80°
        with pytest.raises(AssertionError, match="does not match the request"):
            assert_deformation_angle(d, 20, 60, 120.0, ref_helix_id=ref)


def test_deformation_angle_fires_vacuously_on_an_undeformed_design():
    """Load-bearing red-test: on a straight bundle the oracle hits the can-go-red
    guard (frame barely rotates) instead of passing vacuously."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
        ref = design_state.get_or_404().helices[0].id
        d = design_state.get_or_404()
        with pytest.raises(AssertionError, match="un-deformed"):
            assert_deformation_angle(d, 20, 60, 0.0, ref_helix_id=ref)


# ── The inverse-pair oracle PASSES on a real inverse and FIRES otherwise ───────

def _nick_site(d):
    """A clean FORWARD nick site (helix_id, bp) in a single-domain strand."""
    from backend.core.models import Direction
    for s in d.strands:
        dm = s.domains[0]
        if len(s.domains) == 1 and dm.direction == Direction.FORWARD and dm.end_bp - dm.start_bp >= 4:
            return dm.helix_id, dm.start_bp + (dm.end_bp - dm.start_bp) // 2
    raise AssertionError("no nick site")


def test_inverse_pair_passes_on_nick_then_ligate():
    """nick then ligate is topology-identity — the oracle returns normally."""
    from backend.api import headless_build as hb
    from backend.core.models import Direction, LatticeType
    from tests.automation_harness import assert_inverse_pair
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        start = hb.create_bundle(
            SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB,
        ).model_copy(deep=True)
        h, bp = _nick_site(start)
        assert_inverse_pair(
            start,
            forward=lambda: hb.nick(h, bp, Direction.FORWARD),
            inverse=lambda: hb.ligate(h, bp, Direction.FORWARD),
        )


def test_inverse_pair_fires_when_inverse_does_not_restore():
    """If the 'inverse' leaves the design nicked, the oracle raises (not inverses)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.models import Direction, LatticeType
    from tests.automation_harness import assert_inverse_pair
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        start = hb.create_bundle(
            SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB,
        ).model_copy(deep=True)
        h, bp = _nick_site(start)
        with pytest.raises(AssertionError, match="not inverses"):
            assert_inverse_pair(
                start,
                forward=lambda: hb.nick(h, bp, Direction.FORWARD),
                inverse=lambda: design_state.get_or_404(),  # no-op: stays nicked
            )


def test_inverse_pair_fires_on_vacuous_noop_forward():
    """A forward that doesn't change topology fails the 'must mutate' guard."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.models import LatticeType
    from tests.automation_harness import assert_inverse_pair
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        start = hb.create_bundle(
            SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB,
        ).model_copy(deep=True)
        with pytest.raises(AssertionError, match="did not change the topology"):
            assert_inverse_pair(
                start,
                forward=lambda: design_state.get_or_404(),   # no-op
                inverse=lambda: design_state.get_or_404(),
            )


# ── The geometric-length oracle PASSES on a real change and FIRES otherwise ────

def test_geometric_length_delta_passes_on_a_loop():
    """A loop (+1) is +1 bp of geometry on its helix — the oracle returns normally."""
    from backend.api import headless_build as hb
    from backend.core.models import LatticeType
    from tests.automation_harness import assert_geometric_length_delta
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        d = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB)
        h = d.helices[0]
        start = d.model_copy(deep=True)
        assert_geometric_length_delta(
            start, lambda: hb.loop_skip(h.id, h.bp_start + 14, +1), +1, helix_id=h.id,
        )


def test_geometric_length_delta_fires_on_wrong_expectation():
    """If the actual geometry delta ≠ the declared bp delta, the oracle raises.

    The load-bearing negative test: a loop adds +1 bp, so claiming +2 must fail —
    proving this green can go red (an oracle never seen fail is unproven).
    """
    from backend.api import headless_build as hb
    from backend.core.models import LatticeType
    from tests.automation_harness import assert_geometric_length_delta
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        d = hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB)
        h = d.helices[0]
        start = d.model_copy(deep=True)
        with pytest.raises(AssertionError, match="geometric length changed"):
            assert_geometric_length_delta(
                start, lambda: hb.loop_skip(h.id, h.bp_start + 14, +1), +2, helix_id=h.id,
            )


# ── The deformed-frame oracle PASSES on a bent continuation and FIRES otherwise ─

def _apply_bend(curvature_deg_per_bp: float = 2.0):
    """Bend the active design's middle (planes at bp 20–60). Test scaffolding —
    bend construction has no headless wrapper yet (AF-6)."""
    from backend.api.routes_deformation import AddDeformationBody, add_deformation
    add_deformation(AddDeformationBody(
        type="bend", plane_a_bp=20, plane_b_bp=60,
        params={"kind": "bend", "curvature_deg_per_bp": curvature_deg_per_bp,
                "direction_deg": 0.0},
    ))


def test_on_deformed_frame_passes_on_a_real_deformed_continuation():
    """Build → bend → append onto the bent far end: the new helix sits on the
    deformed frame and is displaced from a straight extrude — oracle returns."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.models import LatticeType
    from tests.automation_harness import assert_on_deformed_frame

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
        ref = design_state.get_or_404().helices[0].id
        _apply_bend()
        before = design_state.get_or_404().model_copy(deep=True)
        after = hb.bundle_deformed_continuation([(0, 0)], 21, source_bp=84, ref_helix_id=ref)
        deflection = assert_on_deformed_frame(before, after, 84, [(0, 0)], ref_helix_id=ref)
        assert deflection > 0.5


def test_on_deformed_frame_fires_when_a_helix_is_off_frame():
    """If a placed helix is moved off the deformed cross-section, the oracle raises.

    The load-bearing negative test — proving this green can go red."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.models import LatticeType
    from tests.automation_harness import assert_on_deformed_frame

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
        ref = design_state.get_or_404().helices[0].id
        _apply_bend()
        before = design_state.get_or_404().model_copy(deep=True)
        after = hb.bundle_deformed_continuation([(0, 0)], 21, source_bp=84, ref_helix_id=ref)
        # Drag the appended helix's start far off the frame.
        new = [h for h in after.helices if h.id not in {x.id for x in before.helices}][0]
        new.axis_start.x += 5.0
        with pytest.raises(AssertionError, match="did not land on the deformed"):
            assert_on_deformed_frame(before, after, 84, [(0, 0)], ref_helix_id=ref)


def test_on_deformed_frame_fires_on_a_straight_continuation():
    """With no bend, the deformed placement equals the straight one — the
    deflection guard fires (the oracle must not pass vacuously)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.models import LatticeType
    from tests.automation_harness import assert_on_deformed_frame

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 0)], 84, lattice=LatticeType.HONEYCOMB, name="B")
        ref = design_state.get_or_404().helices[0].id
        # No bend applied — frame at source_bp is straight.
        before = design_state.get_or_404().model_copy(deep=True)
        after = hb.bundle_deformed_continuation([(0, 0)], 21, source_bp=84, ref_helix_id=ref)
        with pytest.raises(AssertionError, match="had no"):
            assert_on_deformed_frame(before, after, 84, [(0, 0)], ref_helix_id=ref)


# ── AF-10: instance-layout oracles (grid / ring) ──────────────────────────────

def _grid_assembly(rows, cols, *, pitch, row_pitch=None):
    """Active scratch assembly: rows×cols inline 6hb parts on a grid."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("Grid")
    hab.place_grid(make_6hb_design(), rows, cols, pitch=pitch, row_pitch=row_pitch)
    return assembly_state.get_or_404().model_copy(deep=True)


def _ring_assembly(n, *, radius):
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab

    hab.new_assembly("Ring")
    hab.place_ring(make_6hb_design(), n, radius=radius)
    return assembly_state.get_or_404().model_copy(deep=True)


def test_layout_helpers_compose_add_instance():
    """place_grid/place_ring are construction sugar over the (already-covered)
    add_instance route — they wrap no new route, so they intentionally do not move
    the headless-coverage count; the validation gain is the layout oracles below."""
    from backend.api import headless_assembly_build as hab

    assert hasattr(hab, "place_grid") and hasattr(hab, "place_ring")


def test_instances_on_grid_passes_on_a_real_grid():
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_instances_on_grid

    with hab.assembly_scratch_session():
        a = _grid_assembly(2, 3, pitch=15.0, row_pitch=9.0)
        u, v = assert_instances_on_grid(a, 2, 3, pitch=15.0, row_pitch=9.0)
        assert len(u) == 3 and len(v) == 2


def test_instances_on_grid_fires_when_a_part_is_off_lattice():
    """Shoving one part off its cell makes the grid oracle raise (green→red)."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_instances_on_grid

    with hab.assembly_scratch_session():
        a = _grid_assembly(2, 3, pitch=15.0)
        a.instances[0].transform.values[3] += 5.0  # nudge one origin off-grid
        with pytest.raises(AssertionError):
            assert_instances_on_grid(a, 2, 3, pitch=15.0)


def test_instances_on_grid_vacuity_guard():
    """A below-floor pitch trips the non-degeneracy guard."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_instances_on_grid

    with hab.assembly_scratch_session():
        a = _grid_assembly(2, 3, pitch=15.0)
        with pytest.raises(AssertionError, match="non-degeneracy"):
            assert_instances_on_grid(a, 2, 3, pitch=0.0)


def test_instances_on_ring_passes_on_a_real_ring():
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_instances_on_ring

    with hab.assembly_scratch_session():
        a = _ring_assembly(6, radius=20.0)
        radii = assert_instances_on_ring(a, 6, radius=20.0)
        assert len(radii) == 6


def test_instances_on_ring_fires_when_a_part_is_off_ring():
    """Pushing one part off the ring radius makes the oracle raise (green→red)."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_instances_on_ring

    with hab.assembly_scratch_session():
        a = _ring_assembly(6, radius=20.0)
        a.instances[0].transform.values[3] += 5.0  # off the radius
        with pytest.raises(AssertionError, match="off the ring"):
            assert_instances_on_ring(a, 6, radius=20.0)


def test_instances_on_ring_vacuity_guard():
    """radius=0 stacks every part at the centre — the guard fires rather than
    passing vacuously (the load-bearing guard for a ring)."""
    from backend.api import headless_assembly_build as hab
    from tests.automation_harness import assert_instances_on_ring

    with hab.assembly_scratch_session():
        # build a degenerate stacked "ring" and ask the oracle to pass — it must not
        hab.new_assembly("Stack")
        part = make_6hb_design()
        for _ in range(6):
            hab.add_inline_instance(part)  # all at origin
        from backend.api import assembly_state
        a = assembly_state.get_or_404().model_copy(deep=True)
        with pytest.raises(AssertionError, match="non-degeneracy"):
            assert_instances_on_ring(a, 6, radius=0.0)


# ── AF-11: build-spec faithfulness oracle (assert_spec_matches_calls) ──────────

def test_spec_matches_calls_passes_on_a_faithful_build():
    """A 6hb spec build matches the hand-call make_6hb_design()."""
    from backend.api import headless_spec_build as hs
    from tests.automation_harness import assert_spec_matches_calls
    from tests.conftest import SIX_HB_CELLS, make_6hb_design

    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [list(c) for c in SIX_HB_CELLS], "length_bp": 42, "name": "6hb"}]}
    built = assert_spec_matches_calls(
        lambda: hs.build_design(spec), make_6hb_design, kind="design")
    assert len(built.helices) == 6


def test_spec_matches_calls_fires_on_a_divergent_build():
    """If the spec build differs from the hand build, the oracle raises (green→red)."""
    from backend.api import headless_spec_build as hs
    from tests.automation_harness import assert_spec_matches_calls
    from tests.conftest import SIX_HB_CELLS, make_18hb_design

    spec = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [list(c) for c in SIX_HB_CELLS], "length_bp": 42}]}
    with pytest.raises(AssertionError, match="did not produce the same canonical"):
        assert_spec_matches_calls(
            lambda: hs.build_design(spec), make_18hb_design, kind="design")


def test_spec_matches_calls_vacuity_guard():
    """An empty spec build trips the non-emptiness guard rather than passing."""
    from backend.core.models import Design
    from tests.automation_harness import assert_spec_matches_calls

    with pytest.raises(AssertionError, match="empty design"):
        assert_spec_matches_calls(Design, Design, kind="design")


def test_spec_matches_calls_assembly_kind():
    """The assembly kind compares canonical_assembly and guards on instances."""
    from backend.api import assembly_state
    from backend.api import headless_assembly_build as hab
    from backend.api import headless_spec_build as hs
    from tests.automation_harness import assert_spec_matches_calls
    from tests.conftest import SIX_HB_CELLS, make_6hb_design

    beam = {"lattice": "honeycomb", "ops": [
        {"op": "bundle", "cells": [list(c) for c in SIX_HB_CELLS], "length_bp": 42, "name": "6hb"}]}
    spec = {"kind": "assembly", "name": "G", "parts": {"beam": beam},
            "ops": [{"op": "place_grid", "part": "beam", "rows": 2, "cols": 2, "pitch": 10.0}]}

    def hand():
        with hab.assembly_scratch_session():
            hab.new_assembly("G")
            hab.place_grid(make_6hb_design(), 2, 2, pitch=10.0)
            return assembly_state.get_or_404().model_copy(deep=True)

    assert_spec_matches_calls(lambda: hs.build_assembly(spec), hand, kind="assembly")


# ── The cluster-pose oracle PASSES on a real translation and FIRES otherwise ───

def _clustered_posed_design(translation):
    """Active scratch: a 6hb with a 2-helix cluster posed by `translation`.
    Returns (before_snapshot, after_design, cluster_id)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.conftest import SIX_HB_CELLS

    hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
    design = design_state.get_or_404()
    hb.add_cluster("armA", [design.helices[0].id, design.helices[1].id])
    cid = design_state.get_or_404().cluster_transforms[-1].id
    before = design_state.get_or_404().model_copy(deep=True)
    hb.transform_cluster(cid, translation=translation)
    return before, design_state.get_or_404(), cid


def test_cluster_translated_passes_on_a_real_translation():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_cluster_translated

    with hb.scratch_session(LatticeType.HONEYCOMB):
        before, after, cid = _clustered_posed_design([10.0, 0.0, 0.0])
        assert assert_cluster_translated(before, after, cid, translation=[10.0, 0.0, 0.0]) == 2


def test_cluster_translated_fires_when_geometry_did_not_move():
    """Load-bearing red-test: claiming a translation the kernel didn't apply raises."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_cluster_translated

    with hb.scratch_session(LatticeType.HONEYCOMB):
        before, after, cid = _clustered_posed_design([10.0, 0.0, 0.0])
        # really +10 X; asserting +10 Y → the cluster helices fail the shift check
        with pytest.raises(AssertionError, match="did not translate"):
            assert_cluster_translated(before, after, cid, translation=[0.0, 10.0, 0.0])


def test_cluster_translated_vacuity_guard_on_zero_translation():
    """Load-bearing red-test: a ~zero translation trips the can-go-red guard rather
    than passing vacuously (every helix would read as 'unchanged')."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_cluster_translated

    with hb.scratch_session(LatticeType.HONEYCOMB):
        before, after, cid = _clustered_posed_design([10.0, 0.0, 0.0])
        with pytest.raises(AssertionError, match="vacuously"):
            assert_cluster_translated(before, after, cid, translation=[0.0, 0.0, 0.0])


# ── AF-16: the cluster-create feature-log oracle PASSES on a logged creation, FIRES
#    on an unlogged one and on a mismatched helix set ──────────────────────────────

def _logged_cluster_design():
    """Active scratch: a 6hb with a 2-helix cluster created with log=True.
    Returns (design, cluster_id, cluster_helix_ids)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.conftest import SIX_HB_CELLS

    hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
    design = design_state.get_or_404()
    helix_ids = [design.helices[0].id, design.helices[1].id]
    hb.add_cluster("armA", helix_ids, log=True)
    after = design_state.get_or_404()
    return after, after.cluster_transforms[-1].id, helix_ids


def test_cluster_in_feature_log_passes_on_a_logged_creation():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_cluster_in_feature_log

    with hb.scratch_session(LatticeType.HONEYCOMB):
        design, cid, helix_ids = _logged_cluster_design()
        entry = assert_cluster_in_feature_log(design, cid)
        assert entry.feature_type == "cluster_create"
        assert set(entry.helix_ids) == set(helix_ids)


def test_cluster_in_feature_log_fires_when_creation_unlogged():
    """Load-bearing red-test: a cluster created without log=True leaves no entry → the
    oracle raises (the can-go-red guard)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.automation_harness import assert_cluster_in_feature_log
    from tests.conftest import SIX_HB_CELLS

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(SIX_HB_CELLS, 42, lattice=LatticeType.HONEYCOMB, name="6hb")
        design = design_state.get_or_404()
        hb.add_cluster("armA", [design.helices[0].id, design.helices[1].id])  # log=False
        after = design_state.get_or_404()
        cid = after.cluster_transforms[-1].id
        with pytest.raises(AssertionError, match="created without logging"):
            assert_cluster_in_feature_log(after, cid)


def test_cluster_in_feature_log_fires_on_wrong_helix_set():
    """Load-bearing red-test: asserting a helix set that doesn't match the logged entry
    raises — so a build that logged the wrong helices is caught."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_cluster_in_feature_log

    with hb.scratch_session(LatticeType.HONEYCOMB):
        design, cid, helix_ids = _logged_cluster_design()
        with pytest.raises(AssertionError, match="does not match the cluster"):
            assert_cluster_in_feature_log(design, cid, expect_helix_ids=helix_ids[:1])


# ── AF-15 Phase 2: the edge-collinearity oracle PASSES on a real alignment, FIRES
#    when the edges are left skew / on different lines ───────────────────────────

def _two_bars_aligned():
    """Active scratch SQUARE: two 2×3 clusters; align A's axial edge onto B's, then
    return (design, a_id, b_id, src_edge, target_edge)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    hb.create_bundle(
        [(r, c) for r in range(2) for c in range(6)],
        32, lattice=LatticeType.SQUARE, name="grid",
    )
    d = design_state.get_or_404()
    cols = {h.id: h.grid_pos[1] for h in d.helices if h.grid_pos}
    hb.add_cluster("A", [h for h, c in cols.items() if c <= 2])
    a = design_state.get_or_404().cluster_transforms[-1].id
    hb.add_cluster("B", [h for h, c in cols.items() if c >= 3])
    b = design_state.get_or_404().cluster_transforms[-1].id
    src, tgt = ("w", 1, 1), ("w", -1, 1)
    hb.align_cluster_edge(a, src, target_edge=(b, tgt))
    return design_state.get_or_404(), a, b, src, tgt


def test_edges_collinear_passes_on_a_real_alignment():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_edges_collinear

    with hb.scratch_session(LatticeType.SQUARE):
        d, a, b, src, tgt = _two_bars_aligned()
        ang = assert_edges_collinear(d, a, src, target_edge=(b, tgt))
        assert ang < 1.0


def test_edges_collinear_fires_when_edges_left_skew():
    """Load-bearing red-test: WITHOUT running the solver the two bars' edges are
    parallel but on different lines → the on-line assertion raises."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.automation_harness import assert_edges_collinear

    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(
            [(r, c) for r in range(2) for c in range(6)],
            32, lattice=LatticeType.SQUARE, name="grid",
        )
        d = design_state.get_or_404()
        cols = {h.id: h.grid_pos[1] for h in d.helices if h.grid_pos}
        hb.add_cluster("A", [h for h, c in cols.items() if c <= 2])
        a = design_state.get_or_404().cluster_transforms[-1].id
        hb.add_cluster("B", [h for h, c in cols.items() if c >= 3])
        b = design_state.get_or_404().cluster_transforms[-1].id
        # no align_cluster_edge → A and B sit apart in X
        with pytest.raises(AssertionError, match="off the target line"):
            assert_edges_collinear(design_state.get_or_404(), a, ("w", 1, 1),
                                   target_edge=(b, ("w", -1, 1)))


def test_edges_collinear_fires_on_wrong_direction():
    """Load-bearing red-test: aligning to one line then checking against a line at a
    different angle raises the parallelism assertion."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.automation_harness import assert_edges_collinear

    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(
            [(r, c) for r in range(2) for c in range(6)],
            32, lattice=LatticeType.SQUARE, name="grid",
        )
        d = design_state.get_or_404()
        hb.add_cluster("bar", [h.id for h in d.helices])
        cid = design_state.get_or_404().cluster_transforms[-1].id
        src = ("w", 1, 1)
        # align onto a Z-ish line, then check against a 45° line → not collinear
        hb.align_cluster_edge(cid, src, target_line=([4.0, 0.0, 0.0], [0.0, 0.0, 1.0]))
        with pytest.raises(AssertionError, match="not collinear"):
            assert_edges_collinear(design_state.get_or_404(), cid, src,
                                   target_line=([4.0, 0.0, 0.0], [1.0, 0.0, 1.0]))


# ── assert_joint_on_hull_corner (AF-14 Phase 1) ───────────────────────────────

def _bar_with_joint(*, edge=None, corner=None, face=None):
    """Active scratch SQUARE: a 2×6 bar clustered whole, with one joint placed on the
    named OBB feature; return (design, cluster_id, joint_id)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    hb.create_bundle(
        [(r, c) for r in range(2) for c in range(6)],
        32, lattice=LatticeType.SQUARE, name="grid",
    )
    d = design_state.get_or_404()
    hb.add_cluster("bar", [h.id for h in d.helices])
    cid = design_state.get_or_404().cluster_transforms[-1].id
    hb.place_cluster_joint(cid, edge=edge, corner=corner, face=face)
    d = design_state.get_or_404()
    return d, cid, d.cluster_joints[-1].id


def test_joint_on_hull_corner_passes_on_a_real_edge_placement():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_joint_on_hull_corner

    with hb.scratch_session(LatticeType.SQUARE):
        d, _cid, jid = _bar_with_joint(edge=("w", 1, 1))
        ang = assert_joint_on_hull_corner(d, jid, edge=("w", 1, 1))
        assert ang < 1.0


def test_joint_on_hull_corner_passes_on_a_real_corner_placement():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_joint_on_hull_corner

    with hb.scratch_session(LatticeType.SQUARE):
        d, _cid, jid = _bar_with_joint(corner=(1, 1, 1), face=("w", 1))
        assert_joint_on_hull_corner(d, jid, corner=(1, 1, 1), face=("w", 1))


def test_joint_on_hull_corner_fires_on_a_different_edge():
    """Load-bearing red-test: a joint placed on edge (w,+1,+1) is parallel to but offset
    from edge (w,-1,+1) → the on-line assertion raises."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_joint_on_hull_corner

    with hb.scratch_session(LatticeType.SQUARE):
        d, _cid, jid = _bar_with_joint(edge=("w", 1, 1))
        with pytest.raises(AssertionError, match="off the joint axis line"):
            assert_joint_on_hull_corner(d, jid, edge=("w", -1, 1))


def test_joint_on_hull_corner_fires_on_a_different_corner():
    """Load-bearing red-test: a joint at corner (+1,+1,+1) does not pass through corner
    (-1,+1,+1) → the through-corner assertion raises."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_joint_on_hull_corner

    with hb.scratch_session(LatticeType.SQUARE):
        d, _cid, jid = _bar_with_joint(corner=(1, 1, 1), face=("w", 1))
        with pytest.raises(AssertionError, match="from corner"):
            assert_joint_on_hull_corner(d, jid, corner=(-1, 1, 1), face=("w", 1))


# ── assert_range_of_motion (AF-14 Phase 2) ────────────────────────────────────

def _lone_bar():
    """Active scratch SQUARE: a 2×6 bar clustered whole; return (design, cluster_id)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    hb.create_bundle(
        [(r, c) for r in range(2) for c in range(6)],
        32, lattice=LatticeType.SQUARE, name="grid",
    )
    d = design_state.get_or_404()
    hb.add_cluster("bar", [h.id for h in d.helices])
    return design_state.get_or_404(), design_state.get_or_404().cluster_transforms[-1].id


def test_range_of_motion_passes_on_lone_cluster_full_swing():
    from backend.api import headless_build as hb
    from backend.core.cluster_obb import hull_prism_axis
    from tests.automation_harness import assert_range_of_motion

    with hb.scratch_session(LatticeType.SQUARE):
        d, cid = _lone_bar()
        axis = hull_prism_axis(d, cid, edge=("w", 1, 1))
        rom = assert_range_of_motion(d, cid, axis, 360.0)
        assert abs(rom - 360.0) < 2.0


def test_range_of_motion_fires_on_wrong_angle():
    """Load-bearing red-test: a free 360° swing is not 180° → the oracle raises."""
    from backend.api import headless_build as hb
    from backend.core.cluster_obb import hull_prism_axis
    from tests.automation_harness import assert_range_of_motion

    with hb.scratch_session(LatticeType.SQUARE):
        d, cid = _lone_bar()
        axis = hull_prism_axis(d, cid, edge=("w", 1, 1))
        with pytest.raises(AssertionError, match="expected"):
            assert_range_of_motion(d, cid, axis, 180.0)


def test_range_of_motion_obstacle_reduces_swing():
    """The second can-go-red guard: a neighbour in the swing path drops ROM below the
    full limit, so claiming the full 360° raises while the true (reduced) value passes."""
    import numpy as np

    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.core.cluster_obb import (
        cluster_obb,
        cluster_range_of_motion,
        hull_prism_axis,
    )
    from tests.automation_harness import assert_range_of_motion

    with hb.scratch_session(LatticeType.SQUARE):
        hb.create_bundle(
            [(r, c) for r in range(2) for c in range(6)],
            32, lattice=LatticeType.SQUARE, name="grid",
        )
        d = design_state.get_or_404()
        hb.add_cluster("A", [h.id for h in d.helices if h.grid_pos and h.grid_pos[1] <= 2])
        a = design_state.get_or_404().cluster_transforms[-1].id
        hb.add_cluster("B", [h.id for h in d.helices if h.grid_pos and h.grid_pos[1] >= 3])
        b = design_state.get_or_404().cluster_transforms[-1].id

        d = design_state.get_or_404()
        sep = cluster_obb(d, b).center - cluster_obb(d, a).center
        sep_u = sep / np.linalg.norm(sep)
        hb.transform_cluster(b, translation=(sep_u * 2).tolist(),
                             rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
        d = design_state.get_or_404()

        obb_a = cluster_obb(d, a)
        # hinge on the interface edge nearest B → one swing sense drives A's bulk into B
        best, best_d = None, 1e30
        for key in [("w", s1, s2) for s1 in (-1, 1) for s2 in (-1, 1)]:
            p_lo, p_hi = obb_a.edge_endpoints(key)
            dist = float(np.linalg.norm((p_lo + p_hi) / 2 - cluster_obb(d, b).center))
            if dist < best_d:
                best, best_d = key, dist
        axis = hull_prism_axis(d, a, edge=best)

        rom = cluster_range_of_motion(d, a, axis)
        assert rom < 360.0, "B should reduce A's swing"
        assert_range_of_motion(d, a, axis, rom)  # the true reduced value passes
        with pytest.raises(AssertionError, match="expected"):
            assert_range_of_motion(d, a, axis, 360.0)  # claiming a free swing fails


def test_coverage_report_marks_af14_route_covered():
    """AF-14 Phase 1 flipped POST /design/cluster/{id}/joint (add_joint) → covered."""
    report = headless_coverage_report()
    covered = {r["endpoint"] for r in report["covered_routes"]}
    assert "add_joint" in covered


# ── assert_parallelogram_linkage (the 4-bar capstone oracle) ──────────────────

def test_parallelogram_oracle_passes_on_a_real_mechanism():
    """The oracle accepts a genuinely-built headless 4-bar parallelogram."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_parallelogram_linkage
    from tests.test_parallelogram_linkage import build_parallelogram

    with hb.scratch_session(LatticeType.SQUARE):
        design, bar_ids, joint_ids = build_parallelogram()
        out = assert_parallelogram_linkage(design, bar_ids, joint_ids=joint_ids)
        assert out["mobility"] == 1
        assert len(out["joint_roms"]) == 4


def test_parallelogram_oracle_red_on_wrong_joint_count():
    """Load-bearing can-go-red: 3 joints on a 4-link mechanism → Grübler mobility 3,
    not 1, so the oracle raises (the mobility check is real, not cosmetic)."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_parallelogram_linkage
    from tests.test_parallelogram_linkage import build_parallelogram

    with hb.scratch_session(LatticeType.SQUARE):
        design, bar_ids, joint_ids = build_parallelogram()
        with pytest.raises(AssertionError, match="mobility"):
            assert_parallelogram_linkage(
                design, bar_ids, joint_ids=joint_ids[:3], require_movable=False,
            )


def test_parallelogram_oracle_red_on_unarranged_bars():
    """Load-bearing can-go-red: if a bar is never aligned (left in the grid), the bars
    don't meet at shared corners → the closure assertion raises."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.automation_harness import assert_parallelogram_linkage
    from tests.test_parallelogram_linkage import build_parallelogram

    with hb.scratch_session(LatticeType.SQUARE):
        # build a full parallelogram, then shove one bar far away → loop no longer closes
        design, bar_ids, joint_ids = build_parallelogram()
        hb.transform_cluster(bar_ids[2], translation=[100.0, 100.0, 100.0],
                             rotation=[0, 0, 0, 1], pivot=[0, 0, 0])
        design = design_state.get_or_404()
        with pytest.raises(AssertionError, match="shared corner|parallel|degenerate"):
            assert_parallelogram_linkage(
                design, bar_ids, joint_ids=joint_ids, require_movable=False,
            )


# ── assert_recommended_hinge (AF-14 Phase 3) ──────────────────────────────────

def _recommend_bar():
    """Active scratch SQUARE: a 2×6 bar clustered whole; return (design, cluster_id)."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    hb.create_bundle(
        [(r, c) for r in range(2) for c in range(6)],
        32, lattice=LatticeType.SQUARE, name="grid",
    )
    d = design_state.get_or_404()
    hb.add_cluster("bar", [h.id for h in d.helices])
    return design_state.get_or_404(), design_state.get_or_404().cluster_transforms[-1].id


def test_recommended_hinge_passes_on_a_real_bar():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_recommended_hinge

    with hb.scratch_session(LatticeType.SQUARE):
        d, cid = _recommend_bar()
        top = assert_recommended_hinge(d, cid)
        assert not top["is_axial"]


def test_recommended_hinge_red_on_axial_edge_on_top():
    """Load-bearing red-test: a hand-built list with an axial (w) edge wrongly ranked #1
    → the non-axial check raises."""
    from backend.api import headless_build as hb
    from backend.core.cluster_obb import recommend_hinge_joints
    from tests.automation_harness import assert_recommended_hinge

    with hb.scratch_session(LatticeType.SQUARE):
        d, cid = _recommend_bar()
        recs = recommend_hinge_joints(d, cid)
        axial = next(c for c in recs if c["edge"][0] == "w")
        mangled = [axial] + [c for c in recs if c is not axial]
        with pytest.raises(AssertionError, match="axial"):
            assert_recommended_hinge(d, cid, recommendations=mangled)


def test_recommended_hinge_red_on_midpoint_anchor():
    """Load-bearing red-test: a top candidate anchored at the edge MIDPOINT (not a
    corner) → the corner-anchor check raises."""
    from backend.api import headless_build as hb
    from backend.core.cluster_obb import recommend_hinge_joints
    from tests.automation_harness import assert_recommended_hinge

    with hb.scratch_session(LatticeType.SQUARE):
        d, cid = _recommend_bar()
        midpoint_recs = recommend_hinge_joints(d, cid, anchor="midpoint")
        with pytest.raises(AssertionError, match="corner-anchored"):
            assert_recommended_hinge(d, cid, recommendations=midpoint_recs)


# ── The full-sequencing oracle PASSES on a sequenced design and FIRES otherwise ─

def _routed_sequenced_6hb():
    """Active scratch design: a 6hb auto-scaffolded to one strand and fully
    sequenced (scaffold + WC staples).  Returns the sequenced design copy."""
    from backend.api import headless_build as hb

    hb.create_bundle(
        [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)], 42,
        lattice=LatticeType.HONEYCOMB, name="6hb")
    hb.auto_scaffold()
    return hb.full_sequence()


def test_fully_sequenced_oracle_passes_on_sequenced_design():
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_fully_sequenced

    with hb.scratch_session(LatticeType.HONEYCOMB):
        sequenced = _routed_sequenced_6hb()
        assert assert_fully_sequenced(sequenced) > 0


def test_fully_sequenced_oracle_fires_on_unsequenced_design():
    """Red-test: a routed-but-unsequenced design trips the undefined-base guard."""
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from tests.automation_harness import assert_fully_sequenced

    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(
            [(0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (2, 1)], 42,
            lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold()
        unsequenced = design_state.get_or_404()
        with pytest.raises(AssertionError, match="undefined"):
            assert_fully_sequenced(unsequenced)


def test_fully_sequenced_oracle_fires_on_wrong_complement():
    """Red-test: a staple base that is NOT the scaffold's WC complement raises."""
    from backend.api import headless_build as hb
    from tests.automation_harness import assert_fully_sequenced

    with hb.scratch_session(LatticeType.HONEYCOMB):
        sequenced = _routed_sequenced_6hb()
        # Corrupt one staple's sequence to a definite-but-wrong base (no 'N', so the
        # undefined guard passes and the WC guard is the one that must fire).
        staples = [s for s in sequenced.strands if s.strand_type == StrandType.STAPLE]
        target = staples[0]
        bad = "A" * len(target.sequence or "")
        patched = [s.model_copy(update={"sequence": bad}) if s.id == target.id else s
                   for s in sequenced.strands]
        broken = sequenced.model_copy(update={"strands": patched})
        with pytest.raises(AssertionError, match="WC complement"):
            assert_fully_sequenced(broken)


# ── assert_spec_constraints_reported (AF-13 P3 → grammar) ──────────────────────
# Pure oracle tests: the verdict dicts are fabricated (the shape check_relaxed_constraint
# returns), so these pin the comparison logic without an oxDNA run.

def _verdict(status="met", met=True, measured=4.2):
    return {"met": met, "status": status, "measured_nm": measured, "target_nm": 4.0,
            "tol_nm": 1.0, "n_frames": 60, "min_confidence": 50, "confidence": {}}


def test_spec_constraints_reported_passes_on_matching_verdicts():
    from tests.automation_harness import assert_spec_constraints_reported
    spec_result = {"design": object(), "verdicts": [_verdict(), _verdict("unmet", False, 9.0)]}
    hand = [_verdict(), _verdict("unmet", False, 9.0)]
    assert assert_spec_constraints_reported(spec_result, hand) == spec_result["verdicts"]


def test_spec_constraints_reported_fires_on_status_mismatch():
    """Red-test: the grammar reporting a different status than the hand check raises
    (e.g. a landmark resolved to the wrong helix flipping met→unmet)."""
    from tests.automation_harness import assert_spec_constraints_reported
    spec_result = {"verdicts": [_verdict("met", True, 4.2)]}
    with pytest.raises(AssertionError, match="different verdict"):
        assert_spec_constraints_reported(spec_result, [_verdict("unmet", False, 9.0)])


def test_spec_constraints_reported_fires_on_measured_divergence():
    """Red-test: same status but a divergent measured value (a landmark resolved to
    the wrong helix) raises."""
    from tests.automation_harness import assert_spec_constraints_reported
    spec_result = {"verdicts": [_verdict("met", True, 4.2)]}
    with pytest.raises(AssertionError, match="wrong helix"):
        assert_spec_constraints_reported(spec_result, [_verdict("met", True, 6.8)])


def test_spec_constraints_reported_fires_on_count_mismatch():
    """Red-test: a dropped constraint (fewer verdicts than the hand build) raises."""
    from tests.automation_harness import assert_spec_constraints_reported
    spec_result = {"verdicts": [_verdict()]}
    with pytest.raises(AssertionError, match="count mismatch"):
        assert_spec_constraints_reported(spec_result, [_verdict(), _verdict()])


def test_spec_constraints_reported_vacuity_guard():
    """Red-test: an empty verdict list (a spec with no constraints block) would pass
    vacuously — the non-vacuity guard fires instead."""
    from tests.automation_harness import assert_spec_constraints_reported
    with pytest.raises(AssertionError, match="no constraint verdicts"):
        assert_spec_constraints_reported({"verdicts": []}, [])


# ── AF-21: assert_oxpy_equilibrium_parity (GPU-free, hand-built result dicts) ─────

def _parity_result(*, align=14.0, rg=5.0, bp=0.5, conf=4, mut_followed=True):
    """A run_live_field-shaped result dict for oracle unit tests."""
    return {
        "observables": {"alignment_nm": align, "radius_of_gyration_nm": rg,
                        "bp_retention": bp},
        "confidence": conf,
        "mutation": {
            "from_dir": [0, 0, 1], "to_dir": [1, 0, 0],
            "proj_on_to_before_nm": 0.0,
            "proj_on_to_after_nm": align if mut_followed else 0.0,
            "followed": mut_followed,
        },
    }


def test_oxpy_parity_oracle_passes():
    """Matching equilibria + a steering re-aim → the oracle passes and reports the
    deltas + followed flag."""
    from tests.automation_harness import assert_oxpy_equilibrium_parity
    live = _parity_result()
    batch = _parity_result(); batch["mutation"] = None
    r = assert_oxpy_equilibrium_parity(live, batch, tol_nm=0.5, bp_tol=0.02)
    assert r["followed"] is True
    assert r["alignment_delta_nm"] == 0.0


def test_oxpy_parity_oracle_fires_on_divergence():
    """Red-test: a live equilibrium far from batch raises the divergence clause."""
    from tests.automation_harness import assert_oxpy_equilibrium_parity
    live = _parity_result(align=14.0)
    batch = _parity_result(align=20.0); batch["mutation"] = None
    with pytest.raises(AssertionError, match="DIVERGED"):
        assert_oxpy_equilibrium_parity(live, batch, tol_nm=0.5)


def test_oxpy_parity_oracle_fires_on_dead_field():
    """Red-test: a field re-aim that does not move the body raises the steering
    clause (the 'dead field vector mutation' guard)."""
    from tests.automation_harness import assert_oxpy_equilibrium_parity
    live = _parity_result(mut_followed=False)
    batch = _parity_result(); batch["mutation"] = None
    with pytest.raises(AssertionError, match="did NOT steer"):
        assert_oxpy_equilibrium_parity(live, batch)


def test_oxpy_parity_oracle_fires_on_low_confidence():
    """Red-test: too few bursts/frames is inconclusive (the confidence gate)."""
    from tests.automation_harness import assert_oxpy_equilibrium_parity
    live = _parity_result(conf=1)
    batch = _parity_result(conf=1); batch["mutation"] = None
    with pytest.raises(AssertionError, match="INCONCLUSIVE"):
        assert_oxpy_equilibrium_parity(live, batch, min_confidence=2)
