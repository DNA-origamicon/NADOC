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

    AF-6 covered POST /design/deformation, so this re-points to /design/cluster
    (cluster construction, a later AF candidate) — still unwrapped today.
    """
    report = headless_coverage_report()
    covered_paths = {r["path"] for r in report["covered_routes"]}
    uncovered_paths = {r["path"] for r in report["uncovered_routes"]}
    assert any(p.endswith("/design/cluster") for p in uncovered_paths)
    assert not any(p.endswith("/design/cluster") for p in covered_paths)


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
